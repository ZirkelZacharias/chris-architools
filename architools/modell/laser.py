"""Schichtflächen -> Laserteile (Schnitt, Gravur, Beschriftung, Kachelung)."""
import math

import numpy as np
import shapely
from shapely.geometry import LineString, Point, box

from .geomutil import lines, place_text, polys


def _rib_grid(bounds, spacing, width):
    xmin, ymin, xmax, ymax = bounds
    ls = []
    xs = np.arange(math.floor(xmin / spacing) * spacing, xmax + spacing, spacing)
    ys = np.arange(math.floor(ymin / spacing) * spacing, ymax + spacing, spacing)
    for x in xs:
        ls.append(LineString([(x, ymin - 1), (x, ymax + 1)]))
    for y in ys:
        ls.append(LineString([(xmin - 1, y), (xmax + 1, y)]))
    return shapely.union_all([l.buffer(width / 2.0, cap_style="flat") for l in ls]), xs, ys


# Eingebaute Ebenen auf den Geländeplatten und ihre Vorgaben
EBENEN_STANDARD = {
    "Anlegekante nächste Schicht": "ritzen",
    "Gebäudeumrisse": "ritzen",
    "Gebäudenummern": "gravieren",
    "Teile-IDs": "gravieren",
    "Rippen-/Klotzmarken": "ritzen",
}
AKTIONEN = ("ritzen", "gravieren", "raster", "schneiden", "aus")


def aktion(cfg, name):
    e = (cfg.get("ebenen") or {}).get(name)
    if isinstance(e, dict):
        return e.get("aktion", EBENEN_STANDARD.get(name, "ritzen"))
    return e or EBENEN_STANDARD.get(name, "ritzen")


def _raster(geom, raster):
    """Linienraster über das Zusatzmodul (Rastergravur-Plugin); ohne Modul wird die Fläche voll graviert."""
    from .. import zusatz
    grau, weite = raster or (50.0, 0.8)
    r = zusatz.erstes("raster_flaechen", geom, grau, weite)
    return r if r is not None else polys(geom)


def _anwenden(geom, typ, akt, region, d_mm=1.5, breite_mm=0.0, raster=None):
    """Geometrie einer Ebene auf eine Platte anwenden. -> (ritz-Linien, Gravurflächen, Schnittlöcher)"""
    rz, gv, cut = [], [], []
    if akt == "aus" or geom.is_empty:
        return rz, gv, cut
    if typ == "punkt":
        rr = max(d_mm, 0.8) / 2.0
        for pt in getattr(geom, "geoms", [geom]):
            if not region.buffer(-(rr + 0.8)).contains(pt):
                continue
            c = pt.buffer(rr, 16)
            if akt == "schneiden":
                cut.append(c)
            elif akt in ("gravieren", "raster"):
                gv.append(c)
            else:
                rz += lines(c.exterior)
    elif typ == "flaeche":
        if akt == "raster":
            gv += _raster(geom.intersection(region.buffer(-0.3)), raster)
        elif akt == "gravieren":
            gv += polys(geom.intersection(region))
        elif akt == "schneiden":
            cut += polys(geom.intersection(region.buffer(-1.0)))
        else:
            rz += lines(geom.boundary.intersection(region))
    else:                                          # Linie
        if akt == "raster":
            gv += _raster(geom.buffer(max(breite_mm, 1.5) / 2.0, cap_style="flat").intersection(region.buffer(-0.3)), raster)
        elif akt == "gravieren":
            gv += polys(geom.buffer(max(breite_mm, 0.8) / 2.0, cap_style="flat").intersection(region))
        else:                                      # schneiden von offenen Linien ergibt keinen Sinn -> ritzen
            rz += lines(geom.intersection(region))
    return rz, gv, cut


def _text(text, region, hoehe, akt):
    if akt == "aus":
        return [], []
    t = place_text(region, text, hoehe)
    if not t:
        t = place_text(region, text, max(1.8, hoehe * 0.6))
    if akt == "ritzen":
        return [l for p in t for l in lines(p.boundary)], []
    return [], t


