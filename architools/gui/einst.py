"""Seite „Einstellungen“: je gewählter Ausgabe die passenden Karten."""
from nicegui import ui

from .. import projekt as P
from . import einst_umgebung, voreinstellungen, eier
from .. import einstellungen as ES
from .. import formate as FM
from .einst_modell import ModellEinst
from .stil import AKZENT, GRAU, HOEHE, INK, MASSSTAEBE, SCHIEFER, TERRA, hinweis, karte


_dwg_updates = []


def _format_gruppe(titel, tabelle, liste, empfohlen, brauche_oda=False):
    """Mehrfach-Auswahl der Formate. Ein kleines Icon von Zirkel Zacharias (ohne ein Wort) markiert die für Archicad beste Wahl."""
    from .. import dwg, dwg_direkt
    oda = dwg.finden(ES.laden().get("oda_pfad", ""))
    ui.label(titel).classes("text-subtitle2")
    with ui.row().classes("gap-5 items-center"):
        for key, (name, text) in tabelle.items():
            def umschalten(e, key=key):
                if e.value and key not in liste:
                    liste.append(key)
                elif not e.value and key in liste:
                    liste.remove(key)
                for u in _dwg_updates:
                    u()
            with ui.row().classes("items-center no-wrap gap-1"):
                cb = ui.checkbox(name, value=key in liste, on_change=umschalten).tooltip(text)
                if key == empfohlen:
                    eier.zeiger()
    dwg_hinweis = hinweis("") if brauche_oda else None

    def dwg_text(_=None):
        if dwg_hinweis is None:
            return
        dwg_hinweis.text = "" if "dwg" not in liste else "DWG: " + (
            "ODA File Converter gefunden – volle Farben." if oda else
            "kein ODA File Converter – das Programm schreibt die DWG selbst (R2000, Farben auf AutoCAD-Standardfarben gerundet, "
            "keine Transparenz)." if dwg_direkt.verfuegbar() else
            "weder ODA File Converter noch eingebautes DWG-Modul – es bleibt bei DXF.")
    dwg_text()
    _dwg_updates.append(dwg_text)
    hinweis("Mehrere möglich. Mit der Maus über einem Format steht, was es kann.")


def formate_karte(p):
    f = p["formate"]
    ausg = p["ausgaben"]
    with ui.column().classes("w-full") as wurzel:
        with karte("Dateiformate", INK):
            z = ui.column().classes("w-full gap-1")
            with z:
                _format_gruppe("2D-Zeichnungen (Lageplan, Schwarzplan, Informations-DWG)", FM.FORMATE_2D, f["zweid"], FM.EMPFEHLUNG_2D, brauche_oda=True)
            d = ui.column().classes("w-full gap-1")
            with d:
                ui.separator()
                _format_gruppe("3D-Modell der Umgebung", FM.FORMATE_3D, f["dreid"], FM.EMPFEHLUNG_3D)
            warn = ui.label("").classes("text-caption").style("color:#b00020")

            def pruefen():
                z.set_visibility(bool(ausg.get("lageplan") or ausg.get("schwarzplan") or ausg.get("info_dwg")))
                d.set_visibility(bool(ausg.get("ifc")))
                bad = (not f["zweid"] and z.visible) or (not f["dreid"] and d.visible)
                warn.text = "Bitte mindestens ein Format wählen – sonst gibt es keine Datei." if bad else ""
            ui.timer(0.5, pruefen)
    wurzel.set_visibility(True)
    return wurzel


def schnitt_karte(p):
    s = p["schnitt"]
    with ui.column().classes("w-full") as wurzel:
        with karte("Geländeschnitt", TERRA):
            with ui.row().classes("gap-2 items-end"):
                ui.select(MASSSTAEBE, label="Maßstab", new_value_mode="add-unique", with_input=True) \
                    .bind_value(s, "massstab").classes("w-32")
                ui.number("Abstand m", step=0.1, min=0.1).bind_value(s, "abstand_m").classes("w-28") \
                    .tooltip("Rasterabstand entlang der Linie")
            ui.checkbox("Gebäude im Schnitt zeigen").bind_value(s, "gebaeude")
            for k, v in (("ansicht", True), ("tiefe_m", 100.0), ("seite", "links"), ("baeume", True)):
                if k not in s or (k == "tiefe_m" and not s.get(k)):
                    s[k] = v
            ui.checkbox("Dahinterliegende Gebäude als Ansicht zeigen").bind_value(s, "ansicht")
            with ui.row().classes("gap-2 items-end"):
                ui.number("Tiefe m", step=25, min=10).bind_value(s, "tiefe_m").classes("w-28") \
                    .bind_enabled_from(s, "ansicht").tooltip("So weit hinter der Schnittlinie werden Gebäude und Bäume gezeichnet")
                ui.select({"links": "links der Linie", "rechts": "rechts der Linie"}, label="Blick nach") \
                    .bind_value(s, "seite").classes("w-44").bind_enabled_from(s, "ansicht") \
                    .tooltip("Richtung der Linie: erster → zweiter Punkt")
            ui.checkbox("Bäume markieren (dunkelgrün im Schnitt, hellgrün dahinter)").bind_value(s, "baeume") \
                .bind_enabled_from(s, "ansicht")
            ui.select({"dxf": "DXF (empfohlen)", "dwg": "DWG", "pdf": "PDF", "svg": "SVG"}, multiple=True, label="Formate") \
                .bind_value(s, "format").classes("w-64")
            lbl = hinweis("")

            def text():
                if s.get("linie_en"):
                    (a, b), (c, d) = s["linie_en"]
                    lbl.text = f"Linie: ({a:.0f}, {b:.0f}) → ({c:.0f}, {d:.0f}) – gesetzt in der Karte"
                else:
                    lbl.text = "Noch keine Linie gesetzt: dann quer durch die Mitte (Richtung/Länge unten)."
            ui.timer(1.0, text)
            with ui.row().classes("gap-2 items-end"):
                ui.number("Richtung ° (0 = Ost–West)", step=15).bind_value(s, "richtung_grad").classes("w-52") \
                    .bind_enabled_from(s, "linie_en", backward=lambda v: not v)
                ui.number("Länge m", step=50, min=20).bind_value(s, "laenge_m").classes("w-28") \
                    .bind_enabled_from(s, "linie_en", backward=lambda v: not v)
                ui.button("Linie zurücksetzen", icon="restart_alt", on_click=lambda: s.__setitem__("linie_en", None)).props("flat dense")
            hinweis("Eigene Linie: Seite „Gebiet“ → Karte → „Schnittlinie“ wählen und zwei Punkte anklicken.")
    return wurzel


def seite(p):
    ausg = p["ausgaben"]
    with ui.scroll_area().style(f"height:{HOEHE}"):
        with ui.column().classes("w-full gap-3 pr-3").style("max-width:960px; margin:0 auto"):
            leer = ui.card().classes("w-full")
            with leer:
                ui.label("Noch nichts gewählt").classes("text-subtitle1")
                hinweis("Wähle auf der Startseite aus, was am Ende herauskommen soll – hier erscheinen dann die passenden Einstellungen.")
            voreinstellungen.karte_zeigen(p, ui.navigate.reload)
            formate_karte(p)
            einst_umgebung.seiten(p)
            ModellEinst(p).seite()
            sk = schnitt_karte(p)

            def pruefen():
                leer.set_visibility(not P.gewaehlt(p))
                sk.set_visibility(bool(ausg.get("schnitt")))
            ui.timer(0.4, pruefen)
            pruefen()
