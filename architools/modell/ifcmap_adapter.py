"""IFCmap-Projekt (.ifcmap.json) -> Szene für das Gelände-Modell.

Nutzt den Rechenkern von IFCmap (ifcmap_kern.py aus dem IFCmap-Ordner): Kachel-Download
(DGM1, LoD2), ALKIS-Nutzung, Bäume, Flurstücke, Lücken im LoD2, Gleisachsen.
Das Gelände wird ungeglättet aus den DGM-Kacheln gelesen (nicht das ausgedünnte IFC-Netz).
"""
import json
import os
import sys
from dataclasses import replace

import numpy as np
import shapely
from shapely.geometry import MultiPoint, Point

# Auswahlwerte der IFCmap-Oberfläche (ifcmap.py) -> interne Werte
QUELLEN = {"Automatisch (amtlich, sonst OpenStreetMap)": "auto", "Nur OpenStreetMap": "osm",
           "Nur eigene Dateien (GeoJSON)": "dateien"}
LAENDER = {"Automatisch (nach dem Mittelpunkt)": "auto", "Berlin": "berlin", "Brandenburg (neu)": "brandenburg",
           "Nordrhein-Westfalen (neu, ungetestet)": "nrw", "Bayern (neu, ungetestet)": "bayern",
           "Hamburg (neu, ungetestet)": "hamburg", "Anderes Land: nur eigene Dateien": "keins"}
FERN = {"Blöcke bis Traufe (LoD1, spart Speicher)": "bloecke", "wie Nahbereich (LoD2, sehr groß)": "lod2",
        "weglassen": "keine"}

# Vorgaben: was mit welcher IFCmap-Ebene auf den Geländeplatten passiert
EBENEN_VORGABE = {
    "Strasse": {"aktion": "ritzen"},
    "Weg_Platz": {"aktion": "aus"},
    "Bahn": {"aktion": "aus"},
    "Gleisachsen": {"aktion": "ritzen"},
    "Gewaesser": {"aktion": "gravieren"},
    "Wald": {"aktion": "aus"},
    "Gehoelz": {"aktion": "aus"},
    "Gruen": {"aktion": "aus"},
    "Baeume": {"aktion": "schneiden", "punkt_d_mm": 1.5},
    "Flurstuecke": {"aktion": "aus"},
    "ALKIS_Gebaeude": {"aktion": "aus"},
    "ALKIS_Bauwerke": {"aktion": "ritzen"},
    "OEPNV": {"aktion": "ritzen"},
    "Gewaessernetz": {"aktion": "ritzen"},
    "Denkmal": {"aktion": "ritzen"},
    "FNP": {"aktion": "ritzen"},
    "Rad": {"aktion": "ritzen"},
}

# Zusatzdaten, die auf Wunsch aus den Geodiensten geholt werden (IFCmap-Schlüssel -> Ebenenname)
ZUSATZ = {"oepnv": "OEPNV", "gewaesser": "Gewaessernetz", "denkmal": "Denkmal", "fnp": "FNP", "radverkehr": "Rad"}


KERN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kern")


def ordner_finden(cfg=None):
    """Es gibt nur noch EINEN Rechenkern (architools/kern) - keine Kopie und keine Suche nach einem IFCmap-Ordner mehr."""
    return KERN


def kern(cfg=None):
    """Der gemeinsame IFCmap-Rechenkern (Daten laden, IFC, DXF-Pläne)."""
    if KERN not in sys.path:
        sys.path.insert(0, KERN)
    import ifcmap_kern as K
    return K


def _zahl(v, vorgabe=0.0):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return vorgabe


def _mitte(text):
    toks = [t for t in str(text).replace(";", " ").replace(", ", " ").split() if t]
    a, b = (float(t.replace(",", ".")) for t in toks[:2])
    if abs(a) > 1000 and abs(b) > 1000:
        return None, (a, b)
    return (a, b), None


def projekt_lesen(pfad):
    with open(pfad, encoding="utf-8") as f:
        return json.load(f)


