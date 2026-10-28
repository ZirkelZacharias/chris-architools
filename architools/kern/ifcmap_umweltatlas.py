"""Umweltatlas Berlin als zusaetzliche amtliche Quelle (nur Berlin, nur auf Wunsch). Bisher NICHT gegen die Live-Dienste getestet
(nur mit nachgebauten Daten); die Dienstadressen stammen aus den Metadaten von gdi.berlin.de.

  - Gebaeudehoehen (WFS ua_gebaeudehoehen): Firsthoehe, Geschosse, Dachart je Gebaeude -> Hoehe und Dachform fuer Gebaeude ohne LoD2
  - Vegetationshoehen 2020 (1-m-Raster, Dezimeter; ATOM-Download veghoehe_2020.zip, ca. 785 MB, einmalig) -> Baumhoehen und
    Baeume, die im Baumkataster fehlen
  - Vegetationshoehen je Blockflaeche (WFS, Mittelwerte) als billiger Ersatz fuer Baeume ohne Hoehe
Reihenfolge der Quellen: Baumkataster / ALKIS / LoD2 (amtlich) -> Umweltatlas (amtlich) -> OpenStreetMap (nur, was sonst fehlt)."""
import math
import os
import re
import zipfile

import numpy as np
import shapely
from shapely.strtree import STRtree

UA_GEB = "ua_gebaeudehoehen"
UA_VEG = "ua_vegetationshoehen_2020"
VEG_TYP = "ua_vegetationshoehen_2020:a_vegetationshoehe_2020"
VEG_ZIP_URL = "https://gdi.berlin.de/data/ua_vegetationshoehen_2020/atom/veghoehe_2020.zip"

# Dachart-Text (klein, ae/oe/ue) -> OSM-roof:shape
DACHFORMEN = [("flach", "flat"), ("pult", "skillion"), ("pultdach", "skillion"), ("kruppelwalm", "half-hipped"), ("krueppelwalm", "half-hipped"),
              ("mansardwalm", "mansard"), ("mansard", "mansard"), ("walm", "hipped"), ("zelt", "pyramidal"), ("sattel", "gabled"),
              ("tonne", "round"), ("kegel", "cone"), ("kuppel", "dome"), ("turm", "pyramidal"), ("pyramid", "pyramidal")]


def _norm(t):
    return str(t or "").lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")


def dachform(props):
    """Dachart aus den Umweltatlas-Attributen -> roof:shape (oder None, wenn unbekannt/sonstiges)"""
    txt = ""
    for k, v in props.items():
        if _norm(k) == "dachart_txt" and v:
            txt = _norm(v)
            break
    if not txt:
        return None
    for key, form in DACHFORMEN:
        if key in txt:
            return form
    return None


def _zahl(props, name, lo, hi):
    for k, v in props.items():
        if _norm(k) == name:
            try:
                x = float(str(v).replace(",", "."))
            except ValueError:
                return None
            return x if lo <= x <= hi else None
    return None


class Index:
    """Umweltatlas-Gebaeude im Rechteck: .treffer(polygon) -> dict(hoehe, geschosse, dach) des Gebaeudes mit der groessten Ueberlappung
    (mind. 50 % der Grundflaeche), sonst None"""

    def __init__(self, geoms, daten):
        self.geoms, self.daten = geoms, daten
        self.baum = STRtree(geoms) if geoms else None

    def __len__(self):
        return len(self.geoms)

    def treffer(self, poly):
        if self.baum is None or poly is None or poly.is_empty or poly.area <= 0:
            return None
        beste, flaeche = None, 0.0
        for i in self.baum.query(poly):
            try:
                a = poly.intersection(self.geoms[int(i)]).area
            except Exception:
                continue
            if a > flaeche:
                beste, flaeche = self.daten[int(i)], a
        return beste if beste is not None and flaeche >= 0.5 * poly.area else None

    def hoehe(self, poly):
        t = self.treffer(poly)
        return t["hoehe"] if t else None


