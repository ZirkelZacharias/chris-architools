# Quellen und Lizenzen (Stand 28.10.2026)

Kein Rechtsrat. Geprüft wurden die Katalogeinträge des Geoportals Berlin und die Paketlizenzen; Lizenzen können sich ändern.

## Daten
| Quelle | Lizenz | Pflicht |
|---|---|---|
| Berlin: DGM1, LoD2, ALKIS, Baumbestand (Straßenbäume), Fußgänger-/Radnetz, Denkmale, Berlin um 1900, Vegetationshöhen, Luftbilder | dl-de/zero-2.0 | keine |
| Berlin: Karte von Berlin 1:5000 (K5) | dl-de/by-2.0 | Nennung „Geoportal Berlin / Karte von Berlin 1:5000 (K5 SW-Ausgabe)“ |
| Berlin: Anlagenbäume Grün Berlin GmbH | dl-de/by-2.0 | Nennung „Grün Berlin GmbH / Baumbestand in den Liegenschaften …“ |
| OpenStreetMap | ODbL 1.0 | „© OpenStreetMap-Mitwirkende“; Share-Alike nur für veröffentlichte abgeleitete Datenbanken |
| Copernicus GLO-30 (nur Notfall-Gelände) | Copernicus-Lizenz | „Contains modified Copernicus DEM data …“ |
| Brandenburg, Hamburg, NRW, Bayern (Länder-Module) | dl-de/by bzw. zero, CC BY 4.0 (Bayern) | **nicht einzeln geprüft** |
| Berlin 3D-Meshmodell (nur für die experimentelle Fassadenfunktion) | Bedingungen nur im Portal, **nicht geprüft** | vor jeder Veröffentlichung prüfen |

Jeder Export enthält eine `QUELLEN.txt` mit diesen Vermerken.

## Programme (requirements.txt)
Überwiegend MIT/BSD/HPND (numpy, scipy, shapely, rasterio, pyogrio, matplotlib, trimesh, ezdxf, pandas, pyproj, Pillow, nicegui, manifold3d …).
- **PyMuPDF: AGPL-3.0.** Wird im Programm importiert. Ein öffentliches Repository mit AGPL-Abhängigkeit braucht eine AGPL-kompatible Projektlizenz (z. B. `LICENSE` mit AGPL-3.0) **oder** den Ersatz von PyMuPDF (z. B. pypdf/pdfium + matplotlib für PDF-Ausgabe). Entscheidung offen.
- **ifcopenshell: LGPL-3.0.** Unverändert als Bibliothek benutzt: erlaubt, Lizenzhinweis liegt den portablen Paketen bei (offen).
- Die portablen Zip-Pakete enthalten Python und alle Bibliotheken; für sie gelten deren Lizenztexte.

## Persönliches
- `architools/system/bilder/abschluss.jpg` ist ein bewusst enthaltenes persönliches Foto (Entscheidung des Autors).
- Commit-Autoren: nur „Claude“ und „build-bot“; keine E-Mail-Adressen oder Zugangsdaten im Repository.
- `testprotokolle/` enthält nur CI-Läufe (Runner-Pfade, keine persönlichen Daten).
