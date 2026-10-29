"""Werkzeuge: Auto-Lasercut-Layout, Auto-3D-Druck-Layout, Materialbibliothek, Einstellungen."""
import copy
import os

from nicegui import ui

from .. import einstellungen as ES
from ..modell import bibliothek as BIB
from .ergebnis import ergebnis_zeigen
from .stil import (AKZENT, FARBE_DRUCK, GRAU, HOEHE, INK, LINIE, MASSSTAEBE, OCKER, SALBEI, Lauf, feld_pfad, hinweis,
                   karte, mm_text, oeffnen, waehlen)

WERKZEUG_STANDARD = {
    "layout": {"dateien": [], "einheit": "mm", "massstab": 1, "anzahl": 1, "unbekannt": "schneiden",
               "ausgabe_ordner": "", "name": "layout"},
    "druck3d": {"dateien": [], "einheit": "m", "massstab": 500, "modus": "massiv", "zusammenfassen": False,
                "min_wand_mm": 1.2, "ausgabe_ordner": "", "name": "druck"},
}


class Werkzeuge:
    def __init__(self, proj, me):
        self.p = proj
        self.me = me                      # ModellEinst: Material-/Druckerfelder
        self.cfg = proj["modell"]
        w = self.cfg.setdefault("werkzeuge", {})
        for k, v in WERKZEUG_STANDARD.items():
            w.setdefault(k, copy.deepcopy(v))
            for kk, vv in v.items():
                w[k].setdefault(kk, copy.deepcopy(vv))

    def seite_layout(self):
        w = self.cfg["werkzeuge"]["layout"]
        with ui.row().classes("w-full no-wrap gap-4").style(f"height:{HOEHE}"):
            links = ui.scroll_area().classes("h-full").style("width:600px; min-width:520px")
            rechts = ui.column().classes("grow h-full no-wrap").style("min-width:0")
        with links:
            with ui.column().classes("w-full gap-3 pr-3"):
                with karte("Teile", AKZENT):
                    hinweis("DXF, PDF oder SVG – z. B. Fassaden aus ArchiCAD. Rot = schneiden, Blau = ritzen, "
                            "schwarze Flächen = gravieren (auch Layer-Namen „schneiden/ritzen/gravieren“).")
                    feld_pfad("Dateien (mehrere mit ;)", w, "dateien", mehrere=True,
                              typen=("Zeichnungen (*.dxf;*.pdf;*.svg)",))
                    with ui.row().classes("gap-2"):
                        ui.select(["mm", "cm", "m"], label="Einheit der Zeichnung").bind_value(w, "einheit").classes("w-44")
                        ui.number("Maßstab 1:", min=1).bind_value(w, "massstab").classes("w-28") \
                            .tooltip("1 = Zeichnung ist schon im Modellmaßstab")
                        ui.number("Exemplare", min=1, step=1).bind_value(w, "anzahl").classes("w-28")
                    ui.select({"schneiden": "andere Linien schneiden", "ignorieren": "andere Linien ignorieren"},
                              label="Linien ohne Werkstattfarbe").bind_value(w, "unbekannt").classes("w-72")
                with karte("Material und Platte", OCKER):
                    self.me.material_format(self.cfg["laser"])
                with karte("Ausgabe", INK):
                    with ui.row().classes("w-full gap-2 items-end no-wrap"):
                        ui.input("Name").bind_value(w, "name").classes("w-40")
                        feld_pfad("Ausgabeordner", w, "ausgabe_ordner", art="ordner")
        with rechts:
            logel = ui.log(max_lines=1000).classes("w-full log-bild").style("height: 160px; font-size: 12px")
            with ui.scroll_area().classes("w-full").style("flex:1 1 auto"):
                self.erg_l = ui.column().classes("w-full pr-3")
            with ui.row().classes("items-center gap-2 pt-1"):
                knopf = ui.button("Platten anordnen", icon="grid_view", on_click=lambda: self._layout_start()) \
                    .props("unelevated size=lg").style(f"background:{AKZENT}!important")
                fs = ui.spinner(size="lg")
                fs.set_visibility(False)
        self.lauf_l = Lauf(logel, [knopf], fs)

    async def _layout_start(self):
        from ..modell import layout as LY
        w = copy.deepcopy(self.cfg["werkzeuge"]["layout"])
        if not w["dateien"]:
            ui.notify("Bitte Dateien angeben", type="warning")
            return
        if not w.get("ausgabe_ordner"):
            w["ausgabe_ordner"] = os.path.join(os.path.dirname(w["dateien"][0]), "lasercut")
        cfg = copy.deepcopy(self.cfg)
        r = await self.lauf_l.starten(lambda w, cfg, log: LY.layout(w, cfg, log), w, cfg)
        if r:
            ergebnis_zeigen(self.erg_l, r, "Lasercut-Layout")

    def seite_druck(self):
        w = self.cfg["werkzeuge"]["druck3d"]
        with ui.row().classes("w-full no-wrap gap-4").style(f"height:{HOEHE}"):
            links = ui.scroll_area().classes("h-full").style("width:600px; min-width:520px")
            rechts = ui.column().classes("grow h-full no-wrap").style("min-width:0")
        with links:
            with ui.column().classes("w-full gap-3 pr-3"):
                with karte("3D-Dateien", AKZENT):
                    feld_pfad("Dateien (mehrere mit ;)", w, "dateien", mehrere=True,
                              typen=("3D (*.ifc;*.stl;*.obj;*.3mf;*.ply;*.gml;*.glb)",))
                    with ui.row().classes("gap-2"):
                        ui.select(["m", "cm", "mm"], label="Einheit der Datei").bind_value(w, "einheit").classes("w-36") \
                            .tooltip("IFC und CityGML sind immer in Metern")
                        ui.select(MASSSTAEBE, label="Maßstab", new_value_mode="add-unique", with_input=True) \
                            .bind_value(w, "massstab").classes("w-32")
                        ui.number("Min. Wand mm", step=0.1).bind_value(w, "min_wand_mm").classes("w-28")
                    ui.select({"massiv": "massiv – Außenform mit Dach, ohne Innenräume (empfohlen ab 1:200)",
                               "original": "original – wie modelliert (repariert)"}, label="Umwandlung") \
                        .bind_value(w, "modus").classes("w-full")
                    ui.checkbox("alle Teile einer Datei zu einem Körper zusammenfassen").bind_value(w, "zusammenfassen")
                with karte("Drucker", OCKER):
                    self.me.drucker(self.cfg["druck"])
                with karte("Ausgabe", INK):
                    with ui.row().classes("w-full gap-2 items-end no-wrap"):
                        ui.input("Name").bind_value(w, "name").classes("w-40")
                        feld_pfad("Ausgabeordner", w, "ausgabe_ordner", art="ordner")
        with rechts:
            logel = ui.log(max_lines=1000).classes("w-full log-bild").style("height: 160px; font-size: 12px")
            with ui.scroll_area().classes("w-full").style("flex:1 1 auto"):
                self.erg_d = ui.column().classes("w-full pr-3")
            with ui.row().classes("items-center gap-2 pt-1"):
                knopf = ui.button("Druckbar machen", icon="view_in_ar", on_click=lambda: self._druck_start()) \
                    .props("unelevated size=lg").style(f"background:{AKZENT}!important")
                fs = ui.spinner(size="lg")
                fs.set_visibility(False)
        self.lauf_d = Lauf(logel, [knopf], fs)

    async def _druck_start(self):
        from ..modell import druck as D
        w = copy.deepcopy(self.cfg["werkzeuge"]["druck3d"])
        if not w["dateien"]:
            ui.notify("Bitte Dateien angeben", type="warning")
            return
        if not w.get("ausgabe_ordner"):
            w["ausgabe_ordner"] = os.path.join(os.path.dirname(w["dateien"][0]), "druck")
        try:
            w["massstab"] = float(str(w["massstab"]).replace("1:", "").replace(",", "."))
        except ValueError:
            ui.notify("Maßstab als Zahl angeben", type="warning")
            return
        cfg = copy.deepcopy(self.cfg)
        r = await self.lauf_d.starten(lambda w, cfg, log: D.druckbar(w, cfg, log), w, cfg)
        if r:
            r = dict(r, druck_plaene=r["platten"])
            r.pop("platten")
            ergebnis_zeigen(self.erg_d, r, "3D → druckbar")

    def seite_bibliothek(self):
        with ui.scroll_area().style(f"height:{HOEHE}"):
            with ui.row().classes("w-full gap-4 items-start no-wrap"):
                with ui.column().classes("gap-3").style("width:680px"):
                    self._materialien()
                with ui.column().classes("gap-3").style("width:460px"):
                    with karte("Plattenformate / Laser", AKZENT):
                        for n, e in BIB.alle("laser").items():
                            ui.label(f"{n}: {e['bett_mm'][0]:.0f} × {e['bett_mm'][1]:.0f} mm")
                        hinweis("Eigene Formate gibst du direkt beim Werkzeug ein („eigenes Format“).")
                        ui.label("Werkstatt-Regeln: Rot schneiden · Blau ritzen · Schwarz gravieren · Haarlinie · RGB · "
                                 "eine PDF je Platte · Stege ≥ 0,75 mm · 3 mm Rand · 2 mm Teileabstand.") \
                            .classes("text-caption")
                    with karte("3D-Drucker", SALBEI):
                        for n, e in BIB.alle("drucker").items():
                            ui.label(f"{n}: Bett {e['bett_mm'][0]:.0f} × {e['bett_mm'][1]:.0f} mm, "
                                     f"Höhe {e['hoehe_mm']:.0f} mm, Düse {e['duese_mm']} mm")
                        hinweis("Filament: PLA (Standard) oder PETG, 1,75 mm.")

    def _materialien(self):
        form = {"name": "", "staerken": "", "max_mm": None, "hinweis": "", "alt": None}
        with karte("Materialien", OCKER):
            tab = ui.column().classes("w-full gap-0")
            ui.separator()
            titel = ui.label("Neues Material").classes("text-subtitle2")
            with ui.row().classes("w-full gap-2 items-end"):
                ui.input("Name").bind_value(form, "name").classes("w-44")
                ui.input("Stärken mm (z. B. 1; 1,5; 2)").bind_value(form, "staerken").classes("w-52")
                ui.number("Werkstatt-Grenze mm").bind_value(form, "max_mm").classes("w-40")
            ui.input("Hinweis").bind_value(form, "hinweis").classes("w-full")
            with ui.row().classes("gap-2"):
                ui.button("Speichern", icon="save", on_click=lambda: speichern()).props("unelevated")
                ui.button("Abbrechen", on_click=lambda: neu()).props("flat")
                ui.space()
                ui.button("Voreinstellungen wiederherstellen", icon="restore",
                          on_click=lambda: (BIB.zuruecksetzen("materialien"), zeichnen(),
                                            ui.notify("Voreinstellungen wiederhergestellt"))).props("flat dense")

        def neu():
            form.update(name="", staerken="", max_mm=None, hinweis="", alt=None)
            titel.text = "Neues Material"

        def bearbeiten(name, m):
            form.update(name=name, staerken="; ".join(mm_text(s) for s in m["staerken"]), max_mm=m.get("max_mm"),
                        hinweis=m.get("hinweis", ""), alt=name)
            titel.text = f"„{name}“ bearbeiten"

        def loeschen(name):
            BIB.loeschen("materialien", name)
            ui.notify(f"„{name}“ gelöscht")
            zeichnen()

        def speichern():
            try:
                st = sorted({float(x.strip().replace(",", ".")) for x in str(form["staerken"]).replace(";", " ").split()
                             if x.strip()})
            except ValueError:
                ui.notify("Stärken als Zahlen angeben", type="warning")
                return
            if not form["name"] or not st:
                ui.notify("Name und Stärken angeben", type="warning")
                return
            BIB.speichern("materialien", form["name"].strip(),
                          {"staerken": st, "max_mm": form["max_mm"], "hinweis": form["hinweis"]}, alter_name=form["alt"])
            ui.notify("Gespeichert – steht in allen Werkzeugen zur Auswahl", type="positive")
            neu()
            zeichnen()

        def zeichnen():
            tab.clear()
            with tab:
                for name, m in BIB.alle("materialien").items():
                    with ui.row().classes("w-full items-center no-wrap gap-2 py-1").style(f"border-bottom:1px solid {LINIE}"):
                        with ui.column().classes("grow gap-0"):
                            ui.label(name).classes("text-weight-medium")
                            hinweis(", ".join(mm_text(s) for s in m["staerken"]) + " mm"
                                    + (f" · Werkstatt bis {mm_text(m['max_mm'])} mm" if m.get("max_mm") else "")
                                    + (f" · {m['hinweis']}" if m.get("hinweis") else ""))
                        ui.button(icon="edit", on_click=lambda n=name, m=m: bearbeiten(n, m)).props("flat dense round") \
                            .tooltip("Bearbeiten")
                        ui.button(icon="delete", on_click=lambda n=name: loeschen(n)).props("flat dense round") \
                            .tooltip("Löschen")
        zeichnen()

    # ---------------- Programm-Update
    def _update_karte(self):
        import architools_update as AU
        from .. import STAND
        z = {"pfad": ""}
        hinweis(f"Installiert: Stand {STAND}. Eine Update-Datei (ZachariasTools_Update_….zip) enthält nur geänderte und neue Dateien; "
                "Projekte und Einstellungen bleiben unberührt, ersetzte Dateien werden vorher gesichert (Ordner updates/_sicherung).")
        feld_pfad("Update-Datei", z, "pfad", typen=("Update (*.zip)",))
        ausgabe = ui.label("").classes("text-body2").style("white-space:pre-wrap")

        def einspielen():
            pfad = (z["pfad"] or "").strip().strip('"')
            if not pfad or not os.path.isfile(pfad):
                ui.notify("Bitte erst die Update-Datei angeben.", type="warning")
                return
            ok, m = AU.anwenden(pfad)
            ausgabe.text = m + ("\nBitte das Programm schließen und neu starten." if ok and "schon eingespielt" not in m else "")
            ui.notify("Update eingespielt – bitte neu starten" if ok else "Update nicht eingespielt", type="positive" if ok else "negative")
        with ui.row().classes("gap-2"):
            ui.button("Update einspielen", icon="system_update_alt", on_click=einspielen).props("flat dense")
            ui.button("updates-Ordner öffnen", icon="folder", on_click=lambda: (os.makedirs(AU.UPDATES, exist_ok=True), oeffnen(AU.UPDATES))) \
                .props("flat dense")
        hinweis("Oder: die Datei in den Ordner „updates“ neben dem Programm legen – beim nächsten Start wird sie automatisch eingespielt.")
        es = ES.laden()
        ui.checkbox("Beim Start nach einem neueren Stand suchen (nur Hinweis, nichts wird installiert)") \
            .bind_value(es, "update_pruefen").on_value_change(lambda e: ES.speichern(es))
        hinweis("Dafür fragt das Programm bei GitHub nach der neuesten Veröffentlichung. Es werden keine Daten von dir gesendet.")

    # ---------------- Einstellungen
    def seite_einstellungen(self):
        es = ES.laden()

        def sp(_=None):
            ES.speichern(es)
        with ui.scroll_area().style(f"height:{HOEHE}"):
            with ui.column().classes("gap-3").style("width:720px"):
                with karte("DWG-Ausgabe", AKZENT):
                    hinweis("Welche Formate ausgegeben werden (DXF, DWG, PDF, SVG; IFC, GLB, OBJ …), stellst du je Projekt unter "
                            "Einstellungen → Dateiformate ein.")
                    from .. import dwg
                    gef = dwg.finden(es.get("oda_pfad", ""))
                    hinweis(f"ODA File Converter: {gef} – DWG mit vollen Farben." if gef else
                            "ODA File Converter nicht gefunden (optional, kostenlos bei opendesign.com). Ohne ihn schreibt das "
                            "Programm DWG selbst im Format R2000: Farben werden auf AutoCAD-Standardfarben gerundet, Transparenz "
                            "entfällt. Für volle Farben DXF wählen (Archicad öffnet DXF direkt) oder den ODA File Converter installieren.")
                    feld_pfad("Pfad zum ODA File Converter (leer = automatisch suchen)", es, "oda_pfad",
                              typen=("Programm (*.exe;*)",))
                    ui.button("Speichern", icon="save", on_click=sp).props("flat dense")
                with karte("Projekte", OCKER, offen=False):
                    feld_pfad("Standard-Projektordner für neue Projekte", es, "projektordner", art="ordner")
                    ui.button("Speichern", icon="save", on_click=sp).props("flat dense")
                with karte("Programm-Update", AKZENT, offen=False):
                    self._update_karte()
                with karte("Weiteres", SALBEI, offen=False):
                    ui.checkbox("kleine Überraschungen in der Oberfläche zulassen").bind_value(es, "spielereien").on_value_change(sp)
                    from . import assistent
                    ass = es.setdefault("assistent", {})
                    ass.setdefault("an", True)
                    ass.setdefault("gesehen", [])

                    def ass_an(e):
                        ass["an"] = bool(e.value)
                        sp()
                        if assistent._A.get("figur") is not None:
                            assistent._A["figur"].classes(remove="assistent-still") if e.value else assistent.ausschalten()
                    ui.checkbox("Zirkel Zacharias als Assistent: meldet sich mit kurzen Tipps (jeder Tipp nur einmal)", value=bool(ass["an"]),
                                on_change=ass_an)
                    ui.button("Tipps wieder von vorn zeigen", on_click=lambda: (ass["gesehen"].clear(), sp(), ui.notify("Fertig"))) \
                        .props("flat dense no-caps")
                with karte("Daten und Netzwerk", INK, offen=False):
                    hinweis("Heruntergeladene Geodaten werden im Ordner ~/.ifcmap/cache gesammelt und für alle Projekte weiterverwendet. "
                            "Bei SSL-Fehlern im Uni-Netz: Einstellungen → Weitere Optionen → Netzwerk im jeweiligen Projekt.")
                    cache = os.path.join(os.path.expanduser("~"), ".ifcmap", "cache")
                    n = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(cache) for f in fs) if os.path.isdir(cache) else 0
                    hinweis(f"Zwischenspeicher: {n / 1e6:.0f} MB")
