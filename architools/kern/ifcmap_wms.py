"""Kartenbilder aus WMS-Diensten (Luftbild, historische Karten, Umweltatlas-Themenplaene) fuer die Informations-DWG.

Jede gewaehlte Karte wird fuer das Gebiet als PNG geladen und ueber die vorhandene Zusatzplan-Ausgabe (ifcmap_zusatz)
als eigene DXF mit DXF-IMAGE, PNG und World-File geschrieben - im selben Nullpunkt wie alle anderen Ausgaben.
Die Karten sind nur Hintergruende zum Daruntermalen (Raster, nicht vektorisiert).
Die Dienstadressen stammen aus den Metadaten von gdi.berlin.de; die Ebenennamen werden beim Laden per GetCapabilities
ermittelt. Der Abruf selbst ist noch nicht gegen die Live-Dienste getestet.
"""
import io
import math
import os
import re
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

WMS_BASIS = "https://gdi.berlin.de/services/wms/"
EPSG = "EPSG:25833"
KACHEL_PX = 2048            # so gross darf eine einzelne Anfrage hoechstens sein
MAX_PX = 4096               # laengste Seite des fertigen Bildes (wie bei den Zusatzplaenen)

# Schluessel: (Anzeigename, Dienste (der Reihe nach probieren), welche Ebenen, Foto?)
WMS_KATALOG = {
    "luftbild": ("Luftbild – aktuellstes verfügbares Orthofoto (Berlin)", ["dop_%d" % j for j in range(2026, 2013, -1)], "erste", True),
    "luftbild_1998": ("Luftbild 1998 (Schwarzweiß)", ["luftbild_1998_05"], "erste", True),
    "luftbild_1953": ("Luftbild 1953", ["luftbild_1953_22"], "erste", True),
    "luftbild_1928": ("Luftbild 1928", ["luftbild_1928_04"], "erste", True),
    "berlin1900": ("Historische Karte: Berlin um 1900", ["berlin1900"], "alle", False),
    "k5": ("Historische Karte: Karte von Berlin 1:5000 (Schwarzweiß, neuester Stand)", ["k5_historie"], "letzte", False),
    "ua_versiegelung": ("Umweltatlas: Versiegelung 2021", ["ua_versiegelung_2021"], "erste", False),
    "ua_stadtstruktur": ("Umweltatlas: Stadtstruktur (ab 2021)", ["ua_stadtstruktur"], "erste", False),
}
WMS_NAMEN = {k: v[0] for k, v in WMS_KATALOG.items()}


def _lokal(tag):
    return tag.rsplit("}", 1)[-1]


