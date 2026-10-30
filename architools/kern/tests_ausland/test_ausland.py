# -*- coding: utf-8 -*-
"""Tests fuer ifcmap_ausland (Schweiz, Niederlande, UTM-Zone) mit nachgebauten Diensten - ohne Netz.
Aufruf: python architools/kern/tests_ausland/test_ausland.py"""
import io
import json
import os
import shutil
import sys
import tempfile
from dataclasses import replace

import numpy as np

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))
import ifcmap_kern as K          # noqa: E402
import ifcmap_laender as L       # noqa: E402
import ifcmap_ausland as A       # noqa: E402
import rasterio                  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402
from pyproj import Transformer   # noqa: E402

FEHLER = []
LOG = []


def log(s):
    LOG.append(str(s))


def pruef(bed, text):
    print(("ok    " if bed else "FEHLER ") + text)
    if not bed:
        FEHLER.append(text)


def ebene(e, n):                   # Testgelaende: schiefe Ebene + Welle (im Landes-KBS)
    return 400.0 + 0.01 * (e % 100000) - 0.004 * (n % 100000) + 2.0 * np.sin(e / 50.0)


def tif_schreiben(pfad, epsg, x0, y1, res, w, h, nodata=None):
    xs = x0 + (np.arange(w) + 0.5) * res
    ys = y1 - (np.arange(h) + 0.5) * res
    X, Y = np.meshgrid(xs, ys)
    z = ebene(X, Y).astype("float32")
    if nodata is not None:
        z[:5, :5] = nodata
    with rasterio.open(pfad, "w", driver="GTiff", height=h, width=w, count=1, dtype="float32", crs="EPSG:%d" % epsg,
                       transform=from_origin(x0, y1, res, res), nodata=nodata) as d:
        d.write(z, 1)


def ergebnis_pruefen(pfad, utm, land_epsg, name):
    with rasterio.open(pfad) as r:
        a = r.read(1)
        T = r.transform
        pruef(r.crs.to_epsg() == utm, "%s: GeoTIFF im UTM-System EPSG:%d" % (name, utm))
    ok = a != -9999
    rr, cc = np.nonzero(ok)
    sel = np.random.default_rng(1).choice(len(rr), min(4000, len(rr)), replace=False)
    x = T.c + (cc[sel] + 0.5) * T.a
    y = T.f + (rr[sel] + 0.5) * T.e
    ex, ny = Transformer.from_crs("EPSG:%d" % utm, "EPSG:%d" % land_epsg, always_xy=True).transform(x, y)
    soll = ebene(np.asarray(ex), np.asarray(ny))
    d = np.abs(a[rr[sel], cc[sel]] - soll)
    pruef(np.percentile(d, 99) < 0.05, "%s: Hoehen nach dem Umrechnen stimmen (99 %% < 5 cm, max %.3f m)" % (name, d.max()))
    pruef(ok.mean() > 0.99, "%s: Kachel voll abgedeckt (%.1f %%)" % (name, 100 * ok.mean()))


