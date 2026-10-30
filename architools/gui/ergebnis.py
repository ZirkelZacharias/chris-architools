"""Ergebnisanzeige (Modellbau, Umgebung, Schnitt)."""
import os

from nicegui import ui

from .stil import FARBE_DRUCK, FARBE_GRAVUR, FARBE_LASER, GRAU, hinweis, oeffnen, szene3d, url, vorschau_svgs


def ergebnis_zeigen(bereich, stats, titel="Ergebnis"):
    bereich.clear()
    if not stats:
        return
    with bereich:
        with ui.row().classes("w-full items-center gap-2"):
            ui.label(titel).classes("text-h6")
            ui.space()
            if stats.get("ausgabe"):
                ui.button("Ausgabeordner", icon="folder", on_click=lambda: oeffnen(stats["ausgabe"])).props("outline dense")
            if stats.get("laser_ordner"):
                ui.button(f"Laser-PDFs ({len(stats.get('laser_pdfs', [])) + len(stats.get('einsatz_pdfs', []))})",
                          icon="picture_as_pdf", on_click=lambda: oeffnen(stats["laser_ordner"])).props("outline dense")
            if stats.get("kostenliste") and os.path.exists(stats["kostenliste"]):
                ui.button("Kostenliste", icon="receipt_long", on_click=lambda: oeffnen(stats["kostenliste"])) \
                    .props("outline dense").tooltip("Zuschnitt- und Kostenliste (Text, nur geschätzt)")
            if stats.get("holz"):
                ordner_holz = os.path.dirname(stats["holz"][0])
                ui.button("Holz", icon="carpenter", on_click=lambda: oeffnen(ordner_holz)).props("outline dense") \
                    .tooltip("Zuschnittliste und Zeichnung für Rahmenleisten / Podest")
            if stats.get("montageplan"):
                ui.button("Montageplan", icon="picture_as_pdf",
                          on_click=lambda: oeffnen(stats["montageplan"])).props("outline dense")
        zeilen = []
        for k, txt in (("material", "Material"), ("n_laserplatten", "Laserplatten"), ("n_einsatzplatten", "Einsatz-Platten"),
                       ("platten", "Laserplatten"), ("n_teile", "Laserteile"), ("teile", "Laserteile"),
                       ("n_rippen", "Steckrippen"), ("n_stuetzen", "Stützklötze"),
                       ("n_druck", "Gebäude gedruckt"), ("n_gebaeude_laser", "Gebäude gelasert"), ("n_geb_teile", "Gebäude-Laserteile"),
                       ("n_restplatten", "Restplatten genutzt"), ("n_druckplatten", "Druckplatten"), ("n", "Druckkörper")):
            v = stats.get(k)
            if v not in (None, 0, {}) and not isinstance(v, (dict, list)):
                zeilen.append((txt, v))
        if stats.get("filament_g"):
            zeilen.append(("Filament (grob)", f"{stats['filament_g']:.0f} g"))
        with ui.grid(columns=4).classes("w-full gap-1"):
            for a, b in zeilen:
                with ui.card().tight().classes("p-2"):
                    ui.label(str(b)).classes("text-subtitle1 text-weight-medium")
                    ui.label(a).classes("text-caption").style(f"color:{GRAU}")
        if stats.get("kosten_text"):
            with ui.expansion("Zuschnitt- und Kostenliste (nur geschätzt)", icon="receipt_long").classes("w-full").props("dense"):
                ui.html("<pre style='white-space:pre-wrap; font-size:12px; margin:0'>"
                        + stats["kosten_text"].replace("&", "&amp;").replace("<", "&lt;") + "</pre>")
        fl = stats.get("material_farbe") or FARBE_LASER                      # Vorschau in der Farbe des Lasercut-Materials
        teile = [(stats.get("vorschau_laser"), fl), (stats.get("vorschau_gravur"), FARBE_GRAVUR), (stats.get("vorschau_druck"), FARBE_DRUCK), (stats.get("vorschau_gebaeude"), None)]
        if any(p and os.path.exists(p) for p, _ in teile):
            with ui.row().classes("items-center gap-3 mt-2"):
                ui.label("3D-Vorschau").classes("text-subtitle2")
                ui.html(f'<span style="display:inline-block;width:12px;height:12px;background:{fl};border:1px solid #999"></span> Lasercut ({stats.get("material", "")})'
                        f' &nbsp; <span style="display:inline-block;width:12px;height:12px;background:{FARBE_GRAVUR}"></span> Ritzen/Gravur'
                        f' &nbsp; <span style="display:inline-block;width:12px;height:12px;background:{FARBE_DRUCK}"></span> 3D-Druck')
                hinweis("Maus: drehen · rechte Taste: verschieben · Zoom im Reiter „3D-Ansicht“ (hier blättert das Rad durch die Ergebnisse)")
            szene3d(teile, stats.get("modell_b", 400), stats.get("modell_h", 300), zoom=False)
        an = [p for p in stats.get("ansichten") or [] if os.path.exists(p)]
        if an:
            ui.label("Draufsicht und Schnitte").classes("text-subtitle2 mt-2")
            for p in an:
                ui.image(url(p)).classes("w-full bg-white")
        svgs = stats.get("laser_svgs") or stats.get("svgs") or []
        if svgs:
            ui.label("Laserplatten (Vorschau; Linien hier dicker gezeichnet)").classes("text-subtitle2 mt-2")
            vs = [x for x in stats.get("laser_svgs_vorschau") or [] if os.path.exists(x)] \
                or vorschau_svgs(svgs, os.path.join(os.path.dirname(svgs[0]), ".vorschau"))
            with ui.grid(columns=2).classes("w-full gap-2"):
                for p in vs:
                    with ui.card().tight():
                        ui.image(url(p)).classes("w-full bg-white")
                        ui.label(os.path.basename(p).replace(".svg", "")).classes("text-caption p-1")
        dp = stats.get("druck_plaene") or []
        if dp:
            ui.label("Druckplatten").classes("text-subtitle2 mt-2")
            with ui.row().classes("gap-2"):
                for d in dp:
                    if d.get("datei") and os.path.exists(d["datei"]):
                        with ui.card().tight().classes("p-1"):
                            szene3d([(d["datei"], FARBE_DRUCK)], d["format"][0], d["format"][1], hoehe=240, breite=320, zoom=False)
                            ui.label(f"{d['name']}: {len(d['teile'])} Teile").classes("text-caption")