def config_aus_projekt(K, data, rahmen=None, zusatz=None):
    """IFCmap-Projektdaten -> K.Config. rahmen = (mitte_en, breite_m, hoehe_m) überschreibt das Gebiet."""
    latlon, en = _mitte(data.get("mitte", ""))
    dat = data.get("_dateien", {})
    kbs = 25833
    for k, v in (("25832", 25832), ("25831", 25831), ("25834", 25834)):
        if k in str(data.get("kbs", "")):
            kbs = v
    cfg = K.Config(
        latlon=latlon, mitte_en=en, epsg=kbs,
        breite=_zahl(data.get("breite"), 900), hoehe=_zahl(data.get("hoehe"), 900),
        nah_breite=_zahl(data.get("nah_breite"), 600), nah_hoehe=_zahl(data.get("nah_hoehe"), 600),
        mittel_breite=_zahl(data.get("mittel_breite"), 0), mittel_hoehe=_zahl(data.get("mittel_hoehe"), 0),
        online_dgm=bool(data.get("online_dgm", True)), online_lod2=bool(data.get("online_lod2", True)),
        land=LAENDER.get(data.get("land"), "auto"), quelle=QUELLEN.get(data.get("quelle"), "auto"),
        fern_gebaeude=FERN.get(data.get("fern_gebaeude"), "bloecke"),
        dgm=list(dat.get("dgm", [])), lod2=list(dat.get("lod2", [])),
        nutzung_dateien=list(dat.get("nutzung", [])), baum_dateien=list(dat.get("baeume", [])),
        cafile=str(data.get("cafile", "") or ""), unsicher=bool(data.get("unsicher", False)),
        eingabe_crs=str(data.get("eingabe_crs", "") or ""),
        lod2_luecken=bool(data.get("lod2_luecken", True)), overrides=dict(data.get("_overrides", {})),
        baeume_nur_nah=bool(data.get("baeume_nur_nah", True)),
        markant=False, extra=list(zusatz or []), alkis_zusatz=True, dxf_plaene=["schwarzplan"], ifc=False, dxf2d=False,
        mit_gelaende=False, test=False)
    if rahmen is not None:
        (e, n), b, h = rahmen
        cfg = replace(cfg, latlon=None, mitte_en=(e, n), breite=b, hoehe=h)
    return cfg


def _punkte_zu_raster(pts):
    """Nx3 Rasterpunkte (Zellmitten) -> dict(x, y, z) für geo_io/terrain."""
    xs = np.unique(np.round(pts[:, 0], 2))
    ys = np.unique(np.round(pts[:, 1], 2))
    res = float(np.median(np.diff(xs))) if len(xs) > 1 else 1.0
    x0, y0 = xs.min(), ys.min()
    nx = int(round((xs.max() - x0) / res)) + 1
    ny = int(round((ys.max() - y0) / res)) + 1
    z = np.full((ny, nx), np.nan)
    ci = np.round((pts[:, 0] - x0) / res).astype(int)
    ri = np.round((pts[:, 1] - y0) / res).astype(int)
    z[ri, ci] = pts[:, 2]
    nan = ~np.isfinite(z)
    if nan.any():
        from scipy.ndimage import distance_transform_edt
        idx = distance_transform_edt(nan, return_distances=False, return_indices=True)
        z = z[tuple(idx)]
    return {"x": x0 + res * np.arange(nx), "y": y0 + res * np.arange(ny), "z": z}


def _gebaeude(K, d):
    """IFCmap-Gebäudeteile -> Liste im Format von geo_io.read_citygml (gruppiert nach Gebäude)."""
    gruppen = {}
    for t in d.teile:
        gruppen.setdefault(t.get("gebaeude") or t.get("id"), []).append(t)
    out = []
    for gid, teile in gruppen.items():
        roofs, grounds, hs, walls = [], [], [], []
        for t in teile:
            walls += [(np.asarray(e), [np.asarray(h) for h in hh]) for e, hh in t.get("wall") or []]
            roofs += [(np.asarray(e), [np.asarray(h) for h in hh]) for e, hh in t.get("roof") or []]
            grounds += [(np.asarray(e), [np.asarray(h) for h in hh]) for e, hh in t.get("ground") or []]
            if t.get("roofz"):
                hs.append(t["roofz"][0])
        if not roofs and not grounds:
            continue
        pts = np.vstack([e for e, _ in roofs + grounds])
        zmin = min(e[:, 2].min() for e, _ in grounds) if grounds else pts[:, 2].min()
        zmax = pts[:, 2].max()
        mh = None
        if not roofs and hs:
            mh = max(hs) - zmin
            zmax = zmin + mh
        out.append({"id": str(gid), "roofs": roofs, "grounds": grounds, "walls": walls, "zmin": float(zmin),
                    "zmax": float(zmax), "measured_height": mh,
                    "quelle": teile[0].get("quelle", "LoD2")})
    return out


