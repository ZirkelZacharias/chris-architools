"""Formgenaues Nesting über ein Belegungsraster.

Jedes Teil wird (in mehreren Drehungen) gerastert; per FFT-Korrelation werden
alle kollisionsfreien Positionen auf einmal gefunden, gewählt wird die
unterste, dann linkeste (Bottom-Left). Kleine Teile landen dadurch auch in
Löchern großer Teile (z. B. im Inneren der Hohlbau-Ringe).
"""
import os

import numpy as np
from affine import Affine
from rasterio.features import rasterize
from scipy import fft as sfft
from scipy.signal import fftconvolve
from shapely import affinity


class Item:
    def __init__(self, key, geom, angles=(0, 90, 180, 270)):
        self.key = key
        self.geom = geom
        self.area = geom.area
        a = 0.0
        try:                                                  # entartete Form (Linie, Punkt, leer): ohne Zusatzdrehung
            mrr = geom.minimum_rotated_rectangle
            if mrr.geom_type == "Polygon" and not mrr.is_empty:
                xs, ys = mrr.exterior.coords.xy
                a = float(np.degrees(np.arctan2(ys[1] - ys[0], xs[1] - xs[0])))
        except Exception:
            pass
        extra = [(-a) % 360, (90 - a) % 360]
        self.angles = sorted(set([round(x, 3) % 360 for x in list(angles) + extra]))
        self._k = {}


def _raster(geom, shape, res):
    return rasterize([(geom, 1)], out_shape=shape, transform=Affine(res, 0, 0, 0, res, 0),
                     all_touched=True, dtype="uint8").astype(np.float32)


def _kernel(item, ang, gap, res):
    key = (ang, gap, res)
    if key not in item._k:
        g = affinity.rotate(item.geom, ang, origin=(0, 0))
        gb = g.buffer(gap / 2.0, 6) if gap > 0 else g
        minx, miny, maxx, maxy = gb.bounds
        kw = int(np.ceil((maxx - minx) / res)) + 1
        kh = int(np.ceil((maxy - miny) / res)) + 1
        k = _raster(affinity.translate(gb, -minx, -miny), (kh, kw), res)
        item._k[key] = (k, minx, miny)
    return item._k[key]


def _empty(W, H, margin, res):
    nx, ny = int(W / res), int(H / res)
    occ = np.zeros((ny, nx), np.float32)
    m = int(np.ceil(margin / res))
    if m > 0:
        occ[:m, :] = 1
        occ[-m:, :] = 1
        occ[:, :m] = 1
        occ[:, -m:] = 1
    return occ


def _pack(items, W, H, margin, gap, res, occ=None):
    """Bottom-Left-Packen. Mit occ wird in eine bestehende Belegung gepackt (occ wird kopiert).

    Schnell: je Teil wird die Belegung nur EINMAL fouriertransformiert (nicht je Drehung), und nur bis knapp ueber die hoechste belegte
    Zeile (darueber ist alles frei - die erste freie Stelle liegt spaetestens dort). Die erste freie Stelle ist die niedrigste Zeile,
    dann die linkeste: das Ergebnis ist dasselbe wie bei der Suche ueber die ganze Platte, nur wesentlich schneller."""
    occ = _empty(W, H, margin, res) if occ is None else occ.copy()
    ny, nx = occ.shape
    m = int(np.ceil(margin / res))
    placed, rest = [], []
    for it in items:
        kerns = []
        for ang in it.angles:
            k, minx, miny = _kernel(it, ang, gap, res)
            if k.shape[0] <= ny and k.shape[1] <= nx:
                kerns.append((ang, k, minx, miny))
        if not kerns:
            rest.append(it)
            continue
        kh_max = max(k.shape[0] for _, k, _, _ in kerns)
        inner = occ[:max(1, ny - m), m:max(m + 1, nx - m)].any(axis=1)
        top = int(np.nonzero(inner)[0][-1]) + 1 if inner.any() else 0
        R = min(ny, max(top, m) + kh_max + 1)
        shp = (sfft.next_fast_len(R, real=True), sfft.next_fast_len(nx, real=True))
        f_occ = sfft.rfft2(occ[:R], s=shp, workers=1)
        best = None
        for ang, k, minx, miny in kerns:
            kh, kw = k.shape
            conv = sfft.irfft2(f_occ * np.conj(sfft.rfft2(k, s=shp, workers=1)), s=shp, workers=1)[:R - kh + 1, :nx - kw + 1]
            frei = (conv < 0.5).ravel()
            i = int(frei.argmax())
            if not frei[i]:
                continue
            r, c = divmod(i, conv.shape[1])
            score = (r + kh) * nx + c                      # niedrigste Oberkante, dann links
            if best is None or score < best[0]:
                best = (score, ang, r, c, minx, miny, k)
        if best is None:
            rest.append(it)
            continue
        _, ang, r, c, minx, miny, k = best
        kh, kw = k.shape
        occ[r:r + kh, c:c + kw] = np.maximum(occ[r:r + kh, c:c + kw], k)
        placed.append((it, ang, -minx + c * res, -miny + r * res))
    return placed, rest, occ