def gebaeudehoehen_laden(K, cfg, d, log):
    basis = K.WFS_GDI + UA_GEB
    ctx = K.ssl_kontext(cfg.cafile, cfg.unsicher)
    typ = None
    try:
        namen = K.wfs_typnamen(basis, ctx)
        typ = next((n for n in namen if "gebaeudehoehe" in _norm(n)), None) or (namen[0] if namen else None)
    except Exception as e:
        log("  Umweltatlas Gebaeudehoehen: Typenliste nicht lesbar (%s)" % str(e)[:100])
    if not typ:
        return Index([], [])
    feats = K._wfs_extra(cfg, d, basis, typ, log)
    geoms, daten, unbekannt = [], [], set()
    for g, p in feats:
        h = _zahl(p, "hoehe", 1.0, 400.0)
        if h is None:
            continue
        form = dachform(p)
        if form is None:
            for k, v in p.items():
                if _norm(k) == "dachart_txt" and v:
                    unbekannt.add(str(v))
        for t in K._teile(g):
            if t.geom_type in ("Polygon", "MultiPolygon") and not t.is_empty:
                geoms.append(t)
                daten.append(dict(hoehe=h, geschosse=_zahl(p, "geschosse", 0.5, 100), dach=form))
    log("  Umweltatlas Gebaeudehoehen: %d Gebaeude mit Hoehe im Rechteck (Feature-Typ %s)%s"
        % (len(geoms), typ, "; Dachart nicht zugeordnet: %s" % ", ".join(sorted(unbekannt)[:6]) if unbekannt else ""))
    return Index(geoms, daten)


# ----------------------------------------------------------------------------------------------
# Vegetationshoehen
# ----------------------------------------------------------------------------------------------

def _block_baumhoehen(K, cfg, d, log):
    """Blockflaechen mit mittlerer Baumhoehe -> (STRtree, Werte) oder None"""
    feats = K._wfs_extra(cfg, d, K.WFS_GDI + UA_VEG, VEG_TYP, log)
    geoms, werte = [], []
    for g, p in feats:
        w = _zahl(p, "mean_oeff_baum2020", 1.0, 60.0) or _zahl(p, "mean_vegh_bl2020", 1.0, 60.0)
        if w:
            for t in K._teile(g):
                if t.geom_type in ("Polygon", "MultiPolygon"):
                    geoms.append(t)
                    werte.append(w)
    return (STRtree(geoms), werte) if geoms else None


def raster_lesen(K, cfg, d, rect, log):
    """1-m-Vegetationsraster (Hoehe in m, NaN = keine Vegetation) fuer das Rechteck -> (Array, (x0, y_oben), Zellgroesse) oder None.
    Quelle: eigene GeoTIFFs (cfg.veg_raster_dateien), sonst Berlin-Download (einmalig, im Zwischenspeicher)."""
    import rasterio
    from rasterio.windows import from_bounds
    pfade = [p for p in (getattr(cfg, "veg_raster_dateien", None) or []) if os.path.exists(p)]
    if not pfade:
        if not K.ist_berlin(cfg):
            return None
        ziel = os.path.join(K.cache_ordner(), "veghoehe_2020.zip")
        if not os.path.exists(ziel) or os.path.getsize(ziel) < 1000:
            log("  Vegetationsraster Berlin wird geladen (einmalig, ca. 785 MB) ...")
            if not K._datei_laden(VEG_ZIP_URL, ziel, K.ssl_kontext(cfg.cafile, cfg.unsicher), log):
                return None
        with zipfile.ZipFile(ziel) as z:
            namen = [n for n in z.namelist() if n.lower().endswith((".tif", ".tiff"))]
        if not namen:
            log("  Vegetationsraster: keine GeoTIFF-Datei im Archiv gefunden")
            return None
        pfade = ["/vsizip/%s/%s" % (ziel.replace("\\", "/"), namen[0])]
    x0, y0, x1, y1 = rect.bounds
    for pf in pfade:
        try:
            with rasterio.open(pf) as ds:
                fen = from_bounds(x0, y0, x1, y1, ds.transform).round_offsets().round_lengths()
                if fen.width < 2 or fen.height < 2:
                    continue
                a = ds.read(1, window=fen, boundless=True, fill_value=0).astype(np.float32)
                nod = ds.nodata
                tr = ds.window_transform(fen)
                zg = abs(tr.a)
                if nod is not None:
                    a[a == nod] = np.nan
                a[a <= 0] = np.nan
                a /= 10.0                                     # Dezimeter -> Meter
                a[a > 70.0] = np.nan                          # Fuellwerte (z. B. 255 dm = 25,5 m kaeme noch vor; ab 70 m unsinnig)
                log("  Vegetationsraster: %d x %d Zellen a %.1f m, %.0f %% mit Vegetation" % (a.shape[1], a.shape[0], zg, 100.0 * np.isfinite(a).mean()))
                return a, (tr.c, tr.f), zg
        except Exception as e:
            log("  Vegetationsraster %s nicht lesbar: %s" % (os.path.basename(pf), str(e)[:140]))
    return None


