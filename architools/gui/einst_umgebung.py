"""Einstellungen für Archicad-IFC, Lageplan, Schwarzplan und Informations-DWG (Rechenkern IFCmap)."""
from nicegui import ui

from .stil import (AKZENT, GRAU, INK, OCKER, SALBEI, SCHIEFER, TERRA, ausgrauen, feld_pfad, hinweis, karte)

# Auswahllisten: intern -> Beschriftung
QUELLEN = {"auto": "Automatisch (amtlich, sonst OpenStreetMap)", "osm": "Nur OpenStreetMap",
           "dateien": "Nur eigene Dateien (GeoJSON)"}
LAENDER = {"auto": "Automatisch (nach dem Mittelpunkt)", "berlin": "Berlin", "brandenburg": "Brandenburg (neu)",
           "nrw": "Nordrhein-Westfalen (neu, ungetestet)", "bayern": "Bayern (neu, ungetestet)",
           "hamburg": "Hamburg (neu, ungetestet)", "keins": "Anderes Land: nur eigene Dateien"}
KBS = {25833: "ETRS89 / UTM 33N (EPSG:25833) – Berlin, Brandenburg, Sachsen, MV",
       25832: "ETRS89 / UTM 32N (EPSG:25832) – Westen und Süden",
       25831: "ETRS89 / UTM 31N (EPSG:25831)", 25834: "ETRS89 / UTM 34N (EPSG:25834)"}
AUFTEILUNG = {"strassen": "nur Straßen und Wege", "verkehr_wasser": "Straßen, Wege, Bahn und Gewässer",
              "alle": "allen Nutzungsarten", "keine": "nicht aufteilen"}
FERN = {"bloecke": "Blöcke bis Traufe (LoD1, spart Speicher)", "lod2": "wie Nahbereich (LoD2, sehr groß)", "keine": "weglassen"}
EXTRA = [("denkmal", "Denkmalkarte (Baudenkmale, Gartendenkmale, Bodendenkmale, Denkmalbereiche)"),
         ("fnp", "Flächennutzungsplan (FNP 2025)"),
         ("laerm", "Lärmkarte 2022 (Bänder in 5-dB-Stufen)"),
         ("oepnv", "ÖPNV: Vorrangnetz (Tram, Bus, S-Bahn, geplante Strecken) und Haltestellen"),
         ("gewaesser", "Gewässernetz (Flächen und Achsen)"),
         ("radverkehr", "Radverkehrsnetz als eigene Ebene (zusätzlich zu den Wegeflächen) – neu, ungetestet")]
LAERM_ARTEN = {"gesamtlaerm": "Gesamtlärm (alle Quellen)", "strasse": "Straßenverkehr", "ubahn": "Straßen-/U-Bahnverkehr",
               "industrie": "Industrie und Gewerbe", "flug": "Flugverkehr"}
LAERM_WERTE = {"L_DEN": "Tag-Abend-Nacht (L_DEN)", "L_N": "Nacht (L_N)"}
SONNE_MODI = {"wende": "3 Bahnen: 21. Juni, 21. März/Sept., 21. Dezember", "monate": "12 Bahnen: jeweils der 21. jedes Monats",
              "monat": "1 Bahn: der 21. des gewählten Monats"}
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
BUERGERSTEIGE = {"fgn": "Fußgängernetz Berlin (amtlich)", "naeherung": "Näherung aus der Straßenbreite (überall)",
                 "keine": "keine Bürgersteige"}
BAUMSCHATTEN_BEREICH = {"nah": "Nahbereich samt Übergangszone", "alle": "überall (wo Bäume geladen sind)"}
SCHATTEN_MODI = {"aus": "aus", "standard": "Standard: 6. Juli, 16:17 Uhr", "eigen": "eigenes Datum und Uhrzeit"}
MARKANT_QUELLEN = {"auto": "Automatisch: OpenStreetMap → LoD2 (Empfehlung)",
                   "dom_zuerst": "DOM zuerst: DOM → OpenStreetMap → LoD2 (experimentell)",
                   "dom": "Nur DOM (zum Testen)", "osm": "Nur OpenStreetMap (zum Testen)", "lod2": "Nur LoD2 (zum Testen)"}
