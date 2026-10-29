# -*- coding: utf-8 -*-
"""
ifcmap_kern.py - Rechenkern von IFCmap
======================================

Liest DGM1-XYZ, LoD2-CityGML (Berlin) sowie Nutzungsflaechen und Baeume (WFS oder GeoJSON)
und erzeugt in lokalen Koordinaten (Meter; lokal = Ost-E0 / Nord-N0 / Hoehe-Z0):

  ifcmap.ifc               3D: Gelaende (Netz an den Nutzungsgrenzen aufgeteilt), Gebaeude Nah (LoD2),
                          Gebaeude Fern (Bloecke bis Traufe), Baeume; mit IfcMapConversion (EPSG:25833)
  ifcmap_2d.dxf            2D-Arbeitsblaetter: Nutzungsflaechen, Gebaeudegrundrisse, Baeume
  gelaende_punkte.xyz     (optional) ausgeduennte Hoehenpunkte
  protokoll.txt           Protokoll

Die Oberflaeche (ifcmap.py) ruft nur die Funktionen dieses Moduls auf.
"""
import glob
import hashlib
import io
import datetime as dtm
import json
import threading
import math
import os
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field, replace

import numpy as np

import shapely
from shapely.geometry import box, shape
from shapely.ops import unary_union
import ezdxf
import mapbox_earcut as earcut
from scipy.interpolate import LinearNDInterpolator
from scipy.ndimage import maximum_filter
from scipy.spatial import Delaunay, cKDTree

# ----------------------------------------------------------------------------------------------
# Einstellungen / Tabellen
# ----------------------------------------------------------------------------------------------

# Nutzungsarten: (Name, Regex auf dem Nutzungstext (klein, ae/oe/ue/ss), AutoCAD-Farbnummer, RGB)
KATEGORIEN = [
    # Text wird vorher klein geschrieben und ae/oe/ue/ss-normalisiert -> Regex nur in dieser Schreibweise.
    # Deutsche ALKIS-Begriffe und OpenStreetMap-Tags (key=value) werden erkannt.
    ("Gewaesser",      r"gewaesser|wasserfl|hafenbecken|stehendes|fliess|natural=water|waterway|riverbank|landuse=(basin|reservoir)", 5, (90, 150, 220)),
    ("Bahn",           r"bahnverkehr|bahngelaende|\bbahn\b|gleis|schiene|railway=|landuse=railway",                                   8, (120, 120, 120)),
    ("Strasse",        r"strasse|fahrbahn|highway=(motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street|service|road)", 9, (170, 170, 170)),
    ("Weg_Platz",      r"\bweg\b|\bplatz\b|fussgaenger|parkplatz|\brad|highway=(footway|path|pedestrian|cycleway|track|steps|bridleway|corridor)|amenity=parking", 7, (200, 190, 170)),
    ("Wald",           r"wald|forst|natural=wood|landuse=forest",                                                                       3, (40, 110, 50)),
    ("Gehoelz",        r"gehoelz|busch|hecke|natural=scrub",                                                                            82, (90, 150, 70)),
    ("Gruen",          r"gruenland|gruenanlage|wiese|garten|friedhof|sport|freizeit|park|rasen|erholung|natural=grassland|"
                       r"landuse=(grass|meadow|recreation_ground|village_green|cemetery|allotments|greenfield|flowerbed)|leisure=", 92, (150, 200, 100)),
    ("Landwirtschaft", r"landwirtschaft|acker|weide|landuse=(farmland|farmyard|orchard|vineyard|plant_nursery)",                        2, (230, 220, 120)),
    ("Brache_Unland",  r"brach|heide|moor|unland|vegetationslos|sumpf|natural=(heath|bare_rock|sand|scree|beach|wetland)|"
                       r"landuse=(brownfield|quarry|construction)",                                                                     40, (200, 170, 120)),
    ("Siedlung",       r"wohn|gemischt|gewerbe|industrie|handel|dienstleistung|siedlung|bebaut|oeffentlich|flaeche besonderer|"
                       r"ver- und entsorgung|landuse=(residential|commercial|industrial|retail|garages|military|institutional|religious|education)", 30, (220, 190, 170)),
]
SONSTIGE = ("Sonstige", 253, (230, 230, 230))
OHNE_NUTZUNG = "Ohne_Nutzung"
KATEGORIE_NAMEN = [k[0] for k in KATEGORIEN] + [SONSTIGE[0]]
# Vorrang bei Ueberlappungen (z. B. OpenStreetMap): oben liegt vor unten; eigene Kategorien zuerst
PRIORITAET = ["Gewaesser", "Bahn", "Strasse", "Weg_Platz", "Wald", "Gehoelz", "Gruen", "Brache_Unland",
              "Landwirtschaft", "Siedlung", "Sonstige"]
AUFTEILUNG = {"strassen": {"Strasse", "Weg_Platz"},
              "verkehr_wasser": {"Strasse", "Weg_Platz", "Bahn", "Gewaesser"},
              "alle": None, "keine": set()}
# Farben in der IFC (RGB 0-255). Gelaendeteile: Name = Kategorie; Standardfarbe aus kat_info()
IFC_FARBEN = {  # ruhige, entsaettigte Palette (v2.2): helles Gelaende, graphitfarbene Fahrbahn, fast weisse Gebaeude (markante Gebaeude ebenso)
              "Strasse": (92, 96, 104), "Weg_Platz": (196, 196, 198), "Bahn": (122, 128, 140),
              "Gehweg": (214, 212, 208), "Bordstein": (160, 162, 168),
              "Gewaesser": (138, 176, 204), "Wald": (104, 134, 112), "Gehoelz": (132, 158, 120), "Gruen": (172, 194, 156),
              "Landwirtschaft": (216, 210, 174), "Brache_Unland": (208, 194, 170), "Siedlung": (226, 219, 211),
              "Gelaende": (232, 228, 220), "Ohne_Nutzung": (232, 228, 220), "Sonstige": (224, 224, 224),
              "Gebaeude_Nah": (242, 240, 236), "Gebaeude_Fern": (242, 240, 236), "Bruecke": (200, 198, 194), "Gebaeude_Markant": (242, 240, 236), "Baeume": (128, 164, 124),
              "Geschosslinie": (92, 98, 108), "Fenster": (128, 156, 178), "Tuer": (112, 92, 74)}
KBS_NAMEN = {25831: "ETRS89 / UTM zone 31N", 25832: "ETRS89 / UTM zone 32N", 25833: "ETRS89 / UTM zone 33N",
             25834: "ETRS89 / UTM zone 34N"}

BAUM_KRONE_STANDARD = 6.0
BAUM_HOEHE_STANDARD = 10.0
BAUM_STAMM_STANDARD = 0.30

ATOM_DGM = "https://gdi.berlin.de/data/dgm1/atom/"        # DGM1, 2-km-Kacheln: DGM1_<Ost km>_<Nord km>.zip
ATOM_LOD2 = "https://gdi.berlin.de/data/a_lod2/atom/"     # LoD2 CityGML, 1-km-Kacheln: LoD2_<Ost km>_<Nord km>.zip
WFS_ALKIS = "https://gdi.berlin.de/services/wfs/alkis"
WFS_BAEUME = "https://gdi.berlin.de/services/wfs/baumbestand"
WFS_NUTZUNG_TYP = "alkis:tatsaechlichenutzungflaechen"
WFS_BAUM_TYPEN = ["baumbestand:strassenbaeume", "baumbestand:anlagenbaeume"]
WFS_VEG_PUNKTE_TYP = "alkis:vegetationpunkte"
# ALKIS-Zusatzdaten fuer 2D (Name im Protokoll/DXF, Feature-Typ im WFS)
WFS_ALKIS_ZUSATZ = [("Flurstuecke", "alkis:flurstuecke"), ("Gebaeude", "alkis:gebaeudeflaechen"),
                    ("Bauwerke", "alkis:bauwerkeflaechen")]

WFS_GDI = "https://gdi.berlin.de/services/wfs/"
WFS_FGN = "https://gdi.berlin.de/services/wfs/fussgaengernetz"      # Fussgaengernetz Berlin (Linien); Feature-Typ wird per GetCapabilities gesucht
ATOM_DENKMAL = "https://gdi.berlin.de/data/ps_denkmal/atom/PS_Denkmalkarte.zip"          # INSPIRE-GML, EPSG:25833
ATOM_LAERM = "https://gdi.berlin.de/data/ua_stratlaerm_2022/atom/strat_laerm_2022_%s.zip"   # je 2 GeoTIFF: L_DEN und L_N
LAERM_ARTEN = ("gesamtlaerm", "strasse", "ubahn", "industrie", "flug")
# Zusatzdaten (nur Berlin, nur 2D-DXF): Schluessel -> (Anzeigename, DXF-Praefix, Farbe ACI)
EXTRA_KATALOG = {
    "denkmal": ("Denkmalkarte (Denkmalbereiche, Baudenkmale, Gartendenkmale, Bodendenkmale)", "Denkmal", 1),
    "fnp": ("Flaechennutzungsplan (FNP Berlin 2025)", "FNP", 5),
    "laerm": ("Strategische Laermkarte 2022", "Laerm", 6),
    "oepnv": ("OEPNV-Vorrangnetz: Strassenbahn, Bus, S-Bahn, geplante Strecken, mit Haltestellen", "OEPNV", 3),
    "gewaesser": ("Gewaessernetz (ATKIS: Fliessgewaesser, Gewaesserachsen, Standgewaesser)", "Gewaesser", 4),
    "radverkehr": ("Radverkehrsnetz Berlin (Radwege, Radfernwege, Gruene Hauptwege) - ungetestet", "Rad", 30),
}
EXTRA_NAMEN = {"denkmal": "Denkmalkarte", "fnp": "Flächennutzungsplan", "laerm": "Lärmkarte", "oepnv": "ÖPNV", "gewaesser": "Gewässernetz", "radverkehr": "Radverkehrsnetz"}
LAERM_FARBEN = {45: (255, 255, 190), 50: (255, 235, 140), 55: (255, 200, 100), 60: (250, 150, 80), 65: (230, 90, 70),
                70: (190, 40, 80), 75: (120, 30, 110), 80: (70, 20, 90)}
FNP_PALETTE = [(240, 190, 150), (250, 220, 120), (170, 210, 140), (110, 170, 110), (180, 200, 230), (210, 170, 210),
               (230, 150, 150), (200, 200, 200), (160, 190, 170), (240, 230, 160), (150, 180, 210), (220, 190, 120),
               (190, 150, 120), (140, 140, 160)]

LAYER_NAH = "Gebaeude_Nah_LoD2_Daecher"
LAYER_FERN = "Gebaeude_Fern_Bloecke_Traufe"
LAYER_MARKANT = "Gebaeude_Markant_Detail"
LAYER_GESCHOSSE = "Gebaeude_Geschosslinien"
LAYER_FENSTER = "Gebaeude_Fenstermuster"
MINTRAUFE_ANTEIL = 0.5


@dataclass
class Config:
    latlon: tuple = None            # (Breite, Laenge)  ODER
    mitte_en: tuple = None          # (Ost, Nord) im Projekt-Koordinatensystem (epsg)
    epsg: int = 25833               # 25833 = ETRS89/UTM 33N (Berlin, Brandenburg, ...), 25832 = UTM 32N (Westen/Sueden)
    land: str = "auto"              # Bundesland fuer Gelaende-/Gebaeude-Download: "auto" (nach Mittelpunkt), "berlin", "brandenburg", "nrw", "bayern", "hamburg", "keins"
    quelle: str = "auto"            # Nutzung/Baeume: "auto" (amtlich wenn vorhanden, sonst OpenStreetMap), "osm" (nur OSM), "dateien" (nur eigene Dateien); "berlin" = wie auto
    breite: float = 900.0
    hoehe: float = 900.0
    nah_breite: float = 600.0       # Nahbereich: Rechteck um den Mittelpunkt (Ost-West)
    nah_hoehe: float = 600.0        # (Nord-Sued)
    mittel_breite: float = 0.0      # Mittelbereich: optionales groesseres Rechteck um den Nahbereich (0 = keiner). Dort: Gebaeude mit Dachformen,
    mittel_hoehe: float = 0.0       # Baeume und Buergersteige wie im Nahbereich - das Gelaende bleibt aber gröber als im Nahbereich
    toleranz: float = 0.15          # Gelaende im Nahbereich: max. Abweichung des ausgeduennten Netzes vom DGM (m)
    toleranz_fern: float = 1.5      # ... ausserhalb des Nahbereichs (groeber)
    uebergang: float = 60.0         # Breite der Uebergangszone um den Nahbereich, in der die Toleranz stetig waechst (m)
    fern_raster: float = 6.0        # Fernbereich: Netzpunkte nur auf diesem Raster (m, 0 = beliebig)
    baeume_nur_nah: bool = True     # Baeume nur im Nahbereich laden und ausgeben
    fern_zusammenfassen: bool = True   # IFC: Gebaeude-Bloecke des Fernbereichs je Feld zu EINEM Element (viel schneller/kleiner in Archicad)
    fern_zelle: float = 150.0          # Kantenlaenge der Felder in m
    online_dgm: bool = True         # Berlin: fehlende DGM1-Kacheln automatisch herunterladen (ATOM-Dienst)
    online_lod2: bool = True        # Berlin: fehlende LoD2-Kacheln automatisch herunterladen
    fern_gebaeude: str = "bloecke"   # Gebaeude im Fernbereich: "bloecke" (Block bis Traufe, ~LoD1), "lod2" (voll) oder "keine"
    mit_gelaende: bool = True       # False = nur 2D laden (Vorschau): Gelaende wird weder geladen noch heruntergeladen
    dgm: list = field(default_factory=list)
    lod2: list = field(default_factory=list)
    nutzung_dateien: list = field(default_factory=list)   # GeoJSON
    baum_dateien: list = field(default_factory=list)      # GeoJSON
    cafile: str = ""
    unsicher: bool = False
    eingabe_crs: str = ""           # KBS der GeoJSON-Dateien; leer = wie Projekt
    e0n0: tuple = None
    z0: float = None
    ausgabe: str = "ergebnis"
    test: bool = False
    test_groesse: float = 150.0
    ifc: bool = True
    dxf2d: bool = True
    xyz: bool = False
    alkis_zusatz: bool = True             # nur Berlin: Flurstuecke, Gebaeude-Grundrisse, Bauwerke aus ALKIS fuer die 2D-Blaetter
    farben: bool = True                   # Oberflaechenfarben (+ Material) in der IFC
    aufteilung: str = "strassen"          # Gelaende in der IFC teilen nach: "strassen" | "verkehr_wasser" | "alle" | "keine"
    gelaende_typ: str = "geographic"      # "geographic" = IfcGeographicElement, "site" = IfcSite
    overrides: dict = field(default_factory=dict)         # Nutzungstext -> Kategorie
    extra: list = field(default_factory=list)             # Berlin-Zusatzdaten (nur 2D-DXF): "denkmal", "fnp", "laerm", "oepnv", "gewaesser"
    laerm_art: str = "gesamtlaerm"        # "gesamtlaerm" | "strasse" | "ubahn" | "industrie" | "flug"
    laerm_wert: str = "L_DEN"             # "L_DEN" (24-h-Mittel) | "L_N" (Nacht)
    geschosslinien: bool = False          # IFC: waagerechte Linien an den LoD2-Waenden fuer die Geschosse (Zahl aus LoD2/ALKIS/OSM, sonst geschaetzt)
    geschosslinien_quelle: str = "auto"   # "auto" = fehlende Zahl aus der Traufhoehe schaetzen, "daten" = nur Gebaeude mit echter Geschosszahl
    fenstermuster: bool = False           # IFC: Fenster-/Tuermuster auf den LoD2-Waenden - ein MUSTER nach Wandmassen, KEINE Messung
    zusatz: dict = field(default_factory=dict)   # Einstellungen optionaler Zusatzmodule (siehe architools/zusatz.py)
    fenstermuster_radius: float = 100.0   # nur Gebaeude bis zu diesem Abstand vom Mittelpunkt (m)
    geschosslinien_radius: float = 150.0  # nur Gebaeude bis zu diesem Abstand vom Mittelpunkt (m)
    sonne: bool = False                   # Sonnenbahn-Diagramm (IFC + DXF; je Datei ueber die Ebene "Sonne" abwaehlbar)
    sonne_radius: float = 0.0             # Radius des Diagramms in m; 0 = automatisch (40 % der kleineren Nahbereich-Seite)
    sonne_modus: str = "wende"            # "wende" = 21.6./21.3.+9./21.12.;  "monate" = der 21. jedes Monats
    dxf_modus: str = "eine"               # "eine" = eine DXF, "beides" = eine DXF + je Ebene eine Datei, "einzeln" = nur je Ebene eine Datei
    ebenen: dict = field(default_factory=dict)            # Ebenen-Auswahl: {"ifc": {Schluessel: True/False}, "dxf": {...}}; fehlt = Vorgabe
    markant: bool = True                  # Markante Gebaeude (Tuerme, Kuppeln, Hochhaeuser) besonders detailliert: DOM -> OpenStreetMap-3D -> volles LoD2
    markant_hoehe: float = 0.0            # NICHT MEHR VERWENDET (frueher Hoehenschwelle) - bleibt, damit alte Einstellungsdateien laden
    markant_fern: bool = False            # markante Gebaeude auch im Fernbereich ausformulieren (Standard: nur im Nahbereich)
    markant_denkmal: bool = True          # Denkmalkarte (Berlin amtlich, sonst OSM heritage) als Ausloeser
    markant_dach: bool = True             # ungewoehnlich komplexe LoD2-Dachform als Ausloeser
    markant_max: int = 40                 # hoechstens so viele markante Gebaeude
    lod2_luecken: bool = True             # Luecken im LoD2 (neu gebaut, fehlend) mit OSM-Gebaeuden/Dachformen und ALKIS-Grundrissen fuellen; ohne LoD2 alles aus OSM
    markant_dom: bool = True              # DOM (Laserscan-Oberflaeche) als erste Quelle fuer die Form
    markant_osm: bool = True              # OpenStreetMap-3D (building:part, roof:shape ...) als zweite Quelle
    markant_glaettung: str = "normal"      # Glaettung der DOM-Dachhaut: fein | normal | stark
    markant_quelle: str = "auto"          # Quelle der Form: auto (OSM -> LoD2) | dom_zuerst (DOM -> OSM -> LoD2) | dom | osm | lod2 (nur zum Testen; Rueckfall immer LoD2)
    markant_liste: str = ""               # eigene Liste: "Name: Breite, Laenge; Name: Ost, Nord"
    dom: list = field(default_factory=list)               # eigene DOM-Dateien (xyz, asc, tif, zip)
    dxf_plaene: list = field(default_factory=list)        # zusaetzliche fertige Plaene als eigene DXF: "lageplan", "schwarzplan"
    grundrisse_abgleich: bool = True      # 2D-Plaene: in ALKIS fehlende Grundrisse aus LoD2/OpenStreetMap ergaenzen
    zusatzplaene_aktiv: bool = False            # Zusatzplaene (PDF/Bilder, verortet) als eigene DXF ausgeben
    zusatzplaene: list = field(default_factory=list)      # Liste der Zusatzplaene (siehe ifcmap_zusatz.py)
    wms_karten: list = field(default_factory=list)        # optionale Kartenbilder (Luftbild, historische Karten, Umweltatlas), siehe ifcmap_wms.py
    wms_eigene: str = ""                                  # weitere WMS-Dienste, je Zeile: Name | Adresse | Ebene1,Ebene2
    gelaende_luftbild: bool = False                       # Gelaende mit Luftbild als Textur (IFC, 3D-Vorschau); Berlin-Dienst, braucht Internet
    luftbild_aufloesung: float = 0.5                      # Meter je Pixel des Luftbilds fuer die Textur
    wms_aufloesung: float = 0.25                          # Meter je Pixel (hoechstens 4096 Pixel Kantenlaenge)
    # --- Lageplan / Schwarzplan
    buergersteige: str = "fgn"            # Lageplan: "fgn" = Fussgaengernetz (Berlin), "naeherung" = aus der Strassenbreite (ueberall), "keine"
    gehweg_breite: float = 2.5            # Breite des Buergersteigs (m) - bei "fgn" Pufferbreite um die Mittellinie, bei "naeherung" Streifen am Strassenrand
    gehweg_auto: bool = True              # Gehwegbreite nach Strassenbreite (3 Klassen, Berliner Richtwerte); False = feste gehweg_breite
    gehweg_ueberall: bool = False         # Buergersteige auch im Fernbereich (Vorgabe: nur Nahbereich)
    hoehe_ohne_angabe: float = 2.2        # Hoehe (m) fuer Grundrisse (ALKIS/OSM) ohne jede Hoehenangabe
    ua_gebaeudehoehen: bool = True        # Berlin: Umweltatlas-Gebaeudehoehen (Firsthoehe) fuer Gebaeude ohne LoD2 (ALKIS/OSM); Standard an (amtlich vor Schaetzung), bei Ausfall faellt der Kern auf Schaetzung zurueck - ungetestet
    ua_vegetationshoehen: bool = False    # Berlin: Umweltatlas-Vegetationshoehen (Blockmittelwert) fuer Baeume ohne Hoehenangabe - ungetestet
    ua_vegetationsraster: bool = False    # Berlin: Vegetationsraster 1 m (Umweltatlas, einmalig ca. 785 MB): Baumhoehen + fehlende Baeume - ungetestet
    veg_raster_dateien: list = field(default_factory=list)    # eigene Vegetationshoehen-GeoTIFFs (Dezimeter oder wie im Umweltatlas)
    veg_mindesthoehe: float = 4.0         # Raster: erst ab dieser Hoehe (m) gilt eine Spitze als Baum
    veg_max_baeume: int = 20000           # Raster: hoechstens so viele ergaenzte Baeume (die hoechsten zuerst)
    rad_wege: bool = False                # Berlin: Radverkehrsnetz als zusaetzliche Quelle fuer Wegeflaechen (3D, DXF, Plaene) - ungetestet
    rad_breite: float = 2.5               # Breite (m) der Wegeflaeche um die Mittellinie des Radverkehrsnetzes
    osm_ergaenzen: bool = True            # amtliche Quellen zuerst, danach OpenStreetMap nur fuer das, was es amtlich nicht gibt (Baeume)
    bruecken_ifc: bool = True             # IFC: Strassen-/Wegbruecken als Fahrbahn + Platte ueber die Spannweite ziehen
    fahrbahn_absenken: float = 0.10       # IFC: Fahrbahn gegenueber Gehweg/Umgebung um so viel (m) absenken = Bordstein; 0 = aus
    schatten: str = "aus"                 # Plaene: "aus" | "standard" (6.7. um 16:17 Uhr) | "eigen" (schatten_datum + schatten_zeit)
    schatten_lageplan: bool = True        # Schatten im Lageplan (nur wirksam, wenn "schatten" nicht "aus" ist)
    schatten_schwarzplan: bool = True     # Schatten im Schwarzplan (ebenso)
    schatten_datum: str = "6.7."          # Tag.Monat
    schatten_zeit: str = "16:17"          # Ortszeit (MEZ/MESZ)
    schatten_baeume: bool = False         # Baeume werfen Schatten
    schatten_baeume_bereich: str = "nah"   # "nah" = nur im Nahbereich samt Uebergang, "alle" = ueberall, wo Baeume geladen sind
    baumschatten_lageplan: bool = True    # Baumschatten im Lageplan (nur wirksam, wenn schatten_baeume)
    baumschatten_schwarzplan: bool = True
    lp_text: bool = False                 # Lageplan: Beschriftung (Flurstuecksnummern, Hausnummern, Strassennamen, Gebaeudehoehen)
    lp_text_flurstuecke: bool = True      # (ALKIS-Flurstuecke noetig, nur Berlin)
    lp_text_hausnummern: bool = True      # (OpenStreetMap)
    lp_text_strassen: bool = True         # (OpenStreetMap)
    lp_text_hoehen: bool = True           # Traufe/First je Gebaeude aus dem LoD2
    lp_text_hoehen_art: str = "gelaende"  # "gelaende" = ueber Gelaende, "nhn" = m ue. NHN
    lp_text_massstab: int = 500           # Schrifthoehe 2,5 mm auf dem Papier in diesem Massstab
    dach_linien: bool = False             # Lageplan, Nahbereich: Firste, Grate und Kehlen als Linien
    dach_schattierung: bool = False       # Lageplan, Nahbereich: Dachflaechen nach Sonnenstand in 7 Grautoenen
    lageplan_baeume: bool = True          # Lageplan: Baumkronen als Kreise
    dgm_notfall: bool = True              # gibt es gar kein Gelaendemodell: Copernicus GLO-30 (30 m, Oberflaechenmodell) als Notbehelf laden
    sonne_marke: bool = True              # Schattenzeitpunkt im Sonnenbahn-Diagramm markieren
    sonne_monat: int = 0                  # 0 = Sonnenbahnen nach sonne_modus; 1-12 = nur EINE Bahn (21. des Monats)


class Daten:
    """Alles, was nach dem Laden fuer Vorschau und Export gebraucht wird."""
    pass


def _noop(*a, **k):
    pass


# ----------------------------------------------------------------------------------------------
# Hilfsfunktionen
# ----------------------------------------------------------------------------------------------

def umlaute(s):
    return (s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
             .replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue"))


def kat_info(name):
    for n, rx, aci, rgb in KATEGORIEN:
        if n == name:
            return aci, rgb
    if name == SONSTIGE[0]:
        return SONSTIGE[1], SONSTIGE[2]
    return 9, (205, 205, 205)


def ssl_kontext(cafile=None, unsicher=False):
    if unsicher:
        c = ssl.create_default_context()
        c.check_hostname = False
        c.verify_mode = ssl.CERT_NONE
        return c
    try:
        import truststore   # Windows-Zertifikatsspeicher
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        return ssl.create_default_context(cafile=cafile or None)


def ist_berlin(cfg):
    """Liegt der Mittelpunkt (grob) in Berlin?"""
    try:
        from pyproj import Transformer
        lo, la = Transformer.from_crs("EPSG:%d" % cfg.epsg, "EPSG:4326", always_xy=True).transform(*mitte_bestimmen(cfg))
        return 13.08 <= lo <= 13.77 and 52.33 <= la <= 52.68
    except Exception:
        return False


def cache_ordner():
    p = os.path.join(os.path.expanduser("~"), ".ifcmap", "cache")
    os.makedirs(p, exist_ok=True)
    return p


def _datei_laden(url, ziel, ctx, log):
    """Laedt url nach ziel (mit Zwischenspeicher). -> True bei Erfolg, False bei 'nicht vorhanden' (404)."""
    if os.path.exists(ziel) and os.path.getsize(ziel) > 0:
        log("  (aus Zwischenspeicher) %s" % os.path.basename(ziel))
        return True
    req = urllib.request.Request(url, headers={"User-Agent": "ZachariasTools/0.1 (+https://github.com/ZirkelZacharias/zacharias-tools)"})
    tmp = ziel + ".teil"
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120, context=ctx) as r, open(tmp, "wb") as f:
            gesamt = int(r.headers.get("Content-Length") or 0)
            n, letzte = 0, time.time()
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
                n += len(b)
                if time.time() - letzte > 5:
                    letzte = time.time()
                    log("    ... %.0f MB%s" % (n / 1e6, " von %.0f MB" % (gesamt / 1e6) if gesamt else ""))
        os.replace(tmp, ziel)
    except urllib.error.HTTPError as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        if e.code == 404:
            return False
        raise
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    log("  geladen: %s (%.1f MB, %.0f s)" % (os.path.basename(ziel), os.path.getsize(ziel) / 1e6, time.time() - t0))
    return True


def kacheln_online_holen(cfg, kp, log):
    """Laedt die fehlenden Berliner DGM1-/LoD2-Kacheln vom ATOM-Downloaddienst.
    -> (neue DGM-Dateien, neue LoD2-Zips, Liste der erfolgreich geholten Kachelnamen)"""
    ctx = ssl_kontext(cfg.cafile, cfg.unsicher)
    cache = cache_ordner()
    dgm_neu, lod_neu, geholt = [], [], []
    todo = []
    if cfg.online_dgm:
        todo += [("dgm", n) for n in kp["dgm_fehlt"]]
    if cfg.online_lod2:
        todo += [("lod", n) for n in kp["lod_fehlt"]]
    if not todo:
        return dgm_neu, lod_neu, geholt
    log("Kacheln online holen (Berliner ATOM-Downloaddienst, Zwischenspeicher: %s):" % cache)
    for art, name in todo:
        m = re.search(r"_(\d+)_(\d+)_\d+_[a-z]+$", name, re.I)
        if not m:
            continue
        e, n = m.group(1), m.group(2)
        try:
            if art == "dgm":
                zielzip = os.path.join(cache, "DGM1_%s_%s.zip" % (e, n))
                if not _datei_laden(ATOM_DGM + "DGM1_%s_%s.zip" % (e, n), zielzip, ctx, log):
                    log("  keine DGM1-Kachel %s_%s beim Dienst (ausserhalb Berlins?)" % (e, n))
                    continue
                ordner = os.path.join(cache, "DGM1_%s_%s" % (e, n))
                if not os.path.isdir(ordner):
                    with zipfile.ZipFile(zielzip) as z:
                        z.extractall(ordner)
                dat = [q for q in sorted(glob.glob(os.path.join(ordner, "**", "*"), recursive=True))
                       if q.lower().endswith((".xyz", ".txt", ".csv", ".asc", ".tif", ".tiff", ".dat"))]
                if not dat:
                    log("  DGM1_%s_%s.zip enthaelt keine lesbare Hoehendatei" % (e, n))
                    continue
                dgm_neu += dat
            else:
                zielzip = os.path.join(cache, "LoD2_%s_%s.zip" % (e, n))
                if not _datei_laden(ATOM_LOD2 + "LoD2_%s_%s.zip" % (e, n), zielzip, ctx, log):
                    log("  keine LoD2-Kachel %s_%s beim Dienst (dort keine Gebaeude?)" % (e, n))
                    continue
                lod_neu.append(zielzip)
            geholt.append(name)
        except Exception as ex:
            if isinstance(ex, ssl.SSLError) or "CERTIFICATE" in str(ex).upper():
                log("  SSL-Problem: %s -> unter 'Erweitert' CA-Datei angeben oder 'truststore' installieren" % ex)
                break
            log("  FEHLER bei %s: %s" % (name, ex))
            log("  -> Kachel von Hand laden: %s  (Download-Seite des Geoportals) und im Fenster hinzufuegen" % (ATOM_DGM if art == "dgm" else ATOM_LOD2))
    return dgm_neu, lod_neu, geholt


def ebene_an(cfg, art, schluessel, vorgabe=True):
    """Ist die Ebene `schluessel` fuer die Ausgabe `art` ("ifc" oder "dxf") eingeschaltet?
    Schluessel: Gebaeude_Nah, Gebaeude_Fern, Baeume, Rahmen, Nutzung_Grenzen, ALKIS_Flurstuecke, ALKIS_Bauwerke,
    Nutzung:<Kategorie> (DXF-Schraffur) und Gelaende:<Kategorie> (eigenes Gelaendeteil in der IFC)."""
    return bool((getattr(cfg, "ebenen", None) or {}).get(art, {}).get(schluessel, vorgabe))


def detail_masse(cfg):
    """Breite und Hoehe des Detailbereichs: Nahbereich, oder - wenn ein Mittelbereich angegeben und groesser ist - dieser.
    Im Detailbereich liegen Gebaeude mit Dachformen, Baeume und Buergersteige; das feine Gelaende gilt nur im Nahbereich."""
    b, h = float(cfg.nah_breite), float(cfg.nah_hoehe)
    mb, mh = float(getattr(cfg, "mittel_breite", 0) or 0), float(getattr(cfg, "mittel_hoehe", 0) or 0)
    if mb > 0 and mh > 0:
        return max(b, mb), max(h, mh)
    return b, h


def nah_enthaelt(cfg, d, x, y):
    """Liegt der Punkt (absolut) im Detailbereich (Nahbereich bzw. Mittelbereich) um den Mittelpunkt?"""
    b, h = detail_masse(cfg)
    return abs(x - d.ce) <= b / 2 and abs(y - d.cn) <= h / 2


def mitte_bestimmen(cfg):
    if cfg.mitte_en:
        return float(cfg.mitte_en[0]), float(cfg.mitte_en[1])
    if not cfg.latlon:
        raise ValueError("Kein Mittelpunkt angegeben.")
    from pyproj import Transformer
    return Transformer.from_crs("EPSG:4326", "EPSG:%d" % cfg.epsg, always_xy=True).transform(cfg.latlon[1], cfg.latlon[0])


def rechteck(cfg):
    ce, cn = mitte_bestimmen(cfg)
    b, h = (cfg.test_groesse, cfg.test_groesse) if cfg.test else (cfg.breite, cfg.hoehe)
    return ce, cn, ce - b / 2, ce + b / 2, cn - h / 2, cn + h / 2


# ----------------------------------------------------------------------------------------------
# Dateien erkennen + Kachelpruefung
# ----------------------------------------------------------------------------------------------

RX_DGM = re.compile(r"dgm1_33_(\d+)_(\d+)_2_be", re.I)
RX_LOD = re.compile(r"lod2_33_(\d+)_(\d+)_1_be", re.I)


def lod2_dateinamen(pfade):
    """Namen aller CityGML-Dateien in Ordnern/ZIPs (ohne sie zu lesen)."""
    out = []
    for p in pfade:
        if os.path.isdir(p):
            for q in glob.glob(os.path.join(p, "**", "*"), recursive=True):
                if q.lower().endswith((".xml", ".gml", ".zip")):
                    out += lod2_dateinamen([q])
        elif p.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(p) as z:
                    out += [n for n in z.namelist() if n.lower().endswith((".xml", ".gml"))]
            except zipfile.BadZipFile:
                out.append(os.path.basename(p) + " (defekt)")
        else:
            out.append(os.path.basename(p))
    return out


def kacheln_pruefen(cfg):
    """-> dict mit benoetigten/vorhandenen/fehlenden DGM- und LoD2-Kacheln (nur fuer das Berliner Namensschema)."""
    leer = dict(aktiv=False, dgm_need=[], lod_need=[], dgm_fehlt=[], lod_fehlt=[], dgm_unbenannt=[])
    namen = [os.path.basename(p) for p in cfg.dgm] + lod2_dateinamen(cfg.lod2)
    aktiv = cfg.epsg == 25833 and (cfg.quelle == "berlin" or any(RX_DGM.search(n) or RX_LOD.search(n) for n in namen)
                                   or ((cfg.online_dgm or cfg.online_lod2) and ist_berlin(cfg)))
    if not aktiv:
        return leer
    ce, cn, x0, x1, y0, y1 = rechteck(cfg)
    ex0, ex1 = int(math.floor(x0 / 2000)) * 2, int(math.floor((x1 - 1e-6) / 2000)) * 2
    ny0, ny1 = int(math.floor(y0 / 2000)) * 2, int(math.floor((y1 - 1e-6) / 2000)) * 2
    dgm_need = ["dgm1_33_%d_%d_2_be" % (e, n) for e in range(ex0, ex1 + 1, 2) for n in range(ny0, ny1 + 1, 2)]
    lx0, lx1 = int(math.floor(x0 / 1000)), int(math.floor((x1 - 1e-6) / 1000))
    ly0, ly1 = int(math.floor(y0 / 1000)), int(math.floor((y1 - 1e-6) / 1000))
    lod_need = ["LoD2_33_%d_%d_1_BE" % (e, n) for e in range(lx0, lx1 + 1) for n in range(ly0, ly1 + 1)]
    dgm_have = {m.group(0).lower() for p in cfg.dgm for m in [RX_DGM.search(os.path.basename(p))] if m}
    lod_have = {m.group(0).lower() for n in lod2_dateinamen(cfg.lod2) for m in [RX_LOD.search(n)] if m}
    return dict(aktiv=True, dgm_need=dgm_need, lod_need=lod_need,
                dgm_fehlt=[n for n in dgm_need if n.lower() not in dgm_have],
                lod_fehlt=[n for n in lod_need if n.lower() not in lod_have],
                dgm_unbenannt=[p for p in cfg.dgm if not RX_DGM.search(os.path.basename(p))])


