# -*- coding: utf-8 -*-
"""IFCmap - Gelaende und Gebaeude ausserhalb Deutschlands (Schweiz, Niederlande) und die UTM-Zone nach dem Mittelpunkt.

Die Daten dieser Laender liegen in Landes-Koordinatensystemen (Schweiz LV95 EPSG:2056, Niederlande RD New EPSG:28992).
IFCmap rechnet aber immer in UTM. Darum wird alles beim Laden umgerechnet:
  Gelaende  -> je 1-km-Kachel eine GeoTIFF im UTM-System des Projekts (1 m Raster), danach liest der Kern sie wie ein DGM1.
  Gebaeude  -> je 1-km-Kachel eine CityGML-2.0-Datei im UTM-System, danach liest der Kern sie wie ein LoD2.
Hoehen bleiben im Landesbezug (LN02/LHN95 bzw. NAP) - fuer ein Modell spielt das keine Rolle.

Neue Arten fuer die Teile "dgm"/"lod2" eines Profils (siehe ifcmap_laender.py):
  "stac"   Kacheln ueber eine STAC-Schnittstelle (Rechteck-Abfrage), je Kachel die neueste Ausgabe (Schweiz: swissALTI3D)
  "wcs"    Ausschnitt je 1-km-Kachel per WCS 2.0 (Niederlande: AHN-Gelaendemodell); Ersatz: Kartenblatt aus dem Blattindex
  "3dbag"  Gebaeude ueber die 3DBAG-API (OGC API Features, CityJSON), umgewandelt in CityGML
Alles UNGETESTET gegen die echten Dienste (Adressen und Antwortformen am 30.10.2026 im Dienst selbst nachgelesen).
"""
import hashlib
import json
import math
import os
import re
import time
import urllib.parse
import urllib.request

import numpy as np

UA = {"User-Agent": "ZachariasTools/0.1 (+https://github.com/ZirkelZacharias/zacharias-tools)"}

# Grobe Landesumrisse (Laenge, Breite), auf wenige km genau. Sie entscheiden nur, welches Profil gilt - an der Grenze
# das Land in den Einstellungen von Hand waehlen.
UMRISS_SCHWEIZ = [
    (7.59, 47.59), (7.70, 47.54), (8.23, 47.62), (8.45, 47.58), (8.57, 47.81), (8.68, 47.69), (8.88, 47.66), (9.12, 47.66),
    (9.55, 47.53), (9.67, 47.39), (9.53, 47.27), (9.47, 47.05), (9.62, 47.06), (9.88, 46.93), (10.47, 46.87), (10.49, 46.62),
    (10.25, 46.63), (10.15, 46.38), (10.05, 46.23), (9.28, 46.50), (9.00, 46.03), (9.00, 45.82), (8.85, 45.98), (8.58, 46.15),
    (8.44, 46.46), (8.08, 46.26), (7.86, 45.92), (7.04, 45.92), (6.79, 46.15), (6.82, 46.43), (6.59, 46.45), (6.35, 46.40), (6.25, 46.30), (6.22, 46.24), (6.20, 46.18),
    (6.10, 46.14), (5.96, 46.13), (5.97, 46.21), (6.10, 46.25), (6.07, 46.41), (6.12, 46.58), (6.44, 46.92), (6.71, 47.03), (6.95, 47.24), (6.98, 47.49), (7.17, 47.45),
    (7.38, 47.43), (7.50, 47.50)]
UMRISS_NIEDERLANDE = [
    (3.36, 51.37), (3.85, 51.21), (4.25, 51.37), (4.43, 51.47), (4.77, 51.50), (5.10, 51.43), (5.24, 51.26), (5.50, 51.29),
    (5.67, 51.18), (5.86, 51.05), (5.65, 50.85), (5.69, 50.75), (6.02, 50.75), (6.08, 50.88), (6.17, 51.17), (6.07, 51.25),
    (6.22, 51.36), (6.20, 51.52), (5.95, 51.75), (6.17, 51.84), (6.47, 51.85), (6.75, 51.90), (6.85, 52.03), (7.07, 52.24),
    (6.70, 52.48), (7.05, 52.63), (7.20, 53.00), (7.20, 53.25), (6.90, 53.45), (6.00, 53.55), (5.00, 53.45), (4.70, 53.10),
    (4.50, 52.90), (4.45, 52.40), (4.05, 52.00), (3.60, 51.60)]

