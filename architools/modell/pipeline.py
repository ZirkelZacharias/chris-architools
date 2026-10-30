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
from . import gebaeude_laser as GL
from . import geo_io as G
from . import laser as L
from . import report as R
from . import terrain as T
from .geomutil import lines, polys, world_to_model


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
        if q == "auto" and cfg.get("_nur_dgm"):
            sz = A.dgm_aus_koordinaten(cfg, _bbox_rahmen(r), log)
            sz["rahmen"] = r
            return sz
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
                             "raster_grau": float(m.get("raster_grau", 50.0)), "raster_weite_mm": float(m.get("raster_weite_mm", 0.8)),
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


def _hoehenlinien_feats(dgm, cfg, to_model, extent_w, extent_m, f, log):
    """Höhenlinien aus dem Gelände als Ritz-/Gravurlinien. Jede Linie landet automatisch auf der Schicht, auf der sie liegt."""
    import contourpy
    from scipy.ndimage import gaussian_filter
    hl = cfg["laser"]["hoehenlinien"]
    x, y, z = np.asarray(dgm["x"], float), np.asarray(dgm["y"], float), np.asarray(dgm["z"], float)
    res = abs(x[1] - x[0]) if len(x) > 1 else 1.0
    sig = max(float(cfg["dgm"].get("glaettung_m") or 0), 2.0) / res           # etwas glätten: das Raster ist stufig
    z = gaussian_filter(z, sig, mode="nearest")
    aeq = max(0.1, float(hl.get("aequidistanz_m") or 1.0))
    haupt = max(1, int(hl.get("haupt_alle") or 5))
    cg = contourpy.contour_generator(x, y, z)
    feats = []
    n_h = n_n = 0
    k0, k1 = int(np.floor(z.min() / aeq)), int(np.ceil(z.max() / aeq))
    for k in range(k0, k1 + 1):
        lvl = k * aeq
        if lvl <= z.min() or lvl >= z.max():
            continue
        zeilen = [shapely.LineString(l) for l in cg.lines(lvl) if len(l) >= 2]
        if not zeilen:
            continue
        g = shapely.union_all(zeilen).intersection(extent_w)
        if g.is_empty:
            continue
        gm = to_model(g).intersection(extent_m)
        if gm.is_empty or gm.length < 3.0:
            continue
        ist_haupt = (k % haupt == 0)
        akt = (hl.get("haupt") if ist_haupt else hl.get("neben")) or "ritzen"
        if akt == "aus":
            continue
        feats.append({"name": "Höhenlinien", "geom": gm, "typ": "linie", "aktion": akt, "d": 1.5,
                      "breite_mm": 0.6 if ist_haupt else 0.0, "raster": (50.0, 0.8)})
        n_h += ist_haupt
        n_n += not ist_haupt
    log(f"  Höhenlinien auf den Platten: Abstand {aeq:g} m, {n_h} Haupt- und {n_n} Nebenlinien")
    return feats


def _akt(a):
    return {"gravieren": "gravieren", "gravieren (Fläche)": "gravieren", "ritzen": "ritzen", "raster": "raster",
            "schneiden": "schneiden", "aus": "aus"}.get(a, "ritzen")


# ------------------------------------------------------------------ Modell bauen
def _gebaeude_platten(cfg, parts_g, parts_ge, sorte_g, t_g, formate, d_laser, name, svgs, svgs_v, log):
    """Gebäudeteile aus eigenem Material (oder ohne Gelände-Lasercut) auf Platten legen und schreiben"""
    import copy as _copy
    n_ex = max(1, int(cfg["einsatz"].get("exemplare", 1))) if cfg["einsatz"].get("aktiv") else 1
    alle = list(parts_g) + [_copy.copy(p) for _ in range(n_ex) for p in parts_ge]
    log(f"5a   Gebäudeteile aus {sorte_g} {mm(t_g)} mm anordnen")
    platten_g, _ = BL.anordnen(alle, formate, cfg, log)
    pdfs_g = BL.pdfs_schreiben(d_laser, f"{name}_Gebaeude_{_safe(sorte_g)}_{mm(t_g)}mm", platten_g,
                               f"{cfg['projekt_name']} – Gebäude {sorte_g} {mm(t_g)} mm", log)
    for i, pl in enumerate(platten_g, 1):
        sp = os.path.join(d_laser, f"{name}_gebaeude_platte_{i:02d}.svg")
        BL.svg_schreiben(sp, pl, titel=f"Gebäude Platte {i}")
        svgs.append(sp)
        svgs_v.append(_svg_vorschau(sp, pl, sorte_g, f"Gebäude Platte {i}"))
    return platten_g, pdfs_g


