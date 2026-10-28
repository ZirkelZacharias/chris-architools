# Chris ArchItools – Entscheidungsprotokoll

Jede Zeile: Datum · Entscheidung · warum · wie man es ändert.

## Daten und Rechnen
- 28.10.2026 · **Markante Gebäude: DOM nicht mehr Standard.** Automatisch = OpenStreetMap → LoD2. Warum: DOM liest Lüftungsanlagen und Versprünge falsch; rechenärmer (kein DOM-Download). Ändern: Feld „Form aus“ → „DOM zuerst“ (Config `markant_quelle="dom_zuerst"`).
- 28.10.2026 · **Gelände bleibt DGM1** (nicht bDOM). Warum: bDOM ist ein Oberflächenmodell (mit Gebäuden und Bewuchs), also kein Boden. bDOM bleibt für Dachformen/Vegetation denkbar.
- 28.10.2026 · **Ein Rechenkern.** IFCmap-Module liegen einmal in `architools/kern/`; die Kopie `ifcmap_kopie` des Modellbau-Programms entfällt.
- 28.10.2026 · **„Informations-DWG“ = die 2D-Arbeitsdatei von IFCmap** (alle Informationsebenen `2D_…`, optional mit Zusatzplänen). Falls etwas anderes gemeint ist: Zuordnung in `architools/projekt.py` (`umgebung_config`) anpassen.
- 28.10.2026 · **Umgebung und Modellbau laden ihre Daten getrennt.** Warum: unterschiedliche Ausschnitte und Genauigkeit; so rechnet jede Ausgabe nur, was sie braucht. Ändern: gemeinsamen Datenweg in `laufen.py` bauen.
- 28.10.2026 · **Pläne (Lageplan, Schwarzplan) ohne Gelände**; Gelände nur, wenn IFC oder Informations-DWG gewählt sind. Warum: rechenärmer.
- 28.10.2026 · **Ebenen und Nutzungs-Zuordnung gehören nicht zum Daten-Schlüssel.** Änderungen dort laden nichts neu, sondern wirken auf die schon geladenen Daten.
- 28.10.2026 · **Modell-Vorschau (12:05 geändert):** „Vorschau laden“ rechnet bei gewähltem Lasercut/3D-Druck das Modell gleich mit (Umschalter Umgebung/Modell im Reiter 3D-Ansicht); Rechenzeit wie beim Export, Ausgabe in `ausgabe/.vorschau/modell`, Projektstand bleibt unverändert. Der Knopf „Modell-Vorschau berechnen“ bleibt für sich allein nutzbar.
- 28.10.2026 · **Höhe in der 3D-Vorschau nur auf Wunsch überhöhen** (Auswahl „Ansicht überhöhen“, Standard 1×). Nur die Darstellung wird gestreckt (`scale(1,1,k)`), die Dateien bleiben unverändert.
- 28.10.2026 · **bericht.txt (12:15):** Nach jedem Lauf (Vorschau, Export, auch bei Fehlern) schreibt das Programm das Protokoll nach `ausgabe/bericht.txt` (Knopf im Ergebnis); Umgebungs- und Modell-Vorschau stehen zusammen in einer Datei. Zum Weitergeben bei Problemen. Ändern: `Lauf.bericht_schreiben` in `gui/stil.py`.

- 28.10.2026 · **Netzwerk-Einstellungen (Zertifikatsdatei, „unsicher“) der Umgebung gelten auch für Modellbau und Geländeschnitt.**

## Ausgabeort und Updates
- 28.10.2026 · **Ausgabeort frei wählbar (12:47):** Vorschau & Export → „Wohin kommt der Export?“: Zielordner wählen und dem Ausgabeordner einen Namen geben; alles landet in `<Zielordner>/<Name>/` (Unterordner umgebung, modell, schnitt, dazu bericht.txt). Leer = `<Projektordner>/ausgabe`. Die Vorschau schreibt weiter nur in `<Projektordner>/ausgabe/.vorschau`. Gespeichert im Projekt (`ziel`).
- 28.10.2026 · **Updates als kleine ZIP (12:45):** `ChrisArchItools_Update_<System>_Stand<alt>_zu_<neu>.zip` enthält nur geänderte und neue Dateien plus `update.json` (Dateiliste mit Prüfsummen, zu entfernende Dateien). Einspielen: ZIP in den Ordner `updates` legen und das Programm starten, oder Einstellungen → Programm-Update. Alte Dateien werden vorher nach `updates/_sicherung/stand_<alt>/` gesichert; Projekte, Einstellungen und `.venv` werden nie angefasst; Updates müssen der Reihe nach kommen. Ändert sich `requirements.txt`, installiert START die Pakete nach. Der Stand steht in `stand.json` und in der Fußzeile. Auch per Hand möglich (ZIP entpacken, Ordner über das Programm kopieren). Ändern: `architools_update.py`; Bau: `bau/baue.py --release`.