def bauweise(cfg):
    g = cfg["gelaende"]
    b = g.get("bauweise")
    if b:
        return b
    h = g.get("hohlbau")                      # alte Projektdateien
    return {"ringe": "stuetzkloetze", True: "stuetzkloetze", "gitter": "steckrippen"}.get(h, "voll")


def make_parts(P, buildings, features, cfg, log=print):
    """Schichtflächen -> Laserteile.

    features: Liste dict(name, geom (Modell-mm), typ "punkt"/"linie"/"flaeche", aktion, d, breite_mm)
    Rückgabe: (teile, Q, stuetzen, rippen)
    """
    from .rippen import steckrippen
    g = cfg["gelaende"]
    n = len(P) - 1
    gap = 0.3
    t = float(g["schichtdicke_mm"])
    weise = bauweise(cfg)

    # 1) Aussparungen für Gebäude, die tiefer stehen als höhere Schichten
    Q = list(P)
    if g.get("gebaeude_aussparen", True):
        for j in range(1, n + 1):
            cut = [b["footprint"].buffer(gap) for b in buildings
                   if b["layer"] < j and b["footprint"].intersects(P[j])]
            if cut:
                Q[j] = P[j].difference(shapely.union_all(cut))
    # 2) Hohlräume
    abst = float(g.get("rippen_abstand_mm", 80.0))
    xmin, ymin, xmax, ymax = P[0].bounds
    if weise == "steckrippen":                 # Rippen auf Zellmitten, Passlöcher in Zellmitten versetzt
        gx = np.arange(xmin + abst / 2, xmax, abst)
        gy = np.arange(ymin + abst / 2, ymax, abst)
        px = np.arange(xmin + abst, xmax, abst)
        py = np.arange(ymin + abst, ymax, abst)
    else:
        gx = np.arange(math.floor(xmin / abst) * abst, xmax + abst, abst)
        gy = np.arange(math.floor(ymin / abst) * abst, ymax + abst, abst)
        px, py = gx, gy
    hollow = [None] * (n + 1)
    if weise != "voll":
        for k in range(n):
            if k == 0 and g.get("unterste_schicht_voll", True):
                continue
            inner = Q[k + 1].buffer(-g["auflage_rand_mm"])
            if not inner.is_empty:
                hollow[k] = inner
        # Mindesttiefe: Hohlräume flacher als min_hohl_mm werden wieder gefüllt (keine Mini-Rippen/-Säulen).
        # Die Hohlräume sind ineinander geschachtelt (H[k+1] liegt in H[k]), die Tiefe zählt ab Schicht 1.
        tiefe = max(1, math.ceil(float(g.get("min_hohl_mm", 8.0)) / t))
        if tiefe > 1 and tiefe <= n:
            ziel = hollow[tiefe] if tiefe < len(hollow) else None
            for k in range(1, min(tiefe, n)):
                hollow[k] = ziel if ziel is not None and not ziel.is_empty else None
        elif tiefe > n:
            hollow = [None] * (n + 1)
    M = [Q[k].difference(hollow[k]) if hollow[k] is not None else Q[k] for k in range(n + 1)]
    marken = {}                                  # Schicht -> [LineString]
    marken_txt = []                              # (Schicht, Text, Region)
    blocks, rippen = [], []
    s = float(g.get("stuetze_mm", 15.0))
    if weise == "stuetzkloetze":
        sup = [Point(x, y) for x in gx for y in gy]
        for k in range(n + 1):
            hl = hollow[k]
            if hl is None:
                continue
            ok = hl.buffer(-(s / 2 + 1.0))
            for p in sup:
                if ok.contains(p):
                    blocks.append((k, p))
                    below = k - 1
                    if below >= 0 and (hollow[below] is None or not hollow[below].contains(p)):
                        sq = box(p.x - s / 2, p.y - s / 2, p.x + s / 2, p.y + s / 2)
                        marken.setdefault(below, []).append(sq.exterior)
        if blocks:
            log(f"  {len(blocks)} Stützklötze {s:.0f} × {s:.0f} mm "
                f"({len(set((p.x, p.y) for _, p in blocks))} Säulen)")
    elif weise == "steckrippen":
        rippen, rm = steckrippen(M, t, abst, P[0], log=log)
        for seg, rid in rm:
            marken.setdefault(0, []).append(seg)
            marken_txt.append((0, rid, seg.buffer(6, cap_style="flat")))
    # 3) Passlöcher
    holes_pts = []
    if g.get("passloecher"):
        step = max(1, int(round(g["passloch_abstand_mm"] / abst)))
        for ix, x in enumerate(px):
            for iy, y in enumerate(py):
                if ix % step == 0 and iy % step == 0:
                    holes_pts.append(Point(x, y))
    r_h = g["passloch_d_mm"] / 2.0
    gb = cfg["gebaeude"]
    a_anl = aktion(cfg, "Anlegekante nächste Schicht")
    a_geb = aktion(cfg, "Gebäudeumrisse")
    a_nr = aktion(cfg, "Gebäudenummern")
    a_mk = aktion(cfg, "Rippen-/Klotzmarken")
    rasterbild = cfg.get("_rasterbild")             # Funktion Region -> Gravurpolygone (Rastergravur Bild, experimentell)
    stift_t = stift_r = None
    if gb.get("stifte") and gb.get("modus", "druck") == "druck" and any(b.get("stifte") for b in buildings):
        stift_t = max(2.0, float(gb.get("stift_laenge_mm") or 4.0) / 2.0)
        stift_r = (float(gb.get("stift_d_mm") or 2.0) + float(gb.get("stift_spiel_mm") or 0.2)) / 2.0
        log(f"  Steckstifte: Löcher Ø {2 * stift_r:.1f} mm, {stift_t:.0f} mm tief unter {sum(1 for b in buildings if b.get('stifte'))} Gebäuden")
    parts = []
    for k in range(n + 1):
        part = M[k]
        if k < n and holes_pts:
            cover = Q[k + 1].buffer(-(r_h + 2.0))
            hs = [p.buffer(r_h, 24) for p in holes_pts
                  if cover.contains(p) and part.buffer(-(r_h + 1.5)).contains(p)]
            if hs:
                part = part.difference(shapely.union_all(hs))
        if stift_t is not None:                      # Steckstift-Löcher unter den Gebäuden (Sacklöcher -> durchgeschnitten)
            sl = []
            for b in buildings:
                if b.get("stifte") and 0 <= b["layer"] - k < max(1, math.ceil(stift_t / t - 1e-6)):
                    sl += [Point(x, y).buffer(stift_r, 16) for x, y in b["stifte"]]
            if sl:
                part = part.difference(shapely.union_all(sl))
        visible = Q[k].difference(Q[k + 1]) if k < n else Q[k]
        rz, gv, cut = [], [], []
        if k < n:
            r_, g_, _ = _anwenden(Q[k + 1].boundary, "linie", a_anl, part.buffer(0.01))
            rz += r_
            gv += g_
        for mk in marken.get(k, []):
            r_, g_, _ = _anwenden(mk if mk.geom_type == "LineString" else shapely.LineString(mk.coords),
                                  "linie", a_mk, part.buffer(0.01))
            rz += r_
            gv += g_
        for kk, txt, reg in marken_txt:
            if kk == k:
                r_, g_ = _text(txt, reg.intersection(part), 2.5, a_mk if a_mk != "schneiden" else "ritzen")
                rz += r_
                gv += g_
        for b in buildings:
            if b["layer"] == k:
                r_, g_, c_ = _anwenden(b["footprint"], "flaeche", a_geb, visible.buffer(0.01))
                rz += r_
                gv += g_
                cut += c_
        for feat in features:
            fg = feat["geom"]
            if fg.is_empty or not fg.intersects(visible):
                continue
            r_, g_, c_ = _anwenden(fg, feat["typ"], feat["aktion"], visible, feat.get("d", 1.5),
                                   feat.get("breite_mm", 0.0), feat.get("raster"))
            rz += r_
            gv += g_
            cut += c_
        if cut:
            part = part.difference(shapely.union_all(cut))
        raster_mm2 = 0.0
        if rasterbild is not None:
            reg = visible.intersection(part.buffer(-0.3))
            if not reg.is_empty:
                gv += rasterbild(reg)
                raster_mm2 = reg.area
        txt_r, txt_g = [], []
        if gb.get("beschriften", True):
            for b in buildings:
                if b["layer"] == k and b.get("nr"):
                    r_, g_ = _text(b["nr"], b["footprint"].intersection(part), gb["beschriftung_hoehe_mm"],
                                   a_nr if a_nr != "schneiden" else "ritzen")
                    txt_r += r_
                    txt_g += g_
        for i, comp in enumerate(sorted(polys(part), key=lambda p: -p.area), 1):
            c2 = comp.buffer(0.01)
            parts.append({"layer": k, "nr": i, "poly": comp,
                          "ritzen": [x for l in rz + txt_r if l.intersects(c2) for x in lines(l.intersection(c2))],
                          "gravieren": [x for p in gv + txt_g if p.intersects(comp) for x in polys(p.intersection(comp))],
                          "hidden": Q[k + 1] if k < n else None,
                          "raster_mm2": raster_mm2 * comp.area / max(part.area, 1.0) if raster_mm2 else 0.0})
    log(f"  {len(parts)} Laserteile auf {n + 1} Schichten (inkl. Grundplatte), Bauweise: {weise}")
    stuetzen = []
    for k, p in blocks:
        sq = box(-s / 2, -s / 2, s / 2, s / 2)
        if g.get("passloecher") and s > 2 * r_h + 4:
            sq = sq.difference(Point(0, 0).buffer(r_h, 24))
        stuetzen.append({"layer": k, "pos": (p.x, p.y), "poly": sq})
    return parts, Q, stuetzen, rippen


