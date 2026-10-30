"""Gebäude für den Lasercut-Zusammenbau vereinfachen (Klebeflächen, Faltmodell).

LoD2-Gebäude haben oft Dutzende kurze Wandstücke (Vor- und Rücksprünge, runde Ecken) und viele kleine Dachflächen (Gauben,
Dachaufbauten). Ausgeschnitten ergibt das Teile von wenigen Millimetern, die niemand mehr zusammenkleben kann. Hier wird je
Gebäude eine vereinfachte Kopie gebaut – die Laserteile, die Wandhöhen und die 3D-Vorschau entstehen daraus. Alles in Modell-mm.

  1. Grundriss: schmale Rücksprünge schließen, schmale Vorsprünge weglassen (Pufferung mit spitzen Ecken: rechte Winkel bleiben),
     fast gerade Knicke und zu kurze Wände zusammenlegen, kleine Höfe weglassen.
  2. Dach: fast ebene Nachbarflächen zu einer Fläche zusammenfassen, zu kleine Flächen in den Nachbarn mit der längsten gemeinsamen
     Kante aufgehen lassen, dann auf den neuen Grundriss zuschneiden. Wandoberkanten und Dachränder kommen aus denselben Ebenen
     und passen deshalb weiter zusammen.
  3. Stufe "stark": Flachdach in mittlerer Dachhöhe (Klötzchenmodell).
"""
import math

import numpy as np
import shapely
from shapely.geometry import Polygon

STUFEN = {
    #            Puffer   Toleranz  kürzeste Wand  Knick   Dachfläche  Ebenen gleich  Hof
    "aus":    None,
    "leicht": dict(r=0.6, tol=0.25, min_wand=2.0, knick=8.0, min_dach=6.0, winkel=6.0, min_hof=12.0, flach=False),
    "mittel": dict(r=1.2, tol=0.5, min_wand=4.0, knick=15.0, min_dach=20.0, winkel=12.0, min_hof=40.0, flach=False),
    "stark":  dict(r=2.0, tol=0.8, min_wand=6.0, knick=22.0, min_dach=0.0, winkel=0.0, min_hof=100.0, flach=True),
}
STUFEN_TEXT = {
    "aus": "aus – jede LoD2-Fläche einzeln (viele kleine Teile)",
    "leicht": "leicht – Splitter und Knicke unter 2 mm weg",
    "mittel": "mittel – Wände ab 4 mm, Dach ohne kleine Aufbauten (empfohlen)",
    "stark": "stark – Klötzchen: einfacher Grundriss, Flachdach in mittlerer Höhe",
}
MAX_KNICK_ABSTAND = 1.5        # ein Knick wird nur geglättet, wenn die Ecke höchstens so weit von der Sehne liegt (mm)


