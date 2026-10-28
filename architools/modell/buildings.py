"""Gebäude und Bauwerke -> geschlossene, druckbare Körper (trimesh, Modell-mm).

Prinzip LoD2: jede Dachfläche wird senkrecht bis zur Gebäudeunterkante
"heruntergezogen" (Prisma mit schräger Oberseite). Die Vereinigung aller
Prismen ist ein wasserdichter Körper mit echter Dachform, flacher Unterseite
und senkrechten Wänden – ideal für FDM ohne Stützmaterial.
"""
import numpy as np
import shapely
import trimesh
from shapely.geometry import Polygon

from .geomutil import polys
from .terrain import layer_under


try:
    import manifold3d  # noqa: F401  (optional, für echte Vereinigung der Dachprismen)
    HAS_MANIFOLD = True
except ImportError:
    HAS_MANIFOLD = False


def _union(meshes):
    meshes = [m for m in meshes if m is not None and len(m.faces)]
    if not meshes:
        return None
    if len(meshes) == 1:
        return meshes[0]
    if not HAS_MANIFOLD:
        # ohne manifold3d: Teilkörper zusammen in eine Datei; Slicer verschmelzen sich berührende Körper
        return trimesh.util.concatenate(meshes)
    try:
        u = trimesh.boolean.union(meshes, engine="manifold")
        if u is not None and len(u.faces):
            return u
    except Exception:
        pass
    return trimesh.util.concatenate(meshes)


def _prism(poly2d, plane, min_z):
    """Prisma über poly2d, Oberseite auf Ebene z = a x + b y + c."""
    a, b, c = plane
    out = []
    for p in polys(poly2d):
        if p.area < 0.05:
            continue
        try:
            m = trimesh.creation.extrude_polygon(p, height=1.0)
        except Exception:
            continue
        v = m.vertices.copy()
        top = v[:, 2] > 0.5
        v[top, 2] = np.maximum(a * v[top, 0] + b * v[top, 1] + c, min_z)
        m.vertices = v
        out.append(m)
    return out


def _block(poly2d, h):
    out = []
    for p in polys(poly2d):
        if p.area < 0.05:
            continue
        try:
            out.append(trimesh.creation.extrude_polygon(p, height=max(h, 0.3)))
        except Exception:
            pass
    return out


def _fit_plane(xyz):
    A = np.c_[xyz[:, 0], xyz[:, 1], np.ones(len(xyz))]
    sol, *_ = np.linalg.lstsq(A, xyz[:, 2], rcond=None)
    return sol


def _too_thin(fp, min_w):
    return fp.buffer(-min_w / 2.0).is_empty


