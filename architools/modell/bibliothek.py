"""Material-, Laser- und Drucker-Bibliothek.

Voreinstellungen: Werkstatt-Laser (80 x 50 cm, 60 x 30 cm), Prusa MK4 der Werkstatt und
gängige Modellbau-Materialien mit ihren üblichen Stärken (nur innerhalb der Werkstatt-Grenzen). Eigene Einträge liegen in ~/.architools/bibliothek.json und werden
mit den Voreinstellungen zusammengeführt.
"""
import copy
import json
import os

BENUTZER_DATEI = os.path.join(os.path.expanduser("~"), ".architools", "bibliothek.json")

LASER = {
    "Werkstatt-Laser 80 × 50 cm": {"bett_mm": [800, 500]},
    "Werkstatt-Laser 60 × 30 cm": {"bett_mm": [600, 300]},
}

# Werkstatt-Vorgaben für die Laserdatei
WERKSTATT = {
    "farbe_schneiden": (255, 0, 0),
    "farbe_ritzen": (0, 0, 255),
    "farbe_gravieren": (0, 0, 0),
    "linienstaerke_mm": 0.001,
    "min_steg_mm": 0.75,
    "rand_mm": 3.0,                  # Werkstatt: 2–4 mm Abstand zum Plattenrand
    "abstand_mm": 2.0,               # Abstand zwischen Teilen
    "nesting_raster_mm": 1.0,
    "preis_min_netto": 0.85,         # € pro Minute zzgl. MwSt. (sekundengenau, Zeit laut Ruby)
    "mwst": 0.19,
}

# Grobe Erfahrungswerte für die Zeitschätzung (CO2-Laser): Schnittgeschwindigkeit ≈ K / Stärke [mm/s]
SCHNITT_K = {"Finnpappe": 60, "Graupappe": 50, "Graukarton": 60, "Bristolkarton": 80, "MDF": 40,
             "Sperrholz": 45, "Acrylglas": 25}
RITZEN_MM_S = 150.0                 # Ritzen = schnelle Linie mit wenig Leistung
GRAVUR_S_MM2 = 0.02                 # Flächengravur (Raster): Sekunden je mm²
JE_KONTUR_S = 0.4                   # Anfahren/Absetzen je Kontur

DRUCKER = {
    "Werkstatt Prusa MK4": {"bett_mm": [240, 210], "hoehe_mm": 210, "duese_mm": 0.4},
}

FILAMENTE = {
    "PLA": {"dichte_g_cm3": 1.24},
    "PETG": {"dichte_g_cm3": 1.27},
}

# Materialien mit gängigen Stärken (mm). "max_mm" = Werkstatt-Grenze fürs Lasern.
MATERIALIEN = {
    "Finnpappe": {
        "staerken": [0.9, 1.5, 2.0, 2.5, 3.0], "max_mm": 4.0},
    "Graupappe": {
        "staerken": [1.5, 2.0], "max_mm": 2.0,
        "hinweis": "Stärke kann bis 0,2 mm abweichen – Platte messen."},
    "Graukarton": {
        "staerken": [0.5, 1.0, 1.2], "max_mm": 2.0},
    "Bristolkarton": {
        "staerken": [0.25, 0.5, 1.0], "max_mm": 2.0},
    "MDF": {
        "staerken": [1.0, 1.5, 2.0, 3.0], "max_mm": 3.0},
    "Sperrholz": {
        "staerken": [0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 2.5, 3.0], "max_mm": 3.0,
        "hinweis": "Platten dürfen sich nicht winden."},
    "Acrylglas": {
        "staerken": [1.5, 2.0, 3.0, 4.0, 5.0], "max_mm": 5.0},
}

# frühere Namen (Projektdateien v0.2)
ALTE_NAMEN = {"Finnpappe (Modulor)": "Finnpappe", "Graupappe glatt/glatt (Modulor)": "Graupappe",
              "Graukarton glatt/rau (Modulor)": "Graukarton", "Bristolkarton hochweiß (Modulor)": "Bristolkarton",
              "MDF dünn (Modulor)": "MDF", "MDF 3 mm (Modulor, Zuschnitt)": "MDF",
              "Flugzeugsperrholz Birke (Modulor)": "Sperrholz", "Acrylglas GS (Modulor, Zuschnitt)": "Acrylglas",
              "Acrylglas XT (Modulor, Zuschnitt)": "Acrylglas"}


