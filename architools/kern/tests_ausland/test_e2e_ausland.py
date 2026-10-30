# -*- coding: utf-8 -*-
"""Gesamtlauf Amsterdam (Niederlande) und Paris (ohne Profil) mit nachgebauten Diensten: IFC + Lageplan + Lasercut-Modell.
Aufruf aus dem Repo-Ordner: python architools/kern/tests_ausland/test_e2e_ausland.py"""
import io
import os
import sys
import tempfile
import urllib.parse as up

import numpy as np

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from architools import projekt as P, laufen as LF          # noqa: E402
K = P.kern()
import ifcmap_ausland as A                                  # noqa: E402
import test_ausland as T                                    # noqa: E402
from pyproj import Transformer                              # noqa: E402

FEHLER = []


def pruef(b, t):
    print(("ok    " if b else "FEHLER ") + t, flush=True)
    if not b:
        FEHLER.append(t)


class Antwort(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def main():
    tmp = tempfile.mkdtemp(prefix="e2e_ausland_")
    cache = os.path.join(tmp, "cache")
    os.makedirs(cache)
    K.cache_ordner = lambda: cache
    K.OVERPASS = ["https://127.0.0.1:9/api/interpreter"]       # kein Netz: OSM faellt sofort aus
    K.wfs_laden = lambda *a, **k: None
    K.wfs_typnamen = lambda b, c: []

    def wcs(url, ctx, timeout=180):
        q = up.parse_qs(up.urlparse(url).query)
        xa, xb = (float(v) for v in q["SUBSET"][0][2:-1].split(","))
        ya, yb = (float(v) for v in q["SUBSET"][1][2:-1].split(","))
        f = os.path.join(tmp, "w.tif")
        T.tif_schreiben(f, 28992, xa, yb, 0.5, int(round((xb - xa) / 0.5)), int(round((yb - ya) / 0.5)))
        return Antwort(open(f, "rb").read())
    A._oeffnen = wcs

    t_rd = Transformer.from_crs("EPSG:4326", "EPSG:28992", always_xy=True)
    rx, ry = t_rd.transform(4.8922, 52.3731)
    haus, tr = None, None

    def bag(url, ctx, timeout=120):
        q = up.parse_qs(up.urlparse(url).query)
        bx = [float(v) for v in q["bbox"][0].split(",")]
        fe = []
        for i, (dx, dy) in enumerate([(0, 0), (40, 25), (-60, 30), (90, -70)]):
            if bx[0] <= rx + dx <= bx[2] and bx[1] <= ry + dy <= bx[3]:
                f, t = T_haus(i, rx + dx, ry + dy)
                fe.append(f)
        return {"features": fe, "links": [], "metadata": {"transform": {"scale": [0.001] * 3, "translate": [100000.0, 400000.0, 0.0]}}}
    A._json = bag

    # Haus-Generator aus test_ausland (dort lokal definiert) - hier nachgebaut
    def T_haus(i, x, y):
        b, t, ze, zf = 12.0, 9.0, 7.0, 11.0
        Pp = [(x - b / 2, y - t / 2, 0), (x + b / 2, y - t / 2, 0), (x + b / 2, y + t / 2, 0), (x - b / 2, y + t / 2, 0),
              (x - b / 2, y - t / 2, ze), (x + b / 2, y - t / 2, ze), (x + b / 2, y + t / 2, ze), (x - b / 2, y + t / 2, ze),
              (x - b / 2, y, zf), (x + b / 2, y, zf)]
        V = [[int(round((p[0] - 100000.0) / 0.001)), int(round((p[1] - 400000.0) / 0.001)), int(round(p[2] / 0.001))] for p in Pp]
        fl = [[[0, 3, 2, 1]], [[0, 1, 5, 4]], [[1, 2, 6, 9, 5]], [[2, 3, 7, 6]], [[3, 0, 4, 8, 7]], [[4, 5, 9, 8]], [[6, 7, 8, 9]]]
        sem = {"surfaces": [{"type": "GroundSurface"}, {"type": "WallSurface"}, {"type": "RoofSurface"}], "values": [[0, 1, 1, 1, 1, 2, 2]]}
        oid = "NL.IMBAG.Pand.%016d" % i
        return {"type": "CityJSONFeature", "id": oid, "vertices": V, "CityObjects": {
            oid: {"type": "Building", "children": [oid + "-0"], "geometry": []},
            oid + "-0": {"type": "BuildingPart", "parents": [oid], "geometry": [{"type": "Solid", "lod": "2.2", "boundaries": [fl],
                                                                                  "semantics": sem}]}}}, None

    t33 = Transformer.from_crs("EPSG:4326", "EPSG:25833", always_xy=True)
    p = P.neues_projekt("Amsterdam", os.path.join(tmp, "ams"))
    p["gebiet"]["mitte_en"] = list(t33.transform(4.8922, 52.3731))        # so speicherte die Oberflaeche bisher (UTM 33)
    p["umgebung"].update(breite=300.0, hoehe=300.0, nah_breite=200.0, nah_hoehe=200.0, buergersteige="keine", lod2_luecken=True)
    p["gebiet"].update(breite_cm=30.0, hoehe_cm=30.0)
    p["modell"]["massstab"] = 1000
    p["ausgaben"].update(ifc=True, lageplan=True, laser=True)
    zeilen = []
    erg = LF.alles(p, ["ifc", "lageplan", "laser"], lambda s: zeilen.append(str(s)), lambda *a, **k: None)
    pruef(p["umgebung"]["epsg"] == 25831, "Amsterdam: Projekt auf UTM 31 umgestellt")
    pruef(any("Niederlande" in z for z in zeilen), "Amsterdam: Land Niederlande erkannt")
    ifcs = [os.path.join(r, f) for r, _, fs in os.walk(os.path.join(tmp, "ams")) for f in fs if f.endswith(".ifc")]
    pruef(len(ifcs) >= 1, "Amsterdam: IFC geschrieben")
    if ifcs:
        import ifcopenshell
        m = ifcopenshell.open(ifcs[0])
        geb = [e for e in m.by_type("IfcBuildingElementProxy") + m.by_type("IfcBuilding") if "Pand" in (e.Name or "") or "LoD2" in str(e.Name)]
        mc = m.by_type("IfcMapConversion")
        crs = m.by_type("IfcProjectedCRS")
        pruef(bool(crs) and "25831" in (crs[0].Name or ""), "Amsterdam: IFC-Georeferenz EPSG:25831 (%s)" % (crs[0].Name if crs else "-"))
        pruef(len(m.by_type("IfcGeographicElement")) + len(m.by_type("IfcSite")) > 0, "Amsterdam: Gelaende in der IFC")
        alle = len(m.by_type("IfcBuildingElementProxy"))
        pruef(alle >= 4, "Amsterdam: Gebaeude aus 3DBAG in der IFC (%d Elemente)" % alle)
    pruef(not (erg.get("modell") or {}).get("fehler"), "Amsterdam: Lasercut-Modell ohne Fehler (%s)" % (erg.get("modell") or {}).get("fehler"))
    hl = [z for z in zeilen if "DGM:" in z and "Zellen" in z]
    pruef(bool(hl), "Amsterdam: Modellbau hat das umgerechnete AHN-Gelaende (%s)" % (hl[0].strip() if hl else "-"))

    # Paris: kein Profil -> UTM 31 + Copernicus im Modellbau (Kachel nachgebaut)
    K.copernicus_gelaende = lambda kc, dd, log: tuple(np.ravel(a) for a in (
        *np.meshgrid(np.linspace(dd.xmin, dd.xmax, 12), np.linspace(dd.ymin, dd.ymax, 12)),
        np.full(144, 35.0) + np.linspace(0, 5, 144)))
    p2 = P.neues_projekt("Paris", os.path.join(tmp, "par"))
    p2["gebiet"]["mitte_en"] = list(t33.transform(2.3522, 48.8566))
    p2["gebiet"].update(breite_cm=30.0, hoehe_cm=30.0)
    p2["modell"]["massstab"] = 1000
    p2["ausgaben"].update(laser=True)
    z2 = []
    erg2 = LF.alles(p2, ["laser"], lambda s: z2.append(str(s)), lambda *a, **k: None)
    pruef(p2["umgebung"]["epsg"] == 25831, "Paris: Projekt auf UTM 31")
    pruef(not (erg2.get("modell") or {}).get("fehler"), "Paris: Lasercut-Modell mit Copernicus-Gelaende ohne Fehler (%s)"
          % (erg2.get("modell") or {}).get("fehler"))
    pruef(any("Copernicus" in z for z in z2), "Paris: Protokoll nennt den Copernicus-Notbehelf")
    print()
    print("Alle Pruefungen bestanden." if not FEHLER else "%d Fehler" % len(FEHLER))
    if FEHLER:
        print("\n".join(zeilen[-60:]))
        print("\n".join(z2[-30:]))
    return 1 if FEHLER else 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
