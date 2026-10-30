"""Fragt die Berliner Dienste direkt ab und schreibt auf, was sie liefern (Feature-Typen, Attribute, vorkommende Werte).
Dient dazu, Zuordnungen (z. B. ÖPNV-Vorrangnetz, Radverkehrsnetz) an den echten Daten auszurichten."""
import collections
import json
import re
import urllib.parse
import urllib.request

try:                                   # Zertifikate des Betriebssystems verwenden (wie das Programm selbst)
    import truststore
    truststore.inject_into_ssl()
except Exception as e:
    print('truststore nicht nutzbar:', e)

BASIS = "https://gdi.berlin.de/services/wfs/"
DIENSTE = {
    "vorrangnetz": None, "oepnv_ungestoert": None, "radverkehrsnetz": None, "ua_gebaeudehoehen": None,
}
# Mitte Pankow (Betriebswerk) und Alexanderplatz (viele Tram-/Buslinien) als Prüfgebiete
GEBIETE = {"Pankow": (393000, 5826000, 394400, 5827200), "Alexanderplatz": (391800, 5820000, 392800, 5821000)}


def holen(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "ZachariasTools-Sonde"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def typen(dienst):
    x = holen(f"{BASIS}{dienst}?service=WFS&version=2.0.0&request=GetCapabilities").decode("utf-8", "replace")
    return sorted(set(re.findall(r"<(?:\w+:)?Name>([^<]+:[^<]+)</(?:\w+:)?Name>", x)))


def abfragen(dienst, typ, bbox=None, count=20000):
    q = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "outputFormat": "application/json", "srsName": "EPSG:25833",
         "typeNames": typ, "count": str(count)}
    if bbox:
        q["bbox"] = ",".join(str(v) for v in bbox) + ",EPSG:25833"
    return json.loads(holen(f"{BASIS}{dienst}?" + urllib.parse.urlencode(q)))


def zusammenfassen(fc, titel):
    f = fc.get("features", [])
    print(f"  {titel}: {len(f)} Objekte")
    if not f:
        return
    print("    Geometrie:", dict(collections.Counter((x.get("geometry") or {}).get("type") for x in f)))
    cols = collections.defaultdict(collections.Counter)
    for x in f:
        for k, v in (x.get("properties") or {}).items():
            cols[k][str(v)[:60]] += 1
    for k, c in cols.items():
        if len(c) <= 25:
            print(f"    {k}: {dict(c.most_common(25))}")
        else:
            print(f"    {k}: {len(c)} verschiedene Werte, z. B. {list(c)[:4]}")


