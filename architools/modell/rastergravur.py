"""Rastergravur (EXPERIMENTELL, an der Werkstatt noch nicht getestet).

Die Werkstatt nimmt Gravur nur als schwarze Fläche (Vektor). Deshalb wird jede Rastergravur als Linienraster aus
schwarzen Streifen geschrieben: waagerechte Zeilen im Abstand `weite` mm; der Grauwert steckt in der Streifenbreite.
Zwei Arten:
  * Ebene (Fläche) als Raster: gleichmäßiger Grauwert in %, z. B. Wald 40 %, Wasser 20 %.
  * Bild (Luftbild, Karte oder eigene Bilddatei): jede Zeile bekommt eine Breite nach der Dunkelheit des Bildes.
Bei Schichtmodellen bekommt jede Schicht nur ihren sichtbaren Teil (Ring), zusammen ergibt das wieder ein durchgehendes Bild.
Ob die Werkstatt Bitmaps in der PDF annimmt, ist offen; dieses Linienraster hält sich an die Vektor-Regeln, erzeugt aber
viele Einzelobjekte.
"""
import math

import numpy as np
import shapely
from shapely.geometry import Polygon, box

from .geomutil import polys

MIN_STREIFEN = 0.08         # schmalere Streifen werden weggelassen (der Laser bildet sie nicht ab)
MAX_STREIFEN = 0.92         # Anteil der Zeilenbreite: bleibt immer ein Steg zwischen den Zeilen


def flaechen_raster(geom, grau, weite):
    """Fläche mit waagerechtem Streifenraster füllen. grau in % (0–100), weite = Zeilenabstand in mm. -> Liste Polygone"""
    if geom is None or geom.is_empty:
        return []
    grau = max(0.0, min(100.0, float(grau)))
    weite = max(0.2, float(weite))
    if grau >= 96:
        return polys(geom)
    w = weite * grau / 100.0
    if w < MIN_STREIFEN:
        return []
    w = min(w, weite * MAX_STREIFEN)
    x0, y0, x1, y1 = geom.bounds
    out = []
    y = math.floor(y0 / weite) * weite
    while y < y1:
        s = shapely.clip_by_rect(geom, x0 - 1, y, x1 + 1, y + w)
        if not s.is_empty:
            out += [p for p in polys(s) if p.area > 0.01]
        y += weite
    return out


class Bild:
    """Graustufenbild mit Lage in Weltkoordinaten. dunkel(x, y) -> 0 (weiß) … 1 (schwarz)"""

    def __init__(self, grau, rect_welt):
        self.g = np.asarray(grau, dtype=np.float32) / 255.0      # 0 schwarz … 1 weiss
        self.x0, self.y0, self.x1, self.y1 = rect_welt
        self.h, self.w = self.g.shape

    def dunkel(self, x, y):
        c = (np.asarray(x) - self.x0) / (self.x1 - self.x0) * (self.w - 1)
        r = (self.y1 - np.asarray(y)) / (self.y1 - self.y0) * (self.h - 1)
        c = np.clip(np.rint(c).astype(int), 0, self.w - 1)
        r = np.clip(np.rint(r).astype(int), 0, self.h - 1)
        return 1.0 - self.g[r, c]


