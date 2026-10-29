"""Reiter „Quellen“: alle Datenquellen, aus denen sich das Programm Daten holt – mit Zweck, Adresse und Lizenzvermerk."""
from nicegui import ui

from .. import quellen
from .stil import GRAU, LINIE, hinweis, karte


def seite():
    ui.label("Quellen").classes("text-h5")
    hinweis("Alle Stellen, von denen Zacharias Tools Daten holt. Welche davon in einem Lauf wirklich benutzt wurden, steht im bericht.txt; "
            "die Vermerke zum Übernehmen in Pläne und Arbeiten liegen als QUELLEN.txt im Ausgabeordner.")
    for gruppe, eintraege in quellen.LISTE:
        with karte(gruppe, GRAU, offen=True):
            for name, zweck, wo, lizenz, link in eintraege:
                with ui.column().classes("w-full gap-0").style(f"padding:6px 0; border-bottom:1px solid {LINIE}"):
                    ui.label(name).classes("text-weight-medium")
                    ui.label(zweck).style(f"color:{GRAU}; font-size:13px")
                    ui.label("Adresse: " + wo).style(f"color:{GRAU}; font-size:12px")
                    with ui.row().classes("items-center gap-2"):
                        ui.label("Lizenz / Vermerk: " + lizenz).style("font-size:13px")
                        ui.link("Lizenz", link, new_tab=True).style("font-size:12px")
    hinweis("Eigene Dateien (Zusatzpläne, eigene Geodaten) unterliegen den Rechten der jeweiligen Urheber. Lizenzen können sich ändern; "
            "Stand der Prüfung: 28.10.2026.")