def baeume_aus_raster(a, ursprung, zg, mindest=4.0):
    """Baumspitzen = lokale Maxima der geglaetteten Vegetationshoehe (>= mindest m). -> Liste (x, y, hoehe, kronen_durchmesser)"""
    from scipy.ndimage import gaussian_filter, maximum_filter
    from scipy.spatial import cKDTree
    f = np.where(np.isfinite(a), a, 0.0)
    g = gaussian_filter(f, 1.0)
    r = max(1, int(round(2.0 / zg)))                          # Baeume stehen mind. ca. 2 m auseinander
    m = (g == maximum_filter(g, size=2 * r + 1)) & (g >= mindest) & np.isfinite(a)
    from scipy.ndimage import label, center_of_mass
    lab, n = label(m, structure=np.ones((3, 3)))              # Plateaus (gleich hohe Nachbarzellen) zaehlen als EIN Baum
    if n == 0:
        return []
    cm = np.array(center_of_mass(m, lab, range(1, n + 1)))
    iy, ix = np.rint(cm[:, 0]).astype(int), np.rint(cm[:, 1]).astype(int)
    x = ursprung[0] + (ix + 0.5) * zg
    y = ursprung[1] - (iy + 0.5) * zg
    h = maximum_filter(f, size=3)[iy, ix]                  # echte Spitzenhoehe (ungeglaettet)
    nn = cKDTree(np.column_stack([x, y])).query(np.column_stack([x, y]), k=2)[0][:, 1] if len(x) > 1 else np.full(len(x), 99.0)
    kr = np.clip(np.minimum(0.35 * h + 1.5, nn * 1.15), 2.0, 14.0)
    return list(zip(x.tolist(), y.tolist(), h.tolist(), kr.tolist()))