def bild_raster(bild, region, modell_zu_welt, weite, kontrast=1.0, helligkeit=0.0, schritt=None):
    """Bild als Linienraster mit veränderlicher Streifenbreite auf region (Modell-mm). -> Liste Polygone
    modell_zu_welt: Funktion (Nx2 Modell-mm) -> (Nx2 Welt). kontrast: >1 kräftiger, helligkeit: -1 … +1 (positiv = heller)."""
    if region is None or region.is_empty:
        return []
    weite = max(0.25, float(weite))
    schritt = schritt or max(0.2, weite / 2.0)
    x0, y0, x1, y1 = region.bounds
    out = []
    y = math.floor(y0 / weite) * weite + weite / 2
    while y < y1 + weite / 2:
        zeile = shapely.clip_by_rect(region, x0 - 1, y - weite / 2, x1 + 1, y + weite / 2)
        if zeile.is_empty:
            y += weite
            continue
        for stueck in polys(zeile):
            a, _, b, _ = stueck.bounds
            xs = np.arange(a, b + schritt, schritt)
            if len(xs) < 2:
                continue
            wxy = np.asarray(modell_zu_welt(np.c_[xs, np.full(len(xs), y)]))
            d = bild.dunkel(wxy[:, 0], wxy[:, 1])
            d = np.clip(d * float(kontrast) - float(helligkeit), 0.0, 1.0)
            wd = np.minimum(d * weite, weite * MAX_STREIFEN)
            an = wd >= MIN_STREIFEN
            if not an.any():
                continue
            # zusammenhängende Läufe
            idx = np.flatnonzero(np.diff(np.r_[0, an.astype(int), 0]))
            for s0, s1 in zip(idx[::2], idx[1::2]):
                if s1 - s0 < 2:
                    continue
                px, pw = xs[s0:s1], wd[s0:s1] / 2.0
                pts = list(zip(px, y + pw)) + list(zip(px[::-1], y - pw[::-1]))
                pg = Polygon(pts)
                if not pg.is_valid:
                    pg = pg.buffer(0)
                if pg.is_empty:
                    continue
                pg = pg.simplify(0.03).intersection(stueck)
                out += [p for p in polys(pg) if p.area > 0.01]
        y += weite
    return out


# ------------------------------------------------------------------ Bild beschaffen
def bild_beschaffen(cfg, extent_welt, log=print):
    """Quelle laut cfg["raster_bild"] -> Bild (Graustufen) oder None. Quelle: WMS-Schlüssel (z. B. "luftbild") oder Datei."""
    rb = cfg.get("raster_bild") or {}
    from PIL import Image
    x0, y0, x1, y1 = extent_welt
    if rb.get("quelle") == "datei":
        pfad = rb.get("datei") or ""
        if not pfad:
            log("  Rastergravur: keine Bilddatei angegeben")
            return None
        try:
            import warnings
            import rasterio
            with warnings.catch_warnings(), rasterio.open(pfad) as r:
                warnings.simplefilter("ignore")
                arr = r.read()
                b = r.bounds
                if r.crs is None or abs(b.right - b.left) < 5:
                    raise ValueError("ohne Georeferenz")
                im = Image.fromarray(np.moveaxis(arr[:3] if arr.shape[0] >= 3 else arr[:1].repeat(3, 0), 0, -1).astype("uint8"))
                rect = (b.left, b.bottom, b.right, b.top)
        except Exception:
            im = Image.open(pfad).convert("RGB")                  # ohne Georeferenz: auf den Ausschnitt gestreckt
            rect = (x0, y0, x1, y1)
            log("  Rastergravur: Bild ohne Georeferenz - wird auf den ganzen Ausschnitt gestreckt")
        return Bild(np.asarray(im.convert("L")), rect)
    # WMS (Berlin)
    import ifcmap_kern as K
    import ifcmap_wms as WM
    key = rb.get("quelle") or "luftbild"
    if key not in WM.WMS_KATALOG:
        log(f"  Rastergravur: unbekannte Bildquelle {key}")
        return None
    name, dienste, wahl, foto = WM.WMS_KATALOG[key]
    netz = cfg.get("netz") or {}
    ctx = K.ssl_kontext(netz.get("cafile", ""), netz.get("unsicher", False))
    for s in dienste:
        basis = WM.WMS_BASIS + s
        try:
            eb = WM._gewaehlt(WM.ebenen_lesen(basis, ctx), wahl)
            if not eb:
                continue
            aufl = max(0.25, float(rb.get("weite_mm", 0.5)) / 3.0 * float(cfg.get("massstab", 500)) / 1000.0)
            im, W, H, px = WM.bild_holen(basis, eb, (x0, y0, x1, y1), aufl, foto, ctx, log)
            log(f"  Rastergravur: Bildquelle {name} ({s}), {W} × {H} Pixel")
            return Bild(np.asarray(im.convert("L")), (x0, y0, x0 + W * px, y1))   # Oberkante bei y1
        except Exception as e:
            log(f"  Rastergravur: Dienst {s} nicht nutzbar ({str(e)[:70]})")
    log("  Rastergravur: kein Bild geladen - übersprungen")
    return None
