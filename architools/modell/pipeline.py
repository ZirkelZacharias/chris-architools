"""Werkzeug „Gelände-Modell“: Daten -> Schichten -> Laser-PDF, Druck-STL, Montageplan.

Ablauf in zwei Stufen:
  1. eine *Szene* laden (aus Einzeldateien oder aus einem IFCmap-Projekt)
  2. aus der Szene das physische Modell bauen
"""
import csv
import os
import re
import time

import numpy as np
import shapely

from . import bibliothek as BIB
from . import blatt as BL
from . import buildings as B
from . import geo_io as G
from . import laser as L
from . import report as R
from . import terrain as T
from .geomutil import polys, world_to_model


def mm(t):
    """Stärke für Dateinamen und Texte: 2.0 -> 2, 1.5 -> 1,5"""
    return f"{float(t):g}".replace(".", ",")


def _safe(s):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(s))[:60]


def _height_getter(field, default):
    def h(attrs):
        if field and field in attrs:
            try:
                v = float(attrs[field])
                if v > 0:
                    return v
            except (TypeError, ValueError):
                pass
        return float(default)
    return h


def schichtdicke(cfg):
    lc = cfg["laser"]
    for k in ("staerke_gemessen_mm", "staerke_mm"):
        v = lc.get(k)
        if v not in (None, "", 0):
            return float(v)
    return float(cfg["gelaende"].get("schichtdicke_mm", 2.0))


def rahmen(cfg):
    """(Mitte, Breite m, Höhe m, Drehung °) aus Modellgröße in cm, Maßstab und Drehung."""
    g = cfg["gebiet"]
    s = float(cfg["massstab"])
    return (tuple(g["mitte_en"]), float(g["breite_cm"]) * s / 100.0, float(g["hoehe_cm"]) * s / 100.0,
            float(g.get("drehung_grad") or 0.0))


def _bbox_rahmen(r):
    """Achsparalleles Rechteck, das den gedrehten Rahmen umschließt -> (Mitte, Breite, Höhe)."""
    from .geomutil import rahmen_polygon
    (e, n), b, h, d = r
    x0, y0, x1, y1 = rahmen_polygon(e, n, b, h, d).bounds
    return ((x0 + x1) / 2, (y0 + y1) / 2), x1 - x0, y1 - y0


def szene_laden(cfg, log=print):
    """Szene je nach Datenquelle: automatisch aus Koordinaten, IFCmap-Projekt oder eigene Dateien."""
    from .config import resolve_paths
    resolve_paths(cfg)
    q = cfg.get("quelle", "auto")
    r = rahmen(cfg)
    if q in ("auto", "ifcmap"):
        from . import ifcmap_adapter as A
        if q == "auto":
            sz = A.szene_aus_koordinaten(cfg, _bbox_rahmen(r), log)
            sz["rahmen"] = r
            return sz
        if cfg["ifcmap"].get("rahmen", "karte") == "karte":
            sz = A.szene_aus_ifcmap(cfg, log, _bbox_rahmen(r))
            sz["rahmen"] = r
            return sz
        return A.szene_aus_ifcmap(cfg, log, None)
    if not cfg.get("ausschnitt_datei"):
        (e, n), b, h = _bbox_rahmen(r)
        cfg["ausschnitt"] = {"xmin": e - b / 2, "ymin": n - h / 2, "xmax": e + b / 2, "ymax": n + h / 2}
        sz = szene_aus_dateien(cfg, log)
        sz["rahmen"] = r
        return sz
    return None


