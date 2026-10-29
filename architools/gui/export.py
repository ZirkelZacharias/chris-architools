"""Seite „Vorschau und Export“."""
import os
import time

from nicegui import ui

from .. import einstellungen as ES
from .. import laufen as L
from .. import projekt as P
from . import assistent, eier
from .ergebnis import ergebnis_zeigen
from .stil import (AKZENT, GRAU, HOEHE, INK, LINIE, SALBEI, Lauf, feld_pfad, hinweis, karte, oeffnen, szene3d, url)


AKTION = {}                                  # vom Kopf aus erreichbar: Export starten


def seite(p, speichern):
    ausg = p["ausgaben"]
    wahl = {k: True for k in P.AUSGABEN}            # was jetzt exportiert wird (innerhalb der Gewählten)
    opt = {"test": False}
    es = ES.laden()
    erg_ber = {}

    with ui.row().classes("w-full no-wrap gap-4").style(f"height:{HOEHE}"):
        linkspalte = ui.column().classes("h-full no-wrap gap-2").style("width:500px; min-width:440px")
        rechts = ui.column().classes("grow h-full no-wrap gap-1").style("min-width:0")

    # ---------------------------------------------------------------- rechts
    with rechts:
        with ui.tabs().classes("w-full").props("dense align=left") as tabs:
            t_uebersicht = ui.tab("Übersicht", icon="map")
            t_3d = ui.tab("3D-Ansicht", icon="view_in_ar")
            t_erg = ui.tab("Ergebnis", icon="inventory_2")
            t_log = ui.tab("Protokoll", icon="article")
        with ui.tab_panels(tabs, value=t_uebersicht).classes("w-full bg-transparent").style("flex:1 1 auto; min-height:0") \
                .props("keep-alive"):
            with ui.tab_panel(t_uebersicht).classes("p-0 h-full"):
                with ui.scroll_area().classes("h-full w-full"):
                    uebersicht = ui.column().classes("w-full pr-3")
                    with uebersicht:
                        hinweis("Noch keine Vorschau – links „Vorschau laden“ (nur Umgebung) oder gleich exportieren.")
            with ui.tab_panel(t_3d).classes("p-0 h-full"):
                with ui.scroll_area().classes("h-full w-full"):
                    drei_d = ui.column().classes("w-full pr-3")
                    with drei_d:
                        hinweis("Die 3D-Ansicht erscheint nach „Vorschau laden“. Maus: drehen · Rad: zoomen · rechte Taste: verschieben.")
            with ui.tab_panel(t_erg).classes("p-0 h-full"):
                with ui.scroll_area().classes("h-full w-full"):
                    ergebnis = ui.column().classes("w-full pr-3")
                    with ergebnis:
                        hinweis("Noch nichts erzeugt.")
            with ui.tab_panel(t_log).classes("p-0 h-full relative"):
                logel = ui.log(max_lines=4000).classes("w-full h-full log-bild").style("font-size:12px")
                fertig = ui.label("FERTIG").classes("fertig-stempel")
                fertig.set_visibility(False)
        with ui.row().classes("w-full items-center no-wrap gap-3"):
            balken = ui.linear_progress(value=0, show_value=False).classes("grow").props("rounded size=10px")
            balken.set_visibility(False)
            status = ui.label("").classes("text-caption").style(f"color:{GRAU}; min-width:260px")

    # ---------------------------------------------------------------- links
    with linkspalte:
        links = ui.scroll_area().classes("w-full").style("flex:1 1 0; min-height:0")
        with ui.row().classes("w-full gap-2 items-center no-wrap q-pr-sm").style(f"border-top:1px solid {LINIE}; padding-top:8px"):
            b_vor = ui.button("Vorschau laden", icon="visibility", on_click=lambda: vorschau()).props("outline no-caps size=md")
            b_exp = ui.button("Exportieren", icon="rocket_launch", on_click=lambda: exportieren()).props("unelevated no-caps size=md color=secondary") \
                .classes("grow")
            sp = ui.spinner(size="md").style(f"color:{AKZENT}")
            sp.set_visibility(False)
    with links:
        with ui.column().classes("w-full gap-3 pr-3"):
            with karte("Was wird jetzt ausgegeben?", AKZENT):
                zeilen = {}
                for k, (titel, icon, farbe, text, g, _o) in P.AUSGABEN.items():
                    with ui.row().classes("w-full items-center no-wrap gap-2") as z:
                        cb = ui.checkbox(value=True).on_value_change(lambda e, k=k: (wahl.__setitem__(k, bool(e.value)), zeichne_3d()))
                        ui.icon(icon).style(f"color:{farbe}")
                        with ui.column().classes("grow gap-0"):
                            ui.label(titel).classes("text-body2 text-weight-medium")
                            st = ui.label("").classes("text-caption").style(f"color:{GRAU}")
                        def ordner_auf(k=k):
                            s = p["stand"].get(k)
                            oeffnen(s["ordner"] if s else P.ausgabe_ordner(p, k))
                        ui.button(icon="folder_open", on_click=ordner_auf).props("flat dense round").tooltip("Ordner öffnen")
                    zeilen[k] = (z, st)
                hinweis("Haken weg = diese Ausgabe diesmal auslassen. Was schon erzeugt wurde, merkt sich das Projekt.")
            with karte("Wohin kommt der Export?", AKZENT):
                ziel = p.setdefault("ziel", {"ordner": "", "name": ""})
                feld_pfad("Zielordner (leer = Projektordner/ausgabe)", ziel, "ordner", art="ordner")
                ui.input("Name des Ausgabeordners (leer = Projektname)").bind_value(ziel, "name").classes("w-full")
                pfad_text = hinweis("")

                def pfad_zeigen(_=None):
                    pfad_text.text = "Der Export landet in: " + P.ausgabe_basis(p)
                pfad_zeigen()
                ui.timer(1.0, pfad_zeigen)
            with karte("Optionen", GRAU, offen=False):
                ui.checkbox("Testausschnitt (150 × 150 m, schnell zum Ausprobieren – nur Umgebung)").bind_value(opt, "test")
            hinweis("„Vorschau laden“ holt die Umgebungsdaten und zeigt Plan und 3D-Modell – bei Lasercut/3D-Druck auch das Modell "
                    "(Umschalter im Reiter 3D-Ansicht). Das rechnet genauso lange wie der Export.")

    AKTION["start"] = lambda: exportieren()
    lauf = Lauf(logel, [b_vor, b_exp], sp, fertig, balken, status)
    lauf.pop_67 = eier.log_67(logel)
    lauf.bericht_pfad = lambda: os.path.join(P.ausgabe_basis(p), "protokoll.txt")       # immer da, auch nach Fehlern

    def aktualisieren():
        for k, (z, st) in zeilen.items():
            z.set_visibility(bool(ausg.get(k)))
            st.text = P.stand_text(p, k)
        b_vor.set_visibility(any(ausg.get(k) for k in ("ifc", "lageplan", "schwarzplan", "info_dwg", "laser", "druck")))
    ui.timer(1.0, aktualisieren)
    aktualisieren()

    def gewaehlte():
        return [k for k in P.gewaehlt(p) if wahl.get(k)]

    # ---------------------------------------------------------------- Aktionen
    from .stil import FARBE_DRUCK, FARBE_LASER

    d3 = {"modus": "umg", "umg": None, "modell": None, "ue": 1.0}
    UE_WAHL = {1.0: "1× (maßstäblich)", 1.5: "1,5×", 2.0: "2×", 3.0: "3×", 5.0: "5×"}

    def gruppen_gewaehlt():
        g = gewaehlte()
        return (any(P.AUSGABEN[k][4] == "umgebung" for k in g), any(k in g for k in ("laser", "druck")))

    def zeichne_3d():
        """3D-Tab: bei Umgebung UND Modell gewählt mit Umschalter, sonst nur das, was gewählt ist."""
        drei_d.clear()
        hat_umg, hat_mod = gruppen_gewaehlt()
        with drei_d:
            ui.select(UE_WAHL, value=d3["ue"], label="Ansicht überhöhen (nur Darstellung)",
                      on_change=lambda e: (d3.__setitem__("ue", float(e.value)), zeichne_3d())).props("dense outlined").classes("w-64")
            if hat_umg and hat_mod:
                ui.toggle({"umg": "Umgebung (IFC)", "modell": "Modell (Lasercut / 3D-Druck)"}, value=d3["modus"],
                          on_change=lambda e: (d3.__setitem__("modus", e.value), zeichne_3d())).props("no-caps unelevated")
                modus = d3["modus"]
            else:
                modus = "modell" if hat_mod else "umg"
            if modus == "umg":
                r = d3["umg"]
                if not r:
                    hinweis("Die 3D-Ansicht der Umgebung erscheint nach „Vorschau laden“. "
                            "Maus: drehen · Rad: zoomen · rechte Taste: verschieben.")
                elif r.get("glb"):
                    with ui.row().classes("items-center gap-3"):
                        ui.label("Umgebung" + (f" ({d3['ue']:g}-fach überhöht)" if d3["ue"] != 1 else " (maßstäblich)")).classes("text-subtitle2")
                        hinweis("Maus: drehen · Rad: zoomen · rechte Taste: verschieben")
                    szene3d([(r["glb"], None)], r["b"], r["h"], hoehe=640, mitte=(0, 0), z_faktor=d3["ue"])
                else:
                    hinweis("3D-Vorschau war nicht möglich (siehe Protokoll).")
            else:
                s = d3["modell"]
                fl = (s or {}).get("material_farbe") or FARBE_LASER
                teile = [(s.get("vorschau_laser"), fl), (s.get("vorschau_druck"), FARBE_DRUCK)] if s else []
                if not any(pf and os.path.exists(pf) for pf, _ in teile):
                    hinweis("Das Modell (Lasercut-Schichten und 3D-Druck-Gebäude) erscheint nach „Vorschau laden“.")
                    ui.button("Modell-Vorschau berechnen", icon="view_in_ar", on_click=lambda: modell_vorschau()).props("outline")
                else:
                    with ui.row().classes("items-center gap-3"):
                        ui.label("Modell").classes("text-subtitle2")
                        ui.html(f'<span style="display:inline-block;width:12px;height:12px;background:{fl};border:1px solid #999"></span> Lasercut'
                                f' &nbsp; <span style="display:inline-block;width:12px;height:12px;background:{FARBE_DRUCK}"></span> 3D-Druck')
                        hinweis("Maus: drehen · Rad: zoomen · rechte Taste: verschieben")
                    szene3d(teile, s.get("modell_b", 400), s.get("modell_h", 300), hoehe=640, z_faktor=d3["ue"])

    zeichne_3d()

    async def modell_vorschau(wechseln=True):
        aus = [k for k in gewaehlte() if k in ("laser", "druck")]
        if not aus:
            return None
        speichern()
        tabs.set_value(t_log)
        lauf.anhaengen = not wechseln                                      # nach der Umgebungs-Vorschau: gleiches Protokoll
        r = await lauf.starten(lambda p, aus, log, prog: L.modell_export(p, aus, log, prog, vorschau=True), p, aus)
        if r:
            d3["modell"] = r
            if wechseln:
                d3["modus"] = "modell"
            zeichne_3d()
            if wechseln:
                tabs.set_value(t_3d)
        return r

    from . import ebenen as _eb

    def vorschau_job(p, aus, test, log, prog):
        return L.umgebung_vorschau(p, aus, log, prog, test=test)

    async def vorschau():
        aus = [k for k in gewaehlte() if P.AUSGABEN[k][4] == "umgebung"]
        if not aus:
            if any(k in gewaehlte() for k in ("laser", "druck")):
                d3["modus"] = "modell"
                await modell_vorschau()
            else:
                ui.notify("Für die Vorschau wähle mindestens eine Ausgabe, die ein Modell oder einen Plan ergibt.", type="warning")
            return
        speichern()
        tabs.set_value(t_log)
        r = await lauf.starten(vorschau_job, p, aus, opt["test"])
        if r:
            d = r.pop("daten", None)
            _eb.aktualisieren(p, d)
            uebersicht.clear()
            with uebersicht:
                ui.label("Gebiet (gestrichelt: Nahbereich)").classes("text-subtitle2")
                ui.image(url(r["png"])).classes("w-full bg-white")
            d3["umg"] = r
            d3["modus"] = "umg"
            zeichne_3d()
            if any(k in gewaehlte() for k in ("laser", "druck")):          # Lasercut-/3D-Druck-Modell gleich mit berechnen
                await modell_vorschau(wechseln=False)
            tabs.set_value(t_uebersicht)
            ui.notify("Vorschau fertig", type="positive")

    def export_job(p, aus, test, log, prog):
        return L.alles(p, aus, log, prog, test=test)

    async def exportieren():
        aus = gewaehlte()
        if not aus:
            ui.notify("Nichts zum Ausgeben gewählt (Startseite).", type="warning")
            return
        speichern()
        tabs.set_value(t_log)
        t0 = time.time()
        r = await lauf.starten(export_job, p, aus, opt["test"])
        speichern()
        if r:
            if r.get("modell") and not r["modell"].get("fehler"):
                d3["modell"] = r["modell"]
                zeichne_3d()
            u = r.get("umgebung") or {}
            if u.get("d") is not None and not u.get("fehler"):             # auch ohne „Vorschau laden“: 3D-Ansicht und Lageplan-Bild aus den Exportdaten
                from ..laufen import _ausgabe_zuordnen
                lp = [f for f in _ausgabe_zuordnen(u.get("dateien", [])).get("lageplan", []) if f.lower().endswith(".dxf")]
                lauf.anhaengen = True
                rv = await lauf.starten(lambda p, d, ue, lp, log, prog: L.vorschau_aus_daten(d, p, log, prog, ue, lp), p, u["d"], d3["ue"], lp)
                if rv:
                    uebersicht.clear()
                    with uebersicht:
                        ui.label("Gebiet (gestrichelt: Nahbereich)").classes("text-subtitle2")
                        ui.image(url(rv["png"])).classes("w-full bg-white")
                    d3["umg"] = rv
                    zeichne_3d()
            ergebnis.clear()
            with ergebnis:
                zeigen(r)
            tabs.set_value(t_erg)
            ui.notify("Fertig – Ergebnis ansehen", type="positive")
            eier.lang_gelaufen(time.time() - t0)
            fehler = [k for k, v in r.items() if isinstance(v, dict) and v.get("fehler")]
            if fehler:
                assistent.sag("Bei einem Teil des Exports ist etwas schiefgegangen. Die Datei protokoll.txt im Ausgabeordner zeigt, was – "
                              "bei Problemen einfach weitergeben.", "export_fehler", immer=True)
            else:
                assistent.sag("Fertig! In bericht.txt stehen Kosten- und Materialschätzung, die Quellen und Hinweise zu den Daten. "
                              "Quellenvermerke bitte in Pläne und Arbeiten übernehmen.", "export_fertig")

    def zeigen(r):
        with ui.row().classes("items-center gap-2 w-full"):
            ui.button("Ausgabeordner", icon="folder", on_click=lambda: oeffnen(P.ausgabe_basis(p))).props("outline dense")
            ui.button("bericht.txt", icon="description", on_click=lambda: oeffnen(os.path.join(P.ausgabe_basis(p), "bericht.txt"))) \
                .props("outline dense").tooltip("Bericht: Kosten- und Materialschätzung, Quellen, Hinweise")
            ui.button("protokoll.txt", icon="bug_report", on_click=lambda: oeffnen(os.path.join(P.ausgabe_basis(p), "protokoll.txt"))) \
                .props("outline dense").tooltip("Programmprotokoll des letzten Laufs – bei Problemen einfach weitergeben")
            ui.space()
            eier.icon(48)                                                   # Zirkel Zacharias schaut zu – wortlos
        u = r.get("umgebung")
        zu = {}
        if u:
            from ..laufen import _ausgabe_zuordnen
            zu = _ausgabe_zuordnen(u.get("dateien", []))

        def datei_liste(titel, dateien, fehler=None):
            ui.label(titel).classes("text-h6 mt-2")
            if fehler:
                ui.label("Fehler: " + fehler).style("color:#b00020")
            for f in dateien:
                with ui.row().classes("items-center gap-2 no-wrap"):
                    ui.icon("description").style(f"color:{GRAU}")
                    ui.label(os.path.basename(f)).classes("text-body2")
                    ui.label(f"{os.path.getsize(f) / 1e6:.1f} MB" if os.path.exists(f) else "").classes("text-caption") \
                        .style(f"color:{GRAU}")
                    ui.button(icon="open_in_new", on_click=lambda f=f: oeffnen(f)).props("flat dense round")
        # Reihenfolge: 3D-IFC, Lageplan, Modellbau, Schnitt/Höhenlinien, ganz am Ende die gewählten Zusatz-DWGs
        if u and (u.get("fehler") or zu.get("ifc")):
            datei_liste("Umgebung in 3D (IFC)", zu.get("ifc", []), u.get("fehler"))
            vg = d3["umg"]
            if vg and vg.get("glb"):
                with ui.row().classes("items-center gap-3"):
                    ui.label("3D-Vorschau der Umgebung (aus denselben Daten wie die IFC)").classes("text-subtitle2")
                    hinweis("Maus: drehen · rechte Taste: verschieben · Zoom im Reiter „3D-Ansicht“ (hier blättert das Rad durch die Ergebnisse)")
                szene3d([(vg["glb"], None)], vg["b"], vg["h"], hoehe=520, mitte=(0, 0), z_faktor=d3["ue"], zoom=False)
        if u and zu.get("lageplan"):
            datei_liste("Lageplan", zu["lageplan"])
            for b_ in ((d3["umg"] or {}).get("lageplan_bilder") or []):
                ui.image(url(b_)).classes("w-full bg-white")
        m = r.get("modell")
        if m:
            if m.get("fehler"):
                ui.label("Modellbau: Fehler: " + m["fehler"]).style("color:#b00020")
            else:
                sub = ui.column().classes("w-full")
                ergebnis_zeigen(sub, m, "Modellbau")
        for key, titel in (("schnitt", "Geländeschnitt"), ("hoehenlinien", "Höhenlinien")):
            s = r.get(key)
            if not s:
                continue
            ui.label(titel).classes("text-h6 mt-2")
            if s.get("fehler"):
                ui.label("Fehler: " + s["fehler"]).style("color:#b00020")
            else:
                for f in s["dateien"]:
                    with ui.row().classes("items-center gap-2 no-wrap"):
                        ui.label(os.path.basename(f)).classes("text-body2")
                        ui.button(icon="open_in_new", on_click=lambda f=f: oeffnen(f)).props("flat dense round")
                ui.image(url(s["png"])).classes("w-full bg-white")
        if u and (zu.get("schwarzplan") or zu.get("info_dwg")):
            datei_liste("Zusätzliche Pläne (DXF/DWG)", zu.get("schwarzplan", []) + zu.get("info_dwg", []))