def geojson_art(pfad):
    """'nutzung' (Polygone), 'baeume' (Punkte) oder None - nach dem Inhalt."""
    try:
        with open(pfad, "r", encoding="utf-8") as f:
            obj = json.load(f)
        arten = {}
        for ft in obj.get("features", [])[:200]:
            g = (ft.get("geometry") or {}).get("type", "")
            arten[g] = arten.get(g, 0) + 1
        if not arten:
            return None
        pt = sum(v for k, v in arten.items() if "Point" in k)
        po = sum(v for k, v in arten.items() if "Polygon" in k)
        return "baeume" if pt > po else "nutzung" if po else None
    except Exception:
        return None


def _tif_ist_dgm(p):
    try:
        import rasterio
    except ImportError:
        return True
    try:
        with rasterio.open(p) as r:
            return r.count == 1 and str(r.dtypes[0]).startswith(("float", "int16", "int32"))
    except Exception:
        return False


# ----------------------------------------------------------------------------------------------
# Gelaende
# ----------------------------------------------------------------------------------------------

def _dekodieren(raw):
    """Bytes -> Text; erkennt UTF-16/UTF-8 mit BOM, sonst UTF-8 (Fehler ersetzt)."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8-sig", errors="replace")


def _kopfzeilen(pfad, n=40):
    """Die ersten n Zeilen als Text (auch bei UTF-16 und Zeilenenden nur mit CR)."""
    try:
        with open(pfad, "rb") as f:
            raw = f.read(200000)
    except OSError:
        return []
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        raw = raw[:len(raw) // 2 * 2]
    return _dekodieren(raw).splitlines()[:n]


def xyz_format(pfad, zeilen=40):
    """Erkennt Trennzeichen, Kopfzeilen und Dezimalkomma einer Punktdatei.
    -> (sep, skiprows, dezimal, spalten) oder None, wenn keine 3 Zahlenspalten gefunden werden.
    spalten = Indizes von x, y, z (bei 4 Spalten mit vorangestellter Kennung: 1, 2, 3)."""
    skip, fmt = 0, None
    for z in _kopfzeilen(pfad, zeilen):
        z = z.strip()
        if not z:
            skip += 1
            continue
        if ";" in z:
            sep, dez = ";", ("," if "," in z else ".")
        elif "\t" in z:
            sep, dez = "\t", ("," if "," in z else ".")
        elif " " not in z and z.count(",") >= 2:
            sep, dez = ",", "."
        else:
            sep, dez = r"\s+", "."
        teile = [t.strip() for t in (re.split(sep, z) if sep != r"\s+" else z.split())]
        try:
            zahlen = [float(t.replace(",", ".") if dez == "," else t) for t in teile[:4]]
        except ValueError:
            skip += 1          # Kopfzeile
            continue
        if len(teile) >= 3 and len(zahlen) >= 3:
            sp = (1, 2, 3) if (len(zahlen) == 4 and abs(zahlen[0]) < 0.01 * abs(zahlen[1])) else (0, 1, 2)
            fmt = (sep, skip, dez, sp)
        break
    return fmt


RX_ZAHL = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _lade_text_notfall(pfad):
    """Letzter Ausweg: aus jeder Zeile die Zahlen herausziehen (x y z); langsamer, aber sehr tolerant."""
    with open(pfad, "rb") as f:
        text = _dekodieren(f.read())
    probe = text[:5000]
    if re.search(r"\d,\d", probe) and not re.search(r"\d\.\d", probe):
        text = text.replace(",", ".")          # Dezimalkomma
    out = []
    for z in text.splitlines():
        n = RX_ZAHL.findall(z)
        if len(n) >= 3:
            if len(n) >= 4 and abs(float(n[0])) < 0.01 * abs(float(n[1])):
                n = n[1:4]                            # erste Spalte ist eine Kennung
            else:
                n = n[:3]
            out.append((float(n[0]), float(n[1]), float(n[2])))
    return np.array(out) if out else np.zeros((0, 3))


def _lade_asc(pfad, bbox=None):
    """ESRI-ASCII-Grid (.asc) -> Nx3 (Zellmitten)."""
    hdr, nh = {}, 0
    with open(pfad, "r", encoding="utf-8", errors="replace") as f:
        for z in f:
            t = z.split()
            if len(t) == 2 and re.fullmatch(r"[A-Za-z_]+", t[0]):
                hdr[t[0].lower()] = float(t[1].replace(",", "."))
                nh += 1
            else:
                break
    try:
        nc, nr, cs = int(hdr["ncols"]), int(hdr["nrows"]), hdr["cellsize"]
        if "xllcorner" in hdr:
            xl, yl = hdr["xllcorner"] + cs / 2, hdr["yllcorner"] + cs / 2
        else:
            xl, yl = hdr["xllcenter"], hdr["yllcenter"]
    except KeyError as e:
        raise ValueError("%s: ASC-Kopf unvollstaendig (%s fehlt)" % (os.path.basename(pfad), e))
    nod = hdr.get("nodata_value", -9999.0)
    try:
        import pandas as pd
        a = pd.read_csv(pfad, sep=r"\s+", header=None, skiprows=nh, dtype=float, engine="c").values
    except ImportError:
        a = np.loadtxt(pfad, skiprows=nh)
    a = a.reshape(nr, nc)
    xs = xl + np.arange(nc) * cs
    ys = yl + (nr - 1 - np.arange(nr)) * cs
    return _raster_zu_punkte(a, xs, ys, nod, bbox)


def _raster_zu_punkte(a, xs, ys, nod, bbox):
    cm = np.ones(len(xs), dtype=bool)
    rm = np.ones(len(ys), dtype=bool)
    if bbox:
        x0, x1, y0, y1 = bbox
        cm = (xs >= x0) & (xs <= x1)
        rm = (ys >= y0) & (ys <= y1)
    sub = a[np.ix_(rm, cm)]
    X, Y = np.meshgrid(xs[cm], ys[rm])
    ok = np.isfinite(sub)
    if nod is not None:
        ok &= sub != nod
    return np.column_stack([X[ok], Y[ok], sub[ok]])


def _lade_tif(pfad, bbox=None):
    """GeoTIFF-Hoehenraster (.tif) -> Nx3 (Zellmitten). Braucht das Paket rasterio."""
    try:
        import rasterio
    except ImportError:
        raise ValueError("%s: GeoTIFF braucht das Paket rasterio (pip install rasterio)" % os.path.basename(pfad))
    with rasterio.open(pfad) as r:
        a = r.read(1).astype(float)
        T, nod = r.transform, r.nodata
    if abs(T.b) > 1e-9 or abs(T.d) > 1e-9:
        raise ValueError("%s: gedrehte Rasterdatei wird nicht unterstuetzt" % os.path.basename(pfad))
    xs = T.c + (np.arange(a.shape[1]) + 0.5) * T.a
    ys = T.f + (np.arange(a.shape[0]) + 0.5) * T.e
    return _raster_zu_punkte(a, xs, ys, nod, bbox)


def lade_xyz(pfad, bbox=None):
    """Hoehenpunkte aus .xyz/.txt/.csv (beliebiges Trennzeichen), .asc oder .tif -> Nx3 (x, y, z)."""
    low = pfad.lower()
    if low.endswith(".asc"):
        return _lade_asc(pfad, bbox)
    if low.endswith((".tif", ".tiff")):
        return _lade_tif(pfad, bbox)
    fmt = xyz_format(pfad)
    pts = None
    if fmt is not None:
        sep, skip, dez, sp = fmt
        try:
            with open(pfad, "rb") as f:
                bom16 = f.read(2) in (b"\xff\xfe", b"\xfe\xff")
            if not bom16:
                import pandas as pd
                pts = pd.read_csv(pfad, sep=sep, header=None, skiprows=skip, usecols=list(sp), dtype=float,
                                  decimal=dez, engine="c", encoding="utf-8-sig", encoding_errors="replace").values
        except Exception:
            pts = None
    if pts is None or len(pts) == 0:
        pts = _lade_text_notfall(pfad)
    if len(pts) == 0:
        erste = (_kopfzeilen(pfad, 1) or [""])[0].strip()[:100]
        raise ValueError("%s ist keine Punktdatei mit drei Zahlenspalten (x y z). Erste Zeile: '%s'"
                         % (os.path.basename(pfad), erste))
    return pts


RX_KACHEL_KM = re.compile(r"(?<!\d)(\d{3})_(\d{4})(?:_(\d{1,2}))?(?!\d)")        # z.B. 392_5822_2 (Ost km, Nord km, Kantenlaenge km)
RX_KACHEL_M = re.compile(r"(?<!\d)(\d{6})_(\d{7})(?!\d)")                         # z.B. 392000_5822000 (Meter)
IGNORIERT = re.compile(r"wfslinks|metadata|readme|\.xsd$|\.prj$|\.tfw$|\.md5$", re.I)


def kachel_rechteck(name):
    """Aus dem Dateinamen: (xmin, ymin, xmax, ymax) der Kachel in Metern oder None, wenn der Name keine Kachelkoordinaten enthaelt.
    Ist die Kantenlaenge nicht im Namen, wird grosszuegig 5 km angenommen (lieber eine Datei zu viel lesen als eine zu wenig)."""
    b = os.path.basename(name)
    m = RX_KACHEL_KM.search(b)
    if m:
        e, n = int(m.group(1)) * 1000, int(m.group(2)) * 1000
        if not (100000 <= e <= 900000 and 5000000 <= n <= 6200000):
            return None                                        # keine UTM-Koordinaten in Deutschland - Name sagt nichts
        k = int(m.group(3)) if m.group(3) and 1 <= int(m.group(3)) <= 10 else 5
        return (e, n, e + k * 1000, n + k * 1000)
    m = RX_KACHEL_M.search(b)
    if m:
        e, n = int(m.group(1)), int(m.group(2))
        return (e, n, e + 5000, n + 5000)
    return None


def kachel_im_rechteck(name, bbox, rand=5.0):
    """True/False nach dem Dateinamen, None wenn der Name nichts verraet. bbox = (xmin, ymin, xmax, ymax)"""
    r = kachel_rechteck(name)
    if r is None:
        return None
    return not (r[2] < bbox[0] - rand or r[0] > bbox[2] + rand or r[3] < bbox[1] - rand or r[1] > bbox[3] + rand)


def raster_kopf_grenzen(pfad):
    """(xmin, ymin, xmax, ymax) einer .asc/.tif nur aus dem Dateikopf (ohne die Daten zu lesen) oder None."""
    low = pfad.lower()
    try:
        if low.endswith(".asc"):
            hdr = {}
            with open(pfad, "r", encoding="utf-8", errors="replace") as f:
                for z in f:
                    t = z.split()
                    if len(t) == 2 and re.fullmatch(r"[A-Za-z_]+", t[0]):
                        hdr[t[0].lower()] = float(t[1].replace(",", "."))
                    else:
                        break
            nc, nr, cs = int(hdr["ncols"]), int(hdr["nrows"]), hdr["cellsize"]
            x0 = hdr["xllcorner"] if "xllcorner" in hdr else hdr["xllcenter"] - cs / 2
            y0 = hdr["yllcorner"] if "yllcorner" in hdr else hdr["yllcenter"] - cs / 2
            return (x0, y0, x0 + nc * cs, y0 + nr * cs)
        if low.endswith((".tif", ".tiff")):
            import rasterio
            with rasterio.open(pfad) as r:
                b = r.bounds
                return (b.left, b.bottom, b.right, b.top)
    except Exception:
        return None
    return None


def dgm_filtern(pfade, bbox, log=print):
    """Nur Gelaendedateien behalten, die das Rechteck beruehren (nach Kachelname, bei .asc/.tif nach dem Dateikopf). bbox = (xmin, ymin, xmax, ymax).
    Dateien, bei denen sich das nicht klaeren laesst, bleiben drin. -> (behalten, uebersprungen)"""
    keep, skip = [], []
    for p in pfade:
        b = os.path.basename(p)
        if IGNORIERT.search(b):
            skip.append((p, "keine Hoehendaten"))
            continue
        ok = kachel_im_rechteck(b, bbox)
        if ok is None:
            gr = raster_kopf_grenzen(p)
            if gr is not None:
                ok = not (gr[2] < bbox[0] or gr[0] > bbox[2] or gr[3] < bbox[1] or gr[1] > bbox[3])
        if ok is False:
            skip.append((p, "liegt ausserhalb des Rechtecks"))
        else:
            keep.append(p)
    return keep, skip


def raster_schritt(pts):
    """Rasterweite und Ursprung (kleinstes x/y) einer regelmaessigen Punktwolke."""
    xs = np.unique(np.round(pts[:, 0], 3))
    ys = np.unique(np.round(pts[:, 1], 3))

    def st(a):
        dd = np.diff(a)
        dd = dd[dd > 1e-6]
        return float(np.median(dd)) if len(dd) else 1.0
    s = round(min(st(xs), st(ys)), 3) or 1.0
    return s, float(xs.min()), float(ys.min())


def gelaende_ausduennen(dgm_pfade, xmin, xmax, ymin, ymax, tol, log=print, zone=None):
    """zone = (mitte_ost, mitte_nord, breite, hoehe, tol_fern, uebergang, fern_raster) beschreibt den Nahbereich (Rechteck);
    ausserhalb waechst die erlaubte Abweichung von tol auf tol_fern, und im Fernbereich sind nur Punkte auf dem Raster fern_raster erlaubt."""
    teile = []
    gesamt = len(dgm_pfade)
    dgm_pfade, uebersprungen = dgm_filtern(dgm_pfade, (xmin, ymin, xmax, ymax), log)
    if uebersprungen:
        log("  DGM: %d von %d Dateien liegen nicht im Rechteck bzw. enthalten keine Hoehen und werden gar nicht gelesen" % (len(uebersprungen), gesamt))
        for p, grund in uebersprungen[:6]:
            log("    uebersprungen: %s (%s)" % (os.path.basename(p), grund))

    def lesen(p):
        t0 = time.time()
        try:
            return p, lade_xyz(p, (xmin, xmax, ymin, ymax)), time.time() - t0, None
        except Exception as e:
            return p, None, time.time() - t0, e
    if len(dgm_pfade) > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(4, len(dgm_pfade))) as ex:
            ergebnisse = list(ex.map(lesen, dgm_pfade))
    else:
        ergebnisse = [lesen(p) for p in dgm_pfade]
    for p, d, dt, fehler in ergebnisse:
        if fehler is not None:
            log("  FEHLER: %s -> Datei wird uebersprungen" % fehler)
            continue
        m = (d[:, 0] >= xmin) & (d[:, 0] <= xmax) & (d[:, 1] >= ymin) & (d[:, 1] <= ymax)
        teile.append(d[m])
        log("  DGM %s: %d Punkte gelesen, %d im Rechteck (%.0f s)" % (os.path.basename(p), len(d), m.sum(), dt))
    pts = np.vstack(teile) if teile else np.zeros((0, 3))
    if len(pts) == 0:
        log("  WARNUNG: keine DGM-Punkte im Rechteck - passen Dateien, Mittelpunkt und Koordinatensystem zusammen?")
        return None
    s, xo, yo = raster_schritt(pts)
    ix = np.rint((pts[:, 0] - xo) / s).astype(np.int64)
    iy = np.rint((pts[:, 1] - yo) / s).astype(np.int64)
    nx, ny = int(ix.max()) + 1, int(iy.max()) + 1
    if nx * ny > 60e6:
        log("  FEHLER: Gelaenderaster zu gross (%d x %d Zellen) - Gebiet verkleinern oder Raster pruefen" % (nx, ny))
        return None
    Z = np.full((ny, nx), np.nan)
    Z[iy, ix] = pts[:, 2]
    gueltig = ~np.isnan(Z)
    gy, gx = np.nonzero(gueltig)
    gz = Z[gy, gx]
    ex0, ex1 = gx.min() * s + xo, gx.max() * s + xo
    ey0, ey1 = gy.min() * s + yo, gy.max() * s + yo
    log("  DGM-Ausschnitt: Ost %.0f-%.0f (%.0f m), Nord %.0f-%.0f (%.0f m), %d Rasterpunkte, Rasterweite %g m"
        % (ex0, ex1, ex1 - ex0 + s, ey0, ey1, ey1 - ey0 + s, len(gz), s))
    if ex1 - ex0 + s < 0.98 * (xmax - xmin) or ey1 - ey0 + s < 0.98 * (ymax - ymin):
        log("  HINWEIS: Das Rechteck ragt ueber die vorhandenen DGM-Daten hinaus - Gelaende nur dort, wo Daten vorliegen.")
    # erlaubte Abweichung je Rasterzelle (Nahbereich: tol, Uebergang: linear, Fernbereich: tol_fern)
    tolarr = np.full(Z.shape, float(tol))
    erlaubt = np.ones(Z.shape, dtype=bool)
    nah_maske = np.ones(Z.shape, dtype=bool)
    if zone is not None:
        zx, zy, zb, zh, tol_f, uebg, fraster = zone
        X = np.arange(nx)[None, :] * s + xo
        Y = np.arange(ny)[:, None] * s + yo
        dx = np.maximum(np.abs(X - zx) - zb / 2, 0.0)
        dy = np.maximum(np.abs(Y - zy) - zh / 2, 0.0)
        dist = np.hypot(dx, dy)
        w = np.clip(dist / uebg, 0.0, 1.0) if uebg > 0 else (dist > 0).astype(float)
        tolarr = tol + (max(tol_f, tol) - tol) * w
        nah_maske = dist == 0
        if fraster and fraster > s * 1.5:
            k = max(1, int(round(fraster / s)))
            gitter = (np.arange(ny)[:, None] % k == 0) & (np.arange(nx)[None, :] % k == 0)
            erlaubt = (dist < max(uebg, s)) | gitter
    g40, g10 = max(1, int(round(40 / s))), max(1, int(round(10 / s)))
    wahl = np.zeros(Z.shape, dtype=bool)
    wahl[::g40, ::g40] = True
    wahl[0, ::g10] = wahl[-1, ::g10] = True
    wahl[::g10, 0] = wahl[::g10, -1] = True
    wahl[0, -1] = wahl[-1, 0] = wahl[0, 0] = wahl[-1, -1] = True
    wahl &= gueltig
    zaehlt = erlaubt[gy, gx]                       # im Fernbereich zaehlen nur die Rasterpunkte - die uebrigen nicht auswerten
    for it in range(1, 40):
        wy, wx = np.nonzero(wahl)
        if len(wx) < 4:
            break
        f = LinearNDInterpolator(np.column_stack([wx, wy]), Z[wy, wx])
        fehler = np.zeros(Z.shape)
        fehler[gy[zaehlt], gx[zaehlt]] = np.abs(np.nan_to_num(f(gx[zaehlt], gy[zaehlt]) - gz[zaehlt], nan=0.0))
        fehler[wahl] = 0.0
        rel = fehler / tolarr                      # Abweichung im Verhaeltnis zur dort erlaubten
        kand = (rel > 1.0) & (rel == maximum_filter(rel, size=7 if it <= 8 else 3))   # spaeter dichter waehlen: weniger Durchgaenge
        if not kand.any():
            break
        wahl |= kand
    wy, wx = np.nonzero(wahl)
    f = LinearNDInterpolator(np.column_stack([wx, wy]), Z[wy, wx])
    abw = np.abs(np.nan_to_num(f(gx, gy) - gz, nan=0.0))
    px, py, pz = wx * s + xo, wy * s + yo, Z[wy, wx]
    n_nah = int(nah_maske[wy, wx].sum())
    log("  Gelaende: %d Punkte (statt %d), max. Abweichung %.3f m, mittlere %.4f m" % (len(px), len(gz), abw.max(), abw.mean()))
    if zone is not None:
        log("    Nahbereich: %d Punkte (Toleranz %.2f m)   Uebergang/Fern: %d Punkte (bis %.2f m, Uebergang %.0f m, Raster %g m)"
            % (n_nah, tol, len(px) - n_nah, zone[4], zone[5], zone[6]))
    else:
        log("    Toleranz %.2f m" % tol)
    return px, py, pz


# ----------------------------------------------------------------------------------------------
# Gebaeude (CityGML 1.0, AdV-LoD2)
# ----------------------------------------------------------------------------------------------

class _NS:
    B = "{http://www.opengis.net/citygml/building/1.0}"
    G = "{http://www.opengis.net/gml}"
    V3 = False


def _ns_ermitteln(f):
    """Liest die Namensraeume der Wurzel (CityGML 1.0/2.0, GML 3.1/3.2) und setzt den Lesezeiger zurueck."""
    ns = _NS()
    uris = []
    try:
        for ev, v in ET.iterparse(f, events=("start-ns", "start")):
            if ev == "start":
                break
            uris.append(v[1])
    except ET.ParseError:
        pass
    f.seek(0)
    for u in uris:
        if u.startswith("http://www.opengis.net/citygml/building/"):
            ns.B = "{%s}" % u
            ns.V3 = u.rstrip("/").endswith("3.0")
        elif u in ("http://www.opengis.net/gml", "http://www.opengis.net/gml/3.2"):
            ns.G = "{%s}" % u
    return ns


def _zahlen(text):
    """Zahlenliste aus einem GML-Text (schnell: numpy parst den Text direkt)"""
    try:
        return np.fromstring(text, dtype=float, sep=" ")
    except Exception:
        return np.array(text.split(), dtype=float)


def _ring(el, n):
    pl = el.find(n.G + "LinearRing/" + n.G + "posList")                  # direkter Weg (Normalfall), sonst suchen
    if pl is None:
        pl = el.find(".//" + n.G + "posList")
    if pl is not None and pl.text:
        a = _zahlen(pl.text)
        a = a.reshape(-1, 3) if len(a) % 3 == 0 else None
    else:
        poss = [_zahlen(p.text) for p in el.iter(n.G + "pos") if p.text]
        a = np.array(poss) if poss and all(len(p) == 3 for p in poss) else None
    if a is None:
        return None
    if len(a) > 1 and np.abs(a[0] - a[-1]).max() < 1e-5:
        a = a[:-1]
    return a if len(a) >= 3 else None


def _polygone(el, n):
    out = []
    for poly in el.iter(n.G + "Polygon"):
        ext = poly.find(n.G + "exterior")
        if ext is None:
            continue
        e = _ring(ext, n)
        if e is None:
            continue
        holes = [r for r in (_ring(i, n) for i in poly.findall(n.G + "interior")) if r is not None]
        out.append((e, holes))
    return out


def _klasse_nach_normale(polys):
    """Ohne Flaechentypen (nur lod2MultiSurface/Solid): Wand/Dach/Boden aus der Neigung schaetzen."""
    out = {"wall": [], "roof": [], "ground": []}
    if not polys:
        return out
    zmin = min(e[:, 2].min() for e, h in polys)
    for e, h in polys:
        nv = np.zeros(3)
        for i in range(len(e)):
            nv += np.cross(e[i], e[(i + 1) % len(e)])
        L = np.linalg.norm(nv)
        if L < 1e-9:
            continue
        nz = abs(nv[2] / L)
        if nz < 0.1:
            out["wall"].append((e, h))
        elif nz > 0.98 and e[:, 2].mean() <= zmin + 0.3:
            out["ground"].append((e, h))
        else:
            out["roof"].append((e, h))
    return out


def _teil(el, bid, n):
    d = {"id": el.get(n.G + "id"), "gebaeude": bid, "wall": [], "roof": [], "ground": [], "closure": []}
    h = el.find(n.B + "measuredHeight")
    try:
        d["h"] = float(h.text) if h is not None and h.text else None
    except ValueError:
        d["h"] = None
    sg = el.find(n.B + "storeysAboveGround")
    if sg is not None and sg.text:
        try:
            d["geschosse"] = int(float(sg.text))
        except ValueError:
            pass
    typen = {n.B + "WallSurface": "wall", n.B + "RoofSurface": "roof",
             n.B + "GroundSurface": "ground", n.B + "ClosureSurface": "closure"}
    for bb in el.findall(n.B + "boundedBy"):
        for child in bb:
            t = typen.get(child.tag)
            if t:
                d[t].extend(_polygone(child, n))
    if not (d["wall"] or d["roof"] or d["ground"]):
        polys = []
        for tag in ("lod2MultiSurface", "lod2Solid"):
            for c in el.findall(n.B + tag):
                polys += _polygone(c, n)
        if polys:
            d.update(_klasse_nach_normale(polys))
    return d


def _lod_name_ok(name, bbox, zaehler):
    """Soll diese CityGML-Datei (oder dieser ZIP-Eintrag) gelesen werden? LoD1 und Kacheln ausserhalb des Rechtecks nicht."""
    b = os.path.basename(name)
    if IGNORIERT.search(b):
        zaehler["ignoriert"] = zaehler.get("ignoriert", 0) + 1
        return False
    if re.search(r"lod[_-]?1(?!\d)", b, re.I) and not re.search(r"lod[_-]?2", b, re.I):
        zaehler["lod1"] = zaehler.get("lod1", 0) + 1
        return False
    if bbox is not None and kachel_im_rechteck(b, bbox) is False:
        zaehler["ausserhalb"] = zaehler.get("ausserhalb", 0) + 1
        return False
    return True


def _quellen(pfade, bbox=None, zaehler=None):
    zaehler = zaehler if zaehler is not None else {}
    for p in pfade:
        if os.path.isdir(p):
            for q in sorted(glob.glob(os.path.join(p, "**", "*"), recursive=True)):
                if q.lower().endswith((".xml", ".gml", ".zip")):
                    yield from _quellen([q], bbox, zaehler)
        elif p.lower().endswith(".zip"):
            if not _lod_name_ok(p, bbox, zaehler):
                continue
            with zipfile.ZipFile(p) as z:
                for nm in z.namelist():
                    if nm.lower().endswith((".xml", ".gml")) and _lod_name_ok(nm, bbox, zaehler):
                        with z.open(nm) as zf:                      # streamen statt alles in den Speicher laden
                            yield nm, zf
        elif _lod_name_ok(p, bbox, zaehler):
            yield os.path.basename(p), open(p, "rb")


def _dach_stat(roofs):
    """Dachflaechen (Liste (ext, holes)) -> (Anzahl, Menge der Neigungs-/Richtungsklassen, steile Flaeche m2, gesamte Flaeche m2)"""
    n, kl, steil, ges = 0, set(), 0.0, 0.0
    for e, h in roofs:
        if len(e) < 3:
            continue
        nv = np.zeros(3)
        for i in range(len(e)):
            nv += np.cross(e[i], e[(i + 1) % len(e)])
        a = float(np.linalg.norm(nv)) / 2.0
        if a < 0.5:
            continue
        n += 1
        ges += a
        tilt = math.degrees(math.acos(min(1.0, abs(nv[2]) / (2.0 * a))))
        if tilt > 5.0:
            kl.add((int(round(tilt / 15.0)), int(round(math.degrees(math.atan2(nv[1], nv[0])) / 30.0)) % 12))
        else:
            kl.add((0, -1))
        if tilt > 60.0:
            steil += a
    return n, kl, steil, ges


def dach_komplexitaet(teile):
    """Wie vielfaeltig ist das Dach eines Gebaeudes (Liste LoD2-Teile)? -> (Anzahl Dachflaechen, Anzahl Neigungs-/Richtungsklassen,
    Anteil steiler Flaeche > 60 Grad). Verdichtete Fernbereich-Teile tragen das Ergebnis aus der Zeit vor dem Verdichten mit."""
    n, kl, steil, ges = 0, set(), 0.0, 0.0
    for t in teile:
        st = t.get("dachk") or _dach_stat(t["roof"])
        n += st[0]
        kl |= st[1]
        steil += st[2]
        ges += st[3]
    return n, len(kl), (steil / ges if ges > 0 else 0.0)


def _kompakt(t):
    """Fernbereich: nur Grundriss + Dachhoehen (Traufe/First) behalten, Waende und Daecher verwerfen (spart Speicher)."""
    roofz = None
    if t["roof"]:
        roofz = (float(min(e[:, 2].min() for e, h in t["roof"])), float(max(e[:, 2].max() for e, h in t["roof"])))
    return {"id": t["id"], "gebaeude": t["gebaeude"], "h": t["h"], "ground": t["ground"], "wall": [], "roof": [],
            "closure": [], "roofz": roofz, "kompakt": True, "c": t["c"], "dachk": _dach_stat(t["roof"]),
            "quelle": t.get("quelle", "LoD2")}


def _behalten(teile, behalte):
    """Gebaeude im Fernbereich voll behalten (nicht zu Bloecken verdichten)? behalte = dict(punkte=[(x, y)], dach=bool, flaechen=dict|None)
    (nur bei markanten Gebaeuden im Fernbereich: eigene Liste, OSM-/Denkmal-Flaechen, komplexes Dach)"""
    if not behalte:
        return False
    if behalte.get("punkte") or behalte.get("flaechen"):
        from shapely.geometry import Point, Polygon
        for t in teile:
            for e, h in (t["ground"] or t["roof"]):
                if len(e) >= 3:
                    pg = Polygon(e[:, :2]).buffer(2.0)
                    if any(pg.contains(Point(x, y)) for x, y in behalte.get("punkte") or ()):
                        return True
                    fl = behalte.get("flaechen")
                    if fl is not None:
                        for i in fl["tree"].query(pg, predicate="intersects"):
                            try:
                                if fl["geoms"][int(i)].intersection(pg).area >= 0.4 * pg.area:
                                    return True
                            except Exception:
                                pass
    if behalte.get("dach"):
        n, k, steil = dach_komplexitaet(teile)
        if (n >= 40 and k >= 10) or (n >= 8 and steil >= 0.30):
            return True
    return False


FAST_RAND = 350.0          # m: Gebaeude, deren erster und letzter Ring weiter als das ausserhalb des Rechtecks liegen, werden gar nicht erst geparst
_RX_POS = re.compile(rb"<(?:[\w.-]+:)?posList[^>]*>\s*(-?[\d.eE+-]+)\s+(-?[\d.eE+-]+)")


def _gebaeude_iter(f, n, rechteck, log=print):
    """Liefert die Building-Elemente einer CityGML-Datei. Schnell: die Datei wird als Bytes in Stuecken gelesen, jedes Gebaeude per Textsuche
    abgegrenzt; nur Gebaeude nahe am Rechteck werden ueberhaupt geparst (erster/letzter Ring entscheiden). Faellt auf iterparse zurueck, wenn
    die Datei nicht so aufgebaut ist (dann wird alles gelesen wie frueher)."""
    xmin, xmax, ymin, ymax = rechteck
    kopf = f.read(1 << 16)
    f.seek(0)
    m_root = re.search(rb"<(?:[\w.-]+:)?CityModel\b[^>]*>", kopf)
    m_pre = re.search(rb'xmlns:?([\w.-]*)="' + re.escape(n.B.strip("{}").encode()) + rb'"', kopf)
    if not (m_root and m_pre) or os.environ.get("ARCHITOOLS_LANGSAM_LESEN"):
        for ev, bld in ET.iterparse(f, events=("end",)):
            if bld.tag == n.B + "Building":
                yield bld
        return
    pre = m_pre.group(1).decode()
    praefix = (pre + ":") if pre else ""
    wurzel = m_root.group(0).decode("utf-8", "replace")
    wname = re.match(r"<([\w.:-]+)", wurzel).group(1)
    start = re.compile(rb"<" + re.escape(praefix.encode()) + rb"Building(?=[\s>])")
    ende = ("</" + praefix + "Building>").encode()
    x0, x1, y0, y1 = xmin - FAST_RAND, xmax + FAST_RAND, ymin - FAST_RAND, ymax + FAST_RAND
    puffer, geparst, uebersprungen = b"", 0, 0

    def nahe(stueck):
        pos = _RX_POS.findall(stueck)
        if not pos:
            return True
        for x, y in (pos[0], pos[-1]):
            try:
                xf, yf = float(x), float(y)
            except ValueError:
                return True
            if x0 <= xf <= x1 and y0 <= yf <= y1:
                return True
        return False

    while True:
        block = f.read(8 << 20)
        puffer += block
        pos = 0
        while True:
            a = start.search(puffer, pos)
            if not a:
                break
            e = puffer.find(ende, a.start())
            if e < 0:
                break
            stueck = puffer[a.start():e + len(ende)]
            pos = e + len(ende)
            if not nahe(stueck):
                uebersprungen += 1
                continue
            try:
                root = ET.fromstring(wurzel + stueck.decode("utf-8", "replace") + "</" + wname + ">")
            except ET.ParseError:
                continue
            geparst += 1
            for bld in root:
                yield bld
        if not block:
            break
        a = start.search(puffer, pos)
        puffer = puffer[a.start():] if a else puffer[max(pos, len(puffer) - 64):]
    if uebersprungen:
        log("    (schnell gelesen: %d Gebaeude geparst, %d weit ausserhalb uebersprungen)" % (geparst, uebersprungen))


def lod2_lesen(pfade, xmin, xmax, ymin, ymax, log=print, prog=_noop, nah=None, fern="bloecke", behalte=None):
    """Liest CityGML-Gebaeude (Stream, Speicher bleibt klein). nah = (Ost, Nord, Breite, Hoehe) des Nahbereichs-Rechtecks;
    Teile ausserhalb werden (ausser fern == "lod2") nur als Grundriss + Dachhoehen gespeichert."""
    teile, gesehen = [], set()
    zaehler = {}
    for name, f in _quellen(pfade, (xmin, ymin, xmax, ymax), zaehler):
        t0 = time.time()
        try:
            n = _ns_ermitteln(f)
            if n.V3:
                log("  LoD2 %s: CityGML 3.0 wird nicht unterstuetzt (nur 1.0/2.0)" % name)
                continue
            n0 = len(teile)
            for bld in _gebaeude_iter(f, n, (xmin, xmax, ymin, ymax), log):
                bid = bld.get(n.G + "id")
                neu = []
                for el in [bld] + list(bld.iter(n.B + "BuildingPart")):
                    t = _teil(el, bid, n)
                    if not (t["wall"] or t["roof"] or t["ground"]) or (t["id"] is not None and t["id"] in gesehen):
                        continue
                    g = t["ground"] or t["roof"] or t["wall"]
                    p = np.vstack([e for e, h in g])
                    t["c"] = (float(p[:, 0].mean()), float(p[:, 1].mean()))
                    if not (xmin <= t["c"][0] <= xmax and ymin <= t["c"][1] <= ymax):
                        continue
                    if t["id"] is not None:
                        gesehen.add(t["id"])
                    t["quelle"] = "LoD2"
                    neu.append(t)
                if neu:
                    voll = False
                    if behalte and nah is not None and fern != "lod2" and not all(
                            abs(t["c"][0] - nah[0]) <= nah[2] / 2 and abs(t["c"][1] - nah[1]) <= nah[3] / 2 for t in neu):
                        voll = _behalten(neu, behalte)             # nur fuer Gebaeude, die (auch) im Fernbereich liegen
                    for t in neu:
                        if (nah is not None and fern != "lod2" and not voll
                                and not (abs(t["c"][0] - nah[0]) <= nah[2] / 2 and abs(t["c"][1] - nah[1]) <= nah[3] / 2)):
                            t = _kompakt(t)
                        teile.append(t)
                bld.clear()
        except ET.ParseError as e:
            log("  LoD2 %s: nicht lesbar (%s)" % (name, e))
            continue
        log("  LoD2 %s: %d Teile im Rechteck (%.0f s)" % (name, len(teile) - n0, time.time() - t0))
    if zaehler:
        log("  Nicht gelesen: %s" % ", ".join("%d %s" % (v, {"lod1": "LoD1-Dateien (koennen Gebaeude doppeln)", "ausserhalb": "Dateien ausserhalb des Rechtecks",
                                                              "ignoriert": "Nicht-Gebaeude-Dateien (z.B. WFSlinks.xml)"}[k]) for k, v in zaehler.items()))
    return teile


def tri_poly3d(ext, holes):
    if not holes and len(ext) == 3:
        return [ext]
    pts = np.vstack([ext] + list(holes))
    n = np.zeros(3)
    for i in range(len(ext)):
        n += np.cross(ext[i], ext[(i + 1) % len(ext)])
    if np.linalg.norm(n) < 1e-9:
        return []
    ax = int(np.argmax(np.abs(n)))
    keep = [i for i in range(3) if i != ax]
    v2 = np.ascontiguousarray(pts[:, keep], dtype=np.float64)
    ends = np.cumsum([len(ext)] + [len(h) for h in holes]).astype(np.uint32)
    idx = earcut.triangulate_float64(v2, ends).reshape(-1, 3)
    return [pts[i] for i in idx]


def _eben(p, tol=0.006):
    """Liegen alle Punkte (n x 3) in einer Ebene (Abweichung <= tol m)?"""
    c = p.mean(axis=0)
    try:
        _, _, vt = np.linalg.svd(p - c)
    except np.linalg.LinAlgError:
        return False
    return float(np.abs((p - c) @ vt[2]).max()) <= tol


def faces_poly3d(ext, holes):
    """Flaeche als Liste von Polygonen: moeglichst als EIN n-Eck (sauberer Morph, keine Diagonalen),
    nur bei Loechern, windschiefen oder ungueltigen Flaechen als Dreiecke."""
    if not holes:
        if len(ext) == 3:
            return [ext]
        p = [ext[0]]
        for q in ext[1:]:
            if np.linalg.norm(q - p[-1]) > 1e-4:
                p.append(q)
        if len(p) > 1 and np.linalg.norm(p[0] - p[-1]) <= 1e-4:
            p.pop()
        p = np.array(p)
        if len(p) == 3:
            return [p]
        if len(p) >= 4 and _eben(p):
            n = np.zeros(3)
            for i in range(len(p)):
                n += np.cross(p[i], p[(i + 1) % len(p)])
            if np.linalg.norm(n) > 1e-9:
                from shapely.geometry import Polygon
                ax = int(np.argmax(np.abs(n)))
                keep = [i for i in range(3) if i != ax]
                if Polygon(p[:, keep]).is_valid:
                    return [p]
    return tri_poly3d(ext, holes)


def block_faces(t):
    zg = min(e[:, 2].min() for e, h in t["ground"])
    if t.get("roofz"):
        eave, first = t["roofz"]
    elif t["roof"]:
        eave = min(e[:, 2].min() for e, h in t["roof"])
        first = max(e[:, 2].max() for e, h in t["roof"])
    else:
        eave = first = zg + (t["h"] or 3.0)
    roh, hoehe = eave - zg, first - zg
    korr = False
    if roh < MINTRAUFE_ANTEIL * hoehe:
        roh, korr = MINTRAUFE_ANTEIL * hoehe, True
    ztop = zg + roh
    faces = []
    for e, holes in t["ground"]:
        for r in [e] + list(holes):
            n = len(r)
            for i in range(n):
                a, b = r[i], r[(i + 1) % n]
                if np.hypot(*(a[:2] - b[:2])) < 1e-4:
                    continue
                faces.append(np.array([[a[0], a[1], zg], [b[0], b[1], zg], [b[0], b[1], ztop], [a[0], a[1], ztop]]))
        top_e = np.column_stack([e[:, :2], np.full(len(e), ztop)])
        top_h = [np.column_stack([h[:, :2], np.full(len(h), ztop)]) for h in holes]
        faces += faces_poly3d(top_e, top_h)
    return faces, korr


def lod2_faces(t):
    faces = []
    for k in ("wall", "roof", "ground"):
        if k == "ground" and t.get("boden_dicht"):
            continue                                     # Boden steckt schon (mit verdichteten Randpunkten) in den Waenden - 'ground' ist nur der Grundriss
        for e, h in t[k]:
            faces += faces_poly3d(e, h)
    return faces


# ----------------------------------------------------------------------------------------------
# Nutzungsflaechen und Baeume laden
# ----------------------------------------------------------------------------------------------

def _wfs_url(basis, typ, bbox, version, fmt, start=None, count=None, bbox_crs=True):
    q = {"service": "WFS", "version": version, "request": "GetFeature", "outputFormat": fmt, "srsName": "EPSG:25833"}
    if bbox is not None:
        xmin, ymin, xmax, ymax = bbox
        q["bbox"] = "%.1f,%.1f,%.1f,%.1f%s" % (xmin, ymin, xmax, ymax, ",EPSG:25833" if bbox_crs else "")
    if version.startswith("2"):
        q["typeNames"] = typ
        if count:
            q["count"] = str(count)
        if start is not None:
            q["startIndex"] = str(start)
    else:
        q["typeName"] = typ
        q["maxFeatures"] = str(count or 50000)
    return basis + "?" + urllib.parse.urlencode(q)


def _http_json(url, ctx):
    req = urllib.request.Request(url, headers={"User-Agent": "ZachariasTools/0.1 (+https://github.com/ZirkelZacharias/zacharias-tools)", "Accept": "application/json, */*;q=0.5"})
    try:
        with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
            raw = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            text = e.read().decode("utf-8", errors="replace")
        except Exception:
            text = ""
        raise ValueError("HTTP %s: %s" % (e.code, re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))[:300])) from None
    try:
        obj = json.loads(raw)
    except ValueError:
        raise ValueError("Antwort ist kein JSON: " + re.sub(r"\s+", " ", raw[:300])) from None
    if not isinstance(obj, dict) or "features" not in obj:
        raise ValueError("Antwort ist kein GeoJSON: " + raw[:200].replace("\n", " "))
    return obj


def wfs_laden(basis, typ, bbox, cafile, unsicher, log=print, notfall_ohne_bbox=False):
    """Laedt eine Feature-Collection (GeoJSON) vom WFS; probiert mehrere Varianten (die Fehlermeldung des Dienstes wird
    mitgeschrieben). notfall_ohne_bbox: als letzte Moeglichkeit die ganze Ebene laden (der Aufrufer schneidet selbst zu). -> dict oder None"""
    schluessel = None
    try:                                               # Zwischenspeicher auf der Platte (24 Stunden): gleiche Abfrage nicht noch einmal
        import hashlib
        schluessel = os.path.join(cache_ordner(), "wfs_%s.json" % hashlib.sha1(
            ("%s|%s|%s|%s" % (basis, typ, None if bbox is None else tuple(round(v, 1) for v in bbox), notfall_ohne_bbox)).encode()).hexdigest()[:20])
        if os.path.exists(schluessel) and time.time() - os.path.getmtime(schluessel) < 24 * 3600:
            with open(schluessel, "r", encoding="utf-8") as fh:
                obj = json.load(fh)
            log("  WFS %s: %d Objekte (aus dem Zwischenspeicher, nicht aelter als 24 Stunden)" % (typ, len(obj.get("features", []))))
            return obj
    except Exception:
        schluessel = schluessel if isinstance(schluessel, str) else None
    ctx = ssl_kontext(cafile, unsicher)
    versuche = [("2.0.0", "application/json", True), ("2.0.0", "json", True), ("2.0.0", "application/json", False),
                ("1.1.0", "application/json", True), ("1.1.0", "application/json", False)]
    if notfall_ohne_bbox:
        versuche.append(("2.0.0", "application/json", None))
    fehler = []
    for version, fmt, bbox_crs in versuche:
        try:
            bb = bbox if bbox_crs is not None else None
            if version.startswith("2"):
                feats, start, seite = [], 0, 5000
                while True:
                    url = _wfs_url(basis, typ, bb, version, fmt, start, seite, bbox_crs=bool(bbox_crs))
                    if start == 0:
                        log("  WFS: " + url)
                    obj = _http_json(url, ctx)
                    feats += obj["features"]
                    if len(obj["features"]) < seite or bbox_crs is None or len(feats) > 60000:
                        break
                    start += seite
                obj["features"] = feats
            else:
                url = _wfs_url(basis, typ, bb, version, fmt, bbox_crs=bool(bbox_crs))
                log("  WFS: " + url)
                obj = _http_json(url, ctx)
            if fehler:
                log("  (Variante %s %s hat funktioniert, vorher: %s)" % (version, fmt, fehler[-1][:120]))
            if schluessel:
                try:
                    with open(schluessel, "w", encoding="utf-8") as fh:
                        json.dump(obj, fh)
                except Exception:
                    pass
            return obj
        except Exception as e:
            fehler.append(str(e))
            log("  Versuch %s / %s fehlgeschlagen: %s" % (version, fmt, str(e)[:300]))
            if isinstance(e, ssl.SSLError) or "CERTIFICATE" in str(e).upper():
                log("  -> Mit 'pip install truststore' den Windows-Zertifikatsspeicher nutzen, oder unter "
                    "'Erweitert' eine CA-Datei angeben / die SSL-Pruefung abschalten.")
                return None
            if "timed out" in str(e).lower() or isinstance(e, (TimeoutError, socket.timeout)):
                log("  Zeitueberschreitung - der Dienst antwortet nicht rechtzeitig; weitere Varianten werden uebersprungen.")
                break
    log("  FEHLER beim Laden von %s: %s" % (typ, fehler[-1] if fehler else "?"))
    log("  -> Alternative: Daten in QGIS als GeoJSON (EPSG:25833) speichern und im Fenster hinzufuegen.")
    try:
        namen = wfs_typnamen(basis, ctx)
        if namen:
            stamm = typ.split(":")[-1][:6].lower()
            passend = [n for n in namen if stamm in n.lower()] or namen[:15]
            log("  Dieser Dienst bietet u. a. folgende Datensaetze an (bitte dem Support/Claude melden, falls '%s' nicht dabei ist): %s"
                % (typ, ", ".join(passend[:20])))
    except Exception:
        pass
    return None


def typnamen_aus_xml(text):
    """Feature-Typ-Namen aus einem WFS-GetCapabilities-Dokument."""
    teil = text.split("FeatureTypeList", 1)[-1]
    return re.findall(r"<(?:\w+:)?Name>\s*([^<\s]+)\s*</(?:\w+:)?Name>", teil)


def wfs_typnamen(basis, ctx):
    url = basis + "?" + urllib.parse.urlencode({"service": "WFS", "request": "GetCapabilities"})
    req = urllib.request.Request(url, headers={"User-Agent": "ZachariasTools/0.1 (+https://github.com/ZirkelZacharias/zacharias-tools)"})
    with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
        return typnamen_aus_xml(r.read().decode("utf-8", errors="replace"))


def geojson_features(obj, crs_in="", ziel=25833):
    """FeatureCollection -> [(shapely-Geometrie im Projekt-KBS, props)]"""
    if not obj:
        return []
    feats = obj.get("features", []) if isinstance(obj, dict) else obj
    out = []
    for ft in feats:
        g = ft.get("geometry")
        if not g:
            continue
        try:
            geom = shapely.force_2d(shape(g))
        except Exception:
            continue
        out.append((geom, ft.get("properties") or {}))
    if not out:
        return out
    b = out[0][0].bounds
    crs = str(crs_in or "").upper().replace("EPSG:", "").strip() or str(ziel)
    if crs == str(ziel) and abs(b[0]) < 200 and abs(b[1]) < 100:
        crs = "4326"          # Koordinaten sehen nach Grad aus
    if crs != str(ziel):
        from pyproj import Transformer
        tr = Transformer.from_crs("EPSG:" + crs, "EPSG:%s" % ziel, always_xy=True)
        out = [(shapely.transform(g, lambda c: np.column_stack(tr.transform(c[:, 0], c[:, 1]))), p) for g, p in out]
    return out


def lese_geojson(pfad, crs_in="", ziel=25833):
    with open(pfad, "r", encoding="utf-8") as f:
        return geojson_features(json.load(f), crs_in, ziel)


# ----------------------------------------------------------------------------------------------
# OpenStreetMap (Overpass) - Nutzung, Strassen, Gewaesser und Baeume fuer beliebige Orte
# ----------------------------------------------------------------------------------------------

OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter", "https://overpass.openstreetmap.fr/api/interpreter"]
OSM_TIMEOUT = 40            # s je Server (Abfrage und Verbindung) - ein Rechteck von 1 km x 1 km braucht nur wenige Sekunden
OSM_CACHE_TAGE = 14
OSM_STAFFEL = 5.0           # s: so lange auf einen Overpass-Server warten, bevor der naechste parallel dazukommt

_OSM = {"tot": {}, "aus": False, "grund": "", "mem": {}, "sperre": threading.Lock()}


def osm_zuruecksetzen():
    """Zu Beginn eines Laufs: Server wieder zulassen (der Zwischenspeicher bleibt)."""
    with _OSM["sperre"]:
        _OSM["tot"], _OSM["aus"], _OSM["grund"] = {}, False, ""


def osm_abfragen(q, ctx, log, was="OpenStreetMap"):
    """Eine Overpass-Abfrage mit Schutz vor Haengern: kurze Zeitlimits, mehrere Spiegelserver, ein ausgefallener Server wird im
    restlichen Lauf nicht noch einmal versucht, und faellt der letzte aus, wird OpenStreetMap fuer den Rest des Laufs uebersprungen.
    Antworten (auch leere) kommen in den Zwischenspeicher. -> JSON-Antwort (dict) oder None"""
    schl = hashlib.sha1(q.encode("utf-8")).hexdigest()
    with _OSM["sperre"]:
        if schl in _OSM["mem"]:
            return _OSM["mem"][schl]
    datei = os.path.join(cache_ordner(), "osm_%s.json" % schl)
    try:
        if os.path.exists(datei) and time.time() - os.path.getmtime(datei) < OSM_CACHE_TAGE * 86400:
            with open(datei, "r", encoding="utf-8") as f:
                js = json.load(f)
            log("  %s: Antwort aus dem Zwischenspeicher (%d Objekte)" % (was, len(js.get("elements", []))))
            with _OSM["sperre"]:
                _OSM["mem"][schl] = js
            return js
    except Exception:
        pass
    if _OSM["aus"]:
        log("  %s: uebersprungen (%s)" % (was, _OSM["grund"]))
        return None
    # Gestaffelte Parallelabfrage: der erste Server startet sofort, jeder weitere nach OSM_STAFFEL Sekunden ohne Antwort; wer zuerst
    # antwortet, gewinnt. Statt 3 x 40 s Warten auf haengende Server hoechstens ~40 s.
    import queue as _queue
    kandidaten = [u for u in OVERPASS if u not in _OSM["tot"]]
    erg_q = _queue.Queue()
    fertig = {"ja": False}
    daten = urllib.parse.urlencode({"data": q}).encode("utf-8")

    def arbeit(url):
        t0 = time.time()
        try:
            req = urllib.request.Request(url, data=daten, headers={"User-Agent": "ZachariasTools/0.1 (+https://github.com/ZirkelZacharias/zacharias-tools)"})
            with urllib.request.urlopen(req, timeout=OSM_TIMEOUT, context=ctx) as r:
                js = json.loads(r.read().decode("utf-8"))
            if "elements" not in js:                       # Overpass meldet Zeitueberschreitung oft als 200 mit 'remark'
                raise ValueError(js.get("remark") or "Antwort ohne Daten")
            erg_q.put(("ok", url, js, time.time() - t0))
        except Exception as ex:
            erg_q.put(("fehler", url, ex, time.time() - t0))

    letzter, offen, naechster, t_letzter = None, 0, 0, 0.0
    while True:
        if naechster < len(kandidaten) and (offen == 0 or time.time() - t_letzter >= OSM_STAFFEL):
            threading.Thread(target=arbeit, args=(kandidaten[naechster],), daemon=True).start()
            naechster += 1
            offen += 1
            t_letzter = time.time()
        try:
            art, url, wert, dt_ = erg_q.get(timeout=0.25)
        except _queue.Empty:
            if offen == 0 and naechster >= len(kandidaten):
                break
            continue
        offen -= 1
        if art == "ok":
            fertig["ja"] = True
            js = wert
            log("  %s: %s antwortete nach %.1f s (%d Objekte)" % (was, url.split("/")[2], dt_, len(js["elements"])))
            with _OSM["sperre"]:
                _OSM["mem"][schl] = js
            try:
                with open(datei + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(js, f)
                os.replace(datei + ".tmp", datei)
            except OSError:
                pass
            return js
        e = wert
        letzter = e
        ssl_fehler = isinstance(e, ssl.SSLError) or "CERTIFICATE" in str(e).upper()
        log("  %s: %s nicht erreichbar nach %.0f s (%s)%s" % (was, url.split("/")[2], dt_, str(e)[:80],
                                                          "" if ssl_fehler else " - wird in diesem Lauf nicht mehr versucht"))
        if ssl_fehler:
            log("  SSL-Problem -> pip install truststore, oder unter 'Erweitert' CA-Datei angeben.")
            with _OSM["sperre"]:
                _OSM["aus"], _OSM["grund"] = True, "SSL-Problem"
            return None
        with _OSM["sperre"]:
            _OSM["tot"][url] = str(e)
        if offen == 0 and naechster >= len(kandidaten):
            break
        if offen == 0:
            t_letzter = 0.0                                # nichts mehr unterwegs: sofort den naechsten Server nehmen
    with _OSM["sperre"]:
        _OSM["aus"] = True
        _OSM["grund"] = "alle Overpass-Server fielen aus, zuletzt: %s" % str(letzter)[:80]
    log("  FEHLER beim Laden von %s: %s" % (was, letzter))
    log("  -> OpenStreetMap wird fuer den Rest dieses Laufs uebersprungen (kein weiteres Warten). Spaeter nochmal versuchen, "
        "oder Daten selbst als GeoJSON hinzufuegen.")
    return None
STRASSENBREITE = {"motorway": 14, "trunk": 12, "primary": 10, "secondary": 8, "tertiary": 7, "unclassified": 6,
                  "residential": 6, "living_street": 5, "service": 4, "road": 5, "track": 3, "footway": 2, "path": 1.5,
                  "pedestrian": 4, "cycleway": 2.5, "steps": 2, "bridleway": 2, "corridor": 2}
BAHNBREITE = 3.5


def osm_abfrage(s, w, n, e):
    bb = "(%.6f,%.6f,%.6f,%.6f)" % (s, w, n, e)
    nat = '["natural"~"^(wood|scrub|grassland|heath|wetland|water|bare_rock|sand|scree|beach)$"]'
    teile = ['way["landuse"]', 'relation["landuse"]', "way" + nat, "relation" + nat, 'way["leisure"]', 'relation["leisure"]',
             'way["waterway"="riverbank"]', 'relation["waterway"="riverbank"]', 'way["highway"]', 'way["area:highway"]',
             'relation["area:highway"]', 'way["railway"~"^(rail|light_rail|tram|subway|narrow_gauge|funicular)$"]',
             'way["amenity"="parking"]', 'relation["amenity"="parking"]', 'node["natural"="tree"]']
    return "[out:json][timeout:%d];(" % OSM_TIMEOUT + "".join(t + bb + ";" for t in teile) + ");out geom;"


def _osm_nutzart(t):
    for key in ("highway", "area:highway", "railway", "waterway", "natural", "landuse", "leisure", "amenity"):
        if key in t:
            return "%s=%s" % ("highway" if key == "area:highway" else key, t[key])
    return "osm"


def _osm_zahl(v):
    m = re.search(r"\d+(?:[.,]\d+)?", str(v))
    return float(m.group(0).replace(",", ".")) if m else None


def osm_zu_features(js, epsg):
    """Overpass-JSON ('out geom') -> (nutzung [(geom, props)], baeume [(Point, props)]) im Projekt-KBS."""
    from pyproj import Transformer
    from shapely.geometry import Point, LineString, Polygon
    from shapely.ops import polygonize
    tr = Transformer.from_crs("EPSG:4326", "EPSG:%d" % epsg, always_xy=True)

    def xy(geo):
        lon = [p["lon"] for p in geo]
        lat = [p["lat"] for p in geo]
        X, Y = tr.transform(lon, lat)
        return list(zip(X, Y))

    nutz, baeume = [], []
    for el in js.get("elements", []):
        t = el.get("tags") or {}
        typ = el.get("type")
        try:
            if typ == "node":
                if t.get("natural") == "tree":
                    x, y = tr.transform(el["lon"], el["lat"])
                    props = dict(t)
                    for k_neu, k_alt in (("kronendurchmesser", "diameter_crown"), ("baumhoehe", "height"),
                                         ("stammumfg", "circumference")):
                        v = _osm_zahl(t.get(k_alt)) if k_alt in t else None
                        if v:
                            props[k_neu] = v
                    baeume.append((Point(x, y), props))
            elif typ == "way" and el.get("geometry"):
                pts = xy(el["geometry"])
                props = dict(t, nutzart=_osm_nutzart(t))
                geschlossen = len(pts) >= 4 and pts[0] == pts[-1]
                if t.get("tunnel") in ("yes", "building_passage", "culvert") or t.get("highway") in ("proposed", "construction", "raceway"):
                    continue
                if "railway" in t:
                    nutz.append((LineString(pts).buffer(BAHNBREITE / 2, cap_style=2), props))
                elif "highway" in t and t.get("area") != "yes" and not (geschlossen and t["highway"] in ("pedestrian",) and t.get("area") == "yes"):
                    w = _osm_zahl(t.get("width")) or STRASSENBREITE.get(t["highway"], 4)
                    nutz.append((LineString(pts).buffer(w / 2, cap_style=2), props))
                elif geschlossen:
                    nutz.append((Polygon(pts), props))
            elif typ == "relation" and t.get("type") in ("multipolygon", None, "boundary"):
                aussen = [LineString(xy(m["geometry"])) for m in el.get("members", []) if m.get("role") == "outer" and m.get("geometry")]
                innen = [LineString(xy(m["geometry"])) for m in el.get("members", []) if m.get("role") == "inner" and m.get("geometry")]
                if not aussen:
                    continue
                pa = unary_union(list(polygonize(unary_union(aussen))))
                if innen:
                    pa = pa.difference(unary_union(list(polygonize(unary_union(innen)))))
                if not pa.is_empty:
                    nutz.append((pa, dict(t, nutzart=_osm_nutzart(t))))
        except Exception:
            continue
    return nutz, baeume


def osm_laden(bbox, epsg, cafile, unsicher, log=print):
    """Laedt Nutzung und Baeume fuer das Rechteck von Overpass. -> (nutzung, baeume) oder ([], [])"""
    from pyproj import Transformer
    xmin, ymin, xmax, ymax = bbox
    tr = Transformer.from_crs("EPSG:%d" % epsg, "EPSG:4326", always_xy=True)
    lons, lats = zip(*[tr.transform(x, y) for x in (xmin, xmax) for y in (ymin, ymax)])
    q = osm_abfrage(min(lats), min(lons), max(lats), max(lons))
    ctx = ssl_kontext(cafile, unsicher)
    js = osm_abfragen(q, ctx, log, "OpenStreetMap (Nutzung, Baeume)")
    if js is None:
        log("  -> Alternative: Daten selbst als GeoJSON speichern (z. B. QGIS/QuickOSM) und als Dateien hinzufuegen.")
        return [], []
    nutz, baeume = osm_zu_features(js, epsg)
    log("  OpenStreetMap: %d Flaechen/Strassen, %d Baeume" % (len(nutz), len(baeume)))
    return nutz, baeume


def bahn_achsen(d, cfg, log=print):
    """Gleisachsen (OSM: railway=rail/light_rail/subway/tram/narrow_gauge, ohne Tunnel) im Rechteck -> Liste von LineStrings (Projekt-KBS)
    oder None, wenn OpenStreetMap nicht erreichbar ist. Ergebnis wird an d gemerkt. Dieselbe Abfrage liefert auch die Bruecken
    (bridge=*, man_made=bridge) fuer die 2D-Plaene: d._osm_bruecken = [(Geometrie, Tags)] - eine Abfrage statt zwei."""
    if getattr(d, "_bahn_achsen", None) is not None:
        return d._bahn_achsen or None
    from pyproj import Transformer
    from shapely.geometry import LineString, Polygon
    from shapely.ops import linemerge
    xmin, ymin, xmax, ymax = d.bbox
    tr = Transformer.from_crs("EPSG:%d" % cfg.epsg, "EPSG:4326", always_xy=True)
    lons, lats = zip(*[tr.transform(x, y) for x in (xmin, xmax) for y in (ymin, ymax)])
    bb = "(%.6f,%.6f,%.6f,%.6f)" % (min(lats), min(lons), max(lats), max(lons))
    q = ("[out:json][timeout:%d];(way[\"railway\"~\"^(rail|light_rail|tram|subway|narrow_gauge|funicular)$\"]" % OSM_TIMEOUT) + bb + \
        ";way[\"bridge\"][\"bridge\"!=\"no\"][\"highway\"]" + bb + ";way[\"man_made\"=\"bridge\"]" + bb + ";);out geom;"
    js = osm_abfragen(q, ssl_kontext(cfg.cafile, cfg.unsicher), log, "OpenStreetMap (Gleisachsen, Bruecken)")
    d._osm_bruecken = []
    if js is None:
        return None                                              # nicht merken: der naechste Lauf versucht es erneut
    tr2 = Transformer.from_crs("EPSG:4326", "EPSG:%d" % cfg.epsg, always_xy=True)
    linien = []
    for el in js.get("elements", []):
        t = el.get("tags") or {}
        if el.get("type") != "way" or not el.get("geometry"):
            continue
        if t.get("tunnel") in ("yes", "building_passage", "culvert") or t.get("railway") in ("proposed", "construction", "abandoned", "disused"):
            continue
        X, Y = tr2.transform([p["lon"] for p in el["geometry"]], [p["lat"] for p in el["geometry"]])
        if len(X) < 2:
            continue
        xy = list(zip(X, Y))
        if t.get("railway"):
            linien.append(LineString(xy))
        if (t.get("bridge") and t.get("bridge") != "no" and (t.get("highway") or t.get("railway"))) or t.get("man_made") == "bridge":
            try:
                if t.get("man_made") == "bridge" and len(xy) >= 4 and xy[0] == xy[-1]:
                    g = Polygon(xy)
                    g = g if g.is_valid else g.buffer(0)
                else:
                    g = LineString(xy)
                if g.intersects(d.rect):
                    d._osm_bruecken.append((g, dict(t)))
            except Exception:
                pass
    if not linien:
        d._bahn_achsen = []
        return None
    netz = unary_union(linien).intersection(d.rect)
    netz = linemerge(netz) if netz.geom_type == "MultiLineString" else netz
    teile = [g for g in (list(netz.geoms) if hasattr(netz, "geoms") else [netz]) if g.geom_type == "LineString" and g.length > 0.5]
    d._bahn_achsen = teile
    log("  Gleisachsen (OpenStreetMap): %d Linien, %.0f m; Bruecken in OSM: %d" % (len(teile), sum(g.length for g in teile), len(d._osm_bruecken)))
    return teile or None


def wfs_gml_features(basis, typ, bbox, epsg, ctx, log, version="2.0.0"):
    """GetFeature im Standardformat (GML) fuer ein Rechteck -> [(Geometrie im Projekt-KBS, Attribute)]; Fehler werden geworfen."""
    crs = "urn:ogc:def:crs:EPSG::%d" % epsg
    q = {"SERVICE": "WFS", "VERSION": version, "REQUEST": "GetFeature", "SRSNAME": crs,
         "BBOX": "%.1f,%.1f,%.1f,%.1f,%s" % (bbox[0], bbox[1], bbox[2], bbox[3], crs)}
    q["TYPENAMES" if version.startswith("2") else "TYPENAME"] = typ
    url = basis + ("&" if "?" in basis else "?") + urllib.parse.urlencode(q, safe=":,")
    log("  WFS (GML): " + url)
    req = urllib.request.Request(url, headers={"User-Agent": "ZachariasTools/0.1 (+https://github.com/ZirkelZacharias/zacharias-tools)"})
    with urllib.request.urlopen(req, timeout=300, context=ctx) as r:
        daten = r.read()
    if re.search(rb"ExceptionReport|ServiceException", daten[:3000]):
        raise ValueError(re.sub(r"\s+", " ", daten[:400].decode("utf-8", errors="replace")))
    return _in_projekt(gml_features(daten), "", epsg)


def amtliche_nutzung(teil, cfg, d, log):
    """Tatsaechliche Nutzung eines Landes (ALKIS-WFS, Profil 'nutzung' in ifcmap_laender) -> [(Geometrie, Attribute)] im Rechteck."""
    ctx = ssl_kontext(cfg.cafile, cfg.unsicher)
    basis = teil["basis"]
    typen = [teil["typ"]] if teil.get("typ") else []
    if not typen:
        alle = wfs_typnamen(basis, ctx)
        typen = [t for t in alle if re.search(teil.get("muster", "nutzung"), t, re.I)]
        if not typen:
            log("  Der Dienst bietet keinen Datensatz mit '%s' an. Angebot: %s" % (teil.get("muster", "nutzung"), ", ".join(alle[:25])))
            return []
        log("  Datensaetze: %s" % ", ".join(typen[:6]))
    out = []
    for t in typen[:6]:
        try:
            fe = wfs_gml_features(basis, t, d.bbox, cfg.epsg, ctx, log, teil.get("version", "2.0.0"))
        except Exception as e:
            log("  %s: %s" % (t, str(e)[:300]))
            continue
        fe = [(shapely.make_valid(g).intersection(d.rect), p) for g, p in fe if g.geom_type in ("Polygon", "MultiPolygon")]
        fe = [(g, p) for g, p in fe if not g.is_empty and g.area > 1e-3]
        log("  %s: %d Flaechen im Rechteck" % (t, len(fe)))
        out += fe
    return out


# ----------------------------------------------------------------------------------------------
# Nutzungsarten zuordnen
# ----------------------------------------------------------------------------------------------

def _ist_id(v):
    return len(v) > 36 or re.fullmatch(r"[0-9a-fA-F-]{16,}", v) or re.fullmatch(r"[\d\.\-:T Z/]+", v)


ALKIS_CODES = {
    "41001": "Wohnbauflaeche", "41002": "Industrie und Gewerbeflaeche", "41003": "Halde", "41004": "Bergbaubetrieb",
    "41005": "Tagebau Grube Steinbruch", "41006": "Flaeche gemischter Nutzung",
    "41007": "Flaeche besonderer funktionaler Praegung", "41008": "Sport Freizeit und Erholungsflaeche",
    "41009": "Friedhof", "42001": "Strassenverkehr", "42002": "Weg", "42003": "Platz", "42009": "Bahnverkehr",
    "42015": "Flugverkehr", "42016": "Schiffsverkehr", "43001": "Landwirtschaft", "43002": "Wald", "43003": "Gehoelz",
    "43004": "Heide", "43005": "Moor", "43006": "Sumpf", "43007": "Unland Vegetationslose Flaeche",
    "44001": "Fliessgewaesser", "44005": "Hafenbecken", "44006": "Stehendes Gewaesser", "44007": "Meer",
}
RX_NUTZ_SCHLUESSEL = re.compile(r"nutz|bezeich|(^|_)art($|_)|funktion|objekt|klasse|schluessel|code")


def _wert_text(v):
    s = str(v).strip()
    if s in ALKIS_CODES:
        return "%s %s" % (s, ALKIS_CODES[s])
    return s


def nutzungstext(props):
    """Der Text, nach dem eine Nutzungsart erkannt und in der Tabelle angezeigt wird."""
    pref, rest = [], []
    for k, v in props.items():
        if v is None or isinstance(v, (bool, dict, list)):
            continue
        s = _wert_text(v)
        if not s:
            continue
        if RX_NUTZ_SCHLUESSEL.search(umlaute(k.lower())) and not (isinstance(v, str) and _ist_id(s) and s not in ALKIS_CODES.values()):
            pref.append(s)
        elif isinstance(v, str) and not _ist_id(s):
            rest.append(s)
    use = pref or rest
    uniq = list(dict.fromkeys(use))[:2]
    return " / ".join(uniq) or "(ohne Text)"


def auto_kategorie(text):
    t = umlaute(text.lower())
    for name, rx, aci, rgb in KATEGORIEN:
        if re.search(rx, t):
            return name
    return SONSTIGE[0]


def klassifiziere(nutz_feat, rect, overrides=None):
    """-> (regionen {Kategorie: Geometrie}, tabelle [(text, kategorie, anzahl, ha)])"""
    overrides = overrides or {}
    regionen, tab = {}, {}
    for geom, props in nutz_feat:
        if geom.geom_type not in ("Polygon", "MultiPolygon"):
            continue
        geom = shapely.make_valid(geom).intersection(rect)
        if geom.is_empty or geom.area < 1e-3:
            continue
        text = nutzungstext(props)
        kat = overrides.get(text) or auto_kategorie(text)
        regionen.setdefault(kat, []).append(geom)
        n, a, k = tab.get(text, (0, 0.0, kat))
        tab[text] = (n + 1, a + geom.area, kat)
    roh = {k: unary_union(v) for k, v in regionen.items()}
    regionen, belegt = {}, None
    for k in sorted(roh, key=lambda k: PRIORITAET.index(k) if k in PRIORITAET else -1):
        g = roh[k] if belegt is None else roh[k].difference(belegt)
        if g.is_empty or g.area < 1e-3:
            continue
        regionen[k] = g
        belegt = g if belegt is None else belegt.union(g)
    tabelle = sorted([(t, k, n, a / 1e4) for t, (n, a, k) in tab.items()], key=lambda r: -r[3])
    return regionen, tabelle


def feldwert(props, regex):
    for k, v in props.items():
        if re.search(regex, umlaute(k.lower())):
            try:
                x = float(str(v).replace(",", "."))
                if x > 0:
                    return x
            except ValueError:
                pass
    return None


def baeume_aus_features(features, rect):
    out = []
    for geom, props in features:
        if geom.geom_type == "MultiPoint":
            pts = list(geom.geoms)
        elif geom.geom_type == "Point":
            pts = [geom]
        else:
            continue
        for p in pts:
            if not rect.contains(p):
                continue
            kr = feldwert(props, r"krone.*(durch|dm|breite)|kronen.*(durch|dm)|krone|crown")
            ho = feldwert(props, r"hoehe|height")
            st = feldwert(props, r"stamm.*(durch|dm)|trunk.*diam")
            um = feldwert(props, r"stamm.*(umf|umg)|umfang|circumference")
            if kr and kr > 40:
                kr /= 100.0
            if ho and ho > 60:
                ho /= 100.0
            if st is None and um:
                st = (um / 100.0 if um > 3 else um) / math.pi
            if st and st > 3:
                st /= 100.0
            out.append((p.x, p.y, kr or BAUM_KRONE_STANDARD, ho or BAUM_HOEHE_STANDARD,
                        st or BAUM_STAMM_STANDARD, kr is not None))
    return out


def baeume_entdoppeln(baeume, abstand=1.5):
    if len(baeume) < 2:
        return baeume
    xy = np.array([[b[0], b[1]] for b in baeume])
    tree = cKDTree(xy)
    weg = set()
    for i, j in tree.query_pairs(abstand):
        weg.add(max(i, j))
    return [b for i, b in enumerate(baeume) if i not in weg]


# ----------------------------------------------------------------------------------------------
# Laden (fuer Vorschau und Export)
# ----------------------------------------------------------------------------------------------

_CACHE = {}


def _mt(pfade):
    out = []
    for p in pfade:
        try:
            out.append((p, os.path.getmtime(p), os.path.getsize(p)))
        except OSError:
            out.append((p, 0, 0))
    return tuple(out)


AUSGABE_DATEIEN = ("gelaende_punkte.xyz",)       # eigene Ausgaben von IFCmap - nie als Eingabe verwenden


COPERNICUS_URL = "https://copernicus-dem-30m.s3.amazonaws.com/%(n)s/%(n)s.tif"      # Copernicus GLO-30 (AWS Open Data), 1-Grad-Kacheln, Cloud-Optimized GeoTIFF
COPERNICUS_RASTER = 30.0


def copernicus_name(lat0, lon0):
    return "Copernicus_DSM_COG_10_%s%02d_00_%s%03d_00_DEM" % ("N" if lat0 >= 0 else "S", abs(lat0), "E" if lon0 >= 0 else "W", abs(lon0))


def copernicus_gelaende(cfg, d, log):
    """Notbehelf, wenn es fuer das Gebiet kein Gelaendemodell gibt: Copernicus GLO-30 (weltweit, 30 m). ACHTUNG: Das ist ein
    OBERFLAECHENmodell (Gebaeude und Baeume sind enthalten) mit wenigen Metern Genauigkeit - nur als grobe Orientierung gedacht.
    -> (px, py, pz) auf einem regelmaessigen Raster (30 m) ueber das ganze Rechteck oder None"""
    try:
        import rasterio
    except ImportError:
        log("  Notbehelf Copernicus GLO-30 nicht moeglich: das Paket 'rasterio' fehlt (pip install rasterio).")
        return None
    from pyproj import Transformer
    ctx = ssl_kontext(cfg.cafile, cfg.unsicher)
    rand = 120.0
    xa, ya, xb, yb = d.xmin - rand, d.ymin - rand, d.xmax + rand, d.ymax + rand
    t_ll = Transformer.from_crs("EPSG:%d" % cfg.epsg, "EPSG:4326", always_xy=True)
    t_pr = Transformer.from_crs("EPSG:4326", "EPSG:%d" % cfg.epsg, always_xy=True)
    ecken = [t_ll.transform(x, y) for x in (xa, xb) for y in (ya, yb)]
    lo0, lo1 = min(c[0] for c in ecken), max(c[0] for c in ecken)
    la0, la1 = min(c[1] for c in ecken), max(c[1] for c in ecken)
    X, Y, Z = [], [], []
    for lat0 in range(int(math.floor(la0)), int(math.floor(la1)) + 1):
        for lon0 in range(int(math.floor(lo0)), int(math.floor(lo1)) + 1):
            name = copernicus_name(lat0, lon0)
            ziel = os.path.join(cache_ordner(), name + ".tif")
            try:
                if not _datei_laden(COPERNICUS_URL % {"n": name}, ziel, ctx, log):
                    log("  Copernicus-Kachel %s gibt es nicht (Meer?)" % name)
                    continue
            except Exception as e:
                log("  Copernicus-Kachel %s nicht ladbar: %s" % (name, str(e)[:150]))
                continue
            try:
                with rasterio.open(ziel) as ds:
                    from rasterio.windows import Window, from_bounds
                    w = from_bounds(max(lo0, lon0), max(la0, lat0), min(lo1, lon0 + 1), min(la1, lat0 + 1), ds.transform)
                    w = Window(int(math.floor(w.col_off)) - 1, int(math.floor(w.row_off)) - 1, int(math.ceil(w.width)) + 3, int(math.ceil(w.height)) + 3)
                    w = w.intersection(Window(0, 0, ds.width, ds.height))
                    arr = ds.read(1, window=w).astype("float64")
                    tf = ds.window_transform(w)
                    nodata = ds.nodata
            except Exception as e:
                log("  Copernicus-Kachel %s nicht lesbar: %s" % (name, str(e)[:150]))
                continue
            rr, cc = np.indices(arr.shape)
            lon = tf.c + (cc + 0.5) * tf.a + (rr + 0.5) * tf.b
            lat = tf.f + (cc + 0.5) * tf.d + (rr + 0.5) * tf.e
            ok = np.isfinite(arr) & (arr > -500)
            if nodata is not None:
                ok &= arr != nodata
            x, y = t_pr.transform(lon[ok], lat[ok])
            X.append(np.asarray(x)); Y.append(np.asarray(y)); Z.append(arr[ok])
    if not X:
        return None
    X, Y, Z = np.concatenate(X), np.concatenate(Y), np.concatenate(Z)
    m = (X >= xa) & (X <= xb) & (Y >= ya) & (Y <= yb)
    X, Y, Z = X[m], Y[m], Z[m]
    if len(X) < 4:
        return None
    nx = max(2, int(math.ceil((d.xmax - d.xmin) / COPERNICUS_RASTER)) + 1)
    ny = max(2, int(math.ceil((d.ymax - d.ymin) / COPERNICUS_RASTER)) + 1)
    gx, gy = np.meshgrid(np.linspace(d.xmin, d.xmax, nx), np.linspace(d.ymin, d.ymax, ny))
    lin = LinearNDInterpolator(np.column_stack([X, Y]), Z)
    gz = lin(gx, gy)
    bad = ~np.isfinite(gz)
    if bad.any():
        gz[bad] = Z[cKDTree(np.column_stack([X, Y])).query(np.column_stack([gx[bad], gy[bad]]))[1]]
    return gx.ravel(), gy.ravel(), gz.ravel()


def _gelaende_laden(d, cfg, log, prog):
    """Gelaende lesen und ausduennen (mit Zwischenspeicher im Programm); setzt d.px/py/pz und d.z0."""
    d.px = d.py = d.pz = None
    if cfg.dgm and not cfg.mit_gelaende:
        log("Gelaende: wird in der 2D-Vorschau nicht geladen (erst beim Export, oder Haken 'Gelaende in der Vorschau').")
    if cfg.dgm and cfg.mit_gelaende:
        prog(0.05, "Gelaende lesen und ausduennen ...")
        log("Gelaende:")
        zone = (d.ce, d.cn, cfg.nah_breite, cfg.nah_hoehe, cfg.toleranz_fern, cfg.uebergang, cfg.fern_raster)
        key = ("dgm", _mt(cfg.dgm), d.bbox, cfg.toleranz, zone)
        if key not in _CACHE:
            _CACHE[key] = gelaende_ausduennen(cfg.dgm, d.xmin, d.xmax, d.ymin, d.ymax, cfg.toleranz, log, zone)
        else:
            log("  (aus Zwischenspeicher)")
        if _CACHE[key] is not None:
            d.px, d.py, d.pz = _CACHE[key]
    d.dgm_notfall = False
    if d.px is None and cfg.mit_gelaende and getattr(cfg, "dgm_notfall", True) and (cfg.ifc or cfg.xyz):
        prog(0.05, "Kein Gelaendemodell - Notbehelf Copernicus GLO-30 ...")
        log("Gelaende (Notbehelf):")
        log("  Es liegt kein Gelaendemodell fuer dieses Gebiet vor (keine Dateien, kein amtlicher Download) -> Copernicus GLO-30 (30 m).")
        try:
            r = copernicus_gelaende(cfg, d, log)
        except Exception as e:
            log("  Copernicus GLO-30 fehlgeschlagen: %s" % str(e)[:200])
            r = None
        if r is not None:
            d.px, d.py, d.pz = r
            d.dgm_notfall = True
            log("  WARNUNG: Das Gelaende stammt aus Copernicus GLO-30 - ein OBERFLAECHENmodell mit 30 m Raster (Gebaeude und Baeume sind im Gelaende "
                "enthalten, Hoehen auf wenige Meter genau). Nur als grobe Orientierung verwenden; bessere Daten (DGM1/DGM) bitte selbst hinzufuegen.")
            log("  Gelaendenetz: %d Punkte, Hoehen %.1f bis %.1f m" % (len(d.px), d.pz.min(), d.pz.max()))
        else:
            log("  Kein Notbehelf moeglich - die IFC enthaelt dann kein Gelaende.")
    d.z0 = cfg.z0 if cfg.z0 is not None else (float(math.floor(d.pz.min()) - 1) if d.pz is not None else 0.0)


def laender_kacheln(cfg, d, land, log, dgm=True, lod2=True):
    """Gelaende-/Gebaeude-Kacheln eines anderen Bundeslandes als Berlin holen (Modul ifcmap_laender). -> cfg mit den neuen Dateien"""
    import ifcmap_laender as L
    dn, ln, fehlt = L.kacheln_holen(cfg, land, d.bbox, log, sys.modules[__name__], dgm=dgm, lod2=lod2)
    d.laender_fehlt = list(getattr(d, "laender_fehlt", [])) + fehlt
    if dn or ln:
        cfg = replace(cfg, dgm=list(cfg.dgm) + dn, lod2=list(cfg.lod2) + ln)
    return cfg


def fgn_laden(cfg, d, log):
    """Berliner Fussgaengernetz (Mittellinien der Fusswege, auch entlang von Strassen) -> Liste LineString (absolute Koordinaten) oder None.
    Der Name des Feature-Typs wird aus den GetCapabilities gelesen (er ist nicht fest verdrahtet)."""
    ctx = ssl_kontext(cfg.cafile, cfg.unsicher)
    try:
        namen = wfs_typnamen(WFS_FGN, ctx)
    except Exception as e:
        log("  Fussgaengernetz: Dienst nicht erreichbar (%s)" % str(e)[:150])
        return None
    kand = [n for n in namen if not re.search(r"knoten|punkt|node|point", n.lower())]
    kand.sort(key=lambda n: (not re.search(r"fussgaenger|fgn|fuss", umlaute(n.lower())), not re.search(r"netz|kante|abschnitt|linie|strecke", n.lower())))
    log("  Fussgaengernetz: Feature-Typen des Dienstes: %s" % ", ".join(namen[:12]))
    for typ in kand[:3]:
        obj = wfs_laden(WFS_FGN, typ, d.bbox, cfg.cafile, cfg.unsicher, log)
        if not obj:
            continue
        linien = []
        n_quer_attr = 0
        for g, props in geojson_features(obj, "", cfg.epsg):
            lage = ""
            for k, v in (props or {}).items():
                if str(k).lower() == "el_lage":
                    lage = str(v).strip().lower()
            if lage in INDOOR_FGN_WERTE:
                continue
            if any(FGN_QUERUNG_RX.search(umlaute(str(v).lower())) for v in (props or {}).values() if isinstance(v, str)):
                n_quer_attr += 1                          # Dienst kennzeichnet die Linie selbst als Querung / Ueberweg
                continue
            g = shapely.make_valid(g).intersection(d.rect)
            if g.is_empty:
                continue
            for ln in ([g] if g.geom_type == "LineString" else [x for x in getattr(g, "geoms", []) if x.geom_type == "LineString"]):
                if ln.length > 0.5:
                    linien.append(ln)
        if linien:
            log("  Fussgaengernetz %s: %d Linien im Rechteck%s" % (typ, len(linien),
                ("; %d als Querung/Ueberweg gekennzeichnete Linien ausgelassen" % n_quer_attr) if n_quer_attr else ""))
            return linien
    log("  Fussgaengernetz: keine Linien gefunden")
    return None


INDOOR_FGN_WERTE = {"ifgt", "ifgz", "iga", "ikga", "ivbz", "unbk"}
FGN_QUERUNG_RX = re.compile(r"querung|ueberweg|ueberquerung|zebra|furt\b|crossing")


class Vorab:
    """Netzwerkabfragen im Hintergrund starten, waehrend lokal Dateien gelesen werden. Die Protokollzeilen eines Hintergrundjobs
    werden gepuffert und erst beim Abholen ausgegeben (kein Durcheinander im Protokoll)."""

    def __init__(self, log):
        from concurrent.futures import ThreadPoolExecutor
        self.pool = ThreadPoolExecutor(max_workers=6)
        self.f = {}
        self.fertig = {}
        self.log = log

    def start(self, key, fn):
        puffer = []

        def lauf():
            t0 = time.time()
            r = fn(puffer.append)
            puffer.append("    (%.1f s, im Hintergrund)" % (time.time() - t0))
            return r
        self.f[key] = (self.pool.submit(lauf), puffer)

    def hole(self, key, fn):
        """Ergebnis des Hintergrundjobs (wartet, falls noch noetig); ohne Job: direkt aufrufen. Ein zweites Abholen liefert dasselbe Ergebnis."""
        if key in self.fertig:
            return self.fertig[key]
        if key in self.f:
            fut, puffer = self.f.pop(key)
            try:
                r = fut.result()
            finally:
                for z in puffer:
                    self.log(z)
            self.fertig[key] = r
            return r
        return fn(self.log)

    def ende(self):
        for key in list(self.f):
            fut, puffer = self.f.pop(key)
            try:
                fut.result()
            except Exception:
                pass
        self.pool.shutdown(wait=False)


def lade(cfg, log=print, prog=_noop):
    d = Daten()
    d.zeiten = []
    t_lade = time.time()
    osm_zuruecksetzen()
    if any(os.path.basename(p).lower() in AUSGABE_DATEIEN for p in cfg.dgm):
        log("HINWEIS: gelaende_punkte.xyz ist eine Ausgabedatei von IFCmap und wird nicht als Gelaende gelesen.")
        cfg = replace(cfg, dgm=[p for p in cfg.dgm if os.path.basename(p).lower() not in AUSGABE_DATEIEN])
    import ifcmap_laender as L
    cfg, d.land = L.vorbereiten(cfg, sys.modules[__name__], log)
    d.cfg = cfg
    d.ce, d.cn, d.xmin, d.xmax, d.ymin, d.ymax = rechteck(cfg)
    d.rect = box(d.xmin, d.ymin, d.xmax, d.ymax)
    d.bbox = (d.xmin, d.ymin, d.xmax, d.ymax)
    d.nah_rect = box(d.ce - cfg.nah_breite / 2, d.cn - cfg.nah_hoehe / 2, d.ce + cfg.nah_breite / 2, d.cn + cfg.nah_hoehe / 2).intersection(d.rect)
    _db, _dh = detail_masse(cfg)
    d.detail_rect = box(d.ce - _db / 2, d.cn - _dh / 2, d.ce + _db / 2, d.cn + _dh / 2).intersection(d.rect)
    d.mittel_aktiv = (_db, _dh) != (float(cfg.nah_breite), float(cfg.nah_hoehe))
    d.baum_zone = d.detail_rect if d.mittel_aktiv else \
        box(*d.nah_rect.bounds).buffer(max(0.0, float(cfg.uebergang or 0.0)), join_style=2).intersection(d.rect)     # Nahbereich + Uebergangszone (ohne Mittelbereich)
    d.baum_rect = d.baum_zone if cfg.baeume_nur_nah else d.rect
    d.baum_bbox = d.baum_rect.bounds
    d.e0, d.n0 = cfg.e0n0 if cfg.e0n0 else (round(d.ce / 1000) * 1000, round(d.cn / 1000) * 1000)
    log("Mitte (EPSG:%d): Ost %.1f  Nord %.1f   Rechteck %.0f x %.0f m   E0=%.0f N0=%.0f"
        % (cfg.epsg, d.ce, d.cn, d.xmax - d.xmin, d.ymax - d.ymin, d.e0, d.n0))
    if cfg.test:
        log("TESTAUSSCHNITT %.0f x %.0f m" % (d.xmax - d.xmin, d.ymax - d.ymin))

    kp = kacheln_pruefen(cfg)
    if (cfg.online_dgm or cfg.online_lod2) and kp["aktiv"] and cfg.epsg == 25833 and ist_berlin(cfg) \
            and (kp["dgm_fehlt"] or kp["lod_fehlt"]):
        if kp["dgm_unbenannt"] and cfg.online_dgm and kp["dgm_fehlt"]:
            log("  HINWEIS: %d Gelaendedatei(en) ohne Berliner Kachelnamen (%s) - die fehlenden Berliner Kacheln werden trotzdem geholt. "
                "Haken 'DGM1 automatisch herunterladen' abschalten, wenn diese Dateien das Gebiet schon abdecken."
                % (len(kp["dgm_unbenannt"]), ", ".join(os.path.basename(p) for p in kp["dgm_unbenannt"][:4])))
        prog(0.02, "Kacheln herunterladen ...")
        dn, ln, geholt = kacheln_online_holen(replace(cfg, online_dgm=cfg.online_dgm and cfg.mit_gelaende), kp, log)
        if dn or ln:
            cfg = replace(cfg, dgm=list(cfg.dgm) + dn, lod2=list(cfg.lod2) + ln)
            d.cfg = cfg
            kp = dict(kp, dgm_fehlt=[n for n in kp["dgm_fehlt"] if n not in geholt],
                      lod_fehlt=[n for n in kp["lod_fehlt"] if n not in geholt])
    d.laender_fehlt = []
    if d.land and d.land != "berlin" and (cfg.online_dgm or cfg.online_lod2):
        cfg = laender_kacheln(cfg, d, d.land, log, dgm=cfg.online_dgm and cfg.mit_gelaende, lod2=cfg.online_lod2)
        d.cfg = cfg
    d.kacheln = kp
    if not kp["aktiv"] and d.land in (None, "keins", "berlin"):
        log("  (Kachelpruefung nur fuer Berliner Daten - bitte selbst darauf achten, dass die Dateien das Gebiet abdecken)")
    for n in (kp["dgm_fehlt"] if cfg.mit_gelaende else []):
        log("  FEHLT: DGM-Kachel %s (Gelaende dort unvollstaendig)" % n)
    for n in kp["lod_fehlt"]:
        log("  FEHLT: LoD2-Kachel %s (Gebaeude dort unvollstaendig)" % n)

    def zeit(name, t0):
        d.zeiten.append((name, time.time() - t0))

    # Quelle fuer Nutzung/Baeume - steht schon jetzt fest, damit die Abfragen im Hintergrund laufen koennen, waehrend Dateien gelesen werden
    quelle = cfg.quelle
    pr = {}
    if quelle in ("auto", "berlin"):
        import ifcmap_laender as L
        pr = (L.profile().get(d.land) or {}) if d.land else {}
        if ist_berlin(cfg) and cfg.epsg == 25833:
            quelle = "berlin"
            log("Quelle fuer Nutzung/Baeume (automatisch): Berliner ALKIS und Baumbestand (amtlich)")
        elif pr.get("nutzung"):
            quelle = "amtlich_land"
            log("Quelle fuer Nutzung (automatisch): amtliche ALKIS-Daten %s; Baeume: OpenStreetMap" % pr.get("name", d.land))
        else:
            quelle = "osm"
            log("Quelle fuer Nutzung/Baeume (automatisch): fuer dieses Gebiet ist kein amtlicher Dienst hinterlegt -> OpenStreetMap")
    vorab = Vorab(log)
    ctxargs = (cfg.cafile, cfg.unsicher)
    if quelle == "berlin":
        if not cfg.nutzung_dateien:
            vorab.start("nutz", lambda lg: wfs_laden(WFS_ALKIS, WFS_NUTZUNG_TYP, d.bbox, *ctxargs, lg))
        if not cfg.baum_dateien:
            for typ in WFS_BAUM_TYPEN:
                vorab.start("baum:" + typ, lambda lg, typ=typ: wfs_laden(WFS_BAEUME, typ, d.baum_bbox, *ctxargs, lg))
        if cfg.alkis_zusatz:
            for name, typ in WFS_ALKIS_ZUSATZ:
                if not (name == "Gebaeude" and cfg.lod2_luecken):
                    vorab.start("zusatz:" + name, lambda lg, typ=typ: wfs_laden(WFS_ALKIS, typ, d.bbox, *ctxargs, lg))
    elif quelle == "amtlich_land" and not cfg.nutzung_dateien and pr.get("nutzung"):
        vorab.start("amtlich", lambda lg: amtliche_nutzung(pr["nutzung"], cfg, d, lg))
    if (quelle == "osm" and not cfg.nutzung_dateien) or (quelle in ("osm", "amtlich_land") and not cfg.baum_dateien):
        vorab.start("osm", lambda lg: osm_laden(d.bbox, cfg.epsg, cfg.cafile, cfg.unsicher, lg))
    import ifcmap_markant as M
    berlin_amtlich = quelle == "berlin"
    d.osm_geb, d.denkmal, d.luecken = None, None, []
    if (cfg.markant and cfg.markant_osm) or cfg.lod2_luecken:
        vorab.start("osm_geb", lambda lg: M.osm_gebaeude_laden(d, cfg, lg))
    if cfg.markant and cfg.markant_denkmal and berlin_amtlich:
        vorab.start("denkmal", lambda lg: denkmal_flaechen(cfg, d, lg))
    if cfg.lod2_luecken and berlin_amtlich and not cfg.nutzung_dateien:
        vorab.start("zusatz:Gebaeude", lambda lg: wfs_laden(WFS_ALKIS, "alkis:gebaeudeflaechen", d.bbox, *ctxargs, lg))
    brauche_fgn = berlin_amtlich and getattr(cfg, "buergersteige", "") == "fgn" and "lageplan" in (getattr(cfg, "dxf_plaene", None) or [])
    if brauche_fgn:
        vorab.start("fgn", lambda lg: fgn_laden(cfg, d, lg))
    brauche_bahn = bool(set(getattr(cfg, "dxf_plaene", None) or []) & {"lageplan", "schwarzplan"})
    if brauche_bahn:                                           # Gleisachsen + Bruecken (OSM) jetzt im Hintergrund holen, nicht erst beim Export
        vorab.start("bahn", lambda lg: bahn_achsen(d, cfg, lg))
    if len(vorab.f):
        log("Netzabfragen (%s) laufen im Hintergrund, waehrend Dateien gelesen werden." % ", ".join(sorted({k.split(":")[0] for k in vorab.f})))

    # Gelaende
    t0 = time.time()
    _gelaende_laden(d, cfg, log, prog)
    zeit("Gelaende lesen und ausduennen", t0)

    # Gebaeude
    d.teile, d.near, d.far = [], [], []
    nahp = (d.ce, d.cn) + detail_masse(cfg)
    if cfg.lod2:
        t0 = time.time()
        prog(0.35, "Gebaeude lesen ...")
        log("Gebaeude (LoD2):")
        behalte = M.behalte_parameter(cfg, log) if cfg.markant else None
        if behalte is not None and cfg.markant_osm:                      # Fernbereich: OSM-/Denkmal-Flaechen vorher abholen
            try:
                fl = []
                osm_g = vorab.hole("osm_geb", lambda lg: M.osm_gebaeude_laden(d, cfg, lg))
                if osm_g:
                    fl += [o["geom"] for o in osm_g["objekte"] if M.osm_kriterium([o]) or M.osm_denkmal([o])]
                dk = vorab.hole("denkmal", lambda lg: None) if cfg.markant_denkmal and berlin_amtlich else None
                if dk:
                    fl += dk["geoms"]
                behalte["flaechen"] = M.flaechen_aus(fl)
            except Exception as e:
                log("  HINWEIS: OSM-/Denkmal-Flaechen fuer den Fernbereich nicht verfuegbar (%s)" % str(e)[:100])
        key = ("lod", _mt(cfg.lod2) if not any(os.path.isdir(p) for p in cfg.lod2) else tuple(cfg.lod2), d.bbox, nahp, cfg.fern_gebaeude,
               repr(None if behalte is None else (behalte["punkte"], behalte["dach"], len(behalte["flaechen"]["geoms"]) if behalte.get("flaechen") else 0)))
        if key not in _CACHE:
            _CACHE[key] = lod2_lesen(cfg.lod2, d.xmin, d.xmax, d.ymin, d.ymax, log, prog, nahp, cfg.fern_gebaeude, behalte)
        else:
            log("  (aus Zwischenspeicher)")
        d.teile = list(_CACHE[key])
        zeit("Gebaeude (LoD2) lesen", t0)
    # Luecken im LoD2 (oder gar kein LoD2): OSM-Gebaeude/Dachformen, ALKIS-Grundrisse
    if cfg.lod2_luecken:
        t0 = time.time()
        log("Luecken im LoD2:")
        osm_g = vorab.hole("osm_geb", lambda lg: M.osm_gebaeude_laden(d, cfg, lg))
        d.osm_geb = osm_g
        alk = None
        if berlin_amtlich:
            o = vorab.hole("zusatz:Gebaeude", lambda lg: wfs_laden(WFS_ALKIS, "alkis:gebaeudeflaechen", d.bbox, cfg.cafile, cfg.unsicher, lg))
            if o:
                alk = [(g, p) for g, p in geojson_features(o, "", cfg.epsg) if g.geom_type in ("Polygon", "MultiPolygon")]
        d.alk_geb = alk
        try:
            import ifcmap_luecken as LK
            d.ua_geb = None
            if getattr(cfg, "ua_gebaeudehoehen", False):
                if berlin_amtlich:
                    try:
                        import ifcmap_umweltatlas as UA
                        d.ua_geb = UA.gebaeudehoehen_laden(sys.modules[__name__], cfg, d, log)
                    except Exception as e:
                        log("  Umweltatlas-Gebaeudehoehen nicht verfuegbar (%s) - Hoehen werden wie sonst geschaetzt" % str(e)[:120])
                else:
                    log("  Umweltatlas-Gebaeudehoehen gibt es nur fuer Berlin - uebersprungen")
            LK.luecken_fuellen(d, cfg, log, osm_g, alk, nahp, cfg.fern_gebaeude)
        except Exception as e:
            import traceback
            log("  FEHLER beim Fuellen der LoD2-Luecken (uebersprungen): %s" % e)
            log(traceback.format_exc()[-600:])
        zeit("LoD2-Luecken (OSM/ALKIS)", t0)
    elif cfg.markant and cfg.markant_osm:
        d.osm_geb = vorab.hole("osm_geb", lambda lg: M.osm_gebaeude_laden(d, cfg, lg))
    if cfg.markant and cfg.markant_denkmal and berlin_amtlich:
        try:
            d.denkmal = vorab.hole("denkmal", lambda lg: denkmal_flaechen(cfg, d, lg))
        except Exception as e:
            log("  HINWEIS: Denkmalkarte nicht verfuegbar (%s)" % str(e)[:100])
    ohne_grund = 0
    for t in d.teile:
        if nah_enthaelt(cfg, d, t["c"][0], t["c"][1]):
            d.near.append(t)
        elif t["ground"]:
            d.far.append(t)
        else:
            ohne_grund += 1
    if d.teile and d.px is not None:
        try:
            gelaende_an_gebaeuden(d, log)
        except Exception as e:
            log("  HINWEIS: Pruefung Gelaende gegen Gebaeude-Oberkanten uebersprungen: %s" % e)
    if d.teile:
        log("  Gebaeude gesamt: %d Teile - %s (Rechteck %.0f x %.0f m): %d, Fernbereich: %d%s"
            % (len(d.teile), "Nah- und Mittelbereich" if d.mittel_aktiv else "Nahbereich", detail_masse(cfg)[0], detail_masse(cfg)[1], len(d.near), len(d.far),
               (", %d Fernbereich-Teile ohne Grundflaeche im LoD2 uebersprungen" % ohne_grund) if ohne_grund else ""))
        quellen = {}
        for t in d.teile:
            quellen[t.get("quelle", "LoD2")] = quellen.get(t.get("quelle", "LoD2"), 0) + 1
        log("  Quellen der Gebaeude: " + ", ".join("%s %d" % kv for kv in sorted(quellen.items())))

    # Nutzung / Baeume
    t0 = time.time()
    d.nutz_feat, baum_feat = [], []
    osm = {}

    def osm_daten():
        if "r" not in osm:
            osm["r"] = vorab.hole("osm", lambda lg: osm_laden(d.bbox, cfg.epsg, cfg.cafile, cfg.unsicher, lg))
        return osm["r"]
    prog(0.6, "Nutzungsflaechen laden ...")
    if cfg.nutzung_dateien:
        log("Nutzungsflaechen (Dateien):")
        for p in cfg.nutzung_dateien:
            d.nutz_feat += lese_geojson(p, cfg.eingabe_crs, cfg.epsg)
    elif quelle == "berlin":
        log("Nutzungsflaechen (Berliner WFS):")
        obj = vorab.hole("nutz", lambda lg: wfs_laden(WFS_ALKIS, WFS_NUTZUNG_TYP, d.bbox, cfg.cafile, cfg.unsicher, lg))
        if obj is None:
            log("  WARNUNG: Berliner ALKIS nicht erreichbar - Ersatz: OpenStreetMap")
            quelle = "osm"
            log("Nutzungsflaechen (OpenStreetMap, Ersatz):")
            d.nutz_feat = osm_daten()[0]
        else:
            d.nutz_feat = geojson_features(obj, "", cfg.epsg)
    elif quelle == "amtlich_land":
        log("Nutzungsflaechen (amtlich, ALKIS-WFS %s):" % pr.get("name", d.land))
        try:
            d.nutz_feat = vorab.hole("amtlich", lambda lg: amtliche_nutzung(pr["nutzung"], cfg, d, lg))
        except Exception as e:
            log("  FEHLER: %s" % e)
            d.nutz_feat = []
        if not d.nutz_feat:
            log("  WARNUNG: der amtliche Dienst lieferte keine verwertbaren Nutzungsflaechen - Ersatz: OpenStreetMap")
            quelle = "osm"
            log("Nutzungsflaechen (OpenStreetMap, Ersatz):")
            d.nutz_feat = osm_daten()[0]
    elif quelle == "osm":
        log("Nutzungsflaechen (OpenStreetMap):")
        d.nutz_feat = osm_daten()[0]
    if d.nutz_feat:
        log("  %d Nutzungsobjekte; Attribute (Beispiel): %s"
            % (len(d.nutz_feat), {k: v for k, v in list(d.nutz_feat[0][1].items())[:10]}))
    if getattr(cfg, "rad_wege", False):
        if ist_berlin(cfg) and cfg.epsg == 25833:
            try:
                n_rad = rad_als_nutzung(cfg, d, ssl_kontext(cfg.cafile, cfg.unsicher), log)
                d.nutz_feat = list(d.nutz_feat) + n_rad
            except Exception as e:
                log("  Radverkehrsnetz als Wegequelle nicht moeglich (%s) - Wege bleiben wie in der Nutzung" % str(e)[:140])
        else:
            log("  Radverkehrsnetz gibt es nur fuer Berlin - uebersprungen")
    prog(0.75, "Baeume laden ...")
    d.baeume_aus_osm = False
    if cfg.baum_dateien:
        log("Baeume (Dateien):")
        for p in cfg.baum_dateien:
            baum_feat += lese_geojson(p, cfg.eingabe_crs, cfg.epsg)
    elif quelle == "berlin":
        log("Baeume (Berliner WFS):")
        antworten = []
        for typ in WFS_BAUM_TYPEN:
            o = vorab.hole("baum:" + typ, lambda lg, typ=typ: wfs_laden(WFS_BAEUME, typ, d.baum_bbox, cfg.cafile, cfg.unsicher, lg))
            antworten.append(o)
            baum_feat += geojson_features(o, "", cfg.epsg)
        if not baum_feat:
            o = wfs_laden(WFS_ALKIS, WFS_VEG_PUNKTE_TYP, d.baum_bbox, cfg.cafile, cfg.unsicher, log)
            antworten.append(o)
            vp = geojson_features(o, "", cfg.epsg)
            baum_feat = [x for x in vp if re.search(r"baum", umlaute(" ".join(str(v) for v in x[1].values()).lower()))]
        if not baum_feat and all(o is None for o in antworten):
            log("  WARNUNG: Berliner Baumbestand nicht erreichbar - Ersatz: OpenStreetMap")
            baum_feat = osm_daten()[1]
            d.baeume_aus_osm = True
    elif quelle in ("osm", "amtlich_land"):
        log("Baeume (OpenStreetMap):")
        baum_feat = osm_daten()[1]
    if baum_feat:
        log("  %d Baumobjekte; Attribute (Beispiel): %s" % (len(baum_feat), {k: v for k, v in list(baum_feat[0][1].items())[:10]}))
    d.baeume = baeume_entdoppeln(baeume_aus_features(baum_feat, d.baum_rect)) if baum_feat else []
    # Weitere Quellen fuer den Baumbestand: amtlich zuerst (Kataster -> Umweltatlas-Raster), OpenStreetMap nur fuer den Rest
    osm_extra = None
    if quelle == "berlin" and getattr(cfg, "osm_ergaenzen", True) and not cfg.baum_dateien and not d.baeume_aus_osm:
        try:
            osm_extra = baeume_aus_features(osm_daten()[1], d.baum_rect)
        except Exception as e:
            log("  OpenStreetMap-Baeume zur Ergaenzung nicht verfuegbar (%s)" % str(e)[:100])
    if (getattr(cfg, "ua_vegetationsraster", False) or getattr(cfg, "ua_vegetationshoehen", False) or osm_extra) and (d.baeume or osm_extra):
        if ist_berlin(cfg) and cfg.epsg == 25833:
            try:
                import ifcmap_umweltatlas as UA
                UA.baeume_ergaenzen(sys.modules[__name__], cfg, d, log, osm_extra=osm_extra)
            except Exception as e:
                import traceback
                log("  Baum-Ergaenzung (Umweltatlas/OpenStreetMap) nicht moeglich (%s) - Baeume bleiben wie geladen" % str(e)[:140])
                log(traceback.format_exc()[-400:])
        else:
            log("  Umweltatlas-Vegetationsdaten gibt es nur fuer Berlin - uebersprungen")
    if d.baeume:
        log("  Baeume im %s: %d (davon %d mit Kronendurchmesser aus den Daten, Rest Standard %.0f m)"
            % ("Nahbereich samt Uebergangszone" if cfg.baeume_nur_nah else "Rechteck", len(d.baeume), sum(1 for b in d.baeume if b[5]), BAUM_KRONE_STANDARD))
    # ALKIS-Zusatzdaten (nur Berlin) fuer die 2D-Blaetter
    d.zusatz = {}
    if cfg.alkis_zusatz and quelle == "berlin":
        prog(0.85, "ALKIS-Zusatzdaten laden ...")
        log("ALKIS-Zusatzdaten (Berliner WFS):")
        for name, typ in WFS_ALKIS_ZUSATZ:
            fe = geojson_features(vorab.hole("zusatz:" + name, lambda lg, typ=typ: wfs_laden(WFS_ALKIS, typ, d.bbox, cfg.cafile, cfg.unsicher, lg)),
                                  "", cfg.epsg)
            fe = [(shapely.make_valid(g).intersection(d.rect), p) for g, p in fe if g.geom_type in ("Polygon", "MultiPolygon")]
            fe = [(g, p) for g, p in fe if not g.is_empty and g.area > 1e-3]
            if fe:
                d.zusatz[name] = fe
                log("  %s: %d Objekte; Attribute (Beispiel): %s" % (name, len(fe), dict(list(fe[0][1].items())[:8])))
    d.fgn = None
    d.fgn_versucht = bool(brauche_fgn)
    if brauche_fgn:
        try:
            d.fgn = vorab.hole("fgn", lambda lg: fgn_laden(cfg, d, lg))
        except Exception as e:
            log("  HINWEIS: Fussgaengernetz nicht verfuegbar (%s)" % str(e)[:100])
    if brauche_bahn:
        try:
            vorab.hole("bahn", lambda lg: bahn_achsen(d, cfg, lg))
        except Exception as e:
            log("  HINWEIS: Gleisachsen/Bruecken nicht vorab geladen (%s)" % str(e)[:100])
    vorab.ende()
    zeit("Nutzung, Baeume, ALKIS (Netz, ueberlappt mit dem Lesen)", t0)
    d.markant, d.markant_ids = [], set()
    if cfg.markant and d.teile:
        import ifcmap_markant as M
        prog(0.9, "Markante Gebaeude ...")
        t0 = time.time()
        try:
            M.verbessern(d, cfg, log, prog)
        except Exception as e:
            import traceback
            log("  FEHLER bei den markanten Gebaeuden (uebersprungen, Gebaeude bleiben wie im LoD2): %s" % e)
            log(traceback.format_exc()[-600:])
            d.markant, d.markant_ids = [], set()
        zeit("Markante Gebaeude", t0)
    d.extra = {}
    if cfg.extra:
        t0 = time.time()
        d.extra = extra_laden(cfg, d, log, prog)
        zeit("Zusatzdaten (Denkmal, OePNV ...)", t0)
    zuordnen(d)
    d.warnungen = []
    if cfg.mit_gelaende and d.px is None and (cfg.dgm or (kp["aktiv"] and kp["dgm_fehlt"])):
        d.warnungen.append("Es wurden KEINE Gelaendedaten im Rechteck gefunden - die IFC enthaelt dann kein Gelaende. "
                           "Passen Dateien und Mittelpunkt zusammen? (Bei Berlin: Haken 'DGM1 automatisch herunterladen')")
    if getattr(d, "dgm_notfall", False):
        d.warnungen.append("Gelaende NUR als Notbehelf aus Copernicus GLO-30 (30 m, Oberflaechenmodell inkl. Gebaeude/Baeume, Hoehen auf wenige Meter genau) - "
                           "kein DGM fuer dieses Gebiet gefunden.")
    lod2_da = any(t.get("quelle", "LoD2") == "LoD2" for t in d.teile)
    ersatz = bool(d.teile) and not lod2_da
    d.hinweise = []
    if not d.teile and (cfg.lod2 or (kp["aktiv"] and kp["lod_fehlt"]) or cfg.lod2_luecken):
        d.warnungen.append("Es wurden KEINE Gebaeude im Rechteck gefunden (weder LoD2 noch OpenStreetMap/ALKIS). Fehlende Kacheln siehe Protokoll; "
                           "ist OpenStreetMap nicht erreichbar, spaeter nochmal versuchen.")
    if ersatz:
        d.hinweise.append("Fuer dieses Gebiet gibt es kein LoD2 - alle Gebaeude stammen aus OpenStreetMap%s (Hoehen teils geschaetzt, "
                          "siehe Eigenschaft 'Quelle' der Gebaeude in der IFC)." % (" und ALKIS" if any(str(t.get("quelle")).startswith("ALKIS") for t in d.teile) else ""))
    for w in getattr(d, "laender_fehlt", []):
        if ersatz and "LoD2" in w:
            d.hinweise.append("Kein automatischer LoD2-Download fuer dieses Bundesland - Ersatz: OpenStreetMap-Gebaeude. (" + w[:160] + ")")
        else:
            d.warnungen.append("Bundesland-Download: " + w)
    for w in d.warnungen:
        log("WARNUNG: " + w)
    for w in d.hinweise:
        log("HINWEIS: " + w)
    prog(1.0, "Daten geladen")
    d.zeiten.append(("Laden insgesamt", time.time() - t_lade))
    log("Zeiten: " + "; ".join("%s %.0f s" % z for z in d.zeiten))
    return d


GELAENDE_UEBER_TOL = 0.10      # m: Gelaende muss mindestens so viel ueber der Gebaeude-Oberkante liegen, damit dort geschnitten wird


def _ueber_hoehe(xy, z, hoehe):
    """Teil eines Gelaende-Dreiecks (xy (3,2), z (3,)), der hoeher als `hoehe` liegt -> Polygon oder None (Dreieck an der Ebene z = hoehe abgeschnitten)"""
    v = z - hoehe
    if v.max() <= 0:
        return None
    pts = []
    for i in range(3):
        j = (i + 1) % 3
        if v[i] > 0:
            pts.append(tuple(xy[i]))
        if (v[i] > 0) != (v[j] > 0):
            s = v[i] / (v[i] - v[j])
            pts.append((xy[i][0] + (xy[j][0] - xy[i][0]) * s, xy[i][1] + (xy[j][1] - xy[i][1]) * s))
    if len(pts) < 3:
        return None
    from shapely.geometry import Polygon
    p = Polygon(pts)
    return p if p.is_valid and p.area > 0 else None


def gelaende_an_gebaeuden(d, log=print):
    """Liegt das Gelaende innerhalb eines Gebaeudegrundrisses HOEHER als die Oberkante des Gebaeudes, ist das Gelaende dort fast immer
    falsch (Brueckenrampe, Erdwall, Lesefehler im DGM). Es wird dann GENAU DORT ausgeschnitten, wo es ueber der Oberkante liegt (nur
    geschnitten, nichts angeschlossen oder verschoben). Dort, wo das Gelaende unter der Oberkante liegt - z. B. unter einer Bruecke -,
    bleibt es unberuehrt. Die Flaechen stehen in d.loecher und werden beim Aufteilen des Gelaendes ausgespart. Jeder Fall steht im Protokoll."""
    d.loecher = None
    if getattr(d, "px", None) is None or not d.teile or len(d.px) < 4:
        return 0
    import ifcmap_markant as M
    P = np.column_stack([d.px, d.py])
    tin = Delaunay(P)
    S = tin.simplices
    tri_xy, tri_z = P[S], d.pz[S]
    tri_zmax = tri_z.max(axis=1)
    baum = shapely.STRtree(shapely.polygons(tri_xy))
    faelle, flaechen = [], []
    for g in M.gebaeude_gruppen(d, mit_dach=False):
        fp = g["fp"]
        if fp.is_empty or fp.area < 4.0:
            continue
        grenze = g["zmax"] + GELAENDE_UEBER_TOL
        cand = baum.query(fp, predicate="intersects")
        cand = cand[tri_zmax[cand] > grenze]
        stuecke, ueber = [], 0.0
        for t in cand:
            q = _ueber_hoehe(tri_xy[t], tri_z[t], grenze)
            if q is None:
                continue
            s = q.intersection(fp)
            if s.is_empty or s.area < 0.3:
                continue
            A = np.column_stack([tri_xy[t], np.ones(3)])
            try:
                abc = np.linalg.solve(A, tri_z[t])
            except np.linalg.LinAlgError:
                continue
            for pg in M._polys_aus(s):
                c = np.array(pg.exterior.coords)
                ueber = max(ueber, float((c[:, 0] * abc[0] + c[:, 1] * abc[1] + abc[2]).max()) - g["zmax"])
            stuecke.append(s)
        if stuecke:
            u = unary_union(stuecke)
            faelle.append((g["gid"], u.area, fp.area, ueber))
            flaechen.append(u)
    if not faelle:
        return 0
    d.loecher = unary_union(flaechen)
    log("  Gelaende hoeher als die Gebaeude-Oberkante: %d Gebaeude - das Gelaende wird nur dort ausgeschnitten, wo es ueber der Oberkante liegt "
        "(vermutlich falsch gelesen):" % len(faelle))
    for gid, a, fa, dz in sorted(faelle, key=lambda f: -f[3])[:15]:
        log("    %s: %.0f von %.0f m2 des Grundrisses, Gelaende bis %.2f m ueber der Gebaeude-Oberkante" % (gid, a, fa, dz))
    if len(faelle) > 15:
        log("    ... %d weitere" % (len(faelle) - 15))
    return len(faelle)


def zuordnen(d):
    """Nutzungsarten (neu) einordnen - nach Aenderung der Tabelle aufrufbar."""
    d.regionen, d.tabelle = klassifiziere(d.nutz_feat, d.rect, d.cfg.overrides) if d.nutz_feat else ({}, [])
    return d


# ----------------------------------------------------------------------------------------------
# Gelaendenetz an den Nutzungsgrenzen aufteilen
# ----------------------------------------------------------------------------------------------

def stuecke_faces(geom, tri_xy, tri_z):
    A = np.column_stack([tri_xy, np.ones(3)])
    try:
        abc = np.linalg.solve(A, tri_z)
    except np.linalg.LinAlgError:
        return []
    if geom.geom_type == "Polygon":
        teile = [geom]
    elif hasattr(geom, "geoms"):
        teile = [g for g in geom.geoms if g.geom_type == "Polygon"]
    else:
        teile = []
    out = []
    for g in teile:
        if g.area < 1e-4:
            continue
        rings = [np.asarray(g.exterior.coords)[:-1]] + [np.asarray(i.coords)[:-1] for i in g.interiors]
        v = np.vstack(rings)
        ends = np.cumsum([len(r) for r in rings]).astype(np.uint32)
        idx = earcut.triangulate_float64(np.ascontiguousarray(v, dtype=np.float64), ends).reshape(-1, 3)
        z = v[:, 0] * abc[0] + v[:, 1] * abc[1] + abc[2]
        P3 = np.column_stack([v, z])
        out += [P3[i] for i in idx]
    return out


def gelaende_aufteilen(px, py, pz, regionen, log=print, rest_name=None, loecher=None):
    """loecher: Flaechen (shapely), die aus dem Gelaende ausgeschnitten werden (z. B. Gebaeude unter dem Gelaende)"""
    tin = Delaunay(np.column_stack([px, py]))
    S = tin.simplices
    tri_xy = np.stack([px[S], py[S]], axis=2)
    tri_z = pz[S]
    polys = shapely.polygons(tri_xy)
    n = len(S)
    log("  Gelaendenetz: %d Dreiecke" % n)
    faces, fertig, rest = {}, np.zeros(n, dtype=bool), {}
    if loecher is not None and not loecher.is_empty:
        shapely.prepare(loecher)
        n_ganz = 0
        for t in shapely.STRtree(polys).query(loecher, predicate="intersects"):
            if loecher.contains(polys[t]):
                fertig[t] = True
                n_ganz += 1
                continue
            r = polys[t].difference(loecher)
            if r.is_empty or r.area < 1e-4:
                fertig[t] = True
            else:
                rest[t] = r
        log("  Gelaende ausgeschnitten: %d Dreiecke ganz entfernt, %d angeschnitten" % (n_ganz, len(rest)))

    def voll(t, kat):
        faces.setdefault(kat, []).append(np.column_stack([tri_xy[t], tri_z[t]]))

    if regionen:
        tree = shapely.STRtree(polys)
        for kat, reg in regionen.items():
            shapely.prepare(reg)
            cand = tree.query(reg, predicate="intersects")
            cand = cand[~fertig[cand]]
            if len(cand) == 0:
                continue
            innen = shapely.contains(reg, polys[cand])
            for t, ist_innen in zip(cand, innen):
                g = rest.get(t, polys[t])
                if ist_innen and t not in rest:
                    voll(t, kat)
                    fertig[t] = True
                    continue
                if reg.contains(g):
                    faces.setdefault(kat, []).extend(stuecke_faces(g, tri_xy[t], tri_z[t]))
                    fertig[t] = True
                    rest.pop(t, None)
                    continue
                piece = g.intersection(reg)
                if piece.is_empty or piece.area < 1e-4:
                    continue
                faces.setdefault(kat, []).extend(stuecke_faces(piece, tri_xy[t], tri_z[t]))
                r = g.difference(reg)
                if r.is_empty or r.area < 1e-4:
                    fertig[t] = True
                    rest.pop(t, None)
                else:
                    rest[t] = r
    sk = rest_name or (OHNE_NUTZUNG if regionen else "Gelaende")
    for t in np.nonzero(~fertig)[0]:
        if t in rest:
            faces.setdefault(sk, []).extend(stuecke_faces(rest[t], tri_xy[t], tri_z[t]))
        else:
            voll(t, sk)
    return faces, tin


def fahrbahn_teilen(d, reg_gel, log):
    """Bordstein im IFC-Gelaende, Schritt 1: die Strassenflaeche wird in Fahrbahn und Gehweg geteilt (gleiche Aufteilung wie im
    Lageplan). -> (reg_gel mit 'Strasse' = Fahrbahn und neu 'Gehweg', Fahrbahnflaeche oder None, Absenkung in m)"""
    sink = float(getattr(d.cfg, "fahrbahn_absenken", 0.0) or 0.0)
    st = reg_gel.get("Strasse")
    if sink <= 0 or st is None or st.is_empty:
        return reg_gel, None, 0.0
    import ifcmap_plaene as PL
    fb, gw, hint = PL.buergersteige(d, st, log)
    try:                                                                # auf und unter Bruecken: kein Gehweg, kein Bordstein (das DGM liegt dort tiefer)
        import ifcmap_bruecken as BR
        decks = BR.decks_vereint(d)
        if decks is not None and gw is not None and not gw.is_empty:
            weg = gw.intersection(decks.buffer(2.0))
            if not weg.is_empty:
                gw = gw.difference(decks.buffer(2.0))
                fb = unary_union([fb, weg]) if fb is not None and not fb.is_empty else weg
                log("  Bruecken: auf %.0f m2 Gehweg verzichtet (Bruecken liegen ueber dem DGM - der Gehweg bliebe in der Schlucht darunter)" % weg.area)
    except Exception as e:
        log("  HINWEIS: Bruecken im IFC-Gehweg nicht beruecksichtigt (%s)" % str(e)[:80])
    fb = unary_union(_polys(fb)) if fb is not None and not fb.is_empty else None
    if fb is None or fb.is_empty:
        return reg_gel, None, 0.0
    neu = {}
    for k, v in reg_gel.items():
        if k == "Strasse":
            neu["Strasse"] = fb
            if gw is not None and not gw.is_empty:
                neu["Gehweg"] = unary_union(_polys(gw))
        else:
            neu[k] = v
    if hint:
        log("  HINWEIS (Gehweg im IFC): " + hint)
    d._strasse_gesamt = st
    return neu, fb, sink


def _ccw_dreiecke(dreiecke):
    """-> (T (n,3,3) gegen den Uhrzeigersinn, uebrige Flaechen mit mehr als 3 Ecken)"""
    tri = [np.asarray(f, dtype=float) for f in dreiecke]
    dr = [f for f in tri if len(f) == 3]
    rest = [f for f in tri if len(f) != 3]
    if not dr:
        return np.zeros((0, 3, 3)), rest
    T = np.stack(dr)
    a2 = (T[:, 1, 0] - T[:, 0, 0]) * (T[:, 2, 1] - T[:, 0, 1]) - (T[:, 1, 1] - T[:, 0, 1]) * (T[:, 2, 0] - T[:, 0, 0])
    neg = a2 < 0
    T[neg] = T[neg][:, [0, 2, 1], :]                                            # Normale nach oben
    return T, rest


def _rand_kanten(T):
    """Kanten, die nur zu EINEM Dreieck gehoeren (Rand des Netzes), gerichtet so, dass das Innere links liegt -> (A, B) (je (m,3))"""
    A = T.reshape(-1, 3)
    B = np.roll(T, -1, axis=1).reshape(-1, 3)
    ka = np.round(A[:, :2] * 1000).astype(np.int64)
    kb = np.round(B[:, :2] * 1000).astype(np.int64)
    tausch = (ka[:, 0] > kb[:, 0]) | ((ka[:, 0] == kb[:, 0]) & (ka[:, 1] > kb[:, 1]))
    lo = np.where(tausch[:, None], kb, ka)
    hi = np.where(tausch[:, None], ka, kb)
    _, inv, cnt = np.unique(np.hstack([lo, hi]), axis=0, return_inverse=True, return_counts=True)
    rand = cnt[inv.reshape(-1)] == 1
    return A[rand], B[rand]


def _kanten_nahe(A, B, linie, abstand=0.01):
    """Maske: Kantenmitte liegt auf der Linie (Abstand <= abstand)"""
    if not len(A) or linie is None or linie.is_empty:
        return np.zeros(len(A), dtype=bool)
    return shapely.contains_xy(linie.buffer(abstand), (A[:, 0] + B[:, 0]) / 2, (A[:, 1] + B[:, 1]) / 2)


def _wand(a_oben, b_oben, a_unten, b_unten):
    """Senkrechte Flaeche entlang einer Kante (Inneres des Netzes links, Normale nach aussen)"""
    return np.array([a_oben, a_unten, b_unten, b_oben])


def bordstein_flaechen(dreiecke, fahrbahn, rect, sink, log=print):
    """Bordstein im IFC-Gelaende, Schritt 2: die Fahrbahn-Dreiecke werden um sink (m) abgesenkt. Entlang ihres Randes - dort wo sie an
    Gehweg, Platz, Gruen usw. grenzt - entsteht eine senkrechte Wand vom Gelaende hinunter zur abgesenkten Fahrbahn (die Bordsteinkante).
    Kein Rand an der Gebiets-Grenze und nicht an Gebaeude-Ausschnitten (dort wird nichts angeschlossen).
    -> (abgesenkte Dreiecke, Wandflaechen, Randkanten (A, B) mit der urspruenglichen Gelaendehoehe)"""
    T, rest = _ccw_dreiecke(dreiecke)
    rest = [f - np.array([0.0, 0.0, sink]) for f in rest]
    if not len(T):
        return rest, [], (np.zeros((0, 3)), np.zeros((0, 3)))
    A, B = _rand_kanten(T)
    if len(A):
        keep = _kanten_nahe(A, B, fahrbahn.boundary) & ~_kanten_nahe(A, B, rect.boundary)
        keep &= np.hypot(B[:, 0] - A[:, 0], B[:, 1] - A[:, 1]) > 1e-3
        A, B = A[keep], B[keep]
    unten = np.array([0.0, 0.0, sink])
    waende = [_wand(a, b, a - unten, b - unten) for a, b in zip(A, B)]
    tief = [tr - unten for tr in T] + rest
    rand = (A, B)
    if waende:
        laenge = float(np.hypot(B[:, 0] - A[:, 0], B[:, 1] - A[:, 1]).sum())
        log("  Bordstein: Fahrbahn %.0f cm tiefer, %d Wandflaechen, %.0f m Bordsteinkante" % (sink * 100, len(waende), laenge))
    else:
        log("  Bordstein: Fahrbahn %.0f cm tiefer (keine Kanten zu angrenzenden Flaechen gefunden)" % (sink * 100))
    return tief, waende, rand


GEHWEG_RADIUS = 15.0           # m: Hoehe des Gehwegs aus den Fahrbahnrand-Punkten in diesem Umkreis


def gehweg_glaetten(dreiecke, rand, strasse, fahrbahn, rect, log=print):
    """Bordstein im IFC-Gelaende, Schritt 3: Gehweg-Hoehen. Das DGM-Netz ist auf den Gehwegen ausgeduennt und holprig (lange Dreiecke
    zwischen Fahrbahnrand und Park/Haus), der Gehweg wirkt gekruemmt, waehrend die Fahrbahn glatt ist. Innerhalb der Strassenflaeche bekommt
    jeder Gehweg-Punkt deshalb die Hoehe des naechsten Punktes auf dem Fahrbahnrand (lineare Hoehe laengs der Randkante): der Gehweg folgt
    dem Laengsprofil der Strasse, ohne Querneigung. Fuer Punkte auf dem Fahrbahnrand ist das genau die Gelaendehoehe dort - die Bordsteinwand
    passt luckenlos. Wo der Gehweg an anderes Gelaende stoesst (z. B. Gruen), schliesst eine senkrechte Naht-Wand die Kante.
    rand = (A, B): Randkanten der Fahrbahn mit der urspruenglichen Hoehe. -> (neue Dreiecke, Nahtwaende)"""
    from shapely.geometry import LineString
    T, rest = _ccw_dreiecke(dreiecke)
    RA, RB = rand
    if not len(T) or not len(RA):
        return [tr for tr in T] + rest, []
    segs = shapely.linestrings(np.stack([RA[:, :2], RB[:, :2]], axis=1))
    baum = shapely.STRtree(segs)
    V = T.reshape(-1, 3)
    z_alt = V[:, 2].copy()
    schluessel, ersteidx, inv = np.unique(np.round(V[:, :2] * 1000).astype(np.int64), axis=0, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    xy = V[ersteidx, :2]
    innen = shapely.contains_xy(strasse.buffer(0.05), xy[:, 0], xy[:, 1])
    zn = np.full(len(xy), np.nan)
    if innen.any():
        pts = shapely.points(xy[innen])
        ii, jj = baum.query_nearest(pts, return_distance=False, all_matches=False), None
        # query_nearest liefert (Eingabe-Index, Baum-Index)
        pi, si = ii[0], ii[1]
        P = xy[innen][pi]
        a, b = RA[si], RB[si]
        ab = b[:, :2] - a[:, :2]
        L2 = np.maximum((ab ** 2).sum(axis=1), 1e-12)
        tpar = np.clip(((P - a[:, :2]) * ab).sum(axis=1) / L2, 0.0, 1.0)
        fuss = a[:, :2] + ab * tpar[:, None]
        abst = np.hypot(*(P - fuss).T)
        zz = a[:, 2] + (b[:, 2] - a[:, 2]) * tpar
        zz = np.where(abst <= GEHWEG_RADIUS, zz, np.nan)
        tmp = np.full(int(innen.sum()), np.nan)
        tmp[pi] = zz
        zn[innen] = tmp
    z_vert = zn[inv]
    gesetzt = np.isfinite(z_vert)
    z_neu = np.where(gesetzt, z_vert, z_alt)
    Vn = V.copy()
    Vn[:, 2] = z_neu
    Tn = Vn.reshape(-1, 3, 3)
    # Nahtwaende: Rand des Gehwegs, der NICHT am Fahrbahnrand liegt und an dem sich die Hoehe geaendert hat
    A_alt, B_alt = _rand_kanten(T)
    A_neu, B_neu = _rand_kanten(Tn)
    waende = []
    if len(A_alt) and len(A_alt) == len(A_neu) and np.allclose(A_alt[:, :2], A_neu[:, :2], atol=2e-3) and np.allclose(B_alt[:, :2], B_neu[:, :2], atol=2e-3):
        keep = ~_kanten_nahe(A_alt, B_alt, fahrbahn.boundary) & ~_kanten_nahe(A_alt, B_alt, rect.boundary)
        keep &= np.maximum(np.abs(A_alt[:, 2] - A_neu[:, 2]), np.abs(B_alt[:, 2] - B_neu[:, 2])) > 0.005
        for a0, b0, a1, b1 in zip(A_alt[keep], B_alt[keep], A_neu[keep], B_neu[keep]):
            waende.append(_wand(a1, b1, a0, b0))
    n_ge = int((np.abs(z_neu - z_alt) > 0.005).sum())
    s_alt = float(np.abs(z_alt[gesetzt] - np.median(z_alt[gesetzt])).mean()) if gesetzt.any() else 0.0
    log("  Gehweg: %d Punkte auf die Hoehe des Fahrbahnrands gesetzt (Gehweg folgt dem Laengsprofil der Strasse, keine Querneigung), %d Nahtwaende "
        "zu angrenzendem Gelaende" % (n_ge, len(waende)))
    return [tr for tr in Tn] + rest, waende


def baum_faces(x, y, z, krone, hoehe, stamm):
    stamm_h = max(0.35 * hoehe, 1.0)
    rs = stamm / 2
    ang = np.linspace(0, 2 * math.pi, 7)[:-1]
    ring0 = [(x + rs * math.cos(a), y + rs * math.sin(a), z) for a in ang]
    ring1 = [(p[0], p[1], z + stamm_h) for p in ring0]
    sf = [np.array([ring0[i], ring0[(i + 1) % 6], ring1[(i + 1) % 6], ring1[i]]) for i in range(6)]
    kh = max(hoehe - 0.7 * stamm_h, 0.5 * krone)
    rz, rr = kh / 2, krone / 2
    cz = z + hoehe - rz
    nseg, nlat = 8, 4
    lat = np.linspace(-math.pi / 2, math.pi / 2, nlat + 1)
    lon = np.linspace(0, 2 * math.pi, nseg + 1)

    def pt(i, j):
        return (x + rr * math.cos(lat[i]) * math.cos(lon[j]), y + rr * math.cos(lat[i]) * math.sin(lon[j]),
                cz + rz * math.sin(lat[i]))
    kf = [np.array([pt(i, j), pt(i, j + 1), pt(i + 1, j + 1), pt(i + 1, j)]) for i in range(nlat) for j in range(nseg)]
    return sf, kf


# ----------------------------------------------------------------------------------------------
# IFC schreiben
# ----------------------------------------------------------------------------------------------

def _gegenlaeufig(a, b):
    """Gleiche Ecken in umgekehrter Reihenfolge (zwei sich deckende Flaechen, die in entgegengesetzte Richtung zeigen)?"""
    if len(a) != len(b):
        return False
    ra = a[::-1]
    if b[0] not in ra:
        return False
    i = ra.index(b[0])
    return ra[i:] + ra[:i] == b


EBEN_TOL = 0.001                       # m: groesste Abweichung eines n-Ecks von seiner Ebene (nach dem Runden)


def _mesh(faces, shift, nd=3, innen=False, stat=None):
    """Flaechenliste -> (Punkte, Polygone) mit verschweissten Punkten (Raster 10^-nd m). innen=True: Flaechen, die
    doppelt vorkommen und gegeneinander zeigen (Wand zwischen zwei Gebaeudeteilen), werden gestrichen.
    (Vektorisiert: alle Ecken auf einmal runden und per np.unique verschweissen - ca. 10x schneller als Punkt fuer Punkt.)"""
    faces = [np.asarray(fc, dtype=float) for fc in faces]
    if not faces:
        return [], []
    laengen = np.fromiter((len(fc) for fc in faces), dtype=np.int64, count=len(faces))
    alle = np.round(np.vstack(faces) - shift, nd) + 0.0                 # + 0.0: aus -0.0 wird 0.0
    punkte, inv = np.unique(alle, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    verts = punkte.tolist()
    grenzen = np.concatenate([[0], np.cumsum(laengen)])
    nxt = np.roll(inv, -1)
    nxt[grenzen[1:] - 1] = inv[grenzen[:-1]]                     # Ring schliessen: letzte Ecke -> erste Ecke derselben Flaeche
    n = np.add.reduceat(np.cross(punkte[inv], punkte[nxt]), grenzen[:-1], axis=0)    # Flaechenvektor je Flaeche
    gut = np.linalg.norm(n, axis=1) >= 1e-6                      # sonst entartet (Flaeche ~ 0)
    polys = []
    for i in np.nonzero(gut)[0]:
        u = list(dict.fromkeys(inv[grenzen[i]:grenzen[i + 1]].tolist()))
        if len(u) > 3:
            # ArchiCAD meldet 'Normalvektor und Kante nicht rechtwinklig', wenn ein n-Eck NACH dem Runden nicht mehr eben ist
            # -> streng pruefen und sonst in Dreiecke zerlegen
            q = punkte[u]
            c = q.mean(axis=0)
            try:
                dev = float(np.abs((q - c) @ np.linalg.svd(q - c)[2][2]).max())
            except np.linalg.LinAlgError:
                dev = 1.0
            if dev > EBEN_TOL:
                if stat is not None:
                    stat["unebene"] = stat.get("unebene", 0) + 1
                    stat["max_abw"] = max(stat.get("max_abw", 0.0), dev)
                tris = tri_poly3d(q, [])
                if tris:
                    idx = {tuple(v): k for k, v in enumerate(punkte[u].tolist())}
                    for tr in tris:
                        polys.append([u[idx[tuple(v)]] for v in np.asarray(tr).tolist()])
                    continue
        if len(u) >= 3:
            polys.append(u)
    if innen and polys:
        gruppen = {}
        for i, u in enumerate(polys):
            gruppen.setdefault(frozenset(u), []).append(i)
        weg = set()
        for ids in gruppen.values():
            if len(ids) == 2 and _gegenlaeufig(polys[ids[0]], polys[ids[1]]):
                weg.update(ids)
        if weg:
            polys = [u for i, u in enumerate(polys) if i not in weg]
    if innen and polys:
        polys = _nach_aussen(verts, polys)
    return verts, polys


def _nach_aussen(verts, polys):
    """Alle Flaechen eines Gebaeudes zeigen nach aussen: Vorzeichen des Volumens ueber F = (0, 0, z - zmin) (die fehlende
    Bodenflaeche der Bloecke traegt dabei 0 bei). Negativ -> alle Flaechen umdrehen. Sonst sehen Bloecke in ArchiCAD (Rueckseiten)
    dunkler aus als die Dachhaeuser."""
    v = np.asarray(verts, dtype=float)
    zmin = v[:, 2].min()
    vol = 0.0
    for u in polys:
        o = v[u[0]]
        for i in range(1, len(u) - 1):
            a, b = v[u[i]], v[u[i + 1]]
            nz = 0.5 * ((a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]))
            vol += nz * ((o[2] + a[2] + b[2]) / 3.0 - zmin)
    if vol < 0:
        return [u[::-1] for u in polys]
    return polys


def _flaeche(faces):
    a = 0.0
    for f in faces:
        f = np.asarray(f)
        x, y = f[:, 0], f[:, 1]
        a += 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    return a


def _geschosslinien_schreiben(d, je_gebaeude, zahlen, element, sto):
    """Geschosslinien je Gebaeude als EIN flaches Element -> (Gebaeude, Baender)"""
    import ifcmap_geschosse as GS
    nb = ng = 0
    rad = float(getattr(d.cfg, "geschosslinien_radius", 150.0))
    for gid, teile in je_gebaeude.items():
        if gid not in zahlen:
            continue
        n, zg, tr, quelle = zahlen[gid]
        waende = [w for t in teile for w in (t.get("wall") or [])]
        if not waende or n < 2:
            continue
        pts = np.vstack([np.asarray(e)[:, :2] for e, _ in waende])
        c = pts.mean(axis=0)
        if np.hypot(c[0] - d.ce, c[1] - d.cn) > rad:
            continue
        arr = GS.linien(waende, c, n, zg, tr)
        if len(arr) and element("IfcBuildingElementProxy", "Geschosslinien_" + str(gid), list(arr), LAYER_GESCHOSSE, sto, gebaeude=False,
                                farbe=IFC_FARBEN["Geschosslinie"], stil="Geschosslinie",
                                props={"Gebaeude_ID": str(gid), "Geschosse": int(n), "Quelle_Geschosse": quelle,
                                       "Hinweis": "Geschossteilung gleichmaessig ueber die Traufhoehe, keine gemessenen Geschosshoehen"}):
            nb += len(arr)
            ng += 1
    return ng, nb


def _fenstermuster_schreiben(d, je_gebaeude, element, sto):
    """Fenster und Tueren (Muster, nicht gemessen) je Gebaeude als flache Elemente -> (Gebaeude, Fenster, Tueren)"""
    import ifcmap_fenstermuster as FM
    ng = nf = nt = 0
    rad = float(getattr(d.cfg, "fenstermuster_radius", 100.0))
    hinweis = "MUSTER nach Wandbreite und -hoehe, keine Messung: LoD2 enthaelt keine Fenster und Tueren"
    for gid, teile in je_gebaeude.items():
        waende = [w for t in teile for w in (t.get("wall") or [])]
        if not waende:
            continue
        pts = np.vstack([np.asarray(e)[:, :2] for e, _ in waende])
        c = pts.mean(axis=0)
        if np.hypot(c[0] - d.ce, c[1] - d.cn) > rad:
            continue
        fen, tue, _info = FM.fassade(waende, c)
        ok = False
        if len(fen) and element("IfcBuildingElementProxy", "Fenstermuster_" + str(gid), list(fen), LAYER_FENSTER, sto, gebaeude=False,
                                farbe=IFC_FARBEN["Fenster"], stil="Fenster",
                                props={"Gebaeude_ID": str(gid), "Hinweis": hinweis}):
            nf += len(fen)
            ok = True
        if len(tue) and element("IfcBuildingElementProxy", "Tuermuster_" + str(gid), list(tue), LAYER_FENSTER, sto, gebaeude=False,
                                farbe=IFC_FARBEN["Tuer"], stil="Tuer",
                                props={"Gebaeude_ID": str(gid), "Hinweis": hinweis}):
            nt += len(tue)
            ok = True
        ng += int(ok)
    return ng, nf, nt


def schreibe_ifc(pfad, d, faces_gel, interp, gelaende_typ, log=print):
    import ifcopenshell
    import ifcopenshell.api.root, ifcopenshell.api.unit, ifcopenshell.api.context, ifcopenshell.api.project
    import ifcopenshell.api.aggregate, ifcopenshell.api.spatial, ifcopenshell.api.geometry, ifcopenshell.api.layer
    import ifcopenshell.api.pset, ifcopenshell.api.georeference

    shift = np.array([d.e0, d.n0, d.z0])
    f = ifcopenshell.api.project.create_file(version="IFC4")
    proj = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="IFCmap")
    ifcopenshell.api.unit.assign_unit(f)
    ctx = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(f, context_type="Model", context_identifier="Body",
                                                target_view="MODEL_VIEW", parent=ctx)
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="IFCmap")
    bld = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuilding", name="Umgebungsbebauung")
    sto = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey", name="Gelaendeniveau")
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=proj)
    ifcopenshell.api.aggregate.assign_object(f, products=[bld], relating_object=site)
    ifcopenshell.api.aggregate.assign_object(f, products=[sto], relating_object=bld)
    for el in (site, bld, sto):
        ifcopenshell.api.geometry.edit_object_placement(f, product=el)
    try:
        ifcopenshell.api.georeference.add_georeferencing(f)
        ifcopenshell.api.georeference.edit_georeferencing(
            f,
            projected_crs={"Name": "EPSG:%d" % d.cfg.epsg, "Description": KBS_NAMEN.get(d.cfg.epsg, "EPSG:%d" % d.cfg.epsg),
                           "GeodeticDatum": "ETRS89", "MapProjection": "UTM",
                           "MapZone": KBS_NAMEN.get(d.cfg.epsg, "  ")[-3:].strip()},
            coordinate_operation={"Eastings": float(d.e0), "Northings": float(d.n0), "OrthogonalHeight": float(d.z0),
                                  "XAxisAbscissa": 1.0, "XAxisOrdinate": 0.0, "Scale": 1.0})
    except Exception as e:
        log("  Hinweis: Georeferenzierung konnte nicht geschrieben werden (%s)" % e)

    layers, stile, materialien = {}, {}, {}
    uneben_liste = []
    # Geschwindigkeit: die ifcopenshell-API haengt jedes Element einzeln an Beziehungen (Raumstruktur, Layer, Material), und jedes Anhaengen
    # schreibt die ganze bisherige Liste neu -> quadratischer Aufwand bei Tausenden Elementen. Darum werden die Elemente gesammelt und am Ende
    # je Container/Layer/Material in EINEM Aufruf zugewiesen. Alle Elemente teilen sich eine Platzierung (Ursprung), Psets werden direkt geschrieben.
    sammel_cont, sammel_site, sammel_layer, sammel_mat = {}, [], {}, {}
    nullpkt = f.createIfcCartesianPoint((0.0, 0.0, 0.0))
    platzierung = f.createIfcLocalPlacement(None, f.createIfcAxis2Placement3D(nullpkt, None, None))
    import ifcopenshell.guid as _guid

    def pset_direkt(el, name, props):
        liste = []
        for k, v in props.items():
            if isinstance(v, bool):
                w = f.createIfcBoolean(v)
            elif isinstance(v, int):
                w = f.createIfcInteger(v)
            elif isinstance(v, float):
                w = f.createIfcReal(v)
            else:
                w = f.createIfcLabel(str(v))
            liste.append(f.createIfcPropertySingleValue(str(k), None, w, None))
        ps = f.createIfcPropertySet(_guid.new(), None, name, None, liste)
        f.createIfcRelDefinesByProperties(_guid.new(), None, None, None, [el], ps)
    farben_an = bool(getattr(d.cfg, "farben", True))
    if farben_an:
        import ifcopenshell.api.style, ifcopenshell.api.material

    def farbe_zuweisen(rep, el, name, rgb):
        if name not in stile:
            st = ifcopenshell.api.style.add_style(f, name=name)
            ifcopenshell.api.style.add_surface_style(
                f, style=st, ifc_class="IfcSurfaceStyleRendering",
                attributes={"SurfaceColour": {"Name": None, "Red": rgb[0] / 255, "Green": rgb[1] / 255, "Blue": rgb[2] / 255},
                            "Transparency": 0.0, "ReflectanceMethod": "NOTDEFINED",
                            "DiffuseColour": {"Name": None, "Red": rgb[0] / 255, "Green": rgb[1] / 255, "Blue": rgb[2] / 255}})
            stile[name] = st
            materialien[name] = ifcopenshell.api.material.add_material(f, name=name)
        ifcopenshell.api.style.assign_representation_styles(f, shape_representation=rep, styles=[stile[name]])
        sammel_mat.setdefault(name, []).append(el)

    def layer(name):
        if name not in layers:
            layers[name] = ifcopenshell.api.layer.add_layer(f, name=name)
        return layers[name]

    def element(klasse, name, faces, lay, container, predefined=None, objtype=None, props=None, als_site=False, farbe=None,
                gebaeude=False, stil=None, mesh=None, textur=None):
        stat = {}
        if mesh is not None:                              # fertig berechnet (zusammengefasste Fernbereich-Felder)
            verts, polys, stat = mesh
        else:
            verts, polys = _mesh(faces, shift, nd=2, innen=True, stat=stat) if gebaeude else _mesh(faces, shift, stat=stat)
        if not polys:
            return None
        if stat.get("unebene"):
            uneben_liste.append((name, stat["unebene"], stat["max_abw"]))
        kw = dict(ifc_class=klasse, name=name)
        if predefined:
            kw["predefined_type"] = predefined
        el = ifcopenshell.api.root.create_entity(f, **kw)
        if objtype:
            el.ObjectType = objtype
        if textur is not None:
            rep = textur_darstellung(verts, polys, textur)
        else:
            rep = ifcopenshell.api.geometry.add_mesh_representation(f, context=body, vertices=[verts], faces=[polys])
        el.ObjectPlacement = platzierung
        el.Representation = f.createIfcProductDefinitionShape(None, None, [rep])
        if als_site:
            sammel_site.append(el)
        elif container is not None:
            sammel_cont.setdefault(id(container), (container, []))[1].append(el)
        layer(lay)
        sammel_layer.setdefault(lay, []).append(rep)
        if farben_an and farbe and textur is None:
            farbe_zuweisen(rep, el, stil or lay, farbe)
        if props:
            pset_direkt(el, "Pset_Umgebung", props)
        return el

    def textur_darstellung(verts, polys, tx):
        """Gelaende als Dreiecksnetz mit Luftbild-Textur (IfcTriangulatedFaceSet + IfcIndexedTriangleTextureMap). UNGETESTET in Archicad."""
        rect, bildname = tx
        tri = []
        for pl in polys:
            for i in range(1, len(pl) - 1):
                tri.append((int(pl[0]) + 1, int(pl[i]) + 1, int(pl[i + 1]) + 1))
        pts = f.createIfcCartesianPointList3D([tuple(float(c) for c in v) for v in verts])
        fs = f.createIfcTriangulatedFaceSet(pts, None, None, tri, None)
        bw, bh = max(rect[2] - rect[0], 1e-6), max(rect[3] - rect[1], 1e-6)
        uv = [(min(1.0, max(0.0, (v[0] + shift[0] - rect[0]) / bw)), min(1.0, max(0.0, (v[1] + shift[1] - rect[1]) / bh))) for v in verts]
        img = f.createIfcImageTexture(False, False, "DIFFUSE", None, None, bildname)
        weiss = f.createIfcColourRgb(None, 1.0, 1.0, 1.0)
        rs = f.createIfcSurfaceStyleRendering(weiss, 0.0, weiss, None, None, None, None, None, "NOTDEFINED")
        st = f.createIfcSurfaceStyle("Luftbild", "BOTH", [rs, f.createIfcSurfaceStyleWithTextures([img])])
        f.createIfcStyledItem(fs, [st], None)
        f.createIfcIndexedTriangleTextureMap([img], fs, f.createIfcTextureVertexList([list(u) for u in uv]), tri)
        return f.createIfcShapeRepresentation(body, "Body", "Tessellation", [fs])

    n_geb = n_gel = n_baum = 0
    n_gl = n_glb = 0
    fern_modus = getattr(d.cfg, "fern_gebaeude", "bloecke")
    gl_an = bool(getattr(d.cfg, "geschosslinien", False)) and ebene_an(d.cfg, "ifc", "Gebaeude_Geschosse")
    gl_zahlen = {}
    fm_an = bool(getattr(d.cfg, "fenstermuster", False)) and ebene_an(d.cfg, "ifc", "Gebaeude_Fenstermuster")
    n_fm = n_fmf = n_fmt = 0
    zusatz_geb = []                                       # Nahbereichs-Gebaeude fuer optionale Zusatzmodule
    leer = []                                             # Gebaeude, aus denen keine Flaechen entstanden
    # markante Gebaeude zuerst: nur was wirklich geschrieben wurde, wird unten aus den normalen Gebaeuden herausgenommen
    # (sonst verschwaende ein Gebaeude, dessen markantes Element leer bleibt oder dessen Ebene abgeschaltet ist)
    markant_ok = set()
    for m in (getattr(d, "markant", None) or []) if ebene_an(d.cfg, "ifc", "Gebaeude_Markant") else []:
        if element("IfcBuildingElementProxy", "Markant_" + umlaute(re.sub(r"[^\w\-]+", "_", m["name"]).strip("_") or str(m["gid"])),
                   m["faces"], LAYER_MARKANT, sto, gebaeude=True, farbe=IFC_FARBEN["Gebaeude_Markant"], stil="Gebaeude_Markant",
                   props={"Gebaeude_ID": str(m["gid"]), "Quelle": m["quelle"], "Kriterium": m["grund"][:200], "Hoehe_LoD2_m": round(m["H"], 1),
                          "Detailgrad": m["text"][:200]}):
            n_geb += 1
            markant_ok.add(m["gid"])
        else:
            log("  WARNUNG: markantes Gebaeude %s ergab keine Flaechen - es wird als normales Gebaeude geschrieben" % m["name"])
    gruppen_liste = []
    if ebene_an(d.cfg, "ifc", "Gebaeude_Nah"):
        gruppen_liste.append((d.near, LAYER_NAH, "LoD2_", False))
    if fern_modus != "keine" and ebene_an(d.cfg, "ifc", "Gebaeude_Fern"):
        gruppen_liste.append((d.far, LAYER_FERN, "Block_", True))
    for liste, lay, prefix, fern in gruppen_liste:
        je_gebaeude = {}                                  # Teile eines Gebaeudes -> ein Element (ein Morph)
        for t in liste:
            je_gebaeude.setdefault(t["gebaeude"] or t["id"], []).append(t)
        if gl_an and not fern:
            try:
                import ifcmap_geschosse as GS
                gl_zahlen = GS.geschosszahl_je_gebaeude(d, je_gebaeude, getattr(d.cfg, "geschosslinien_quelle", "auto"))
            except Exception as e:
                log("  HINWEIS: Geschosslinien nicht moeglich (%s)" % str(e)[:100])
                gl_zahlen = {}
        felder = {}
        zusammen = fern and fern_modus == "bloecke" and bool(getattr(d.cfg, "fern_zusammenfassen", True))
        zelle = max(30.0, float(getattr(d.cfg, "fern_zelle", 150.0) or 150.0))
        for gid, teile in je_gebaeude.items():
            if gid in markant_ok:
                continue                                  # kommt als eigenes markantes Element (Layer Gebaeude_Markant_Detail)
            if zusammen:
                fa = []
                for t in teile:
                    if t["ground"]:
                        fa += block_faces(t)[0]
                if not fa:
                    leer.append(prefix + str(gid))
                    continue
                st_ = {}
                vv, pp = _mesh(fa, shift, nd=2, innen=True, stat=st_)
                if not pp:
                    leer.append(prefix + str(gid))
                    continue
                c0 = teile[0]["c"]
                fe = felder.setdefault((int(math.floor((c0[0] - d.e0) / zelle)), int(math.floor((c0[1] - d.n0) / zelle))),
                                       dict(v=[], p=[], n=0, stat={}, ids=[], quellen=set()))
                off = len(fe["v"])
                fe["v"] += vv
                fe["p"] += [[i + off for i in u] for u in pp]
                fe["n"] += 1
                fe["ids"].append(str(gid))
                fe["quellen"].update(t.get("quelle", "LoD2") for t in teile)
                if st_.get("unebene"):
                    fe["stat"]["unebene"] = fe["stat"].get("unebene", 0) + st_["unebene"]
                    fe["stat"]["max_abw"] = max(fe["stat"].get("max_abw", 0.0), st_.get("max_abw", 0.0))
                n_geb += 1
                continue
            faces, voll = [], True
            for t in teile:
                if fern and (fern_modus != "lod2" or t.get("kompakt")):
                    if t["ground"]:
                        faces += block_faces(t)[0]
                    voll = False
                elif not fern or fern_modus == "lod2":
                    faces += lod2_faces(t)
            detail = "LoD2 Dach" if voll else "Block bis Traufe"
            quellen = sorted({t.get("quelle", "LoD2") for t in teile})
            if quellen != ["LoD2"]:
                detail = ("Dachform aus OSM" if voll and any("OSM" in q for q in quellen) else detail) + " (Ersatz fuer LoD2)"
            props = {"Gebaeude_ID": str(gid), "Detailgrad": detail, "Teile": len(teile), "Quelle": "+".join(quellen)}
            infos = [t["info"] for t in teile if t.get("info")]
            if infos:
                props["Quelle_Info"] = "; ".join(infos)[:250]
            if any(t.get("geschaetzt") for t in teile):
                props["Hoehe_geschaetzt"] = True
            if element("IfcBuildingElementProxy", prefix + str(gid), faces, lay, sto, gebaeude=True,
                       farbe=IFC_FARBEN["Gebaeude_Nah"], stil="Gebaeude", props=props):
                n_geb += 1
                if gl_zahlen and not fern and gid in gl_zahlen:
                    g1, b1 = _geschosslinien_schreiben(d, {gid: teile}, gl_zahlen, element, sto)
                    n_gl += g1
                    n_glb += b1
                if not fern:
                    zusatz_geb.append((gid, teile))
                if fm_an and not fern:
                    g2, f2, t2 = _fenstermuster_schreiben(d, {gid: teile}, element, sto)
                    n_fm += g2
                    n_fmf += f2
                    n_fmt += t2
            else:
                leer.append(prefix + str(gid))
        for (ix, iy), fe in sorted(felder.items()):
            nm = "Fernbloecke_E%+d_N%+d" % (ix * zelle, iy * zelle)
            props = {"Gebaeude": fe["n"], "Detailgrad": "Block bis Traufe (zusammengefasst)", "Feld_m": zelle,
                     "Quelle": "+".join(sorted(fe["quellen"])), "Gebaeude_IDs": ", ".join(fe["ids"][:12]) + (" ..." if len(fe["ids"]) > 12 else "")}
            element("IfcBuildingElementProxy", nm, [], lay, sto, gebaeude=True, farbe=IFC_FARBEN["Gebaeude_Nah"], stil="Gebaeude", props=props,
                    mesh=(fe["v"], fe["p"], fe["stat"]))
        if felder:
            log("  Fernbereich: %d Gebaeude zu %d Elementen (Felder von %.0f m) zusammengefasst - schneller und kleiner in Archicad" %
                (sum(fe["n"] for fe in felder.values()), len(felder), zelle))
    if gl_an:
        qs = {}
        for gid, (n_, zg_, tr_, q_) in gl_zahlen.items():
            qs[q_.split(" (")[0].split(" aus ")[0]] = qs.get(q_.split(" (")[0].split(" aus ")[0], 0) + 1
        log("  Geschosslinien: %d Baender an %d Gebaeuden (Geschosszahl aus: %s; Teilung gleichmaessig ueber die Traufhoehe, keine gemessenen Geschosshoehen)"
            % (n_glb, n_gl, ", ".join("%s %d" % (k, v) for k, v in sorted(qs.items())) or "keine Angaben"))
    if zusatz_geb and getattr(d.cfg, "zusatz", None):
        try:                                  # NICHT "import zusatz": der Plugin-Ordner "zusatz" neben dem Programm waere sonst ein leeres Namensraum-Paket
            from architools import zusatz as _ZU
        except ImportError:
            import zusatz as _ZU
        _ZU.rufe("ifc_ende", dict(f=f, d=d, sto=sto, body=body, shift=shift, platzierung=platzierung, gebaeude=zusatz_geb, interp=interp,
                                  pfad=pfad, log=log, einstellungen=d.cfg.zusatz, ifcopenshell=ifcopenshell), log=log)
    if fm_an:
        log("  Fenstermuster: %d Fenster und %d Tueren an %d Gebaeuden - ein MUSTER nach Wandbreite und -hoehe, KEINE Messung (LoD2 enthaelt keine Oeffnungen)"
            % (n_fmf, n_fmt, n_fm))
    if leer:
        log("  WARNUNG: %d Gebaeude ergaben keine Flaechen und fehlen in der IFC: %s%s" % (len(leer), ", ".join(leer[:8]), " ..." if len(leer) > 8 else ""))

    # Gelaende: je Nutzungsart ein Element
    tex = None
    if getattr(d.cfg, "gelaende_luftbild", False):
        try:
            import ifcmap_wms as _W
            lb = getattr(d, "luftbild", None) or _W.luftbild_fuer_gelaende(d, d.cfg, log)
            d.luftbild = lb
            if lb:
                bildname = os.path.splitext(os.path.basename(pfad))[0] + "_luftbild.jpg"
                lb[0].save(os.path.join(os.path.dirname(pfad), bildname), quality=88)
                tex = (lb[1], bildname)
                log("  Gelaende mit Luftbild-Textur (%s) - die Bilddatei muss neben der IFC liegen; Archicad liest Texturen aus IFC nicht immer" % bildname)
        except Exception as e:
            log("  HINWEIS: Luftbild-Textur nicht moeglich (%s)" % str(e)[:100])
    texte = {}
    for text, kat, n, ha in d.tabelle:
        texte.setdefault(kat, []).append(text)
    for kat, fl in faces_gel.items():
        lay = "Gelaende" if kat == "Gelaende" else "Gelaende_" + umlaute(kat)
        props = {"Kategorie": kat, "Flaeche_m2": round(_flaeche(fl), 1)}
        if kat in texte:
            props["Nutzungsarten_ALKIS"] = "; ".join(texte[kat])[:250]
        if gelaende_typ == "site":
            ok = element("IfcSite", lay, fl, lay, None, props=props, als_site=True, farbe=IFC_FARBEN.get(kat, kat_info(kat)[1]),
                         textur=tex if kat != "Bordstein" else None)
        else:
            ok = element("IfcGeographicElement", lay, fl, lay, site, predefined="TERRAIN", props=props,
                         farbe=IFC_FARBEN.get(kat, kat_info(kat)[1]), textur=tex if kat != "Bordstein" else None)
        n_gel += 1 if ok else 0

    # Baeume
    for i, (x, y, kr, ho, st, aus_daten) in enumerate(d.baeume if ebene_an(d.cfg, "ifc", "Baeume") else []):
        z = float(interp(x, y)) if interp else d.z0
        if math.isnan(z):
            continue
        sf, kf = baum_faces(x, y, z, kr, ho, st)
        if element("IfcGeographicElement", "Baum_%d" % (i + 1), sf + kf, "Baeume", site, predefined="USERDEFINED",
                   objtype="Baum", farbe=IFC_FARBEN["Baeume"], props={"Kronendurchmesser_m": round(kr, 2), "Hoehe_m": round(ho, 2),
                                          "Stammdurchmesser_m": round(st, 2),
                                          "Werte_aus_Daten": bool(aus_daten)}):
            n_baum += 1
    if getattr(d.cfg, "sonne", False) and ebene_an(d.cfg, "ifc", "Sonne"):
        try:
            s = sonnenbahnen(d.cfg, d)
            zc = float(interp(d.ce, d.cn)) if interp else d.z0
            if math.isnan(zc):
                zc = d.z0
            for lay, (fl, rgb) in sonne_ifc_flaechen(d, s, zc).items():
                element("IfcBuildingElementProxy", lay, fl, lay, sto, farbe=rgb,
                        props={"Radius_m": round(s["radius"], 1), "Breite": round(s["breite"], 5), "Laenge": round(s["laenge"], 5),
                               "Zeit": "MEZ/MESZ (Ortszeit Mitteleuropa)", "Nordabweichung_Grad": round(s["drehung"], 2)})
            log("  Sonnenbahn-Diagramm: Radius %.0f m, %d Bahnen" % (s["radius"], len(s["bahnen"])))
        except Exception as e:
            log("  FEHLER beim Sonnenbahn-Diagramm (IFC): %s" % e)
    for cont, els in sammel_cont.values():                 # direkt statt ueber die API (die prueft je Element alle bisherigen -> minutenlang)
        f.createIfcRelContainedInSpatialStructure(_guid.new(), None, None, None, els, cont)
    if sammel_site:
        f.createIfcRelAggregates(_guid.new(), None, None, None, proj, sammel_site)
    for lay_, reps in sammel_layer.items():
        ifcopenshell.api.layer.assign_layer(f, items=reps, layer=layers[lay_])
    for name_, els in sammel_mat.items():
        ifcopenshell.api.material.assign_material(f, products=els, material=materialien[name_])
    if uneben_liste:
        log("  Nicht ebene Flaechen (nach dem Runden): %d Flaechen in %d Elementen wurden in Dreiecke zerlegt, damit ArchiCAD keine "
            "Warnung 'Normalvektor und Kante nicht rechtwinklig' meldet" % (sum(u[1] for u in uneben_liste), len(uneben_liste)))
        for nm, k, ab in sorted(uneben_liste, key=lambda u: -u[2])[:15]:
            log("    %s: %d Flaeche(n), groesste Abweichung %.1f mm" % (nm, k, ab * 1000))
    f.write(pfad)
    return n_geb, n_gel, n_baum


# ----------------------------------------------------------------------------------------------
# Sonnenbahn-Diagramm
# ----------------------------------------------------------------------------------------------

MONATE = ["Januar", "Februar", "Maerz", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
SONNE_WENDE = [(12, "21. Dezember", "Winter", (70, 120, 220)), (3, "21. Maerz / 21. September", "Tagundnachtgleiche", (90, 170, 90)),
               (6, "21. Juni", "Sommer", (240, 150, 30))]
SONNE_HORIZONT = (120, 120, 120)
SONNE_STUNDEN = (60, 60, 60)


def _letzter_sonntag(jahr, monat):
    d = dtm.date(jahr, monat, 31)
    return d - dtm.timedelta(days=(d.weekday() + 1) % 7)


def _sommerzeit(utc):
    """EU-Sommerzeit: letzter Sonntag im Maerz 01:00 UTC bis letzter Sonntag im Oktober 01:00 UTC"""
    a = dtm.datetime.combine(_letzter_sonntag(utc.year, 3), dtm.time(1))
    b = dtm.datetime.combine(_letzter_sonntag(utc.year, 10), dtm.time(1))
    return a <= utc < b


def sonnenstand(breite, laenge, utc):
    """Sonnenstand (Naeherung, Genauigkeit ca. 0,1 Grad) fuer naive UTC-Zeit -> (Azimut von Nord im Uhrzeigersinn, Hoehe) in Grad"""
    n = (utc - dtm.datetime(2000, 1, 1, 12)).total_seconds() / 86400.0
    L = (280.460 + 0.9856474 * n) % 360
    gm = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = math.radians(L + 1.915 * math.sin(gm) + 0.020 * math.sin(2 * gm))
    eps = math.radians(23.439 - 0.0000004 * n)
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    dec = math.asin(math.sin(eps) * math.sin(lam))
    gmst = (280.46061837 + 360.98564736629 * n) % 360
    ha = math.radians(gmst + laenge) - ra
    phi = math.radians(breite)
    el = math.asin(math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * math.cos(ha))
    az = math.atan2(-math.cos(dec) * math.sin(ha), math.sin(dec) * math.cos(phi) - math.cos(dec) * math.sin(phi) * math.cos(ha))
    return math.degrees(az) % 360, math.degrees(el)


def sonnenbahnen(cfg, d):
    """Berechnet die Sonnenbahnen fuer das Projekt. Azimute sind auf das Gitternetz (Plan-Nord) bezogen.
    -> dict(breite, laenge, drehung, radius, bahnen=[dict(key, label, rgb, kurve=[(az, el)], stunden=[(h, az, el)])])"""
    from pyproj import Transformer
    lon, lat = Transformer.from_crs("EPSG:%d" % cfg.epsg, "EPSG:4326", always_xy=True).transform(d.ce, d.cn)
    zurueck = Transformer.from_crs("EPSG:4326", "EPSG:%d" % cfg.epsg, always_xy=True)
    e2, n2 = zurueck.transform(lon, lat + 0.0005)
    drehung = math.degrees(math.atan2(e2 - d.ce, n2 - d.cn))      # Gitter-Azimut von "wahr Nord" (Meridiankonvergenz)
    if 1 <= int(getattr(cfg, "sonne_monat", 0) or 0) <= 12:
        m1 = int(cfg.sonne_monat)
        eintraege = [(m1, "21. " + MONATE[m1 - 1], MONATE[m1 - 1], (240, 150, 30))]
    elif cfg.sonne_modus == "monate":
        def farbe(m):
            f = 1 - abs(m - 6) / 6.0                          # 0 = Dezember (blau) ... 1 = Juni (orange)
            return tuple(int(round(w + (so - w) * f)) for w, so in zip((70, 120, 220), (240, 150, 30)))
        eintraege = [(m, "21. " + MONATE[m - 1], MONATE[m - 1], farbe(m)) for m in range(1, 13)]
    else:
        eintraege = SONNE_WENDE
    R = cfg.sonne_radius if cfg.sonne_radius and cfg.sonne_radius > 0 else 0.4 * min(cfg.nah_breite, cfg.nah_hoehe)
    jahr = 2026
    bahnen = []
    for m, label, key, rgb in eintraege:
        tag0 = dtm.datetime(jahr, m, 21)
        kurve, stunden = [], []
        for minute in range(0, 24 * 60 + 1, 5):
            lokal = tag0 + dtm.timedelta(minutes=minute)
            utc = lokal - dtm.timedelta(hours=2 if _sommerzeit(lokal - dtm.timedelta(hours=1)) else 1)
            az, el = sonnenstand(lat, lon, utc)
            if el < 0:
                continue
            az = (az + drehung) % 360
            kurve.append((az, el))
            if minute % 60 == 0 and minute < 24 * 60:
                stunden.append((minute // 60, az, el))
        if len(kurve) >= 2:
            bahnen.append({"key": key, "label": label, "rgb": rgb, "kurve": kurve, "stunden": stunden})
    return {"breite": lat, "laenge": lon, "drehung": drehung, "radius": R, "bahnen": bahnen}


def _aci_nah(rgb):
    """naechstliegende AutoCAD-Farbnummer (1-255) zu einer RGB-Farbe (R2000-DXF kennt keine True-Color-Layer)"""
    pal = ezdxf.colors.DXF_DEFAULT_COLORS
    beste, bd = 7, 1e9
    for i in range(1, 256):
        c = pal[i]
        r, g, b = (c >> 16) & 255, (c >> 8) & 255, c & 255
        dd = (r - rgb[0]) ** 2 + (g - rgb[1]) ** 2 + (b - rgb[2]) ** 2
        if dd < bd:
            beste, bd = i, dd
    return beste


def _balken_reihe(pts, w):
    """Vierkantrohr (Seite w) entlang einer Punktfolge -> Flaechenliste (aussen orientiert)"""
    pts = [np.asarray(p, float) for p in pts]
    ringe = []
    for i, p in enumerate(pts):
        r = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)])
        L = np.linalg.norm(r)
        if L < 1e-9:
            continue
        r /= L
        ref = np.array([0.0, 0.0, 1.0]) if abs(r[2]) < 0.95 else np.array([1.0, 0.0, 0.0])
        u = np.cross(r, ref); u /= np.linalg.norm(u)
        v = np.cross(r, u)
        h = w / 2
        ringe.append((p, [p + (-u - v) * h, p + (u - v) * h, p + (u + v) * h, p + (-u + v) * h]))
    flaechen = []

    def ausrichten(q, mitte):
        q = [np.asarray(x) for x in q]
        n = np.cross(q[1] - q[0], q[2] - q[0])
        if np.dot(n, sum(q) / len(q) - mitte) < 0:
            q = q[::-1]
        return q
    for (p0, a), (p1, b) in zip(ringe[:-1], ringe[1:]):
        mitte = (p0 + p1) / 2
        for k in range(4):
            q = ausrichten([a[k], a[(k + 1) % 4], b[(k + 1) % 4], b[k]], mitte)
            flaechen += [[q[0], q[1], q[2]], [q[0], q[2], q[3]]]      # Dreiecke: die Seitenflaechen sind leicht windschief,
                                                                       # ArchiCAD verwirft windschiefe Vielecke
    if ringe:
        flaechen.append(ausrichten(ringe[0][1], ringe[0][0] - (ringe[1][0] - ringe[0][0]) if len(ringe) > 1 else ringe[0][0]))
        flaechen.append(ausrichten(ringe[-1][1], ringe[-1][0] + (ringe[-1][0] - ringe[-2][0]) if len(ringe) > 1 else ringe[-1][0]))
    return flaechen


def _wuerfel(c, a):
    c = np.asarray(c, float)
    h = a / 2
    ecken = [c + np.array([sx, sy, sz]) * h for sz in (-1, 1) for sy in (-1, 1) for sx in (-1, 1)]
    idx = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    out = []
    for q in idx:
        pts = [ecken[i] for i in q]
        n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
        out.append(pts if np.dot(n, sum(pts) / 4 - c) > 0 else pts[::-1])
    return out


def sonne_ifc_flaechen(d, s, zc):
    """-> {Layername: (Flaechen, RGB)} fuer die 3D-Sonnenbahn-Kuppel"""
    R, w = s["radius"], max(0.3, s["radius"] / 200.0)

    def p3(az, el):
        a, e = math.radians(az), math.radians(el)
        return (d.ce + R * math.cos(e) * math.sin(a), d.cn + R * math.cos(e) * math.cos(a), zc + R * math.sin(e))
    out = {}
    ring = [p3(a, 0.0) for a in range(0, 361, 5)]
    fl = _balken_reihe(ring, w)
    fl += _balken_reihe([p3(0, 0), (d.ce + 1.12 * R * math.sin(0), d.cn + 1.12 * R, zc)], w * 2)      # Nord-Marke
    for az in (90, 180, 270):
        a = math.radians(az + s["drehung"])
        fl += _balken_reihe([p3(az, 0), (d.ce + 1.06 * R * math.sin(a), d.cn + 1.06 * R * math.cos(a), zc)], w)
    out["Sonnenbahn_Horizont"] = (fl, SONNE_HORIZONT)
    stunden = []
    for b in s["bahnen"]:
        out["Sonnenbahn_" + _zeichen(b["key"], 30)] = (_balken_reihe([p3(az, el) for az, el in b["kurve"]], w), b["rgb"])
        for h, az, el in b["stunden"]:
            stunden += _wuerfel(p3(az, el), w * 3.5)
    out["Sonnenbahn_Stunden"] = (stunden, SONNE_STUNDEN)
    return out


# ----------------------------------------------------------------------------------------------
# Berlin-Zusatzdaten (Denkmal, FNP, Laerm, OEPNV, Gewaesser) - nur fuer die 2D-DXF
# ----------------------------------------------------------------------------------------------

def _lokal(tag):
    return tag.rsplit("}", 1)[-1]


def _gml_zahlen(el):
    """Koordinatenliste aus gml:posList / gml:pos / gml:coordinates unterhalb von el -> [(x, y), ...]"""
    pts = []
    for e in el.iter():
        n = _lokal(e.tag)
        if n == "posList" and e.text:
            v = [float(t) for t in e.text.split()]
            dim = int(e.get("srsDimension") or el.get("srsDimension") or (3 if len(v) % 3 == 0 and len(v) % 2 else 2))
            pts += [(v[i], v[i + 1]) for i in range(0, len(v) - dim + 1, dim)]
        elif n == "pos" and e.text:
            v = [float(t) for t in e.text.split()]
            if len(v) >= 2:
                pts.append((v[0], v[1]))
        elif n == "coordinates" and e.text:
            for t in e.text.split():
                v = [float(x) for x in t.split(",")]
                if len(v) >= 2:
                    pts.append((v[0], v[1]))
    return pts


def _gml_geom(el):
    """GML-Geometrie-Element -> Liste shapely-Geometrien (Polygon/Linie/Punkt). Achsen (Nord, Ost) werden erkannt."""
    from shapely.geometry import Polygon, LineString, Point
    out = []
    n = _lokal(el.tag)
    if n in ("Polygon", "PolygonPatch"):
        ringe = []
        for k in el:
            kn = _lokal(k.tag)
            if kn in ("exterior", "interior", "outerBoundaryIs", "innerBoundaryIs"):
                p = _gml_zahlen(k)
                if len(p) >= 3:
                    ringe.append((kn in ("exterior", "outerBoundaryIs"), p))
        aussen = [p for a, p in ringe if a]
        if aussen:
            out.append(Polygon(aussen[0], [p for a, p in ringe if not a]))
    elif n in ("LineString", "Curve"):
        p = _gml_zahlen(el)
        if len(p) >= 2:
            out.append(LineString(p))
    elif n == "Point":
        p = _gml_zahlen(el)
        if p:
            out.append(Point(p[0]))
    else:
        for k in el:
            out += _gml_geom(k)
    return out


GML_GEOM = ("Polygon", "Surface", "MultiSurface", "MultiPolygon", "LineString", "Curve", "MultiCurve", "Point", "MultiPoint",
            "CompositeSurface", "OrientableSurface")


def gml_features(daten):
    """Liest Features aus einem GML-Dokument (bytes): [(shapely-Geometrie, {Attribut: Text}), ...].
    Geometrien werden unabhaengig vom Schema gefunden; Attribute = alle Blatt-Elemente ausserhalb der Geometrie."""
    wurzel = ET.fromstring(daten)
    feats = []
    kandidaten = []
    for e in wurzel.iter():
        if _lokal(e.tag) in ("member", "featureMember", "featureMembers"):
            kandidaten += list(e) if _lokal(e.tag) == "featureMembers" else list(e)[:1]
    if not kandidaten:
        kandidaten = [wurzel]
    for f in kandidaten:
        geoms, props = [], {}

        def lauf(el, pfad):
            for k in el:
                n = _lokal(k.tag)
                if n in GML_GEOM:
                    geoms.extend(_gml_geom(k))
                    continue
                href = k.get("{http://www.w3.org/1999/xlink}href")
                if href:
                    props[n] = href.rsplit("/", 1)[-1]
                if len(k) == 0:
                    if k.text and k.text.strip():
                        props[n] = k.text.strip()
                else:
                    lauf(k, pfad + [n])
        lauf(f, [])
        if not geoms:
            continue
        g = geoms[0] if len(geoms) == 1 else unary_union(geoms)
        feats.append((g, props))
    return feats


def _in_projekt(feats, crs_in, ziel):
    """Features -> geojson_features (KBS-Umrechnung); vertauschte Achsen (Nord, Ost) werden erkannt."""
    from shapely.geometry import mapping
    if feats:
        b = feats[0][0].bounds
        if b[0] > 1e6 and 1e5 < b[1] < 1e6:                 # (Nord, Ost) statt (Ost, Nord)
            feats = [(shapely.transform(g, lambda c: c[:, ::-1]), p) for g, p in feats]
    return geojson_features({"features": [{"geometry": mapping(g), "properties": p} for g, p in feats]}, crs_in, ziel)


def _zeichen(s, n=40):
    s = umlaute(str(s))
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    return s[:n] or "Sonstige"


def _gruppe_waehlen(feats, bevorzugt):
    """Attribut zum Gruppieren: erstes passende Textattribut mit 2..20 verschiedenen Werten. -> Name oder None"""
    if not feats:
        return None
    namen = list(feats[0][1].keys())
    reihe = [n for b in bevorzugt for n in namen if n.lower() == b] + [n for b in bevorzugt for n in namen if b in n.lower()]
    for n in reihe:
        werte = {str(p.get(n)) for g, p in feats if p.get(n) not in (None, "")}
        if 2 <= len(werte) <= 40:
            return n
    return None


def _zuschneiden(feats, rect):
    out = []
    for g, p in feats:
        try:
            g = shapely.make_valid(g) if g.geom_type in ("Polygon", "MultiPolygon") and not g.is_valid else g
            c = g.intersection(rect)
        except Exception:
            continue
        if c.is_empty or (c.geom_type in ("Polygon", "MultiPolygon") and c.area < 1e-3):
            continue
        out.append((c, p))
    return out


def _art(g):
    return "poly" if g.geom_type in ("Polygon", "MultiPolygon") else ("line" if "Line" in g.geom_type else "point")


def _teile(g):
    """GeometryCollection etc. in einfache Teile auflösen"""
    if g.geom_type.startswith("Multi") or g.geom_type == "GeometryCollection":
        return [t for x in g.geoms for t in _teile(x)]
    return [g]


def _extra_sammeln(out, sub, feats):
    for g, p in feats:
        for t in _teile(g):
            out.append((sub, _art(t), t, p))


def extra_denkmal(cfg, d, ctx, log):
    ziel = os.path.join(cache_ordner(), "PS_Denkmalkarte.zip")
    if not _datei_laden(ATOM_DENKMAL, ziel, ctx, log):
        log("  Denkmalkarte nicht gefunden.")
        return []
    with zipfile.ZipFile(ziel) as z:
        namen = [n for n in z.namelist() if n.lower().endswith((".gml", ".xml"))]
        if not namen:
            log("  Die Zip enthaelt keine GML-Datei: %s" % ", ".join(z.namelist()[:10]))
            return []
        feats = []
        for n in namen:
            feats += gml_features(z.read(n))
    feats = _zuschneiden(_in_projekt(feats, "", cfg.epsg), d.rect)
    if feats:
        log("  Denkmal-Objekte im Rechteck: %d; Attribute (Beispiel): %s" % (len(feats), dict(list(feats[0][1].items())[:8])))
    out = []
    kat = (("Gesamtanlage", "Gesamtanlage"), ("Denkmalbereich", "Denkmalbereich"), ("Baudenkmal", "Baudenkmal"),
           ("Gartendenkmal", "Gartendenkmal"), ("Bodendenkmal", "Bodendenkmal"), ("Archaeolog", "Bodendenkmal"), ("Ensemble", "Denkmalbereich"))
    for g, p in feats:
        text = " ".join(str(v) for v in p.values()).lower()
        sub = next((n for k, n in kat if k.lower() in text), "")
        _extra_sammeln(out, sub, [(g, p)])
    return out


def denkmal_flaechen(cfg, d, log):
    """Baudenkmale der Berliner Denkmalkarte im Rechteck (ohne Gesamtanlagen/Denkmalbereiche, die ganze Viertel umfassen)
    -> dict(geoms, tree, namen) oder None"""
    import ifcmap_markant as M
    ctx = ssl_kontext(cfg.cafile, cfg.unsicher)
    erg = extra_denkmal(cfg, d, ctx, log)
    geoms, namen = [], []
    for sub, art, g, p in erg:
        if art != "poly" or sub in ("Gesamtanlage", "Denkmalbereich", "Gartendenkmal", "Bodendenkmal"):
            continue
        name = ""
        for k, v in p.items():
            if re.search(r"bezeich|^name|objekt.*name|titel", umlaute(str(k).lower())) and v not in (None, ""):
                s = str(v).strip()
                if re.match(r"^(https?:|urn:|[a-z]+://)", s, re.I) or len(s) > 70:       # Kennung/URL statt Name (INSPIRE-ID) -> kein Name
                    continue
                name = s[:80]
                break
        geoms.append(g)
        namen.append(name)
    fl = M.flaechen_aus(geoms, namen)
    if fl:
        log("  Baudenkmale im Rechteck: %d" % len(fl["geoms"]))
    return fl


def extra_fnp(cfg, d, ctx, log):
    out = []
    for dienst in ("fnp_2025", "fnp_ak"):
        basis = WFS_GDI + dienst
        try:
            typen = wfs_typnamen(basis, ctx)
        except Exception as e:
            log("  %s: Dienst nicht erreichbar (%s)" % (dienst, e))
            continue
        feats = []
        for typ in typen[:8]:
            obj = wfs_laden(basis, typ, d.bbox, cfg.cafile, cfg.unsicher, log)
            if obj:
                feats += geojson_features(obj, "", cfg.epsg)
        feats = _zuschneiden(feats, d.rect)
        if not feats:
            log("  %s: keine Flaechen im Rechteck (Feature-Typen: %s)" % (dienst, ", ".join(typen[:8])))
            continue
        log("  FNP (%s): %d Objekte; Attribute (Beispiel): %s" % (dienst, len(feats), dict(list(feats[0][1].items())[:10])))
        attr = _gruppe_waehlen(feats, ["nutzung", "nutz", "bezeichnung", "bez", "art", "name", "kategorie"])
        log("  FNP wird gruppiert nach: %s" % (attr or "(keine Gruppierung)"))
        for g, p in feats:
            sub = _zeichen(p.get(attr), 30) if attr and p.get(attr) not in (None, "") else ""
            _extra_sammeln(out, sub, [(g, p)])
        break
    return out


def _wfs_extra(cfg, d, basis, typ, log):
    """Eine WFS-Ebene laden und auf das Rechteck zuschneiden; protokolliert, wie viele Objekte ankamen und wo sie liegen.
    Vertauschte Achsen (Nord, Ost) werden erkannt und korrigiert; faellt die Abfrage mit Rechteck aus, wird die ganze Ebene geladen."""
    obj = wfs_laden(basis, typ, d.bbox, cfg.cafile, cfg.unsicher, log, notfall_ohne_bbox=True)
    feats = geojson_features(obj, "", cfg.epsg)
    if not feats:
        log("  %s: keine Objekte geliefert" % typ)
        return []
    rohe = len(feats)
    b = feats[0][0].bounds
    out = _zuschneiden(feats, d.rect)
    if not out and rohe:
        tausch = [(shapely.transform(g, lambda c: c[:, ::-1]), p) for g, p in feats]
        out2 = _zuschneiden(tausch, d.rect)
        if out2:
            log("  %s: Achsen vertauscht (Nord/Ost) - korrigiert" % typ)
            out = out2
    log("  %s: %d geladen, %d im Rechteck (erstes Objekt bei Ost %.0f / Nord %.0f, Gebiet bei Ost %.0f / Nord %.0f)"
        % (typ, rohe, len(out), b[0], b[1], d.ce, d.cn))
    return out


def _vorrang_sub(props, nacht):
    """Eigenschaften eines Vorrangnetz-Objekts -> Untergruppe (Ebenenname): [Nacht_][Geplant_]Tram|Bus|Netz.
    Echte Werte des Dienstes (Test 28.10.2026): vorrangtyp = Bus | Tram | Bus_Zukunft | Tram_Zukunft | NBS | leer (kein Vorrang);
    v_zukunft = 1 und v_z_jahr bei geplanten Strecken. Die S-Bahn gehoert nicht zum Vorrangnetz (kommt aus OpenStreetMap)."""
    vt = umlaute(str(props.get("vorrangtyp") or "").lower())
    geplant = "zukunft" in vt or vt.strip() == "nbs" or str(props.get("v_zukunft") or "").strip() in ("1", "1.0")
    if "tram" in vt:
        art = "Tram"
    elif "bus" in vt:
        art = "Bus"
    else:
        werte = umlaute(" ".join(str(v) for k, v in props.items() if v not in (None, "") and k not in ("linien", "no")).lower())
        art = "Tram" if re.search(r"tram|strassenbahn", werte) else ("Bus" if re.search(r"\bbus\b|metrobus", werte) else "Netz")
    return ("Nacht_" if nacht else "") + ("Geplant_" if geplant else "") + art


def extra_oepnv(cfg, d, ctx, log):
    """OEPNV-Linien: amtlich das Berliner OEPNV-Vorrangnetz (Strassenbahn/Bus, Nachtnetz, geplante und im Bau befindliche Strecken), Haltestellen
    aus dem BVG-Netz; fehlen im amtlichen Ergebnis S-Bahn oder geplante Strecken, ergaenzt OpenStreetMap genau diese (siehe osm_extra_oepnv_luecken).
    Ist das Vorrangnetz nicht erreichbar, gilt ersatzweise das BVG-Netz (ungestoert). Bisher nicht gegen den Live-Dienst getestet."""
    out = []
    basis = WFS_GDI + "vorrangnetz"
    typen = []
    try:
        typen = [n for n in wfs_typnamen(basis, ctx)]
    except Exception as e:
        log("  (Typenliste des Vorrangnetz-Dienstes nicht lesbar: %s)" % str(e)[:100])
    if not typen:
        typen = ["vorrangnetz:a_oepnv_vorrangnetz", "vorrangnetz:b_oepnv_nachtangebot"]
    for typ in typen:
        nacht = "nacht" in typ.lower()
        feats = [(g, p) for g, p in _wfs_extra(cfg, d, basis, typ, log) if g.geom_type != "Point"]
        if not feats:
            continue
        log("  %s: Attribute (Beispiel): %s" % (typ, dict(list(feats[0][1].items())[:10])))
        for g, p in feats:
            _extra_sammeln(out, _vorrang_sub(p, nacht), [(g, p)])
        zaehl = {}
        for sub, *_ in out:
            zaehl[sub] = zaehl.get(sub, 0) + 1
        log("  Vorrangnetz-Untergruppen: " + ", ".join("%s %d" % kv for kv in sorted(zaehl.items())))
    if not out:                                          # Ersatz: BVG-Netz (ungestoert)
        log("  Vorrangnetz lieferte nichts - Ersatz: BVG-Netz (ungestoert)")
        for typ, sub in (("oepnv_ungestoert:d_tramlinien", "Tram"), ("oepnv_ungestoert:c_buslinien", "Bus")):
            _extra_sammeln(out, sub, _wfs_extra(cfg, d, WFS_GDI + "oepnv_ungestoert", typ, log))
    for typ, sub in (("oepnv_ungestoert:b_tramstopp", "Tram_Haltestellen"), ("oepnv_ungestoert:a_busstopp", "Bus_Haltestellen")):
        try:
            _extra_sammeln(out, sub, _wfs_extra(cfg, d, WFS_GDI + "oepnv_ungestoert", typ, log))
        except Exception as e:
            log("  %s: nicht ladbar (%s)" % (sub, str(e)[:80]))
    if out:                                              # nur was amtlich fehlt, aus OpenStreetMap ergaenzen
        vorhanden = {s for s, *_ in out}
        fehlt = []
        if not any("SBahn" in s for s in vorhanden):
            fehlt.append("SBahn")
        if not any("Geplant" in s for s in vorhanden):
            fehlt.append("Geplant")
        if fehlt:
            try:
                plus = osm_extra_oepnv_luecken(cfg, d, log, fehlt)
                log("  OpenStreetMap ergaenzt (amtlich nicht vorhanden: %s): %d Objekte" % (", ".join(fehlt), len(plus)))
                out += plus
            except Exception as e:
                log("  OpenStreetMap-Ergaenzung nicht moeglich (%s)" % str(e)[:100])
    return out


def extra_gewaesser(cfg, d, ctx, log):
    basis = WFS_GDI + "atkis"
    bekannt = [("atkis:c41_ax_fliessgewaesser_f", "Wasserflaeche"), ("atkis:b15_ax_gewaesserachse_l", "Achse"),
               ("atkis:c42_ax_hafenbecken_f", "Wasserflaeche")]
    try:                                     # weitere Gewaessertypen (z. B. Standgewaesser) im Dienst suchen
        for n in wfs_typnamen(basis, ctx):
            low = n.lower()
            if "standgewaesser" in low or "stehendesgewaesser" in low:
                bekannt.append((n, "Wasserflaeche"))
    except Exception as e:
        log("  (Typenliste des Dienstes nicht lesbar: %s)" % e)
    out = []
    for typ, sub in bekannt:
        feats = _wfs_extra(cfg, d, basis, typ, log)
        _extra_sammeln(out, sub, feats)
    return out


def extra_radverkehr(cfg, d, ctx, log):
    """Radverkehrsnetz Berlin (gdi.berlin.de, Dienst 'radverkehrsnetz'). Die Feature-Typen stammen aus der Dienstbeschreibung;
    liefert ein Typ nichts, wird die Typenliste des Dienstes nach 'rad'/'gruen' durchsucht. Bisher nicht gegen den Live-Dienst getestet."""
    basis = WFS_GDI + "radverkehrsnetz"
    arten = [("radverkehrsnetz:radverkehrsnetz", "Radnetz"), ("radverkehrsnetz:radfernwege", "Radfernwege"),
             ("radverkehrsnetz:stadtgruen", "Gruene_Hauptwege")]
    out = []
    for typ, sub in arten:
        try:
            feats = _wfs_extra(cfg, d, basis, typ, log)
        except Exception as e:
            log("  %s: nicht ladbar (%s)" % (typ, str(e)[:100]))
            feats = []
        if feats:
            log("  %s: Attribute (Beispiel): %s" % (sub, dict(list(feats[0][1].items())[:8])))
        ist_gepl = lambda p: str((p or {}).get("existenz", "")).strip().lower() == "nein"
        gepl = [(g, p) for g, p in feats if ist_gepl(p)]
        if gepl:                                                     # geplante, noch nicht gebaute Strecken: eigene Gruppe, keine Wege
            log("  %s: %d geplante (noch nicht vorhandene) Strecken -> Gruppe %s_geplant, nicht als Weg" % (sub, len(gepl), sub))
            _extra_sammeln(out, sub + "_geplant", gepl)
        _extra_sammeln(out, sub, [(g, p) for g, p in feats if not ist_gepl(p)])
    if not out:
        try:
            bekannt = {t for t, _ in arten}
            for n in wfs_typnamen(basis, ctx):
                if n in bekannt or "untersuchung" in n.lower():
                    continue
                feats = _wfs_extra(cfg, d, basis, n, log)
                _extra_sammeln(out, "Radnetz", feats)
        except Exception as e:
            log("  (Typenliste des Dienstes nicht lesbar: %s)" % e)
    return out


def rad_als_nutzung(cfg, d, ctx, log):
    """Radverkehrsnetz (Linien) -> Wegeflaechen als zusaetzliche Nutzungsobjekte [(Polygon, Eigenschaften)]. Sie gelten als 'Weg':
    Strassen, Bahn und Gewaesser behalten Vorrang (Radfahrstreifen auf der Fahrbahn aendern also nichts), Gruen/Wald/Siedlung weichen dem Weg."""
    log("Radverkehrsnetz als Quelle fuer Wege (Berlin):")
    out = []
    breite0 = float(getattr(cfg, "rad_breite", 2.5) or 2.5)
    for sub, art, g, p in extra_radverkehr(cfg, d, ctx, log):
        if art != "line" or sub.endswith("_geplant"):
            continue
        ex = umlaute(str((p or {}).get("existenz") or "").lower())
        if "stra" in ex:                                             # 'ja, in Strassennetz': liegt schon auf der Strassenflaeche
            continue
        w = feldwert(p, r"breite|width")
        w = w if (w and 0.5 <= w <= 12.0) else breite0
        poly = g.buffer(w / 2.0, cap_style=2, join_style=2)
        if not poly.is_empty:
            out.append((poly, {"nutzung": "Weg (Radverkehrsnetz)"}))
    log("  -> %d Wegeflaechen aus dem Radverkehrsnetz (Breite %.1f m, wenn der Dienst keine angibt)" % (len(out), breite0))
    return out


def extra_laerm(cfg, d, ctx, log):
    try:
        import rasterio
        from rasterio.features import shapes
        from rasterio.windows import from_bounds
    except Exception:
        log("  Die Laermkarte braucht das Paket rasterio (pip install rasterio).")
        return []
    art = cfg.laerm_art if cfg.laerm_art in LAERM_ARTEN else "gesamtlaerm"
    wert = "L_N" if str(cfg.laerm_wert).upper() == "L_N" else "L_DEN"
    ziel = os.path.join(cache_ordner(), "strat_laerm_2022_%s.zip" % art)
    if not _datei_laden(ATOM_LAERM % art, ziel, ctx, log):
        log("  Laermkarte nicht gefunden.")
        return []
    with zipfile.ZipFile(ziel) as z:
        tifs = [n for n in z.namelist() if n.lower().endswith((".tif", ".tiff"))]
        if not tifs:
            log("  Die Zip enthaelt keine GeoTIFF: %s" % ", ".join(z.namelist()[:10]))
            return []
        passend = [n for n in tifs if wert.lower().replace("_", "") in n.lower().replace("_", "")] or tifs
        if wert == "L_N":
            passend = [n for n in passend if "den" not in os.path.basename(n).lower().replace("_", "")] or passend
        tif = passend[0]
        ordner = os.path.join(cache_ordner(), "laerm_" + art)
        os.makedirs(ordner, exist_ok=True)
        lokal = os.path.join(ordner, os.path.basename(tif))
        if not os.path.exists(lokal):
            with open(lokal, "wb") as f:
                f.write(z.read(tif))
    log("  Rasterdatei: %s" % os.path.basename(lokal))
    with rasterio.open(lokal) as r:
        if r.crs is not None and r.crs.to_epsg() not in (None, cfg.epsg):
            log("  WARNUNG: Raster in EPSG:%s, Projekt in EPSG:%d - Laermkarte wird uebersprungen." % (r.crs.to_epsg(), cfg.epsg))
            return []
        win = from_bounds(d.xmin, d.ymin, d.xmax, d.ymax, r.transform).round_offsets().round_lengths()
        a = r.read(1, window=win, masked=True, boundless=True)
        tr = r.window_transform(win)
        cs = abs(tr.a)
    if a.size == 0 or a.mask.all():
        log("  Laermkarte: keine Werte im Rechteck.")
        return []
    v = np.ma.filled(a.astype("float64"), np.nan)
    log("  Laermwerte im Rechteck: %.0f bis %.0f dB (Zellgroesse %.0f m)" % (np.nanmin(v), np.nanmax(v), cs))
    klasse = np.floor(v / 5.0) * 5
    klasse = np.where(np.isnan(v) | (v < 40), -1, np.clip(klasse, 45, 80)).astype("int16")
    out = []
    for geo, val in shapes(klasse, mask=klasse >= 45, transform=tr):
        val = int(val)
        g = shape(geo).intersection(d.rect)
        if g.is_empty:
            continue
        sub = "%d_%s" % (val, "ueber_80" if val >= 80 else str(val + 5))
        _extra_sammeln(out, sub, [(g, {"band": val})])
    # Teilflaechen je Band vereinigen und glaetten
    nach = {}
    for sub, art_, g, p in out:
        nach.setdefault(sub, []).append(g)
    out = []
    for sub, liste in nach.items():
        u = unary_union(liste).buffer(cs * 0.4, join_style=1).buffer(-cs * 0.4, join_style=1).simplify(cs * 0.3).intersection(d.rect)
        for t in _teile(u):
            out.append((sub, _art(t), t, {}))
    log("  Laermbaender: %s" % ", ".join(sorted(nach)))
    return out


EXTRA_LADER = {"denkmal": extra_denkmal, "fnp": extra_fnp, "oepnv": extra_oepnv, "gewaesser": extra_gewaesser, "laerm": extra_laerm,
               "radverkehr": extra_radverkehr}


def _osm_elemente(abfrage_teile, cfg, d, log):
    """Overpass-Abfrage (Liste von Teilen wie 'way["waterway"]') fuer das Rechteck -> Elemente (JSON, 'out geom')."""
    from pyproj import Transformer
    tr = Transformer.from_crs("EPSG:%d" % cfg.epsg, "EPSG:4326", always_xy=True)
    lons, lats = zip(*[tr.transform(x, y) for x in (d.xmin, d.xmax) for y in (d.ymin, d.ymax)])
    bb = "(%.6f,%.6f,%.6f,%.6f)" % (min(lats), min(lons), max(lats), max(lons))
    q = "[out:json][timeout:%d];(" % OSM_TIMEOUT + "".join(t + bb + ";" for t in abfrage_teile) + ");out geom;"
    js = osm_abfragen(q, ssl_kontext(cfg.cafile, cfg.unsicher), log)
    return (js or {}).get("elements", [])


def _osm_geometrien(elemente, epsg):
    """Overpass-Elemente -> [(Geometrie im Projekt-KBS, Tags)]: Knoten = Punkt, Weg = Linie (geschlossen + Flaeche = Polygon),
    Relation = Multipolygon oder (Routen) Linien aller Mitglieder."""
    from pyproj import Transformer
    from shapely.geometry import Point, LineString, Polygon, MultiLineString
    from shapely.ops import polygonize
    tr = Transformer.from_crs("EPSG:4326", "EPSG:%d" % epsg, always_xy=True)

    def xy(geo):
        X, Y = tr.transform([p["lon"] for p in geo], [p["lat"] for p in geo])
        return list(zip(X, Y))
    out = []
    for el in elemente:
        t = dict(el.get("tags") or {})
        t["_osm"] = "%s/%s" % (el.get("type"), el.get("id"))              # OSM-Kennung (fuer Protokoll und IFC-Eigenschaften)
        try:
            if el["type"] == "node":
                x, y = tr.transform(el["lon"], el["lat"])
                out.append((Point(x, y), t))
            elif el["type"] == "way" and el.get("geometry"):
                pts = xy(el["geometry"])
                if len(pts) >= 4 and pts[0] == pts[-1] and (t.get("area") == "yes" or t.get("waterway") == "riverbank" or "waterway" not in t and "railway" not in t and "highway" not in t
                                                            and t.get("route") is None):
                    out.append((Polygon(pts), t))
                elif len(pts) >= 2:
                    out.append((LineString(pts), t))
            elif el["type"] == "relation":
                mem = [m for m in el.get("members", []) if m.get("geometry")]
                if t.get("type") == "multipolygon":
                    aussen = [LineString(xy(m["geometry"])) for m in mem if m.get("role") == "outer"]
                    innen = [LineString(xy(m["geometry"])) for m in mem if m.get("role") == "inner"]
                    if aussen:
                        pa = unary_union(list(polygonize(unary_union(aussen))))
                        if innen:
                            pa = pa.difference(unary_union(list(polygonize(unary_union(innen)))))
                        if not pa.is_empty:
                            out.append((pa, t))
                else:
                    linien = [LineString(xy(m["geometry"])) for m in mem if len(m["geometry"]) >= 2 and m.get("type") == "way"]
                    if linien:
                        out.append((MultiLineString(linien), t))
        except Exception:
            continue
    return out


def osm_extra_oepnv(cfg, d, log):
    el = _osm_elemente(['way["railway"="tram"]', 'relation["route"="bus"]', 'relation["route"="trolleybus"]',
                        'way["railway"="light_rail"]["service"!~"siding|yard|spur|crossover"]',
                        'node["highway"="bus_stop"]', 'node["railway"="tram_stop"]'], cfg, d, log)
    out = []
    for g, t in _zuschneiden(_osm_geometrien(el, cfg.epsg), d.rect):
        if t.get("railway") == "light_rail":
            sub = "SBahn"
        elif t.get("railway") == "tram":
            sub = "Tram_Linien"
        elif t.get("route") in ("bus", "trolleybus"):
            sub = "Bus_Linien"
        elif t.get("railway") == "tram_stop":
            sub = "Tram_Haltestellen"
        elif t.get("highway") == "bus_stop":
            sub = "Bus_Haltestellen"
        else:
            continue
        _extra_sammeln(out, sub, [(g, t)])
    return out


def osm_extra_gewaesser(cfg, d, log):
    el = _osm_elemente(['way["waterway"]', 'way["natural"="water"]', 'relation["natural"="water"]', 'way["waterway"="riverbank"]'], cfg, d, log)
    out = []
    for g, t in _zuschneiden(_osm_geometrien(el, cfg.epsg), d.rect):
        if t.get("tunnel") in ("yes", "culvert"):
            continue
        sub = "Wasserflaeche" if g.geom_type in ("Polygon", "MultiPolygon") else "Achse"
        _extra_sammeln(out, sub, [(g, t)])
    return out


def osm_extra_denkmal(cfg, d, log):
    el = _osm_elemente(['nwr["heritage"]', 'nwr["historic"="archaeological_site"]', 'nwr["historic"="monument"]'], cfg, d, log)
    out = []
    for g, t in _zuschneiden(_osm_geometrien(el, cfg.epsg), d.rect):
        sub = "Bodendenkmal" if t.get("historic") == "archaeological_site" else ("Gartendenkmal" if t.get("leisure") in ("park", "garden") else "Baudenkmal")
        _extra_sammeln(out, sub, [(g, dict(t))])
    return out


def osm_extra_oepnv_luecken(cfg, d, log, was):
    """S-Bahn (railway=light_rail) und geplante/im Bau befindliche Tram- und S-Bahn-Strecken aus OpenStreetMap"""
    teile = []
    if "SBahn" in was:
        teile += ['way["railway"="light_rail"]["service"!~"siding|yard|spur|crossover"]']
    if "Geplant" in was:
        teile += ['way["railway"="construction"]["construction"~"tram|light_rail"]', 'way["railway"="proposed"]["proposed"~"tram|light_rail"]',
                  'way["proposed:railway"~"tram|light_rail"]', 'way["construction:railway"~"tram|light_rail"]']
    if not teile:
        return []
    el = _osm_elemente(teile, cfg, d, log)
    out = []
    for g, t in _zuschneiden(_osm_geometrien(el, cfg.epsg), d.rect):
        if g.geom_type not in ("LineString", "MultiLineString"):
            continue
        geplant = t.get("railway") in ("construction", "proposed") or "proposed:railway" in t or "construction:railway" in t
        if geplant:
            sub = "Geplant_" + ("SBahn" if "light_rail" in str(t.get("construction") or t.get("proposed") or t.get("proposed:railway") or t.get("construction:railway")) else "Tram")
            if (("Geplant" not in was) or sub is None):
                continue
        else:
            if "SBahn" not in was:
                continue
            sub = "SBahn"
        _extra_sammeln(out, sub, [(g, t)])
    return out


def osm_extra_radverkehr(cfg, d, log):
    el = _osm_elemente(['way["highway"="cycleway"]', 'way["cycleway"~"track|lane|share_busway|opposite_track|opposite_lane"]',
                        'way["cycleway:left"~"track|lane"]', 'way["cycleway:right"~"track|lane"]', 'way["cycleway:both"~"track|lane"]',
                        'relation["route"="bicycle"]["network"~"icn|ncn|rcn"]'], cfg, d, log)
    out = []
    for g, t in _zuschneiden(_osm_geometrien(el, cfg.epsg), d.rect):
        if g.geom_type not in ("LineString", "MultiLineString"):
            continue
        sub = "Radfernwege" if t.get("route") == "bicycle" else ("Radnetz" if t.get("highway") == "cycleway" else "Radspuren")
        _extra_sammeln(out, sub, [(g, t)])
    return out


OSM_EXTRA = {"oepnv": osm_extra_oepnv, "gewaesser": osm_extra_gewaesser, "denkmal": osm_extra_denkmal, "radverkehr": osm_extra_radverkehr}


def extra_laden(cfg, d, log, prog=_noop):
    """Zusatzdaten laden: amtlich (Berlin), sonst/ersatzweise OpenStreetMap (OEPNV, Gewaesser, Denkmal).
    -> {Schluessel: [(Untergruppe, 'poly'|'line'|'point', Geometrie, Attribute), ...]}"""
    ergebnis = {}
    gewaehlt = [k for k in (cfg.extra or []) if k in EXTRA_LADER]
    if not gewaehlt:
        return ergebnis
    berlin = ist_berlin(cfg) and cfg.epsg == 25833
    ctx = ssl_kontext(cfg.cafile, cfg.unsicher)
    for i, k in enumerate(gewaehlt):
        prog(0.9 + 0.09 * i / len(gewaehlt), "Zusatzdaten: %s ..." % EXTRA_NAMEN.get(k, k))
        log("Zusatzdaten %s:" % EXTRA_KATALOG[k][0])
        erg = []
        if berlin:
            log("  Quelle: amtlich (Berlin)")
            try:
                erg = EXTRA_LADER[k](cfg, d, ctx, log)
            except Exception as e:
                log("  FEHLER bei %s: %s" % (k, e))
        if not erg and k in OSM_EXTRA:
            log("  Quelle: OpenStreetMap%s" % (" (Ersatz, amtliche Daten lieferten nichts)" if berlin else " (kein amtlicher Dienst hinterlegt)"))
            try:
                erg = OSM_EXTRA[k](cfg, d, log)
            except Exception as e:
                log("  FEHLER bei %s (OpenStreetMap): %s" % (k, e))
        elif not erg and not berlin:
            log("  Fuer diese Ebene gibt es ausserhalb Berlins keine hinterlegte Quelle (auch nicht in OpenStreetMap) - uebersprungen. "
                "Eigene Daten lassen sich als GeoJSON-Datei hinzufuegen.")
        if erg:
            ergebnis[k] = erg
            log("  -> %d Objekte uebernommen" % len(erg))
        else:
            log("  -> keine Objekte im Rechteck (oder Dienst nicht erreichbar)")
    return ergebnis


# ----------------------------------------------------------------------------------------------
# 2D-DXF (Arbeitsblaetter)
# ----------------------------------------------------------------------------------------------

def _polys(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    if hasattr(g, "geoms"):
        return [p for x in g.geoms for p in _polys(x)]
    return []


def _sauber(geom, fang=0.01, tol=0.05, min_flaeche=0.5, min_loch=1.0):
    """Geometrie fuer die 2D-Zeichnung aufraeumen: gueltig machen, auf Zentimeter-Raster einrasten
    (damit gemeinsame Kanten exakt zusammenfallen), Zwischenpunkte auf geraden Strecken entfernen,
    Splitter und Minilocher streichen. -> Liste von Polygonen (Aussenring gegen den Uhrzeigersinn)."""
    from shapely.geometry import Polygon
    from shapely.geometry.polygon import orient
    out = []
    for p in _polys(geom):
        if not p.is_valid:
            p = shapely.make_valid(p)
        for q in _polys(p):
            q = q.simplify(tol, preserve_topology=True)
            if fang:
                q = shapely.set_precision(q, fang)
            for r in _polys(q.buffer(0)):
                if r.area < min_flaeche:
                    continue
                loecher = [i for i in r.interiors if Polygon(i).area >= min_loch]
                out.append(orient(Polygon(r.exterior, loecher), 1.0))
    return out


PLAN_NAMEN = {"lageplan": "Lageplan", "schwarzplan": "Schwarzplan"}
DXF_VERSION = "R2010"            # R2010: True-Color (Layer + Objekte) und Transparenz


class Zeichner:
    """Duenne Huelle um ezdxf: lokale Koordinaten, True-Color, Schraffuren (Flaechen gibt es nur als Schraffur), Linien, Kreise, Text."""

    def __init__(self, d):
        self.d = d
        self.doc = ezdxf.new(DXF_VERSION)
        self.doc.header["$INSUNITS"] = 6
        self.doc.header["$MEASUREMENT"] = 1
        self.msp = self.doc.modelspace()
        self.s2 = np.array([d.e0, d.n0])
        self.geschrieben = set()
        self.n_flaechen = 0

    def loc(self, c):
        return [(round(float(p[0]), 3), round(float(p[1]), 3)) for p in (np.asarray(c)[:, :2] - self.s2)]

    def layer(self, name, rgb=None, aci=None):
        if name not in self.doc.layers:
            l = self.doc.layers.add(name, color=aci if aci else (_aci_nah(rgb) if rgb else 7))
            if rgb:
                l.rgb = tuple(int(v) for v in rgb)
        return name

    def flaeche(self, geom, layer, rgb, aci=None, transparenz=0.0, min_flaeche=0.5, min_loch=1.0, sauber=True):
        """Flaeche (Polygon/MultiPolygon, absolute Koordinaten) als Schraffur in einem Vollton; keine Umrisslinien.
        transparenz: 0 = deckend ... 1 = unsichtbar."""
        self.layer(layer, rgb, aci)
        n = 0
        polys = _sauber(geom, min_flaeche=min_flaeche, min_loch=min_loch) if sauber else _polys(geom)
        for p in polys:
            h = self.msp.add_hatch(color=aci or _aci_nah(rgb), dxfattribs={"layer": layer})
            h.set_solid_fill(color=aci or _aci_nah(rgb), style=0, rgb=ezdxf.colors.RGB(*[int(v) for v in rgb]))
            if transparenz and transparenz > 0:
                h.transparency = float(transparenz)
            h.paths.add_polyline_path(self.loc(p.exterior.coords)[:-1], is_closed=True, flags=ezdxf.const.BOUNDARY_PATH_EXTERNAL)
            for i in p.interiors:
                h.paths.add_polyline_path(self.loc(i.coords)[:-1], is_closed=True, flags=0)      # Loch (Standardpfad, nicht "aussen")
            n += 1
        self.n_flaechen += n
        return n

    def linie(self, coords, layer, rgb=None, aci=None, geschlossen=False):
        """Polylinie (nur fuer Linien: Grenzen, Kronen, Firste, Rahmen ...)"""
        self.layer(layer, rgb, aci)
        pts = self.loc(coords)
        if geschlossen and len(pts) > 1 and pts[0] == pts[-1]:
            pts = pts[:-1]
        sauber = []                                   # Punkte naeher als 2 cm zusammenziehen
        for p in pts:
            if not sauber or math.hypot(p[0] - sauber[-1][0], p[1] - sauber[-1][1]) >= 0.02:
                sauber.append(p)
        while geschlossen and len(sauber) > 1 and math.hypot(sauber[0][0] - sauber[-1][0], sauber[0][1] - sauber[-1][1]) < 0.02:
            sauber.pop()
        pts = sauber
        schluessel = (layer, tuple(sorted(pts)))
        if len(pts) < 2 or schluessel in self.geschrieben:  # keine Doppelten
            return None
        self.geschrieben.add(schluessel)
        e = self.msp.add_lwpolyline(pts, close=geschlossen and len(pts) >= 3, dxfattribs={"layer": layer})
        if rgb:
            e.rgb = tuple(int(v) for v in rgb)
        return e

    def kreis(self, x, y, r, layer, rgb=None, aci=None):
        self.layer(layer, rgb, aci)
        e = self.msp.add_circle((round(x - self.d.e0, 3), round(y - self.d.n0, 3)), round(r, 3), dxfattribs={"layer": layer})
        if rgb:
            e.rgb = tuple(int(v) for v in rgb)
        return e

    def speichern(self, pfad):
        try:
            ezdxf.zoom.extents(self.msp)
        except Exception:
            pass
        _extents_setzen(self.doc)
        self.doc.saveas(pfad)


def gebaeude_umrisse(d):
    """Grundrisse fuer die 2D-Plaene -> (nah, fern) als Listen von Polygonen. ALKIS-Grundrisse (Berlin) haben Vorrang vor LoD2; was in den
    3D-Teilen (LoD2, ergaenzte OSM-Gebaeude) steht, in ALKIS aber fehlt (z. B. Gartenlauben), wird als Rest dazugenommen - sonst gaebe es
    Schatten ohne Gebaeude. Wird einmal berechnet und an d gemerkt."""
    from shapely.geometry import Polygon
    cfg = d.cfg
    zus = getattr(d, "zusatz", {}) or {}
    schl = (id(zus.get("Gebaeude")), len(d.teile))
    c_ = getattr(d, "_umrisse_cache", None)
    if c_ and c_[0] == schl:
        return c_[1]
    quellen = []
    if zus.get("Gebaeude"):
        quellen = [g for g, props in zus["Gebaeude"]]
    eigene = []
    for t in d.teile:
        for e, holes in t["ground"]:
            if len(e) >= 3:
                p = Polygon(e[:, :2], [h[:, :2] for h in holes if len(h) >= 3])
                eigene.append(p if p.is_valid else p.buffer(0))
    if not quellen:
        quellen = eigene
        n_extra = 0
    elif not getattr(cfg, "grundrisse_abgleich", True):
        n_extra = 0                                         # Abgleich abgeschaltet: nur ALKIS
    else:
        import shapely
        alk = unary_union([q for q in quellen if q is not None and not q.is_empty]).buffer(0.3)
        shapely.prepare(alk)
        extra = []
        for p in eigene:
            if p.is_empty:
                continue
            if not alk.intersects(p):
                rest = p
            else:
                rest = p.difference(alk)
                if rest.is_empty or rest.area < max(1.0, 0.3 * p.area):
                    continue
            if rest.area >= 1.0:
                extra.append(rest)
        quellen = list(quellen) + extra
        n_extra = len(extra)
    d._umrisse_extra = n_extra
    nah, fern = [], []
    for g in quellen:
        for p in _polys(g):
            c = p.representative_point()
            (nah if nah_enthaelt(cfg, d, c.x, c.y) else fern).append(p)
    d._umrisse_cache = (schl, (nah, fern))
    return nah, fern


def gebaeude_vereint(liste):
    """winzige Spalten zwischen Gebaeudeteilen schliessen (mitre) -> MultiPolygon/Polygon"""
    if not liste:
        return None
    return unary_union([p.buffer(0.03, join_style=2) for p in liste]).buffer(-0.03, join_style=2)


def _dxf_sonne(z, d):
    """Sonnenbahn-Diagramm (Linien) + Markierung des Schattenzeitpunkts"""
    cfg = d.cfg
    from ezdxf.enums import TextEntityAlignment
    s = sonnenbahnen(cfg, d)
    R = s["radius"]
    hoehe = max(1.5, R / 40.0)

    def plan(az, el):
        r = R * (90.0 - el) / 90.0
        a = math.radians(az)
        return (d.ce + r * math.sin(a), d.cn + r * math.cos(a))

    def text(t, x, y, layer_, h=hoehe):
        z.layer(layer_)
        e = z.msp.add_text(t, height=h, dxfattribs={"layer": layer_})
        e.set_placement((round(x - d.e0, 3), round(y - d.n0, 3)), align=TextEntityAlignment.MIDDLE_CENTER)
    l_h = z.layer("2D_Sonne_Horizont", aci=8)
    for el in (0, 30, 60):
        z.kreis(d.ce, d.cn, R * (90.0 - el) / 90.0, l_h)
        if el:
            text("%d°" % el, d.ce + R * (90.0 - el) / 90.0 * math.sin(math.radians(45 + s["drehung"])),
                 d.cn + R * (90.0 - el) / 90.0 * math.cos(math.radians(45 + s["drehung"])), l_h, hoehe * 0.7)
    for az, name in ((0, "N"), (90, "O"), (180, "S"), (270, "W")):
        a = math.radians(az + s["drehung"])
        z.linie([(d.ce, d.cn), (d.ce + R * math.sin(a), d.cn + R * math.cos(a))], l_h)
        text(name, d.ce + 1.1 * R * math.sin(a), d.cn + 1.1 * R * math.cos(a), l_h, hoehe * (1.6 if az == 0 else 1.2))
    for b in s["bahnen"]:
        l_b = z.layer("2D_Sonne_Bahn_" + _zeichen(b["key"], 30), b["rgb"])
        z.linie([plan(az, el) for az, el in b["kurve"]], l_b, rgb=b["rgb"])
    l_s = z.layer("2D_Sonne_Stunden", aci=7)
    l_t = z.layer("2D_Sonne_Beschriftung", aci=7)
    for b in s["bahnen"]:
        for h, az, el in b["stunden"]:
            x, y = plan(az, el)
            z.kreis(x, y, hoehe * 0.25, l_s)
            if len(s["bahnen"]) <= 3 or len(s["bahnen"]) == 1:
                text(str(h), x + hoehe * 0.9, y + hoehe * 0.9, l_s, hoehe * 0.7)
    text("Sonnenbahn %.2f N %.2f O - Zeit: MEZ/MESZ - Nord = Plan-Nord um %.1f° gedreht" % (s["breite"], s["laenge"], s["drehung"]),
         d.ce, d.cn - R * 1.2, l_t, hoehe * 0.8)
    for i, b in enumerate(s["bahnen"][:3] if len(s["bahnen"]) <= 3 else []):
        text(b["label"], d.ce, d.cn - R * 1.3 - i * hoehe * 1.2, "2D_Sonne_Bahn_" + _zeichen(b["key"], 30), hoehe * 0.8)
    # Schattenzeitpunkt im Diagramm markieren (eigene Rechnung des Schattenmoduls)
    if getattr(cfg, "schatten", "aus") != "aus" and getattr(cfg, "sonne_marke", True):
        import ifcmap_schatten as SC
        so = SC.sonne_fuer_plan(cfg, d)
        if so and so["el"] > 0:
            x, y = plan(so["az"], so["el"])
            l_m = z.layer("2D_Sonne_Schattenpunkt", (220, 30, 30))
            z.kreis(x, y, hoehe * 0.7, l_m, rgb=(220, 30, 30))
            z.kreis(x, y, hoehe * 0.2, l_m, rgb=(220, 30, 30))
            text("Schatten: %d.%d. %02d:%02d" % (so["lokal"].day, so["lokal"].month, so["lokal"].hour, so["lokal"].minute),
                 x + hoehe * 3.5, y - hoehe * 1.2, l_m, hoehe * 0.8)


def _dxf_standard(z, d):
    """Die gewoehnliche 2D-DXF. Ebenen (alle Layer mit 2D_ beginnend); Flaechen sind ausschliesslich Schraffuren:
         2D_Rahmen_Gebiet / 2D_Rahmen_Nahbereich     Umrandungen (Linien)
         2D_Gebaeude_Nah / _Fern                      Grundrisse (Schraffur), zusammenhaengende Teile vereinigt
         2D_Nutzung_<Art>                             je Nutzungsart eine Schraffur (Vollton)
         2D_Nutzung_Grenzen                           alle Nutzungsgrenzen als Linien (nur auf Wunsch)
         2D_Baeume_Krone                              Kreise (Linien)
         2D_ALKIS_Flurstuecke (Linien) / _Bauwerke (Schraffur)   (Berlin, optional)"""
    from shapely.ops import linemerge
    cfg = d.cfg

    def an(schluessel, vorgabe=True):
        return ebene_an(cfg, "dxf", schluessel, vorgabe)

    # --- Rahmen
    x0, x1, y0, y1 = d.xmin, d.xmax, d.ymin, d.ymax
    if an("Rahmen"):
        z.linie([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z.layer("2D_Rahmen_Gebiet", aci=5), geschlossen=True)
        z.linie([(d.ce - cfg.nah_breite / 2, d.cn - cfg.nah_hoehe / 2), (d.ce + cfg.nah_breite / 2, d.cn - cfg.nah_hoehe / 2),
                 (d.ce + cfg.nah_breite / 2, d.cn + cfg.nah_hoehe / 2), (d.ce - cfg.nah_breite / 2, d.cn + cfg.nah_hoehe / 2)],
                z.layer("2D_Rahmen_Nahbereich", aci=4), geschlossen=True)
        if getattr(d, "mittel_aktiv", False):
            mb, mh = detail_masse(cfg)
            z.linie([(d.ce - mb / 2, d.cn - mh / 2), (d.ce + mb / 2, d.cn - mh / 2), (d.ce + mb / 2, d.cn + mh / 2), (d.ce - mb / 2, d.cn + mh / 2)],
                    z.layer("2D_Rahmen_Mittelbereich", aci=3), geschlossen=True)

    # --- Nutzung: Schraffur je Art
    alle_grenzen = []
    for kat, reg in d.regionen.items():
        if not an("Nutzung:" + kat):
            continue
        aci, rgb = kat_info(kat)
        for p in _sauber(reg, min_flaeche=1.0, min_loch=2.0):
            z.flaeche(p, "2D_Nutzung_" + umlaute(kat), rgb, aci, sauber=False)
            alle_grenzen.append(p.boundary)
    if alle_grenzen and an("Nutzung_Grenzen", False):
        gr = unary_union(alle_grenzen)
        gr = linemerge(gr) if gr.geom_type == "MultiLineString" else gr
        l_gr = z.layer("2D_Nutzung_Grenzen", aci=8)
        for ln in (gr.geoms if hasattr(gr, "geoms") else [gr]):
            if ln.geom_type == "LineString" and ln.length > 0.05:
                z.linie(ln.coords, l_gr, geschlossen=ln.is_ring)

    # --- Bruecken: oberhalb aller Nutzungsflaechen, mit ihrer Strasse / ihrem Weg / ihrer Bahn
    if an("Bruecken"):
        try:
            import ifcmap_bruecken as BR
            for e in BR.bruecken(d, cfg, lambda *a: None):
                aci_b, rgb_b = kat_info({"strasse": "Strasse", "weg": "Weg_Platz", "bahn": "Bahn"}[e["typ"]])
                if e["fahrbahn"] is not None:
                    z.flaeche(e["fahrbahn"], "2D_Bruecke_" + {"strasse": "Strasse", "weg": "Weg", "bahn": "Bahn"}[e["typ"]], rgb_b, aci_b, min_flaeche=0.5)
                if e["gehweg"] is not None:
                    z.flaeche(e["gehweg"], "2D_Bruecke_Gehweg", kat_info("Weg_Platz")[1], kat_info("Weg_Platz")[0], min_flaeche=0.3)
        except Exception:
            pass

    # --- Gebaeude (nur Schraffur)
    nah, fern = gebaeude_umrisse(d)
    for name, liste, aci_f, rgb in (("Nah", nah, 8, (110, 110, 110)), ("Fern", fern, 9, (175, 175, 175))):
        if liste and an("Gebaeude_" + name):
            z.flaeche(gebaeude_vereint(liste), "2D_Gebaeude_" + name, rgb, aci_f, min_flaeche=1.0)

    # --- ALKIS-Zusatz
    zus = getattr(d, "zusatz", {}) or {}
    if zus.get("Flurstuecke") and an("ALKIS_Flurstuecke"):                    # gemeinsame Flurstuecksgrenzen nur einmal zeichnen
        flurstuecke_linien(z, d, zus["Flurstuecke"], (150, 90, 160))
    if zus.get("Bauwerke") and an("ALKIS_Bauwerke"):
        for g, props in zus["Bauwerke"]:
            z.flaeche(g, "2D_ALKIS_Bauwerke", (140, 160, 190), 4, min_flaeche=0.3)

    # --- Berlin-Zusatzdaten (Denkmal, FNP, Laerm, OEPNV, Gewaesser)
    for key, items in (getattr(d, "extra", {}) or {}).items():
        if not an("Extra:" + key):
            continue
        _, praefix, aci0 = EXTRA_KATALOG[key]
        subs = sorted({s for s, *_ in items})
        for si, sub in enumerate(subs):
            if not an("Extra:%s:%s" % (key, sub)):
                continue
            name = "2D_%s%s" % (praefix, "_" + _zeichen(sub) if sub else "")
            if key == "laerm":
                band = int(sub.split("_")[0]) if sub[:2].isdigit() else 45
                rgb = LAERM_FARBEN.get(band, (200, 200, 200))
            elif key == "fnp":
                rgb = FNP_PALETTE[si % len(FNP_PALETTE)]
            else:
                rgb = None
            aci = {"Tram_Linien": 1, "Bus_Linien": 5, "Tram_Haltestellen": 1, "Bus_Haltestellen": 5, "Achse": 5, "Wasserflaeche": 5,
                   "Radnetz": 30, "Radfernwege": 1, "Gruene_Hauptwege": 3, "Radspuren": 40}.get(sub, _oepnv_aci(key, sub, aci0))
            teile = [(art, g, p) for s, art, g, p in items if s == sub]
            polys = [g for art, g, p in teile if art == "poly"]
            if polys:                                                            # Flaechen nur als Schraffur
                if rgb is None:
                    rgb = tuple((ezdxf.colors.DXF_DEFAULT_COLORS[aci] >> s_) & 255 for s_ in (16, 8, 0))
                z.flaeche(unary_union(polys), name, rgb, aci, min_flaeche=1.0, min_loch=2.0)
            linien = [g for art, g, p in teile if art == "line"]
            if linien:
                l = z.layer(name, aci=aci)
                gr = unary_union(linien)
                gr = linemerge(gr) if gr.geom_type == "MultiLineString" else gr
                for ln in (gr.geoms if hasattr(gr, "geoms") else [gr]):
                    if ln.geom_type == "LineString" and ln.length > 0.05:
                        z.linie(ln.simplify(0.05).coords, l, geschlossen=False)
            punkte = [(g, p) for art, g, p in teile if art == "point"]
            if punkte:
                l = z.layer(name, aci=aci)
                for g, p in punkte:
                    z.kreis(g.x, g.y, 2.0, l)
                    bez = next((str(p[k]) for k in p if k.lower() in ("haltestelle", "name", "bez", "bezeichnung", "stop_name") and p[k]), "")
                    if bez:
                        z.msp.add_text(bez, height=2.5, dxfattribs={"layer": l, "insert": (round(g.x - d.e0 + 2.5, 3), round(g.y - d.n0 + 2.5, 3))})

    # --- Sonnenbahn-Diagramm
    if getattr(cfg, "sonne", False) and an("Sonne"):
        try:
            _dxf_sonne(z, d)
        except Exception as e:
            print("  FEHLER beim Sonnenbahn-Diagramm (DXF): %s" % e)

    # --- Baeume: nur Kronen (Linien), keine Staemme
    if d.baeume and an("Baeume"):
        l_k = z.layer("2D_Baeume_Krone", (60, 140, 60))
        for (x, y, kr, ho, st, _) in d.baeume:
            z.kreis(x, y, max(kr, 1.0) / 2, l_k, rgb=(60, 140, 60))


def _oepnv_aci(key, sub, aci0):
    """Farbe der OEPNV-Untergruppen: geplant = Magenta, S-Bahn = Gruen, Tram = Rot, Bus = Blau, Nachtnetz = Grau"""
    if key != "oepnv":
        return aci0
    if "Geplant" in sub:
        return 6
    for k, a in (("SBahn", 3), ("Tram", 1), ("Bus", 5)):
        if k in sub:
            return a
    return 8 if "Nacht" in sub else aci0


def flurstuecke_linien(z, d, flurstuecke, rgb):
    """Flurstuecksgrenzen: gemeinsame Kanten nur einmal"""
    from shapely.ops import linemerge
    l = z.layer("2D_ALKIS_Flurstuecke", rgb)
    grenzen = [p.boundary for g, props in flurstuecke for p in _sauber(g, min_flaeche=0.3)]
    if grenzen:
        gr = unary_union(grenzen)
        gr = linemerge(gr) if gr.geom_type == "MultiLineString" else gr
        for ln in (gr.geoms if hasattr(gr, "geoms") else [gr]):
            if ln.geom_type == "LineString" and ln.length > 0.05:
                z.linie(ln.coords, l, rgb=rgb, geschlossen=ln.is_ring)


def schreibe_dxf_2d(pfad, d, variante=None, log=print):
    """2D-Arbeitsblatt als DXF R2010. variante None = gewoehnliche DXF, "lageplan" / "schwarzplan" = fertiger Plan (ifcmap_plaene.py).
    Flaechen sind immer Schraffuren; Linien nur fuer Grenzen, Kronen, Firste, Achsen, Sonnenbahnen und Rahmen."""
    z = Zeichner(d)
    if variante in PLAN_NAMEN:
        import ifcmap_plaene as P
        P.zeichne(z, d, variante, log)
    else:
        _dxf_standard(z, d)
    z.speichern(pfad)
    return z


def dxf_gruppe(layername):
    """Zusammengehoerige Layer ergeben eine Ebene (Krone, Rahmen, Sonne, Plan-Schichten)."""
    n = layername
    if n.endswith("_Flaeche"):
        n = n[:-len("_Flaeche")]
    for p in ("2D_Baeume_", "2D_Rahmen_"):
        if n.startswith(p):
            return p[:-1]
    if n.startswith("2D_Sonne_"):
        return "2D_Sonne"
    if n.startswith("2D_Dach_"):
        return "2D_Dach"
    return n


def _extents_setzen(doc):
    """Zeichnungsgrenzen in den Kopf schreiben (ezdxf laesst $EXTMIN/$EXTMAX sonst auf 1e+20 stehen)."""
    try:
        import ezdxf.bbox
        bb = ezdxf.bbox.extents(doc.modelspace())
        if bb.has_data:
            doc.header["$EXTMIN"] = tuple(float(v) for v in bb.extmin)
            doc.header["$EXTMAX"] = tuple(float(v) for v in bb.extmax)
            doc.header["$LIMMIN"] = (float(bb.extmin.x), float(bb.extmin.y))
            doc.header["$LIMMAX"] = (float(bb.extmax.x), float(bb.extmax.y))
    except Exception:
        pass


ANKER_LAYER = "2D_Anker_Gebiet"


def dxf_einzeln_schreiben(pfad, ordner, log=print, anker=None):
    """Zerlegt die fertige DXF in eine Datei je Ebene (gleiche lokale Koordinaten).
    anker = (x0, y0, x1, y1) in lokalen Koordinaten: in jede Datei kommt ein Rechteck auf dem Layer 2D_Anker_Gebiet, damit alle
    Dateien dieselbe Ausdehnung haben. ArchiCAD setzt eine Zeichnung sonst nach ihrer eigenen Ausdehnung - die Einzeldateien
    lagen dann gegeneinander verschoben. Das Rechteck kann nach dem Platzieren geloescht werden."""
    quelle = ezdxf.readfile(pfad)
    gruppen = {}
    for e in quelle.modelspace():
        gruppen.setdefault(dxf_gruppe(e.dxf.layer), []).append(e)
    os.makedirs(ordner, exist_ok=True)
    namen = []
    for name, ents in sorted(gruppen.items()):
        ziel = ezdxf.new(DXF_VERSION)
        ziel.header["$INSUNITS"] = 6
        ziel.header["$MEASUREMENT"] = 1
        for e in ents:
            ln = e.dxf.layer
            if ln not in ziel.layers:
                try:
                    ql = quelle.layers.get(ln)
                    nl = ziel.layers.add(ln, color=ql.dxf.color)
                    if ql.dxf.hasattr("true_color"):
                        nl.dxf.true_color = ql.dxf.true_color
                except Exception:
                    ziel.layers.add(ln)
        msp = ziel.modelspace()
        for e in ents:
            msp.add_entity(e.copy())
        if anker is not None:
            if ANKER_LAYER not in ziel.layers:
                ziel.layers.add(ANKER_LAYER, color=8)
            x0, y0, x1, y1 = anker
            msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": ANKER_LAYER})
        _extents_setzen(ziel)
        try:
            ezdxf.zoom.extents(msp)
        except Exception:
            pass
        datei = os.path.join(ordner, name + ".dxf")
        ziel.saveas(datei)
        namen.append(datei)
    log("  %d Einzeldateien in %s (jede mit Anker-Rechteck auf Layer %s, damit sie in ArchiCAD deckungsgleich sitzen)"
        % (len(namen), ordner, ANKER_LAYER))
    return namen


def pruefe_dxf(pfad, log=print):
    """Liest die geschriebene DXF wieder ein und prueft sie: Struktur (ezdxf-Audit), Version, geschlossene Rahmen, doppelte Punkte,
    Minikanten, doppelte Linien, Selbstueberschneidungen und Flaechen, die als Linie statt als Schraffur gezeichnet wurden.
    -> Anzahl der Beanstandungen"""
    from shapely.geometry import LinearRing
    doc = ezdxf.readfile(pfad)
    audit = doc.audit()
    probleme = {"Strukturfehler": len(audit.errors), "offene Ringe": 0, "doppelte Punkte": 0, "Kanten < 2 cm": 0,
                "doppelte Polylinien": 0, "Selbstueberschneidung": 0, "Flaechen als Linie": 0, "nicht R2010": 0}
    if doc.dxfversion != "AC1024":
        probleme["nicht R2010"] = 1
    gesehen = set()
    n_poly = n_hatch = n_kreis = 0
    for e in doc.modelspace():
        t = e.dxftype()
        if t == "CIRCLE":
            n_kreis += 1
        elif t == "HATCH":
            n_hatch += 1
        elif t == "LWPOLYLINE":
            n_poly += 1
            ln = e.dxf.layer
            pts = [(round(x, 3), round(y, 3)) for x, y, *_ in e.get_points()]
            if ln.startswith(("2D_Gebaeude", "2D_Nutzung_", "2D_ALKIS_Bauwerke", "2D_Bruecke", "2D_Plan_", "2D_Natur_", "2D_Strasse_", "2D_Weg_", "2D_Wasser", "2D_Bahn",
                              "2D_Schatten", "2D_Dach_Ton")) and ln != "2D_Nutzung_Grenzen":
                probleme["Flaechen als Linie"] += 1
            if ln.startswith("2D_Rahmen") and not e.closed:
                probleme["offene Ringe"] += 1
            n = len(pts)
            for i in range(n if e.closed else n - 1):
                a, b = pts[i], pts[(i + 1) % n]
                if a == b:
                    probleme["doppelte Punkte"] += 1
                elif math.hypot(a[0] - b[0], a[1] - b[1]) < 0.02:
                    probleme["Kanten < 2 cm"] += 1
            schluessel = (e.dxf.layer, tuple(sorted(pts)))
            if schluessel in gesehen:
                probleme["doppelte Polylinien"] += 1
            gesehen.add(schluessel)
            if e.closed and n >= 4 and not LinearRing(pts).is_simple:
                probleme["Selbstueberschneidung"] += 1
    summe = sum(probleme.values())
    log("  DXF-Pruefung (R2010): %d Schraffuren, %d Polylinien, %d Kreise - %s" % (
        n_hatch, n_poly, n_kreis, "keine Beanstandungen" if not summe else
        ", ".join("%s: %d" % (k, v) for k, v in probleme.items() if v)))
    return summe


# ----------------------------------------------------------------------------------------------
# Export
# ----------------------------------------------------------------------------------------------

def exportiere(d, log=print, prog=_noop, protokoll=None):
    """Schreibt alle gewuenschten Dateien. -> Liste der erzeugten Dateien"""
    cfg = d.cfg
    os.makedirs(cfg.ausgabe, exist_ok=True)
    osm_zuruecksetzen()
    zuordnen(d)
    erzeugt = []
    t_start = time.time()

    # Fussgaengernetz (Berlin) - fuer die Buergersteige im Lageplan UND fuer den Bordstein im IFC-Gelaende
    braucht_gehweg = "lageplan" in (getattr(cfg, "dxf_plaene", None) or []) or (cfg.ifc and float(getattr(cfg, "fahrbahn_absenken", 0) or 0) > 0)
    if braucht_gehweg and getattr(cfg, "buergersteige", "") == "fgn" and not getattr(d, "fgn_versucht", False) \
            and ist_berlin(cfg) and cfg.epsg == 25833 and d.regionen.get("Strasse") is not None:
        d.fgn_versucht = True
        try:
            d.fgn = fgn_laden(cfg, d, log)
        except Exception as e:
            log("  Fussgaengernetz nicht verfuegbar (%s)" % str(e)[:120])

    faces_gel, interp = {}, None
    if d.px is not None and cfg.ifc:
        prog(0.1, "Gelaende nach Nutzung aufteilen ...")
        log("Gelaende nach Nutzung aufteilen:")
        t0 = time.time()
        erlaubt = AUFTEILUNG.get(cfg.aufteilung, AUFTEILUNG["strassen"])
        reg_gel = {k: v for k, v in d.regionen.items() if ebene_an(cfg, "ifc", "Gelaende:" + k, erlaubt is None or k in erlaubt)}
        fahrbahn, sink = None, 0.0
        if cfg.ifc:
            reg_gel, fahrbahn, sink = fahrbahn_teilen(d, reg_gel, log)
        brueck_decks = []
        try:
            import ifcmap_bruecken as BR
            reg_gel, fahrbahn, brueck_decks = BR.ifc_decks_vorbereiten(d, cfg, reg_gel, fahrbahn, log)
        except Exception as e:
            log("  HINWEIS: Bruecken im IFC nicht beruecksichtigt (%s)" % str(e)[:80])
        # Bordstein nur im Detailbereich (Nah-/Mittelbereich), wo es auch Buergersteige gibt: im Fernbereich bleibt die Strasse auf Gelaendehoehe.
        # Das spart Zehntausende Wandflaechen; die Fahrbahn wird exakt am Rand des Detailbereichs getrennt (dort schliesst eine Wand).
        bereich = None if getattr(cfg, "gehweg_ueberall", False) else (getattr(d, "detail_rect", None) or getattr(d, "nah_rect", None))
        if fahrbahn is not None and bereich is not None and "Strasse" in reg_gel:
            fern_fb = fahrbahn.difference(bereich)
            nah_fb = fahrbahn.intersection(bereich)
            if not fern_fb.is_empty:
                log("  Bordstein nur im %s (Fahrbahn %.0f von %.0f m2); im Fernbereich bleibt die Strasse auf Gelaendehoehe"
                    % ("Nah- und Mittelbereich" if getattr(d, "mittel_aktiv", False) else "Nahbereich", nah_fb.area, fahrbahn.area))
                reg_gel = dict(reg_gel)
                if nah_fb.is_empty:
                    fahrbahn = None
                else:
                    fahrbahn = unary_union(_polys(nah_fb))
                reg_gel["Strasse"] = fahrbahn if fahrbahn is not None else fern_fb
                if fahrbahn is not None:
                    reg_gel["_Strasse_fern"] = unary_union(_polys(fern_fb))
        log("  Gelaende wird aufgeteilt nach: %s" % (", ".join(reg_gel) if reg_gel else "(nicht aufgeteilt)"))
        alle = erlaubt is None and not (cfg.ebenen or {}).get("ifc")
        faces_gel, tin = gelaende_aufteilen(d.px, d.py, d.pz, reg_gel, log, rest_name=None if alle else "Gelaende",
                                            loecher=getattr(d, "loecher", None))
        if fahrbahn is not None and faces_gel.get("Strasse"):
            try:
                tief, wand, rand = bordstein_flaechen(faces_gel["Strasse"], fahrbahn, d.rect, sink, log)
                faces_gel["Strasse"] = tief
                if faces_gel.get("Gehweg") and len(rand[0]):
                    try:
                        faces_gel["Gehweg"], naht = gehweg_glaetten(faces_gel["Gehweg"], rand, d._strasse_gesamt, fahrbahn, d.rect, log)
                        wand = wand + naht
                    except Exception as e:
                        log("  HINWEIS: Gehweg konnte nicht geglaettet werden (%s)" % e)
                if wand:
                    faces_gel["Bordstein"] = wand
            except Exception as e:
                log("  FEHLER beim Bordstein (die Fahrbahn bleibt auf Gelaendehoehe): %s" % e)
        if "_Strasse_fern" in faces_gel:                       # Fern-Fahrbahn (nicht abgesenkt) wieder zur Strasse
            faces_gel["Strasse"] = list(faces_gel.get("Strasse", [])) + faces_gel.pop("_Strasse_fern")
        lin = LinearNDInterpolator(tin, d.pz)
        interp = lambda x, y: lin(x, y)
        if brueck_decks:
            try:
                import ifcmap_bruecken as BR
                for kat, fl in BR.ifc_decks_flaechen(d, brueck_decks, interp, log).items():
                    faces_gel.setdefault(kat, [])
                    faces_gel[kat] = list(faces_gel[kat]) + fl
            except Exception as e:
                log("  FEHLER bei den Bruecken im IFC (das Gelaende bleibt wie es ist): %s" % e)
        log("  Teilflaechen je Kategorie: " + ", ".join("%s %d" % (k, len(v)) for k, v in faces_gel.items())
            + " (%.0f s)" % (time.time() - t0))

    ZE = []                                                      # Zeiten der Ausgabeschritte (kommen am Ende ins Protokoll)
    if cfg.ifc:
        t_ifc = time.time()
        prog(0.4, "IFC schreiben ...")
        log("IFC schreiben:")
        try:
            import ifcopenshell  # noqa
        except ImportError:
            log("  FEHLER: ifcopenshell ist nicht installiert - es gibt keine IFC-Datei. Fuer sehr neue Python-Versionen "
                "gibt es oft noch kein Paket: bitte Python 3.12 installieren und IFCmap.bat erneut ausfuehren "
                "(pip install ifcopenshell).")
        else:
            if cfg.test:
                varianten = [("test_variante_A_IfcGeographicElement.ifc", "geographic"), ("test_variante_B_IfcSite.ifc", "site")]
            else:
                varianten = [("ifcmap.ifc", cfg.gelaende_typ)]
            for name, typ in varianten:
                pfad = os.path.join(cfg.ausgabe, name)
                g, gl, b = schreibe_ifc(pfad, d, faces_gel, interp, typ, log)
                log("  %s: Gebaeude %d, Gelaendeflaechen %d, Baeume %d  (%.1f MB)" % (name, g, gl, b, os.path.getsize(pfad) / 1e6))
                erzeugt.append(pfad)
            ZE.append(("IFC schreiben", time.time() - t_ifc))
    if cfg.dxf2d:
        t_2d = time.time()
        prog(0.8, "2D-DXF schreiben ...")
        pfad = os.path.join(cfg.ausgabe, "ifcmap_2d.dxf" if not cfg.test else "test_ifcmap_2d.dxf")
        schreibe_dxf_2d(pfad, d)
        try:
            pruefe_dxf(pfad, log)
        except Exception as e:
            log("  (DXF-Pruefung nicht moeglich: %s)" % e)
        log("  %s (%.1f MB)" % (os.path.basename(pfad), os.path.getsize(pfad) / 1e6))
        try:
            import collections
            zaehler = collections.Counter(e.dxf.layer for e in ezdxf.readfile(pfad).modelspace())
            log("  DXF-Layer in der Datei (%d): %s" % (len(zaehler), ", ".join("%s (%d)" % kv for kv in sorted(zaehler.items()))))
        except Exception:
            pass
        modus = getattr(cfg, "dxf_modus", "eine")
        if modus in ("beides", "einzeln"):
            try:
                erzeugt += dxf_einzeln_schreiben(
                    pfad, os.path.join(cfg.ausgabe, "dxf_ebenen"), log,
                    anker=(d.xmin - d.e0, d.ymin - d.n0, d.xmax - d.e0, d.ymax - d.n0))
            except Exception as e:
                log("  FEHLER beim Zerlegen der DXF in Einzeldateien: %s" % e)
                modus = "beides"
        if modus == "einzeln":
            os.remove(pfad)
        else:
            erzeugt.append(pfad)
        ZE.append(("Arbeits-DXF (ifcmap_2d.dxf)", time.time() - t_2d))
    for pl in [x for x in (getattr(cfg, "dxf_plaene", None) or []) if x in PLAN_NAMEN]:
        prog(0.88, "%s schreiben ..." % PLAN_NAMEN[pl])
        t_pl = time.time()
        pfad = os.path.join(cfg.ausgabe, ("test_" if cfg.test else "") + "ifcmap_%s.dxf" % pl)
        try:
            schreibe_dxf_2d(pfad, d, variante=pl, log=log)
            try:
                pruefe_dxf(pfad, log)
            except Exception as e:
                log("  (DXF-Pruefung nicht moeglich: %s)" % e)
            log("  %s: %s (%.1f MB)" % (PLAN_NAMEN[pl], os.path.basename(pfad), os.path.getsize(pfad) / 1e6))
            for h in (getattr(d, "plan_hinweise", None) or []) if pl == "lageplan" else []:
                log("  HINWEIS: " + h)
            erzeugt.append(pfad)
        except Exception as e:
            log("  FEHLER beim %s: %s" % (PLAN_NAMEN[pl], e))
        ZE.append((PLAN_NAMEN[pl], time.time() - t_pl))
    if getattr(cfg, "zusatzplaene_aktiv", False) and getattr(cfg, "zusatzplaene", None):
        prog(0.95, "Zusatzplaene schreiben ...")
        t_zu = time.time()
        try:
            import ifcmap_zusatz as ZU
            erzeugt.extend(ZU.schreibe_zusatzplaene(d, cfg.zusatzplaene, cfg.ausgabe, log, praefix="test_" if cfg.test else ""))
        except Exception as e:
            log("  FEHLER bei den Zusatzplaenen: %s" % e)
        ZE.append(("Zusatzplaene", time.time() - t_zu))
    if cfg.dxf2d and (getattr(cfg, "wms_karten", None) or getattr(cfg, "wms_eigene", "")):
        prog(0.96, "Kartenbilder laden ...")
        t_wm = time.time()
        try:
            import ifcmap_wms as WM
            erzeugt.extend(WM.schreibe_wms(d, cfg, cfg.ausgabe, log, praefix="test_" if cfg.test else ""))
        except Exception as e:
            log("  FEHLER bei den Kartenbildern: %s" % e)
        ZE.append(("Kartenbilder", time.time() - t_wm))
    if cfg.xyz and d.px is not None:
        pfad = os.path.join(cfg.ausgabe, "gelaende_punkte.xyz")
        o = np.lexsort((d.px, d.py))
        with open(pfad, "w", newline="\n") as fh:
            fh.write("\n".join("%.3f %.3f %.3f" % (x - d.e0, y - d.n0, z) for x, y, z in zip(d.px[o], d.py[o], d.pz[o])) + "\n")
        log("  gelaende_punkte.xyz")
        erzeugt.append(pfad)
    if ZE:
        log("Zeiten der Ausgabe: " + "; ".join("%s %.0f s" % (n, t) for n, t in ZE))
    log("\nLokaler Nullpunkt: E0 = %.0f, N0 = %.0f, Z0 = %.0f m  (lokal = Ost-E0 / Nord-N0 / Hoehe-Z0; EPSG:%d, NHN)"
        % (d.e0, d.n0, d.z0, cfg.epsg))
    log("Fertig in %.0f s." % (time.time() - t_start))
    prog(1.0, "Fertig")
    if protokoll:
        pfad = os.path.join(cfg.ausgabe, "protokoll.txt")
        with open(pfad, "w", encoding="utf-8") as fh:
            fh.write("\n".join(protokoll) + "\n")
        erzeugt.append(pfad)
    return erzeugt
