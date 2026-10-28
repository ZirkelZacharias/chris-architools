"""Fenstermuster (optional, IFC): Fenster und Türen als flache Rechtecke auf den LoD2-Wänden.

WICHTIG: Das ist ein MUSTER, KEINE Messung. LoD2 enthält keine Öffnungen, und weder das DOM noch Luftbilder liefern sie
verlässlich. Das Muster richtet sich nur nach Wandbreite und -höhe (Geschosshöhe ca. 3,1 m, Fensterachse ca. 3 m, Fenster
1,2 × 1,4 m, Brüstung 0,9 m, Tür im Erdgeschoss an breiten Wänden). Balkone lassen sich daraus nicht ableiten und fehlen.
Jedes Rechteck liegt 3 cm vor der Wand (flach – so bleibt es in Archicad leicht).
"""
import numpy as np

GESCHOSS_M = 3.1
ACHSE_M = 3.0
FENSTER_B, FENSTER_H, BRUESTUNG = 1.2, 1.4, 0.9
TUER_B, TUER_H = 1.0, 2.1
VOR = 0.03                      # Abstand vor der Wand
MIN_BREITE, MIN_HOEHE = 3.2, 3.0


def _flaechen_normale(p):
    n = np.zeros(3)
    for i in range(len(p)):
        n += np.cross(p[i], p[(i + 1) % len(p)])
    return n


def fassade(waende, mitte_xy):
    """waende: [(ext Nx3, holes)] (Weltkoordinaten); mitte_xy: Mittelpunkt des Gebäudes (für die Außenrichtung).
    -> (fenster [Mx4x3], tueren [Kx4x3], infos dict)"""
    import shapely
    fenster, tueren = [], []
    geschosse = 0
    for ext, holes in waende:
        ext = np.asarray(ext, float)
        if len(ext) < 3:
            continue
        n = _flaechen_normale(ext)
        ln = np.linalg.norm(n)
        if ln < 1e-6:
            continue
        n = n / ln
        if abs(n[2]) > 0.2:                                   # kein senkrechtes Wandstück
            continue
        nxy = np.array([n[0], n[1]])
        nxy /= np.linalg.norm(nxy)
        c = ext[:, :2].mean(axis=0)
        if np.dot(c - np.asarray(mitte_xy, float), nxy) < 0:
            nxy = -nxy                                        # nach außen
        u = np.array([-nxy[1], nxy[0]])                       # entlang der Wand, von außen gesehen nach rechts
        s = (ext[:, :2] - ext[0, :2]) @ u
        z = ext[:, 2]
        poly = shapely.Polygon(np.column_stack([s, z]))
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or poly.area < 6:
            continue
        smin, zmin, smax, zmax = poly.bounds
        W, Ht = smax - smin, zmax - zmin
        if W < MIN_BREITE or Ht < MIN_HOEHE:
            continue
        # Traufnahe Höhe: unteres Viertel der Wandhöhen entlang der Wand (Giebel zählen nicht bis zum First)
        xs = np.linspace(smin + 0.2, smax - 0.2, 9)
        tops = []
        for x in xs:
            seg = poly.intersection(shapely.LineString([(x, zmin - 1), (x, zmax + 1)]))
            if not seg.is_empty:
                tops.append(seg.bounds[3])
        if not tops:
            continue
        top = float(np.quantile(tops, 0.25))
        nfl = max(1, int(round((top - zmin) / GESCHOSS_M)))
        fh = (top - zmin) / nfl
        geschosse = max(geschosse, nfl)
        nax = max(1, int(W // ACHSE_M))
        a = W / nax
        fb = min(FENSTER_B, 0.55 * a)
        ax_mitten = smin + a * (np.arange(nax) + 0.5)
        tuer_ax = nax // 2 if W >= 6.0 else -1
        boxen, art = [], []
        for k in range(nfl):
            z0 = zmin + k * fh
            for i, sm in enumerate(ax_mitten):
                if k == 0 and i == tuer_ax:
                    boxen.append((sm - TUER_B / 2, z0 + 0.2, sm + TUER_B / 2, z0 + 0.2 + TUER_H))
                    art.append(1)
                else:
                    boxen.append((sm - fb / 2, z0 + BRUESTUNG, sm + fb / 2, z0 + BRUESTUNG + FENSTER_H))
                    art.append(0)
        if not boxen:
            continue
        b = np.array(boxen)
        geo = shapely.box(b[:, 0], b[:, 1], b[:, 2], b[:, 3])
        ok = shapely.contains(poly.buffer(-0.15), geo)
        for (s0, z0, s1, z1), kind, gut in zip(boxen, art, ok):
            if not gut:
                continue
            # u zeigt von außen gesehen nach rechts; gegen den Uhrzeigersinn = Normale zeigt nach außen
            P = [(s0, z0), (s1, z0), (s1, z1), (s0, z1)]
            q = np.array([[ext[0, 0] + u[0] * ss + nxy[0] * VOR, ext[0, 1] + u[1] * ss + nxy[1] * VOR, zz] for ss, zz in P])
            (tueren if kind else fenster).append(q)
    return (np.array(fenster) if fenster else np.zeros((0, 4, 3)), np.array(tueren) if tueren else np.zeros((0, 4, 3)),
            {"geschosse": geschosse})


def zu_flaechen(arr):
    return [q for q in arr]
