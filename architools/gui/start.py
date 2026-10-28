"""Startseite: Projekt und Auswahl, was am Ende herauskommen soll."""
import os

from nicegui import ui

from .. import projekt as P
from . import zustand as Z
from .stil import AKZENT, GRAU, HOEHE, INK, LINIE, feld_pfad, hinweis, karte, waehlen


def seite(wechsel, neu_laden):
    p = Z.projekt()
    kacheln = {}

    with ui.scroll_area().style(f"height:{HOEHE}"):
        with ui.column().classes("w-full gap-4 pr-3").style("max-width:1180px; margin:0 auto"):
            # ---------------- Projekt
            with ui.card().classes("w-full"):
                ui.label("Projekt").classes("text-h6")
                with ui.row().classes("w-full items-end gap-3 no-wrap"):
                    ui.input("Name des Projekts").bind_value(p, "name").classes("w-72")
                    ui.input("Projektordner").bind_value(p, "ordner").classes("grow")

                    async def ordner_waehlen():
                        r = await waehlen("ordner")
                        if r:
                            p["ordner"] = os.path.join(r, P.sicher(p["name"]))
                            neu_laden(p, nur_feld=True)
                    ui.button(icon="folder_open", on_click=ordner_waehlen).props("flat dense round").tooltip("Ordner wählen")
                lbl = hinweis("")

                def zeige_pfad():
                    ziel = os.path.join(p["ordner"], P.sicher(p["name"]) + P.ENDUNG)
                    lbl.text = ("Projektdatei: " + ziel + ("  ·  vorhanden" if os.path.exists(ziel) else "  ·  wird beim Speichern angelegt"))
                ui.timer(0.8, zeige_pfad)
                with ui.row().classes("gap-2"):
                    def speichern():
                        try:
                            f = Z.speichern(p)
                            ui.notify(f"Gespeichert: {f}", type="positive")
                        except Exception as e:
                            ui.notify(f"Speichern nicht möglich: {e}", type="negative")
                    ui.button("Speichern", icon="save", on_click=speichern).props("unelevated").style(f"background:{AKZENT}!important")

                    async def oeffnen():
                        r = await waehlen("datei", typen=("ArchItools-Projekt (*.architools.json)",))
                        if r:
                            try:
                                Z.oeffnen(r)
                                ui.navigate.reload()
                            except Exception as e:
                                ui.notify(f"Projekt nicht lesbar: {e}", type="negative")
                    ui.button("Projekt öffnen …", icon="folder_open", on_click=oeffnen).props("outline")

                    def neu():
                        Z.neu()
                        ui.navigate.reload()
                    ui.button("Neues Projekt", icon="add", on_click=neu).props("outline")

                    async def altes():
                        r = await waehlen("datei", typen=("IFCmap-Projekt (*.ifcmap.json;*.json)",))
                        if r:
                            try:
                                P.aus_ifcmap(p, r)
                                ui.notify("IFCmap-Einstellungen übernommen (Mittelpunkt, Größe, Daten, Quelle).", type="positive")
                                ui.navigate.reload()
                            except Exception as e:
                                ui.notify(f"Nicht lesbar: {e}", type="negative")
                    ui.button("Altes IFCmap-Projekt übernehmen …", icon="history", on_click=altes).props("flat")
                zl = [x for x in P.zuletzt() if x != p.get("_pfad")][:5]
                if zl:
                    hinweis("Zuletzt geöffnet:")
                    with ui.row().classes("gap-1"):
                        for x in zl:
                            def go(x=x):
                                try:
                                    Z.oeffnen(x)
                                    ui.navigate.reload()
                                except Exception as e:
                                    ui.notify(f"Nicht lesbar: {e}", type="negative")
                            ui.chip(os.path.basename(x).replace(P.ENDUNG, ""), icon="description", on_click=go).props("dense outline clickable")

            # ---------------- Ausgaben
            ui.label("Was soll am Ende herauskommen?").classes("text-h5").style("font-family: Georgia, serif")
            hinweis("Alles anklicken, was du für dieses Projekt brauchst. Du kannst auf einmal alles exportieren oder nur einzelne "
                    "Dateien – und das Projekt später wieder öffnen, um weitere auszugeben.")
            zaehler = ui.label("").classes("text-body2").style(f"color:{AKZENT}")

            def aktualisieren():
                n = len(P.gewaehlt(p))
                zaehler.text = f"{n} Ausgabe{'n' if n != 1 else ''} gewählt" if n else "noch nichts gewählt"
                for k, (card, haken, stand) in kacheln.items():
                    an = bool(p["ausgaben"].get(k))
                    if an:
                        card.classes(add="an")
                    else:
                        card.classes(remove="an")
                    haken.name = "check_box" if an else "check_box_outline_blank"
                    stand.text = P.stand_text(p, k)

            for gruppe, gtitel in P.GRUPPEN.items():
                eintraege = [(k, v) for k, v in P.AUSGABEN.items() if v[4] == gruppe]
                ui.label(gtitel).classes("text-subtitle1 text-weight-medium").style(f"color:{INK}")
                with ui.grid(columns=3).classes("w-full gap-3"):
                    for k, (titel, icon, farbe, text, _g, _o) in eintraege:
                        card = ui.card().classes("ausgabe-kachel").style(f"--kachel:{farbe}")
                        with card:
                            with ui.row().classes("items-center no-wrap gap-2 w-full"):
                                ui.icon(icon).style(f"color:{AKZENT}; font-size:30px")
                                ui.label(titel).classes("text-subtitle1 text-weight-medium grow")
                                haken = ui.icon("check_box_outline_blank").style(f"color:{AKZENT}; font-size:26px")
                            ui.label(text).classes("text-body2").style(f"color:{GRAU}")
                            stand = ui.label("").classes("text-caption").style(f"color:{GRAU}")

                        def klick(k=k):
                            p["ausgaben"][k] = not p["ausgaben"].get(k)
                            aktualisieren()
                        card.on("click", klick)
                        kacheln[k] = (card, haken, stand)
            aktualisieren()
            ui.timer(2.0, aktualisieren)
            with ui.row().classes("w-full justify-end"):
                ui.button("Weiter: Gebiet festlegen", icon="arrow_forward", on_click=lambda: wechsel("gebiet")) \
                    .props("unelevated size=lg").style(f"background:{AKZENT}!important")
