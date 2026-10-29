# -*- coding: utf-8 -*-
"""IFCmap - Laendermodule: Gelaende (DGM) und Gebaeude (LoD2) der Bundeslaender automatisch holen.

Jedes Land ist ein Profil (siehe PROFILE unten). Die Profile koennen ohne Programmieren geaendert oder ergaenzt werden:
Datei  system/laender.json  (neben diesem Programm)  oder  ~/.ifcmap/laender.json  - Eintraege dort ueberschreiben die eingebauten.

Teil "dgm" und "lod2" eines Profils:
  art     "kachel"   fester Download pro Kachel (Adresse = url mit Platzhaltern)
          "wfs"      Gebaeude per WFS-Abfrage je Kachel (nur lod2)
          "manuell"  kein automatischer Download - das Programm nennt die benoetigten Kacheln und das Portal
  kachel  Kantenlaenge der Kacheln in m (Ursprung = Vielfache davon)
  url     Platzhalter: {E} {N} (Meter, Ecke links unten), {ekm} {nkm} (Kilometer), {ekm3} (Ost-km dreistellig), {zone} (32, 33 ...)
  liste   optional: Verzeichnis-Adresse, deren Inhalt nach dem Dateinamen durchsucht wird (wenn der Name ein Jahr o. ae. enthaelt)
  muster  Regulaerer Ausdruck fuer den Dateinamen in der Liste (mit {ekm} {nkm}); der letzte Treffer (neuestes Jahr) gilt
  nutzung (optional, eigener Teil) amtliche Nutzungsflaechen per ALKIS-WFS: basis, muster (Regulaerer Ausdruck fuer den Datensatznamen,
          Vorgabe "nutzung") oder fester Datensatz "typ". Fehlt der Teil oder liefert der Dienst nichts, nimmt IFCmap OpenStreetMap.
  status  Hinweistext ("bestaetigt", "ungetestet" ...) - erscheint im Protokoll
"""
import glob
import hashlib
import json
import math
import os
import re
import time
import zipfile
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import replace