def _clip_part(part, cell):
    out = []
    for comp in polys(part["poly"].intersection(cell)):
        if comp.area < 1.0:
            continue
        hid = part.get("hidden")
        if comp.area < 400 and hid is not None and comp.difference(hid).area < 1.0:
            continue          # kleiner, vollständig verdeckter Rippen-/Ringstummel an einer Kachelfuge
        c2 = comp.buffer(0.01)
        out.append({**part, "poly": comp,
                    "ritzen": [x for l in part["ritzen"] for x in lines(l.intersection(c2))],
                    "gravieren": [x for g in part["gravieren"] for x in polys(g.intersection(comp))]})
    return out


def tile_parts(parts, formats, margin, log=print, split_sparse=True, sparse_len=250.0):
    """Teile, die auf keine Platte passen, in Kacheln zerlegen (Fugen je Schicht versetzt).

    Zusätzlich werden lange, dünne Ringteile in Stücke von sparse_len geteilt, damit sie
    sich dicht packen lassen.
    """
    W = max(f[0] for f in formats) - 2 * margin - 4
    H = max(f[1] for f in formats) - 2 * margin - 4
    out = []
    n_split = 0
    for p in parts:
        mrr = p["poly"].minimum_rotated_rectangle
        xs, ys = mrr.exterior.coords.xy
        e1 = math.hypot(xs[1] - xs[0], ys[1] - ys[0])
        e2 = math.hypot(xs[2] - xs[1], ys[2] - ys[1])
        a, b = max(e1, e2), min(e1, e2)
        fits = (a <= W and b <= H) or (a <= H and b <= W)
        # dünne, weitläufige Ringe nesten schlecht -> in kürzere Stücke teilen
        sparse = split_sparse and a > sparse_len and p["poly"].area < 0.3 * mrr.area
        if fits and not sparse:
            out.append(p)
            continue
        n_split += 1
        minx, miny, maxx, maxy = p["poly"].bounds
        if fits:
            tw = th = sparse_len
        else:
            tw, th = (W, H) if (maxx - minx) >= (maxy - miny) else (H, W)
            tw, th = tw * 0.97, th * 0.97
        off = 0.5 if p["layer"] % 2 else 0.0
        if p.get("rippe"):                       # Rippen nur in der Länge teilen
            minx, miny, maxx, maxy = p["poly"].bounds
            lmax = (W if not fits else sparse_len) * 0.97
            tw = (maxx - minx) / math.ceil((maxx - minx) / lmax) + 1e-6
            th, off = (maxy - miny) + 10, 0.0
        x = minx - off * tw
        tiles = []
        while x < maxx:
            y = miny - off * th
            while y < maxy:
                tiles += _clip_part(p, box(x, y, x + tw, y + th))
                y += th
            x += tw
        out += tiles
    if n_split:
        log(f"  {n_split} Teile gekachelt (zu groß für die Platte oder lange dünne Ringe)")
    return out


