"""Projektmodell von Zacharias Tools.

Ein Projekt ist EINE Datei (``<Name>.architools.json``) in einem Projektordner. Darin steht, was am Ende
gewünscht ist (``ausgaben``), die gemeinsamen Gebietsangaben, die Einstellungen je Ausgabe und der ``stand``:
welche Ausgaben schon erzeugt wurden. So lässt sich ein Projekt später öffnen, um weitere Dateien auszugeben.
"""
import copy
import dataclasses
import datetime
import json
import os
import re
import sys

from .modell import config as MC

VERSION = 1
ENDUNG = ".architools.json"
ZULETZT = os.path.join(os.path.expanduser("~"), ".architools", "zuletzt.json")
STANDARD_MITTE = (393676.0, 5826540.0)          # Betriebswerk Pankow (EPSG:25833)

# Ausgaben: Schlüssel -> (Titel, Symbol, Farbe, Beschreibung, Gruppe, Unterordner)
AUSGABEN = {
    "ifc": ("Archicad-Umgebungs-IFC", "domain", "#1f6f78",
            "Gelände, Gebäude, Straßen, Bäume – als IFC für Archicad.", "umgebung", "umgebung"),
    "lageplan": ("Lageplan (DXF/DWG)", "map", "#3d6a9e",
                 "Fertiger 2D-Lageplan mit Gehwegen, Bäumen, Schatten.", "umgebung", "umgebung"),
    "schwarzplan": ("Schwarzplan (DXF/DWG)", "location_city", "#18232e",
                    "Figur-Grund-Plan: Gebäude schwarz auf weiß.", "umgebung", "umgebung"),
    "info_dwg": ("Informations-DWG", "layers", "#5f8f6b",
                 "Alle Geodaten als Ebenen in einer 2D-Zeichnung (Nutzung, Flurstücke, Höhen …).", "umgebung", "umgebung"),
    "druck": ("Gebäude für das Modell", "view_in_ar", "#7fb3c4",
              "Gebäude als 3D-Druck (STL) oder als Laserteile: Stapelmodell, Klebeflächen, Faltmodell.", "modell", "modell/druck"),
    "laser": ("Gelände Lasercut", "grid_view", "#d19a2b",
              "Geländeschichten als Laser-PDFs, Montageplan, Steckrippen.", "modell", "modell/laser"),
    "schnitt": ("Geländeschnitt", "show_chart", "#c8643b",
                "Schnitt durch Gelände und Gebäude – oder Straßen-/Fassadenabwicklung entlang einer Linie (DXF/SVG).", "sonstige", "schnitt"),
    "hoehenlinien": ("Höhenlinien (DXF/DWG)", "terrain", "#8a5a2b",
                     "Schichtlinien aus dem Geländemodell mit Höhenkoten – eigene Zeichnung.", "sonstige", "hoehenlinien"),
}
GRUPPEN = {"umgebung": "Umgebung (IFCmap-Kern)", "modell": "Modellbau", "sonstige": "Weitere Werkzeuge"}

# Felder der Umgebungs-Konfiguration, die NICHT in der Oberfläche/Projektdatei stehen, sondern aus dem Projekt abgeleitet werden
_ABGELEITET = {"latlon", "mitte_en", "ausgabe", "ifc", "dxf2d", "dxf_plaene", "test", "test_groesse", "e0n0", "z0",
               "mit_gelaende", "xyz"}

SCHNITT_STANDARD = {
    "art": "schnitt",                 # "schnitt" = Geländeschnitt; "abwicklung" = Straßen-/Fassadenabwicklung (Linie mit mehreren Punkten)
    "linie_en": None,                 # [[Ost, Nord], [Ost, Nord]] oder None = quer durch die Mitte
    "richtung_grad": 0.0,             # nur wenn linie_en None: Richtung der Schnittlinie (0 = Ost-West)
    "laenge_m": 200.0,
    "massstab": 500,
    "abstand_m": 0.5,                 # Rasterabstand entlang der Linie
    "gebaeude": True,
    "ansicht": True,                  # Gebäude und Bäume HINTER der Schnittlinie als Ansicht zeigen
    "tiefe_m": 100.0,                 # so weit hinter der Linie
    "seite": "links",                 # Blickseite: "links" oder "rechts" der Linie (Abwicklung auch "beide")
    "baeume": True,                   # Bäume markieren (dunkelgrün = von der Linie getroffen, hellgrün = dahinter)
    "format": ["dxf"],
}


HOEHENLINIEN_STANDARD = {
    "aequidistanz_m": 1.0, "haupt_alle": 5, "beschriften": True, "glaetten": True, "massstab": 500, "z_null": None,
    "min_laenge_m": 4.0,
}


def jetzt():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def sicher(name):
    s = re.sub(r"[^\w\-. äöüÄÖÜß]", "_", str(name or "Projekt")).strip(" .")
    return s or "Projekt"


def kern():
    from .modell.ifcmap_adapter import kern as _k
    return _k()


