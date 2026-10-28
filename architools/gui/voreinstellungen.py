"""Voreinstellungen für die Umgebung (aus IFCmap): ein Klick stellt Ausgaben und Optionen passend ein."""
import json
import os

from nicegui import ui

from .. import projekt as P
from .einst_umgebung import GENAUIGKEIT
from .stil import AKZENT, GRAU, INK, OCKER, SALBEI, SCHIEFER, TERRA, hinweis, karte

DATEI = os.path.join(os.path.expanduser("~"), ".architools", "voreinstellungen.json")

# Alle hier genannten Schalter werden von jeder Voreinstellung gesetzt (BASIS) und einzeln überschrieben.
BASIS = dict(ifc=True, info_dwg=False, lageplan=False, schwarzplan=False, dxf_modus="eine", aufteilung="strassen",
             fern_gebaeude="bloecke", farben=True, baeume_nur_nah=True, sonne=False, markant=True, markant_dom=True,
             markant_osm=True, markant_fern=False, fern_zusammenfassen=True, schatten="aus", schatten_lageplan=True,
             schatten_schwarzplan=True, buergersteige="fgn", dach_linien=False, dach_schattierung=False, lageplan_baeume=True,
             extra=[], online_dgm=True, genauigkeit="Standard", ebenen={"ifc": {}, "dxf": {}})
VORGABEN = [
    ("Entwurf: Modell und Pläne", TERRA,
     "IFC mit Gelände, Straßen, Wegen und Gebäuden – dazu Lageplan und Schwarzplan",
     dict(lageplan=True, schwarzplan=True, ebenen={"ifc": {"Baeume": False}, "dxf": {}})),
    ("Schwarzplan", INK, "Nur ein Schwarzplan – schnell, ohne Gelände und ohne IFC",
     dict(ifc=False, schwarzplan=True, online_dgm=False, markant=False, schatten="standard")),
    ("Lageplan", AKZENT,
     "Lageplan: Bürgersteige, Grün, Wasser, Brücken, weiße Gebäude mit dünner Kontur und Bäume – ohne IFC",
     dict(ifc=False, lageplan=True, online_dgm=False, markant=False)),
    ("Massenmodell", SCHIEFER,
     "Schlanke IFC: grobes Gelände, Gebäude als Blöcke (Fernbereich zusammengefasst), ohne Bäume und Bürgersteige – klein und schnell",
     dict(genauigkeit="Schnell", aufteilung="keine", markant=False, buergersteige="keine", fern_zusammenfassen=True,
          ebenen={"ifc": {"Baeume": False}, "dxf": {}})),
    ("Standortanalyse", SALBEI, "Informations-DWG mit Zusatzdaten (ÖPNV, Gewässer, Denkmal), Lageplan und Sonnenbahn – dazu die IFC",
     dict(info_dwg=True, lageplan=True, sonne=True, extra=["oepnv", "gewaesser", "denkmal"])),
    ("Präsentation: alles", OCKER, "Feines Gelände, markante Gebäude (experimentell), Bäume, Sonnenbahn und alle Pläne",
     dict(genauigkeit="Fein", info_dwg=True, lageplan=True, schwarzplan=True, sonne=True, aufteilung="verkehr_wasser",
          schatten="standard", dach_linien=True, dach_schattierung=True)),
]
AUSGABEN_SCHLUESSEL = ("ifc", "info_dwg", "lageplan", "schwarzplan")


