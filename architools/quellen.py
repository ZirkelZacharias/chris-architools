"""Quellenvermerke: Wird bei jedem Export als QUELLEN.txt in den Ausgabeordner geschrieben (Namensnennung nach den Datenlizenzen)."""
import os

TEXT = """QUELLEN UND LIZENZEN DER DATEN (zum Export gehörig)
====================================================
Je nach Einstellung nutzt Zacharias Tools folgende Datenquellen. Die Liste enthält alles, was geladen werden kann; im Bericht
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

# Für den Reiter „Quellen“ in der Oberfläche: (Gruppe, [(Name, wofür, Anbieter/Adresse, Lizenz/Vermerk, Link)])
LISTE = [
    ("Berlin – amtliche Daten (Geoportal Berlin, Senatsverwaltung für Stadtentwicklung, Bauen und Wohnen)", [
        ("Digitales Geländemodell DGM1", "Gelände (IFC, Lasercut, Schnitt, Höhenlinien)", "gdi.berlin.de (ATOM-Download)",
         "Datenlizenz Deutschland – Zero 2.0 (keine Namensnennung nötig)", "https://www.govdata.de/dl-de/zero-2-0"),
        ("3D-Gebäudemodelle LoD2", "Gebäude mit Dachformen", "gdi.berlin.de (ATOM-Download)",
         "Datenlizenz Deutschland – Zero 2.0", "https://www.govdata.de/dl-de/zero-2-0"),
        ("ALKIS (Flurstücke, Gebäude, Bauwerke, tatsächliche Nutzung)", "Nutzungsflächen, Flurstücke, Lückenfüller für Gebäude", "gdi.berlin.de (WFS)",
         "Datenlizenz Deutschland – Zero 2.0", "https://www.govdata.de/dl-de/zero-2-0"),
        ("Baumbestand (Straßenbäume, Anlagenbäume)", "Bäume mit Krone und Höhe", "gdi.berlin.de (WFS)",
         "Straßenbäume: Zero 2.0 · Anlagenbäume (Grün Berlin GmbH): Namensnennung, dl-de/by-2-0", "https://www.govdata.de/dl-de/by-2-0"),
        ("Fußgängernetz und Radverkehrsnetz", "Gehwege und Radwege", "gdi.berlin.de (WFS)", "Datenlizenz Deutschland – Zero 2.0",
         "https://www.govdata.de/dl-de/zero-2-0"),
        ("Denkmalkarte, Berlin um 1900, Umweltatlas (Vegetations-/Gebäudehöhen u. a.)", "Zusatzebenen, Höhen für Gebäude und Bäume ohne Angabe",
         "gdi.berlin.de (WFS/WMS)", "je Datensatz Zero 2.0 oder Namensnennung 2.0 – siehe QUELLEN.txt", "https://daten.berlin.de"),
        ("Luftbilder und Karte von Berlin 1:5000 (K5)", "Kartenbilder als Hintergrund / Rastergravur", "gdi.berlin.de (WMS)",
         "Luftbild Zero 2.0 · K5 mit Namensnennung: „Geoportal Berlin / Karte von Berlin 1:5000 (K5 SW-Ausgabe)“", "https://www.govdata.de/dl-de/by-2-0"),
    ]),
    ("OpenStreetMap", [
        ("OpenStreetMap über die Overpass-API", "Gebäude- und Straßenergänzungen, Gleise, Brücken, Hausnummern, Straßennamen; Notlösung ohne amtliche Daten",
         "overpass-api.de, overpass.kumi.systems, overpass.private.coffee, overpass.openstreetmap.fr",
         "© OpenStreetMap-Mitwirkende, ODbL 1.0 – bei veröffentlichten Plänen angeben", "https://www.openstreetmap.org/copyright"),
    ]),
    ("Gelände außerhalb amtlicher Daten", [
        ("Copernicus-Geländemodell GLO-30", "nur wenn kein amtliches Gelände vorliegt", "copernicus-dem-30m.s3.amazonaws.com",
         "Contains modified Copernicus DEM data (GLO-30), European Union / ESA", "https://spacedata.copernicus.eu"),
    ]),
    ("Andere Bundesländer (optionale Länder-Module, Vermerke nicht einzeln geprüft)", [
        ("Brandenburg", "Gelände, Gebäude", "data.geobasis-bb.de", "© GeoBasis-DE/LGB, dl-de/by-2-0", "https://geobasis-bb.de"),
        ("Hamburg", "Gelände, Gebäude", "geodienste.hamburg.de", "Freie und Hansestadt Hamburg, Landesbetrieb Geoinformation und Vermessung, dl-de/by-2-0",
         "https://suche.transparenz.hamburg.de"),
        ("Nordrhein-Westfalen", "Gelände, Gebäude", "opengeodata.nrw.de", "Geobasis NRW, dl-de/zero-2-0", "https://www.opengeodata.nrw.de"),
        ("Bayern", "Gelände, Gebäude", "download1.bayernwolke.de", "Bayerische Vermessungsverwaltung, www.geodaten.bayern.de, CC BY 4.0",
         "https://geodaten.bayern.de"),
    ]),
    ("Programm selbst", [
        ("GitHub", "Prüfung auf Programm-Updates", "api.github.com", "es werden keine Projektdaten übertragen", "https://github.com/ZirkelZacharias"),
    ]),
]


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
