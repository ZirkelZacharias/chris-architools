"""Werkzeuge: Auto-Lasercut-Layout, Auto-3D-Druck-Layout, Materialbibliothek, Einstellungen."""
import copy
import os

from nicegui import ui

from .. import einstellungen as ES
from ..modell import bibliothek as BIB
from .ergebnis import ergebnis_zeigen
from .stil import (AKZENT, FARBE_DRUCK, GRAU, HOEHE, INK, LINIE, MASSSTAEBE, OCKER, SALBEI, SCHIEFER, TERRA, Lauf, feld_pfad, hinweis,
                   karte, mm_text, oeffnen, waehlen)

WERKZEUG_STANDARD = {
    "layout": {"dateien": [], "einheit": "mm", "massstab": 1, "anzahl": 1, "unbekannt": "schneiden",
               "ausgabe_ordner": "", "name": "layout"},
    "druck3d": {"dateien": [], "einheit": "m", "massstab": 500, "modus": "massiv", "zusammenfassen": False,
                "min_wand_mm": 1.2, "ausgabe_ordner": "", "name": "druck"},
    "cadlaser": {"dateien": [], "einheit": "m", "massstab": 200, "modus": "flaeche", "umwandlung": "bauteile",
                 "winkel": 3.0, "ebenheit_mm": 0.3, "min_flaeche_mm2": 20.0, "min_breite_mm": 2.0, "lasche_mm": 4.0, "beschriften": True,
                 "anzahl": 1, "ausgabe_ordner": "", "name": "cad",
                 "materialien": [], "gruppen_wahl": {}, "muster": {}, "material_gravur": True},   # Standard: modell/cad_lasercut.STANDARD
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
                self._zusatz_layout(w)
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

    def _zusatz_layout(self, w):
        """Karten der Zusatzmodule im Lasercut-Layout (z. B. „Rasterlaser-Bild einpassen“)"""
        from types import SimpleNamespace
        from .. import zusatz as _z
        from .stil import TERRA, ausgrauen
        h = SimpleNamespace(karte=karte, hinweis=hinweis, feld_pfad=feld_pfad, ausgrauen=ausgrauen, TERRA=TERRA, OCKER=OCKER,
                            SCHIEFER=SCHIEFER, SALBEI=SALBEI, GRAU=GRAU, AKZENT=AKZENT, waehlen=waehlen)
        _z.rufe("gui_layout", ui, w, h)

    async def _layout_start(self):
        from .. import zusatz as _z
        from ..modell import layout as LY
        w = copy.deepcopy(self.cfg["werkzeuge"]["layout"])
        zus = any(_z.rufe("layout_hat_teile", w))
        if not w["dateien"] and not zus:
            ui.notify("Bitte Dateien angeben", type="warning")
            return
        if not w.get("ausgabe_ordner"):
            w["ausgabe_ordner"] = os.path.join(os.path.dirname(w["dateien"][0]), "lasercut") if w["dateien"] else \
                os.path.join(os.path.expanduser("~"), "ZachariasTools_Lasercut")
        cfg = copy.deepcopy(self.cfg)
        r = await self.lauf_l.starten(lambda w, cfg, log, prog: LY.layout(w, cfg, log), w, cfg)
        if r:
            ergebnis_zeigen(self.erg_l, r, "Lasercut-Layout")

    def seite_cad(self):
        """CAD zu Lasercut: 3D-Entwurf in ebene Laserteile zerlegen, mit 3D-Vorschau und Kostenschätzung"""
        w = self.cfg["werkzeuge"]["cadlaser"]
        with ui.row().classes("w-full no-wrap gap-4").style(f"height:{HOEHE}"):
            links = ui.scroll_area().classes("h-full").style("width:600px; min-width:520px")
            rechts = ui.column().classes("grow h-full no-wrap").style("min-width:0")
        with links:
            with ui.column().classes("w-full gap-3 pr-3"):
                with karte("3D-Entwurf", AKZENT):
                    hinweis("Der Entwurf aus ArchiCAD oder einem anderen CAD-Programm als IFC, OBJ, STL, 3MF, PLY, GLB oder DXF "
                            "(mit 3D-Flächen). Das Programm erkennt die ebenen Flächen selbst und macht Laserteile daraus.")
                    feld_pfad("Dateien (mehrere mit ;)", w, "dateien", mehrere=True,
                              typen=("3D (*.ifc;*.obj;*.stl;*.3mf;*.ply;*.glb;*.dxf)",))
                    with ui.row().classes("gap-2"):
                        ui.select(["m", "cm", "mm"], label="Einheit der Datei").bind_value(w, "einheit").classes("w-36") \
                            .tooltip("IFC ist immer in Metern; OBJ, STL … haben keine feste Einheit")
                        ui.select(MASSSTAEBE, label="Maßstab", new_value_mode="add-unique", with_input=True) \
                            .bind_value(w, "massstab").classes("w-32")
                        ui.number("Exemplare", min=1, step=1).bind_value(w, "anzahl").classes("w-28")
                    ui.select({"bauteile": "Bauteile aus IFC – Wände, Decken, Dach in echter Stärke (empfohlen)",
                               "massiv": "Außenform – Hülle mit Dach, ohne Innenräume (empfohlen für Massenmodelle)",
                               "original": "Bauteile einzeln – jede Fläche für sich (viele kleine Teile)"},
                              label="Umwandlung").bind_value(w, "umwandlung").classes("w-full") \
                        .tooltip("Bei allen Umwandlungen werden Gelände und andere unebene Flächen (Meshes) in Höhenschichten zerlegt.")
                bt_karte = ui.column().classes("w-full gap-3")
                bt_karte.bind_visibility_from(w, "umwandlung", value="bauteile")
                with bt_karte:
                    self._cad_bauteile_karten(w)
                with karte("Zerlegung in Laserteile", TERRA):
                    ui.select({"falt": "Faltmodell – Flächen mit Klebelaschen und Ritzlinien an den Kanten",
                               "flaeche": "Klebeflächen – jede Fläche einzeln, ohne Laschen (auf Stoß kleben)",
                               "stapel": "Schichten – waagerechte Scheiben in Materialstärke (Schichtenmodell)"},
                              label="Bauweise").bind_value(w, "modus").classes("w-full")
                    with ui.row().classes("gap-2"):
                        ui.number("Winkel °", min=0.1, max=45, step=0.5).bind_value(w, "winkel").classes("w-28") \
                            .tooltip("Flächen, die um höchstens so viel geknickt sind, gelten als eine ebene Fläche. "
                                     "Größer = weniger, aber leicht verzogene Teile (Kuppeln, runde Gebäude).")
                        ui.number("Ebenheit mm", min=0.05, step=0.05).bind_value(w, "ebenheit_mm").classes("w-32") \
                            .tooltip("So weit darf eine Fläche (im Modell) von der Ebene abweichen")
                        ui.number("Kleinste Fläche mm²", min=0, step=5).bind_value(w, "min_flaeche_mm2").classes("w-40") \
                            .tooltip("Kleinere Flächen werden weggelassen (Details, die sich nicht kleben lassen)")
                        ui.number("Lasche mm", min=1, step=0.5).bind_value(w, "lasche_mm").classes("w-28") \
                            .tooltip("Breite der Klebelaschen (nur Faltmodell)")
                    ui.checkbox("Teile mit ihrer Nummer beschriften (graviert)").bind_value(w, "beschriften")
                    hinweis("Wände stehen auf der Platte aufrecht (oben = oben), Boden und Dach liegen mit x nach rechts. "
                            "Die Plattenstärke wird bei den Kanten NICHT abgezogen – bei dünner Pappe unkritisch, bei 3 mm "
                            "Holz oder Acryl die Teile mit Gehrung oder kleiner Zugabe nachbearbeiten.")
                with karte("Material und Platte", OCKER):
                    self.me.material_format(self.cfg["laser"])
                with karte("Ausgabe", INK):
                    with ui.row().classes("w-full gap-2 items-end no-wrap"):
                        ui.input("Name").bind_value(w, "name").classes("w-40")
                        feld_pfad("Ausgabeordner", w, "ausgabe_ordner", art="ordner")
        with rechts:
            logel = ui.log(max_lines=1000).classes("w-full log-bild").style("height: 160px; font-size: 12px")
            with ui.scroll_area().classes("w-full").style("flex:1 1 auto"):
                self.erg_c = ui.column().classes("w-full pr-3")
            with ui.row().classes("items-center gap-2 pt-1"):
                knopf = ui.button("Zerlegen und Kosten schätzen", icon="content_cut", on_click=lambda: self._cad_start()) \
                    .props("unelevated size=lg").style(f"background:{AKZENT}!important")
                fs = ui.spinner(size="lg")
                fs.set_visibility(False)
        self.lauf_c = Lauf(logel, [knopf], fs)

    # ------------------------------------------------------------------ CAD zu Lasercut: Bauteile aus IFC
    def _cad_bauteile_karten(self, w):
        """Materialien anlegen, je Bauteilart an/aus und Material, Materialdarstellung (Rastergravur aus dem Zusatzmodul)"""
        from ..modell.cad_bauteile import GRUPPEN
        mats_bib = BIB.alle("materialien")
        w.setdefault("materialien", [])
        w.setdefault("gruppen_wahl", {})
        w.setdefault("muster", {})
        for g in GRUPPEN:
            w["gruppen_wahl"].setdefault(g, {"an": True, "material": 0})

        def mat_namen():
            lc = self.cfg["laser"]
            out = {0: f"1 · {lc.get('material', '')} {mm_text(float(lc.get('staerke_mm') or 2))} mm (wie unten)"}
            for i, m in enumerate(w["materialien"], 1):
                out[i] = f"{i + 1} · {m.get('sorte')} {mm_text(float(m.get('staerke_mm') or 1))} mm"
            return out

        with karte("Materialien", OCKER):
            hinweis("Material 1 ist das Material unter „Material und Platte“. Weitere hier anlegen – dann bekommt jede Bauteilart "
                    "ihr eigenes Material (eigene Platten, PDFs und Kosten; die Lagenzahl richtet sich nach dessen Stärke).")

            @ui.refreshable
            def liste():
                for i, m in enumerate(w["materialien"]):
                    with ui.row().classes("w-full items-end gap-2 no-wrap"):
                        ui.label(f"{i + 2}").classes("text-subtitle2").style("width:14px")
                        ui.select(list(mats_bib), label="Material").bind_value(m, "sorte").style("min-width:0; flex:1 1 0") \
                            .on_value_change(lambda e: (gruppen.refresh()))
                        ui.number("Stärke mm", min=0.1, max=10, step=0.1).bind_value(m, "staerke_mm").classes("w-28") \
                            .on_value_change(lambda e: (gruppen.refresh()))
                        ui.button(icon="delete", on_click=lambda i=i: (w["materialien"].pop(i), _nachher_loeschen(i))) \
                            .props("flat dense round").tooltip("Material entfernen")

            def _nachher_loeschen(i):
                for e in w["gruppen_wahl"].values():           # Bauteile mit diesem Material zurück auf Material 1
                    k = int(e.get("material", 0) or 0)
                    if k == i + 1:
                        e["material"] = 0
                    elif k > i + 1:
                        e["material"] = k - 1
                liste.refresh()
                gruppen.refresh()

            def neu():
                w["materialien"].append({"sorte": next(iter(mats_bib), "Graupappe"), "staerke_mm": 1.0})
                liste.refresh()
                gruppen.refresh()
            liste()
            ui.button("Material hinzufügen", icon="add", on_click=neu).props("outline dense no-caps")
        with karte("Bauteile: welche und aus welchem Material", TERRA):
            @ui.refreshable
            def gruppen():
                opts = mat_namen()
                for g, titel in GRUPPEN.items():
                    e = w["gruppen_wahl"][g]
                    if int(e.get("material", 0) or 0) not in opts:
                        e["material"] = 0
                    with ui.row().classes("w-full items-center gap-2 no-wrap"):
                        ui.checkbox(titel).bind_value(e, "an").style("width:190px; flex:0 0 190px")
                        ui.select(opts, label="Material").bind_value(e, "material").style("min-width:0; flex:1 1 0") \
                            .bind_enabled_from(e, "an")
            gruppen()
            hinweis("Wände, Decken, Dachflächen: echte Stärke ÷ Materialstärke = Lagen (gerundet, mind. 1); jede Lage ist ein Schnitt "
                    "durch das Bauteil, Öffnungen und Ecken stimmen. Das Dach ist abnehmbar (nicht festkleben). Gelände und Freiflächen "
                    "(Meshes) werden in Höhenschichten der Materialstärke zerlegt, unter Gebäuden ausgespart. Sichtbare Außenlagen "
                    "bekommen keine gravierte Teilenummer.")
        with karte("Materialdarstellung als Rastergravur", SALBEI):
            from .. import zusatz as ZU
            info = ZU.erstes("cad_muster") if ZU.hat("cad_muster") else None
            if not info:
                hinweis("Braucht das Zusatzmodul mit der Rastergravur (Fassadenmodul ab 1.10). Ohne Modul bleiben die Flächen ungraviert.")
                return
            ui.checkbox("Material aus dem IFC als Muster gravieren") \
                .bind_value(w, "material_gravur")
            hinweis("Maße aus echten Größen ÷ Maßstab (Ziegel 24 × 7,1 cm, Schalung 2,5 × 1,25 m …), zu feine Muster werden vergröbert. "
                    "Graviert wird nur Sichtbares: Außenlage von Wänden, Decken und Dach, beim Gelände der Ring, den die nächste "
                    "Schicht frei lässt.")
            tab = ui.column().classes("w-full gap-1")

            def zeigen(namen):
                tab.clear()
                with tab:
                    for n in namen:
                        w["muster"].setdefault(n, info["vorschlag"](n, None))
                        with ui.row().classes("w-full items-center gap-2 no-wrap"):
                            ui.label(n).classes("text-body2").style("width:190px; flex:0 0 190px; overflow:hidden; text-overflow:ellipsis")
                            ui.select(info["muster"], label="Muster").bind_value(w["muster"], n).style("min-width:0; flex:1 1 0")

            async def lesen():
                ifc = [p for p in (w.get("dateien") or []) if str(p).lower().endswith(".ifc")]
                if not ifc:
                    ui.notify("Erst eine IFC-Datei angeben", type="warning")
                    return
                from nicegui import run

                def namen():
                    import ifcopenshell
                    out = set()
                    for p in ifc:
                        f = ifcopenshell.open(p)
                        out |= {m.Name for m in f.by_type("IfcMaterial") if m.Name}
                    return sorted(out)
                try:
                    zeigen(await run.io_bound(namen))
                except Exception as e:
                    ui.notify(f"IFC nicht lesbar: {str(e)[:80]}", type="negative")
            ui.button("Materialien aus dem IFC lesen", icon="palette", on_click=lesen).props("outline dense no-caps")
            if w["muster"]:
                zeigen(sorted(w["muster"]))

    async def _cad_start(self):
        from ..modell import cad_lasercut as C
        w = copy.deepcopy(self.cfg["werkzeuge"]["cadlaser"])
        if not w["dateien"]:
            ui.notify("Bitte Dateien angeben", type="warning")
            return
        try:
            w["massstab"] = float(str(w["massstab"]).replace("1:", "").replace(",", "."))
        except ValueError:
            ui.notify("Maßstab als Zahl angeben", type="warning")
            return
        if not w.get("ausgabe_ordner"):
            w["ausgabe_ordner"] = os.path.join(os.path.dirname(w["dateien"][0]), "lasercut")
        cfg = copy.deepcopy(self.cfg)
        r = await self.lauf_c.starten(lambda w, cfg, log, prog: C.lasercut(w, cfg, log), w, cfg)
        if r:
            self._cad_ergebnis(r)

    def _cad_ergebnis(self, r):
        """Kostenschätzung, 3D-Ansicht (zusammengebaut / auseinandergezogen) und die üblichen Laser-Ergebnisse"""
        from .stil import szene3d
        bereich = self.erg_c
        bereich.clear()
        k = r.get("kosten") or {}
        eur = lambda v: f"{v:,.0f} €".replace(",", ".")
        with bereich:
            ui.label("CAD zu Lasercut").classes("text-h6")
            with ui.grid(columns=4).classes("w-full gap-1"):
                for wert, txt in ((eur(k.get("brutto", 0)), "Gesamt (Schätzung, brutto)"), (eur(k.get("material", 0)), "Material"),
                                  (eur(k.get("laser", 0)), f"Laser (ca. {r.get('laserzeit_min', 0):.0f} min)"),
                                  (f"{r['teile']} Teile / {r['platten']} Platten", r.get("material", ""))):
                    with ui.card().tight().classes("p-2"):
                        ui.label(wert).classes("text-subtitle1 text-weight-medium")
                        ui.label(txt).classes("text-caption").style(f"color:{GRAU}")
            hinweis("Nur geschätzt: Richtwerte aus der Bibliothek, keine Kalkulation und kein Angebot (Einzelheiten in der Kostenliste unten).")
            if len(r.get("materialien") or []) > 1:
                with ui.row().classes("items-center gap-3"):
                    for m in r["materialien"]:
                        ui.html(f'<span style="display:inline-block;width:12px;height:12px;background:{m["farbe"]};border:1px solid #999">'
                                f'</span> {m["sorte"]} {mm_text(m["t"])} mm: {m["teile"]} Teile, {m["platten"]} Platten')
            if r.get("vorschau_gruppen"):
                self._cad_vorschau_gruppen(r)
            elif r.get("vorschau_laser"):
                b, h, z = r["modell_b"], r["modell_h"], r.get("modell_z", 0)
                zeigen = {"zus": (r["vorschau_laser"], "Zusammengebaut"), "expl": (r.get("vorschau_explosion"), "Auseinandergezogen")}
                halter = {}

                def aufbauen(art):
                    halter["s"].clear()
                    pfad = zeigen[art][0]
                    if pfad:
                        with halter["s"]:
                            L = max(b, h, z)
                            szene3d([(pfad, r.get("material_farbe"))], L, L, hoehe=460, mitte=(b / 2, h / 2))
                with ui.row().classes("items-center gap-3 mt-2"):
                    ui.label("3D-Vorschau").classes("text-subtitle2")
                    ui.toggle({"zus": "Zusammengebaut", "expl": "Auseinandergezogen"}, value="zus",
                              on_change=lambda e: aufbauen(e.value)).props("dense no-caps")
                    hinweis("Platten in echter Materialstärke. Maus: drehen · rechte Taste: verschieben · Rad: zoomen")
                halter["s"] = ui.column().classes("w-full")
                aufbauen("zus")
            if r.get("dxf") and os.path.exists(r["dxf"]):
                ui.button("DXF aller Platten", icon="draw", on_click=lambda: oeffnen(os.path.dirname(r["dxf"]))).props("outline dense")
            unten = ui.column().classes("w-full")
        rest = {kk: v for kk, v in r.items() if not kk.startswith("vorschau")}
        ergebnis_zeigen(unten, rest, "Teile und Platten")

    def _cad_vorschau_gruppen(self, r):
        """3D-Vorschau je Bauteilgruppe: Gruppen ein/aus, Dach anheben, Platten mit ihrer Gravur"""
        from ..modell.cad_bauteile import GRUPPEN
        from .stil import url
        gl = {g: p for g, p in r["vorschau_gruppen"].items() if p and os.path.exists(p)}
        b, h, z = r["modell_b"], r["modell_h"], r.get("modell_z", 0)
        L_ = max(b, h, z, 50.0)
        objekte = {}
        with ui.row().classes("items-center gap-3 mt-2 w-full"):
            ui.label("3D-Vorschau").classes("text-subtitle2")
            for g in gl:
                ui.checkbox(GRUPPEN[g].split(" (")[0], value=True,
                            on_change=lambda e, g=g: objekte[g].visible(e.value) if g in objekte else None).props("dense")
            if "dach" in gl:
                ui.label("Dach anheben").classes("text-caption").style(f"color:{GRAU}")
                ui.slider(min=0, max=round(max(z, 40.0) * 1.2), value=0,
                          on_change=lambda e: objekte["dach"].move(0, 0, float(e.value)) if "dach" in objekte else None) \
                    .classes("w-40").props("dense label")
        hinweis("Platten in echter Materialstärke, Oberseite mit ihrer Gravur. Maus: drehen · rechte Taste: verschieben · Rad: zoomen")
        cam = ui.scene.perspective_camera(fov=45, near=max(0.05, L_ / 400), far=L_ * 40)
        with ui.scene(height=520, grid=False, background_color="#eef1f3", camera=cam).classes("w-full") as sc:
            sc.spot_light(distance=L_ * 20, intensity=0.15).move(L_, -L_, L_ * 2)
            for g, p in gl.items():
                objekte[g] = sc.gltf(url(p))
        sc.move_camera(x=b / 2 + L_ * 0.2, y=h / 2 - L_ * 1.0, z=L_ * 0.9, look_at_x=b / 2, look_at_y=h / 2, look_at_z=z / 3, duration=0)

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
        r = await self.lauf_d.starten(lambda w, cfg, log, prog: D.druckbar(w, cfg, log), w, cfg)
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
        hinweis(f"Installiert: Build {STAND}. Eine Update-Datei (ZachariasTools_Update_….zip) enthält nur geänderte und neue Dateien; "
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
        ui.checkbox("Beim Start nach einem neueren Build suchen (nur Hinweis, nichts wird installiert)") \
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
                with karte("Zusatzmodule (Plugins)", SCHIEFER, offen=False):
                    from .. import zusatz
                    liste = zusatz.liste()
                    if liste:
                        for n, name, ver, beschr, pfad in liste:
                            with ui.row().classes("items-start no-wrap gap-2"):
                                ui.icon("extension").style("color:#3d6a9e")
                                with ui.column().classes("gap-0"):
                                    ui.label(f"{name}" + (f"  ·  Version {ver}" if ver else "")).classes("text-weight-medium")
                                    if beschr:
                                        hinweis(beschr)
                                    hinweis(f"Ordner: {pfad}")
                    else:
                        hinweis("Keine Zusatzmodule installiert. Sie sind nicht Teil des öffentlichen Programms.")
                    hinweis("Zusatzmodule sind Ordner mit einer __init__.py. Sie liegen im Ordner „zusatz“ neben dem Ordner „architools“ "
                            "(portables Paket: ZachariasTools/programm/zusatz) oder in ~/.zacharias-tools/zusatz. "
                            "Nach dem Hineinkopieren das Programm neu starten. Ein fehlerhaftes Modul bricht nie einen Export ab.")
                with karte("Daten und Netzwerk", INK, offen=False):
                    hinweis("Heruntergeladene Geodaten werden im Ordner ~/.ifcmap/cache gesammelt und für alle Projekte weiterverwendet. "
                            "Bei SSL-Fehlern im Uni-Netz: Einstellungen → Weitere Optionen → Netzwerk im jeweiligen Projekt.")
                    cache = os.path.join(os.path.expanduser("~"), ".ifcmap", "cache")
                    n = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(cache) for f in fs) if os.path.isdir(cache) else 0
                    hinweis(f"Zwischenspeicher: {n / 1e6:.0f} MB")