PROFILE = {
    "brandenburg": dict(
        name="Brandenburg", epsg=25833, box=(11.26, 51.36, 14.77, 53.56), portal="https://geobasis-bb.de",
        dgm=dict(art="kachel", kachel=1000, ext="zip",
                 url="https://data.geobasis-bb.de/geobasis/daten/dgm/xyz/dgm_{zone}{ekm3}-{nkm}.zip",
                 status="Adresse gefunden, noch nicht an echten Daten getestet"),
        lod2=dict(art="wfs", kachel=1000, basis="https://isk.geobasis-bb.de/ows/gebaeudelod2_wfs", typ="auto", version="2.0.0",
                  status="WFS-Adresse bestaetigt, Abfrage noch nicht an echten Daten getestet"),
        nutzung=dict(basis="https://isk.geobasis-bb.de/ows/alkis_sf_wfs", muster="nutzung", version="2.0.0",
                     status="UNGETESTET - ob der Dienst die Tatsaechliche Nutzung enthaelt, ist nicht belegt; sonst Ersatz OpenStreetMap")),
    "nrw": dict(
        name="Nordrhein-Westfalen", epsg=25832, box=(5.86, 50.32, 9.46, 52.53), portal="https://www.opengeodata.nrw.de",
        dgm=dict(art="kachel", kachel=1000, ext="tif",
                 liste="https://www.opengeodata.nrw.de/produkte/geobasis/hm/dgm1_tiff/dgm1_tiff/",
                 muster=r"dgm1_32_{ekm}_{nkm}_1_nw[^\"'<>\s/]*\.tif",
                 url="https://www.opengeodata.nrw.de/produkte/geobasis/hm/dgm1_tiff/dgm1_tiff/dgm1_32_{ekm}_{nkm}_1_nw.tif",
                 status="Verzeichnis und Namensschema bestaetigt, noch nicht an echten Daten getestet"),
        lod2=dict(art="kachel", kachel=1000, ext="gml",
                  liste="https://www.opengeodata.nrw.de/produkte/geobasis/3dg/lod2_gml/lod2_gml/",
                  muster=r"LoD2_32_{ekm}_{nkm}_1_NW[^\"'<>\s/]*\.(?:gml|xml|zip)",
                  url="https://www.opengeodata.nrw.de/produkte/geobasis/3dg/lod2_gml/lod2_gml/LoD2_32_{ekm}_{nkm}_1_NW.gml",
                  status="UNGETESTET - Verzeichnis aus der Erinnerung, bei Fehler Adresse in system/laender.json anpassen"),
        nutzung=dict(basis="https://www.wfs.nrw.de/geobasis/wfs_nw_alkis_vereinfacht", muster="nutzung", version="2.0.0",
                     status="Dienst bestaetigt (ALKIS vereinfacht, enthaelt Tatsaechliche Nutzung); Abfrage ungetestet, sonst Ersatz OpenStreetMap")),
    "bayern": dict(
        name="Bayern", epsg=25832, box=(8.97, 47.27, 13.84, 50.57), portal="https://geodaten.bayern.de/opengeodata",
        dgm=dict(art="kachel", kachel=1000, ext="tif",
                 url="https://download1.bayernwolke.de/a/dgm/dgm1/{ekm}_{nkm}.tif",
                 status="UNGETESTET - Adresse und Kachelgroesse aus der Erinnerung, bei Fehler in system/laender.json anpassen"),
        lod2=dict(art="kachel", kachel=2000, ext="gml",
                  url="https://download1.bayernwolke.de/a/lod2/citygml/{ekm}_{nkm}.gml",
                  status="UNGETESTET - Adresse und Kachelgroesse aus der Erinnerung, bei Fehler in system/laender.json anpassen")),
    "hamburg": dict(
        name="Hamburg", epsg=25832, box=(9.70, 53.39, 10.35, 53.75), portal="https://suche.transparenz.hamburg.de",
        dgm=dict(art="manuell", kachel=1000,
                 status="kein automatischer Download: DGM1 im Hamburger Transparenzportal laden und unter 'Eigene Dateien' hinzufuegen"),
        lod2=dict(art="wfs", kachel=1000, basis="https://geodienste.hamburg.de/HH_WFS_LoD2_DE", typ="auto", version="2.0.0",
                  status="UNGETESTET - WFS-Adresse aus der Erinnerung, bei Fehler in system/laender.json anpassen")),
}
# DOM = Oberflaechenmodell (Laserscan, 1 m) - nur fuer 'Markante Gebaeude' (Kirchtuerme, Kuppeln ...), kachelweise nach Bedarf
PROFILE["berlin"] = dict(
    name="Berlin", epsg=25833, box=(13.08, 52.33, 13.77, 52.68), portal="https://daten.berlin.de",
    dom=dict(art="kachel", kachel=2000, ext="zip",
             url="https://gdi.berlin.de/data/dom/atom/DOM1_{ekm}_{nkm}.zip",
             status="Adresse aus dem ATOM-Feed gdi.berlin.de/data/dom/atom/0.atom (2-km-Kacheln, CSV gezippt, 1 m, DOM1 aus Laserscan 2021); "
                    "Dateiinhalt noch ungesehen - bei Fehler DOM von daten.berlin.de laden und unter 'Eigene Dateien' hinzufuegen"))
PROFILE["nrw"]["dom"] = dict(
    art="kachel", kachel=1000, ext="tif",
    liste="https://www.opengeodata.nrw.de/produkte/geobasis/hm/dom1_tiff/dom1_tiff/",
    muster=r"dom1_32_{ekm}_{nkm}_1_nw[^\"'<>\s/]*\.tif",
    url="https://www.opengeodata.nrw.de/produkte/geobasis/hm/dom1_tiff/dom1_tiff/dom1_32_{ekm}_{nkm}_1_nw.tif",
    status="UNGETESTET - Verzeichnis nach dem Muster des DGM erraten")
PROFILE["brandenburg"]["dom"] = dict(
    art="kachel", kachel=1000, ext="zip",
    url="https://data.geobasis-bb.de/geobasis/daten/dom/xyz/dom_{zone}{ekm3}-{nkm}.zip",
    status="UNGETESTET - Adresse nach dem Muster des DGM erraten")
_DOM_LETZTE = []                                     # DOM-Dateien des letzten kacheln_holen(..., dom=True)
# Berlin hat seinen eigenen, laengst erprobten Weg im Kern (ATOM-Dienst) und steht deshalb hier nur zur Erkennung
REIHENFOLGE = ["berlin", "hamburg", "brandenburg", "nrw", "bayern"]
BERLIN_BOX = (13.08, 52.33, 13.77, 52.68)
NAMEN = {"berlin": "Berlin", "hamburg": "Hamburg", "brandenburg": "Brandenburg", "nrw": "Nordrhein-Westfalen", "bayern": "Bayern"}