def main():
    tmp = tempfile.mkdtemp(prefix="ausland_")
    cache = os.path.join(tmp, "cache")
    os.makedirs(cache)
    K.cache_ordner = lambda: cache
    quellen_dir = os.path.join(tmp, "dienst")
    os.makedirs(quellen_dir)

    # ---------------- UTM-Zone ----------------
    pruef(A.utm_epsg(2.35, 48.86) == 25831, "Paris -> UTM 31")
    pruef(A.utm_epsg(-9.14, 38.72) == 25829, "Lissabon -> UTM 29")
    pruef(A.utm_epsg(-74.0, 40.7) == 32618, "New York -> WGS84 UTM 18N")
    pruef(A.utm_epsg(151.2, -33.9) == 32756, "Sydney -> WGS84 UTM 56S")
    cfg = K.Config(latlon=(48.8566, 2.3522), epsg=25833)
    c2, land = L.vorbereiten(cfg, K, log)
    pruef(land is None and c2.epsg == 25831, "Paris (Vorgabe UTM 33): ohne Land, KBS auf EPSG:25831 umgestellt")
    ce, cn = K.mitte_bestimmen(c2)
    lo, la = Transformer.from_crs("EPSG:25831", "EPSG:4326", always_xy=True).transform(ce, cn)
    pruef(abs(lo - 2.3522) < 1e-6 and abs(la - 48.8566) < 1e-6, "Paris: Mittelpunkt bleibt derselbe Ort")
    c3, _ = L.vorbereiten(K.Config(mitte_en=(393676.3, 5826540.3), epsg=25833), K, log)
    pruef(c3.epsg == 25833 and c3.mitte_en == (393676.3, 5826540.3), "Pankow: unveraendert UTM 33")
    c4, _ = L.vorbereiten(K.Config(latlon=(48.8566, 2.3522), epsg=25833, land="keins"), K, log)
    pruef(c4.epsg == 25833, "'Nur eigene Dateien': KBS bleibt wie eingestellt")
    c5, land5 = L.vorbereiten(K.Config(latlon=(47.37, 8.54), epsg=25833), K, log)
    pruef(land5 == "schweiz" and c5.epsg == 25832, "Zuerich: Schweiz, UTM 32")
    c6, land6 = L.vorbereiten(K.Config(latlon=(52.22, 6.89), epsg=25833), K, log)
    pruef(land6 == "niederlande" and c6.epsg == 25832, "Enschede: Niederlande, UTM 32 (Osten des Landes)")

    # ---------------- Schweiz: STAC + Umrechnen ----------------
    cfg = replace(c5, breite=900, hoehe=900, nah_breite=600, nah_hoehe=600)
    ce, cn, x0, x1, y0, y1 = K.rechteck(cfg)
    bb_lv = A._huelle(A._trafo(25832, 2056), x0 - 1000, y0 - 1000, x1 + 1000, y1 + 1000)
    feats = []
    for ek in range(int(bb_lv[0] // 1000), int(bb_lv[2] // 1000) + 1):
        for nk in range(int(bb_lv[1] // 1000), int(bb_lv[3] // 1000) + 1):
            for jahr in (2019, 2025):
                fid = "swissalti3d_%d_%d-%d" % (jahr, ek, nk)
                href = "https://data.geo.admin.ch/ch.swisstopo.swissalti3d/%s/%s_0.5_2056_5728.tif" % (fid, fid)
                feats.append({"id": fid, "assets": {"a": {"href": href}, "b": {"href": href.replace("_0.5_", "_2_")}}})
                if jahr == 2025:
                    tif_schreiben(os.path.join(quellen_dir, os.path.basename(href)), 2056, ek * 1000, nk * 1000 + 1000, 2.0, 500, 500,
                                  nodata=-9999.0)
    seiten = [feats[:7], feats[7:]]

    def json_mock(url, ctx, timeout=120):
        if "swissalti3d" in url:
            i = 1 if "seite2" in url else 0
            return {"features": seiten[i], "links": ([{"rel": "next", "href": url + "&seite2=1"}] if i == 0 else [])}
        raise AssertionError(url)

    geladen = []

    def laden_mock(url, ziel, ctx, log):
        q = os.path.join(quellen_dir, os.path.basename(url.split("?")[0]))
        geladen.append(url)
        if not os.path.exists(q):
            return False
        shutil.copy(q, ziel)
        return True

    A._json = json_mock
    K._datei_laden = laden_mock
    d = type("D", (), {})()
    d.bbox = (x0, y0, x1, y1)
    dn, ln, fehlt = L.kacheln_holen(cfg, "schweiz", d.bbox, log, K, dgm=True, lod2=True)
    pruef(len(dn) >= 1 and all(os.path.basename(p).startswith("schweiz_dgm_utm32_") for p in dn),
          "Schweiz: %d UTM-Kachel(n) erzeugt" % len(dn))
    pruef(all("_2025_" in u for u in geladen) and all("_0.5_" in u for u in geladen), "Schweiz: nur neueste Ausgabe (2025), 0,5 m")
    pruef(ln == [] and any("OpenStreetMap" in z for z in LOG), "Schweiz: keine LoD2-Dateien, Hinweis auf OpenStreetMap")
    for p in dn:
        ergebnis_pruefen(p, 25832, 2056, "Schweiz " + os.path.basename(p))
    pruef(all(K.kachel_im_rechteck(os.path.basename(p), d.bbox) is not False for p in dn), "Schweiz: Kern erkennt die Kacheln am Namen")
    roh = sum(len(K.lade_xyz(p, (x0, x1, y0, y1))) for p in dn)
    pruef(roh > 0.95 * (x1 - x0) * (y1 - y0), "Schweiz: Kern liest das umgerechnete Gelaende (%d Punkte im 1-m-Raster)" % roh)
    pts = K.gelaende_ausduennen(dn, x0, x1, y0, y1, 0.15, log)
    pruef(pts is not None and len(pts[0]) > 100, "Schweiz: Kern duennt das Gelaende aus (%d Punkte)" % (len(pts[0]) if pts else 0))
    n_vorher = len(geladen)
    dn2, _, _ = L.kacheln_holen(cfg, "schweiz", d.bbox, log, K, dgm=True, lod2=False)
    pruef(len(geladen) == n_vorher and sorted(dn2) == sorted(dn), "Schweiz: zweiter Lauf aus dem Zwischenspeicher")

    # ---------------- Niederlande: WCS ----------------
    cfg = replace(K.Config(latlon=(52.3731, 4.8922), epsg=25833), breite=900, hoehe=900)
    cfg, land = L.vorbereiten(cfg, K, log)
    pruef(land == "niederlande" and cfg.epsg == 25831, "Amsterdam: Niederlande, UTM 31")
    ce, cn, x0, x1, y0, y1 = K.rechteck(cfg)
    anfragen = []

    class Antwort(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def oeffnen_mock(url, ctx, timeout=180):
        anfragen.append(url)
        import urllib.parse as up
        q = up.parse_qs(up.urlparse(url).query)
        subs = q["SUBSET"]
        if not subs[0].startswith("x("):
            return Antwort(b"<ows:ExceptionReport>falsche Achse</ows:ExceptionReport>")
        xa, xb = (float(v) for v in subs[0][2:-1].split(","))
        ya, yb = (float(v) for v in subs[1][2:-1].split(","))
        w, h = int(round((xb - xa) / 0.5)), int(round((yb - ya) / 0.5))
        f = os.path.join(tmp, "wcs_antwort.tif")
        tif_schreiben(f, 28992, xa, yb, 0.5, w, h)
        with open(f, "rb") as g:
            return Antwort(g.read())

    A._oeffnen = oeffnen_mock
    LOG.clear()
    dn, ln, fehlt = L.kacheln_holen(cfg, "niederlande", (x0, y0, x1, y1), log, K, dgm=True, lod2=False)
    pruef(len(dn) >= 1, "Niederlande: %d UTM-Kachel(n) aus dem WCS" % len(dn))
    for p in dn:
        ergebnis_pruefen(p, 25831, 28992, "Niederlande " + os.path.basename(p))

    # WCS mit anderer Achsbezeichnung: erst x/y, dann X/Y
    A._oeffnen = lambda url, ctx, timeout=180: (Antwort(b"<ExceptionReport/>") if "SUBSET=x(" in url else oeffnen_mock(url.replace("SUBSET=X(", "SUBSET=x(").replace("SUBSET=Y(", "SUBSET=y("), ctx))
    for f in os.listdir(cache):
        if f.startswith("niederlande_"):
            os.remove(os.path.join(cache, f))
    dn, _, _ = L.kacheln_holen(cfg, "niederlande", (x0, y0, x1, y1), log, K, dgm=True, lod2=False)
    pruef(len(dn) >= 1, "Niederlande: WCS antwortet erst mit der zweiten Achsbezeichnung (X/Y) - trotzdem geladen")

    # ---------------- Niederlande: 3DBAG ----------------
    t_rd = Transformer.from_crs("EPSG:25831", "EPSG:28992", always_xy=True)
    gebaeude = []
    rng = np.random.default_rng(3)
    for i in range(12):
        ux, uy = rng.uniform(x0 + 50, x1 - 50), rng.uniform(y0 + 50, y1 - 50)
        rx, ry = t_rd.transform(ux, uy)
        gebaeude.append((i, rx, ry, ux, uy))

    def haus(i, rx, ry):
        """Satteldachhaus 10 x 8 m, Traufe 6 m, First 9 m, Boden 0 m NAP (CityJSON mit transform)."""
        b, t, z0, ze, zf = 10.0, 8.0, 0.0, 6.0, 9.0
        P = [(rx - b / 2, ry - t / 2, z0), (rx + b / 2, ry - t / 2, z0), (rx + b / 2, ry + t / 2, z0), (rx - b / 2, ry + t / 2, z0),
             (rx - b / 2, ry - t / 2, ze), (rx + b / 2, ry - t / 2, ze), (rx + b / 2, ry + t / 2, ze), (rx - b / 2, ry + t / 2, ze),
             (rx - b / 2, ry, zf), (rx + b / 2, ry, zf)]
        tr = {"scale": [0.001, 0.001, 0.001], "translate": [100000.0, 400000.0, 0.0]}
        V = [[int(round((p[0] - 100000.0) / 0.001)), int(round((p[1] - 400000.0) / 0.001)), int(round(p[2] / 0.001))] for p in P]
        fl = [[[0, 3, 2, 1]], [[0, 1, 5, 4]], [[1, 2, 6, 9, 5]], [[2, 3, 7, 6]], [[3, 0, 4, 8, 7]], [[4, 5, 9, 8]], [[6, 7, 8, 9]]]
        werte = [0, 1, 1, 1, 1, 2, 2]
        sem = {"surfaces": [{"type": "GroundSurface"}, {"type": "WallSurface"}, {"type": "RoofSurface"}], "values": [werte]}
        oid = "NL.IMBAG.Pand.%016d" % i
        return {"type": "CityJSONFeature", "id": oid, "vertices": V, "CityObjects": {
            oid: {"type": "Building", "children": [oid + "-0"], "geometry": [{"type": "MultiSurface", "lod": "0", "boundaries": [[[0, 1, 2, 3]]]}]},
            oid + "-0": {"type": "BuildingPart", "parents": [oid], "geometry": [
                {"type": "Solid", "lod": "1.2", "boundaries": [[[[0, 3, 2, 1]]]]},
                {"type": "Solid", "lod": "2.2", "boundaries": [fl], "semantics": sem}]}}}, tr

    fe = [haus(i, rx, ry) for i, rx, ry, ux, uy in gebaeude]

    def bag_json(url, ctx, timeout=120):
        import urllib.parse as up
        q = up.parse_qs(up.urlparse(url).query)
        bx = [float(v) for v in q["bbox"][0].split(",")]
        off = int(q.get("offset", ["0"])[0])
        drin = [f for (f, tr), (i, rx, ry, ux, uy) in zip(fe, gebaeude) if bx[0] <= rx <= bx[2] and bx[1] <= ry <= bx[3]]
        seite = drin[off:off + 5]
        links = [{"rel": "next", "href": url.split("&offset")[0] + "&offset=%d" % (off + 5)}] if off + 5 < len(drin) else []
        return {"type": "FeatureCollection", "features": seite, "links": links, "metadata": {"transform": fe[0][1]}}

    A._json = bag_json
    LOG.clear()
    _, ln, fehlt = L.kacheln_holen(cfg, "niederlande", (x0, y0, x1, y1), log, K, dgm=False, lod2=True)
    pruef(len(ln) >= 1 and all(os.path.basename(p).startswith("niederlande_lod2_utm31_") for p in ln), "3DBAG: %d CityGML-Kachel(n)" % len(ln))
    teile = K.lod2_lesen(ln, x0, x1, y0, y1, log)
    pruef(len(teile) == len(gebaeude), "3DBAG: alle %d Gebaeude genau einmal gelesen (ohne Doppel an Kachelgrenzen): %d" % (len(gebaeude), len(teile)))
    if teile:
        t = teile[0]
        pruef(len(t["wall"]) == 4 and len(t["roof"]) == 2 and len(t["ground"]) == 1, "3DBAG: Waende/Dach/Boden richtig zugeordnet")
        zs = np.vstack([e for e, h in t["roof"]])[:, 2]
        pruef(abs(zs.max() - 9.0) < 0.01 and abs(zs.min() - 6.0) < 0.01, "3DBAG: First 9 m, Traufe 6 m")
        mitten = sorted((round(tt["c"][0], 0), round(tt["c"][1], 0)) for tt in teile)
        soll = sorted((round(ux, 0), round(uy, 0)) for i, rx, ry, ux, uy in gebaeude)
        abw = max(np.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(mitten, soll))
        pruef(abw <= 1.5, "3DBAG: Lage nach dem Umrechnen RD -> UTM stimmt (max %.2f m Rundung)" % abw)
        fl = sum(len(K.lod2_faces(tt)) for tt in teile)
        pruef(fl > 0, "3DBAG: Kern erzeugt Flaechen fuer die IFC (%d)" % fl)

    # ---------------- Copernicus im Modellbau (Ausland ohne Profil) ----------------
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HIER))))
    from architools.modell import ifcmap_adapter as AD
    K.copernicus_gelaende = lambda kc, dd, log: (np.array([dd.xmin, dd.xmax, dd.xmin, dd.xmax]),
                                                 np.array([dd.ymin, dd.ymin, dd.ymax, dd.ymax]), np.array([1.0, 2.0, 3.0, 4.0]))
    r = AD._copernicus_notfall(K, K.Config(), 0, 10, 0, 10, log)
    pruef(len(r) == 1 and r[0].shape == (4, 3), "Modellbau: Copernicus-Notbehelf liefert Gelaendepunkte")

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("%d Fehler" % len(FEHLER) if FEHLER else "Alle Pruefungen bestanden.")
    if FEHLER:
        print("\n".join(LOG[-40:]))
    return 1 if FEHLER else 0


if __name__ == "__main__":
    sys.exit(main())