# ------------------------------------------------------------------ Grundriss
def _polys(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    return [p for p in getattr(g, "geoms", []) if p.geom_type == "Polygon" and not p.is_empty]


def _ring(pts, min_wand, knick):
    """Ring (Liste von Punkten, ohne Wiederholung) ausdünnen: fast gerade Ecken und Ecken an zu kurzen Wänden entfernen"""
    P = [np.asarray(p, float) for p in pts]
    geaendert = True
    while geaendert and len(P) > 4:
        geaendert = False
        n = len(P)
        # 1) fast gerade Ecken (Knick unter knick, nah an der Sehne) entfernen - in Durchgängen, nie zwei Nachbarn auf einmal:
        #    so bleibt ein rundes Gebäude ein regelmäßiges Vieleck
        kand = []
        for i in range(n):
            a, b, c = P[i - 1], P[i], P[(i + 1) % n]
            u, v = b - a, c - b
            lu, lv = np.hypot(*u), np.hypot(*v)
            if lu < 1e-9 or lv < 1e-9:
                kand.append((-1.0, i))
                continue
            w = math.degrees(math.acos(max(-1.0, min(1.0, float(u @ v) / (lu * lv)))))
            s_ = c - a
            ls = np.hypot(*s_)
            abst = abs(s_[0] * (b - a)[1] - s_[1] * (b - a)[0]) / ls if ls > 1e-9 else 0.0
            if w < knick - 0.5 and abst <= MAX_KNICK_ABSTAND:          # halbes Grad Spielraum: Rundungsrauschen entscheidet nicht
                kand.append((w, i))
        if kand:
            ist = {i for _, i in kand}
            start = min(kand)[1]
            weg = set()
            for k in range(n):                                   # reihum ab der flachsten Ecke, jede zweite: gleichmäßig
                i = (start + k) % n
                if i not in ist or (i - 1) % n in weg or (i + 1) % n in weg or n - len(weg) <= 4:
                    continue
                weg.add(i)
            P = [P[i] for i in range(n) if i not in weg]
            geaendert = bool(weg)
            if geaendert:
                continue
        # 2) kürzeste Wand unter min_wand: den Endpunkt entfernen, der die Fläche am wenigsten ändert
        lang = [np.hypot(*(P[(i + 1) % n] - P[i])) for i in range(n)]
        i = int(np.argmin(lang))
        if lang[i] < min_wand:
            def dreieck(k):
                a, b, c = P[k - 1], P[k], P[(k + 1) % n]
                return abs((b - a)[0] * (c - a)[1] - (b - a)[1] * (c - a)[0]) / 2.0
            k = i if dreieck(i) <= dreieck((i + 1) % n) else (i + 1) % n
            P.pop(k)
            geaendert = True
    return [tuple(p) for p in P]


def grundriss(fp, s):
    """Vereinfachter Grundriss (Polygon/MultiPolygon in Modell-mm) nach Stufe s (dict aus STUFEN)"""
    r = s["r"]
    g = fp.buffer(r, join_style="mitre", mitre_limit=10).buffer(-r, join_style="mitre", mitre_limit=10)   # schmale Rücksprünge zu
    g = g.buffer(-r, join_style="mitre", mitre_limit=10).buffer(r, join_style="mitre", mitre_limit=10)    # schmale Vorsprünge weg
    if g.is_empty or g.area < 0.5 * fp.area:                     # sehr schmales Gebäude: Pufferung frisst es auf -> nur glätten
        g = fp
    g = g.simplify(0.05, preserve_topology=True)                 # nur Rechen-Krümel; Douglas-Peucker mit großer Toleranz macht
                                                                   # runde Gebäude unregelmäßig - das Ausdünnen übernimmt _ring
    out = []
    for p in _polys(g):
        ext = _ring(list(p.exterior.coords)[:-1], s["min_wand"], s["knick"])
        if len(ext) < 3:
            continue
        loecher = []
        for h in p.interiors:
            hp = Polygon(h)
            if hp.area < s["min_hof"]:
                continue
            hr = _ring(list(h.coords)[:-1], s["min_wand"], s["knick"])
            if len(hr) >= 3:
                loecher.append(hr)
        q = Polygon(ext, loecher)
        if not q.is_valid:
            q = q.buffer(0)
        out += [x for x in _polys(q) if x.area > 1.0]
    if not out:
        return fp
    return out[0] if len(out) == 1 else shapely.MultiPolygon(out)


# ------------------------------------------------------------------ Dach
def _normale(e):
    a, b, _ = e
    n = np.array([-a, -b, 1.0])
    return n / np.linalg.norm(n)


def _z(e, x, y):
    return e[0] * x + e[1] * y + e[2]


def _flaeche_wahr(xy, e):
    return xy.area / max(_normale(e)[2], 0.05)


def _gemeinsam(a, b):
    try:
        return a.boundary.intersection(b.boundary).length if a.distance(b) < 0.05 else 0.0
    except Exception:
        return 0.0


def dach(b, fp_neu, s):
    """Dachflächen [(xy-Polygon, Ebene)] vereinfacht und auf den neuen Grundriss zugeschnitten; None, wenn nichts zu machen ist"""
    fl = []
    for xyz, _ints in b.get("dach3d") or []:
        xyz = np.asarray(xyz, float)
        if len(xyz) > 1 and np.allclose(xyz[0], xyz[-1]):
            xyz = xyz[:-1]
        if len(xyz) < 3:
            continue
        xy = Polygon(xyz[:, :2])
        if not xy.is_valid:
            xy = xy.buffer(0)
        if xy.is_empty or xy.area < 0.01:
            continue
        A = np.c_[xyz[:, 0], xyz[:, 1], np.ones(len(xyz))]
        e, *_ = np.linalg.lstsq(A, xyz[:, 2], rcond=None)
        fl.append([xy, tuple(float(v) for v in e)])
    if not fl:
        return None
    # 1) fast ebene Nachbarn zusammenfassen (Vergleich mit der Ebene der Gruppe, nicht nur des Nachbarn - sonst wandert
    #    die Gruppe einmal um ein rundes Dach herum)
    if s["winkel"] > 0:
        cos_g = math.cos(math.radians(s["winkel"]))
        fl.sort(key=lambda f: -f[0].area)
        geaendert = True
        while geaendert:
            geaendert = False
            for i in range(len(fl)):
                for j in range(len(fl)):
                    if i == j or fl[i] is None or fl[j] is None:
                        continue
                    if float(_normale(fl[i][1]) @ _normale(fl[j][1])) < cos_g:
                        continue
                    k = _gemeinsam(fl[i][0], fl[j][0])
                    if k < 0.3:
                        continue
                    m = fl[i][0].boundary.intersection(fl[j][0].boundary).centroid
                    if abs(_z(fl[i][1], m.x, m.y) - _z(fl[j][1], m.x, m.y)) > 0.4:     # Stufe im Dach: nicht zusammenlegen
                        continue
                    fl[i][0] = shapely.union_all([fl[i][0], fl[j][0]]).buffer(0)
                    fl[j] = None
                    geaendert = True
            fl = [f for f in fl if f is not None]
    # 2) auf den neuen Grundriss zuschneiden; was der Grundriss neu dazubekommt, geht an die Nachbarfläche
    fl = [[f[0].intersection(fp_neu), f[1]] for f in fl]
    fl = [f for f in fl if not f[0].is_empty and f[0].area > 0.01]
    if not fl:
        return None
    rest = fp_neu.difference(shapely.union_all([f[0] for f in fl]).buffer(0.01))
    for r in _polys(rest):
        if r.area < 0.01:
            continue
        k = max(range(len(fl)), key=lambda i: (_gemeinsam(fl[i][0], r), -fl[i][0].distance(r)))
        fl[k][0] = shapely.union_all([fl[k][0], r]).buffer(0)
    # 3) kleine Flächen (auch Splitter, die beim Zusammenlegen und Zuschneiden entstehen) in den Nachbarn mit der längsten
    #    gemeinsamen Kante; Stück für Stück, bis keines mehr zu klein ist
    grenze = max(s["min_dach"], 2.0)
    for _ in range(400):
        fl = [[p, e] for xy, e in fl for p in _polys(xy.buffer(0)) if p.area > 1e-4]
        if len(fl) < 2:
            break
        klein = [i for i in range(len(fl)) if _flaeche_wahr(fl[i][0], fl[i][1]) < grenze]
        if not klein:
            break
        i = min(klein, key=lambda k: fl[k][0].area)
        nb = [(j, _gemeinsam(fl[i][0], fl[j][0])) for j in range(len(fl)) if j != i]
        nb = [(j, k) for j, k in nb if k > 0.05] or [(min((j for j in range(len(fl)) if j != i),
                                                          key=lambda j: fl[i][0].distance(fl[j][0])), 0.0)]
        j = max(nb, key=lambda t: t[1])[0]
        fl[j][0] = shapely.union_all([fl[j][0], fl[i][0].buffer(0.02, join_style="mitre")]).intersection(fp_neu).buffer(0)
        fl.pop(i)
    out = []
    for xy, e in fl:
        for p in _polys(xy.buffer(0)):
            p = p.simplify(0.05, preserve_topology=True)
            if p.area > 0.05:
                out.append((p, e))
    return out or None


# ------------------------------------------------------------------ Gesamt
def gebaeude(b, stufe):
    """Vereinfachte Kopie des Gebäudes (dict) oder b selbst bei 'aus'. Die Kopie hat footprint, prismen, dach3d, height_mm neu."""
    s = STUFEN.get(stufe or "aus")
    if not s or b.get("footprint") is None or b["footprint"].is_empty:
        return b
    fp = b["footprint"]
    fp_neu = grundriss(fp, s)
    n = dict(b)
    n["footprint"] = fp_neu
    n["_original_footprint"] = fp
    if s["flach"] or not b.get("dach3d"):
        if b.get("dach3d"):                                       # mittlere Dachhöhe (flächengewichtet)
            hs, ws = [], []
            for xyz, _ in b["dach3d"]:
                xyz = np.asarray(xyz, float)
                a = Polygon(xyz[:, :2]).area if len(xyz) >= 3 else 0.0
                if a > 0:
                    hs.append(float(xyz[:, 2].mean()))
                    ws.append(a)
            if ws:
                n["height_mm"] = float(np.average(hs, weights=ws))
        n["prismen"], n["dach3d"] = None, None
        return n
    fl = dach(b, fp_neu, s)
    if not fl:
        n["prismen"], n["dach3d"] = None, None
        return n
    n["prismen"] = [(p.buffer(0.05, join_style="mitre"), np.array(e)) for p, e in fl]
    n["dach3d"] = [(np.c_[np.asarray(p.exterior.coords), _z(e, *np.asarray(p.exterior.coords).T)],
                    [np.c_[np.asarray(h.coords), _z(e, *np.asarray(h.coords).T)] for h in p.interiors]) for p, e in fl]
    return n


def zaehlen(b):
    """(Wände, Dachflächen) eines Gebäudes - fürs Protokoll"""
    from .gebaeude_laser import _ring_kanten
    nw = sum(len(r) for r in _ring_kanten(b["footprint"])) if b.get("footprint") is not None else 0
    nd = len(b.get("dach3d") or []) or (len(_polys(b["footprint"])) if b.get("footprint") is not None else 0)
    return nw, nd
