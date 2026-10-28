"""3D-Druck: Körper auf Druckbetten verteilen und Werkzeug „3D → druckbar“.

Werkzeug „3D → druckbar“ liest STL, OBJ, 3MF, PLY, IFC und CityGML, skaliert auf den
Modellmaßstab, macht die Körper druckbar (geschlossen, flache Unterseite) und verteilt sie
auf das Druckbett. Zu große Teile werden geteilt.
"""
import math
import os
import re

import numpy as np
import shapely
import trimesh
from shapely.geometry import Polygon

from . import bibliothek as BIB
from . import nesting as N
from .geomutil import polys

try:
    import manifold3d  # noqa: F401
    HAS_MANIFOLD = True
except ImportError:
    HAS_MANIFOLD = False


def stl(pfad, meshes):
    meshes = [m for m in meshes if m is not None and len(m.faces)]
    if not meshes:
        return
    (trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]).export(pfad)


def umriss(mesh):
    """Grundriss (Projektion nach unten) eines Körpers als Polygon."""
    try:
        tri = mesh.vertices[mesh.faces][:, :, :2]
        ps = [Polygon(t) for t in tri if abs(Polygon(t).area) > 1e-6]
        g = shapely.union_all([p.buffer(0.01) for p in ps])
        g = shapely.union_all(polys(g))
        return g.buffer(-0.01) if not g.is_empty else g
    except Exception:
        b = mesh.bounds
        return shapely.box(b[0][0], b[0][1], b[1][0], b[1][1])


def place_mesh(mesh, ang, dx, dy):
    m = mesh.copy()
    T = trimesh.transformations.rotation_matrix(np.radians(ang), [0, 0, 1])
    T[0, 3] += dx
    T[1, 3] += dy
    m.apply_transform(T)
    return m


def auf_betten(items, cfg, praefix, log=print, gruppe=""):
    """items: [{id, mesh, fp, ref?}] (mm, Unterseite z = 0). Schreibt praefix_01.stl ... -> Liste Druckplatten."""
    dc = cfg["druck"]
    bett, hmax = BIB.druckbett(cfg)
    for it in items:
        h = float(it["mesh"].bounds[1][2] - it["mesh"].bounds[0][2])
        if h > hmax:
            log(f"  WARNUNG: {it['id']} ist {h:.0f} mm hoch – Drucker schafft {hmax:.0f} mm")
    schritt = int(dc.get("drehschritt_grad", 90)) or 90
    angs = list(range(0, 360, schritt))
    its = [N.Item(i, it["fp"].buffer(0.2), angs) for i, it in enumerate(items)]
    pl, rest = N.nest(its, [bett], float(dc.get("rand_mm", 5)), float(dc.get("abstand_mm", 3)),
                      float(dc.get("nesting_raster_mm", 1.0)), log, "Druckplatte " + gruppe)
    for it in [items[i.key] for i in rest]:
        log(f"  {it['id']} passt nicht aufs Druckbett – nur als Einzeldatei")
    out = []
    for pi, s in enumerate(pl, 1):
        meshes, drawn = [], []
        name = f"{os.path.basename(praefix)}_{pi:02d}"
        for it, ang, dx, dy in s["placements"]:
            e = items[it.key]
            meshes.append(place_mesh(e["mesh"], ang, dx, dy))
            fp = N.place(e["fp"], ang, dx, dy)
            big = max(polys(fp), key=lambda g: g.area) if polys(fp) else fp
            drawn.append((e["id"], list(big.exterior.coords)))
            if e.get("ref") is not None:
                e["ref"]["druckplatte"] = name
        datei = f"{praefix}_{pi:02d}.stl"
        stl(datei, meshes)
        out.append({"name": name, "format": s["format"], "datei": datei, "teile": drawn})
    return out


# ------------------------------------------------------------------ Werkzeug 3D -> druckbar
def _laden_trimesh(pfad):
    sc = trimesh.load(pfad, force="scene")
    out = []
    for name, geom in sc.geometry.items():
        if not isinstance(geom, trimesh.Trimesh):
            continue
        # Szenengraph-Transformationen anwenden
        for node in sc.graph.geometry_nodes.get(name, []):
            T, _ = sc.graph.get(node)
            m = geom.copy()
            m.apply_transform(T)
            out.append((str(name), m))
        if name not in sc.graph.geometry_nodes:
            out.append((str(name), geom.copy()))
    return out


IFC_WEG = ("IfcOpeningElement", "IfcSpace", "IfcAnnotation", "IfcVirtualElement", "IfcGrid")