def _json_orte():
    return [os.path.join(os.path.dirname(os.path.abspath(__file__)), "system", "laender.json"),
            os.path.join(os.path.expanduser("~"), ".ifcmap", "laender.json")]


def profile(log=None):
    """Eingebaute Profile + Aenderungen aus system/laender.json und ~/.ifcmap/laender.json."""
    p = json.loads(json.dumps(PROFILE))
    try:                                                    # Länderprofile aus Zusatzmodulen (Plugins je Bundesland)
        import sys as _sys
        _pk = _sys.modules.get("architools.zusatz")
        if _pk is None:
            import architools.zusatz as _pk
        for _n, _m in _pk.module().items():
            for _land, _w in (getattr(_m, "LAENDER", None) or {}).items():
                if isinstance(_w, dict):
                    p[_land] = json.loads(json.dumps(_w))
    except Exception:
        pass
    for pfad in _json_orte():
        if not os.path.exists(pfad):
            continue
        try:
            with open(pfad, "r", encoding="utf-8") as f:
                extra = json.load(f)
        except Exception as e:
            if log:
                log("  HINWEIS: %s nicht lesbar (%s) - eingebaute Laenderprofile gelten" % (pfad, e))
            continue
        for land, w in extra.items():
            if land.startswith("_") or not isinstance(w, dict):
                continue
            ziel = p.setdefault(land, {})
            for k, v in w.items():
                if isinstance(v, dict) and isinstance(ziel.get(k), dict):
                    ziel[k].update(v)
                else:
                    ziel[k] = v
    return p


def standard_json():
    """Inhalt der mitgelieferten system/laender.json: nur Aenderungen gegenueber den eingebauten Profilen (zunaechst keine)."""
    return {
        "_hinweis": "Hier stehen nur Aenderungen gegenueber den eingebauten Laenderprofilen (Erklaerung im Kopf von ifcmap_laender.py). "
                    "Eintraege, deren Name mit _ beginnt, werden ignoriert. Neues Land: Eintrag mit eigenem Namen (epsg, box = West, Sued, Ost, Nord in Grad, dgm, lod2, nutzung).",
        "_beispiel_adresse_aendern": {"bayern": {"dgm": {"url": "https://example.org/dgm/{ekm}_{nkm}.tif"}}},
        "_eingebaute_laender": sorted(PROFILE),
    }


def land_bestimmen(cfg, K, prof=None):
    """-> Land-Kennung ("berlin", "nrw" ...) oder None (unbekannt / 'keins')."""
    wahl = getattr(cfg, "land", "auto") or "auto"
    if wahl == "keins":
        return None
    if wahl != "auto":
        return wahl
    try:
        from pyproj import Transformer
        ce, cn = K.mitte_bestimmen(cfg)
        lo, la = Transformer.from_crs("EPSG:%d" % cfg.epsg, "EPSG:4326", always_xy=True).transform(ce, cn)
    except Exception:
        return None
    return land_am_punkt(lo, la, prof or profile())


def land_am_punkt(lo, la, prof):
    """Bundesland zu Laenge/Breite. Berlin und Hamburg (Stadtstaaten in groesseren Land-Rechtecken) haben Vorrang; sonst gewinnt bei
    ueberlappenden Rechtecken das Land, dessen Mitte (auf die Rechteckgroesse bezogen) am naechsten liegt. An Landesgrenzen bleibt das
    eine Naeherung - dort das Land in den Einstellungen von Hand waehlen."""
    for land in ("berlin", "hamburg"):
        box = BERLIN_BOX if land == "berlin" else tuple((prof.get(land) or {}).get("box") or ())
        if len(box) == 4 and box[0] <= lo <= box[2] and box[1] <= la <= box[3]:
            return land
    beste, bw = None, None
    for land, p in prof.items():
        box = tuple(p.get("box") or ())
        if land in ("berlin", "hamburg") or len(box) != 4 or not (box[0] <= lo <= box[2] and box[1] <= la <= box[3]):
            continue
        w = max(abs(lo - (box[0] + box[2]) / 2) / ((box[2] - box[0]) / 2), abs(la - (box[1] + box[3]) / 2) / ((box[3] - box[1]) / 2))
        if bw is None or w < bw:
            beste, bw = land, w
    return beste


