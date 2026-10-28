"""Draufsicht und Schnitte des fertigen Modells (PNG für Oberfläche und Bericht)."""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import shapely
from matplotlib.patches import PathPatch, Rectangle
from matplotlib.path import Path

from .geomutil import lines, polys

PAPPE = plt.get_cmap("copper")
DRUCK = "#7fb3c4"


def _patch(p, **kw):
    verts, codes = [], []
    for ring in [p.exterior] + list(p.interiors):
        c = np.asarray(ring.coords)
        verts += list(c)
        codes += [Path.MOVETO] + [Path.LINETO] * (len(c) - 2) + [Path.CLOSEPOLY]
    return PathPatch(Path(verts, codes), **kw)


def _farbe(k, n):
    return PAPPE(0.35 + 0.55 * k / max(1, n))


def draufsicht(pfad, parts, blds, b, h, schnitte):
    n = max([p["layer"] for p in parts] + [1])
    fig, ax = plt.subplots(figsize=(14, 14 * h / b + 0.8))
    for k in range(n + 1):
        for p in parts:
            if p["layer"] == k:
                ax.add_patch(_patch(p["poly"], facecolor=_farbe(k, n), edgecolor="#5a4a35", lw=0.25))
    for bd in blds:
        if bd["status"] == "druck":
            for fp in polys(bd["footprint"]):
                ax.add_patch(_patch(fp, facecolor=DRUCK, edgecolor="#2d5866", lw=0.4))
    for name, (a, e) in schnitte.items():
        ax.plot([a[0], e[0]], [a[1], e[1]], color="#c8643b", lw=1.4, ls=(0, (8, 4)))
        ax.text(a[0], a[1], f" {name}", color="#c8643b", fontsize=12, weight="bold", va="bottom")
        ax.text(e[0], e[1], f" {name}", color="#c8643b", fontsize=12, weight="bold", va="bottom")
    ax.set_xlim(-5, b + 5)
    ax.set_ylim(-5, h + 5)
    ax.set_aspect("equal")
    ax.set_title("Draufsicht des Modells (dunkler = höher, blau = 3D-Druck)", loc="left")
    ax.tick_params(labelsize=7)
    fig.tight_layout()
    fig.savefig(pfad, dpi=110)
    plt.close(fig)


def schnitt(pfad, titel, a, e, parts, blds, t):
    """Schnitt entlang der Linie a -> e (Modell-mm)."""
    linie = shapely.LineString([a, e])
    L = linie.length
    n = max([p["layer"] for p in parts] + [1])
    zmax = (n + 1) * t
    stuecke = []
    for p in parts:
        k = p["layer"]
        for seg in lines(p["poly"].intersection(linie)):
            u0 = linie.project(shapely.Point(seg.coords[0]))
            u1 = linie.project(shapely.Point(seg.coords[-1]))
            stuecke.append((min(u0, u1), abs(u1 - u0), k))
    koerper = []
    d = np.array(e, float) - np.array(a, float)
    d /= max(np.linalg.norm(d), 1e-9)
    normal = np.array([-d[1], d[0], 0.0])
    for bd in blds:
        if bd["status"] != "druck" or bd["mesh"] is None or not bd["footprint"].intersects(linie):
            continue
        try:
            sec = bd["mesh"].section(plane_origin=[a[0], a[1], 0], plane_normal=normal)
        except Exception:
            sec = None
        if sec is None:
            continue
        z0 = (bd["layer"] + 1) * t
        for pts in sec.discrete:
            u = (pts[:, 0] - a[0]) * d[0] + (pts[:, 1] - a[1]) * d[1]
            koerper.append(np.c_[u, pts[:, 2] + z0])
            zmax = max(zmax, float(pts[:, 2].max() + z0))
    hoch = max(2.2, 14 * (zmax + 10) / L + 1.0)
    fig, ax = plt.subplots(figsize=(14, hoch))
    for u, w, k in stuecke:
        ax.add_patch(Rectangle((u, k * t), w, t, facecolor=_farbe(k, n), edgecolor="#5a4a35", lw=0.2))
    for c in koerper:
        ax.fill(c[:, 0], c[:, 1], facecolor=DRUCK, edgecolor="#2d5866", lw=0.5)
    ax.set_xlim(-3, L + 3)
    ax.set_ylim(-1, zmax + 5)
    ax.set_aspect("equal")
    ax.set_title(f"{titel} – maßstäblich (Höhe nicht überhöht dargestellt)", loc="left")
    ax.tick_params(labelsize=7)
    fig.tight_layout()
    fig.savefig(pfad, dpi=110)
    plt.close(fig)


def erzeugen(ordner, name, parts, blds, t, b, h):
    """Draufsicht + Schnitte A-A (West–Ost) und B-B (Süd–Nord) durch die Modellmitte. -> Liste PNG-Pfade"""
    os.makedirs(ordner, exist_ok=True)
    teile = [p for p in parts if not p.get("rippe")]
    schnitte = {"A": ((0, h / 2), (b, h / 2)), "B": ((b / 2, 0), (b / 2, h))}
    out = []
    p = os.path.join(ordner, f"{name}_draufsicht.png")
    draufsicht(p, teile, blds, b, h, schnitte)
    out.append(p)
    for k, (a, e) in schnitte.items():
        p = os.path.join(ordner, f"{name}_schnitt_{k}.png")
        schnitt(p, f"Schnitt {k}–{k}", a, e, teile, blds, t)
        out.append(p)
    return out
