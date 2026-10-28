"""Steckrippen: senkrechte Rippen als Gitter unter den hohlen Geländeschichten.

Jede Rippe steht auf der Grundplatte und reicht genau bis zur Unterseite der untersten
Schicht, die an dieser Stelle Material hat (gestuftes Profil). Rippen in x- und y-Richtung
werden an den Kreuzungen halb geschlitzt und ineinander gesteckt – ohne Kleber.
"""
import numpy as np
import shapely
import shapely.ops
from shapely.geometry import LineString, box

from .geomutil import lines, place_text, polys

SCHRITT = 0.5          # mm Abtastung entlang der Rippe


def _profil(linie, M, t):
    """Höhe der Rippe (mm über der Grundplatte) entlang der Linie, abgetastet. -> (u, z)"""
    L = linie.length
    u = np.arange(0.0, L + SCHRITT / 2, SCHRITT)
    m = np.full(len(u), np.inf)
    for k in range(1, len(M)):
        cut = linie.intersection(M[k])
        for seg in lines(cut):
            a = linie.project(shapely.Point(seg.coords[0]))
            b = linie.project(shapely.Point(seg.coords[-1]))
            a, b = min(a, b), max(a, b)
            sel = (u >= a) & (u <= b) & ~np.isfinite(m)
            m[sel] = k
    z = np.where(np.isfinite(m) & (m >= 2), (m - 1) * t, 0.0)
    # an Stufen die niedrigere Höhe nehmen (Rippe darf nirgends in eine Schicht ragen)
    zp = np.r_[z[:1], z[:-1]]
    zn = np.r_[z[1:], z[-1:]]
    z = np.minimum(np.minimum(zp, z), zn)
    zp = np.r_[z[:1], z[:-1]]
    zn = np.r_[z[1:], z[-1:]]
    z = np.minimum(np.minimum(zp, z), zn)
    return u, z


def _profil_poly(u, z):
    """Treppenprofil aus Abtastwerten -> Liste Polygone (u, z)."""
    out = []
    i, n = 0, len(u)
    while i < n:
        if z[i] <= 0:
            i += 1
            continue
        j = i
        boxes = []
        while j < n and z[j] > 0:
            k = j
            while k + 1 < n and z[k + 1] == z[j]:
                k += 1
            u0 = u[j] - SCHRITT / 2 if j > i else u[j]
            u1 = u[k] + SCHRITT / 2 if k + 1 < n and z[k + 1] > 0 else u[k]
            boxes.append(box(max(u0, u[i]), 0, u1, z[j]))
            j = k + 1
        g = shapely.union_all(boxes)
        out += polys(g)
        i = j
    return out


def _lage(q, seg, t):
    """3D-Körper der Rippe an ihrem Platz im Modell (für die Vorschau)."""
    try:
        import trimesh
        m = trimesh.creation.extrude_polygon(q, t)
        v = m.vertices.copy()
        (ax, ay), (bx, by) = seg.coords[0], seg.coords[-1]
        L = max(seg.length, 1e-9)
        dx, dy = (bx - ax) / L, (by - ay) / L
        nx, ny = -dy, dx
        u, zz, w = v[:, 0], v[:, 1], v[:, 2] - t / 2
        m.vertices = np.c_[ax + u * dx + w * nx, ay + u * dy + w * ny, t + zz]
        return m
    except Exception:
        return None


def steckrippen(M, t, abstand, extent, rand=6.0, spiel=0.15, min_laenge=12.0, schrift=3.0, log=print):
    """M[k] = Material der Schicht k (Modell-mm, M[0] = Grundplatte). t = Plattenstärke.

    Rückgabe: (rippen, marken)
      rippen: Liste Laserteile {id, poly (u,z), ritzen, gravieren}
      marken: Liste (LineString, id) – Lage der Rippen auf der Grundplatte
    """
    xmin, ymin, xmax, ymax = extent.bounds
    innen = extent.buffer(-rand)
    xs = np.arange(xmin + abstand / 2, xmax - rand, abstand)
    ys = np.arange(ymin + abstand / 2, ymax - rand, abstand)
    linien = []
    for i, x in enumerate(xs):
        for seg in lines(LineString([(x, ymin), (x, ymax)]).intersection(innen)):
            linien.append(("A", i, seg))
    for j, y in enumerate(ys):
        for seg in lines(LineString([(xmin, y), (xmax, y)]).intersection(innen)):
            linien.append(("B", j, seg))
    prof = {}
    for richt, i, seg in linien:
        prof[(richt, i, seg.wkb)] = _profil(seg, M, t)

    def z_bei(richt, i, seg, pkt):
        u, z = prof[(richt, i, seg.wkb)]
        d = seg.project(pkt)
        return float(z[min(len(z) - 1, max(0, int(round(d / SCHRITT))))]), d

    w = t + spiel
    schlitze = {}                          # key -> [box(u,z)]
    for ra, ia, sa in [l for l in linien if l[0] == "A"]:
        for rb, ib, sb in [l for l in linien if l[0] == "B"]:
            p = sa.intersection(sb)
            if p.is_empty or p.geom_type != "Point":
                continue
            za, ua = z_bei(ra, ia, sa, p)
            zb, ub = z_bei(rb, ib, sb, p)
            if za <= 0 or zb <= 0:
                continue
            hm = min(za, zb) / 2.0
            schlitze.setdefault((ra, ia, sa.wkb), []).append(box(ua - w / 2, hm, ua + w / 2, za + 1))
            schlitze.setdefault((rb, ib, sb.wkb), []).append(box(ub - w / 2, -1, ub + w / 2, hm))
    rippen, marken = [], []
    zaehler = {}
    for richt, i, seg in linien:
        key = (richt, i, seg.wkb)
        u, z = prof[key]
        for pg in _profil_poly(u, z):
            if pg.bounds[2] - pg.bounds[0] < min_laenge:
                continue
            s = [b for b in schlitze.get(key, []) if b.intersects(pg)]
            if s:
                pg = pg.difference(shapely.union_all(s))
            for q in polys(pg):
                if q.area < 5:
                    continue
                n = zaehler.get((richt, i), 0) + 1
                zaehler[(richt, i)] = n
                rid = f"R{richt}{i + 1:02d}-{n}"
                txt = place_text(q, rid, schrift)
                rippen.append({"id": rid, "poly": q, "ritzen": [], "gravieren": txt,
                               "layer": -1, "rippe": True, "lage": _lage(q, seg, t)})
                u0, u1 = q.bounds[0], q.bounds[2]
                marken.append((shapely.ops.substring(seg, u0, u1), rid))
    if rippen:
        hmax = max(r["poly"].bounds[3] for r in rippen)
        log(f"  Steckrippen: {len(rippen)} Rippen (Raster {abstand:.0f} mm, bis {hmax:.0f} mm hoch, "
            f"{sum(len(v) for v in schlitze.values()) // 2} Steckverbindungen)")
    return rippen, marken