def _lesen():
    try:
        with open(BENUTZER_DATEI, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _schreiben(data):
    os.makedirs(os.path.dirname(BENUTZER_DATEI), exist_ok=True)
    with open(BENUTZER_DATEI, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def alle(art):
    """art: "materialien" | "laser" | "drucker" -> dict Name -> Eintrag.
    Voreinstellungen + eigene Einträge; Voreinstellungen lassen sich überschreiben und löschen."""
    basis = {"materialien": MATERIALIEN, "laser": LASER, "drucker": DRUCKER}[art]
    data = _lesen()
    weg = set((data.get("geloescht") or {}).get(art, []))
    out = {k: dict(v, voreinstellung=True) for k, v in copy.deepcopy(basis).items() if k not in weg}
    for name, e in data.get(art, {}).items():
        out[name] = dict(e, eigen=True, voreinstellung=name in basis)
    return out


def speichern(art, name, eintrag, alter_name=None):
    data = _lesen()
    if alter_name and alter_name != name:
        _entfernen(data, art, alter_name)
    data.setdefault(art, {})[name] = {k: v for k, v in eintrag.items() if k not in ("eigen", "voreinstellung")}
    weg = (data.get("geloescht") or {}).get(art, [])
    if name in weg:
        weg.remove(name)
    _schreiben(data)


def _entfernen(data, art, name):
    data.get(art, {}).pop(name, None)
    basis = {"materialien": MATERIALIEN, "laser": LASER, "drucker": DRUCKER}[art]
    if name in basis:
        weg = data.setdefault("geloescht", {}).setdefault(art, [])
        if name not in weg:
            weg.append(name)


def loeschen(art, name):
    data = _lesen()
    _entfernen(data, art, name)
    _schreiben(data)


def zuruecksetzen(art):
    """Alle Voreinstellungen wiederherstellen (eigene, neue Einträge bleiben)."""
    data = _lesen()
    basis = {"materialien": MATERIALIEN, "laser": LASER, "drucker": DRUCKER}[art]
    for k in list(data.get(art, {})):
        if k in basis:
            del data[art][k]
    (data.get("geloescht") or {}).pop(art, None)
    _schreiben(data)


def plattenformate(cfg):
    """Plattenformat aus der Projekt-Einstellung: einer der Werkstatt-Laser oder ein eigenes Format.

    cfg["laser"]["format"]: Name aus LASER oder "eigen" (dann cfg["laser"]["eigenes_format_mm"] = [B, H]).
    Ein eigenes Format muss auf mindestens einen der Laser passen.
    """
    lc = cfg["laser"]
    name = lc.get("format", "Werkstatt-Laser 80 × 50 cm")
    if name == "eigen":
        w, h = map(float, lc.get("eigenes_format_mm") or [800, 500])
        w, h = max(w, h), min(w, h)
        if not any(w <= e["bett_mm"][0] and h <= e["bett_mm"][1] for e in alle("laser").values()):
            raise ValueError(f"Eigenes Format {w:.0f} × {h:.0f} mm passt auf keinen Laser")
        return [(w, h)]
    e = alle("laser").get(name)
    if not e:
        raise ValueError(f"Plattenformat „{name}“ unbekannt")
    w, h = map(float, e["bett_mm"])
    return [(max(w, h), min(w, h))]


def material(cfg):
    """(Sorte, Stärke) aus dem Projekt. Die Stärke ist die Schichtdicke des Geländes."""
    lc = cfg["laser"]
    sorte = ALTE_NAMEN.get(lc.get("material"), lc.get("material") or "Graupappe")
    st = float(lc.get("staerke_mm") or 2.0)
    mat = alle("materialien").get(sorte)
    hinweis = []
    if mat and mat.get("max_mm") and st > mat["max_mm"] + 1e-6:
        hinweis.append(f"{sorte}: {st} mm liegt über der Werkstatt-Grenze von {mat['max_mm']} mm")
    return sorte, st, hinweis


def druckbett(cfg):
    dc = cfg["druck"]
    g = dc.get("geraet", "Werkstatt Prusa MK4")
    if g == "eigen":
        return tuple(map(float, dc.get("bett_mm") or [240, 210])), float(dc.get("hoehe_mm") or 210)
    e = alle("drucker")[g]
    return tuple(map(float, e["bett_mm"])), float(e["hoehe_mm"])