def eigene():
    try:
        with open(DATEI, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def sammeln(p):
    u, a = p["umgebung"], p["ausgaben"]
    w = {k: bool(a.get(k)) for k in AUSGABEN_SCHLUESSEL}
    for k in BASIS:
        if k in AUSGABEN_SCHLUESSEL or k == "genauigkeit":
            continue
        v = u.get(k)
        w[k] = json.loads(json.dumps(v)) if isinstance(v, (dict, list)) else v
    cur = (float(u.get("toleranz") or 0), float(u.get("toleranz_fern") or 0), float(u.get("uebergang") or 0), float(u.get("fern_raster") or 0))
    w["genauigkeit"] = next((n for n, v in GENAUIGKEIT.items() if cur == tuple(map(float, v))), "Eigene Werte")
    return w


def anwenden(p, werte):
    w = json.loads(json.dumps(BASIS))
    w.update(json.loads(json.dumps(werte)))
    u, a = p["umgebung"], p["ausgaben"]
    for k in AUSGABEN_SCHLUESSEL:
        a[k] = bool(w[k])
    for k, v in w.items():
        if k in AUSGABEN_SCHLUESSEL or k == "genauigkeit":
            continue
        if k in u:
            u[k] = v
    if w.get("genauigkeit") in GENAUIGKEIT:
        for key, val in zip(("toleranz", "toleranz_fern", "uebergang", "fern_raster"), GENAUIGKEIT[w["genauigkeit"]]):
            u[key] = val
    u["ebenen"] = {"ifc": dict((w.get("ebenen") or {}).get("ifc") or {}), "dxf": dict((w.get("ebenen") or {}).get("dxf") or {})}


def karte_zeigen(p, neu_laden):
    """Karte „Voreinstellungen“ (oben auf der Einstellungs-Seite)."""
    state = {"aktiv": None}
    with karte("Voreinstellungen (Umgebung)", TERRA, offen=False) as k:
        hinweis("Ein Klick stellt die Ausgaben und Optionen der Umgebung passend ein. Danach kannst du alles weiter unten noch ändern.")
        gitter = ui.grid(columns=2).classes("w-full gap-2")
        lbl = hinweis("Keine Voreinstellung gewählt.")

        def waehlen(name, werte):
            anwenden(p, werte)
            state["aktiv"] = (name, sammeln(p))
            lbl.text = f"Aktiv: {name} – Seite neu laden, um alle Felder aktuell zu sehen …"
            neu_laden()

        def zeichnen():
            gitter.clear()
            with gitter:
                for name, farbe, text, werte in VORGABEN:
                    with ui.card().classes("cursor-pointer").style(f"border-left:5px solid {farbe}").on(
                            "click", lambda n=name, w=werte: waehlen(n, w)):
                        ui.label(name).classes("text-subtitle2")
                        ui.label(text).classes("text-caption").style(f"color:{GRAU}")
                for name, werte in eigene().items():
                    with ui.card().classes("cursor-pointer").style(f"border-left:5px solid {SCHIEFER}").on(
                            "click", lambda n=name, w=werte: waehlen(n, w)):
                        with ui.row().classes("items-center w-full no-wrap"):
                            ui.label(name).classes("text-subtitle2 grow")
                            ui.button(icon="delete", on_click=lambda n=name: loeschen(n)).props("flat dense round size=sm") \
                                .on("click.stop", lambda: None)
                        ui.label("eigene Voreinstellung").classes("text-caption").style(f"color:{GRAU}")

        def loeschen(name):
            alle = eigene()
            alle.pop(name, None)
            _schreiben(alle)
            zeichnen()

        def speichern():
            name = (eingabe.value or "").strip()[:40]
            if not name:
                ui.notify("Bitte einen Namen eingeben.", type="warning")
                return
            alle = eigene()
            alle[name] = sammeln(p)
            _schreiben(alle)
            eingabe.value = ""
            ui.notify(f"Voreinstellung „{name}“ gespeichert", type="positive")
            zeichnen()
        with ui.row().classes("items-end gap-2"):
            eingabe = ui.input("Aktuelle Einstellung speichern als …").classes("w-64")
            ui.button("Speichern", icon="save", on_click=speichern).props("flat dense")
        zeichnen()
    return k


def _schreiben(alle):
    os.makedirs(os.path.dirname(DATEI), exist_ok=True)
    with open(DATEI, "w", encoding="utf-8") as f:
        json.dump(alle, f, ensure_ascii=False, indent=1)
