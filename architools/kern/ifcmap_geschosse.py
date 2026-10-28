"""Geschosslinien: waagerechte Linien (schmale Baender) an den LoD2-Waenden, die die Geschosse andeuten.

Das ist KEINE Fassadenabbildung. Es gibt nur die Geschosszahl her, und die kommt - in dieser Reihenfolge - aus
  1. dem LoD2 (storeysAboveGround, falls vorhanden),
  2. ALKIS (Berlin, Attribut 'aog' = Anzahl oberirdischer Geschosse),
  3. OpenStreetMap (building:levels),
  4. sonst (nur Modus 'auto') geschaetzt: Hoehe von Gelaende bis Traufe / 3,1 m, gerundet.
Die Linien teilen die Traufhoehe gleichmaessig in diese Geschosse; die echten Geschosshoehen sind nicht bekannt.
Jedes Band liegt 3 cm vor der Wand, 4 cm hoch (flach - so bleibt es in Archicad leicht).
"""
import numpy as np

GESCHOSS_M = 3.1
BAND_H = 0.04
VOR = 0.03
MIN_WAND_H = 2.5


def _zahl(v, lo=0.5, hi=100):
    try:
        x = float(str(v).replace(",", ".").strip().split()[0])
    except (ValueError, IndexError):
        return None
    return x if lo <= x < hi else None


def _aog(props):
    for k, v in (props or {}).items():
        kl = str(k).lower()
        if kl == "aog" or "oberirdisch" in kl:
            x = _zahl(v)
            if x:
                return x
    return None


def _fuss(teile):
    """Grundriss des Gebaeudes (shapely) und tiefster Punkt"""
    import shapely
    from shapely.ops import unary_union
    polys = []
    zmin = None
    for t in teile:
        for e, h in (t.get("ground") or []):
            e = np.asarray(e)
            if len(e) >= 3:
                p = shapely.Polygon(e[:, :2])
                if not p.is_valid:
                    p = p.buffer(0)
                if not p.is_empty:
                    polys.append(p)
                z = float(e[:, 2].min())
                zmin = z if zmin is None else min(zmin, z)
    if not polys:
        return None, zmin
    return unary_union(polys), zmin


def _traufe(teile, zg):
    tr = []
    for t in teile:
        if t.get("roofz"):
            tr.append(float(t["roofz"][0]))
        elif t.get("roof"):
            tr.append(float(min(np.asarray(e)[:, 2].min() for e, h in t["roof"])))
    return float(min(tr)) if tr else None


def _meiste_ueberlappung(geom, baum, geoms, mind=0.5):
    best, bo = None, 0.0
    for i in baum.query(geom, predicate="intersects"):
        try:
            o = geoms[int(i)].intersection(geom).area
        except Exception:
            continue
        if o > bo:
            bo, best = o, int(i)
    return best if best is not None and bo >= mind * geom.area else None


def geschosszahl_je_gebaeude(d, je_gebaeude, modus="auto"):
    """-> {gid: (n, zg, traufe, quelle)}; modus 'daten' = nur echte Angaben (LoD2/ALKIS/OSM), 'auto' = sonst geschaetzt"""
    import shapely
    alk = getattr(d, "alk_geb", None)
    a_geoms = a_props = a_tree = None
    if alk:
        a_geoms = [g for g, p in alk if g is not None and not g.is_empty]
        a_props = [p for g, p in alk if g is not None and not g.is_empty]
        if a_geoms:
            a_tree = shapely.STRtree(a_geoms)
    osm = getattr(d, "osm_geb", None)
    o_geoms = o_tags = o_tree = None
    if osm and osm.get("objekte"):
        ob = [o for o in osm["objekte"] if o["art"] == "building" and _zahl((o["tags"] or {}).get("building:levels"))]
        if ob:
            o_geoms = [o["geom"] for o in ob]
            o_tags = [o["tags"] for o in ob]
            o_tree = shapely.STRtree(o_geoms)
    out = {}
    for gid, teile in je_gebaeude.items():
        fuss, zg = _fuss(teile)
        if fuss is None or fuss.is_empty or zg is None:
            continue
        tr = _traufe(teile, zg)
        if tr is None or tr - zg < MIN_WAND_H:
            continue
        n, q = None, None
        for t in teile:
            x = _zahl(t.get("geschosse"))
            if x:
                n, q = x, "LoD2 (storeysAboveGround)"
                break
        if n is None and a_tree is not None:
            i = _meiste_ueberlappung(fuss, a_tree, a_geoms)
            if i is not None:
                x = _aog(a_props[i])
                if x:
                    n, q = x, "ALKIS (aog)"
        if n is None and o_tree is not None:
            i = _meiste_ueberlappung(fuss, o_tree, o_geoms)
            if i is not None:
                x = _zahl(o_tags[i].get("building:levels"))
                if x:
                    n, q = x, "OpenStreetMap (building:levels)"
        if n is None and modus != "daten":
            n, q = (tr - zg) / GESCHOSS_M, "geschaetzt aus der Traufhoehe (%.1f m je Geschoss)" % GESCHOSS_M
        if n is None:
            continue
        n = max(1, int(round(n)))
        out[gid] = (n, zg, tr, q)
    return out


def _normale(p):
    n = np.zeros(3)
    for i in range(len(p)):
        n += np.cross(p[i], p[(i + 1) % len(p)])
    return n


def linien(waende, mitte_xy, n, zg, tr):
    """waende: [(ext Nx3, holes)] in Weltkoordinaten -> Array [Kx4x3] schmaler Baender an den Geschossgrenzen (n-1 Linien je Wand)"""
    import shapely
    if n < 2:
        return np.zeros((0, 4, 3))
    zs = [zg + k * (tr - zg) / n for k in range(1, n)]
    out = []
    for ext, holes in waende:
        ext = np.asarray(ext, float)
        if len(ext) < 3:
            continue
        nv = _normale(ext)
        ln = np.linalg.norm(nv)
        if ln < 1e-6:
            continue
        nv /= ln
        if abs(nv[2]) > 0.2:
            continue
        nxy = np.array([nv[0], nv[1]])
        nxy /= np.linalg.norm(nxy)
        c = ext[:, :2].mean(axis=0)
        if np.dot(c - np.asarray(mitte_xy, float), nxy) < 0:
            nxy = -nxy
        u = np.array([-nxy[1], nxy[0]])
        s = (ext[:, :2] - ext[0, :2]) @ u
        poly = shapely.Polygon(np.column_stack([s, ext[:, 2]]))
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or poly.area < 3:
            continue
        smin, zmin, smax, zmax = poly.bounds
        for z in zs:
            if z < zmin + 0.3 or z > zmax - 0.2:
                continue
            seg = poly.intersection(shapely.LineString([(smin - 1, z), (smax + 1, z)]))
            for part in getattr(seg, "geoms", [seg]):
                if part.geom_type != "LineString" or part.length < 0.4:
                    continue
                (s0, _), (s1, _) = part.coords[0], part.coords[-1]
                if s0 > s1:
                    s0, s1 = s1, s0
                P = [(s0, z - BAND_H / 2), (s1, z - BAND_H / 2), (s1, z + BAND_H / 2), (s0, z + BAND_H / 2)]
                out.append(np.array([[ext[0, 0] + u[0] * ss + nxy[0] * VOR, ext[0, 1] + u[1] * ss + nxy[1] * VOR, zz] for ss, zz in P]))
    return np.array(out) if out else np.zeros((0, 4, 3))