def vorbereiten(cfg, K, log):
    """Land bestimmen und das Koordinatensystem passend setzen. -> (cfg, land)"""
    prof = profile(log)
    land = land_bestimmen(cfg, K, prof)
    if land is None:
        return cfg, None
    log("Bundesland: %s%s" % (NAMEN.get(land) or prof.get(land, {}).get("name", land),
                              " (automatisch nach dem Mittelpunkt erkannt)" if (getattr(cfg, "land", "auto") or "auto") == "auto" else ""))
    ep = 25833 if land == "berlin" else prof.get(land, {}).get("epsg")
    if ep and ep != cfg.epsg:
        try:
            from pyproj import Transformer
            mitte = cfg.mitte_en
            if mitte:
                mitte = Transformer.from_crs("EPSG:%d" % cfg.epsg, "EPSG:%d" % ep, always_xy=True).transform(*mitte)
            log("  Koordinatensystem von EPSG:%d auf EPSG:%d umgestellt (passend zu %s)%s"
                % (cfg.epsg, ep, NAMEN.get(land, land), "; E0/N0 neu bestimmt" if cfg.e0n0 else ""))
            cfg = replace(cfg, epsg=ep, mitte_en=mitte, e0n0=None)
        except Exception as e:
            log("  HINWEIS: Koordinatensystem passt nicht zu %s (EPSG:%s) und konnte nicht umgestellt werden: %s" % (NAMEN.get(land, land), ep, e))
    return cfg, land


# ----------------------------------------------------------------------------------------------
# Kacheln
# ----------------------------------------------------------------------------------------------

def kachel_liste(bbox, groesse):
    """bbox = (xmin, ymin, xmax, ymax) -> [(E, N), ...] linke untere Ecken der Kacheln, die das Rechteck beruehren."""
    x0, y0, x1, y1 = bbox
    g = int(groesse)
    e0, e1 = int(math.floor(x0 / g)) * g, int(math.floor((x1 - 1e-6) / g)) * g
    n0, n1 = int(math.floor(y0 / g)) * g, int(math.floor((y1 - 1e-6) / g)) * g
    return [(e, n) for e in range(e0, e1 + 1, g) for n in range(n0, n1 + 1, g)]


def _fuellen(s, v):
    for k, w in v.items():
        s = s.replace("{" + k + "}", str(w))
    return s


