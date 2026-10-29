"""Programmweite Einstellungen (nicht an ein Projekt gebunden)."""
import json
import os

PFAD = os.path.join(os.path.expanduser("~"), ".architools", "einstellungen.json")
STANDARD = {
    "dwg_erzeugen": False,          # DXF zusätzlich als DWG schreiben (braucht den ODA File Converter)
    "oda_pfad": "",                 # leer = automatisch suchen
    "projektordner": os.path.join(os.path.expanduser("~"), "ArchItools"),
    "update_pruefen": True,         # beim Start nach einem neueren Build suchen (nur Hinweis, nichts wird installiert)
    "update_ignoriert": 0,          # dieser Build wurde mit „nicht mehr erinnern“ zurückgestellt
    "spielereien": True,          # kleine Überraschungen in der Oberfläche
}


def laden():
    e = dict(STANDARD)
    try:
        with open(PFAD, encoding="utf-8") as f:
            e.update(json.load(f))
    except Exception:
        pass
    return e


def speichern(e):
    os.makedirs(os.path.dirname(PFAD), exist_ok=True)
    with open(PFAD, "w", encoding="utf-8") as f:
        json.dump(e, f, indent=1, ensure_ascii=False)