## Schnitt
- 28.10.2026 · **Der Schnitt wird nie überhöht** (Wunsch 12:47): Maßstab 1:1 in Höhe und Länge, die Eingabe „Überhöhung“ gibt es dort nicht mehr (Lasercut-Gelände und 3D-Vorschau haben ihre eigene, optionale Überhöhung).
- 28.10.2026 · **Schnitt zeigt die Ansicht dahinter** (Einstellungen → Schnitt: Ansicht an/aus, Tiefe 100 m, Seite links/rechts, Bäume an/aus): Gebäude-Silhouetten (hellgrau, deckend), Gelände dahinter, Bäume. Bäume, die die Schnittlinie treffen, sind dunkelgrün, die dahinter hellgrün. Ebenen getrennt (12:16): DXF/DWG `SCHNITT_GELAENDE`, `SCHNITT_GEBAEUDE`, `SCHNITT_BAEUME` (Vordergrund) und `HINTERGRUND_GELAENDE`, `HINTERGRUND_GEBAEUDE`, `HINTERGRUND_BAEUME`; SVG-Gruppen `SCHNITT` und `HINTERGRUND`. Nur mit Beispieldaten getestet.

## ÖPNV
- 28.10.2026 · **Informations-DWG: ÖPNV aus dem ÖPNV-Vorrangnetz** (Tram, Bus, S-Bahn, geplante Tramstrecke; statt der BVG-Karte). Reihenfolge: Vorrangnetz → BVG (nur als Ersatz) → Haltestellen → OpenStreetMap füllt Lücken (inkl. light_rail). Die Attributnamen des Vorrangnetz-Dienstes sind ungetestet (kein Netz hier); das Protokoll listet Beispielattribute, falls etwas nicht erkannt wird. Der WMS liefert nur Bilder, deshalb WFS.

## Formate
- 28.10.2026 · **2D-Standard DXF** (02:12 wieder, nachdem er kurz DWG war). Archicad liest beide gleichwertig; DXF ist ohne Verlust (Farben, Transparenz, Schraffuren). Nur ein kleines Icon von Zirkel Zacharias (ohne Pfeil, Text oder Tipp) markiert die Archicad-optimale Wahl (DXF bzw. IFC); er sagt nichts und hat keine Sprechblase. Ändern: `architools/formate.py` (`STANDARD_2D`, `EMPFEHLUNG_2D`) und `projekt.py` (`formate`, `SCHNITT_STANDARD`).
- 28.10.2026 · **DWG wird direkt im Programm geschrieben** (`architools/dwg_direkt.py`, Bibliothek ezdwg): Format R2000 (AC1015), Farben auf ACI-Palette, keine Transparenz, Schraffuren als Hatch. Reihenfolge: ODA File Converter, wenn vorhanden → eingebauter Schreiber → DXF bleibt erhalten. Geprüft nur durch Zurücklesen/Rendern, nicht in Archicad.
- 28.10.2026 · **3D-Standard IFC.** GLB/OBJ/STL/PLY sind zusätzliche Umwandlungen (Rechenzeit, Speicher, keine Bauteil-Information). Das Zacharias-Icon markiert nur das Standardformat.
- 28.10.2026 · **DXF → PDF/SVG über ezdxf + matplotlib** (getestet), **IFC → GLB/OBJ/STL/PLY über ifcopenshell + trimesh** (getestet).

## Gebiet und Karte
- 28.10.2026 · **Rahmen wirkt „schief“, weil UTM33 gegenüber Nord um etwa −1,25° gedreht ist** (Meridiankonvergenz); die Karte ist nach Norden ausgerichtet. Knopf „nach Norden“ setzt die Drehung auf −Konvergenz. Ändern: Drehung von Hand.
- 28.10.2026 · **Nah- und Mittelbereich nur auf der Gebiet-Seite**, nicht doppelt in den Einstellungen.