def umgebung_standard():
    """Alle Einstellungen des Rechenkerns (K.Config) mit Vorgaben – außer den aus dem Projekt abgeleiteten."""
    K = kern()
    out = {}
    for f in dataclasses.fields(K.Config):
        if f.name in _ABGELEITET:
            continue
        if f.default is not dataclasses.MISSING:
            out[f.name] = f.default
        elif f.default_factory is not dataclasses.MISSING:           # type: ignore[misc]
            out[f.name] = f.default_factory()
        else:
            out[f.name] = None
    out["epsg"] = 25833
    out["markant"] = False                 # Markante Gebäude: experimentell, Standard aus
    out["buergersteige"] = "keine"         # Bürgersteige: Standard aus
    return out


def zusatz_gemeinsam(p):
    """Zusatzmodule: ein gemeinsamer Bereich „gemeinsam“ in den Umgebungs- und den Modellbau-Einstellungen (dasselbe Objekt, wie beim
    Gebiet), z. B. für die Liste eigener Fassadenfotos, die für IFC und Modell gilt. Nach dem Laden (zwei gespeicherte Kopien) neu verknüpft."""
    uz = p["umgebung"].setdefault("zusatz", {})
    gz = p["modell"].setdefault("gebaeude", {}).setdefault("zusatz", {})
    gem = uz.get("gemeinsam") or gz.get("gemeinsam") or {}
    uz["gemeinsam"] = gem
    gz["gemeinsam"] = gem
    return gem


def neues_projekt(name="Neues Projekt", ordner=None):
    modell = MC.default_config()
    ordner = ordner or os.path.join(os.path.expanduser("~"), "ArchItools", sicher(name))
    p = {
        "version": VERSION, "name": name, "ordner": ordner,
        "ausgaben": {k: False for k in AUSGABEN},
        "stand": {},                                          # Schlüssel -> {"zeit", "dateien", "ordner"}
        "gebiet": {"mitte_en": list(STANDARD_MITTE), "drehung_grad": 0.0,
                   "breite_cm": modell["gebiet"]["breite_cm"], "hoehe_cm": modell["gebiet"]["hoehe_cm"]},
        "umgebung": umgebung_standard(),
        "modell": modell,
        "schnitt": copy.deepcopy(SCHNITT_STANDARD),
        "hoehenlinien": copy.deepcopy(HOEHENLINIEN_STANDARD),
        "notizen": "",
        "formate": {"zweid": ["dxf"], "dreid": ["ifc"]},
        "ziel": {"ordner": "", "name": ""},                   # Ausgabe: selbst gewählter Ordner + selbst benannter Unterordner
    }
    p["umgebung"].update(breite=900.0, hoehe=900.0, nah_breite=600.0, nah_hoehe=600.0)
    p["modell"]["gebiet"] = p["gebiet"]                       # gemeinsam benutzt (gleiches Objekt)
    p["modell"]["quelle"] = "auto"
    p["modell"].setdefault("werkzeuge", {})
    zusatz_gemeinsam(p)
    return p


def verbinden(p):
    """Nach Laden/Ändern: Querverbindungen herstellen (gemeinsames Gebiet, Pflichtschlüssel)."""
    base = neues_projekt(p.get("name", "Projekt"), p.get("ordner"))
    for k in ("ausgaben", "gebiet", "umgebung", "schnitt", "hoehenlinien"):
        merged = base[k]
        merged.update(p.get(k) or {})
        p[k] = merged
    m = MC.default_config()
    MC.deep_update(m, p.get("modell") or {})
    p["modell"] = m
    p["formate"] = {**base["formate"], **(p.get("formate") or {})}
    for k in ("stand", "notizen", "version", "name", "ordner", "ziel"):
        p.setdefault(k, base[k])
    p["modell"]["gebiet"] = p["gebiet"]
    p["modell"]["projekt_name"] = sicher(p["name"])
    zusatz_gemeinsam(p)
    return p


def laden(pfad):
    with open(pfad, encoding="utf-8") as f:
        p = json.load(f)
    p = verbinden(p)
    p["_pfad"] = os.path.abspath(pfad)
    p["ordner"] = os.path.dirname(p["_pfad"])               # Projekt zieht mit dem Ordner um
    return p


def speichern(p, pfad=None):
    pfad = pfad or p.get("_pfad") or os.path.join(p["ordner"], sicher(p["name"]) + ENDUNG)
    os.makedirs(os.path.dirname(os.path.abspath(pfad)), exist_ok=True)
    data = {k: v for k, v in p.items() if not k.startswith("_")}
    m = {k: v for k, v in p["modell"].items() if not k.startswith("_") and k != "gebiet"}
    data["modell"] = m
    data["version"] = VERSION
    tmp = pfad + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False, default=_json)
    os.replace(tmp, pfad)
    p["_pfad"] = os.path.abspath(pfad)
    merken(p["_pfad"])
    return p["_pfad"]


def _json(o):
    if isinstance(o, (set, tuple)):
        return list(o)
    try:
        import numpy as np
        if isinstance(o, np.generic):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
    except Exception:
        pass
    return str(o)


