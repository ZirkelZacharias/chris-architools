"""Seite „Gebiet“: Mittelpunkt, Rahmen (Umgebung und Modell), Maßstab, Einsatz – mit gemeinsamer Karte."""
import copy
import math
import os

from nicegui import run, ui

from .stil import (AKZENT, GRAU, INK, MASSSTAEBE, OCKER, SALBEI, SCHIEFER, TERRA, WASSERZEICHEN, ausgrauen, en_zu_ll,
                   feld_pfad, hinweis, karte, ll_zu_en, mm_text, HOEHE)

KARTENMODI = {"mitte": "Mittelpunkt setzen", "drehen": "Ausrichten", "flurstueck": "Flurstücke wählen",
              "schnitt": "Schnittlinie"}


class Gebiet:
    def __init__(self, proj, speichern=None):
        self.p = proj
        self.cfg = proj["modell"]
        self.speichern = speichern or (lambda: None)
        self.flurst = []
        self._sync_an = False

    def _karte_massstab(self):
        cfg, geb = self.cfg, self.cfg["gebiet"]
        with karte("Modell: Maßstab und Rahmen", TERRA):
            with ui.row().classes("gap-2 items-end"):
                self.f_s = ui.select(MASSSTAEBE, label="Maßstab", value=cfg["massstab"], new_value_mode="add-unique",
                                     with_input=True).classes("w-36") \
                    .tooltip("Gängige Maßstäbe – ein anderer lässt sich eintippen (z. B. 750)")
                self.f_dreh = ui.number("Drehung °", value=geb.get("drehung_grad", 0), step=1, format="%.1f") \
                    .classes("w-28").tooltip("Rahmen im Uhrzeigersinn um den Mittelpunkt drehen – oder in der Karte "
                                             "„Ausrichten“ wählen und klicken, wohin die Oberkante zeigen soll")
                ui.button("nach Norden", icon="navigation", on_click=lambda: self._nach_norden()).props("flat dense no-caps") \
                    .tooltip("Rahmen so drehen, dass die Oberkante nach wahrem Norden zeigt (wie die Karte). Ohne Drehung liegt "
                             "der Rahmen im UTM-Gitter – das ist in Berlin rund 1,2° gegen Nord gedreht.")
            with ui.row().classes("gap-2 items-end"):
                ui.label("Modell (cm)").classes("w-24 text-caption")
                self.f_cmb = ui.number("Breite", value=geb["breite_cm"], format="%.1f", step=1).classes("w-28")
                self.f_cmh = ui.number("Tiefe", value=geb["hoehe_cm"], format="%.1f", step=1).classes("w-28")
            with ui.row().classes("gap-2 items-end"):
                ui.label("Real (m)").classes("w-24 text-caption")
                s0 = float(cfg["massstab"])
                self.f_mb = ui.number("Breite", value=geb["breite_cm"] * s0 / 100, format="%.0f", step=10).classes("w-28")
                self.f_mh = ui.number("Tiefe", value=geb["hoehe_cm"] * s0 / 100, format="%.0f", step=10).classes("w-28")
            hinweis("Der Maßstab bleibt, wie gewählt; Modell- und Realgröße rechnen sich gegenseitig um.")
            self._sync_an = False
            self.f_s.on_value_change(lambda e: self._sync("s", e.value))
            self.f_cmb.on_value_change(lambda e: self._sync("cmb", e.value))
            self.f_cmh.on_value_change(lambda e: self._sync("cmh", e.value))
            self.f_mb.on_value_change(lambda e: self._sync("mb", e.value))
            self.f_mh.on_value_change(lambda e: self._sync("mh", e.value))
            self.f_dreh.on_value_change(lambda e: self._drehung(e.value))
            self.lbl_rahmen = ui.label("").classes("text-body2").style(f"color:{AKZENT}")
            with ui.row().classes("gap-2 items-end"):
                ui.number("Überhöhung", step=0.5, min=1).bind_value(cfg["gelaende"], "ueberhoehung").classes("w-28") \
                    .tooltip("1 = maßstäblich; 2 = Gelände doppelt so hoch (Gebäude bleiben maßstäblich)")
                ui.number("Sockelhöhe m ü. NHN").bind_value(cfg["gelaende"], "basis_hoehe_m").classes("w-44") \
                    .tooltip("Welche Geländehöhe der Oberkante der Grundplatte entspricht. Leer = automatisch: "
                             "tiefster Punkt im Rahmen, auf volle Meter abgerundet. Ein höherer Wert spart Schichten – "
                             "Gelände darunter wird flach. Nützlich, wenn mehrere Modelle aneinanderpassen sollen.")
            hinweis("Sockelhöhe leer lassen = automatisch (tiefster Punkt im Rahmen).")

    def _karte_einsatz(self):
        ec = self.cfg["einsatz"]
        ec.setdefault("auswahl", "mitte")
        ec.setdefault("polygone_en", [])
        with karte("Modell: Projektgrundstück als Einsatz", TERRA, offen=False):
            cb = ui.checkbox("Grundstück als herausnehmbaren Einsatz ausgeben").bind_value(ec, "aktiv")
            with ui.column().classes("w-full gap-1") as inhalt:
                ui.radio({"mitte": "Flurstück unter dem Mittelpunkt",
                          "eigen": "eigene Auswahl in der Karte (Flurstücke anklicken oder Polygon zeichnen)"}) \
                    .bind_value(ec, "auswahl").props("dense")
                with ui.row().classes("gap-2 items-center"):
                    ui.button("Flurstücke laden", icon="download", on_click=self._flurstuecke_laden).props("flat dense") \
                        .tooltip("Flurstücke im Rahmen laden, danach in der Karte „Flurstücke wählen“ und anklicken")
                    ui.button("Auswahl leeren", icon="clear", on_click=self._auswahl_leeren).props("flat dense")
                    self.lbl_auswahl = hinweis("")
                hinweis("Polygon zeichnen: Werkzeug oben links in der Karte (Fünfeck bzw. Rechteck).")
                feld_pfad("Flurstücke als Datei (nur bei eigenen Dateien)", ec, "flurstuecke_datei",
                          typen=("Vektordaten (*.gpkg;*.shp;*.geojson)",))
                with ui.row().classes("gap-2"):
                    ui.number("Exemplare", min=1, step=1).bind_value(ec, "exemplare").classes("w-28")
                    ui.number("Spiel mm", step=0.1).bind_value(ec, "spiel_mm").classes("w-28")
                    ui.select({"drucken": "mitdrucken", "umriss": "nur Umriss ritzen (für Entwürfe)"},
                              label="Gebäude darauf").bind_value(ec, "gebaeude").classes("w-60")
            ausgrauen(inhalt, cb)
        self._auswahl_text()

    def _kartenbereich(self):
        geb = self.cfg["gebiet"]
        with ui.column().classes("w-full h-full no-wrap gap-1"):
            with ui.row().classes("w-full items-center gap-2"):
                hinweis("Klick in die Karte:")
                self.modus = ui.toggle(KARTENMODI, value="mitte").props("dense no-caps size=sm")
                ui.space()
                hinweis("Polygon zeichnen: Werkzeug links oben")
            with ui.element("div").classes("w-full relative").style("flex:1 1 auto; min-height:300px"):
                lat, lon = en_zu_ll(*geb["mitte_en"])
                self.karte = ui.leaflet(center=(lat, lon), zoom=self._zoom(), hide_drawn_items=True,
                                        draw_control={"draw": {"polygon": True, "rectangle": True, "marker": False,
                                                               "circlemarker": False, "polyline": False, "circle": False},
                                                      "edit": {"edit": False, "remove": False}}) \
                    .classes("w-full h-full absolute-full")
                ui.html(f'<div class="stempel">{WASSERZEICHEN.upper()}</div>')
            self.karte.on("map-click", self._karte_klick)
            self.karte.on("draw:created", self._gezeichnet)
            self.marker = self.karte.marker(latlng=(lat, lon))
            self.rahmen_layer = None
            self.grund_layer = None
            self.flurst_layer = None

    def _mitte_text(self):
        e, n = self.cfg["gebiet"]["mitte_en"]
        lat, lon = en_zu_ll(e, n)
        self.inp_mitte.value = f"{lat:.6f}, {lon:.6f}"

    def _mitte_eingabe(self):
        from ..modell.ifcmap_adapter import _mitte
        try:
            latlon, en = _mitte(self.inp_mitte.value)
        except Exception:
            ui.notify("Mittelpunkt: zwei Zahlen, z. B. 52.5785, 13.4309 oder 393676 5826540", type="warning")
            return
        if en is None:
            en = ll_zu_en(*latlon)
        self.cfg["gebiet"]["mitte_en"] = list(en)
        lat, lon = en_zu_ll(*en)
        if hasattr(self, "marker"):
            self.marker.move(lat, lon)
            self.karte.set_center((lat, lon))



    def _karte_klick(self, e):
        ll = e.args.get("latlng") or {}
        if "lat" not in ll:
            return
        en = ll_zu_en(ll["lat"], ll["lng"])
        modus = self.modus.value
        if modus == "drehen":
            ce, cn = self.cfg["gebiet"]["mitte_en"]
            winkel = math.degrees(math.atan2(en[0] - ce, en[1] - cn))
            self.f_dreh.value = round(winkel, 1)
        elif modus == "flurstueck":
            self._flurstueck_klick(en)
        elif modus == "schnitt":
            self._schnitt_punkt(en)
        else:
            self.cfg["gebiet"]["mitte_en"] = list(en)
            self.marker.move(ll["lat"], ll["lng"])
            self._mitte_text()
            self._rahmen()


    def _drehung(self, wert):
        try:
            w = float(wert or 0)
        except (TypeError, ValueError):
            return
        w = ((w + 180) % 360) - 180
        self.cfg["gebiet"]["drehung_grad"] = w
        self._rahmen()

    def _sync(self, feld, wert):
        """Der Maßstab bleibt, wie er gewählt ist; Modellgröße (cm) und reale Größe (m) rechnen sich gegenseitig um."""
        if self._sync_an:
            return
        try:
            w = float(str(wert).replace("1:", "").replace(",", ".").strip())
        except (TypeError, ValueError):
            return
        if w <= 0:
            return
        g, cfg = self.cfg["gebiet"], self.cfg
        if feld == "s":
            cfg["massstab"] = int(w) if w == int(w) else w
        s = float(cfg["massstab"])
        if feld == "cmb":
            g["breite_cm"] = w
        elif feld == "cmh":
            g["hoehe_cm"] = w
        elif feld == "mb":
            g["breite_cm"] = round(w * 100 / s, 2)
        elif feld == "mh":
            g["hoehe_cm"] = round(w * 100 / s, 2)
        self._sync_an = True
        try:
            if feld != "cmb":
                self.f_cmb.value = g["breite_cm"]
            if feld != "cmh":
                self.f_cmh.value = g["hoehe_cm"]
            if feld != "mb":
                self.f_mb.value = round(g["breite_cm"] * s / 100, 1)
            if feld != "mh":
                self.f_mh.value = round(g["hoehe_cm"] * s / 100, 1)
        finally:
            self._sync_an = False
        self._rahmen()



    def _zoom(self):
        """Kartenzoom so, dass der Rahmen gut ins Bild passt."""
        b, h = self._rahmen_m()
        lat = en_zu_ll(*self.cfg["gebiet"]["mitte_en"])[0]
        mpp = max(b, h, 50.0) / 450.0
        return int(max(10, min(19, math.log2(156543.03 * math.cos(math.radians(lat)) / mpp))))

    def _rahmen_m(self):
        g = self.cfg["gebiet"]
        s = float(self.cfg.get("massstab") or 500)
        return float(g.get("breite_cm") or 80) * s / 100.0, float(g.get("hoehe_cm") or 50) * s / 100.0

    def _rahmen(self):
        if not hasattr(self, "karte"):
            return
        from ..modell.geomutil import rahmen_polygon
        e, n = self.cfg["gebiet"]["mitte_en"]
        b, h = self._rahmen_m()
        d = float(self.cfg["gebiet"].get("drehung_grad") or 0)
        poly = rahmen_polygon(e, n, b, h, d)
        ecken = [list(en_zu_ll(x, y)) for x, y in list(poly.exterior.coords)[:-1]]
        oben = [list(en_zu_ll(x, y)) for x, y in list(poly.exterior.coords)[2:4]]
        if self.rahmen_layer is not None:
            for lay in self.rahmen_layer:
                self.karte.remove_layer(lay)
        modell_an = self.p["ausgaben"].get("laser") or self.p["ausgaben"].get("druck")
        self.rahmen_layer = [] if not modell_an else [
            self.karte.generic_layer(name="polygon", args=[ecken, {"color": TERRA, "weight": 2, "fillOpacity": 0.06}]),
            self.karte.generic_layer(name="polyline", args=[oben, {"color": TERRA, "weight": 5, "opacity": 0.8}])]
        self.lbl_rahmen.text = (f"1:{float(self.cfg['massstab']):g}  ·  {b:.0f} × {h:.0f} m real  ·  "
                                f"{mm_text(self.cfg['gebiet']['breite_cm'])} × {mm_text(self.cfg['gebiet']['hoehe_cm'])} cm Modell"
                                + (f"  ·  {d:g}° gedreht" if d else "") + "  (dicke Linie = Oberkante)")
        self._umgebung_rahmen()
        self._schnitt_zeichnen()
        x0, y0, x1, y1 = poly.bounds
        self.cfg["ausschnitt"] = {"xmin": x0, "ymin": y0, "xmax": x1, "ymax": y1}



    def _nach_norden(self):
        from .stil import konvergenz
        e, n = self.cfg["gebiet"]["mitte_en"]
        self.f_dreh.value = round(-konvergenz(e, n), 2)

    def _schnitt_punkt(self, en):
        """Erster Klick = Anfang, zweiter Klick = Ende der Schnittlinie."""
        pts = getattr(self, "_schnitt_pkt", [])
        pts.append([round(en[0], 2), round(en[1], 2)])
        if len(pts) >= 2:
            self.p["schnitt"]["linie_en"] = [pts[0], pts[1]]
            pts = []
            ui.notify("Schnittlinie gesetzt", type="positive")
        else:
            ui.notify("Anfangspunkt gesetzt – jetzt den Endpunkt anklicken", type="info")
        self._schnitt_pkt = pts
        self._schnitt_zeichnen()

    def _schnitt_zeichnen(self):
        if getattr(self, "schnitt_layer", None) is not None:
            self.karte.remove_layer(self.schnitt_layer)
            self.schnitt_layer = None
        l = (self.p["schnitt"] or {}).get("linie_en")
        if l and self.p["ausgaben"].get("schnitt"):
            ll = [list(en_zu_ll(x, y)) for x, y in l]
            self.schnitt_layer = self.karte.generic_layer(name="polyline", args=[ll, {"color": "#c8643b", "weight": 4, "dashArray": "10 6"}])

    def _umgebung_rahmen(self):
        """Rechteck der Umgebung (IFC/Pläne) und Nahbereich in der Karte (blau)."""
        if getattr(self, "umg_layer", None):
            for lay in self.umg_layer:
                self.karte.remove_layer(lay)
        self.umg_layer = []
        u = self.p["umgebung"]
        if not any(self.p["ausgaben"].get(k) for k in ("ifc", "lageplan", "schwarzplan", "info_dwg")):
            return
        e, n = self.cfg["gebiet"]["mitte_en"]
        for b, h, farbe, w, fo in ((float(u.get("breite") or 0), float(u.get("hoehe") or 0), AKZENT, 2, 0.04),
                                   (float(u.get("nah_breite") or 0), float(u.get("nah_hoehe") or 0), SCHIEFER, 1, 0.0)):
            if b > 0 and h > 0:
                ecken = [list(en_zu_ll(x, y)) for x, y in ((e - b / 2, n - h / 2), (e + b / 2, n - h / 2),
                                                           (e + b / 2, n + h / 2), (e - b / 2, n + h / 2))]
                self.umg_layer.append(self.karte.generic_layer(
                    name="polygon", args=[ecken, {"color": farbe, "weight": w, "fillOpacity": fo, "dashArray": "6 4" if w == 1 else None}]))

    def _karte_mitte(self):
        with karte("Mittelpunkt", AKZENT):
            with ui.row().classes("w-full items-end gap-2 no-wrap"):
                self.inp_mitte = ui.input("Mittelpunkt: Breite, Länge (Google Maps) oder Ost Nord").classes("grow")
                self.inp_mitte.on("keydown.enter", lambda: self._mitte_eingabe())
                self.inp_mitte.on("blur", lambda: self._mitte_eingabe())
                ui.button(icon="my_location", on_click=lambda: self._mitte_eingabe()).props("flat dense round") \
                    .tooltip("Mittelpunkt übernehmen")
            self._mitte_text()
            hinweis("Gilt für alle Ausgaben. In der Karte klicken setzt den Mittelpunkt ebenfalls.")

    def _karte_umgebung(self):
        u = self.p["umgebung"]
        with karte("Umgebung (IFC, Pläne): Größe", SCHIEFER) as k:
            with ui.row().classes("gap-2 items-end"):
                ui.label("Gebiet (m)").classes("w-24 text-caption")
                ui.number("Ost–West", min=50, step=50).bind_value(u, "breite").classes("w-28") \
                    .on_value_change(lambda e: self._rahmen())
                ui.number("Nord–Süd", min=50, step=50).bind_value(u, "hoehe").classes("w-28") \
                    .on_value_change(lambda e: self._rahmen())
            with ui.row().classes("gap-2 items-end"):
                ui.label("Nahbereich (m)").classes("w-24 text-caption")
                ui.number("Ost–West", min=20, step=50).bind_value(u, "nah_breite").classes("w-28") \
                    .on_value_change(lambda e: self._rahmen())
                ui.number("Nord–Süd", min=20, step=50).bind_value(u, "nah_hoehe").classes("w-28") \
                    .on_value_change(lambda e: self._rahmen())
            with ui.row().classes("gap-2 items-end"):
                ui.label("Mittelbereich (m)").classes("w-24 text-caption")
                ui.number("Ost–West", min=0, step=50).bind_value(u, "mittel_breite").classes("w-28")
                ui.number("Nord–Süd", min=0, step=50).bind_value(u, "mittel_hoehe").classes("w-28")
            hinweis("Blau durchgezogen = Gebiet, blau gestrichelt = Nahbereich (feines Gelände, Dachformen, Bäume). Mittelbereich "
                    "(0 = aus): optionaler dritter Bereich dazwischen. Die Rechtecke liegen im UTM-Gitter (so wie in Archicad mit "
                    "Koordinaten); die Karte ist nach wahrem Norden ausgerichtet – darum wirken sie etwa 1,2° schief.")
        return k

    def seite(self):
        """Linke Spalte mit den Karten, rechts die Karte."""
        ausg = self.p["ausgaben"]
        with ui.row().classes("w-full no-wrap gap-4").style(f"height:{HOEHE}"):
            links = ui.scroll_area().classes("h-full").style("width:560px; min-width:480px")
            rechts = ui.column().classes("grow h-full no-wrap gap-1").style("min-width:0")
        with links:
            with ui.column().classes("w-full gap-3 pr-3"):
                self._karte_mitte()
                umg = ui.column().classes("w-full")
                with umg:
                    self._karte_umgebung()
                mod = ui.column().classes("w-full gap-3")
                with mod:
                    self._karte_massstab()
                    self._karte_einsatz()

                def sichtbar():
                    umg.set_visibility(any(ausg.get(k) for k in ("ifc", "lageplan", "schwarzplan", "info_dwg")))
                    mod.set_visibility(bool(ausg.get("laser") or ausg.get("druck")))
                    self._rahmen()
                self._sichtbar = sichtbar
                ui.timer(1.0, lambda: self._pruefen(sichtbar))
        with rechts:
            self._kartenbereich()
        ui.timer(0.5, self._rahmen, once=True)
        ui.timer(0.3, sichtbar, once=True)

    def _pruefen(self, sichtbar):
        z = (tuple(bool(self.p["ausgaben"].get(k)) for k in self.p["ausgaben"]),)
        if z != getattr(self, "_zust", None):
            self._zust = z
            sichtbar()

    def _auswahl_text(self):
        ec = self.cfg["einsatz"]
        n = len(ec.get("polygone_en") or [])
        if hasattr(self, "lbl_auswahl"):
            self.lbl_auswahl.text = f"{n} Fläche{'n' if n != 1 else ''} gewählt" if n else "noch nichts gewählt"
        self._auswahl_zeichnen()

    def _auswahl_zeichnen(self):
        if not hasattr(self, "karte"):
            return
        if self.grund_layer is not None:
            self.karte.remove_layer(self.grund_layer)
            self.grund_layer = None
        pg = self.cfg["einsatz"].get("polygone_en") or []
        if pg:
            ll = [[list(en_zu_ll(x, y)) for x, y in r] for r in pg]
            self.grund_layer = self.karte.generic_layer(
                name="polygon", args=[ll, {"color": SCHIEFER, "weight": 2, "fillOpacity": 0.3}])

    def _gezeichnet(self, e):
        lay = (e.args or {}).get("layer") or {}
        ll = lay.get("_latlngs")
        if not ll:
            return
        while ll and isinstance(ll[0], list):
            ll = ll[0]
        ring = [list(ll_zu_en(p["lat"], p["lng"])) for p in ll if "lat" in p]
        if len(ring) < 3:
            return
        ec = self.cfg["einsatz"]
        ec.setdefault("polygone_en", []).append(ring)
        ec["auswahl"], ec["aktiv"] = "eigen", True
        self._auswahl_text()
        ui.notify("Fläche zum Einsatz hinzugefügt", type="positive")

    def _auswahl_leeren(self):
        self.cfg["einsatz"]["polygone_en"] = []
        self._auswahl_text()

    async def _flurstuecke_laden(self):
        from ..modell.geomutil import rahmen_polygon
        cfg = self.cfg
        e, n = cfg["gebiet"]["mitte_en"]
        b, h = self._rahmen_m()
        poly = rahmen_polygon(e, n, b, h, float(cfg["gebiet"].get("drehung_grad") or 0))
        bb = poly.bounds
        ui.notify("Flurstücke werden geladen …")

        def laden():
            if cfg.get("quelle") == "dateien":
                from ..modell import geo_io as G
                pfad = cfg["einsatz"].get("flurstuecke_datei")
                if not pfad:
                    raise ValueError("Bei eigenen Dateien bitte eine Flurstücks-Datei angeben")
                return [g for g, _ in G.read_vector(pfad, "", bb, lambda s: None) if "Polygon" in g.geom_type]
            from ..modell.ifcmap_adapter import kern
            K = kern(cfg)
            nz = cfg.get("netz", {})
            obj = K.wfs_laden(K.WFS_ALKIS, "alkis:flurstuecke", bb, nz.get("cafile", ""), nz.get("unsicher", False),
                              lambda s: None)
            if not obj:
                raise ValueError("ALKIS-Flurstücke nicht erreichbar (Netz/SSL prüfen)")
            return [g for g, _ in K.geojson_features(obj, "", 25833) if "Polygon" in g.geom_type]
        try:
            fl = await run.io_bound(laden)
        except Exception as ex:
            ui.notify(str(ex), type="negative")
            return
        out = []
        for g in fl:
            for p in getattr(g, "geoms", [g]):
                if p.intersects(poly):
                    out.append(p)
        self.flurst = out
        if self.flurst_layer is not None:
            self.karte.remove_layer(self.flurst_layer)
        ll = [[list(en_zu_ll(x, y)) for x, y in p.exterior.coords] for p in out]
        self.flurst_layer = self.karte.generic_layer(
            name="polygon", args=[ll, {"color": "#555", "weight": 1, "fillOpacity": 0.0, "interactive": False}])
        self.modus.value = "flurstueck"
        ui.notify(f"{len(out)} Flurstücke geladen – zum Wählen anklicken", type="positive")

    def _flurstueck_klick(self, en):
        from shapely.geometry import Point
        pt = Point(*en)
        tr = [p for p in self.flurst if p.contains(pt)]
        if not tr:
            ui.notify("Hier ist kein geladenes Flurstück – erst „Flurstücke laden“ (Karte 7)", type="info")
            return
        p = min(tr, key=lambda x: x.area)
        ring = [[round(x, 2), round(y, 2)] for x, y in p.exterior.coords]
        ec = self.cfg["einsatz"]
        lst = ec.setdefault("polygone_en", [])
        if ring in lst:
            lst.remove(ring)
        else:
            lst.append(ring)
        ec["auswahl"], ec["aktiv"] = "eigen", True
        self._auswahl_text()