def szene_aus_ifcmap(cfg, log=print, rahmen=None):
    K = kern(cfg)
    ic = cfg["ifcmap"]
    if not ic.get("projekt") or not os.path.exists(ic["projekt"]):
        raise FileNotFoundError(f"IFCmap-Projekt nicht gefunden: {ic.get('projekt')}")
    data = projekt_lesen(ic["projekt"])
    kc = config_aus_projekt(K, data, rahmen, ic.get("zusatz"))
    log(f"IFCmap-Projekt: {os.path.basename(ic['projekt'])} (IFCmap-Kern aus {os.path.dirname(K.__file__)})")
    return _szene(K, kc, cfg, log)


def szene_aus_koordinaten(cfg, rahmen, log=print):
    """Nur Mittelpunkt + Rahmen: Berlin (und hinterlegte Länder) lädt alles selbst –
    DGM1, LoD2, ALKIS-Nutzung, Bäume, Flurstücke; sonst OpenStreetMap."""
    K = kern(cfg)
    (e, n), b, h = rahmen
    nz = cfg.get("netz", {})
    kc = K.Config(mitte_en=(e, n), epsg=25833, breite=b, hoehe=h, nah_breite=b, nah_hoehe=h,
                  online_dgm=True, online_lod2=True, land="auto", quelle="auto", fern_gebaeude="lod2",
                  lod2_luecken=True, markant=False, extra=list(cfg["ifcmap"].get("zusatz") or []),
                  alkis_zusatz=True, dxf_plaene=["schwarzplan"],
                  ifc=False, dxf2d=False, mit_gelaende=False, baeume_nur_nah=False,
                  cafile=nz.get("cafile", "") or "", unsicher=bool(nz.get("unsicher", False)),
                  ua_gebaeudehoehen=bool(cfg["ifcmap"].get("ua_gebaeudehoehen", False)),
                  ua_vegetationsraster=bool(cfg["ifcmap"].get("ua_vegetationsraster", False)),
                  rad_wege=bool(cfg["ifcmap"].get("rad_wege", False)),
                  osm_ergaenzen=bool(cfg["ifcmap"].get("osm_ergaenzen", True)))
    log(f"Automatisch laden: Mitte {e:.0f} / {n:.0f}, {b:.0f} × {h:.0f} m (Daten-Kern: {os.path.dirname(K.__file__)})")
    return _szene(K, kc, cfg, log)