## Noch nicht verdrahtet / ungetestet
- **Quellenreihenfolge (Wunsch 02:26): amtlich zuerst, OpenStreetMap nur für das, was es amtlich nicht gibt.** Gebäude ohne LoD2: Umriss ALKIS (OSM-Umriss nur ohne passenden ALKIS-Grundriss; passend = ≥ 70 % Überdeckung, Fläche 0,6–1,6×) → Höhe/Dachform Umweltatlas (wenn gewählt, gilt vor OSM, außer bei Gebäuden mit OSM-Teilen) → OSM-Tags → ALKIS-Geschosse × 3 m → 2,2 m. Quelle im IFC: `ALKIS+UA`, `ALKIS+OSM`, `OSM`, `ALKIS`. Bäume: Baumkataster → Umweltatlas-Raster → OSM nur, wo im Umkreis von 3 m kein amtlicher Baum steht. Ändern: Haken in Einstellungen → Daten (`osm_ergaenzen`, `ua_*`); Logik in `kern/ifcmap_luecken.py` (`bauen`, `alkis_passend`) und `kern/ifcmap_umweltatlas.py`.
- **Radverkehrsnetz (Wunsch 02:26): vor allem Quelle für die Wege**, nicht nur Zusatzebene (Haken `rad_wege`, Standard aus): Linien des Dienstes `radverkehrsnetz` (Typen `radverkehrsnetz`, `radfernwege`, `stadtgruen`) werden zu Wegeflächen (Breite aus dem Dienst, sonst 2,5 m) und gelten als Nutzung „Weg“ – Straße, Bahn und Gewässer behalten Vorrang, Grün/Wald/Siedlung weichen. Wirkt auf 3D-Gelände, DXF und Pläne. Die Zusatzebene `2D_Rad_*` bleibt als Option. Ungetestet gegen den Live-Dienst.
- **Umweltatlas Vegetationshöhen**: Es gibt ein 1-m-Raster (Dezimeter, aus True-Orthophotos 2020; WMS-Ebene `c_vegetationshoehe_2020_raster`, Download `veghoehe_2020.zip`, ca. 785 MB). Der WMS liefert nur eingefärbte Bilder (Grüntöne), nicht die Werte; deshalb wird der GeoTIFF-Download genutzt (einmalig, Zwischenspeicher, Fensterlesen ohne Entpacken). Verwendung: Bäume ohne Höhe bekommen die höchste Rasterzelle im Kronenradius; Baumspitzen (lokale Maxima ≥ 4 m, Plateaus = ein Baum), die im Kataster fehlen und nicht auf Gebäuden stehen, werden ergänzt (Krone ≈ 0,35·Höhe + 1,5 m, höchstens 20 000). Haken `ua_vegetationsraster` (Standard aus). Ohne das Raster gibt es als billigen Ersatz die Blockmittelwerte (`ua_vegetationshoehen`). Eigene Raster: `veg_raster_dateien`.
- **Das Vegetationsraster verbessert Gebäude nicht**: es enthält nur Pflanzen, keine Dächer. Für Gebäudedetails dienen Umweltatlas-Gebäudehöhen (Firsthöhe, Dachart, Geschosse; Haken `ua_gebaeudehoehen`, Standard aus), ALKIS und OSM; echte Dachformen kämen aus DOM (nicht Standard).
- **Alle Berliner Echtdaten-Downloads** (DGM1, LoD2, ALKIS, OSM) konnten hier nicht getestet werden (kein Netz); getestet wurde mit Beispieldateien.
- **DWG über ODA** (der eingebaute Schreiber ist durch Zurücklesen geprüft), **Import alter IFCmap-Projektdateien** (nur sicher abbildbare Felder + Mittelpunkt/KBS).

## Kleine Überraschungen (Absicht: unauffällig)
- „Archicad-Bildungsversion“-Stempel; das Bild liegt blass hinter dem Protokoll; 5 Klicks auf den Titel zeigen es.
- Zirkel Zacharias (nur 3D, absichtlich schlecht gerendert) – 3 Klicks aufs Versionskürzel oder selten nach langem Lauf. Er sagt nie etwas. Als kleines 3D-Icon (durchsichtiger Hintergrund, `figuren.icon()`) markiert er das Archicad-beste Format und sitzt still im Ergebnis-Reiter.
- Freundin: Rosi Radiergummi (3D, schlecht gerendert; Doppelbild mit Zirkel Zacharias) – nach sehr langen Läufen (> 10 min) kommt er mit ihr. Es gibt keinen 2D-Zacharias mehr (28.10. 12:17, auf Wunsch); Gerda Geodreieck (flach) ist rausgenommen. „Dorothea“ ist bewusst nicht vergeben.
- „Sonnenbank-Flavour“ bleibt der Name der Sonnenbahn-Karte; eine leise „· 67 ·“-Zeile im Protokoll bei 67 %.