def _vars(e, n, epsg):
    return {"E": e, "N": n, "ekm": e // 1000, "nkm": n // 1000, "ekm3": "%03d" % ((e // 1000) % 1000), "zone": epsg - 25800}


def _text_laden(url, ctx, ziel=None, max_alter=86400):
    """Text von url (mit Zwischenspeicher auf der Platte)."""
    if ziel and os.path.exists(ziel) and time.time() - os.path.getmtime(ziel) < max_alter:
        with open(ziel, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    req = urllib.request.Request(url, headers={"User-Agent": "ZachariasTools/0.1 (+https://github.com/ZirkelZacharias/zacharias-tools)"})
    with urllib.request.urlopen(req, timeout=120, context=ctx) as r:
        text = r.read().decode("utf-8", errors="replace")
    if ziel:
        with open(ziel, "w", encoding="utf-8") as f:
            f.write(text)
    return text


def _name_in_liste(teil, v, ctx, cache, log, speicher):
    """Sucht den Dateinamen der Kachel im Verzeichnis `liste`. -> Adresse oder None."""
    liste = teil["liste"]
    if liste not in speicher:
        ziel = os.path.join(cache, "liste_%s.txt" % hashlib.sha1(liste.encode()).hexdigest()[:12])
        try:
            speicher[liste] = _text_laden(liste, ctx, ziel)
            log("  Dateiliste gelesen: %s (%d kB)" % (liste, len(speicher[liste]) // 1024))
        except Exception as e:
            speicher[liste] = ""
            log("  Dateiliste nicht lesbar (%s) - es wird der Standardname versucht" % e)
    text = speicher[liste]
    if not text:
        return None
    try:
        treffer = re.findall(_fuellen(teil["muster"], v), text)
    except re.error as e:
        log("  FEHLER im 'muster' der Laenderdatei: %s" % e)
        return None
    if not treffer:
        return "nicht_in_liste"
    name = sorted(set(treffer))[-1]
    return urllib.parse.urljoin(liste, name)


def _dgm_dateien_aus(pfad, cache):
    """Gelesene Kachel -> lesbare Hoehendateien (entpackt ZIPs)."""
    if not pfad.lower().endswith(".zip"):
        return [pfad]
    ordner = pfad[:-4] + "_entpackt"
    if not os.path.isdir(ordner):
        with zipfile.ZipFile(pfad) as z:
            z.extractall(ordner)
    return [q for q in sorted(glob.glob(os.path.join(ordner, "**", "*"), recursive=True))
            if q.lower().endswith((".xyz", ".txt", ".csv", ".asc", ".tif", ".tiff", ".dat"))]


def _wfs_kachel_holen(teil, land, e, n, epsg, ctx, ziel, log, K):
    """Eine Gebaeude-Kachel per WFS -> GML-Datei ziel. True bei Erfolg."""
    basis = teil["basis"]
    typ = teil.get("typ") or "auto"
    if typ == "auto":
        try:
            namen = K.wfs_typnamen(basis, ctx)
        except Exception as ex:
            log("    GetCapabilities fehlgeschlagen: %s" % ex)
            namen = []
        wahl = [x for x in namen if re.search(r"(^|:)Building$", x, re.I)] or [x for x in namen if re.search(r"building|gebaeude|gebäude", x, re.I)]
        typ = wahl[0] if wahl else "bldg:Building"
        log("    Feature-Typ: %s%s" % (typ, "" if wahl else " (geraten - GetCapabilities nannte keinen)"))
        teil["typ"] = typ                                            # fuer die weiteren Kacheln merken
    g = int(teil["kachel"])
    crs = "urn:ogc:def:crs:EPSG::%d" % epsg
    q = {"SERVICE": "WFS", "VERSION": teil.get("version", "2.0.0"), "REQUEST": "GetFeature", "TYPENAMES": typ, "TYPENAME": typ,
         "SRSNAME": crs, "BBOX": "%d,%d,%d,%d,%s" % (e, n, e + g, n + g, crs)}
    url = basis + ("&" if "?" in basis else "?") + urllib.parse.urlencode(q, safe=":,")
    tmp = ziel + ".teil"
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ZachariasTools/0.1 (+https://github.com/ZirkelZacharias/zacharias-tools)"})
        with urllib.request.urlopen(req, timeout=300, context=ctx) as r, open(tmp, "wb") as f:
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
        with open(tmp, "rb") as f:
            kopf = f.read(4000).decode("utf-8", errors="replace")
        if re.search(r"ExceptionReport|ServiceException", kopf):
            log("    WFS meldet einen Fehler: %s" % re.sub(r"\s+", " ", kopf)[:300])
            os.remove(tmp)
            return False
        os.replace(tmp, ziel)
    except Exception as ex:
        if os.path.exists(tmp):
            os.remove(tmp)
        log("    FEHLER bei %s: %s" % (basis, ex))
        return False
    log("  geladen: %s (%.1f MB, %.0f s)" % (os.path.basename(ziel), os.path.getsize(ziel) / 1e6, time.time() - t0))
    return True


def kacheln_holen(cfg, land, bbox, log, K, dgm=True, lod2=True, dom=False):
    """Holt die Kacheln des Landes `land` fuer bbox. -> (dgm_dateien, lod2_dateien, fehlend_texte)
    Bereits geholte Kacheln liegen im Zwischenspeicher (~/.ifcmap/cache). Mit dom=True werden zusaetzlich die
    Oberflaechenmodell-Dateien geholt und in _DOM_LETZTE abgelegt."""
    _DOM_LETZTE.clear()
    prof = profile(log).get(land)
    if not prof:
        log("  Kein Laenderprofil fuer '%s' (system/laender.json)." % land)
        return [], [], []
    ctx = K.ssl_kontext(cfg.cafile, cfg.unsicher)
    cache = K.cache_ordner()
    epsg = int(prof.get("epsg") or cfg.epsg)
    dgm_out, lod_out, fehlt = [], [], []
    listen = {}
    for art, an in (("dgm", dgm), ("lod2", lod2), ("dom", dom)):
        teil = prof.get(art)
        if not an or not teil:
            continue
        tilename = {"dgm": "Gelaende (DGM)", "lod2": "Gebaeude (LoD2)", "dom": "Oberflaechenmodell (DOM)"}[art]
        log("%s %s - Status: %s" % (prof.get("name", land), tilename, teil.get("status", "?")))
        kach = kachel_liste(bbox, teil.get("kachel", 1000))
        if teil.get("art") == "manuell" or not (teil.get("url") or teil.get("basis")):
            fehlt.append("%s %s: kein automatischer Download. Benoetigte Kacheln (%d x %d m, linke untere Ecke %s): %s. Portal: %s"
                         % (prof.get("name", land), tilename, teil.get("kachel", 1000), teil.get("kachel", 1000), "Ost/Nord in m",
                            ", ".join("%d/%d" % k for k in kach), prof.get("portal", "")))
            if art == "lod2" and getattr(cfg, "lod2_luecken", False):
                log("  Fuer %s gibt es keinen automatischen LoD2-Download - die Gebaeude kommen stattdessen aus OpenStreetMap "
                    "(eigene LoD2-Dateien lassen sich weiterhin unter 'Eigene Dateien' hinzufuegen; Portal: %s)." % (prof.get("name", land), prof.get("portal", "")))
            else:
                log("  " + fehlt[-1])
            continue
        log("  %d Kachel(n) noetig" % len(kach))
        for e, n in kach:
            v = _vars(e, n, epsg)
            ext = teil.get("ext", "gml" if art == "lod2" else "zip")
            ziel = os.path.join(cache, "%s_%s_%d_%d_%d.%s" % (land, art, e, n, int(teil.get("kachel", 1000)), ext))
            try:
                if teil.get("art") == "wfs":
                    if os.path.exists(ziel) and os.path.getsize(ziel) > 0:
                        log("  (aus Zwischenspeicher) %s" % os.path.basename(ziel))
                        ok = True
                    else:
                        ok = _wfs_kachel_holen(teil, land, e, n, epsg, ctx, ziel, log, K)
                    adresse = teil["basis"]
                else:
                    adresse = None
                    if teil.get("liste") and teil.get("muster"):
                        adresse = _name_in_liste(teil, v, ctx, cache, log, listen)
                        if adresse == "nicht_in_liste":
                            log("  Kachel %d/%d steht nicht in der Dateiliste (Gebiet ohne Daten?)" % (e // 1000, n // 1000))
                            fehlt.append("%s %s: Kachel %d/%d nicht beim Dienst" % (prof.get("name", land), tilename, e // 1000, n // 1000))
                            continue
                    if not adresse:
                        adresse = _fuellen(teil["url"], v)
                    if adresse.lower().endswith(".zip") and ext != "zip":
                        ziel = ziel[:-len(ext)] + "zip"
                    ok = K._datei_laden(adresse, ziel, ctx, log)
                    if not ok:
                        log("  Kachel %d/%d nicht vorhanden (404): %s" % (e // 1000, n // 1000, adresse))
                if not ok:
                    fehlt.append("%s %s: Kachel %d/%d konnte nicht geladen werden (%s)" % (prof.get("name", land), tilename, e // 1000, n // 1000, adresse))
                    continue
                if art in ("dgm", "dom"):
                    dat = _dgm_dateien_aus(ziel, cache)
                    if not dat:
                        log("  %s enthaelt keine lesbare Hoehendatei" % os.path.basename(ziel))
                        fehlt.append("%s: %s ohne lesbare Hoehendatei" % (prof.get("name", land), os.path.basename(ziel)))
                    if art == "dgm":
                        dgm_out += dat
                    else:
                        _DOM_LETZTE.extend(dat)
                else:
                    lod_out.append(ziel)
            except Exception as ex:
                if "CERTIFICATE" in str(ex).upper():
                    log("  SSL-Problem: %s -> unter 'Erweitert' CA-Datei angeben oder 'truststore' installieren" % ex)
                    break
                log("  FEHLER bei Kachel %d/%d: %s" % (e // 1000, n // 1000, ex))
                fehlt.append("%s %s: Kachel %d/%d (%s)" % (prof.get("name", land), tilename, e // 1000, n // 1000, ex))
    if [f for f in fehlt if not ("LoD2" in f and getattr(cfg, "lod2_luecken", False) and "kein automatischer Download" in f)]:
        log("Hinweis: Fehlende Kacheln bitte von Hand laden (Portal: %s) und unter 'Eigene Dateien' hinzufuegen." % prof.get("portal", ""))
    return dgm_out, lod_out, fehlt


def kacheln_vorschau(cfg, land, bbox):
    """Fuer die Oberflaeche: Text, welche Kacheln das Rechteck braucht. -> (Zeilen, Profil-Name oder None)"""
    prof = profile().get(land)
    if not prof:
        return [], None
    z = []
    for art, nm in (("dgm", "Gelaende"), ("lod2", "Gebaeude")):
        t = prof.get(art)
        if t:
            z.append("%s: %d Kachel(n) a %d m, %s" % (nm, len(kachel_liste(bbox, t.get("kachel", 1000))), t.get("kachel", 1000),
                                                    "automatisch" if t.get("art") != "manuell" else "von Hand laden"))
    return z, prof.get("name")