def _szene(K, kc, cfg, log):
    ic = cfg["ifcmap"]
    d = K.lade(kc, log=lambda s: log("  " + s))
    kc = d.cfg
    sz = {"quelle": "IFCmap", "extent": d.rect}
    # Gelände: fehlende Kacheln holen, ungeglättet lesen
    dgm = list(kc.dgm)
    try:
        kp = K.kacheln_pruefen(kc)
        if kc.online_dgm and kp["aktiv"] and kc.epsg == 25833 and K.ist_berlin(kc) and kp["dgm_fehlt"]:
            dn, _, _ = K.kacheln_online_holen(replace(kc, online_lod2=False, mit_gelaende=True), kp, log)
            dgm += dn
        elif kc.online_dgm and getattr(d, "land", None) not in (None, "berlin", "keins"):
            kc2 = K.laender_kacheln(replace(kc, mit_gelaende=True), d, d.land, log, dgm=True, lod2=False)
            dgm = list(kc2.dgm)
    except Exception as e:
        log(f"  Hinweis: Kachel-Download: {e}")
    pad = 30.0
    bb = (d.xmin - pad, d.xmax + pad, d.ymin - pad, d.ymax + pad)
    keep, _ = K.dgm_filtern(dgm, (bb[0], bb[2], bb[1], bb[3]), log)
    teile = []
    for p in keep:
        try:
            a = K.lade_xyz(p, bb)
            if a is not None and len(a):
                teile.append(a)
        except Exception as e:
            log(f"  DGM {os.path.basename(p)}: {e}")
    if not teile:
        raise RuntimeError("Keine Geländedaten für das Gebiet (DGM-Kacheln fehlen – Download in IFCmap prüfen)")
    sz["dgm"] = _punkte_zu_raster(np.vstack(teile))
    z = sz["dgm"]["z"]
    log(f"  DGM: {z.shape[1]} × {z.shape[0]} Zellen, Höhe {np.nanmin(z):.1f} – {np.nanmax(z):.1f} m")
    sz["gebaeude"] = _gebaeude(K, d)
    sz["baeume"] = [(float(b[0]), float(b[1]), float(b[2]), float(b[3])) for b in (getattr(d, "baeume", None) or [])]   # Position, Kronendurchmesser, Höhe
    log(f"  Gebäude aus IFCmap: {len(sz['gebaeude'])}")
    sz["bloecke"] = []
    # Ebenen
    vorgabe = dict(EBENEN_VORGABE)
    wahl = ic.get("ebenen") or {}
    ebenen = []

    def eb(name, items):
        e = dict(vorgabe.get(name, {"aktion": "aus"}))
        w = wahl.get(name)
        if isinstance(w, dict):
            e.update(w)
        elif isinstance(w, str):
            e["aktion"] = w
        ebenen.append({"name": name, "items": items, "aktion": e.get("aktion", "aus"),
                       "d": float(e.get("punkt_d_mm", 1.5)), "breite_m": float(e.get("breite_m", 0))})

    for kat, geom in (getattr(d, "regionen", None) or {}).items():
        eb(kat, [(geom, {})])
    try:
        ach = K.bahn_achsen(d, kc, log)
        if ach:
            eb("Gleisachsen", [(l, {}) for l in ach])
    except Exception as e:
        log(f"  Gleisachsen nicht verfügbar ({e})")
    if getattr(d, "baeume", None):
        eb("Baeume", [(MultiPoint([(b[0], b[1]) for b in d.baeume]), {})])
    zs = getattr(d, "zusatz", None) or {}
    fl = zs.get("Flurstuecke") or []
    if fl:
        eb("Flurstuecke", [(shapely.union_all([g.boundary for g, _ in fl]), {})])
    for k, name in (("Gebaeude", "ALKIS_Gebaeude"), ("Bauwerke", "ALKIS_Bauwerke")):
        if zs.get(k):
            eb(name, [(g, p) for g, p in zs[k]])
    for k, lst in (getattr(d, "extra", None) or {}).items():
        name = ZUSATZ.get(k)
        if name and lst:
            eb(name, [(g, a) for _ug, _art, g, a in lst if g is not None and not g.is_empty])
    sz["ebenen"] = ebenen
    log("  Ebenen: " + ", ".join(f"{e['name']} ({e['aktion']})" for e in ebenen))
    # Projektgrundstück
    if cfg.get("einsatz", {}).get("aktiv"):
        pt = Point(d.ce, d.cn)
        tr = [g for g, _ in fl if g.contains(pt)]
        if tr:
            sz["grundstueck"] = max(tr, key=lambda g: g.area)
            log(f"  Projektgrundstück (ALKIS-Flurstück unter dem Mittelpunkt): {sz['grundstueck'].area:.0f} m²")
        else:
            log("  Hinweis: kein ALKIS-Flurstück unter dem Mittelpunkt – Einsatz braucht eine Flurstücks-Datei")
    return sz


def kartendaten(cfg):
    """Für die Karte in der Oberfläche: Mittelpunkt (lat, lon) und Gebiet des IFCmap-Projekts."""
    data = projekt_lesen(cfg["ifcmap"]["projekt"])
    latlon, en = _mitte(data.get("mitte", ""))
    from pyproj import Transformer
    epsg = 25832 if "25832" in str(data.get("kbs", "")) else 25833
    if en is None:
        en = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True).transform(latlon[1], latlon[0])
    return {"mitte_en": en, "epsg": epsg, "breite": _zahl(data.get("breite"), 900),
            "hoehe": _zahl(data.get("hoehe"), 900)}