PROFILE = {
    "schweiz": dict(
        name="Schweiz", epsg="utm", box=(5.95, 45.81, 10.50, 47.82), umriss=UMRISS_SCHWEIZ, portal="https://www.swisstopo.admin.ch",
        dgm=dict(art="stac", kachel=1000, stac="https://data.geo.admin.ch/api/stac/v1", sammlung="ch.swisstopo.swissalti3d",
                 asset=r"_0\.5_2056_5728\.tif$", ersatz=r"_2_2056_5728\.tif$", daten_epsg=2056,
                 status="NEU, UNGETESTET - swissALTI3D ueber die STAC-Schnittstelle (Adressen am 30.10.2026 im Dienst gelesen)"),
        lod2=dict(art="manuell", kachel=1000,
                  status="kein automatischer Download: swissBUILDINGS3D gibt es nur als DWG/DXF/FileGDB - die Gebaeude kommen aus OpenStreetMap")),
    "niederlande": dict(
        name="Niederlande", epsg="utm", box=(3.30, 50.74, 7.23, 53.56), umriss=UMRISS_NIEDERLANDE, portal="https://www.pdok.nl",
        dgm=dict(art="wcs", kachel=1000, basis="https://service.pdok.nl/rws/ahn/wcs/v1_0", coverage="dtm_05m", daten_epsg=28992,
                 index="https://service.pdok.nl/rws/actueel-hoogtebestand-nederland/atom/downloads/dtm_05m/kaartbladindex.json",
                 status="NEU, UNGETESTET - AHN-Gelaendemodell 0,5 m per WCS (Dienst und Blattindex am 30.10.2026 gelesen)"),
        lod2=dict(art="3dbag", kachel=1000, basis="https://api.3dbag.nl", sammlung="pand", daten_epsg=28992,
                  status="NEU, UNGETESTET - 3DBAG (LoD2.2) ueber die 3DBAG-API, umgewandelt in CityGML")),
}
NAMEN = {k: v["name"] for k, v in PROFILE.items()}
EIGENE_ARTEN = ("stac", "wcs", "3dbag")


# ----------------------------------------------------------------------------------------------
# UTM-Zone und Umrisse
# ----------------------------------------------------------------------------------------------

def utm_epsg(lon, lat):
    """UTM-Zone am Punkt -> EPSG-Code. In Europa ETRS89 (25828-25838), sonst WGS84 (326xx Nord, 327xx Sued)."""
    zone = int(math.floor((float(lon) + 180.0) / 6.0)) % 60 + 1
    if lat >= 0 and 28 <= zone <= 38 and 34.0 <= lat <= 72.0:
        return 25800 + zone
    return (32600 if lat >= 0 else 32700) + zone


def zone_von(epsg):
    """EPSG eines UTM-Systems -> Zone (oder None)."""
    e = int(epsg)
    if 25801 <= e <= 25860 or 32601 <= e <= 32660 or 32701 <= e <= 32760:
        return e % 100
    return None


def im_umriss(lon, lat, ring):
    """Punkt-in-Polygon (Strahlverfahren)."""
    drin = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > lat) != (y2 > lat):
            x = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < x:
                drin = not drin
    return drin


# ----------------------------------------------------------------------------------------------
# Hilfen
# ----------------------------------------------------------------------------------------------

def _oeffnen(url, ctx, timeout=180):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout, context=ctx)