def _fill(occ, geom, gap, res, need):
    """Füllt Lücken mit identischen Kleinteilen (Stützklötze). Rückgabe: [(dx, dy)]."""
    if need <= 0:
        return []
    gb = geom.buffer(gap / 2.0, 6)
    minx, miny, maxx, maxy = gb.bounds
    kw = int(np.ceil((maxx - minx) / res)) + 1
    kh = int(np.ceil((maxy - miny) / res)) + 1
    ny, nx = occ.shape
    if kh > ny or kw > nx:
        return []
    k = _raster(affinity.translate(gb, -minx, -miny), (kh, kw), res)
    conv = fftconvolve(occ, k[::-1, ::-1], mode="valid")
    out = []
    for r, c in np.argwhere(conv < 0.5):
        win = occ[r:r + kh, c:c + kw]
        if (win * k).sum() > 0.5:
            continue
        occ[r:r + kh, c:c + kw] = np.maximum(win, k)
        out.append((-minx + c * res, -miny + r * res))
        if len(out) >= need:
            break
    return out


def place(geom, ang, dx, dy):
    return affinity.translate(affinity.rotate(geom, ang, origin=(0, 0)), dx, dy)


def place_viele(geoms, ang, dx, dy):
    """Wie place, aber für lange Listen (Raster aus Zehntausenden Linien/Punkten) auf einmal und damit viel schneller."""
    if len(geoms) < 50:
        return [place(g, ang, dx, dy) for g in geoms]
    import shapely
    a = np.radians(ang)
    c, sn = np.cos(a), np.sin(a)
    arr = np.empty(len(geoms), dtype=object)
    arr[:] = list(geoms)
    return list(shapely.transform(arr, lambda xy: np.c_[xy[:, 0] * c - xy[:, 1] * sn + dx, xy[:, 0] * sn + xy[:, 1] * c + dy]))


def _run(items, formats, margin, gap, res, filler, n_filler):
    sheets = []
    rest = items
    left = n_filler
    while rest:
        best = None
        for fw, fh in formats:
            pl, rs, occ = _pack(rest, fw, fh, margin, gap, res)
            if not pl:
                continue
            util = sum(p[0].area for p in pl) / (fw * fh)
            score = (len(rs) == 0, util)     # alles Restliche drauf? dann kleinstes passendes Format
            if best is None or score > best[0]:
                best = (score, (fw, fh), pl, rs, occ)
        if best is None:
            return sheets, rest, left
        _, fmt, pl, rs, occ = best
        sheets.append({"format": fmt, "placements": pl, "filler": [], "occ": occ})
        rest = rs
    # Verdichten: schwach belegte Platten in die Lücken der anderen umziehen
    changed = True
    while changed and len(sheets) > 1:
        changed = False
        order = sorted(range(len(sheets)), key=lambda i: _util(sheets[i]))
        for i in order:
            src = sheets[i]
            todo = [p[0] for p in src["placements"]]
            trial = {}
            for j in sorted((j for j in range(len(sheets)) if j != i), key=lambda j: -_util(sheets[j])):
                if not todo:
                    break
                t = sheets[j]
                pl, todo, occ = _pack(todo, *t["format"], margin, gap, res, occ=trial.get(j, (None, t["occ"]))[1])
                if pl:
                    trial[j] = (trial.get(j, ([], None))[0] + pl, occ)
            if not todo:
                for j, (pl, occ) in trial.items():
                    sheets[j]["placements"] = sheets[j]["placements"] + pl
                    sheets[j]["occ"] = occ
                del sheets[i]
                changed = True
                break
    # Stützklötze in die Lücken
    if filler is not None:
        for s in sheets:
            fill = _fill(s["occ"], filler, gap, res, left)
            s["filler"] = fill
            left -= len(fill)
        while left > 0:
            fmt = min(formats, key=lambda f: f[0] * f[1])
            occ = _empty(*fmt, margin, res)
            fill = _fill(occ, filler, gap, res, left)
            if not fill:
                break
            left -= len(fill)
            sheets.append({"format": fmt, "placements": [], "filler": fill, "occ": occ})
    return sheets, [], left