def _holen(url, ctx, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": "ZachariasTools/0.1 (+https://github.com/ZirkelZacharias/zacharias-tools)"})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read(), (r.headers.get("Content-Type") or "").lower()


def _url(basis, **par):
    sep = "&" if "?" in basis else "?"
    return basis + sep + urllib.parse.urlencode(par, safe=",:")


def ebenen_lesen(basis, ctx):
    """GetCapabilities -> Liste (Name, Titel, hat_EPSG25833) der Blattebenen"""
    roh, _ = _holen(_url(basis, SERVICE="WMS", REQUEST="GetCapabilities", VERSION="1.1.1"), ctx, 45)
    root = ET.fromstring(roh)
    out = []

    def lauf(knoten, srs):
        eig = set(srs)
        for k in knoten:
            if _lokal(k.tag) in ("SRS", "CRS") and k.text:
                eig.update(k.text.split())
        kinder = [k for k in knoten if _lokal(k.tag) == "Layer"]
        if not kinder:
            name = next((k.text for k in knoten if _lokal(k.tag) == "Name" and k.text), None)
            titel = next((k.text for k in knoten if _lokal(k.tag) == "Title" and k.text), name)
            if name:
                out.append((name.strip(), (titel or name).strip(), EPSG in eig))
        for k in kinder:
            lauf(k, eig)
    for cap in root.iter():
        if _lokal(cap.tag) == "Capability":
            for l in cap:
                if _lokal(l.tag) == "Layer":
                    lauf(l, set())
            break
    return out


def _gewaehlt(ebenen, wahl):
    gut = [e for e in ebenen if e[2]] or ebenen
    if not gut:
        return []
    if wahl == "alle":
        return [e[0] for e in gut]
    if wahl == "letzte":
        return [gut[-1][0]]
    return [gut[0][0]]


def bild_holen(basis, ebenen, rect, aufloesung, foto, ctx, log=print):
    """Gebiet rect=(xmin, ymin, xmax, ymax) als PIL-Bild; Kacheln werden zusammengesetzt. -> (Bild, Breite_px, Hoehe_px)"""
    from PIL import Image
    x0, y0, x1, y1 = rect
    B, H = x1 - x0, y1 - y0
    aufl = max(float(aufloesung or 0.25), B / MAX_PX, H / MAX_PX)
    W, Hp = int(math.ceil(B / aufl)), int(math.ceil(H / aufl))
    fmt = "image/jpeg" if foto else "image/png"
    gross = Image.new("RGB", (W, Hp), "white")
    nx, ny = int(math.ceil(W / KACHEL_PX)), int(math.ceil(Hp / KACHEL_PX))
    for j in range(ny):
        for i in range(nx):
            c0, r0 = i * KACHEL_PX, j * KACHEL_PX
            c1, r1 = min(W, c0 + KACHEL_PX), min(Hp, r0 + KACHEL_PX)
            bx0, bx1 = x0 + c0 * aufl, x0 + c1 * aufl
            by1, by0 = y1 - r0 * aufl, y1 - r1 * aufl
            u = _url(basis, SERVICE="WMS", VERSION="1.1.1", REQUEST="GetMap", LAYERS=",".join(ebenen), STYLES="",
                     SRS=EPSG, BBOX="%.3f,%.3f,%.3f,%.3f" % (bx0, by0, bx1, by1), WIDTH=c1 - c0, HEIGHT=r1 - r0,
                     FORMAT=fmt, TRANSPARENT="FALSE")
            roh, typ = _holen(u, ctx)
            if not typ.startswith("image/"):
                raise RuntimeError("Dienst lieferte kein Bild: %s" % roh[:200].decode("utf-8", "replace").replace("\n", " "))
            kachel = Image.open(io.BytesIO(roh)).convert("RGB")
            gross.paste(kachel, (c0, r0))
    return gross, W, Hp, aufl


def luftbild_fuer_gelaende(d, cfg, log=print):
    """Luftbild (aktuellstes Orthofoto, Berlin) fuer das ganze Gebiet als PIL-Bild; -> (Bild, rect) oder None.
    Wird als Textur auf das Gelaende gelegt (IFC, 3D-Vorschau). Bei Fehlern: None und eine Zeile im Protokoll."""
    import ifcmap_kern as K
    from PIL import Image
    ctx = K.ssl_kontext(cfg.cafile, cfg.unsicher)
    rect = (d.xmin, d.ymin, d.xmax, d.ymax)
    name, dienste, wahl, foto = WMS_KATALOG["luftbild"]
    fehler = []
    for s in dienste:
        basis = WMS_BASIS + s
        try:
            eb = _gewaehlt(ebenen_lesen(basis, ctx), wahl)
            if not eb:
                raise RuntimeError("keine Ebenen im Dienst")
            im, W, H, px = bild_holen(basis, eb, rect, float(getattr(cfg, "luftbild_aufloesung", 0.5) or 0.5), True, ctx, log)
            if max(W, H) > 4096:
                im = im.resize((min(W, 4096), min(H, 4096)))
            log("  Luftbild (%s): %d x %d Pixel, %.2f m je Pixel" % (s, im.size[0], im.size[1], px))
            return im, rect
        except Exception as e:
            fehler.append("%s: %s" % (s, str(e)[:70]))
    log("  HINWEIS: Luftbild nicht erreichbar oder ausserhalb des Dienstgebiets (%s) - Gelaende bleibt ohne Textur" % "; ".join(fehler[:3]))
    return None


def _eigene(text):
    """Zeilen 'Name | Adresse | Ebene1,Ebene2' (Ebenen optional) -> Liste von Dicts"""
    out = []
    for z in (text or "").splitlines():
        t = [s.strip() for s in z.split("|")]
        if len(t) >= 2 and t[1].lower().startswith("http"):
            out.append({"name": t[0] or "Karte", "url": t[1], "ebenen": [e for e in (t[2].split(",") if len(t) > 2 else []) if e.strip()]})
    return out


def schreibe_wms(d, cfg, ordner, log=print, praefix=""):
    """Alle gewaehlten Kartenbilder als eigene DXF (+PNG/PGW). -> Liste der erzeugten Dateien"""
    import ifcmap_kern as K
    import ifcmap_zusatz as ZU
    auftraege = []
    for k in (getattr(cfg, "wms_karten", None) or []):
        if k in WMS_KATALOG:
            name, dienste, wahl, foto = WMS_KATALOG[k]
            auftraege.append({"key": k, "name": name, "dienste": [WMS_BASIS + s for s in dienste], "wahl": wahl, "foto": foto, "ebenen": []})
    for e in _eigene(getattr(cfg, "wms_eigene", "")):
        auftraege.append({"key": "eigen", "name": e["name"], "dienste": [e["url"]], "wahl": "erste", "foto": False, "ebenen": e["ebenen"]})
    if not auftraege:
        return []
    ctx = K.ssl_kontext(cfg.cafile, cfg.unsicher)
    rect = (d.xmin, d.ymin, d.xmax, d.ymax)
    aufl = float(getattr(cfg, "wms_aufloesung", 0.25) or 0.25)
    erzeugt = []
    tmp = tempfile.mkdtemp(prefix="ifcmap_wms_")
    for a in auftraege:
        log("Kartenbild %s:" % a["name"])
        try:
            basis, ebenen, fehler = None, a["ebenen"], []
            for b in a["dienste"]:
                try:
                    if not ebenen:
                        el = ebenen_lesen(b, ctx)
                        eb = _gewaehlt(el, a["wahl"])
                        if not eb:
                            raise RuntimeError("keine Ebenen im Dienst")
                    else:
                        eb = ebenen
                    basis, ebenen = b, eb
                    break
                except Exception as e:
                    fehler.append("%s: %s" % (b.rsplit("/", 1)[-1], str(e)[:80]))
            if not basis:
                log("  Dienst nicht erreichbar oder nicht vorhanden (%s) - uebersprungen" % "; ".join(fehler[:3]))
                continue
            log("  Dienst %s, Ebene(n): %s" % (basis.rsplit("/", 1)[-1], ", ".join(ebenen)))
            im, W, H, px = bild_holen(basis, ebenen, rect, aufl, a["foto"], ctx, log)
            sauber = re.sub(r"[^A-Za-z0-9]+", "_", K.umlaute(a["name"])).strip("_")[:40].strip("_") or "Karte"
            png = os.path.join(tmp, sauber + ".png")
            im.save(png)
            plan = {"name": "Karte_" + sauber, "datei": png, "modus": "bild", "seite": 1,
                    "punkte": [{"x": 0, "y": 0, "E": rect[0], "N": rect[3]}, {"x": W, "y": H, "E": rect[0] + W * px, "N": rect[3] - H * px}]}
            log("  %d x %d Pixel, %.2f m je Pixel" % (W, H, px))
            erzeugt.extend(ZU.schreibe_zusatzplaene(d, [plan], ordner, log, praefix=praefix))
        except Exception as e:
            log("  FEHLER bei %s: %s" % (a["name"], e))
    return erzeugt