MARKANT_GLATT = {"normal": "Normal (Empfehlung)", "fein": "Fein – näher am DOM, rauere Dächer",
                 "stark": "Stark – glatte Dächer, weniger Details"}
DXF_MODI = {"eine": "Eine DXF-Datei", "beides": "Eine DXF + jede Ebene als eigene Datei",
            "einzeln": "Nur einzelne Dateien (eine je Ebene)"}
GELAENDE_TYPEN = {"geographic": "IfcGeographicElement (Variante A)", "site": "IfcSite (Variante B)"}
# toleranz, toleranz_fern, uebergang, fern_raster
GENAUIGKEIT = {"Schnell": (0.3, 2.5, 40, 10), "Standard": (0.15, 1.5, 60, 6), "Fein": (0.05, 0.5, 80, 2)}


def _zahl(label, u, key, breite="w-28", **kw):
    return ui.number(label, **kw).bind_value(u, key).classes(breite)


def _wahl(label, opts, u, key, breite="w-full"):
    return ui.select(opts, label=label).bind_value(u, key).classes(breite)


def _haken(text, u, key, **kw):
    return ui.checkbox(text, **kw).bind_value(u, key)


def _wenn_aus(p, *schluessel):
    """Sichtbarkeit: mindestens eine der Ausgaben ist gewählt."""
    return lambda: any(p["ausgaben"].get(k) for k in schluessel)