def _laden_ifc(pfad, log, klassen_weg=IFC_WEG):
    try:
        import ifcopenshell
        import ifcopenshell.geom
    except ImportError:
        raise RuntimeError("Für IFC wird das Paket ifcopenshell gebraucht (start.bat installiert es, "
                           "wenn es für deine Python-Version verfügbar ist – Python 3.12 empfohlen).")
    f = ifcopenshell.open(pfad)
    st = ifcopenshell.geom.settings()
    st.set("use-world-coords", True)
    out = []
    it = ifcopenshell.geom.iterator(st, f, include=f.by_type("IfcProduct"))
    if not it.initialize():
        return out
    n_weg = 0
    while True:
        sh = it.get()
        el = f.by_id(sh.id)
        if el.is_a() in klassen_weg or any(el.is_a(k) for k in klassen_weg):
            n_weg += 1
        else:
            g = sh.geometry
            v = np.array(g.verts, float).reshape(-1, 3)
            fc = np.array(g.faces, int).reshape(-1, 3)
            if len(fc):
                name = f"{el.is_a()}_{getattr(el, 'Name', '') or el.GlobalId}"
                out.append((name, trimesh.Trimesh(v, fc, process=True)))
        if not it.next():
            break
    log(f"  IFC: {len(out)} Bauteile gelesen, {n_weg} ausgelassen (Öffnungen, Räume …)")
    return out


def _massiv(mesh, min_flaeche=0.02):
    """2,5D-Massivkörper: alle nach oben zeigenden Flächen senkrecht bis zur Unterkante ziehen
    und vereinigen. Ergebnis: geschlossen, ohne Innenräume, flache Unterseite."""
    z0 = float(mesh.bounds[0][2])
    n = mesh.face_normals
    up = n[:, 2] > 0.05
    if not up.any():
        return None
    tri = mesh.triangles[up]
    nn = n[up]
    d = -np.einsum("ij,ij->i", nn, tri[:, 0, :])
    key = np.round(np.c_[nn * 200, d * 20]).astype(np.int64)
    gruppen = {}
    for i, k in enumerate(map(tuple, key)):
        gruppen.setdefault(k, []).append(i)
    prismen = []
    for idx in gruppen.values():
        ps = [Polygon(tri[i][:, :2]) for i in idx]
        g = shapely.union_all([p.buffer(0.002, join_style="mitre") for p in ps if p.area > 1e-9])
        g = g.buffer(-0.002, join_style="mitre").simplify(0.01, preserve_topology=True)
        g = shapely.set_precision(shapely.make_valid(g), 0.001)
        if g.is_empty or g.area < min_flaeche:
            continue
        a_, b_, c_ = nn[idx[0]]
        dd = d[idx[0]]
        plane = (-a_ / c_, -b_ / c_, -dd / c_)
        for p in polys(g):
            try:
                m = trimesh.creation.extrude_polygon(p, height=1.0)
            except Exception:
                continue
            v = m.vertices.copy()
            top = v[:, 2] > 0.5
            v[top, 2] = plane[0] * v[top, 0] + plane[1] * v[top, 1] + plane[2]
            v[~top, 2] = z0
            v[top, 2] = np.maximum(v[top, 2], z0 + 0.05)
            m.vertices = v
            prismen.append(m)
    return _saeubern(vereinigen(prismen))


def _saeubern(m):
    """Nach Boolean-Operationen: Splitterflächen entfernen, damit der Körper auch als STL (float32) dicht bleibt."""
    if m is None:
        return m
    m = m.copy()
    m.merge_vertices(digits_vertex=4)
    m.update_faces(m.nondegenerate_faces())
    m.remove_unreferenced_vertices()
    if not m.is_watertight:
        trimesh.repair.fill_holes(m)
    trimesh.repair.fix_normals(m)
    return m


def vereinigen(meshes):
    meshes = [m for m in meshes if m is not None and len(m.faces)]
    if not meshes:
        return None
    if len(meshes) == 1:
        return meshes[0]
    if HAS_MANIFOLD:
        try:
            u = trimesh.boolean.union(meshes, engine="manifold")
            if u is not None and len(u.faces):
                return u
        except Exception:
            pass
    return trimesh.util.concatenate(meshes)


def _reparieren(m):
    m = m.copy()
    m.merge_vertices()
    m.update_faces(m.nondegenerate_faces())
    m.update_faces(m.unique_faces())
    m.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(m)
    if not m.is_watertight:
        trimesh.repair.fill_holes(m)
    return m


def _teilen(m, bett, hmax, rand):
    """Körper, die größer als das Bett sind, mit senkrechten Schnitten teilen (Schnittflächen geschlossen)."""
    W, H = bett[0] - 2 * rand, bett[1] - 2 * rand
    (x0, y0, _), (x1, y1, _) = m.bounds
    nx = max(1, math.ceil((x1 - x0) / W))
    ny = max(1, math.ceil((y1 - y0) / H))
    if nx * ny == 1:
        return [m]
    stuecke = []
    for i in range(nx):
        for j in range(ny):
            s = m
            xa, xb = x0 + i * (x1 - x0) / nx, x0 + (i + 1) * (x1 - x0) / nx
            ya, yb = y0 + j * (y1 - y0) / ny, y0 + (j + 1) * (y1 - y0) / ny
            try:
                for o, nrm in (((xa, 0, 0), (1, 0, 0)), ((xb, 0, 0), (-1, 0, 0)),
                               ((0, ya, 0), (0, 1, 0)), ((0, yb, 0), (0, -1, 0))):
                    s = s.slice_plane(o, nrm, cap=True)
                    if s is None or not len(s.faces):
                        break
            except Exception:
                s = None
            if s is not None and len(s.faces):
                stuecke.append(s)
    return stuecke