def wms_sonde():
    """Luftbild-Dienste: welche Ebenen gibt es, und was liefert ein Probebild am Betriebswerk Pankow (Statistik)?
    Hintergrund: Die Rastergravur ergab gleichförmige Linien – Verdacht: falsche Ebene (Übersicht statt Orthofoto)."""
    import io
    import xml.etree.ElementTree as ET
    try:
        import numpy as np
        from PIL import Image
    except Exception as e:
        print("WMS-Sonde: numpy/PIL fehlen", e)
        return
    wbasis = "https://gdi.berlin.de/services/wms/"
    bb = (393550, 5826450, 393850, 5826750)             # 300 x 300 m um den Ringlokschuppen
    dienste = ["truedop_%d" % j for j in range(2026, 2018, -1)] + ["truedop_2020_sommer"] + ["dop_%d" % j for j in range(2026, 2017, -1)] + ["luftbild_1998_05", "luftbild_1953_22", "luftbild_1928_04"]
    print("\n=== WMS-Sonde Luftbilder (Betriebswerk Pankow, 300 x 300 m, 1 m/Pixel) ===")
    for d in dienste:
        try:
            x = holen(wbasis + d + "?SERVICE=WMS&REQUEST=GetCapabilities&VERSION=1.1.1", 60)
        except Exception as e:
            print(f"  {d}: GetCapabilities Fehler {str(e)[:100]}")
            continue
        root = ET.fromstring(x)
        lok = lambda t: t.rsplit("}", 1)[-1]
        ebenen = []

        def lauf(k, tiefe):
            name = next((c.text for c in k if lok(c.tag) == "Name" and c.text), None)
            titel = next((c.text for c in k if lok(c.tag) == "Title" and c.text), "")
            abstr = next((c.text for c in k if lok(c.tag) == "Abstract" and c.text), "")
            kinder = [c for c in k if lok(c.tag) == "Layer"]
            srs = sorted({w for c in k if lok(c.tag) in ("SRS", "CRS") and c.text for w in c.text.split()})
            print(f"  {d}: {'  ' * tiefe}Ebene name={name!r} titel={titel!r} blatt={not kinder} srs25833={'EPSG:25833' in srs} "
                  f"abstract={abstr[:120]!r}")
            if not kinder and name:
                ebenen.append(name)
            for c in kinder:
                lauf(c, tiefe + 1)
        for cap in root.iter():
            if lok(cap.tag) == "Capability":
                for l in cap:
                    if lok(l.tag) == "Layer":
                        lauf(l, 0)
                break
        for e in ebenen[:6]:
            for fmt in ("image/jpeg", "image/png"):
                u = (wbasis + d + "?" + urllib.parse.urlencode({"SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap", "LAYERS": e, "STYLES": "",
                     "SRS": "EPSG:25833", "BBOX": ",".join(map(str, bb)), "WIDTH": 300, "HEIGHT": 300, "FORMAT": fmt, "TRANSPARENT": "FALSE"}, safe=",:"))
                try:
                    roh = holen(u, 90)
                    im = Image.open(io.BytesIO(roh)).convert("RGB")
                    a = np.asarray(im).astype(float)
                    g = a.mean(axis=2)
                    farben, anz = np.unique(a.reshape(-1, 3).astype(int), axis=0, return_counts=True)
                    print(f"    GetMap {d}/{e} {fmt}: {im.size}, Grau Mittel {g.mean():.0f} Streuung {g.std():.1f} P2/P98 "
                          f"{np.percentile(g, 2):.0f}/{np.percentile(g, 98):.0f}, {len(np.unique(g.astype(int)))} Grauwerte, "
                          f"{len(farben)} Farben, häufigste Farbe {tuple(farben[anz.argmax()])} = {anz.max() / anz.sum() * 100:.0f} %, "
                          f"weiß {np.mean(g > 250) * 100:.0f} %")
                except Exception as ex:
                    print(f"    GetMap {d}/{e} {fmt}: Fehler {str(ex)[:160]}")


def luftbildsuche_live():
    """Die Luftbildsuche des Programms (Probebild je Ebene) gegen die echten Dienste: welche Ebene wird je Katalogeintrag gewählt?"""
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "architools", "kern"))
    import ssl
    import ifcmap_wms as WM
    ctx = ssl.create_default_context()
    print("\n=== Luftbildsuche des Programms (live, Betriebswerk Pankow) ===")
    for k, (name, dienste, wahl, foto) in WM.WMS_KATALOG.items():
        if not foto:
            continue
        print(f"  {k}: {name}")
        b, e = WM.luftbild_suchen([WM.WMS_BASIS + s for s in dienste], (393550, 5826450, 393850, 5826750), ctx, print)
        print(f"  -> {k}: {(b or '').rsplit('/', 1)[-1] or 'KEIN LUFTBILD'} / {e}")


if __name__ == "__main__":
    try:
        luftbildsuche_live()
    except Exception as e:
        print("Luftbildsuche Fehler:", e)
    try:
        wms_sonde()
    except Exception as e:
        print("WMS-Sonde Fehler:", e)
    for d in DIENSTE:
        print(f"\n=== {d} ===")
        try:
            ts = typen(d)
            print("  Feature-Typen:", ts)
        except Exception as e:
            print("  Typenliste nicht lesbar:", e)
            continue
        for t in ts:
            for name, bb in (("ganz Berlin (bis 20000)", None),) + tuple(GEBIETE.items()):
                try:
                    zusammenfassen(abfragen(d, t, bb), f"{t} / {name}")
                except Exception as e:
                    print(f"  {t} / {name}: Fehler {str(e)[:150]}")
                if d == "ua_gebaeudehoehen" and bb is None:
                    break
