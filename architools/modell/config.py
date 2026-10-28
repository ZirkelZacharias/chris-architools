"""Standardwerte und Laden/Speichern der Projektkonfiguration (JSON)."""
import copy
import json

DEFAULTS = {
    "projekt_name": "Umgebungsmodell",
    "ausgabe_ordner": "ausgabe",
    "massstab": 500,                       # 1:massstab
    # Ausschnitt in EPSG:25833 (Meter). Alternativ eine Polygon-Datei (z. B. Kreis oder Freiform).
    "ausschnitt": {"xmin": 0.0, "ymin": 0.0, "xmax": 0.0, "ymax": 0.0},
    "ausschnitt_datei": "",

    "dgm": {
        "datei": "",                       # GeoTIFF / ASC / XYZ – Datei oder Ordner mit Kacheln
        "glaettung_m": 1.5,                # Glättung des Rohgeländes gegen DGM-Rauschen
    },

    "quelle": "auto",                      # "auto" (aus Koordinaten, Berlin lädt alles selbst), "ifcmap", "dateien"
    "gebiet": {"mitte_en": [393676.0, 5826540.0], "breite_cm": 80.0, "hoehe_cm": 50.0, "drehung_grad": 0.0},
    "netz": {"cafile": "", "unsicher": False},   # bei SSL-Problemen (Uni-Netz): CA-Datei angeben
    "ifcmap": {
        "rahmen": "karte",                 # "karte" = Rahmen aus Modellgröße (cm) und Maßstab, "ifcmap" = Gebiet des Projekts
        "projekt": "",                     # Pfad zur .ifcmap.json
        "ordner": "",                      # IFCmap-Programmordner (leer = neben diesem Programm suchen)
        "ebenen": {},                      # Nutzungsart/Ebene -> {"aktion": ..., "breite_m": ..., "punkt_d_mm": ...}
        "zusatz": [],                      # zusätzlich holen: "oepnv", "gewaesser", "denkmal", "fnp"
    },

    # Projektgrundstück als herausnehmbarer Einsatz (eigene Platten, mehrere Exemplare möglich)
    "einsatz": {
        "aktiv": False,
        "flurstuecke_datei": "",           # Flurstücke (z. B. ALKIS) – gewählt wird das unter dem Mittelpunkt
        "layer": "",
        "mitte": None,                     # [Ost, Nord]; None = Mitte des Ausschnitts
        "spiel_mm": 0.4,                   # Luft zwischen Einsatz und Aussparung (gesamt)
        "exemplare": 1,                    # so oft wird der Schichtstapel des Einsatzes gelasert
        "gebaeude": "drucken",             # "drucken" | "umriss" (nur Umriss ritzen, z. B. für Entwürfe)
        "bauweise": "",                    # leer = wie das Gelände; sonst "voll" | "steckrippen" | "stuetzkloetze"
        "auswahl": "mitte",                # "mitte" = Flurstück unter dem Mittelpunkt, "eigen" = gewählte Flurstücke/Polygon
        "polygone_en": [],                 # eigene Auswahl: Liste von Ringen [[Ost, Nord], ...] (EPSG:25833)
    },

    "gelaende": {
        "ueberhoehung": 1.0,               # 1.0 = maßstäblich, 2.0 = doppelt so hoch
        "basis_hoehe_m": None,             # None = automatisch (unterste Geländehöhe)
        "min_breite_mm": 3.0,              # schmalere Stege/Zipfel werden entfernt
        "min_flaeche_mm2": 30.0,           # kleinere Inseln/Löcher werden entfernt
        "bauweise": "voll",                # "voll" | "steckrippen" | "stuetzkloetze"
        "auflage_rand_mm": 12.0,
        "min_hohl_mm": 8.0,                # Hohlraum erst ab dieser Tiefe (flachere Stellen bleiben voll)           # Ringbreite unter der Kante der nächsten Schicht
        "rippen_abstand_mm": 80.0,         # Raster der Steckrippen bzw. Stützklötze
        "stuetze_mm": 15.0,                # Kantenlänge der Stützklötze
        "unterste_schicht_voll": True,     # Grundplatte immer voll
        "passloecher": True,               # Löcher für Passstifte/Zahnstocher
        "passloch_d_mm": 3.0,
        "passloch_abstand_mm": 160.0,
        "beschriftung_hoehe_mm": 4.0,
        "gebaeude_aussparen": True,        # Gebäude auf höheren Schichten aussparen, damit sie eben stehen
    },

    # Was auf den Geländeplatten passiert: "ritzen" (blau), "gravieren" (schwarze Fläche),
    # "schneiden" (rot), "aus"
    "ebenen": {
        "Anlegekante nächste Schicht": "ritzen",
        "Gebäudeumrisse": "ritzen",
        "Gebäudenummern": "gravieren",
        "Teile-IDs": "gravieren",
        "Rippen-/Klotzmarken": "ritzen",
    },

    "laser": {
        "format": "Werkstatt-Laser 80 × 50 cm",   # oder "Werkstatt-Laser 60 × 30 cm" oder "eigen"
        "eigenes_format_mm": [694, 422],
        "material": "Graupappe",
        "staerke_mm": 2.0,                 # Nennstärke = Schichtdicke
        "staerke_gemessen_mm": None,       # gemessene Stärke (Messschieber) – hat Vorrang
        "rand_mm": 3.0,                    # Werkstatt: 2–4 mm
        "abstand_mm": 2.0,                 # Abstand zwischen Teilen
        "nesting_raster_mm": 1.0,          # kleiner = dichter, aber langsamer
        "drehungen": [0, 90, 180, 270],
        "ringe_teilen": True,              # lange dünne Ringteile in Stücke teilen (packt dichter)
        "teilstueck_mm": 250.0,
        "ausgabe_dxf": False,              # zusätzlich DXF (z. B. zur Kontrolle in ArchiCAD)
        # Restplatten: werden zuerst belegt; was darauf nicht passt, kommt auf das gewählte Format.
        # [{"name": "Rest 1", "b_mm": 400, "h_mm": 300, "anzahl": 1}, ...]  (gleiches Material und gleiche Stärke)
        "restplatten": [],
    },

    # Rastergravur (EXPERIMENTELL): Bild als Linienraster (schwarze Streifen) auf die Geländeschichten.
    "raster_bild": {
        "aktiv": False,
        "quelle": "luftbild",              # WMS-Schlüssel (luftbild, luftbild_1998, k5 ...) oder "datei"
        "datei": "",                       # Bilddatei (GeoTIFF mit Georeferenz oder JPG/PNG auf den Ausschnitt gestreckt)
        "weite_mm": 0.5,                   # Zeilenabstand; kleiner = feiner, aber mehr Objekte und längere Laserzeit
        "kontrast": 1.0,
        "helligkeit": 0.0,                 # -1 … +1; positiv = heller
        "teststreifen": True,              # 100 × 100 mm Probestück in drei Stufen mitlasern
    },

    # Holz: Rahmenleisten ums Modell und Grundpodest (nur Zuschnittliste und Zeichnung, kein Laser)
    "holz": {
        "rahmen": {
            "aktiv": False,
            "breite_mm": 20.0,             # Breite der Leiste von oben gesehen
            "hoehe_mm": None,              # Höhe der Leiste; None = Höhe des Geländestapels
            "gehrung": True,               # Ecken auf Gehrung (45°); sonst stumpf
        },
        "podest": {
            "aktiv": False,
            "hoehe_mm": 80.0,              # Gesamthöhe des Podests (Oberkante Deckplatte)
            "deckplatte_mm": 12.0,         # Stärke der Deckplatte
            "ueberstand_mm": 20.0,         # Deckplatte steht so weit über das Modell (bzw. den Rahmen) hinaus
            "rahmenholz_breite_mm": 12.0,  # Stärke der Rahmenbretter
            "stuetz_abstand_mm": 300.0,    # Stützrahmen im Unterbau höchstens in diesem Abstand
        },
    },

    # Markierungen aus eigenen Dateien. aktion: "ritzen", "gravieren", "schneiden", "aus"
    "markierungen": [
        # {"name": "Straßen", "datei": "", "layer": "", "aktion": "ritzen", "breite_m": 0.0, "punkt_d_mm": 1.5}
    ],

    "gebaeude": {
        "citygml": [],                     # LoD2 CityGML Dateien oder Ordner
        "grundriss_datei": "",             # alternativ/zusätzlich: Grundrisse (z. B. ALKIS) als Blöcke
        "grundriss_layer": "",
        "hoehe_feld": "",                  # Attribut mit Gebäudehöhe in m
        "standard_hoehe_m": 9.0,
        "nahzone_mitte": None,             # [x, y] EPSG:25833; None = Mitte des Ausschnitts
        "nahzone_radius_m": None,          # None = alle Gebäude mit LoD2-Dächern; sonst außerhalb Blöcke
        "min_breite_mm": 1.2,              # Prusa MK4, 0,4er Düse: unter 1,2 mm nicht sinnvoll
        "min_hoehe_mm": 1.0,
        "zu_klein": "gravieren",           # "gravieren" (nur auf Platte) oder "verstaerken"
        "platzhalter_ids": [],             # gml:id – nur Umriss gravieren (z. B. eigener Entwurf)
        "separat_ids": [],                 # gml:id – eigene Druckplatten (z. B. Ensemble als Einsatz)
        "beschriften": True,               # Gebäudenummer auf die Platte gravieren
        "teile_beschriften": True,         # Laserformen: Teilenummer auf jedes Teil gravieren
        "fenstermuster": False,            # Flächen/Faltmodell: Fenster und Türen als gravierte Rechtecke - ein MUSTER nach Wandmaßen, KEINE Messung
        "beschriftung_hoehe_mm": 2.5,
        # Wie werden die Gebäude gebaut?  "druck" = 3D-Druck (STL), "stapel" = Stapelmodell aus Laserplatten,
        # "flaeche" = ebene Wand-/Dachflächen zum Kleben (ohne Laschen), "falt" = Faltmodell (Abwicklung mit Laschen)
        "modus": "druck",
        "material": "",                    # Laser-Material der Gebäudeteile; leer = wie das Gelände
        "staerke_mm": None,                # Stärke dazu; None = wie das Gelände (bei anderem Material Pflicht)
        "lasche_mm": 3.0,                  # Breite der Klebelaschen (nur Faltmodell)
        "stifte": False,                   # 3D-Druck: Löcher für Steckstifte unter den Gebäuden und im Gelände
        "stift_d_mm": 2.0,                 # Ø des Stifts (Draht, Rundholz, Zahnstocher)
        "stift_laenge_mm": 4.0,            # so tief stecken die Stifte (je Seite die Hälfte, mind. 2 mm)
        "stift_spiel_mm": 0.2,             # Luft im Loch (Durchmesser + Spiel)
        "stift_abstand_mm": 40.0,          # ab dieser Gebäudegröße mehrere Stifte (Abstand)
    },

    # Weitere Bauwerke (Brücken, Mauern, Bahnsteige ...) als Extrusion
    "bauwerke": [
        # {"name": "Bahnsteige", "datei": "", "layer": "", "hoehe_feld": "", "hoehe_m": 0.8, "breite_m": 0.0}
    ],

    "druck": {
        "geraet": "Werkstatt Prusa MK4",   # oder "eigen" (dann bett_mm, hoehe_mm)
        "bett_mm": [240, 210],
        "hoehe_mm": 210,
        "filament": "PLA",
        "rand_mm": 5.0,
        "abstand_mm": 3.0,
        "nesting_raster_mm": 1.0,
        "drehschritt_grad": 90,
        "fuellgrad_effektiv": 0.35,        # grobe Schätzung Wände + Infill
    },
}