# ------------------------------------------------------------------ Szene aus Dateien
def szene_aus_dateien(cfg, log=print):
    sz = {"quelle": "Dateien"}
    sz["extent"] = G.load_extent(cfg, log)
    sz["dgm"] = G.load_dgm(cfg["dgm"]["datei"], sz["extent"].bounds, log=log)
    gc = cfg["gebaeude"]
    sz["gebaeude"] = G.read_citygml(gc["citygml"], sz["extent"].bounds, log) if gc.get("citygml") else []
    sz["bloecke"] = []
    if gc.get("grundriss_datei"):
        items = G.read_vector(gc["grundriss_datei"], gc.get("grundriss_layer", ""), sz["extent"].bounds, log)
        sz["bloecke"].append({"items": items, "art": "Gebäude", "ergaenzen": True,
                              "hoehe": _height_getter(gc.get("hoehe_feld"), gc["standard_hoehe_m"]), "breite_m": 0})
    for bw in cfg.get("bauwerke", []):
        if bw.get("datei"):
            items = G.read_vector(bw["datei"], bw.get("layer", ""), sz["extent"].bounds, log)
            sz["bloecke"].append({"items": items, "art": bw.get("name", "Bauwerk"), "ergaenzen": False,
                                  "hoehe": _height_getter(bw.get("hoehe_feld"), bw.get("hoehe_m", 1.0)),
                                  "breite_m": float(bw.get("breite_m") or 0)})
    sz["ebenen"] = []
    for m in cfg.get("markierungen", []):
        if not m.get("datei"):
            continue
        items = G.read_vector(m["datei"], m.get("layer", ""), sz["extent"].bounds, log)
        sz["ebenen"].append({"name": m.get("name") or os.path.basename(m["datei"]), "items": items,
                             "aktion": _akt(m.get("aktion", "ritzen")), "d": float(m.get("punkt_d_mm") or 1.5),
                             "breite_m": float(m.get("breite_m") or 0)})
        log(f"  {sz['ebenen'][-1]['name']}: {len(items)} Objekte")
    return sz


def einsatz_polygon(cfg, szene, log=print):
    """Projektgrundstück (Weltkoordinaten): aus der Szene (IFCmap) oder das Flurstück der Datei,
    auf dem der Mittelpunkt liegt."""
    ec = cfg["einsatz"]
    if not ec.get("aktiv"):
        return None
    if ec.get("auswahl") == "eigen" and ec.get("polygone_en"):
        from shapely.geometry import Polygon as _P
        g = shapely.union_all([shapely.make_valid(_P(r)) for r in ec["polygone_en"] if len(r) >= 3])
        if not g.is_empty:
            log(f"  Einsatz: eigene Auswahl, {g.area:.0f} m²")
            return g
    if szene.get("grundstueck") is not None:
        return szene["grundstueck"]
    if not ec.get("flurstuecke_datei"):
        log("  WARNUNG: Einsatz übersprungen – kein Flurstück verfügbar (ALKIS nicht erreichbar und keine "
            "Flurstücks-Datei angegeben)")
        return None
    ext = szene["extent"]
    mitte = ec.get("mitte") or [ext.centroid.x, ext.centroid.y]
    pt = shapely.Point(*mitte)
    kand = [g for g, _ in G.read_vector(ec["flurstuecke_datei"], ec.get("layer", ""), ext.bounds, log)
            if "Polygon" in g.geom_type]
    treffer = [g for g in kand if g.contains(pt)]
    if not treffer:
        if not kand:
            raise ValueError("Einsatz: keine Flurstücke im Ausschnitt gefunden")
        treffer = [min(kand, key=lambda g: g.distance(pt))]
        log("  Hinweis: Mittelpunkt liegt in keinem Flurstück – nächstes Flurstück genommen")
    g = max(treffer, key=lambda g: g.area)
    log(f"  Projektgrundstück: {g.area:.0f} m²")
    return g


def _akt(a):
    return {"gravieren": "gravieren", "gravieren (Fläche)": "gravieren", "ritzen": "ritzen",
            "schneiden": "schneiden", "aus": "aus"}.get(a, "ritzen")