def seiten(p):
    """Baut die Einstellungs-Karten; sichtbar sind nur die Karten zu den gewählten Ausgaben."""
    u = p["umgebung"]
    ausg = p["ausgaben"]
    regeln = []                       # (Element, Funktion) – Sichtbarkeit nach Auswahl

    def abschnitt(wann):
        col = ui.column().classes("w-full gap-3")
        regeln.append((col, wann))
        return col

    with ui.column().classes("w-full gap-3") as wurzel:
        # -------------------------------------------------- Gebiet und Daten (immer, wenn Umgebung gewählt)
        with abschnitt(_wenn_aus(p, "ifc", "lageplan", "schwarzplan", "info_dwg")):
            with karte("Koordinatensystem", AKZENT, offen=False) as k_koord:
                hinweis("Größe von Gebiet, Nah- und Mittelbereich stellst du auf der Seite „Gebiet“ ein (dort siehst du sie in der Karte).")
                _wahl("Koordinatensystem", KBS, u, "epsg")
            with karte("Daten", SCHIEFER):
                _wahl("Bundesland", LAENDER, u, "land")
                _wahl("Quelle für Nutzung und Bäume", QUELLEN, u, "quelle")
                hinweis("Immer die beste Quelle: amtliche Daten, wo es sie gibt (Berlin, Brandenburg …), sonst OpenStreetMap.")
                _haken("Gelände-Kacheln (DGM1) automatisch laden", u, "online_dgm")
                _haken("Gebäude-Kacheln (LoD2) automatisch laden", u, "online_lod2")
                _haken("Lücken im LoD2 füllen (OpenStreetMap-Dachformen, ALKIS-Grundrisse; ohne LoD2 alles aus OSM)", u, "lod2_luecken")
                hinweis("Weitere amtliche Quellen (nur Berlin, neu und ungetestet). Reihenfolge immer: amtlich zuerst (ALKIS, LoD2, Baumkataster, Umweltatlas), "
                        "OpenStreetMap nur für das, was es amtlich nicht gibt.")
                _haken("Gebäude ohne LoD2: Höhe und Dachform aus den Umweltatlas-Gebäudehöhen (vor OpenStreetMap; wirkt zusammen mit „Lücken im LoD2 füllen“)", u, "ua_gebaeudehoehen")
                _haken("Bäume: Vegetationsraster 1 m aus dem Umweltatlas (Baumhöhen + fehlende Bäume; einmaliger Download, ca. 785 MB)", u, "ua_vegetationsraster")
                _haken("Bäume ohne Höhe: billiger Ersatz mit Blockmittelwerten des Umweltatlas (kein großer Download)", u, "ua_vegetationshoehen")
                _haken("Wege: Radverkehrsnetz Berlin als zusätzliche Quelle für Wegeflächen (3D, DXF, Pläne)", u, "rad_wege")
                _haken("OpenStreetMap-Bäume ergänzen, die es amtlich nicht gibt", u, "osm_ergaenzen")
                _haken("Ohne Geländemodell: Copernicus GLO-30 (30 m) als Notbehelf laden", u, "dgm_notfall")
                with ui.expansion("Eigene Dateien", value=False).classes("w-full"):
                    hinweis("Gelände: xyz / asc / tif · Gebäude: CityGML (xml, gml, zip) · Nutzung und Bäume: GeoJSON")
                    feld_pfad("Gelände (DGM)", u, "dgm", mehrere=True, typen=("Gelände (*.xyz;*.asc;*.tif;*.tiff;*.zip;*.txt)",))
                    feld_pfad("Gebäude (LoD2, CityGML)", u, "lod2", mehrere=True, typen=("CityGML (*.xml;*.gml;*.zip)",))
                    feld_pfad("Oberflächenmodell (DOM)", u, "dom", mehrere=True, typen=("DOM (*.xyz;*.asc;*.tif;*.zip)",))
                    feld_pfad("Nutzung (GeoJSON)", u, "nutzung_dateien", mehrere=True, typen=("GeoJSON (*.geojson;*.json)",))
                    feld_pfad("Bäume (GeoJSON)", u, "baum_dateien", mehrere=True, typen=("GeoJSON (*.geojson;*.json)",))

        # -------------------------------------------------- IFC
        with abschnitt(_wenn_aus(p, "ifc")):
            with karte("Archicad-IFC – 3D-Modell", AKZENT):
                _wahl("Gelände teilen nach", AUFTEILUNG, u, "aufteilung")
                _wahl("Gebäude im Fernbereich", FERN, u, "fern_gebaeude")
                fz = _haken("Fernbereich je Feld (150 m) zu EINEM Element zusammenfassen – viel schneller und kleiner in Archicad",
                            u, "fern_zusammenfassen")
                hinweis("Ohne Haken bleibt jedes Gebäude ein eigenes Element (auswählbar, aber Archicad braucht für Tausende "
                        "Elemente lange).")
                _haken("Farben und Materialien (ruhige Palette: Fahrbahn graphit, Gebäude fast weiß …)", u, "farben")
                with ui.row().classes("gap-2 items-center"):
                    ui.label("Bordstein: Fahrbahn tiefer als Gehweg und Umgebung um").classes("text-body2")
                    cm = ui.number(value=round(float(u.get("fahrbahn_absenken") or 0) * 100, 1), min=0, max=30, step=1) \
                        .classes("w-20")
                    cm.on_value_change(lambda e: u.__setitem__("fahrbahn_absenken", float(e.value or 0) / 100.0))
                    ui.label("cm (0 = aus)").classes("text-body2")
                hinweis("Das Gelände bleibt auf DGM-Höhe (dort stehen auch die Gebäude); nur die Fahrbahn sinkt.")
                _haken("Brücken im IFC: Straße/Gehweg nur auf Brücken, die im LoD2 vorhanden sind (sonst weglassen)", u, "bruecken_ifc")
                _wahl("Gelände in der IFC als", GELAENDE_TYPEN, u, "gelaende_typ")
                gl = _haken("Geschosslinien: waagerechte Linien an den Wänden der Gebäude im Nahbereich (optional)", u, "geschosslinien")
                with ui.column().classes("w-full gap-1") as gl_in:
                    _wahl("Geschosszahl", {"auto": "aus den Daten, sonst aus der Traufhöhe geschätzt", "daten": "nur Gebäude mit echter Geschosszahl"},
                          u, "geschosslinien_quelle", "w-96")
                    with ui.row().classes("gap-2 items-center"):
                        ui.label("nur Gebäude bis").classes("text-body2")
                        _zahl("", u, "geschosslinien_radius", min=20, step=10, breite="w-20")
                        ui.label("m um den Mittelpunkt").classes("text-body2")
                    hinweis("Keine Fassade: Es gibt weder Fenster noch Türen. Die Geschosszahl kommt aus LoD2, ALKIS (Berlin) oder OpenStreetMap; "
                            "fehlt sie, wird sie aus der Traufhöhe geteilt durch 3,1 m geschätzt (steht je Gebäude als Eigenschaft in der IFC). "
                            "Die Linien teilen die Traufhöhe gleichmäßig – echte Geschosshöhen sind nicht bekannt.")
                ausgrauen(gl_in, gl)
                fm = _haken("Fenstermuster: Fenster und Türen als flache Rechtecke an den Wänden (optional, MUSTER – nicht gemessen)", u, "fenstermuster")
                with ui.column().classes("w-full gap-1") as fm_in:
                    with ui.row().classes("gap-2 items-center"):
                        ui.label("nur Gebäude bis").classes("text-body2")
                        _zahl("", u, "fenstermuster_radius", min=20, step=10, breite="w-20")
                        ui.label("m um den Mittelpunkt").classes("text-body2")
                    hinweis("Ein Muster, keine Fassade: LoD2 enthält keine Fenster und Türen, und es gibt keine offene Quelle dafür. Das Muster richtet sich nur "
                            "nach Wandbreite und -höhe (Achse ca. 3 m, Fenster 1,2 × 1,4 m, Tür im Erdgeschoss). Die echte Lage der Fenster stimmt damit nicht. "
                            "Jedes Element trägt den Vermerk „MUSTER“. Nicht im Schnitt.")
                ausgrauen(fm_in, fm)
                u.setdefault("zusatz", {})
                from .. import zusatz as _zusatz
                _zusatz.rufe("gui_umgebung", ui, u)
            with karte("Markante Gebäude – experimentell", OCKER, offen=False) as k_markant:
                ui.label("EXPERIMENTELL: Diese Funktion klappt noch nicht immer – Gebäude können fehlen oder falsche Formen haben.") \
                    .classes("text-caption").style(f"color:{OCKER}")
                mk = _haken("Markante Gebäude besonders detailliert darstellen", u, "markant")
                with ui.column().classes("w-full gap-0") as mk_in:
                    ui.label("Als markant gilt ein Gebäude, wenn mindestens eines davon zutrifft:").classes("text-body2")
                    _haken("OpenStreetMap-Merkmal (Kirche, Turm, Theater, Museum, Planetarium, Bahnhof …)", u, "markant_osm")
                    _haken("Denkmalkarte (Berlin amtlich, sonst OpenStreetMap-Denkmal)", u, "markant_denkmal")
                    _haken("ungewöhnlich komplexe Dachform im LoD2 (viele oder steile Dachflächen)", u, "markant_dach")
                    ui.input("… oder steht in deiner Liste (Name: Breite, Länge; …)").bind_value(u, "markant_liste").classes("w-full")
                    _wahl("Form aus", MARKANT_QUELLEN, u, "markant_quelle")
                    _wahl("Dachhaut glätten", MARKANT_GLATT, u, "markant_glaettung")
                    with ui.row().classes("gap-2 items-center"):
                        ui.label("höchstens").classes("text-body2")
                        _zahl("", u, "markant_max", min=1, step=5, breite="w-20")
                        ui.label("markante Gebäude").classes("text-body2")
                    _haken("auch im Fernbereich (Standard: nur Nahbereich)", u, "markant_fern")
                    hinweis("Reihenfolge je Gebäude: DOM → OpenStreetMap in 3D → volles LoD2. Das DOM bildet Lüftungsanlagen und "
                            "Dachsprünge teils falsch ab – deshalb ist es nicht Standard.")
                ausgrauen(mk_in, mk)

        # -------------------------------------------------- Lageplan / Schwarzplan
        with abschnitt(_wenn_aus(p, "lageplan", "schwarzplan", "ifc")):
            with karte("Bürgersteige", SALBEI):
                _wahl("Darstellung (Lageplan und IFC-Gelände)", BUERGERSTEIGE, u, "buergersteige")
                _haken("Breite nach Straßenbreite: 2,0 / 3,0 / 4,0 m (Berliner Richtwerte)", u, "gehweg_auto")
                with ui.row().classes("gap-2 items-center"):
                    ui.label("oder feste Breite").classes("text-body2")
                    _zahl("", u, "gehweg_breite", min=0.5, step=0.5, breite="w-20")
                    ui.label("m").classes("text-body2")
                _haken("Bürgersteige auch im Fernbereich (Standard: nur im Nahbereich)", u, "gehweg_ueberall")
        with abschnitt(_wenn_aus(p, "lageplan", "schwarzplan")):
            with karte("Lageplan und Schwarzplan", SCHIEFER):
                with ui.column().classes("w-full gap-0") as lp:
                    ui.label("Lageplan").classes("text-subtitle2")
                    _haken("Baumkronen als Kreise", u, "lageplan_baeume")
                    _haken("Nahbereich: Dachlinien (Firste, Grate, Kehlen)", u, "dach_linien")
                    _haken("Nahbereich: Dachflächen nach Sonnenstand schattieren (7 Grautöne)", u, "dach_schattierung")
                _wahl("Schatten in den Plänen", SCHATTEN_MODI, u, "schatten")
                with ui.column().classes("w-full gap-0") as sch:
                    with ui.row().classes("gap-2"):
                        ui.input("Datum (Tag.Monat)").bind_value(u, "schatten_datum").classes("w-36")
                        ui.input("Uhrzeit (MEZ/MESZ)").bind_value(u, "schatten_zeit").classes("w-36") \
                            .bind_enabled_from(u, "schatten", backward=lambda s: s == "eigen")
                    with ui.row().classes("gap-3"):
                        _haken("im Lageplan", u, "schatten_lageplan")
                        _haken("im Schwarzplan", u, "schatten_schwarzplan")
                    _haken("Bäume werfen Schatten", u, "schatten_baeume")
                    with ui.column().classes("w-full gap-0") as bs:
                        _wahl("wo", BAUMSCHATTEN_BEREICH, u, "schatten_baeume_bereich", "w-72")
                        with ui.row().classes("gap-3"):
                            _haken("Baumschatten im Lageplan", u, "baumschatten_lageplan")
                            _haken("Baumschatten im Schwarzplan", u, "baumschatten_schwarzplan")
                    _bsw = ui.checkbox().bind_value_from(u, "schatten_baeume")
                    _bsw.set_visibility(False)
                    ausgrauen(bs, _bsw)
                    sch.bind_visibility_from(u, "schatten", backward=lambda s: s != "aus")
                hinweis("Jeder Plan ist eine eigene DXF-Datei im selben Nullpunkt wie die IFC. In jedem Plan lässt sich der "
                        "Schatten über die Ebene „Schatten“ abwählen.")
                lp_regel = _wenn_aus(p, "lageplan")
                regeln.append((lp, lp_regel))

        # -------------------------------------------------- Lageplan-Beschriftung
        with abschnitt(_wenn_aus(p, "lageplan")):
            with karte("Lageplan-Beschriftung", SCHIEFER, offen=False):
                bt = _haken("Lageplan beschriften (jede Art auf eigener Ebene, Schrift 2,5 mm auf dem Papier)", u, "lp_text")
                with ui.column().classes("w-full gap-0") as bt_in:
                    _haken("Flurstücksnummern (ALKIS, nur Berlin – braucht den Haken „ALKIS-Zusatzdaten“ bei Informations-DWG/Daten)", u, "lp_text_flurstuecke")
                    _haken("Hausnummern (OpenStreetMap)", u, "lp_text_hausnummern")
                    _haken("Straßennamen (OpenStreetMap)", u, "lp_text_strassen")
                    _haken("Gebäudehöhen: Traufe und First (LoD2)", u, "lp_text_hoehen")
                    _wahl("Höhen angeben", {"gelaende": "über Gelände (Tr = Traufe, Fi = First)", "nhn": "in m ü. NHN"},
                          u, "lp_text_hoehen_art", "w-80")
                    with ui.row().classes("gap-2 items-center"):
                        ui.label("Maßstab für die Schrifthöhe 1:").classes("text-body2")
                        _zahl("", u, "lp_text_massstab", min=50, step=50, breite="w-24")
                    hinweis("Wo OpenStreetMap oder ALKIS nichts liefern, bleibt der Text weg (steht im Protokoll). Noch nicht gegen die "
                            "Live-Dienste getestet.")
                ausgrauen(bt_in, bt)

        # -------------------------------------------------- Informations-DWG
        with abschnitt(_wenn_aus(p, "info_dwg")):
            with karte("Informations-DWG – alle Ebenen in einer Zeichnung", INK, offen=True):
                _wahl("Ausgabe", DXF_MODI, u, "dxf_modus")
                hinweis("Einzeldateien liegen im Unterordner dxf_ebenen und haben alle denselben Nullpunkt.")
                _haken("Berlin: ALKIS-Flurstücke, -Gebäude und -Bauwerke einbeziehen", u, "alkis_zusatz")
            with karte("Zusatzdaten (nur Informations-DWG)", TERRA, offen=False):
                for key, text in EXTRA:
                    def umschalten(e, key=key):
                        lst = u.setdefault("extra", [])
                        if e.value and key not in lst:
                            lst.append(key)
                        elif not e.value and key in lst:
                            lst.remove(key)
                    ui.checkbox(text, value=key in (u.get("extra") or []), on_change=umschalten)
                with ui.row().classes("gap-2"):
                    ui.select(LAERM_ARTEN, label="Lärmkarte: Art").bind_value(u, "laerm_art").classes("w-64")
                    ui.select(LAERM_WERTE, label="Wert").bind_value(u, "laerm_wert").classes("w-56")
                hinweis("Quelle automatisch: amtlich (Berlin), sonst OpenStreetMap – ÖPNV, Gewässer und Denkmäler gibt es so überall.")
            with karte("Kartenbilder zum Daruntermalen (nur Informations-DWG, optional)", TERRA, offen=False):
                from .. import projekt as _P
                _P.kern()
                import ifcmap_wms as _WM
                for key, (text, *_r) in _WM.WMS_KATALOG.items():
                    def wms_umschalten(e, key=key):
                        lst = u.setdefault("wms_karten", [])
                        if e.value and key not in lst:
                            lst.append(key)
                        elif not e.value and key in lst:
                            lst.remove(key)
                    ui.checkbox(text + " – ungetestet", value=key in (u.get("wms_karten") or []), on_change=wms_umschalten)
                with ui.row().classes("gap-2 items-center"):
                    ui.label("Auflösung:").classes("text-body2")
                    _zahl("", u, "wms_aufloesung", min=0.05, max=5, step=0.05, breite="w-20")
                    ui.label("m je Pixel (höchstens 4096 Pixel Kantenlänge)").classes("text-body2")
                ui.textarea("Weitere WMS-Dienste (je Zeile: Name | Adresse | Ebene1,Ebene2 – Ebenen optional)") \
                    .bind_value(u, "wms_eigene").classes("w-full").props("autogrow outlined dense")
                hinweis("Das sind Rasterbilder (kein Vektor): je Karte eine eigene DXF mit eingebettetem Bild samt PNG und World-File, im "
                        "selben Nullpunkt. Nur Berlin; weitere Umweltatlas-Themenpläne (Klima, Grünvolumen …) lassen sich über "
                        "„Weitere WMS-Dienste“ mit der Adresse https://gdi.berlin.de/services/wms/<Dienstname> ergänzen. "
                        "Abruf noch nicht gegen die Live-Dienste getestet. Karten liegen als Bild vor – bitte Quelle und Lizenz "
                        "(Geoportal Berlin) beim Veröffentlichen angeben.")

        with abschnitt(_wenn_aus(p, "info_dwg", "lageplan", "schwarzplan")):
            from . import zusatzplan
            zusatzplan.liste_karte(p)

        # -------------------------------------------------- Erweitert: selten gebrauchte Karten wandern hierher
        with abschnitt(_wenn_aus(p, "ifc", "lageplan", "schwarzplan", "info_dwg")):
            ui.label("Erweitert – selten gebraucht").classes("text-subtitle2 q-mt-md").style(f"color:{GRAU}").props("id=erweitert-anker")
            erweitert = ui.column().classes("w-full gap-3")
        k_koord.move(erweitert)
        k_markant.move(erweitert)
        regeln.append((k_markant, _wenn_aus(p, "ifc")))

        # -------------------------------------------------- Sonnenbank-Flavour (Sonnenbahn)
        with abschnitt(_wenn_aus(p, "ifc", "lageplan", "schwarzplan", "info_dwg")):
            with karte("Sonnenbank-Flavour", OCKER, offen=False):
                sn = _haken("Sonnenbahn-Diagramm miterzeugen (IFC und DXF)", u, "sonne")
                with ui.column().classes("w-full gap-1") as sn_in:
                    _wahl("Bahnen", SONNE_MODI, u, "sonne_modus")
                    mon = ui.select({i + 1: m for i, m in enumerate(MONATE)}, label="Monat (für „1 Bahn“)") \
                        .classes("w-52")
                    mon.value = int(u.get("sonne_monat") or 6) if int(u.get("sonne_monat") or 0) else 6
                    mon.on_value_change(lambda e: u.__setitem__("sonne_monat", int(e.value or 0)))
                    mon.bind_enabled_from(u, "sonne_modus", backward=lambda m: m == "monat")
                    _zahl("Radius (m, 0 = automatisch)", u, "sonne_radius", "w-56", min=0, step=10)
                    _haken("Zeitpunkt des Schattens im Diagramm markieren", u, "sonne_marke")
                    hinweis("Leer/0 = automatisch (40 % des Nahbereichs). Zeit MEZ/MESZ, Nord um die Meridiankonvergenz korrigiert.")
                ausgrauen(sn_in, sn)

        # -------------------------------------------------- Genauigkeit und Erweitertes
        with abschnitt(_wenn_aus(p, "ifc", "info_dwg")):
            with karte("Genauigkeit des Geländes", SCHIEFER, offen=False):
                aktuell = next((n for n, v in GENAUIGKEIT.items()
                                if (float(u.get("toleranz") or 0), float(u.get("toleranz_fern") or 0),
                                    float(u.get("uebergang") or 0), float(u.get("fern_raster") or 0)) == tuple(map(float, v))), "Eigene Werte")
                vor = ui.select(list(GENAUIGKEIT) + ["Eigene Werte"], label="Voreinstellung", value=aktuell).classes("w-52")
                felder = {}
                with ui.row().classes("gap-2"):
                    for key, text in (("toleranz", "Toleranz Nah (m)"), ("toleranz_fern", "Toleranz Fern (m)"),
                                      ("uebergang", "Übergang (m)"), ("fern_raster", "Raster Fern (m)")):
                        felder[key] = _zahl(text, u, key, "w-36", min=0, step=0.05)

                def setze(e):
                    if e.value in GENAUIGKEIT:
                        for (key, _), v in zip(felder.items(), GENAUIGKEIT[e.value]):
                            u[key] = v
                            felder[key].value = v
                vor.on_value_change(setze)
                hinweis("Schnell = kleine, rasch geschriebene IFC · Standard = guter Kompromiss · Fein = sehr genau (groß, langsam). "
                        "Toleranz = größte erlaubte Abweichung des Netzes vom DGM.")
        with abschnitt(_wenn_aus(p, "ifc", "lageplan", "schwarzplan", "info_dwg")):
            with karte("Weitere Optionen", GRAU, offen=False):
                _haken("Bäume nur im Nahbereich laden und ausgeben", u, "baeume_nur_nah")
                _haken("2D-Pläne: in ALKIS fehlende Gebäude aus LoD2/OpenStreetMap ergänzen", u, "grundrisse_abgleich")
                ui.input("KBS der GeoJSON-Dateien (EPSG, leer = wie Projekt)").bind_value(u, "eingabe_crs").classes("w-72")
                nullp = ui.checkbox("Nullpunkt von Hand festlegen (damit neue Teile zu früheren Archicad-Dateien passen)",
                                    value=bool(u.get("e0n0")))
                with ui.row().classes("gap-2") as nz:
                    e0 = ui.number("E0", value=(u.get("e0n0") or [None, None])[0]).classes("w-32")
                    n0 = ui.number("N0", value=(u.get("e0n0") or [None, None])[1]).classes("w-32")

                def nullpunkt(_=None):
                    u["e0n0"] = (float(e0.value), float(n0.value)) if nullp.value and e0.value and n0.value else None
                for el in (nullp, e0, n0):
                    el.on_value_change(nullpunkt)
                ausgrauen(nz, nullp)
                hinweis("Ohne Haken: E0/N0 werden automatisch auf 1000 m gerundet, Z0 = tiefster Punkt − 1 m.")
            with karte("Netzwerk (nur bei Problemen)", GRAU, offen=False):
                feld_pfad("CA-Datei (bei SSL-Fehler)", u, "cafile", typen=("Zertifikat (*.pem;*.crt;*.cer)",))
                _haken("SSL-Prüfung abschalten (nur im Notfall)", u, "unsicher")

    def aktualisieren():
        for el, f in regeln:
            el.set_visibility(bool(f()))
    ui.timer(0.4, aktualisieren)
    aktualisieren()
    return wurzel
