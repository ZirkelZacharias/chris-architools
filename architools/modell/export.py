"""Ausgabe: Laserplatten als SVG + DXF, Druckplatten als STL."""
import ezdxf
import numpy as np
import trimesh


def _ring_path(coords, H):
    pts = [(x, H - y) for x, y in coords]
    return "M" + " L".join(f"{x:.3f},{y:.3f}" for x, y in pts) + " Z"


def _line_path(coords, H):
    pts = [(x, H - y) for x, y in coords]
    return "M" + " L".join(f"{x:.3f},{y:.3f}" for x, y in pts)


def write_sheet_svg(path, W, H, cut_polys, engrave_lines, text_polys, lc, title=""):
    sw = lc["linienstaerke_mm"]
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" '
           f'viewBox="0 0 {W} {H}">',
           f'<title>{title}</title>']
    # Reihenfolge für den Laser: Beschriften, Gravieren, dann Innen- vor Außenschnitten
    out.append(f'<g id="beschriften" fill="{lc["farbe_beschriften"]}" stroke="none" fill-rule="evenodd">')
    for p in text_polys:
        d = _ring_path(p.exterior.coords, H) + "".join(_ring_path(i.coords, H) for i in p.interiors)
        out.append(f'<path d="{d}"/>')
    out.append("</g>")
    out.append(f'<g id="gravieren" fill="none" stroke="{lc["farbe_gravieren"]}" stroke-width="{sw}">')
    for l in engrave_lines:
        out.append(f'<path d="{_line_path(l.coords, H)}"/>')
    out.append("</g>")
    out.append(f'<g id="schneiden_innen" fill="none" stroke="{lc["farbe_schneiden"]}" stroke-width="{sw}">')
    for p in cut_polys:
        for i in p.interiors:
            out.append(f'<path d="{_ring_path(i.coords, H)}"/>')
    out.append("</g>")
    out.append(f'<g id="schneiden_aussen" fill="none" stroke="{lc["farbe_schneiden"]}" stroke-width="{sw}">')
    for p in cut_polys:
        out.append(f'<path d="{_ring_path(p.exterior.coords, H)}"/>')
    out.append("</g></svg>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


def write_sheet_dxf(path, W, H, cut_polys, engrave_lines, text_polys):
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    doc.header["$INSUNITS"] = 4
    for name, col in (("SCHNEIDEN", 1), ("GRAVIEREN", 5), ("BESCHRIFTUNG", 7), ("PLATTE", 8)):
        doc.layers.add(name, color=col)
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (W, 0), (W, H), (0, H)], close=True, dxfattribs={"layer": "PLATTE"})
    for p in text_polys:
        for r in [p.exterior] + list(p.interiors):
            msp.add_lwpolyline(list(r.coords)[:-1], close=True, dxfattribs={"layer": "BESCHRIFTUNG"})
    for l in engrave_lines:
        msp.add_lwpolyline(list(l.coords), dxfattribs={"layer": "GRAVIEREN"})
    for p in cut_polys:
        for r in list(p.interiors) + [p.exterior]:
            msp.add_lwpolyline(list(r.coords)[:-1], close=True, dxfattribs={"layer": "SCHNEIDEN"})
    doc.saveas(path)


def place_mesh(mesh, ang, dx, dy):
    m = mesh.copy()
    T = trimesh.transformations.rotation_matrix(np.radians(ang), [0, 0, 1])
    T[0, 3] += dx
    T[1, 3] += dy
    m.apply_transform(T)
    return m


def write_stl(path, meshes):
    if not meshes:
        return
    m = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
    m.export(path)