# ------------------------------------------------------------------ Modell bauen
def run(cfg, log=print, szene=None, laser=True, druck=True):
    """Kompletter Lauf. Ohne szene wird aus den Dateien im Projekt geladen. laser/druck: nur das Gewuenschte rechnen und schreiben."""
    from .config import resolve_paths
    t0 = time.time()
    cfg = resolve_paths(cfg)
    out = os.path.abspath(cfg["ausgabe_ordner"])
    d_laser = os.path.join(out, "laser")
    d_druck = os.path.join(out, "druck")
    d_einzel = os.path.join(d_druck, "einzeln")
    for d in (d_laser, d_druck, d_einzel):
        os.makedirs(d, exist_ok=True)
    name = _safe(cfg["projekt_name"])
    t = schichtdicke(cfg)
    cfg["gelaende"]["schichtdicke_mm"] = t
    formate = BIB.plattenformate(cfg)
    sorte, st, hinweise = BIB.material(cfg)
    for h in hinweise:
        log("  WARNUNG: " + h)
    log(f"Material: {sorte} {mm(t)} mm · Platte {formate[0][0]:.0f} × {formate[0][1]:.0f} mm")

    scale = float(cfg["massstab"])
    f = 1000.0 / scale
    log("1/6  Daten laden")
    if szene is None:
        szene = szene_aus_dateien(cfg, log)
    if szene.get("rahmen") is not None:                 # Rahmen aus der Karte (auch gedreht)
        from .geomutil import rahmen_polygon, rahmen_transform
        (ce, cn), rb, rh, dreh = szene["rahmen"]
        extent_w = rahmen_polygon(ce, cn, rb, rh, dreh)
        to_model, tm_xy, tw_xy = rahmen_transform(ce, cn, rb, rh, dreh, f)
        modell_b, modell_h = rb * f, rh * f
        if dreh:
            log(f"  Rahmen um {dreh:g}° gedreht")
    else:
        extent_w = szene["extent"]
        x0, y0, x1, y1 = extent_w.bounds
        to_model = world_to_model(x0, y0, f)
        tm_xy = lambda xy: (np.asarray(xy, float)[:, :2] - [x0, y0]) * f
        tw_xy = lambda xy: np.asarray(xy, float)[:, :2] / f + [x0, y0]
        modell_b, modell_h = (x1 - x0) * f, (y1 - y0) * f
    cfg["_tm_xy"], cfg["_tw_xy"], cfg["_extent_world"] = tm_xy, tw_xy, extent_w
    extent_m = to_model(extent_w)
    log(f"  Modellgröße {modell_b:.0f} × {modell_h:.0f} mm bei 1:{scale:.0f}")

    log("2/6  Geländeschichten")
    P, info = T.build_levels(szene["dgm"], extent_w, to_model, scale, cfg["gelaende"], cfg["dgm"], log)

    log("3/6  Gebäude und Bauwerke")
    blds = []
    if szene.get("gebaeude"):
        blds += B.build_buildings(szene["gebaeude"], extent_m, f, P, cfg, log)
    for bl in szene.get("bloecke", []):
        items = bl["items"]
        if bl.get("ergaenzen") and blds:
            known = shapely.union_all([b["footprint"] for b in blds])
            items = [(g, a) for g, a in items if to_model(g).intersection(known).area < 0.5 * to_model(g).area]
        new = B.build_blocks_from_footprints(items, to_model, extent_m, f, P, cfg, bl["art"], bl["hoehe"],
                                             bl.get("breite_m", 0))
        log(f"  {bl['art']}: {len(new)} als Blöcke")
        blds += new
    B.number_buildings(blds)

    feats = []
    for e in szene.get("ebenen", []):
        if e["aktion"] == "aus":
            continue
        bw = float(e.get("breite_m") or 0)
        for g, _a in e["items"]:
            tt = g.geom_type
            typ = "punkt" if "Point" in tt else "flaeche" if "Polygon" in tt else "linie"
            if typ == "linie" and bw > 0 and e["aktion"] != "gravieren":
                g, typ = g.buffer(bw / 2.0, cap_style="flat"), "flaeche"
            gm = to_model(g).intersection(extent_m)
            if gm.is_empty:
                continue
            feats.append({"name": e["name"], "geom": gm, "typ": typ, "aktion": e["aktion"],
                          "d": float(e.get("d") or 1.5), "breite_mm": bw * f})

    # Projektgrundstück als Einsatz
    E_w = einsatz_polygon(cfg, szene, log)
    parts_e, blds_in, P_haupt, stuetzen = [], [], P, []
    if E_w is not None:
        import copy as _copy
        ec = cfg["einsatz"]
        E_m = to_model(E_w).intersection(extent_m)
        sp = float(ec.get("spiel_mm", 0.4)) / 2.0
        P_haupt = [p.difference(E_m.buffer(sp, join_style="mitre")) for p in P]
        P_e = [p.intersection(E_m.buffer(-sp, join_style="mitre")) for p in P]
        while len(P_e) > 1 and P_e[-1].is_empty:
            P_e.pop()
        blds_in = [b for b in blds if E_m.contains(b["footprint"].representative_point())]
        blds = [b for b in blds if b not in blds_in]
        for b in blds_in:                          # Gebäude auf dem Einsatz werden normal mitgedruckt
            if ec.get("gebaeude") == "umriss" and b["status"] == "druck":
                b["status"] = "platzhalter"
        cfg_e = _copy.deepcopy(cfg)
        cfg_e["gelaende"]["bauweise"] = ec.get("bauweise") or L.bauweise(cfg)
        cfg_e["gelaende"]["passloecher"] = False
        log(f"4a   Einsatz: {len(P_e)} Schichten, {len(blds_in)} Gebäude darauf")
        if laser:
            parts_e, _, st_e, rip_e = L.make_parts(P_e, blds_in, feats, cfg_e, log)
            for r in rip_e:
                r["id"] = "E-" + r["id"]
                r.pop("lage", None)
            parts_e += rip_e
            stuetzen = list(st_e)

    parts, Q, stuetzen_e, rippen_3d, platten, platten_e, pdfs, pdfs_e, svgs = [], [], [], [], [], [], [], [], []
    if laser:
        log("4/6  Laserteile")
        lc = cfg["laser"]
        stuetzen_e = stuetzen if E_w is not None else []
        parts, Q, stuetzen, rippen = L.make_parts(P_haupt, blds, feats, cfg, log)
        rippen_3d = [r["lage"] for r in rippen if r.get("lage") is not None]
        for r in rippen:
            r.pop("lage", None)
        parts = parts + rippen
        for _ in range(2):
            parts = L.tile_parts(parts, formate, lc["rand_mm"], log, lc.get("ringe_teilen", True),
                                 float(lc.get("teilstueck_mm", 250)))
        L.finalize_ids(parts, cfg)
        if parts_e:
            for _ in range(2):
                parts_e = L.tile_parts(parts_e, formate, lc["rand_mm"], log, False)
            L.finalize_ids(parts_e, cfg_e, "E-")
        meldungen = []
        for p in parts + parts_e:
            BL.bereinigen(p, protokoll=meldungen)
        for m in meldungen[:20]:
            log("  " + m)
        if len(meldungen) > 20:
            log(f"  … {len(meldungen) - 20} weitere Korrekturen")

        _vorschau_3d(out, name, parts + parts_e, stuetzen, blds + blds_in, t, log, rippen_3d)

        log("5/6  Laserplatten anordnen")
        filler = stuetzen[0]["poly"] if stuetzen else None
        platten, rest = BL.anordnen(parts, formate, cfg, log, filler=filler, n_filler=len(stuetzen))
        titel = f"{cfg['projekt_name']} – {sorte} {mm(t)} mm"
        pdfs = BL.pdfs_schreiben(d_laser, f"{name}_{_safe(sorte)}_{mm(t)}mm", platten, titel, log)
        svgs = []
        for i, pl in enumerate(platten, 1):
            sp = os.path.join(d_laser, f"{name}_platte_{i:02d}.svg")
            BL.svg_schreiben(sp, pl, titel=f"Platte {i}")
            svgs.append(sp)
        if lc.get("ausgabe_dxf"):
            BL.dxf_schreiben(os.path.join(d_laser, f"{name}_laser.dxf"), platten)
        log(f"  Werkstatt-PDFs: {len(pdfs)} (je Platte eine Datei, z. B. {os.path.basename(pdfs[0]) if pdfs else '-'})")
        pdfs_e, platten_e = [], []
        if parts_e:
            import copy as _copy
            n_ex = max(1, int(cfg["einsatz"].get("exemplare", 1)))
            alle_e = []
            for x in range(n_ex):
                for p in parts_e:
                    q = _copy.copy(p)
                    alle_e.append(q)
            log(f"5b   Einsatz anordnen ({n_ex} Exemplar{'e' if n_ex > 1 else ''})")
            fe = stuetzen_e[0]["poly"] if stuetzen_e else None
            platten_e, _ = BL.anordnen(alle_e, formate, cfg, log, filler=fe, n_filler=len(stuetzen_e) * n_ex)
            pdfs_e = BL.pdfs_schreiben(d_laser, f"{name}_Einsatz_{_safe(sorte)}_{mm(t)}mm", platten_e,
                                       titel + " – Einsatz", log)
            for i, pl in enumerate(platten_e, 1):
                sp_ = os.path.join(d_laser, f"{name}_einsatz_platte_{i:02d}.svg")
                BL.svg_schreiben(sp_, pl, titel=f"Einsatz Platte {i}")
                svgs.append(sp_)
            log(f"  Einsatz-PDFs: {len(pdfs_e)}")

    else:
        log("4/6  Laserteile: nicht gewählt")
        parts_e, stuetzen = [], []
        _vorschau_3d(out, name, [], [], blds + blds_in, t, log, [])

    log("6/6  Druckplatten und Montageplan")
    from . import druck as D
    printable = [b for b in blds + blds_in if b["status"] == "druck" and b["mesh"] is not None]
    if not druck:
        printable_w = []
        log("6/6  Gebäude-3D-Druck: nicht gewählt")
    else:
        printable_w = printable
    for b in printable_w:
        D.stl(os.path.join(d_einzel, f"{b['nr']}_{_safe(b['gml_id'])}.stl"), [b["mesh"]])
    drucke = []
    for grp in ("umgebung", "einsatz"):
        sel = [b for b in printable_w if b["gruppe"] == grp]
        if sel:
            drucke += D.auf_betten([{"id": b["nr"], "mesh": b["mesh"], "fp": b["footprint"], "ref": b} for b in sel],
                                   cfg, os.path.join(d_druck, f"{name}_{grp}"), log, grp)
    vol = sum(abs(b["mesh"].volume) for b in printable)
    fil = BIB.FILAMENTE.get(cfg["druck"].get("filament", "PLA"), BIB.FILAMENTE["PLA"])

    plat = {}
    for pl in platten:
        plat[pl["format"]] = plat.get(pl["format"], 0) + 1
    teile_fl = sum(p["poly"].area for p in parts)
    voll = sum(q.area for q in Q)
    stats = {
        "modell_b": modell_b, "modell_h": modell_h, "platten": plat,
        "teile_flaeche": teile_fl, "voll_flaeche": voll,
        "ersparnis": 100 * (1 - teile_fl / voll) if voll else 0,
        "n_druck": len(printable), "n_gravur": sum(b["status"] == "gravur" for b in blds + blds_in),
        "n_platz": sum(b["status"] == "platzhalter" for b in blds + blds_in),
        "n_druckplatten": len(drucke), "n_stuetzen": len(stuetzen),
        "n_rippen": sum(1 for p in parts if p.get("rippe")),
        "volumen_cm3": vol / 1000.0,
        "filament_g": vol / 1000.0 * fil["dichte_g_cm3"] * cfg["druck"].get("fuellgrad_effektiv", 0.35),
        "material": f"{sorte} {mm(t)} mm", "bauweise": L.bauweise(cfg),
    }
    if laser:
        # Laserzeit und Kosten (nur für den Bericht)
        zeit, z_lo, z_hi, zt = BL.laserzeit(platten + platten_e, sorte, t)
        pm, mw = BIB.WERKSTATT["preis_min_netto"], BIB.WERKSTATT["mwst"]
        stats["laser"] = {"s": zeit, "s_lo": z_lo, "s_hi": z_hi, "teile": zt,
                          "netto": zeit / 60 * pm, "netto_lo": z_lo / 60 * pm, "netto_hi": z_hi / 60 * pm,
                          "preis_min": pm, "mwst": mw}
        # Draufsicht und Schnitte
        from . import ansichten as AN
        try:
            stats["ansichten"] = AN.erzeugen(out, name, parts + parts_e, blds + blds_in, t, modell_b, modell_h)
        except Exception as e:
            log(f"  Hinweis: Ansichten nicht erzeugt ({e})")
            stats["ansichten"] = []
        R.write_pdf(os.path.join(out, f"{name}_montageplan.pdf"), cfg, info, Q, parts + parts_e, platten + platten_e,
                    blds + blds_in,
                    drucke, feats, stats, stuetzen)
    else:
        stats["ansichten"] = []
    with open(os.path.join(out, f"{name}_teileliste.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["Typ", "ID", "Schicht", "Platte", "Fläche/Höhe", "Status", "gml_id"])
        for p in parts + parts_e:
            w.writerow(["Rippe" if p.get("rippe") else "Laserteil", p["id"],
                        "" if p.get("rippe") else p["layer"], p.get("platte", "-"),
                        f"{p['poly'].area / 100:.1f} cm²", "", ""])
        for b in blds + blds_in:
            w.writerow([b["art"], b["nr"], b["layer"], b.get("druckplatte", "-"),
                        f"{b['height_mm']:.1f} mm", f"{b['status']} ({b['lod']})", b["gml_id"]])
    stats.update({
        "ausgabe": out, "laser_ordner": d_laser, "laser_pdfs": pdfs, "einsatz_pdfs": pdfs_e, "laser_svgs": svgs,
        "n_einsatzplatten": len(platten_e),
        "vorschau_laser": os.path.join(out, f"{name}_vorschau_laser.stl"),
        "vorschau_druck": os.path.join(out, f"{name}_vorschau_druck.stl"),
        "montageplan": os.path.join(out, f"{name}_montageplan.pdf"),
        "druck_stls": [d["datei"] for d in drucke], "druck_plaene": drucke,
        "n_laserplatten": len(platten), "n_teile": len(parts), "dauer_s": time.time() - t0,
    })
    log(f"Fertig in {stats['dauer_s']:.0f} s: {len(platten)} Laserplatten, {len(drucke)} Druckplatten. Ausgabe: {out}")
    return stats


def _vorschau_3d(out, name, parts, stuetzen, blds, t, log, rippen_3d=()):
    """Das fertige Modell zusammengesetzt, getrennt nach Laser- und Druckteilen (eigene Farben in der Vorschau)."""
    try:
        import trimesh
        laser, druck = [], []
        for p in parts:
            if p.get("rippe"):
                continue
            for comp in polys(p["poly"]):
                m = trimesh.creation.extrude_polygon(comp, t)
                m.apply_translation([0, 0, p["layer"] * t])
                laser.append(m)
        laser += list(rippen_3d)
        for st in stuetzen:
            m = trimesh.creation.extrude_polygon(st["poly"], t)
            m.apply_translation([st["pos"][0], st["pos"][1], st["layer"] * t])
            laser.append(m)
        for b in blds:
            if b["mesh"] is not None and b["status"] == "druck":
                m = b["mesh"].copy()
                m.apply_translation([0, 0, (b["layer"] + 1) * t])
                druck.append(m)
        if laser:
            trimesh.util.concatenate(laser).export(os.path.join(out, f"{name}_vorschau_laser.stl"))
        if druck:
            trimesh.util.concatenate(druck).export(os.path.join(out, f"{name}_vorschau_druck.stl"))
    except Exception as e:
        log(f"  Hinweis: 3D-Vorschau nicht erzeugt ({e})")