def build_buildings(bldgs, extent_m, f, P, cfg, log=print):
    """bldgs: Ausgabe von read_citygml. f = mm pro m. Rückgabe: Liste von dicts."""
    gc = cfg["gebaeude"]
    min_w = float(gc["min_breite_mm"])
    min_h = float(gc["min_hoehe_mm"])
    eps = 0.02
    tm_xy, tw_xy = cfg["_tm_xy"], cfg["_tw_xy"]
    center = gc.get("nahzone_mitte")
    radius = gc.get("nahzone_radius_m")
    if center in (None, "", []):
        c = cfg["_extent_world"].centroid
        center = (c.x, c.y)
    platz = set(gc.get("platzhalter_ids") or [])
    sep = set(gc.get("separat_ids") or [])

    def tm(xy):
        return tm_xy(np.asarray(xy)[:, :2])

    if not HAS_MANIFOLD:
        log("  Hinweis: manifold3d fehlt – Dachflächen werden als einzelne, sich berührende Körper "
            "exportiert (Slicer verschmelzen sie beim Slicen).")
    res = []
    for b in bldgs:
        zmin = b["zmin"]
        prisms, fps = [], []
        roof_xy = []
        for ext, ints in b["roofs"]:
            e2 = tm(ext)
            p = shapely.make_valid(Polygon(e2, [tm(i) for i in ints if len(i) >= 4]))
            p = p.intersection(extent_m)
            if p.is_empty or p.area < 0.05:
                continue
            xyz = np.c_[e2, (ext[:, 2] - zmin) * f]
            fps.append(p)
            roof_xy.append(xyz)
            prisms.append((p.buffer(eps, join_style="mitre"), _fit_plane(xyz)))
        if not fps and b["grounds"]:
            for ext, ints in b["grounds"]:
                p = shapely.make_valid(Polygon(tm(ext), [tm(i) for i in ints if len(i) >= 4]))
                fps.append(p.intersection(extent_m))
        fp = shapely.union_all(fps) if fps else Polygon()
        fp = shapely.union_all(polys(fp)) if not fp.is_empty else fp
        if fp.is_empty or fp.area < 0.2:
            continue
        height = (b["zmax"] - zmin) * f
        if b.get("measured_height") and not b["roofs"]:
            height = b["measured_height"] * f
        cw = fp.centroid
        world_c = tuple(tw_xy([[cw.x, cw.y]])[0])
        in_near = radius in (None, "", 0) or \
            np.hypot(world_c[0] - center[0], world_c[1] - center[1]) <= float(radius)
        status = "druck"
        if b["id"] in platz:
            status = "platzhalter"
        elif _too_thin(fp, min_w) or height < min_h:
            status = "gravur" if gc["zu_klein"] == "gravieren" else "verstaerkt"
        mesh = None
        if status == "druck":
            if in_near and prisms:
                parts = []
                for poly, plane in prisms:
                    parts += _prism(poly, plane, min_z=min(0.3, height))
                mesh = _union(parts)
            else:
                mesh = _union(_block(fp, height))
        elif status == "verstaerkt":
            fat = fp.buffer(min_w / 2.0).buffer(-min_w / 4.0)
            mesh = _union(_block(fat, max(height, min_h)))
            fp = shapely.union_all(polys(fat))
            status = "druck"
        k = layer_under(P, fp)
        res.append({"gml_id": b["id"], "footprint": fp, "mesh": mesh, "status": status,
                    "height_mm": height, "layer": k, "gruppe": "einsatz" if b["id"] in sep else "umgebung",
                    "art": "Gebäude", "lod": "LoD2" if (in_near and prisms) else "Block"})
    log(f"  Gebäude: {sum(r['status']=='druck' for r in res)} druckbar, "
        f"{sum(r['status']=='gravur' for r in res)} nur graviert (zu klein), "
        f"{sum(r['status']=='platzhalter' for r in res)} Platzhalter")
    return res


def build_blocks_from_footprints(items, to_model, extent_m, f, P, cfg, art, height_of, width_m=0.0):
    """Grundrisse/Bauwerke als Blöcke. items: [(geom_world, attrs)]."""
    gc = cfg["gebaeude"]
    min_w = float(gc["min_breite_mm"])
    out = []
    for g, attrs in items:
        if width_m and g.geom_type in ("LineString", "MultiLineString"):
            g = g.buffer(width_m / 2.0, cap_style="flat")
        gm = to_model(g).intersection(extent_m)
        fp = shapely.union_all(polys(gm)) if not gm.is_empty else gm
        if fp.is_empty or fp.area < 0.2:
            continue
        h = height_of(attrs) * f
        status = "druck"
        if _too_thin(fp, min_w) or h < gc["min_hoehe_mm"]:
            if gc["zu_klein"] == "gravieren":
                status = "gravur"
            else:
                fp = shapely.union_all(polys(fp.buffer(min_w / 2.0)))
                h = max(h, gc["min_hoehe_mm"])
        mesh = _union(_block(fp, h)) if status == "druck" else None
        out.append({"gml_id": str(attrs.get("gml_id") or attrs.get("id") or ""), "footprint": fp,
                    "mesh": mesh, "status": status, "height_mm": h,
                    "layer": layer_under(P, fp),
                    "gruppe": "umgebung", "art": art, "lod": "Block"})
    return out


def number_buildings(items):
    """Nummern in Leserichtung (oben links -> unten rechts)."""
    items.sort(key=lambda b: (-round(b["footprint"].centroid.y / 20), b["footprint"].centroid.x))
    for i, b in enumerate(items, 1):
        pre = "B" if b["art"] != "Gebäude" else "G"
        b["nr"] = f"{pre}{i:03d}"
    return items