def rahmen_teile(grenzen, n_schichten, breite_mm, spiel=0.5):
    """Rahmen ums Modell als Laserteile: je Schicht vier Leisten (die langen laufen durch, die kurzen sitzen dazwischen).
    grenzen = (x0, y0, x1, y1) des Modells in mm. -> Liste Teile (wie make_parts)."""
    x0, y0, x1, y1 = grenzen
    b = float(breite_mm)
    ix0, iy0, ix1, iy1 = x0 - spiel, y0 - spiel, x1 + spiel, y1 + spiel
    leisten = [box(ix0 - b, iy0 - b, ix1 + b, iy0), box(ix0 - b, iy1, ix1 + b, iy1 + b),        # unten, oben (durchgehend)
               box(ix0 - b, iy0, ix0, iy1), box(ix1, iy0, ix1 + b, iy1)]                         # links, rechts (dazwischen)
    out = []
    for k in range(int(n_schichten)):
        for i, r in enumerate(leisten, 1):
            out.append({"layer": k, "nr": i, "poly": r, "ritzen": [], "gravieren": [], "hidden": None, "raster_mm2": 0.0, "rahmen": True})
    return out


def finalize_ids(parts, cfg, praefix=""):
    """Teile-IDs vergeben und (verdeckt, falls möglich) aufbringen."""
    th = cfg["gelaende"]["beschriftung_hoehe_mm"]
    akt = aktion(cfg, "Teile-IDs")
    akt = "ritzen" if akt == "schneiden" else akt
    by_layer = {}
    for p in parts:
        if p.get("rippe"):
            continue
        by_layer.setdefault(p["layer"], []).append(p)
    for k, ps in by_layer.items():
        ps.sort(key=lambda p: (-p["poly"].area))
        for i, p in enumerate(ps, 1):
            p["id"] = f"{praefix}S{k:02d}-{i}"
            if akt == "aus":
                continue
            hidden = p.get("hidden")
            region = p["poly"].intersection(hidden) if hidden is not None else None
            r_, g_ = _text(p["id"], region, th, akt) if region is not None and not region.is_empty else ([], [])
            if not (r_ or g_):
                r_, g_ = _text(p["id"], p["poly"], th, akt)
            p["ritzen"] = p["ritzen"] + r_
            p["gravieren"] = p["gravieren"] + g_
    # Rippen-Stücke nach dem Kacheln neu nummerieren
    zaehl = {}
    for p in parts:
        if p.get("rippe"):
            base = p["id"].rsplit("-", 1)[0]
            zaehl[base] = zaehl.get(base, 0) + 1
            p["id"] = f"{base}-{zaehl[base]}"
    return parts