def deep_update(base, upd):
    for k, v in upd.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_update(base[k], v)
        else:
            base[k] = v
    return base


def default_config():
    return copy.deepcopy(DEFAULTS)


def load(path):
    import os
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    cfg = deep_update(default_config(), data)
    _migrieren(cfg, data)
    cfg["_basis"] = os.path.dirname(os.path.abspath(path))
    return cfg


def resolve_paths(cfg):
    """Relative Pfade gelten relativ zur Projektdatei."""
    import os
    base = cfg.get("_basis") or os.getcwd()

    def rp(p):
        return p if not p or os.path.isabs(p) else os.path.normpath(os.path.join(base, p))

    cfg["ausgabe_ordner"] = rp(cfg["ausgabe_ordner"])
    cfg["ausschnitt_datei"] = rp(cfg.get("ausschnitt_datei", ""))
    cfg["dgm"]["datei"] = rp(cfg["dgm"]["datei"])
    g = cfg["gebaeude"]
    g["citygml"] = [rp(x) for x in g.get("citygml") or []]
    g["grundriss_datei"] = rp(g.get("grundriss_datei", ""))
    cfg["einsatz"]["flurstuecke_datei"] = rp(cfg["einsatz"].get("flurstuecke_datei", ""))
    cfg["ifcmap"]["projekt"] = rp(cfg["ifcmap"].get("projekt", ""))
    for lst in ("markierungen", "bauwerke"):
        for m in cfg.get(lst, []):
            m["datei"] = rp(m.get("datei", ""))
    return cfg