def _json(url, ctx, timeout=120):
    with _oeffnen(url, ctx, timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def _trafo(von, nach):
    from pyproj import Transformer
    return Transformer.from_crs("EPSG:%d" % von, "EPSG:%d" % nach, always_xy=True)


def _huelle(t, x0, y0, x1, y1, n=8):
    """Umgerechnetes Rechteck (Randpunkte, nicht nur Ecken) -> (xmin, ymin, xmax, ymax)."""
    xs = np.concatenate([np.linspace(x0, x1, n), np.full(n, x1), np.linspace(x1, x0, n), np.full(n, x0)])
    ys = np.concatenate([np.full(n, y0), np.linspace(y0, y1, n), np.full(n, y1), np.linspace(y1, y0, n)])
    a, b = t.transform(xs, ys)
    return float(np.min(a)), float(np.min(b)), float(np.max(a)), float(np.max(b))


def _dgm_name(cache, land, epsg, e, n):
    # Name mit Ost/Nord in Metern (6_7 Stellen) - so erkennt der Kern die Kachel am Namen
    return os.path.join(cache, "%s_dgm_utm%d_%06d_%07d.tif" % (land, zone_von(epsg) or 0, e, n))


def _lod_name(cache, land, epsg, e, n):
    return os.path.join(cache, "%s_lod2_utm%d_%06d_%07d.gml" % (land, zone_von(epsg) or 0, e, n))


def nach_utm(quellen, ziel, ziel_epsg, e, n, g=1000, res=1.0, rand=2.0):
    """Hoehenraster (Liste von Dateien im Landes-KBS) -> eine GeoTIFF im UTM-System fuer die Kachel (e, n, g), Raster res.
    -> Anzahl gueltiger Zellen (0 = nichts abgedeckt; dann wird keine Datei geschrieben)."""
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.warp import reproject, Resampling
    x0, y1 = e - rand, n + g + rand
    w = h = int(round((g + 2 * rand) / res))
    tf = from_origin(x0, y1, res, res)
    ziel_arr = np.full((h, w), np.nan, dtype="float32")
    for q in quellen:
        with rasterio.open(q) as src:
            arr = src.read(1).astype("float32")
            nod = src.nodata
            if nod is not None and np.isfinite(nod):
                arr[arr == nod] = np.nan
            arr[(arr < -1000) | (arr > 10000)] = np.nan              # AHN/swissALTI3D: Fuellwerte wie 3.4e38
            tmp = np.full((h, w), np.nan, dtype="float32")
            reproject(arr, tmp, src_transform=src.transform, src_crs=src.crs, src_nodata=np.nan,
                      dst_transform=tf, dst_crs="EPSG:%d" % ziel_epsg, dst_nodata=np.nan, resampling=Resampling.bilinear)
        m = np.isnan(ziel_arr) & np.isfinite(tmp)
        ziel_arr[m] = tmp[m]
    gut = int(np.isfinite(ziel_arr).sum())
    if gut == 0:
        return 0
    ziel_arr[~np.isfinite(ziel_arr)] = -9999.0
    tmpd = ziel + ".teil"
    with rasterio.open(tmpd, "w", driver="GTiff", height=h, width=w, count=1, dtype="float32", crs="EPSG:%d" % ziel_epsg,
                       transform=tf, nodata=-9999.0, compress="deflate") as dst:
        dst.write(ziel_arr, 1)
    os.replace(tmpd, ziel)
    return gut


# ----------------------------------------------------------------------------------------------
# Schweiz: STAC
# ----------------------------------------------------------------------------------------------

def stac_kacheln(teil, bbox_ll, ctx, log):
    """STAC-Rechteckabfrage -> {kachel_id: (jahr, url)} mit der neuesten Ausgabe je Kachel."""
    url = "%s/collections/%s/items?%s" % (teil["stac"].rstrip("/"), teil["sammlung"],
                                          urllib.parse.urlencode({"bbox": "%.6f,%.6f,%.6f,%.6f" % bbox_ll, "limit": 100}))
    beste = {}
    seiten = 0
    while url and seiten < 50:
        seiten += 1
        j = _json(url, ctx)
        for f in j.get("features") or []:
            fid = str(f.get("id", ""))
            m = re.search(r"_(\d{4})(?:-\d\d)?_(\d+-\d+)$", fid)
            if not m:
                continue
            jahr, kid = int(m.group(1)), m.group(2)
            assets = [a.get("href", "") for a in (f.get("assets") or {}).values()]
            href = next((a for a in assets if re.search(teil["asset"], a)), None) \
                or next((a for a in assets if teil.get("ersatz") and re.search(teil["ersatz"], a)), None)
            if href and (kid not in beste or jahr > beste[kid][0]):
                beste[kid] = (jahr, href)
        url = next((l.get("href") for l in (j.get("links") or []) if l.get("rel") == "next"), None)
    log("  STAC %s: %d Kachel(n) im Gebiet (%s)" % (teil["sammlung"], len(beste),
                                                   ", ".join("%s/%d" % (k, v[0]) for k, v in sorted(beste.items())[:8])))
    return beste


def _stac_dgm(land, teil, kach, epsg, ctx, cache, log, K, fehlt):
    fertig = [_dgm_name(cache, land, epsg, e, n) for e, n in kach]
    if all(os.path.exists(p) and os.path.getsize(p) > 0 for p in fertig):     # alles schon umgerechnet: keine Abfrage noetig
        log("  (aus Zwischenspeicher) %d umgerechnete Kachel(n)" % len(fertig))
        return fertig
    t_ll = _trafo(epsg, 4326)
    xs = [e for e, n in kach] + [e + 1000 for e, n in kach]
    ys = [n for e, n in kach] + [n + 1000 for e, n in kach]
    bb_ll = _huelle(t_ll, min(xs) - 20, min(ys) - 20, max(xs) + 20, max(ys) + 20)
    try:
        beste = stac_kacheln(teil, bb_ll, ctx, log)
    except Exception as ex:
        log("  STAC-Abfrage fehlgeschlagen: %s" % str(ex)[:200])
        fehlt.append("Schweiz Gelaende: STAC-Schnittstelle nicht erreichbar (%s)" % str(ex)[:120])
        return []
    if not beste:
        log("  Keine swissALTI3D-Kachel im Gebiet - liegt der Ort wirklich in der Schweiz?")
        fehlt.append("Schweiz Gelaende: keine Kachel beim Dienst (Ort ausserhalb der Schweiz?)")
        return []
    quell = {}
    for kid, (jahr, href) in beste.items():
        ziel = os.path.join(cache, os.path.basename(urllib.parse.urlparse(href).path))
        try:
            if K._datei_laden(href, ziel, ctx, log):
                quell[kid] = ziel
            else:
                fehlt.append("Schweiz Gelaende: %s nicht vorhanden (404)" % href)
        except Exception as ex:
            log("  FEHLER beim Laden von %s: %s" % (href, str(ex)[:150]))
            fehlt.append("Schweiz Gelaende: %s (%s)" % (os.path.basename(href), str(ex)[:100]))
    t_ch = _trafo(epsg, int(teil.get("daten_epsg", 2056)))
    out = []
    for e, n in kach:
        ziel = _dgm_name(cache, land, epsg, e, n)
        if os.path.exists(ziel) and os.path.getsize(ziel) > 0:
            log("  (aus Zwischenspeicher) %s" % os.path.basename(ziel))
            out.append(ziel)
            continue
        x0, y0, x1, y1 = _huelle(t_ch, e - 5, n - 5, e + 1005, n + 1005)
        noetig = [p for kid, p in quell.items()
                  if _kid_beruehrt(kid, x0, y0, x1, y1)]
        if not noetig:
            continue
        try:
            gut = nach_utm(noetig, ziel, epsg, e, n)
            if gut:
                log("  umgerechnet nach UTM: %s (%d Zellen aus %d swissALTI3D-Kachel(n))" % (os.path.basename(ziel), gut, len(noetig)))
                out.append(ziel)
        except Exception as ex:
            log("  Umrechnen nach UTM fehlgeschlagen (%s): %s" % (os.path.basename(ziel), str(ex)[:200]))
            fehlt.append("Schweiz Gelaende: Kachel %d/%d nicht umrechenbar (%s)" % (e // 1000, n // 1000, str(ex)[:100]))
    return out


def _kid_beruehrt(kid, x0, y0, x1, y1):
    """swissALTI3D-Kachelname '2600-1199' (km Ost - km Nord in LV95) beruehrt das Rechteck?"""
    try:
        ek, nk = (int(v) for v in kid.split("-"))
    except ValueError:
        return True
    e, n = ek * 1000, nk * 1000
    return not (e + 1000 < x0 or e > x1 or n + 1000 < y0 or n > y1)


# ----------------------------------------------------------------------------------------------
# Niederlande: WCS (Ersatz: Kartenblatt)
# ----------------------------------------------------------------------------------------------

def wcs_url(teil, x0, y0, x1, y1, achsen=("x", "y")):
    q = [("SERVICE", "WCS"), ("VERSION", "2.0.1"), ("REQUEST", "GetCoverage"), ("COVERAGEID", teil["coverage"]),
         ("FORMAT", "image/tiff"), ("SUBSET", "%s(%.2f,%.2f)" % (achsen[0], x0, x1)), ("SUBSET", "%s(%.2f,%.2f)" % (achsen[1], y0, y1))]
    return teil["basis"] + ("&" if "?" in teil["basis"] else "?") + urllib.parse.urlencode(q, safe="(),")


def _ist_tiff(pfad):
    try:
        with open(pfad, "rb") as f:
            return f.read(4) in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")
    except OSError:
        return False


def _wcs_dgm(land, teil, kach, epsg, ctx, cache, log, K, fehlt):
    t_nl = _trafo(epsg, int(teil.get("daten_epsg", 28992)))
    out, achsen, wcs_tot = [], None, False
    for e, n in kach:
        ziel = _dgm_name(cache, land, epsg, e, n)
        if os.path.exists(ziel) and os.path.getsize(ziel) > 0:
            log("  (aus Zwischenspeicher) %s" % os.path.basename(ziel))
            out.append(ziel)
            continue
        x0, y0, x1, y1 = _huelle(t_nl, e - 5, n - 5, e + 1005, n + 1005)
        roh = os.path.join(cache, "%s_wcs_%s_%d_%d_%d_%d.tif" % (land, teil["coverage"], x0, y0, x1, y1))
        ok = os.path.exists(roh) and _ist_tiff(roh)
        if not ok and not wcs_tot:
            for ax in ([achsen] if achsen else [("x", "y"), ("X", "Y"), ("E", "N")]):
                url = wcs_url(teil, x0, y0, x1, y1, ax)
                try:
                    t0 = time.time()
                    with _oeffnen(url, ctx, 300) as r, open(roh + ".teil", "wb") as f:
                        while True:
                            b = r.read(1 << 20)
                            if not b:
                                break
                            f.write(b)
                    if _ist_tiff(roh + ".teil"):
                        os.replace(roh + ".teil", roh)
                        achsen, ok = ax, True
                        log("  WCS %s: Ausschnitt %d/%d geladen (%.1f MB, %.0f s)"
                            % (teil["coverage"], e // 1000, n // 1000, os.path.getsize(roh) / 1e6, time.time() - t0))
                        break
                    with open(roh + ".teil", "rb") as f:
                        txt = f.read(600).decode("utf-8", errors="replace")
                    os.remove(roh + ".teil")
                    log("  WCS antwortet ohne Rasterbild (Achsen %s/%s): %s" % (ax[0], ax[1], re.sub(r"\s+", " ", txt)[:200]))
                except Exception as ex:
                    if os.path.exists(roh + ".teil"):
                        os.remove(roh + ".teil")
                    log("  WCS-Abfrage fehlgeschlagen (Achsen %s/%s): %s" % (ax[0], ax[1], str(ex)[:150]))
            if not ok:
                wcs_tot = True
                log("  WCS liefert nichts - Ersatz: ganze AHN-Kartenblaetter laden (gross, bis ~500 MB je Blatt)")
        quellen = [roh] if ok else _blaetter(teil, (x0, y0, x1, y1), ctx, cache, log, K, fehlt)
        if not quellen:
            continue
        try:
            gut = nach_utm(quellen, ziel, epsg, e, n)
            if gut:
                log("  umgerechnet nach UTM: %s (%d Zellen)" % (os.path.basename(ziel), gut))
                out.append(ziel)
            else:
                log("  Kachel %d/%d: keine Hoehenwerte (Meer, oder Ort ausserhalb der Niederlande?)" % (e // 1000, n // 1000))
        except Exception as ex:
            log("  Umrechnen nach UTM fehlgeschlagen (%s): %s" % (os.path.basename(ziel), str(ex)[:200]))
            fehlt.append("Niederlande Gelaende: Kachel %d/%d nicht umrechenbar (%s)" % (e // 1000, n // 1000, str(ex)[:100]))
    return out


_INDEX = {}


def _blaetter(teil, bb, ctx, cache, log, K, fehlt):
    """Ersatzweg: AHN-Kartenblaetter aus dem Blattindex, die das Rechteck bb (RD) beruehren, ganz laden."""
    from shapely.geometry import box, shape
    url = teil.get("index")
    if not url:
        return []
    if url not in _INDEX:
        ziel = os.path.join(cache, "index_%s.json" % hashlib.sha1(url.encode()).hexdigest()[:12])
        try:
            if not (os.path.exists(ziel) and time.time() - os.path.getmtime(ziel) < 30 * 86400):
                K._datei_laden(url, ziel, ctx, log)
            with open(ziel, "r", encoding="utf-8") as f:
                _INDEX[url] = json.load(f).get("features") or []
        except Exception as ex:
            log("  Blattindex nicht lesbar: %s" % str(ex)[:150])
            _INDEX[url] = []
    r = box(*bb)
    out = []
    for f in _INDEX[url]:
        try:
            if not shape(f["geometry"]).intersects(r):
                continue
        except Exception:
            continue
        p = f.get("properties") or {}
        href = p.get("url")
        if not href:
            continue
        ziel = os.path.join(cache, "ahn_%s" % os.path.basename(urllib.parse.urlparse(href).path))
        log("  Kartenblatt %s (%.0f MB)" % (p.get("kaartbladNr", "?"), float(p.get("length") or 0) / 1e6))
        try:
            if K._datei_laden(href, ziel, ctx, log):
                out.append(ziel)
        except Exception as ex:
            fehlt.append("Niederlande Gelaende: Blatt %s (%s)" % (p.get("kaartbladNr", "?"), str(ex)[:100]))
    return out


# ----------------------------------------------------------------------------------------------
# Niederlande: 3DBAG (CityJSON -> CityGML)
# ----------------------------------------------------------------------------------------------

LOD_RANG = ["2.2", "2", "1.3", "1.2", "1"]
TYP = {"WallSurface": "WallSurface", "RoofSurface": "RoofSurface", "GroundSurface": "GroundSurface",
       "ClosureSurface": "ClosureSurface", "OuterCeilingSurface": "RoofSurface", "OuterFloorSurface": "GroundSurface"}


def bag_seiten(teil, bb_rd, ctx, log, max_seiten=200):
    """3DBAG-API: alle Gebaeude im Rechteck bb_rd (RD) -> (Liste CityJSONFeature, transform)."""
    url = "%s/collections/%s/items?%s" % (teil["basis"].rstrip("/"), teil["sammlung"],
                                          urllib.parse.urlencode({"bbox": "%.2f,%.2f,%.2f,%.2f" % bb_rd, "limit": 100}))
    feats, transform, seiten = [], None, 0
    while url and seiten < max_seiten:
        seiten += 1
        j = _json(url, ctx, 180)
        transform = transform or (j.get("metadata") or {}).get("transform")
        feats += j.get("features") or []
        url = next((l.get("href") for l in (j.get("links") or []) if l.get("rel") == "next"), None)
    if url:
        log("  3DBAG: nach %d Seiten abgebrochen - Gebiet sehr dicht, Rest kommt aus OpenStreetMap" % seiten)
    return feats, transform


def _verts(feat, transform):
    v = np.asarray(feat.get("vertices") or [], dtype=float).reshape(-1, 3)
    tr = feat.get("transform") or transform
    if tr and len(v):
        v = v * np.asarray(tr.get("scale", [1, 1, 1]), dtype=float) + np.asarray(tr.get("translate", [0, 0, 0]), dtype=float)
    return v


def _beste_geometrie(obj):
    geoms = [g for g in (obj.get("geometry") or []) if g.get("type") in ("Solid", "MultiSurface", "CompositeSurface")]
    for lod in LOD_RANG:
        for g in geoms:
            if str(g.get("lod")) == lod:
                return g
    return None


def _flaechen(g):
    """Geometrie -> Liste (Typ, [Ring(Indizes), ...])."""
    sem = g.get("semantics") or {}
    surf = sem.get("surfaces") or []
    werte = sem.get("values")
    out = []
    if g["type"] == "Solid":
        for si, schale in enumerate(g.get("boundaries") or []):
            for fi, fl in enumerate(schale):
                k = None
                try:
                    k = werte[si][fi]
                except (TypeError, IndexError):
                    pass
                out.append((TYP.get(surf[k]["type"]) if k is not None and k < len(surf) else None, fl))
    else:
        for fi, fl in enumerate(g.get("boundaries") or []):
            k = None
            try:
                k = werte[fi]
            except (TypeError, IndexError):
                pass
            out.append((TYP.get(surf[k]["type"]) if k is not None and k < len(surf) else None, fl))
    return out


def _typ_nach_neigung(pts):
    nv = np.zeros(3)
    for i in range(len(pts)):
        nv += np.cross(pts[i], pts[(i + 1) % len(pts)])
    L = np.linalg.norm(nv)
    if L < 1e-9:
        return None
    nz = nv[2] / L
    if abs(nz) < 0.1:
        return "WallSurface"
    return "GroundSurface" if nz < -0.9 else "RoofSurface"


def _pos(pts):
    p = np.vstack([pts, pts[:1]])
    return " ".join("%.3f %.3f %.3f" % (x, y, z) for x, y, z in p)


def citygml_aus_3dbag(feats, transform, t_utm, kachel=None):
    """CityJSONFeatures (RD + NAP) -> CityGML-2.0-Text im UTM-System. kachel = (e, n, g): nur Gebaeude mit Mitte darin.
    -> (text, anzahl)"""
    teile_xml, anzahl = [], 0
    for feat in feats:
        V = _verts(feat, transform)
        if not len(V):
            continue
        X, Y = t_utm.transform(V[:, 0], V[:, 1])
        U = np.column_stack([np.asarray(X), np.asarray(Y), V[:, 2]])
        objs = feat.get("CityObjects") or {}
        hauptid = feat.get("id") or next(iter(objs), "x")
        teile = []
        for oid, obj in objs.items():
            if obj.get("type") not in ("Building", "BuildingPart"):
                continue
            g = _beste_geometrie(obj)
            if g is None or str(g.get("lod")).startswith("0"):
                continue
            fl = {"WallSurface": [], "RoofSurface": [], "GroundSurface": [], "ClosureSurface": []}
            for typ, ringe in _flaechen(g):
                if not ringe or len(ringe[0]) < 3:
                    continue
                aussen = U[np.asarray(ringe[0], dtype=int)]
                typ = typ or _typ_nach_neigung(aussen)
                if typ not in fl:
                    continue
                innen = [U[np.asarray(r, dtype=int)] for r in ringe[1:] if len(r) >= 3]
                fl[typ].append((aussen, innen))
            if any(fl.values()):
                teile.append((oid, fl))
        if not teile:
            continue
        alle = np.vstack([e for _, fl in teile for v in fl.values() for e, h in v])
        cx, cy = float(alle[:, 0].mean()), float(alle[:, 1].mean())
        if kachel is not None:
            e0, n0, gk = kachel
            if not (e0 <= cx < e0 + gk and n0 <= cy < n0 + gk):
                continue
        xml = ['<core:cityObjectMember><bldg:Building gml:id="%s">' % _id(hauptid)]
        for oid, fl in teile:
            if len(teile) > 1:
                xml.append('<bldg:consistsOfBuildingPart><bldg:BuildingPart gml:id="%s">' % _id(oid))
            for typ, liste in fl.items():
                for i, (e, innen) in enumerate(liste):
                    xml.append('<bldg:boundedBy><bldg:%s><bldg:lod2MultiSurface><gml:MultiSurface><gml:surfaceMember><gml:Polygon>'
                               '<gml:exterior><gml:LinearRing><gml:posList srsDimension="3">%s</gml:posList></gml:LinearRing></gml:exterior>%s'
                               '</gml:Polygon></gml:surfaceMember></gml:MultiSurface></bldg:lod2MultiSurface></bldg:%s></bldg:boundedBy>'
                               % (typ, _pos(e), "".join('<gml:interior><gml:LinearRing><gml:posList srsDimension="3">%s</gml:posList>'
                                                         '</gml:LinearRing></gml:interior>' % _pos(h) for h in innen), typ))
            if len(teile) > 1:
                xml.append('</bldg:BuildingPart></bldg:consistsOfBuildingPart>')
        xml.append('</bldg:Building></core:cityObjectMember>')
        teile_xml.append("".join(xml))
        anzahl += 1
    kopf = ('<?xml version="1.0" encoding="UTF-8"?>\n<core:CityModel xmlns:core="http://www.opengis.net/citygml/2.0" '
            'xmlns:bldg="http://www.opengis.net/citygml/building/2.0" xmlns:gml="http://www.opengis.net/gml">\n'
            '<!-- Quelle: 3DBAG (tudelft3d / 3DGI), CC BY 4.0 - umgerechnet von RD New nach UTM durch Zacharias Tools; Hoehen NAP -->\n')
    return kopf + "\n".join(teile_xml) + "\n</core:CityModel>\n", anzahl


def _id(s):
    s = re.sub(r"[^A-Za-z0-9_.-]", "_", str(s))
    return s if re.match(r"[A-Za-z_]", s) else "id_" + s


def _bag_lod2(land, teil, kach, epsg, ctx, cache, log, fehlt):
    t_rd = _trafo(epsg, int(teil.get("daten_epsg", 28992)))
    t_utm = _trafo(int(teil.get("daten_epsg", 28992)), epsg)
    out = []
    for e, n in kach:
        ziel = _lod_name(cache, land, epsg, e, n)
        if os.path.exists(ziel) and os.path.getsize(ziel) > 0 and time.time() - os.path.getmtime(ziel) < 90 * 86400:
            log("  (aus Zwischenspeicher) %s" % os.path.basename(ziel))
            out.append(ziel)
            continue
        bb = _huelle(t_rd, e - 60, n - 60, e + 1060, n + 1060)       # etwas groesser: Gebaeude ueber die Kachelgrenze
        t0 = time.time()
        try:
            feats, tr = bag_seiten(teil, bb, ctx, log)
        except Exception as ex:
            log("  3DBAG-Abfrage fehlgeschlagen (Kachel %d/%d): %s" % (e // 1000, n // 1000, str(ex)[:200]))
            fehlt.append("Niederlande Gebaeude: 3DBAG nicht erreichbar (%s)" % str(ex)[:100])
            continue
        text, anz = citygml_aus_3dbag(feats, tr, t_utm, (e, n, 1000))
        with open(ziel + ".teil", "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(ziel + ".teil", ziel)
        log("  3DBAG Kachel %d/%d: %d Gebaeude (%.0f s) -> %s" % (e // 1000, n // 1000, anz, time.time() - t0, os.path.basename(ziel)))
        out.append(ziel)
    return out


# ----------------------------------------------------------------------------------------------
# Einstieg aus ifcmap_laender.kacheln_holen
# ----------------------------------------------------------------------------------------------

def teil_holen(land, prof, art, teil, kach, epsg, ctx, cache, log, K, fehlt):
    """Ein Teil (dgm/lod2) mit einer der eigenen Arten -> Liste Dateien (GeoTIFF bzw. CityGML im UTM-System epsg)."""
    a = teil.get("art")
    if a == "stac" and art in ("dgm", "dom"):
        return _stac_dgm(land, teil, kach, epsg, ctx, cache, log, K, fehlt)
    if a == "wcs" and art in ("dgm", "dom"):
        return _wcs_dgm(land, teil, kach, epsg, ctx, cache, log, K, fehlt)
    if a == "3dbag" and art == "lod2":
        return _bag_lod2(land, teil, kach, epsg, ctx, cache, log, fehlt)
    log("  Art '%s' passt nicht zu %s - uebersprungen" % (a, art))
    return []