def _util(s):
    return sum(p[0].area for p in s["placements"]) / (s["format"][0] * s["format"][1])


def _restplatten(items, fest, margin, gap, res, log, label):
    """Restplatten zuerst belegen: je Restplatte werden die groessten Teile gepackt, die noch draufpassen.
    -> (Platten, uebrige Items). fest: [(Name, (B, H))]"""
    sheets, rest = [], list(items)
    for name, (fw, fh) in sorted(fest, key=lambda f: -f[1][0] * f[1][1]):
        if not rest:
            break
        pl, rs, occ = _pack(sorted(rest, key=lambda i: -i.area), fw, fh, margin, gap, res)
        if not pl:
            log(f"  {label} {name} ({fw:.0f} x {fh:.0f} mm): nichts passt darauf - nicht benutzt")
            continue
        sheets.append({"format": (fw, fh), "placements": pl, "filler": [], "occ": occ, "rest": name})
        rest = rs
    return sheets, rest


def nest(items, formats, margin, gap, res, log=print, label="Platte", filler=None, n_filler=0, tries=3, fest=None):
    """Verteilt items auf Platten. formats: [(B, H)].

    filler: Geometrie eines Kleinteils (z. B. Stützklotz), das n_filler-mal in Lücken gesetzt wird.
    Probiert mehrere Packreihenfolgen und nimmt die mit der kleinsten Plattenfläche.
    Rückgabe: Liste von dict(format, placements=[(item, ang, dx, dy)], filler=[(dx, dy)]),
              nicht platzierbare Items
    """
    def bbox_area(i):
        b = i.geom.bounds
        return (b[2] - b[0]) * (b[3] - b[1])

    def maxdim(i):
        b = i.geom.bounds
        return max(b[2] - b[0], b[3] - b[1])

    rest_sheets = []
    if fest:
        rest_sheets, items = _restplatten(items, fest, margin, gap, res, log, "Restplatte")
    orders = [lambda i: -i.area, lambda i: -bbox_area(i), lambda i: -maxdim(i)][:max(1, tries)]
    best = None

    def lauf(key):
        return _run(sorted(items, key=key), formats, margin, gap, res, filler, n_filler)

    if len(orders) > 1 and len(items) > 40:                 # die Reihenfolgen sind unabhaengig; FFT gibt die Sperre frei -> echte Parallelitaet
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(len(orders), max(1, os.cpu_count() or 1))) as ex:
            ergebnisse = list(ex.map(lauf, orders))
    else:
        ergebnisse = [lauf(key) for key in orders]
    for sh, rest, left in ergebnisse:
        score = (len(rest), sum(s["format"][0] * s["format"][1] for s in sh), len(sh))
        if best is None or score < best[0]:
            best = (score, sh, rest, left)
    _, sheets, rest, left = best
    sheets = sheets + rest_sheets
    fa = filler.area if filler is not None else 0
    for n, s in enumerate(sheets, 1):
        W, H = s["format"]
        a = sum(p[0].area for p in s["placements"]) + fa * len(s["filler"])
        extra = f" + {len(s['filler'])} Stützklötze" if s["filler"] else ""
        bez = f"Restplatte {s['rest']}" if s.get("rest") else f"{label} {n}"
        log(f"  {bez}: {W:.0f} x {H:.0f} mm, {len(s['placements'])} Teile{extra}, "
            f"Ausnutzung {100 * a / (W * H):.0f} %")
    if rest:
        log(f"  Warnung: {len(rest)} Teile passen auf kein {label}nformat")
    if left > 0:
        log(f"  Warnung: {left} Stützklötze nicht platziert")
    return sheets, rest
