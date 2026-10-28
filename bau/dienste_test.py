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
# Kurzfassung der Auffälligkeiten
print("\n=== AUFFÄLLIGKEITEN ===")
for z in zeilen:
    if any(w in z for w in ("FEHLER", "nicht erreichbar", "fehlgeschlagen", "keine Objekte", "0 Objekte", "Vorrangnetz", "Attribute (Beispiel)")):
        print(z[:300])
