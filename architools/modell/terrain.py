"""DGM -> Höhenschichten (Flächen in Modell-mm)."""
import math

import contourpy
import numpy as np
import shapely
from scipy.ndimage import gaussian_filter
from shapely.geometry import Polygon

from .geomutil import clean_area, polys


def build_levels(dgm, extent_world, to_model, scale, gcfg, dgm_cfg, log=print):
    """Erzeugt Schichtflächen P[0..n] (P[0] = gesamter Ausschnitt).

    Schicht k liegt dort, wo das Gelände >= basis + (k - 0.5) * dz ist,
    d. h. die Oberkante von Schicht k steht für die Höhe basis + k * dz.
    """
    t = float(gcfg["schichtdicke_mm"])
    ue = float(gcfg["ueberhoehung"]) or 1.0
    dz = t * scale / 1000.0 / ue                    # echte Höhendifferenz pro Schicht in m
    x, y, z = dgm["x"], dgm["y"], dgm["z"]
    res = abs(x[1] - x[0]) if len(x) > 1 else 1.0
    sig = float(dgm_cfg.get("glaettung_m") or 0) / res
    if sig > 0:
        z = gaussian_filter(z, sig, mode="nearest")

    # Höhen innerhalb des Ausschnitts
    xmin, ymin, xmax, ymax = extent_world.bounds
    mx = (x >= xmin) & (x <= xmax)
    my = (y >= ymin) & (y <= ymax)
    zin = z[np.ix_(my, mx)]
    zlo, zhi = float(zin.min()), float(zin.max())
    base = gcfg.get("basis_hoehe_m")
    base = math.floor(zlo) if base in (None, "") else float(base)
    n = int(math.floor((zhi - base) / dz + 0.5))
    log(f"  Gelände {zlo:.1f} – {zhi:.1f} m, Basis {base:.2f} m, "
        f"{dz:.2f} m echte Höhe je Schicht -> {n} Schichten über der Grundplatte")

    extent_m = to_model(extent_world)
    P = [extent_m]
    cg = contourpy.contour_generator(x, y, z, fill_type="OuterOffset")
    minw = float(gcfg["min_breite_mm"])
    mina = float(gcfg["min_flaeche_mm2"])
    for k in range(1, n + 1):
        lo = base + (k - 0.5) * dz
        pts_list, offs_list = cg.filled(lo, float(z.max()) + 1.0)
        out = []
        for pts, offs in zip(pts_list, offs_list):
            rings = [pts[offs[i]:offs[i + 1]] for i in range(len(offs) - 1)]
            if len(rings[0]) < 4:
                continue
            p = Polygon(rings[0], [r for r in rings[1:] if len(r) >= 4])
            out.append(shapely.make_valid(p))
        g = shapely.union_all(out) if out else Polygon()
        g = to_model(g.intersection(extent_world))
        g = clean_area(g, minw, mina)
        # Schichten müssen ineinander liegen
        g = g.intersection(P[-1])
        g = shapely.union_all([p for p in polys(g) if p.area >= mina]) if not g.is_empty else g
        if g.is_empty:
            log(f"  Schicht {k}: nach Bereinigung leer – höhere Schichten entfallen")
            break
        P.append(g)
    info = {"basis_m": base, "dz_m": dz, "z_min": zlo, "z_max": zhi, "ueberhoehung": ue}
    return P, info


def layer_at(P, pt):
    """Index der obersten Schicht, die den Punkt enthält."""
    k = 0
    for i in range(1, len(P)):
        if P[i].contains(pt):
            k = i
        else:
            break
    return k


def layer_under(P, footprint):
    """Tiefste Schicht unter dem ganzen Grundriss (dort steht das Gebäude eben auf)."""
    k = 0
    for i in range(1, len(P)):
        if P[i].buffer(0.5).contains(footprint):
            k = i
        else:
            break
    return k