def druckbar(cfg_werkzeug, cfg, log=print):
    """Werkzeug 3D -> druckbar.

    cfg_werkzeug: dateien [Pfade], einheit "m"|"cm"|"mm", massstab, modus "massiv"|"original",
                  zusammenfassen bool, min_wand_mm, ausgabe_ordner, name
    """
    w = cfg_werkzeug
    f_einheit = {"m": 1000.0, "cm": 10.0, "mm": 1.0}[w.get("einheit", "m")]
    f = f_einheit / float(w.get("massstab", 500))
    out = os.path.abspath(w.get("ausgabe_ordner") or "ausgabe_druck")
    os.makedirs(os.path.join(out, "einzeln"), exist_ok=True)
    bett, hmax = BIB.druckbett(cfg)
    roh = []
    for p in w["dateien"]:
        low = p.lower()
        log(f"Lesen: {os.path.basename(p)}")
        if low.endswith(".ifc"):
            roh += _laden_ifc(p, log)
        elif low.endswith((".gml", ".citygml", ".xml")):
            from .geo_io import read_citygml
            for b in read_citygml([p], (-1e9, -1e9, 1e9, 1e9), log):
                roh.append((b["id"], ("citygml", b)))
        else:
            roh += _laden_trimesh(p)
    # in Modell-mm umrechnen
    koerper = []
    for name, m in roh:
        if isinstance(m, tuple):
            koerper.append((name, m))
            continue
        m = m.copy()
        m.apply_scale(f)
        koerper.append((name, m))
    if w.get("zusammenfassen", True):
        ms = [m for _, m in koerper if not isinstance(m, tuple)]
        cg = [(n, m) for n, m in koerper if isinstance(m, tuple)]
        koerper = ([("gesamt", trimesh.util.concatenate(ms))] if ms else []) + cg
    ergebnis = []
    modus = w.get("modus", "massiv")
    for name, m in koerper:
        if isinstance(m, tuple):                       # CityGML: Dachprismen wie im Gelände-Modell
            m = _citygml_massiv(m[1], f)
        elif modus == "massiv":
            m = _massiv(m)
        else:
            m = _reparieren(m)
        if m is None or not len(m.faces):
            continue
        m.apply_translation([0, 0, -m.bounds[0][2]])
        dicht = m.is_watertight
        for s in _teilen(m, bett, hmax, float(cfg["druck"].get("rand_mm", 5))):
            s.apply_translation(-np.r_[s.bounds[0][:2], s.bounds[0][2]])
            ergebnis.append({"id": re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:40] + (f"_{len(ergebnis) + 1}"),
                             "mesh": s, "fp": umriss(s), "dicht": dicht})
    n_undicht = sum(1 for e in ergebnis if not e["dicht"])
    if n_undicht:
        log(f"  Hinweis: {n_undicht} Körper nicht vollständig geschlossen – PrusaSlicer repariert das beim "
            f"Import meist automatisch; sonst Modus „massiv“ wählen.")
    duenn = [e["id"] for e in ergebnis if umriss(e["mesh"]).buffer(-float(w.get("min_wand_mm", 1.2)) / 2).is_empty]
    if duenn:
        log(f"  WARNUNG: {len(duenn)} Körper sind dünner als {w.get('min_wand_mm', 1.2)} mm – "
            f"beim Drucken fehleranfällig: {', '.join(duenn[:5])}")
    for e in ergebnis:
        stl(os.path.join(out, "einzeln", e["id"] + ".stl"), [e["mesh"]])
    platten = auf_betten(ergebnis, cfg, os.path.join(out, w.get("name", "druck")), log)
    log(f"Fertig: {len(ergebnis)} Körper auf {len(platten)} Druckplatten · {out}")
    return {"ausgabe": out, "platten": platten, "n": len(ergebnis)}


def _citygml_massiv(b, f):
    from .buildings import _fit_plane, _prism
    zmin = b["zmin"]
    pr = []
    for ext, ints in b["roofs"]:
        e2 = ext[:, :2] * f
        p = shapely.make_valid(Polygon(e2, [i[:, :2] * f for i in ints if len(i) >= 4]))
        xyz = np.c_[e2, (ext[:, 2] - zmin) * f]
        pr += _prism(p.buffer(0.02, join_style="mitre"), _fit_plane(xyz), min_z=0.3)
    return vereinigen(pr)
