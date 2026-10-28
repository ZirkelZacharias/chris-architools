"""Formgenaues Nesting über ein Belegungsraster.

Jedes Teil wird (in mehreren Drehungen) gerastert; per FFT-Korrelation werden
alle kollisionsfreien Positionen auf einmal gefunden, gewählt wird die
unterste, dann linkeste (Bottom-Left). Kleine Teile landen dadurch auch in
Löchern großer Teile (z. B. im Inneren der Hohlbau-Ringe).
"""
import numpy as np
from affine import Affine
from rasterio.features import rasterize
from scipy.signal import fftconvolve
from shapely import affinity


class Item:
    def __init__(self, key, geom, angles=(0, 90, 180, 270)):
        self.key = key
        self.geom = geom
        self.area = geom.area
        mrr = geom.minimum_rotated_rectangle
        xs, ys = mrr.exterior.coords.xy
        a = np.degrees(np.arctan2(ys[1] - ys[0], xs[1] - xs[0]))
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
    """Bottom-Left-Packen. Mit occ wird in eine bestehende Belegung gepackt (occ wird kopiert)."""
    occ = _empty(W, H, margin, res) if occ is None else occ.copy()
    ny, nx = occ.shape
    placed, rest = [], []
    for it in items:
        best = None
        for ang in it.angles:
            k, minx, miny = _kernel(it, ang, gap, res)
            kh, kw = k.shape
            if kh > ny or kw > nx:
                continue
            conv = fftconvolve(occ, k[::-1, ::-1], mode="valid")
            feas = np.argwhere(conv < 0.5)
            if not len(feas):
                continue
            score = (feas[:, 0].astype(np.int64) + kh) * nx + feas[:, 1]   # niedrigste Oberkante, dann links
            i = int(np.argmin(score))
            if best is None or score[i] < best[0]:
                best = (score[i], ang, int(feas[i, 0]), int(feas[i, 1]), minx, miny, k)
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


def nest(items, formats, margin, gap, res, log=print, label="Platte", filler=None, n_filler=0, tries=3):
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

    orders = [lambda i: -i.area, lambda i: -bbox_area(i), lambda i: -maxdim(i)][:max(1, tries)]
    best = None
    for key in orders:
        sh, rest, left = _run(sorted(items, key=key), formats, margin, gap, res, filler, n_filler)
        score = (len(rest), sum(s["format"][0] * s["format"][1] for s in sh), len(sh))
        if best is None or score < best[0]:
            best = (score, sh, rest, left)
    _, sheets, rest, left = best
    fa = filler.area if filler is not None else 0
    for n, s in enumerate(sheets, 1):
        W, H = s["format"]
        a = sum(p[0].area for p in s["placements"]) + fa * len(s["filler"])
        extra = f" + {len(s['filler'])} Stützklötze" if s["filler"] else ""
        log(f"  {label} {n}: {W:.0f} x {H:.0f} mm, {len(s['placements'])} Teile{extra}, "
            f"Ausnutzung {100 * a / (W * H):.0f} %")
    if rest:
        log(f"  Warnung: {len(rest)} Teile passen auf kein {label}nformat")
    if left > 0:
        log(f"  Warnung: {left} Stützklötze nicht platziert")
    return sheets, rest
