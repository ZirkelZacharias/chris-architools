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


if __name__ == "__main__":
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