def merken(pfad):
    try:
        os.makedirs(os.path.dirname(ZULETZT), exist_ok=True)
        try:
            with open(ZULETZT, encoding="utf-8") as f:
                liste = json.load(f).get("liste", [])
        except Exception:
            liste = []
        liste = [pfad] + [x for x in liste if x != pfad and os.path.exists(x)]
        with open(ZULETZT, "w", encoding="utf-8") as f:
            json.dump({"liste": liste[:12]}, f)
    except OSError:
        pass


def zuletzt():
    try:
        with open(ZULETZT, encoding="utf-8") as f:
            return [x for x in json.load(f).get("liste", []) if os.path.exists(x)]
    except Exception:
        return []


# ------------------------------------------------------------------ Abfragen
def gewaehlt(p, gruppe=None):
    return [k for k, v in AUSGABEN.items() if p["ausgaben"].get(k) and (gruppe is None or v[4] == gruppe)]


def ausgabe_basis(p):
    """Ordner, in den der Export am Ende schreibt: <selbst gewählter Ordner>/<selbst gewählter Name>;
    ohne Wahl: <Projektordner>/ausgabe."""
    z = p.get("ziel") or {}
    ordner = (z.get("ordner") or "").strip().strip('"')
    if not ordner:
        return os.path.join(p["ordner"], "ausgabe")
    name = sicher((z.get("name") or "").strip() or p.get("name") or "Ausgabe")
    return os.path.join(ordner, name)


def ausgabe_ordner(p, key=None):
    basis = ausgabe_basis(p)
    return os.path.join(basis, AUSGABEN[key][5]) if key else basis


def stand_setzen(p, key, dateien, ordner=None):
    p["stand"][key] = {"zeit": jetzt(), "dateien": [os.path.relpath(x, p["ordner"]) if os.path.isabs(x) and x.startswith(p["ordner"]) else x
                                                      for x in dateien][:200],
                       "ordner": ordner or ausgabe_ordner(p, key)}


def stand_text(p, key):
    s = p["stand"].get(key)
    return f"erzeugt {s['zeit']}" if s else "noch nicht erzeugt"


# ------------------------------------------------------------------ Umgebung -> K.Config
def umgebung_config(p, ausgaben=None, test=False):
    """Baut die Konfiguration des Rechenkerns für die gewählten Umgebungs-Ausgaben."""
    K = kern()
    ausgaben = [a for a in (ausgaben or gewaehlt(p, "umgebung")) if AUSGABEN[a][4] == "umgebung"]
    u = dict(p["umgebung"])
    felder = {f.name for f in dataclasses.fields(K.Config)}
    kw = {k: v for k, v in u.items() if k in felder and k not in _ABGELEITET}
    for k in ("breite", "hoehe", "nah_breite", "nah_hoehe", "mittel_breite", "mittel_hoehe"):
        kw[k] = float(u.get(k) or 0)
    e, n = p["gebiet"]["mitte_en"]
    plaene = [a for a in ("lageplan", "schwarzplan") if a in ausgaben]
    kw.update(mitte_en=(float(e), float(n)), latlon=None, ifc="ifc" in ausgaben, dxf2d="info_dwg" in ausgaben,
              dxf_plaene=plaene, test=bool(test), xyz=False,
              # Gelände nur laden, wenn IFC oder Informations-DWG es brauchen (Pläne kommen ohne aus - schneller)
              mit_gelaende=("ifc" in ausgaben or "info_dwg" in ausgaben),
              ausgabe=os.path.join(ausgabe_basis(p), "umgebung"))
    kw["sonne"] = bool(u.get("sonne"))
    return K.Config(**kw)


def aus_ifcmap(p, pfad):
    """Alte IFCmap-Projektdatei (.ifcmap.json) in dieses Projekt übernehmen (Einstellungen + Mittelpunkt)."""
    from .modell import ifcmap_adapter as A
    K = kern()
    data = A.projekt_lesen(pfad)
    kc = A.config_aus_projekt(K, data)
    felder = dataclasses.asdict(kc)
    # Nur, was config_aus_projekt sicher aus den GUI-Beschriftungen der alten Datei zurückübersetzt
    for k in ("epsg", "breite", "hoehe", "nah_breite", "nah_hoehe", "mittel_breite", "mittel_hoehe", "online_dgm",
              "online_lod2", "land", "quelle", "fern_gebaeude", "dgm", "lod2", "nutzung_dateien", "baum_dateien",
              "cafile", "unsicher", "eingabe_crs", "lod2_luecken", "overrides", "baeume_nur_nah"):
        if k in felder and k in p["umgebung"]:
            p["umgebung"][k] = felder[k]
    try:
        k = A.kartendaten({"ifcmap": {"projekt": pfad}})
        p["gebiet"]["mitte_en"] = list(k["mitte_en"])
        p["umgebung"]["epsg"] = k["epsg"]
    except Exception:
        pass
    return p