def baeume_ergaenzen(K, cfg, d, log, gebaeude=None, osm_extra=None):
    """Baeume ohne eigene Hoehe bekommen die Raster-Hoehe, Baeume, die im Kataster fehlen, werden aus dem Raster ergaenzt.
    Faellt das Raster aus (oder ist nur ua_vegetationshoehen gewaehlt), gilt der Blockmittelwert fuer Baeume ohne Hoehe.
    osm_extra = Baeume aus OpenStreetMap: kommen zuletzt dazu, nur wo kein amtlicher Baum (Kataster oder Raster) im Umkreis von 3 m steht.
    Gibt (hoehen_gesetzt, neue_baeume_raster, neue_baeume_osm) zurueck."""
    rect = d.baum_rect
    ras = None
    if getattr(cfg, "ua_vegetationsraster", False):
        try:
            ras = raster_lesen(K, cfg, d, rect, log)
        except Exception as e:
            log("  Vegetationsraster nicht verfuegbar (%s)" % str(e)[:140])
    n_h = n_neu = n_osm = 0
    ras_h = None
    baeume = list(d.baeume)
    if ras is not None:
        a, (ox, oy), zg = ras
        ras_h = (a, ox, oy, zg)
        neu = []
        for b in baeume:
            x, y, kr, ho, st = b[0], b[1], b[2], b[3], b[4]
            if abs(ho - K.BAUM_HOEHE_STANDARD) < 1e-6:                 # keine eigene Hoehe in den Daten
                rr = max(1, int(round(max(kr, 2.0) / 2.0 / zg)))
                cx, cy = int((x - ox) / zg), int((oy - y) / zg)
                fen = a[max(0, cy - rr):cy + rr + 1, max(0, cx - rr):cx + rr + 1]
                if fen.size and np.isfinite(fen).any():
                    ho = float(np.nanmax(fen))
                    n_h += 1
            neu.append((x, y, kr, ho, st) + tuple(b[5:]))
        baeume = neu
        # fehlende Baeume
        kand = baeume_aus_raster(a, (ox, oy), zg, getattr(cfg, "veg_mindesthoehe", 4.0))
        if kand:
            if baeume:
                from scipy.spatial import cKDTree
                pb = np.array([(b[0], b[1]) for b in baeume])
                kb = np.array([b[2] for b in baeume])
                kd = cKDTree(pb)
            hh = None
            if gebaeude is None:
                gebaeude = _gebaeude_flaechen(d)
            neue = []
            for (x, y, h, kr) in kand:
                if not rect.contains(shapely.Point(x, y)):
                    continue
                if baeume:
                    dist, i = kd.query([x, y])
                    if dist < max(2.5, 0.5 * kb[int(i)]):
                        continue
                if gebaeude is not None and len(gebaeude[0].query(shapely.Point(x, y), predicate="within")):
                    continue
                neue.append((x, y, kr, h, K.BAUM_STAMM_STANDARD, True))
            grenze = int(getattr(cfg, "veg_max_baeume", 20000) or 20000)
            if len(neue) > grenze:
                neue.sort(key=lambda t: -t[3])
                log("  Vegetationsraster: %d Baumspitzen, nur die %d hoechsten werden uebernommen (Einstellung veg_max_baeume)" % (len(neue), grenze))
                neue = neue[:grenze]
            baeume += neue
            n_neu = len(neue)
        log("  Vegetationsraster: %d Baeume bekamen die Rasterhoehe, %d fehlende Baeume ergaenzt (nur Spitzen >= %.0f m, ausserhalb von Gebaeuden)"
            % (n_h, n_neu, getattr(cfg, "veg_mindesthoehe", 4.0)))
    elif getattr(cfg, "ua_vegetationshoehen", False) and baeume:
        bl = _block_baumhoehen(K, cfg, d, log)
        if bl is None:
            log("  Umweltatlas Vegetationshoehen: keine Blockflaechen mit Wert im Rechteck")
        else:
            neu = []
            for b in baeume:
                x, y, kr, ho, st = b[0], b[1], b[2], b[3], b[4]
                if abs(ho - K.BAUM_HOEHE_STANDARD) < 1e-6:
                    for i in bl[0].query(shapely.Point(x, y), predicate="within"):
                        ho = bl[1][int(i)]
                        n_h += 1
                        break
                neu.append((x, y, kr, ho, st) + tuple(b[5:]))
            baeume = neu
            log("  Umweltatlas Vegetationshoehen (Blockmittelwerte): %d Baeume ohne Hoehenangabe erhielten die mittlere Baumhoehe ihrer Blockflaeche" % n_h)
    if osm_extra:
        from scipy.spatial import cKDTree
        kd = cKDTree(np.array([(b[0], b[1]) for b in baeume])) if baeume else None
        plus = []
        for b in osm_extra:
            if kd is not None and kd.query([b[0], b[1]])[0] < 3.0:
                continue
            x, y, kr, ho, st = b[0], b[1], b[2], b[3], b[4]
            if ras_h is not None and abs(ho - K.BAUM_HOEHE_STANDARD) < 1e-6:
                a, ox, oy, zg = ras_h
                rr = max(1, int(round(max(kr, 2.0) / 2.0 / zg)))
                cx, cy = int((x - ox) / zg), int((oy - y) / zg)
                fen = a[max(0, cy - rr):cy + rr + 1, max(0, cx - rr):cx + rr + 1]
                if fen.size and np.isfinite(fen).any():
                    ho = float(np.nanmax(fen))
            plus.append((x, y, kr, ho, st) + tuple(b[5:]))
        baeume += plus
        n_osm = len(plus)
        log("  OpenStreetMap: %d Baeume ergaenzt, die es in den amtlichen Quellen nicht gibt (kein amtlicher Baum im Umkreis von 3 m)" % n_osm)
    d.baeume = baeume
    return n_h, n_neu, n_osm


def _gebaeude_flaechen(d):
    """(STRtree, Polygone) der Gebaeudegrundrisse (LoD2 und ergaenzte)"""
    from shapely.geometry import Polygon
    polys = []
    for t in getattr(d, "teile", []) or []:
        for e, h in (t.get("ground") or t.get("roof") or []):
            try:
                if len(e) >= 3:
                    pg = Polygon(np.asarray(e)[:, :2]).buffer(0)
                    if not pg.is_empty:
                        polys.append(pg)
            except Exception:
                pass
    return (STRtree(polys), polys) if polys else None
