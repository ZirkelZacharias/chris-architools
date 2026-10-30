"""Echtlauf gegen die Berliner Dienste (braucht Internet): Gebiet Betriebswerk Pankow, 300 x 300 m.
Schreibt alles ins Protokoll; scheitert nie hart, damit der Bericht auch bei Teilfehlern vollständig ist."""
import json
import os
import sys
import tempfile
import time
import traceback

sys.path.insert(0, os.getcwd())
from architools import laufen as L, projekt as P  # noqa: E402

TMP = tempfile.mkdtemp()
p = P.neues_projekt("Dienste", os.path.join(TMP, "proj"))
p["gebiet"]["mitte_en"] = [393694.5, 5826537.7]
u = p["umgebung"]
u.update(land="berlin", quelle="berlin", online_dgm=True, online_lod2=True, breite=300.0, hoehe=300.0, nah_breite=200.0, nah_hoehe=200.0,
         lod2_luecken=True, alkis_zusatz=True, ua_gebaeudehoehen=True, ua_vegetationshoehen=True, rad_wege=True, osm_ergaenzen=True,
         extra=["oepnv", "radverkehr", "gewaesser", "denkmal"], buergersteige="fgn")
p["formate"] = {"zweid": ["dxf"], "dreid": ["ifc"]}
p["ausgaben"].update(ifc=True, lageplan=True, schwarzplan=True, info_dwg=True, schnitt=True)
p["schnitt"]["linie_en"] = [[393550, 5826540], [393850, 5826540]]
zeilen = []


def log(s):
    print(s, flush=True)
    zeilen.append(str(s))


t0 = time.time()
try:
    erg = L.alles(p, P.gewaehlt(p), log, lambda x, t="": None)
    print("FERTIG", round(time.time() - t0), "s")
    for k, v in erg.items():
        print(k, "->", (v.get("fehler") or "ok") if isinstance(v, dict) else v)
    for r, _, fs in os.walk(os.path.join(TMP, "proj", "ausgabe")):
        for f in fs[:60]:
            print("  Datei:", os.path.join(r, f).replace(TMP, ""), os.path.getsize(os.path.join(r, f)))
except Exception:
    print("ABBRUCH:\n" + traceback.format_exc())
# Zweiter Lauf am Alexanderplatz: viele Tram-, Bus- und S-Bahn-Linien -> prüft die ÖPNV-Ebenen der Informations-DWG
try:
    print("\n=== ÖPNV-Test Alexanderplatz ===")
    p2 = P.neues_projekt("Alex", os.path.join(TMP, "alex"))
    p2["gebiet"]["mitte_en"] = [392300.0, 5820500.0]
    u2 = p2["umgebung"]
    u2.update(land="berlin", quelle="berlin", online_dgm=True, online_lod2=False, breite=400.0, hoehe=400.0, nah_breite=300.0,
              nah_hoehe=300.0, lod2_luecken=False, alkis_zusatz=False, extra=["oepnv"], buergersteige="keine", markant=False)
    p2["formate"] = {"zweid": ["dxf"], "dreid": ["ifc"]}
    p2["ausgaben"].update(info_dwg=True)
    erg2 = L.alles(p2, ["info_dwg"], log, lambda x, t="": None)
    import ezdxf
    for r, _, fs in os.walk(os.path.join(TMP, "alex", "ausgabe")):
        for f in fs:
            if f.endswith(".dxf"):
                doc = ezdxf.readfile(os.path.join(r, f))
                zaehl = {}
                for e in doc.modelspace():
                    zaehl[e.dxf.layer] = zaehl.get(e.dxf.layer, 0) + 1
                print("ÖPNV-Ebenen:", {k: v for k, v in zaehl.items() if "OEPNV" in k.upper() or "OPNV" in k.upper()})
except Exception:
    print("ABBRUCH ÖPNV-Test:\n" + traceback.format_exc())
# Ausland (neu): Zürich (swissALTI3D per STAC, Gebäude aus OSM), Amsterdam (AHN per WCS, 3DBAG), Paris (UTM 31 + Copernicus)
for name, lat, lon in (("Zuerich", 47.3717, 8.5423), ("Amsterdam", 52.3731, 4.8922), ("Paris", 48.8530, 2.3499)):
    try:
        print("\n=== Ausland-Test %s ===" % name)
        from pyproj import Transformer
        p3 = P.neues_projekt(name, os.path.join(TMP, name))
        p3["gebiet"]["mitte_en"] = list(Transformer.from_crs("EPSG:4326", "EPSG:25833", always_xy=True).transform(lon, lat))
        p3["umgebung"].update(breite=300.0, hoehe=300.0, nah_breite=200.0, nah_hoehe=200.0, buergersteige="keine", lod2_luecken=True,
                              markant=False)
        p3["gebiet"].update(breite_cm=30.0, hoehe_cm=30.0)
        p3["modell"]["massstab"] = 1000
        p3["formate"] = {"zweid": ["dxf"], "dreid": ["ifc"]}
        p3["ausgaben"].update(ifc=True, lageplan=True, laser=True)
        t3 = time.time()
        erg3 = L.alles(p3, ["ifc", "lageplan", "laser"], log, lambda x, t="": None)
        print("FERTIG", name, round(time.time() - t3), "s, KBS EPSG:%s" % p3["umgebung"]["epsg"])
        for k, v in erg3.items():
            print(" ", k, "->", (v.get("fehler") or "ok") if isinstance(v, dict) else v)
    except Exception:
        print("ABBRUCH Ausland-Test %s:\n%s" % (name, traceback.format_exc()))
# Kurzfassung der Auffälligkeiten
print("\n=== AUFFÄLLIGKEITEN ===")
for z in zeilen:
    if any(w in z for w in ("FEHLER", "nicht erreichbar", "fehlgeschlagen", "keine Objekte", "0 Objekte", "Vorrangnetz", "Attribute (Beispiel)",
                            "STAC", "WCS", "3DBAG", "Koordinatensystem", "Copernicus", "umgerechnet")):
        print(z[:300])