def _gebaeude_teile(cfg, blds, blds_in, sorte, t, formate, log, getrennt=False):
    """Gebäude als Laserteile (Stapelmodell, Klebeflächen, Faltmodell).
    -> (Teile Umgebung, Teile Einsatz, Material, Stärke, eigenes Material?)  getrennt=True: immer eigene Plattengruppe"""
    gc = cfg["gebaeude"]
    modus = gc.get("modus", "druck")
    sorte_g = gc.get("material") or sorte
    t_g = float(gc.get("staerke_mm") or t)
    if sorte_g != sorte and not gc.get("staerke_mm"):
        mat_g = BIB.alle("materialien").get(sorte_g) or {}
        t_g = float((mat_g.get("staerken") or [t])[0])
    eigen = getrennt or (sorte_g != sorte) or abs(t_g - t) > 1e-6
    if modus == "falt" and t_g > 1.0:
        log(f"  HINWEIS: Faltmodell mit {mm(t_g)} mm Material - zum Falten ist dünner Karton (bis ca. 0,5 mm) besser; "
            "bei dickerer Pappe sind die Ritzlinien nur eine Knick-Hilfe")
    lc = cfg["laser"]
    pg = GL.teile_fuer(blds, cfg, t_g, formate, lc["rand_mm"], log)
    pe = GL.teile_fuer(blds_in, cfg, t_g, formate, lc["rand_mm"], log) if blds_in else []
    return pg, pe, sorte_g, t_g, eigen


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
                          "d": float(e.get("d") or 1.5), "breite_mm": bw * f,
                          "raster": (float(e.get("raster_grau", 50.0)), float(e.get("raster_weite_mm", 0.8)))})

    if laser and (cfg["laser"].get("hoehenlinien") or {}).get("aktiv"):
        try:
            feats += _hoehenlinien_feats(szene["dgm"], cfg, to_model, extent_w, extent_m, f, log)
        except Exception as e:
            log(f"  HINWEIS: Höhenlinien auf den Platten nicht erzeugt ({str(e)[:120]})")

    # Projektgrundstück als Einsatz
    E_w = einsatz_polygon(cfg, szene, log)
    parts_e, blds_in, P_haupt, stuetzen = [], [], P, []
    if E_w is not None and not E_w.is_empty:
        # Einsatz muss im Modellrahmen liegen (häufig: eigene Fläche noch vom früheren Mittelpunkt gezeichnet)
        E_m0 = to_model(E_w)
        drin = E_m0.intersection(extent_m)
        anteil = drin.area / E_m0.area if E_m0.area > 0 else 0.0
        if drin.is_empty or drin.area < 1.0 or (P and P[0].intersection(drin).area < 1.0):
            c = E_w.centroid
            log(f"  HINWEIS: Der Einsatz ({E_w.area:.0f} m², Mitte Ost {c.x:.0f} / Nord {c.y:.0f}) liegt außerhalb des Modellrahmens "
                f"(Mitte Ost {extent_w.centroid.x:.0f} / Nord {extent_w.centroid.y:.0f}) – ohne Einsatz weitergerechnet. Wurde die Fläche "
                f"noch am alten Mittelpunkt gezeichnet? Auf der Seite Gebiet die Auswahl leeren und neu zeichnen.")
            E_w = None
        elif anteil < 0.98:
            log(f"  HINWEIS: Nur {anteil * 100:.0f} % des Einsatzes liegen im Modellrahmen – der Rest wird abgeschnitten.")
    elif E_w is not None:
        E_w = None
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

    parts, Q, stuetzen_e, rippen_3d, platten, platten_e, pdfs, pdfs_e, svgs, svgs_v = [], [], [], [], [], [], [], [], [], []
    parts_g, parts_ge, platten_g, pdfs_g, rest_ungenutzt = [], [], [], [], []
    modus = cfg["gebaeude"].get("modus", "druck")
    sorte_g, t_g, eigen_mat = sorte, t, False
    if laser:
        log("4/6  Laserteile")
        lc = cfg["laser"]
        stuetzen_e = stuetzen if E_w is not None else []
        teststreifen = []
        if (cfg.get("raster_bild") or {}).get("aktiv"):
            # Rastergravur eines Bildes: gehört zum Zusatzmodul (Plugin); ohne Modul wird sie übersprungen
            from .. import zusatz
            cfg["_dgm"] = szene.get("dgm")                     # für Quellen, die aus dem Geländemodell berechnet werden (Schummerung u. a.)
            try:
                rr = zusatz.erstes("modell_raster_bild", cfg, extent_w.bounds, extent_m, tw_xy, log, log=log)
            finally:
                cfg.pop("_dgm", None)
            if rr:
                cfg["_rasterbild"] = rr.get("region")
                teststreifen = rr.get("teststreifen") or []
            else:
                log("  HINWEIS: Rastergravur eines Bildes ist angekreuzt, aber das Zusatzmodul dafür ist nicht installiert - übersprungen")
        parts, Q, stuetzen, rippen = L.make_parts(P_haupt, blds, feats, cfg, log)
        cfg.pop("_rasterbild", None)
        rippen_3d = [r["lage"] for r in rippen if r.get("lage") is not None]
        for r in rippen:
            r.pop("lage", None)
        parts = parts + rippen
        rz = (lc.get("rahmen") or {})
        if rz.get("aktiv"):
            n_sch = 1 + max([p["layer"] for p in parts if not p.get("rippe")] or [0])
            rt = L.rahmen_teile(extent_m.bounds, n_sch * t, t, ueberstand_mm=float(rz.get("ueberstand_mm") or 0.0))
            rippen_3d += [r["lage"] for r in rt if r.get("lage") is not None]
            for r in rt:
                r.pop("lage", None)
            parts = parts + rt
            log(f"  Rahmen mitgelasert: 4 stehende Wände aus demselben Material, {n_sch * t + float(rz.get('ueberstand_mm') or 0):.1f} mm hoch "
                f"(Modellhöhe), Dicke {t:g} mm")
        for _ in range(2):
            parts = L.tile_parts(parts, formate, lc["rand_mm"], log, lc.get("ringe_teilen", True),
                                 float(lc.get("teilstueck_mm", 250)))
        L.finalize_ids(parts, cfg)
        if parts_e:
            for _ in range(2):
                parts_e = L.tile_parts(parts_e, formate, lc["rand_mm"], log, False)
            L.finalize_ids(parts_e, cfg_e, "E-")
        if modus != "druck":
            parts_g, parts_ge, sorte_g, t_g, eigen_mat = _gebaeude_teile(cfg, blds, blds_in, sorte, t, formate, log)
        meldungen = []
        for p in parts + parts_e + parts_g + parts_ge:
            BL.bereinigen(p, protokoll=meldungen)
        for m in meldungen[:20]:
            log("  " + m)
        if len(meldungen) > 20:
            log(f"  … {len(meldungen) - 20} weitere Korrekturen")

        _vorschau_3d(out, name, parts + parts_e, stuetzen, blds + blds_in, t, log, rippen_3d, BIB.farbe(sorte))

        log("5/6  Laserplatten anordnen")
        filler = stuetzen[0]["poly"] if stuetzen else None
        fest = BL.restplatten(cfg)
        if fest:
            log(f"  Restplatten: {len(fest)} angelegt, werden zuerst belegt")
        haupt = parts + (parts_g if not eigen_mat else []) + teststreifen
        platten, rest = BL.anordnen(haupt, formate, cfg, log, filler=filler, n_filler=len(stuetzen), fest=fest)
        titel = f"{cfg['projekt_name']} – {sorte} {mm(t)} mm"
        pdfs = BL.pdfs_schreiben(d_laser, f"{name}_{_safe(sorte)}_{mm(t)}mm", platten, titel, log)
        svgs, svgs_v = [], []
        for i, pl in enumerate(platten, 1):
            sp = os.path.join(d_laser, f"{name}_platte_{i:02d}.svg" if not pl.get("rest") else f"{name}_restplatte_{i:02d}.svg")
            bez = f"Restplatte {pl['rest']}" if pl.get("rest") else f"Platte {i}"
            BL.svg_schreiben(sp, pl, titel=bez)
            svgs.append(sp)
            svgs_v.append(_svg_vorschau(sp, pl, sorte, bez))
        if eigen_mat and (parts_g or parts_ge):
            platten_g, pdfs_g = _gebaeude_platten(cfg, parts_g, parts_ge, sorte_g, t_g, formate, d_laser, name, svgs, svgs_v, log)
        if lc.get("ausgabe_dxf"):
            BL.dxf_schreiben(os.path.join(d_laser, f"{name}_laser.dxf"), platten)
        log(f"  Werkstatt-PDFs: {len(pdfs)} (je Platte eine Datei, z. B. {os.path.basename(pdfs[0]) if pdfs else '-'})")
        pdfs_e, platten_e = [], []
        if parts_e:
            import copy as _copy
            n_ex = max(1, int(cfg["einsatz"].get("exemplare", 1)))
            alle_e = []
            for x in range(n_ex):
                for p in parts_e + (parts_ge if not eigen_mat else []):
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
                svgs_v.append(_svg_vorschau(sp_, pl, sorte, f"Einsatz Platte {i}"))
            log(f"  Einsatz-PDFs: {len(pdfs_e)}")

    else:
        parts_e, stuetzen = [], []
        if druck and modus != "druck":
            log("4/6  Gebäude als Laserteile (ohne Geländeplatten)")
            lc = cfg["laser"]
            parts_g, parts_ge, sorte_g, t_g, eigen_mat = _gebaeude_teile(cfg, blds, blds_in, sorte, t, formate, log, True)
            meld = []
            for p in parts_g + parts_ge:
                BL.bereinigen(p, protokoll=meld)
            svgs, svgs_v = [], []
            if parts_g or parts_ge:
                platten_g, pdfs_g = _gebaeude_platten(cfg, parts_g, parts_ge, sorte_g, t_g, formate, d_laser, name, svgs, svgs_v, log)
        else:
            log("4/6  Laserteile: nicht gewählt")
        _vorschau_3d(out, name, [], [], blds + blds_in, t, log, [])

    log("6/6  Druckplatten und Montageplan")
    from . import druck as D
    printable = [b for b in blds + blds_in if b["status"] == "druck" and b["mesh"] is not None]
    if not druck or modus != "druck":
        printable_w = []
        log("6/6  Gebäude-3D-Druck: nicht gewählt" if modus == "druck" else f"6/6  Gebäude werden gelasert ({modus}) - keine Druck-STL")
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

    holz_dateien = []
    try:
        if (laser or druck) and ((cfg.get("holz") or {}).get("podest") or {}).get("aktiv"):
            from . import podest as PO
            holz_res = PO.berechnen(cfg, modell_b, modell_h, len(P) * t, t=t)
            holz_dateien = PO.schreiben(os.path.join(out, "holz"), name, holz_res, log)
    except Exception as e:
        log(f"  Hinweis: Holz (Rahmen/Podest) nicht berechnet ({e})")
        holz_res = None
    plat = {}
    for pl in platten + platten_g:
        plat[pl["format"]] = plat.get(pl["format"], 0) + 1
    teile_fl = sum(p["poly"].area for p in parts)
    voll = sum(q.area for q in Q)
    stats = {
        "modell_b": modell_b, "modell_h": modell_h, "platten": plat,
        "teile_flaeche": teile_fl, "voll_flaeche": voll,
        "ersparnis": 100 * (1 - teile_fl / voll) if voll else 0,
        "n_druck": len(printable) if modus == "druck" else 0, "n_gebaeude_laser": len(printable) if modus != "druck" else 0, "n_gravur": sum(b["status"] == "gravur" for b in blds + blds_in),
        "n_platz": sum(b["status"] == "platzhalter" for b in blds + blds_in),
        "n_druckplatten": len(drucke), "n_stuetzen": len(stuetzen),
        "n_rippen": sum(1 for p in parts if p.get("rippe") and not p.get("rahmen")),
        "volumen_cm3": vol / 1000.0,
        "filament_g": vol / 1000.0 * fil["dichte_g_cm3"] * cfg["druck"].get("fuellgrad_effektiv", 0.35),
        "material": f"{sorte} {mm(t)} mm", "bauweise": L.bauweise(cfg),
        "holz": holz_dateien, "gebaeude_modus": modus, "n_geb_teile": len(parts_g) + len(parts_ge),
        "gebaeude_material": f"{sorte_g} {mm(t_g)} mm", "n_restplatten": sum(1 for pl in platten if pl.get("rest")),
    }
    if laser or platten_g:
        # Laserzeit und Kosten (nur für den Bericht)
        zeit, z_lo, z_hi, zt = BL.laserzeit(platten + platten_e, sorte, t)
        if platten_g:
            g1, g2, g3, gt = BL.laserzeit(platten_g, sorte_g, t_g)
            zeit, z_lo, z_hi = zeit + g1, z_lo + g2, z_hi + g3
            zt = {k: (v + gt.get(k, 0) if k != "v_schnitt" else v) for k, v in zt.items()}
        pm, mw = BIB.WERKSTATT["preis_min_netto"], BIB.WERKSTATT["mwst"]
        stats["laser"] = {"s": zeit, "s_lo": z_lo, "s_hi": z_hi, "teile": zt,
                          "netto": zeit / 60 * pm, "netto_lo": z_lo / 60 * pm, "netto_hi": z_hi / 60 * pm,
                          "preis_min": pm, "mwst": mw}
    if laser:
        # Draufsicht und Schnitte
        from . import ansichten as AN
        try:
            stats["ansichten"] = AN.erzeugen(out, name, parts + parts_e, blds + blds_in, t, modell_b, modell_h)
        except Exception as e:
            log(f"  Hinweis: Ansichten nicht erzeugt ({e})")
            stats["ansichten"] = []
        R.write_pdf(os.path.join(out, f"{name}_montageplan.pdf"), cfg, info, Q, parts + parts_e, platten + platten_g + platten_e,
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
        for p in parts_g + parts_ge:
            w.writerow([p.get("art", "Gebäudeteil"), p["id"], "", p.get("platte", "-"),
                        f"{p['poly'].area / 100:.1f} cm²", modus, ""])
        for b in blds + blds_in:
            w.writerow([b["art"], b["nr"], b["layer"], b.get("druckplatte", "-"),
                        f"{b['height_mm']:.1f} mm", f"{b['status']} ({b['lod']})", b["gml_id"]])
    try:
        from . import kosten as KO
        stats["kostenliste"] = os.path.join(out, f"{name}_zuschnitt_und_kosten.txt")
        stats["kosten_text"] = KO.schreiben(stats["kostenliste"], cfg, stats, platten, platten_e, drucke, platten_g)
    except Exception as e:
        stats["kostenliste"] = None
        log(f"  Hinweis: Zuschnitt-/Kostenliste nicht erzeugt ({e})")
    stats.update({
        "ausgabe": out, "laser_ordner": d_laser, "laser_pdfs": pdfs + pdfs_g, "einsatz_pdfs": pdfs_e, "laser_svgs": svgs, "laser_svgs_vorschau": svgs_v, "material_farbe": BIB.farbe(sorte) if laser else None,
        "n_einsatzplatten": len(platten_e),
        "vorschau_laser": os.path.join(out, f"{name}_vorschau_laser.stl"),
        "vorschau_druck": os.path.join(out, f"{name}_vorschau_druck.stl"),
        "vorschau_gravur": next((x for x in (os.path.join(out, f"{name}_vorschau_gravur.glb"), os.path.join(out, f"{name}_vorschau_gravur.stl"))
                                 if os.path.exists(x)), os.path.join(out, f"{name}_vorschau_gravur.stl")),
        "montageplan": os.path.join(out, f"{name}_montageplan.pdf"),
        "druck_stls": [d["datei"] for d in drucke], "druck_plaene": drucke,
        "n_laserplatten": len(platten), "n_teile": len(parts), "dauer_s": time.time() - t0,
    })
    try:
        from .. import zusatz as ZU
        if ZU.vorhanden():
            ZU.rufe("modell_ende", dict(cfg=cfg, buildings=blds + blds_in, ausgabe=out, name=name, massstab=scale, log=log), log=log)
    except Exception as e:
        log(f"  HINWEIS: Zusatzmodule im Modellbau nicht ausgeführt ({str(e)[:100]})")
    log(f"Fertig in {stats['dauer_s']:.0f} s: {len(platten)} Laserplatten, {len(drucke)} Druckplatten. Ausgabe: {out}")
    return stats


def _svg_vorschau(pfad, platte, sorte, titel):
    """Vorschau-SVG in Materialfarbe (nur zur Anzeige, im Unterordner .vorschau; die Werkstatt-Datei bleibt unverändert)."""
    ordner = os.path.join(os.path.dirname(pfad), ".vorschau")
    os.makedirs(ordner, exist_ok=True)
    ziel = os.path.join(ordner, os.path.basename(pfad))
    f = BIB.farbe(sorte)
    BL.svg_schreiben(ziel, platte, linie_mm=0.6, titel=titel, plattenfarbe=f, teilefarbe=BIB.aufhellen(f, 0.35))
    return ziel


def _vorschau_gravur_glb(out, name, parts, t, farbe, log, px_mm=4.0, max_px=2048):
    """Ritzen und Gravur (auch Rastergravur mit Zehntausenden Streifen) als Bild auf der Oberseite jeder Schicht -> .glb oder None.
    Je Schicht ein Bild in Materialfarbe: fein gezeichnet (px_mm), dann auf höchstens max_px verkleinert – das Raster erscheint so als
    Halbtonbild, wie es aus etwas Abstand auf dem Material wirkt. Nur für die Vorschau; die Laserdateien bleiben unverändert."""
    alt_glb = os.path.join(out, f"{name}_vorschau_gravur.glb")
    if os.path.exists(alt_glb):                                        # Vorschau eines früheren Laufs nicht stehen lassen
        os.remove(alt_glb)
    try:
        import trimesh
        from PIL import Image, ImageDraw
    except Exception:
        return None
    if not any((p.get("gravieren") or p.get("ritzen")) for p in parts):
        return None
    farbe = (farbe or "#d9c7a3").lstrip("#")
    grund = tuple(int(farbe[i:i + 2], 16) for i in (0, 2, 4))
    brand, ritz = (62, 42, 30), (105, 78, 58)
    schichten = {}
    for p in parts:
        schichten.setdefault(p["layer"], []).append(p)
    szene = trimesh.Scene()
    n_bilder = 0
    gross = max((max(c.bounds[2] for p in parts for c in polys(p["poly"])) - min(c.bounds[0] for p in parts for c in polys(p["poly"]))), 50.0)
    abstand = max(0.15, gross / 2500.0)       # Bild knapp über der Platte; genug Abstand, damit die 3D-Ansicht nicht flimmert
    for k, ps in sorted(schichten.items()):
        if not any((p.get("gravieren") or p.get("ritzen")) for p in ps):
            continue
        flaechen = [c for p in ps for c in polys(p["poly"]) if c.area > 1]
        if not flaechen:
            continue
        x0 = min(c.bounds[0] for c in flaechen); y0 = min(c.bounds[1] for c in flaechen)
        x1 = max(c.bounds[2] for c in flaechen); y1 = max(c.bounds[3] for c in flaechen)
        W, H = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
        f = min(px_mm, 8000.0 / max(W, H))                              # fein zeichnen (Streifen ab ca. 0,25 mm sichtbar) ...
        iw, ih = max(2, int(W * f)), max(2, int(H * f))
        im = Image.new("RGB", (iw, ih), grund)
        dr = ImageDraw.Draw(im)
        pix = lambda cs: [((x - x0) * f, (y1 - y) * f) for x, y in cs]
        for p in ps:
            for g in p.get("gravieren") or []:
                for c in polys(g):
                    if len(c.exterior.coords) >= 3:
                        dr.polygon(pix(c.exterior.coords), fill=brand)
                        for r in c.interiors:
                            dr.polygon(pix(r.coords), fill=grund)
            for l in p.get("ritzen") or []:
                for ln in lines(l):
                    dr.line(pix(ln.coords), fill=ritz, width=max(1, int(round(0.3 * f))))
        sk = min(1.0, max_px / float(max(iw, ih)))                       # ... dann verkleinern: Raster wird Halbton
        if sk < 1.0:
            im = im.resize((max(2, int(iw * sk)), max(2, int(ih * sk))), Image.LANCZOS)
        V, F = [], []
        for c in flaechen:
            try:
                v2, f2 = trimesh.creation.triangulate_polygon(c)
            except Exception:
                continue
            F.append(f2 + sum(len(v) for v in V))
            V.append(v2)
        if not V:
            continue
        V = np.vstack(V)
        uv = np.c_[(V[:, 0] - x0) / W, (V[:, 1] - y0) / H]
        mat = trimesh.visual.material.PBRMaterial(baseColorTexture=im, baseColorFactor=[255, 255, 255, 255], metallicFactor=0.0,
                                                  roughnessFactor=1.0, emissiveTexture=im, emissiveFactor=[0.6, 0.6, 0.6])
        # sonst dunkelt glTF ab (Faktor 0,4, metallisch = schwarz); das Eigenleuchten gleicht das schwächere Licht für glTF in der 3D-Ansicht aus
        m = trimesh.Trimesh(np.c_[V, np.full(len(V), (k + 1) * t + abstand)], np.vstack(F), process=False,
                            visual=trimesh.visual.TextureVisuals(uv=uv, material=mat))
        szene.add_geometry(m, node_name=f"Schicht_{k}")
        n_bilder += 1
    if not n_bilder:
        return None
    ziel = os.path.join(out, f"{name}_vorschau_gravur.glb")
    szene.export(ziel)
    alt = os.path.join(out, f"{name}_vorschau_gravur.stl")
    if os.path.exists(alt):
        os.remove(alt)
    log(f"  3D-Vorschau: Gravur und Ritzlinien als Bild auf {n_bilder} Schichten ({os.path.getsize(ziel) / 1e6:.1f} MB)")
    return ziel


def _vorschau_3d(out, name, parts, stuetzen, blds, t, log, rippen_3d=(), farbe=None):
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
        glb = _vorschau_gravur_glb(out, name, [p for p in parts if not p.get("rippe")], t, farbe, log)
        if not glb:                                                    # Ersatz: Ritz- und Gravurflächen als dünne dunkle Auflage
            gravur, grenze = [], 4000
            for p in parts:
                if p.get("rippe") or len(gravur) >= grenze:
                    continue
                geoms = [g.buffer(0.25) for g in (p.get("ritzen") or []) if g is not None and not g.is_empty]
                geoms += [g for g in (p.get("gravieren") or []) if g is not None and not g.is_empty]
                for g in geoms:
                    for comp in polys(g):
                        if comp.area < 0.05 or len(gravur) >= grenze:
                            continue
                        try:
                            m = trimesh.creation.extrude_polygon(comp, 0.15)
                        except Exception:
                            continue
                        m.apply_translation([0, 0, (p["layer"] + 1) * t + 0.02])
                        gravur.append(m)
            if len(gravur) >= grenze:
                log(f"  3D-Vorschau: Gravuren nur teilweise gezeigt (erste {grenze} Teile)")
            if gravur:
                trimesh.util.concatenate(gravur).export(os.path.join(out, f"{name}_vorschau_gravur.stl"))
        if laser:
            trimesh.util.concatenate(laser).export(os.path.join(out, f"{name}_vorschau_laser.stl"))
        if druck:
            trimesh.util.concatenate(druck).export(os.path.join(out, f"{name}_vorschau_druck.stl"))
    except Exception as e:
        log(f"  Hinweis: 3D-Vorschau nicht erzeugt ({e})")
