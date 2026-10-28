"""Quellenvermerke: Wird bei jedem Export als QUELLEN.txt in den Ausgabeordner geschrieben (Namensnennung nach den Datenlizenzen)."""
import os

TEXT = """QUELLEN UND LIZENZEN DER DATEN (zum Export gehörig)
====================================================
Je nach Einstellung nutzt Zacharias Tools folgende Datenquellen. Die Liste enthält alles, was geladen werden kann; im Protokoll
(bericht.txt) steht, was in diesem Lauf tatsächlich verwendet wurde. Für Pläne, Berichte, Arbeiten bitte die zutreffenden Vermerke übernehmen.

BERLIN (Geoportal Berlin / Senatsverwaltung für Stadtentwicklung, Bauen und Wohnen)
  Ohne Namensnennungspflicht (Datenlizenz Deutschland - Zero - Version 2.0, https://www.govdata.de/dl-de/zero-2-0):
    Digitales Geländemodell DGM1 · 3D-Gebäudemodelle LoD2 · ALKIS Berlin (Flurstücke, Gebäude, Bauwerke, tatsächliche Nutzung)
    Baumbestand Berlin (Straßenbäume und Anlagenbäume, soweit die Zero-Lizenz im Katalog steht) · Fußgängernetz · Radverkehrsnetz
    Denkmalkarte (Schutzgebiete INSPIRE, Denkmale) · Berlin um 1900 (AISBer) · Umweltatlas Vegetationshöhen 2020
    Luftbilder (DOP20RGBI u. a.)
  Mit Namensnennung (Datenlizenz Deutschland - Namensnennung - Version 2.0, https://www.govdata.de/dl-de/by-2-0):
    Karte von Berlin 1:5000 (K5):  "Geoportal Berlin / Karte von Berlin 1:5000 (K5 SW-Ausgabe)"
    Baumbestand in den Liegenschaften der Grün Berlin GmbH (Anlagenbäume):  "Grün Berlin GmbH / Baumbestand in den Liegenschaften der Grün Berlin GmbH (Anlagenbäume)"
  Hinweis: Die Katalogeinträge des Geoportals wurden am 28.10.2026 geprüft; Lizenzen können sich ändern. Empfehlung für Pläne:
    "Datengrundlage: Geoportal Berlin, Datenlizenz Deutschland (Zero bzw. Namensnennung 2.0)".

OPENSTREETMAP (Gebäude- und Straßenergänzungen, Gleise, Brücken, Hausnummern, Straßennamen, Notlösung ohne amtliche Daten)
  "© OpenStreetMap-Mitwirkende", Open Database License (ODbL) 1.0, https://www.openstreetmap.org/copyright
  Bitte bei veröffentlichten Plänen angeben. Abgeleitete Datenbanken (z. B. eine Sammlung der Rohdaten) unterliegen Share-Alike.

COPERNICUS-GELÄNDEMODELL (nur wenn kein amtliches Gelände vorliegt)
  "Contains modified Copernicus DEM data (GLO-30), European Union / ESA".

ANDERE BUNDESLÄNDER (nur bei den optionalen Länder-Modulen; Vermerke aus den veröffentlichten Lizenzen, nicht einzeln geprüft)
  Brandenburg: "© GeoBasis-DE/LGB, dl-de/by-2-0"          Hamburg: "Freie und Hansestadt Hamburg, Landesbetrieb Geoinformation und Vermessung, dl-de/by-2-0"
  Nordrhein-Westfalen: "Geobasis NRW, dl-de/zero-2-0"        Bayern: "Bayerische Vermessungsverwaltung, www.geodaten.bayern.de, CC BY 4.0"

Eigene Dateien (Zusatzpläne, eigene Geodaten) unterliegen den Rechten der jeweiligen Urheber.
"""


def schreiben(ordner):
    """-> Pfad der QUELLEN.txt (Fehler werden verschluckt: der Vermerk darf nie einen Export verhindern)"""
    try:
        os.makedirs(ordner, exist_ok=True)
        pfad = os.path.join(ordner, "QUELLEN.txt")
        with open(pfad, "w", encoding="utf-8") as f:
            f.write(TEXT)
        return pfad
    except OSError:
        return None
