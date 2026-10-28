"""Kleine Überraschungen – bewusst unauffällig.

* „Archicad-Bildungsversion“: Stempel auf der Karte, kleiner Fußzeilen-Stempel; fünf Klicks auf den Titel zeigen das Bild.
* Das Bild liegt immer (blass) hinter dem Protokoll (CSS-Klasse log-bild).
* „Zirkel Zacharias“: eine absichtlich schlecht gerenderte 3D-Figur (kein 2D mehr) – taucht selten nach einem
  langen Lauf auf oder nach drei Klicks aufs Versionskürzel; ein Klick schickt ihn weg. Er sagt nie etwas.
* Seine platonische Freundin „Rosi Radiergummi“ (ebenfalls schlecht gerendert in 3D): nach sehr langen Läufen kommt er mit ihr
  (figuren.py).
* Bei der Formatwahl zeigt nur ein kleines Icon von ihm das für Archicad beste Format – ohne Pfeil, Text oder Tipp.
* Die 67: bei 67 % Fortschritt steht im Protokoll eine leise Zeile „· 67 ·“.
* „Sonnenbank-Flavour“ ist der Name der Sonnenbahn-Karte in den Einstellungen.
"""
import os
import random

from nicegui import ui

from .stil import BILD, WASSERZEICHEN



def maskott_pfad():
    """Zirkel Zacharias gibt es nur noch als schlecht gerenderte 3D-Figur."""
    from . import figuren
    return figuren.pfad("3d")


def maskott_zeigen(sekunden=14, art=None):
    """Zirkel Zacharias schaut kurz vorbei (3D, schlecht gerendert). art: None/'3d' allein oder 'duo' mit Rosi Radiergummi."""
    from . import figuren
    try:
        art = "duo3d" if art in ("duo", "duo3d") else "3d"
        pfad = figuren.pfad(art)
    except Exception:
        return
    breite = {"3d": 128, "duo3d": 230}[art]
    from .stil import url
    box = ui.element("div").classes("maskott").style(f"width:{breite}px")
    with box:
        ui.image(url(pfad)).style(f"width:{breite}px")
    box.on("click", lambda: box.delete())
    ui.timer(sekunden, box.delete, once=True)


def bildungsversion():
    with ui.dialog() as d, ui.card().classes("p-2"):
        ui.image("/bild/abschluss.jpg").style("width:520px")
        ui.label(WASSERZEICHEN).classes("text-caption self-center")
    d.open()


def fuss():
    """Fußzeile: kaum sichtbarer Stempel und Versionskürzel (3 Klicks = Zirkel-Zacharias)."""
    from .. import VERSION
    klicks = {"n": 0}

    def kl():
        klicks["n"] += 1
        if klicks["n"] >= 3:
            klicks["n"] = 0
            maskott_zeigen()
    ui.label(f"Zacharias Tools {VERSION}").classes("cursor-default").style(
        "position:fixed; left:68px; bottom:4px; font-size:10px; color:#9aa4ad; z-index:10").on("click", kl)


def titel_klicks():
    """Fünf Klicks auf den Titel zeigen das Bild."""
    k = {"n": 0}

    def f():
        k["n"] += 1
        if k["n"] >= 5:
            k["n"] = 0
            bildungsversion()
    return f


def log_67(logel):
    """Gibt eine Funktion für die Fortschrittsanzeige zurück: bei 67 % einmal eine leise Zeile ins Protokoll."""
    zust = {"gesehen": False}

    def f(x):
        if x < 0.05:
            zust["gesehen"] = False
        elif not zust["gesehen"] and 0.67 <= x < 0.72:
            zust["gesehen"] = True
            logel.push("                                   · 67 ·")
    return f


def lang_gelaufen(sekunden):
    """Nach einem langen Lauf schaut der Zirkel mit kleiner Wahrscheinlichkeit vorbei."""
    if sekunden > 600 and random.random() < 0.4:
        maskott_zeigen(art="duo")                                      # nach sehr langen Läufen mit Freundin
    elif sekunden > 90 and random.random() < 0.15:
        maskott_zeigen()


def icon(hoehe=40):
    """Kleines 3D-Icon von Zirkel Zacharias (durchsichtiger Hintergrund)."""
    try:
        from . import figuren
        pfad = figuren.icon()
    except Exception:
        return None
    from .stil import url
    return ui.image(url(pfad)).style(f"height:{hoehe}px; width:auto; min-width:{int(hoehe * 0.85)}px").props("fit=contain")


def zeiger():
    """Zirkel Zacharias als kleines 3D-Icon neben dem für Archicad besten Format – ohne Wort, ohne Pfeil, ohne Tipp."""
    icon(40)