def save(cfg, path):
    data = {k: v for k, v in cfg.items() if not k.startswith("_")}
    data["_version"] = 2
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _migrieren(cfg, data):
    """Ältere Projektdateien (v0.1) übernehmen."""
    if "quelle" not in data and (data.get("dgm", {}).get("datei") or data.get("ausschnitt_datei")):
        cfg["quelle"] = "dateien"
    a = data.get("ausschnitt")
    if "gebiet" not in data and a and a.get("xmax", 0) > a.get("xmin", 0):
        s = float(cfg.get("massstab") or 500)
        cfg["gebiet"] = {"mitte_en": [(a["xmin"] + a["xmax"]) / 2, (a["ymin"] + a["ymax"]) / 2],
                         "breite_cm": round((a["xmax"] - a["xmin"]) * 100 / s, 1),
                         "hoehe_cm": round((a["ymax"] - a["ymin"]) * 100 / s, 1)}
    g = data.get("gelaende", {})
    if "hohlbau" in g and "bauweise" not in g:
        cfg["gelaende"]["bauweise"] = {"ringe": "stuetzkloetze", True: "stuetzkloetze",
                                       "gitter": "steckrippen"}.get(g["hohlbau"], "voll")
    if "schichtdicke_mm" in g and "staerke_mm" not in data.get("laser", {}):
        cfg["laser"]["staerke_mm"] = g["schichtdicke_mm"]
    lz = data.get("laser", {})
    from .bibliothek import ALTE_NAMEN
    cfg["laser"]["material"] = ALTE_NAMEN.get(cfg["laser"].get("material"), cfg["laser"].get("material"))
    if "plattenformate_mm" in lz and "format" not in lz:
        w, h = lz["plattenformate_mm"][0]
        cfg["laser"]["format"] = "eigen"
        cfg["laser"]["eigenes_format_mm"] = [w, h]
    for m in cfg.get("markierungen", []):
        if m.get("aktion") == "gravieren" and data.get("_version") is None:
            m["aktion"] = "ritzen"               # früher hieß Linien-Gravur „gravieren“
    if data.get("druck", {}).get("bett_mm") and "geraet" not in data.get("druck", {}):
        cfg["druck"]["geraet"] = "eigen"
