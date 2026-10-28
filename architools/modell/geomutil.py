"""Kleine Geometrie-Helfer (alles in Modell-Millimetern)."""
import math

import numpy as np
import shapely
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Polygon
from shapely import affinity


def polys(g):
    """Alle Polygone einer beliebigen Geometrie als Liste."""
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, (MultiPolygon, GeometryCollection)):
        out = []
        for p in g.geoms:
            out += polys(p)
        return out
    return []


def lines(g):
    """Alle Linien (inkl. Polygonränder) als Liste von LineStrings."""
    if g is None or g.is_empty:
        return []
    t = g.geom_type
    if t == "LineString":
        return [g] if g.length > 0 else []
    if t == "LinearRing":
        return [LineString(g.coords)]
    if t == "Polygon":
        return lines(g.boundary)
    if hasattr(g, "geoms"):
        out = []
        for p in g.geoms:
            out += lines(p)
        return out
    return []


def clean_area(g, min_width, min_area, simplify=0.1):
    """Öffnen (schmale Stellen weg), kleine Inseln und Löcher entfernen."""
    if g.is_empty:
        return g
    g = shapely.make_valid(g)
    g = shapely.union_all(polys(g))
    r = min_width / 2.0
    if r > 0:
        g = g.buffer(-r, join_style="round").buffer(r, join_style="round")
    out = []
    for p in polys(g):
        if p.area < min_area:
            continue
        holes = [h for h in p.interiors if Polygon(h).area >= min_area]
        out.append(Polygon(p.exterior, holes))
    g = shapely.union_all(out) if out else Polygon()
    if simplify and not g.is_empty:
        g = g.simplify(simplify, preserve_topology=True)
        g = shapely.make_valid(g)
        g = shapely.union_all(polys(g)) if not g.is_empty else g
    return g


def world_to_model(x0, y0, f):
    """Affine Transformation Welt (m) -> Modell (mm)."""
    m = [f, 0, 0, f, -x0 * f, -y0 * f]
    return lambda g: affinity.affine_transform(g, m)


_FONT = None


def text_polys(text, x, y, height, angle=0.0):
    """Text als Umriss-Polygone (Modell-mm), zentriert auf (x, y)."""
    global _FONT
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath
    if _FONT is None:
        _FONT = FontProperties(family="DejaVu Sans", weight="bold")
    tp = TextPath((0, 0), text, size=height * 1.37, prop=_FONT)
    rings = [np.asarray(r) for r in tp.to_polygons() if len(r) >= 3]
    if not rings:
        return []
    # gerade/ungerade Füllregel: als Symmetrische Differenz zusammensetzen
    g = Polygon()
    for r in rings:
        p = Polygon(r)
        if p.is_valid and p.area > 0:
            g = g.symmetric_difference(p)
    minx, miny, maxx, maxy = g.bounds
    g = affinity.translate(g, -(minx + maxx) / 2, -(miny + maxy) / 2)
    if angle:
        g = affinity.rotate(g, angle, origin=(0, 0))
    g = affinity.translate(g, x, y)
    return polys(g)


def text_size(text, height):
    ps = text_polys(text, 0, 0, height)
    if not ps:
        return 0, 0
    b = shapely.union_all(ps).bounds
    return b[2] - b[0], b[3] - b[1]


def place_text(region, text, height, max_tries=200):
    """Sucht in region eine Stelle für den Text (waagerecht oder senkrecht).

    Rückgabe: Liste von Text-Polygonen oder [] wenn kein Platz.
    """
    if region is None or region.is_empty:
        return []
    w, h = text_size(text, height)
    if w == 0:
        return []
    inner = region.buffer(-(h / 2 + 0.6))
    if inner.is_empty:
        return []
    cands = []
    for p in sorted(polys(inner), key=lambda p: -p.area):
        cands.append(p.representative_point())
        ln = p.exterior
        n = int(min(max_tries, ln.length / 4)) + 1
        cands += [ln.interpolate(i / n, normalized=True) for i in range(n)]
    from shapely.prepared import prep as _prep
    prep = _prep(region.buffer(-0.4))
    for pt in cands[:max_tries]:
        for ang in (0, 90):
            ww, hh = (w, h) if ang == 0 else (h, w)
            rect = shapely.box(pt.x - ww / 2, pt.y - hh / 2, pt.x + ww / 2, pt.y + hh / 2)
            if prep.contains(rect):
                return text_polys(text, pt.x, pt.y, height, ang)
    return []


def rahmen_polygon(cx, cy, b, h, drehung_grad=0.0):
    """Rahmen (Weltkoordinaten): Rechteck b x h um (cx, cy), im Uhrzeigersinn um drehung_grad gedreht."""
    t = math.radians(drehung_grad)
    c, s = math.cos(t), math.sin(t)
    pts = []
    for u, v in ((-b / 2, -h / 2), (b / 2, -h / 2), (b / 2, h / 2), (-b / 2, h / 2)):
        pts.append((cx + c * u + s * v, cy - s * u + c * v))
    return Polygon(pts)


def rahmen_transform(cx, cy, b, h, drehung_grad, f):
    """Welt -> Modell (mm) für einen gedrehten Rahmen: Rahmen liegt danach achsparallel bei (0, 0).
    Rückgabe: (shapely-Funktion, numpy Welt->Modell, numpy Modell->Welt)"""
    t = math.radians(drehung_grad)
    c, s = math.cos(t), math.sin(t)
    # u = c (x-cx) - s (y-cy), v = s (x-cx) + c (y-cy); Modell = f (u + b/2, v + h/2)
    m = [f * c, -f * s, f * s, f * c,
         f * (-c * cx + s * cy + b / 2), f * (-s * cx - c * cy + h / 2)]

    def shp(g):
        return affinity.affine_transform(g, m)

    def zu_modell(xy):
        xy = np.asarray(xy, float)
        x, y = xy[:, 0] - cx, xy[:, 1] - cy
        return np.c_[f * (c * x - s * y + b / 2), f * (s * x + c * y + h / 2)]

    def zu_welt(xy):
        xy = np.asarray(xy, float)
        u, v = xy[:, 0] / f - b / 2, xy[:, 1] / f - h / 2
        return np.c_[cx + c * u + s * v, cy - s * u + c * v]
    return shp, zu_modell, zu_welt
