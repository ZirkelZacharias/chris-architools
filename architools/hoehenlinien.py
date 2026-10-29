"""Höhenlinien: Schichtlinien aus dem Geländemodell (DGM) als eigene Zeichnung (DXF/DWG) mit Höhenkoten.

Koordinaten wie bei den anderen 2D-Ausgaben: lokal = Ost - E0 / Nord - N0 (E0/N0 = Mittelpunkt auf 1000 m gerundet).
Höhen: m ü. NHN (wahre Höhe); mit "z_null" wird dieser Wert abgezogen (z. B. der Nullpunkt Z0 des IFC).
Jede Linie liegt in ihrer Höhe (DXF-Elevation), Hauptlinien und Nebenlinien haben eigene Ebenen.
"""
import copy
import math
import os

import numpy as np

STANDARD = {
    "aequidistanz_m": 1.0,        # Abstand der Höhenlinien
    "haupt_alle": 5,              # jede n-te Linie ist Hauptlinie (stärker, beschriftet)
    "beschriften": True,
    "glaetten": True,             # DGM1 ist rasterig – leicht glätten
    "massstab": 500,              # nur für die Schrifthöhe (2,5 mm auf dem Papier)
    "z_null": None,               # None = wahre Höhen (m ü. NHN)
    "min_laenge_m": 4.0,          # kürzere Linien (Rauschen) weglassen
}


def einstellungen(p):
    s = dict(STANDARD)
    s.update(p.get("hoehenlinien") or {})
    return s


def gebiet_box(p):
    """(xmin, ymin, xmax, ymax) der Umgebung in Weltkoordinaten (Größe aus den Umgebungs-Einstellungen)."""
    e, n = (float(v) for v in p["gebiet"]["mitte_en"])
    u = p["umgebung"]
    b = float(u.get("breite") or 900.0)
    h = float(u.get("hoehe") or 900.0)
    return e - b / 2, n - h / 2, e + b / 2, n + h / 2


def nullpunkt(p):
    e, n = (float(v) for v in p["gebiet"]["mitte_en"])
    return round(e / 1000) * 1000, round(n / 1000) * 1000


def szene_laden(p, box, log):
    """DGM (und was die Modellbau-Datenwege sonst mitbringen) für das Gebiet laden."""
    from .modell import pipeline
    cfg = copy.deepcopy(p["modell"])
    pad = 20.0
    x0, y0, x1, y1 = box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad
    cfg["massstab"] = 1000
    cfg["gebiet"] = {"mitte_en": [(x0 + x1) / 2, (y0 + y1) / 2], "drehung_grad": 0.0,
                     "breite_cm": (x1 - x0) * 100 / 1000.0, "hoehe_cm": (y1 - y0) * 100 / 1000.0}
    cfg["_basis"] = p["ordner"]
    cfg["_nur_dgm"] = True                       # Hoehenlinien brauchen nur das Gelaende
    u = p.get("umgebung", {})
    cfg["netz"] = {"cafile": u.get("cafile", "") or "", "unsicher": bool(u.get("unsicher", False))}
    return pipeline.szene_laden(cfg, log)


def linien_berechnen(dgm, box, s, log=print):
    """Schichtlinien aus dem Raster. -> Liste (z, hauptlinie?, [(x, y), …], geschlossen?)"""
    import contourpy
    import shapely
    from shapely.geometry import LineString, box as sbox
    x, y, z = np.asarray(dgm["x"], float), np.asarray(dgm["y"], float), np.asarray(dgm["z"], float)
    z = np.where(np.isfinite(z), z, np.nanmean(z))
    if s.get("glaetten", True) and len(x) > 3:
        from scipy.ndimage import gaussian_filter
        z = gaussian_filter(z, sigma=1.0, mode="nearest")
    ae = max(float(s.get("aequidistanz_m") or 1.0), 0.05)
    haupt = max(int(s.get("haupt_alle") or 5), 1)
    zmin, zmax = float(np.nanmin(z)), float(np.nanmax(z))
    stufen = np.arange(math.ceil(zmin / ae) * ae, zmax + 1e-9, ae)
    gen = contourpy.contour_generator(x, y, z, line_type=contourpy.LineType.Separate)
    rahmen = sbox(*box)
    minl = float(s.get("min_laenge_m") or 0)
    out = []
    for h in stufen:
        h = round(float(h), 4)
        idx = int(round(h / ae))
        ist_haupt = (idx % haupt == 0)
        for lin in gen.lines(h):
            if len(lin) < 3:
                continue
            ls = LineString(lin)
            if ls.length < minl:
                continue
            ls = ls.simplify(0.05)
            teile = ls.intersection(rahmen)
            for t in getattr(teile, "geoms", [teile]):
                if t.geom_type != "LineString" or t.length < max(minl, 0.5):
                    continue
                pts = [(float(a), float(b)) for a, b in t.coords]
                geschl = len(pts) > 3 and pts[0] == pts[-1]
                out.append((h, ist_haupt, pts, geschl))
    log(f"  {len(out)} Höhenlinien, {len(stufen)} Höhenstufen ({ae:g} m), Gelände {zmin:.1f}–{zmax:.1f} m ü. NHN")
    return out


def _text_stelle(pts):
    """Beschriftungsstelle: Mitte der Linie (nach Länge) und Richtung (lesbar, nie auf dem Kopf)."""
    a = np.asarray(pts, float)
    seg = np.hypot(*np.diff(a, axis=0).T)
    c = np.cumsum(seg)
    i = int(np.searchsorted(c, c[-1] / 2))
    i = min(i, len(seg) - 1)
    d = a[i + 1] - a[i]
    w = math.degrees(math.atan2(d[1], d[0]))
    if w > 90 or w <= -90:
        w += 180
    f = 0.5 if seg[i] == 0 else (c[i] - c[-1] / 2) / seg[i]
    m = a[i + 1] - d * min(max(f, 0), 1)
    return float(m[0]), float(m[1]), w


def zeichnen(linien, box, p, ordner, name, log=print):
    import ezdxf
    from ezdxf.enums import TextEntityAlignment
    s = einstellungen(p)
    e0, n0 = nullpunkt(p)
    z_null = s.get("z_null")
    zn = float(z_null) if z_null not in (None, "") else 0.0
    os.makedirs(ordner, exist_ok=True)
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.M
    msp = doc.modelspace()
    for lay, col in (("HOEHENLINIEN_HAUPT", 32), ("HOEHENLINIEN_NEBEN", 30), ("HOEHENLINIEN_TEXT", 32), ("HOEHENLINIEN_RAHMEN", 8)):
        doc.layers.add(lay, color=col)
    doc.layers.get("HOEHENLINIEN_NEBEN").dxf.lineweight = 13
    doc.layers.get("HOEHENLINIEN_HAUPT").dxf.lineweight = 35
    th = 2.5e-3 * float(s.get("massstab") or 500)               # 2,5 mm auf dem Papier
    n_text = 0
    for h, haupt, pts, geschl in linien:
        lok = [(round(x - e0, 3), round(y - n0, 3)) for x, y in pts]
        if geschl:
            lok = lok[:-1]
        msp.add_lwpolyline(lok, close=geschl, dxfattribs={
            "layer": "HOEHENLINIEN_HAUPT" if haupt else "HOEHENLINIEN_NEBEN", "elevation": round(h - zn, 3)})
        if haupt and s.get("beschriften", True):
            from math import hypot
            laenge = sum(hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))
            if laenge >= th * 8:
                tx, ty, w = _text_stelle(pts)
                t = msp.add_text(f"{h:g}", height=th, rotation=w, dxfattribs={"layer": "HOEHENLINIEN_TEXT"})
                t.set_placement((round(tx - e0, 3), round(ty - n0, 3), round(h - zn, 3)), align=TextEntityAlignment.MIDDLE_CENTER)
                n_text += 1
    x0, y0, x1, y1 = box
    msp.add_lwpolyline([(x0 - e0, y0 - n0), (x1 - e0, y0 - n0), (x1 - e0, y1 - n0), (x0 - e0, y1 - n0)], close=True,
                       dxfattribs={"layer": "HOEHENLINIEN_RAHMEN"})
    z_txt = "wahre Höhen m ü. NHN" if not zn else f"Höhen relativ zu {zn:g} m ü. NHN"
    msp.add_text(f"{name} · Äquidistanz {float(s['aequidistanz_m']):g} m · {z_txt} · Nullpunkt E0={e0:.0f} N0={n0:.0f}",
                 height=th, dxfattribs={"layer": "HOEHENLINIEN_RAHMEN", "insert": (x0 - e0, y0 - n0 - 3 * th)})
    f_dxf = os.path.join(ordner, f"{name}.dxf")
    doc.saveas(f_dxf)
    from . import einstellungen as ES
    from .formate import zweid_umwandeln
    fm = (p.get("formate") or {}).get("zweid") or ["dxf"]
    teile = zweid_umwandeln([f_dxf], fm, ES.laden().get("oda_pfad", ""), log)
    log(f"  Zeichnung: {len(linien)} Linien, {n_text} Höhenkoten, Nullpunkt E0={e0:.0f} N0={n0:.0f}")
    # PNG-Vorschau
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 9 * max(y1 - y0, 1) / max(x1 - x0, 1) + 0.4), dpi=100)
    for h, haupt, pts, geschl in linien:
        a = np.asarray(pts)
        ax.plot(a[:, 0] - e0, a[:, 1] - n0, color="#8a5a2b" if haupt else "#c9a57a", lw=1.0 if haupt else 0.5)
    ax.set_aspect("equal")
    ax.set_xlim(x0 - e0, x1 - e0)
    ax.set_ylim(y0 - n0, y1 - n0)
    ax.set_title(f"{name} · Äquidistanz {float(s['aequidistanz_m']):g} m · {z_txt}", fontsize=9)
    ax.tick_params(labelsize=7)
    fig.tight_layout()
    f_png = os.path.join(ordner, f"{name}.png")
    fig.savefig(f_png)
    plt.close(fig)
    teile.append(f_png)
    return {"dateien": teile, "png": f_png}


def erzeugen(p, log=print, prog=lambda *a: None):
    s = einstellungen(p)
    box = gebiet_box(p)
    log(f"Höhenlinien für {box[2] - box[0]:.0f} × {box[3] - box[1]:.0f} m um ({p['gebiet']['mitte_en'][0]:.0f}, {p['gebiet']['mitte_en'][1]:.0f})")
    prog(0.05, "Geländedaten laden …")
    sz = szene_laden(p, box, log)
    prog(0.6, "Höhenlinien berechnen …")
    linien = linien_berechnen(sz["dgm"], box, s, log)
    if not linien:
        raise RuntimeError("Keine Höhenlinien: das Gelände ist in diesem Gebiet (fast) eben oder es liegen keine Geländedaten vor.")
    prog(0.8, "Zeichnen …")
    from .projekt import ausgabe_ordner, sicher
    ordner = ausgabe_ordner(p, "hoehenlinien")
    r = zeichnen(linien, box, p, ordner, sicher(p["name"]) + "_Hoehenlinien", log)
    prog(1.0, "Fertig")
    return {"ordner": ordner, **r}
