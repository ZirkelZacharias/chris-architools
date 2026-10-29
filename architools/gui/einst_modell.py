"""Einstellungen für Gelände-Lasercut und Gebäude-3D-Druck (Modellbau)."""
import copy
import os

from nicegui import ui

from ..modell import bibliothek as BIB
from ..modell.laser import EBENEN_STANDARD
from .stil import (AKTION_TEXT, AKZENT, GRAU, INK, MASSSTAEBE, OCKER, SALBEI, SCHIEFER, TERRA, ausgrauen, feld_pfad,
                   hinweis, mm_text)
from .stil import karte as _karte

_UNTER = {"an": False}


def karte(titel, farbe=AKZENT, offen=True):
    """Eigene Kachel – oder, innerhalb einer Sammel-Kachel (Gelände Lasercut), ein Unterabschnitt davon."""
    if _UNTER["an"]:
        return ui.expansion(titel, value=offen).classes("w-full").props("header-class=text-weight-medium dense") \
            .style(f"border-left:3px solid {farbe}; background:#fafbfb")
    return _karte(titel, farbe, offen)

BAUWEISE_TEXT = {"voll": "voll (jede Schicht ganz)", "steckrippen": "hohl mit Steckrippen",
                 "stuetzkloetze": "hohl mit Stützklötzen"}
IFCMAP_EBENEN = ["Strasse", "Weg_Platz", "Bahn", "Gleisachsen", "Gewaesser", "Wald", "Gehoelz", "Gruen",
                 "Brache_Unland", "Landwirtschaft", "Siedlung", "Baeume", "Flurstuecke", "ALKIS_Gebaeude",
                 "ALKIS_Bauwerke"]
ZUSATZ_EBENEN = {"oepnv": ("OEPNV", "ÖPNV (Tram-/Buslinien, Haltestellen)"),
                 "gewaesser": ("Gewaessernetz", "Gewässernetz (Achsen, Flächen)"),
                 "denkmal": ("Denkmal", "Denkmalkarte"),
                 "fnp": ("FNP", "Flächennutzungsplan"),
                 "radverkehr": ("Rad", "Radverkehrsnetz")}
EBENEN_NAMEN = {"Strasse": "Straßen", "Weg_Platz": "Wege / Plätze", "Bahn": "Bahnflächen", "Gleisachsen": "Gleisachsen",
                "Gewaesser": "Gewässer", "Wald": "Wald", "Gehoelz": "Gehölz", "Gruen": "Grünflächen",
                "Brache_Unland": "Brache / Unland", "Landwirtschaft": "Landwirtschaft", "Siedlung": "Siedlung",
                "Baeume": "Bäume", "Flurstuecke": "Flurstücksgrenzen", "ALKIS_Gebaeude": "ALKIS-Gebäudegrundrisse",
                "ALKIS_Bauwerke": "ALKIS-Bauwerke (Mauern, Brücken …)", "OEPNV": "ÖPNV", "Gewaessernetz": "Gewässernetz",
                "Denkmal": "Denkmalkarte", "FNP": "Flächennutzungsplan", "Rad": "Radverkehrsnetz"}


class ModellEinst:
    def __init__(self, proj):
        self.p = proj
        self.cfg = proj["modell"]

    def material_format(self, lc):
        mats = BIB.alle("materialien")
        if lc.get("material") not in mats and mats:
            lc["material"] = next(iter(mats))
        with ui.row().classes("w-full gap-2 items-end"):
            muster = ui.element("div").style("width:26px;height:26px;border-radius:6px;border:1px solid #999;margin-bottom:6px") \
                .tooltip("So sieht das Material in der Vorschau aus")
            sel_m = ui.select(list(mats), label="Material").bind_value(lc, "material").classes("min-w-[220px] grow")
            sel_s = ui.select([], label="Stärke mm", new_value_mode="add-unique", with_input=True) \
                .classes("w-40").tooltip("Standardstärke wählen oder eigene Stärke in mm eintippen (z. B. gemessen) und Enter")
        hw = hinweis("")
        lc["staerke_gemessen_mm"] = None

        def staerken():
            m = BIB.alle("materialien").get(lc.get("material"))
            opts = [float(x) for x in (m or {}).get("staerken", [])] or [2.0]
            st = float(lc.get("staerke_mm") or 0)
            if st not in opts:
                if st > 0 and getattr(staerken, "eigen", False):
                    opts = sorted(opts + [st])
                else:
                    st = opts[min(len(opts) - 1, 1)]
            lc["staerke_mm"] = st
            sel_s.options = {o: mm_text(o) for o in opts}
            sel_s.value = st
            sel_s.update()
            txt = []
            if m and m.get("max_mm") and st > float(m["max_mm"]) + 1e-6:
                txt.append(f"Achtung: Werkstatt lasert {lc['material']} nur bis {mm_text(m['max_mm'])} mm.")
            if m and m.get("hinweis"):
                txt.append(m["hinweis"])
            hw.text = " ".join(txt)

        def staerke_gewaehlt(e):
            try:
                v = float(str(e.value).replace(",", ".").replace("mm", "").strip())
            except (TypeError, ValueError):
                ui.notify("Stärke als Zahl in mm angeben", type="warning")
                return
            if v <= 0 or v > 20:
                ui.notify("Stärke zwischen 0 und 20 mm", type="warning")
                return
            lc["staerke_mm"] = v
            staerken.eigen = True
            if v != e.value:
                staerken()
        sel_s.on_value_change(staerke_gewaehlt)
        def muster_farbe(*_):
            muster.style(f"background:{BIB.farbe(lc.get('material'))}")
        sel_m.on_value_change(lambda e: (setattr(staerken, "eigen", False), staerken(), muster_farbe()))
        muster_farbe()
        staerken()
        fm = list(BIB.alle("laser")) + ["eigen"]
        with ui.row().classes("w-full gap-2 items-end"):
            sel_f = ui.select({k: (k if k != "eigen" else "eigenes Format") for k in fm}, label="Plattenformat") \
                .bind_value(lc, "format").classes("min-w-[240px] grow")
            ef = lc.setdefault("eigenes_format_mm", [694, 422])
            b = ui.number("Breite mm", value=ef[0]).classes("w-28")
            h = ui.number("Höhe mm", value=ef[1]).classes("w-28")
            b.on_value_change(lambda e: ef.__setitem__(0, e.value))
            h.on_value_change(lambda e: ef.__setitem__(1, e.value))
            b.bind_visibility_from(lc, "format", value="eigen")
            h.bind_visibility_from(lc, "format", value="eigen")
        frei = lambda f: f == "eigen"
        with ui.row().classes("w-full gap-2 items-end"):
            ui.number("Plattenrand mm", min=2, max=4, step=0.5).bind_value(lc, "rand_mm").classes("w-36") \
                .bind_enabled_from(lc, "format", backward=frei).tooltip("Werkstatt: 2–4 mm Abstand zum Plattenrand")
            ui.number("Abstand Teile mm", min=0.5, step=0.5).bind_value(lc, "abstand_mm").classes("w-36") \
                .bind_enabled_from(lc, "format", backward=frei)
            ui.select({1.0: "Standard (1 mm)", 0.5: "dicht (0,5 mm, langsam)", 2.0: "schnell (2 mm)"},
                      label="Nesting").bind_value(lc, "nesting_raster_mm").classes("w-44") \
                .bind_enabled_from(lc, "format", backward=frei)
        sperre = ui.label("Werkstatt-Laser: Rand, Abstand und Nesting sind auf die Werkstatt-Vorgaben festgelegt.") \
            .classes("text-caption").style(f"color:{GRAU}")
        sperre.bind_visibility_from(lc, "format", backward=lambda f: f != "eigen")

        def werkstatt(e=None):
            if lc.get("format") != "eigen":
                lc["rand_mm"] = BIB.WERKSTATT["rand_mm"]
                lc["abstand_mm"] = BIB.WERKSTATT["abstand_mm"]
                lc["nesting_raster_mm"] = BIB.WERKSTATT["nesting_raster_mm"]
        sel_f.on_value_change(werkstatt)
        werkstatt()

    def drucker(self, dc):
        with ui.row().classes("w-full gap-2 items-end"):
            ui.select(list(BIB.alle("drucker")) + ["eigen"], label="3D-Drucker").bind_value(dc, "geraet").classes("min-w-[220px]")
            ui.select(list(BIB.FILAMENTE), label="Filament").bind_value(dc, "filament").classes("w-28")
            e1 = ui.number("Bett B mm", value=dc["bett_mm"][0]).classes("w-28")
            e2 = ui.number("Bett T mm", value=dc["bett_mm"][1]).classes("w-28")
            e3 = ui.number("Höhe mm").bind_value(dc, "hoehe_mm").classes("w-28")
            e1.on_value_change(lambda e: dc["bett_mm"].__setitem__(0, e.value))
            e2.on_value_change(lambda e: dc["bett_mm"].__setitem__(1, e.value))
            for x in (e1, e2, e3):
                x.bind_visibility_from(dc, "geraet", value="eigen")

    def _karte_bauweise(self):
        g = self.cfg["gelaende"]
        hohl = lambda b: b != "voll"
        with karte("Bauweise (hohl oder voll)", SALBEI):
            ui.select(BAUWEISE_TEXT, label="Bauweise").bind_value(g, "bauweise").classes("w-full")
            with ui.row().classes("gap-2"):
                ui.number("Raster mm", step=10).bind_value(g, "rippen_abstand_mm").classes("w-28") \
                    .bind_enabled_from(g, "bauweise", backward=hohl).tooltip("Abstand der Steckrippen bzw. Klotzsäulen")
                ui.number("Auflagerand mm").bind_value(g, "auflage_rand_mm").classes("w-32") \
                    .bind_enabled_from(g, "bauweise", backward=hohl)
                ui.number("Hohl ab mm").bind_value(g, "min_hohl_mm").classes("w-28") \
                    .bind_enabled_from(g, "bauweise", backward=hohl).tooltip("Flachere Hohlräume bleiben voll")
                ui.number("Klotz mm").bind_value(g, "stuetze_mm").classes("w-24") \
                    .bind_enabled_from(g, "bauweise", backward=lambda v: v == "stuetzkloetze")
            with ui.row().classes("gap-2 items-center"):
                ui.checkbox("Passlöcher").bind_value(g, "passloecher")
                ui.number("Ø mm").bind_value(g, "passloch_d_mm").classes("w-20").bind_enabled_from(g, "passloecher")
                ui.number("Abstand mm", step=10).bind_value(g, "passloch_abstand_mm").classes("w-28") \
                    .bind_enabled_from(g, "passloecher")
                ui.number("Schrift mm").bind_value(g, "beschriftung_hoehe_mm").classes("w-24")

    GEB_MODI = {"druck": "3D-Druck (STL für den Drucker)",
                "stapel": "Stapelmodell (Schichten aus Pappe, Laser)",
                "flaeche": "Flächen zum Kleben (ohne Laschen, Laser)",
                "falt": "Faltmodell (mit Laschen, Laser)"}

    def _karte_gebaeude(self):
        g = self.cfg["gebaeude"]
        g.setdefault("modus", "druck")
        ist_druck = lambda m: m == "druck"
        ist_laser = lambda m: m != "druck"
        with karte("Gebäude im Modell (3D-Druck oder Laser) – alle Einstellungen", AKZENT):
            ui.select(self.GEB_MODI, label="Gebäude werden gebaut als").bind_value(g, "modus").classes("w-full")
            # --- Laserformen
            with ui.column().classes("w-full gap-1").bind_visibility_from(g, "modus", backward=ist_laser):
                hinweis("Die Laserteile liegen in wahrer Größe auf den Platten; jedes Teil trägt die Gebäudenummer und seine Teilenummer. "
                        "Bei Stapelmodell und Flächen entspricht jede Dachfläche ihrer wahren Form (keine Draufsicht).")
                mats = BIB.alle("materialien")
                with ui.row().classes("gap-2 items-end"):
                    g.setdefault("material", "")
                    ui.select({"": "wie Gelände", **{k: k for k in mats}}, label="Material der Gebäude").bind_value(g, "material") \
                        .classes("min-w-[220px]")
                    ui.number("Stärke mm (leer = wie Gelände)", min=0.1, max=10, step=0.1).bind_value(g, "staerke_mm") \
                        .classes("w-56").props("clearable")
                    ui.number("Laschenbreite mm", min=1, max=10, step=0.5).bind_value(g, "lasche_mm").classes("w-40") \
                        .bind_visibility_from(g, "modus", value="falt")
                ui.checkbox("Teile-Nummern auf die Teile gravieren").bind_value(g, "teile_beschriften")
                ui.checkbox("Fenstermuster gravieren (nur Flächen und Faltmodell; MUSTER, nicht gemessen)").bind_value(g, "fenstermuster") \
                    .tooltip("LoD2 enthält keine Fenster und Türen. Das Muster richtet sich nur nach Wandbreite und -höhe (Achse ca. 3 m, "
                             "Fenster 1,2 × 1,4 m). Die echte Lage der Fenster stimmt damit nicht.")
                hinweis_f = hinweis("Faltmodell: Am besten dünner Karton (z. B. Bristolkarton 0,25–0,5 mm); die blauen Linien sind die Faltkanten, "
                                    "die Laschen kommen innen an die Nachbarwand.")
                hinweis_f.bind_visibility_from(g, "modus", value="falt")
            # --- 3D-Druck
            with ui.column().classes("w-full gap-1").bind_visibility_from(g, "modus", backward=ist_druck):
                with ui.row().classes("gap-2"):
                    ui.number("Nahzone Radius m (leer = alles LoD2)").bind_value(g, "nahzone_radius_m").classes("w-64") \
                        .tooltip("Außerhalb werden Gebäude als einfache Blöcke gedruckt")
                    ui.number("Min. Wand mm").bind_value(g, "min_breite_mm").classes("w-28")
                    ui.select({"gravieren": "nur auf Platte", "verstaerken": "verstärken"}, label="Zu kleine Bauten") \
                        .bind_value(g, "zu_klein").classes("w-40")
                self.drucker(self.cfg["druck"])
                with ui.row().classes("gap-2 items-center"):
                    sw = ui.checkbox("Steckstifte (Gebäude abnehmbar)").bind_value(g, "stifte") \
                        .tooltip("Unter jedem Gebäude stehen Zapfen, die in Löcher der Geländeplatten greifen")
                    st = ui.row().classes("gap-2 items-center")
                    with st:
                        ui.number("Ø mm", min=1, step=0.5).bind_value(g, "stift_d_mm").classes("w-20")
                        ui.number("Länge mm", min=1, step=0.5).bind_value(g, "stift_laenge_mm").classes("w-24")
                        ui.number("Spiel mm", min=0, step=0.1).bind_value(g, "stift_spiel_mm").classes("w-24") \
                            .tooltip("Das Loch ist um diesen Betrag größer als der Stift")
                        ui.number("Abstand mm", min=10, step=5).bind_value(g, "stift_abstand_mm").classes("w-28") \
                            .tooltip("Bei langen Gebäuden alle x mm ein weiterer Stift")
                    ausgrauen(st, sw)
            # --- optionale Zusatzmodule (nicht im öffentlichen Repository)
            g.setdefault("zusatz", {})
            from .. import zusatz as _zusatz
            _zusatz.rufe("gui_modell", ui, g)

    def _karte_restplatten(self):
        lc = self.cfg["laser"]
        rp = lc.setdefault("restplatten", [])
        with karte("Restplatten verwerten", SALBEI, offen=bool(rp)):
            hinweis("Angebrochene Platten (gleiches Material und gleiche Stärke wie oben) hier anlegen. Das Programm belegt sie zuerst "
                    "mit den passenden Teilen, alles Übrige kommt auf das oben gewählte Plattenformat.")
            box = ui.column().classes("w-full gap-1")

            def zeichnen():
                box.clear()
                with box:
                    for r in rp:
                        with ui.row().classes("w-full items-end no-wrap gap-1"):
                            ui.input("Name").bind_value(r, "name").props("dense").classes("w-32")
                            ui.number("Breite mm", min=20).bind_value(r, "b_mm").props("dense").classes("w-28")
                            ui.number("Höhe mm", min=20).bind_value(r, "h_mm").props("dense").classes("w-28")
                            ui.number("Anzahl", min=1, step=1).bind_value(r, "anzahl").props("dense").classes("w-20")
                            ui.button(icon="close", on_click=lambda r=r: (rp.remove(r), zeichnen())).props("flat dense round")
                    ui.button("Restplatte hinzufügen", icon="add",
                              on_click=lambda: (rp.append({"name": f"Rest {len(rp) + 1}", "b_mm": 400, "h_mm": 300, "anzahl": 1}),
                                                zeichnen())).props("flat dense")
            zeichnen()

    def _karte_holz(self):
        hc = self.cfg.setdefault("holz", {})
        rc = hc.setdefault("rahmen", {})
        pc = hc.setdefault("podest", {})
        for k, v in (("aktiv", False), ("breite_mm", 20.0), ("hoehe_mm", None), ("gehrung", True)):
            rc.setdefault(k, v)
        for k, v in (("aktiv", False), ("hoehe_mm", 80.0), ("deckplatte_mm", 12.0), ("ueberstand_mm", 20.0),
                     ("rahmenholz_breite_mm", 12.0), ("stuetz_abstand_mm", 300.0)):
            pc.setdefault(k, v)
        with karte("Holz: Rahmenleisten und Grundpodest (Zuschnittliste)", OCKER, offen=False):
            hinweis("Es entstehen eine Zuschnittliste (Text und CSV) und eine Zeichnung – gelasert wird nichts. Maße ohne Sägezugabe.")
            sw = ui.checkbox("Rahmenleisten ums Modell").bind_value(rc, "aktiv")
            b1 = ui.row().classes("gap-2 items-center")
            with b1:
                ui.number("Leistenbreite mm", min=5).bind_value(rc, "breite_mm").classes("w-36").tooltip("Breite von oben gesehen")
                ui.number("Leistenhöhe mm (leer = Höhe des Geländestapels)", min=3).bind_value(rc, "hoehe_mm").classes("w-80").props("clearable")
                ui.checkbox("Gehrung (45°)").bind_value(rc, "gehrung")
            ausgrauen(b1, sw)
            sw2 = ui.checkbox("Grundpodest aus Holz (Deckplatte, Rahmenbretter, bei Bedarf Stützrahmen – kein Boden)").bind_value(pc, "aktiv")
            b2 = ui.row().classes("gap-2 items-center")
            with b2:
                ui.number("Podesthöhe mm", min=20).bind_value(pc, "hoehe_mm").classes("w-36").tooltip("Gesamthöhe bis Oberkante Deckplatte")
                ui.number("Deckplatte mm", min=4).bind_value(pc, "deckplatte_mm").classes("w-32")
                ui.number("Überstand mm", min=0).bind_value(pc, "ueberstand_mm").classes("w-32").tooltip("Deckplatte steht über Modell bzw. Rahmen hinaus")
                ui.number("Brettstärke mm", min=4).bind_value(pc, "rahmenholz_breite_mm").classes("w-32")
                ui.number("Stützabstand mm", min=100).bind_value(pc, "stuetz_abstand_mm").classes("w-36").tooltip("Stützrahmen im Unterbau höchstens in diesem Abstand")
            ausgrauen(b2, sw2)

    def _karte_raster(self):
        rb = self.cfg.setdefault("raster_bild", {})
        for k, v in (("aktiv", False), ("quelle", "luftbild"), ("datei", ""), ("weite_mm", 0.5), ("kontrast", 1.0),
                     ("helligkeit", 0.0), ("teststreifen", True)):
            rb.setdefault(k, v)
        try:
            from .. import projekt as _P
            _P.kern()
            import ifcmap_wms as _WM
            quellen = {k: v for k, v in _WM.WMS_NAMEN.items() if not k.startswith("ua_")}
        except Exception:
            quellen = {"luftbild": "Luftbild (Berlin)"}
        with karte("Rastergravur eines Bildes (experimentell)", TERRA, offen=False):
            sw = ui.checkbox("Luftbild / Bild als Rastergravur auf die Geländeschichten").bind_value(rb, "aktiv")
            box = ui.column().classes("w-full gap-1")
            with box:
                hinweis("Experimentell und an der Werkstatt noch nicht getestet. Das Bild wird als Linienraster aus schwarzen Streifen "
                        "geschrieben (die Werkstatt nimmt Gravur nur als schwarze Fläche). Jede Schicht bekommt nur ihren sichtbaren Ring; "
                        "zusammengesetzt ergibt das wieder ein durchgehendes Bild. Die Gravur kostet nach Fläche, nicht nach Bildinhalt – "
                        "eine ganze 80 × 50-Platte kann rund eine Stunde dauern. Erst den Teststreifen lasern lassen. "
                        "Hell wirkt es auf Finnpappe, Bristolkarton und Sperrholz; auf Graupappe ist der Kontrast schwach.")
                with ui.row().classes("gap-2 items-end"):
                    ui.select({**quellen, "datei": "eigene Bilddatei"}, label="Bildquelle").bind_value(rb, "quelle").classes("min-w-[260px]")
                    ui.number("Zeilenabstand mm", min=0.25, max=3, step=0.05).bind_value(rb, "weite_mm").classes("w-40") \
                        .tooltip("Kleiner = feiner, aber mehr Objekte und längere Laserzeit")
                    ui.number("Kontrast", min=0.3, max=3, step=0.1).bind_value(rb, "kontrast").classes("w-28")
                    ui.number("Helligkeit −1…+1", min=-1, max=1, step=0.1).bind_value(rb, "helligkeit").classes("w-40")
                datei = ui.column().classes("w-full")
                with datei:
                    feld_pfad("Bilddatei (GeoTIFF mit Georeferenz, sonst JPG/PNG auf den Ausschnitt gestreckt)", rb, "datei",
                              typen=("Bilder (*.tif;*.tiff;*.jpg;*.jpeg;*.png)",))
                datei.bind_visibility_from(rb, "quelle", value="datei")
                ui.checkbox("Teststreifen 100 × 100 mm in drei Stufen mitlasern").bind_value(rb, "teststreifen")
            ausgrauen(box, sw)

    def _ebenen_tabelle(self):
        cfg = self.cfg
        eb = cfg.setdefault("ebenen", {})
        ui.label("Geländeplatten").classes("text-subtitle2")
        with ui.grid(columns=2).classes("w-full gap-x-3 gap-y-0 items-center"):
            for name in EBENEN_STANDARD:
                eb.setdefault(name, EBENEN_STANDARD[name])
                ui.label(name)
                ui.select(AKTION_TEXT if name != "Anlegekante nächste Schicht" else
                          {k: v for k, v in AKTION_TEXT.items() if k != "schneiden"}).bind_value(eb, name).props("dense")
        with ui.column().classes("w-full").bind_visibility_from(cfg, "quelle", backward=lambda q: q in ("auto", "ifcmap")):
            ui.label("Ebenen aus den Geodaten").classes("text-subtitle2 mt-2")
            from ..modell.ifcmap_adapter import EBENEN_VORGABE
            ie = cfg["ifcmap"].setdefault("ebenen", {})
            zus = cfg["ifcmap"].setdefault("zusatz", [])

            def zeile(name):
                e = ie.setdefault(name, dict(EBENEN_VORGABE.get(name, {"aktion": "aus"})))
                if isinstance(e, str):
                    e = ie[name] = {"aktion": e}
                e.setdefault("aktion", "aus")
                ui.label(EBENEN_NAMEN.get(name, name))
                ui.select(AKTION_TEXT).bind_value(e, "aktion").props("dense")
                if name == "Baeume":
                    e.setdefault("punkt_d_mm", 1.5)
                    ui.number("Ø mm", step=0.5).bind_value(e, "punkt_d_mm").props("dense").classes("w-20") \
                        .bind_enabled_from(e, "aktion", backward=lambda a: a != "aus")
                elif name in ("Gleisachsen", "OEPNV", "Gewaessernetz"):
                    e.setdefault("breite_m", 0)
                    ui.number("Breite m", step=0.5).bind_value(e, "breite_m").props("dense").classes("w-20") \
                        .bind_enabled_from(e, "aktion", backward=lambda v: v == "gravieren") \
                        .tooltip("Nur für „gravieren“: Linien werden zu Flächen dieser Breite")
                else:
                    e.setdefault("raster_grau", 50.0)
                    ui.number("Grau %", min=5, max=100, step=5).bind_value(e, "raster_grau").props("dense").classes("w-20") \
                        .bind_visibility_from(e, "aktion", value="raster").tooltip("Grauwert der Rastergravur (Streifenbreite im Zeilenabstand 0,8 mm)")
            with ui.grid(columns=3).classes("w-full gap-x-3 gap-y-0 items-center"):
                for name in IFCMAP_EBENEN:
                    zeile(name)
            ui.label("Zusätzlich aus den Geodiensten holen (Berlin amtlich, sonst OpenStreetMap)") \
                .classes("text-subtitle2 mt-2")
            zbox = ui.grid(columns=3).classes("w-full gap-x-3 gap-y-0 items-center")

            def zus_zeichnen():
                zbox.clear()
                with zbox:
                    for k, (name, txt) in ZUSATZ_EBENEN.items():
                        if k in zus:
                            zeile(name)
            with ui.row().classes("gap-1"):
                for k, (name, txt) in ZUSATZ_EBENEN.items():
                    def umschalten(e, k=k):
                        if e.value and k not in zus:
                            zus.append(k)
                        elif not e.value and k in zus:
                            zus.remove(k)
                        zus_zeichnen()
                    ui.checkbox(txt, value=k in zus, on_change=umschalten).props("dense")
            zus_zeichnen()
            ui.label("Weitere amtliche Quellen (nur Berlin, neu und ungetestet; amtlich zuerst, OpenStreetMap nur als Ergänzung)").classes("text-subtitle2 mt-2")
            im = cfg["ifcmap"]
            for k, txt in (("ua_gebaeudehoehen", "Gebäude ohne LoD2: Höhe und Dachform aus dem Umweltatlas"),
                           ("ua_vegetationsraster", "Bäume: Vegetationsraster 1 m (einmaliger Download, ca. 785 MB)"),
                           ("rad_wege", "Wege: Radverkehrsnetz als zusätzliche Quelle"),
                           ("osm_ergaenzen", "OpenStreetMap-Bäume ergänzen, die es amtlich nicht gibt")):
                im.setdefault(k, k in ("osm_ergaenzen", "ua_gebaeudehoehen"))
                ui.checkbox(txt).bind_value(im, k).props("dense")
        with ui.column().classes("w-full").bind_visibility_from(cfg, "quelle", value="dateien"):
            ui.label("Eigene Markierungs-Dateien").classes("text-subtitle2 mt-2")
            box = ui.column().classes("w-full gap-1")

            def neu_zeichnen():
                box.clear()
                with box:
                    for m in cfg["markierungen"]:
                        with ui.row().classes("w-full items-end no-wrap gap-1"):
                            ui.input("Name").bind_value(m, "name").classes("w-24").props("dense")
                            feld_pfad("Datei", m, "datei", typen=("Vektordaten (*.gpkg;*.shp;*.geojson)",))
                            ui.select(AKTION_TEXT).bind_value(m, "aktion").props("dense").classes("w-36")
                            ui.number("Breite m").bind_value(m, "breite_m").props("dense").classes("w-20") \
                                .bind_enabled_from(m, "aktion", backward=lambda a: a != "aus")
                            ui.number("Ø mm").bind_value(m, "punkt_d_mm").props("dense").classes("w-16") \
                                .bind_enabled_from(m, "aktion", backward=lambda a: a != "aus")
                            m.setdefault("raster_grau", 50.0)
                            ui.number("Grau %", min=5, max=100, step=5).bind_value(m, "raster_grau").props("dense").classes("w-16") \
                                .bind_visibility_from(m, "aktion", value="raster")
                            ui.button(icon="close", on_click=lambda m=m: (cfg["markierungen"].remove(m), neu_zeichnen())) \
                                .props("flat dense round")
                    ui.button("Markierung hinzufügen", icon="add",
                              on_click=lambda: (cfg["markierungen"].append(
                                  {"name": "", "datei": "", "layer": "", "aktion": "ritzen", "breite_m": 0, "punkt_d_mm": 1.5}),
                                  neu_zeichnen())).props("flat dense")
            neu_zeichnen()

    def _schicht_info(self):
        try:
            from ..modell.pipeline import schichtdicke
            t = schichtdicke(self.cfg)
            s = float(self.cfg["massstab"])
            ue = float(self.cfg["gelaende"].get("ueberhoehung") or 1.0)
            dz = t * s / 1000.0 / ue
            txt = (f"1 Schicht = {mm_text(t)} mm Platte ≙ {dz:.2f} m Geländehöhe".replace(".", ",")
                   + (f" (1:{s:g}" + (f", {ue:g}× überhöht)" if ue != 1 else ")")))
            if hasattr(self, "lbl_schicht2"):
                self.lbl_schicht2.text = txt
            if hasattr(self, "lbl_schicht"):
                self.lbl_schicht.text = txt
        except Exception:
            pass
    # ------------------------------------------------------------------ Seite
    def _karte_daten(self):
        cfg = self.cfg
        if cfg.get("quelle") not in ("auto", "dateien"):
            cfg["quelle"] = "auto"
        with karte("Modell: Daten", AKZENT):
            ui.toggle({"auto": "Automatisch (Koordinaten)", "dateien": "Eigene Dateien"}).bind_value(cfg, "quelle")
            with ui.column().classes("w-full gap-0").bind_visibility_from(cfg, "quelle", value="auto"):
                hinweis("Berlin: Gelände (DGM1), Gebäude (LoD2), ALKIS-Nutzung, Bäume und Flurstücke werden automatisch "
                        "geladen und zwischengespeichert. Außerhalb Berlins: Länder-Downloads bzw. OpenStreetMap.")
            with ui.column().classes("w-full").bind_visibility_from(cfg, "quelle", value="dateien"):
                feld_pfad("DGM (GeoTIFF/XYZ/ASC, Datei oder Ordner)", cfg["dgm"], "datei",
                          typen=("Gelände (*.tif;*.tiff;*.xyz;*.asc;*.txt)",))
                feld_pfad("LoD2-CityGML (mehrere mit ;)", cfg["gebaeude"], "citygml", mehrere=True,
                          typen=("CityGML (*.gml;*.xml)",))
                feld_pfad("Grundrisse als Blöcke (optional)", cfg["gebaeude"], "grundriss_datei",
                          typen=("Vektordaten (*.gpkg;*.shp;*.geojson)",))
                with ui.row().classes("gap-2"):
                    ui.input("Höhen-Attribut").bind_value(cfg["gebaeude"], "hoehe_feld").classes("w-40")
                    ui.number("Standardhöhe m").bind_value(cfg["gebaeude"], "standard_hoehe_m").classes("w-36")

    def seite(self):
        """Karten für Lasercut und 3D-Druck; sichtbar je nach gewählten Ausgaben."""
        cfg, ausg = self.cfg, self.p["ausgaben"]
        regeln = []

        def abschnitt(wann):
            col = ui.column().classes("w-full gap-3")
            regeln.append((col, wann))
            return col

        teile = {}
        with ui.column().classes("w-full gap-3") as wurzel:
            with abschnitt(lambda: ausg.get("laser") or ausg.get("druck")) as a_daten:
                self._karte_daten()
            teile["modell_daten"] = a_daten
            # Alles zum Gelände-Lasercut in EINER Kachel (Unterabschnitte zum Aufklappen)
            with abschnitt(lambda: ausg.get("laser")) as a_laser:
                with _karte("Gelände Lasercut – alle Einstellungen", OCKER):
                    _UNTER["an"] = True
                    try:
                        with karte("Material und Platte", OCKER):
                            self.material_format(cfg["laser"])
                            self.lbl_schicht2 = ui.label("").classes("text-body2").style(f"color:{AKZENT}")
                        self._karte_restplatten()
                        self._karte_raster()
                        self._karte_bauweise()
                        with karte("Was wird geritzt, graviert, geschnitten?", SCHIEFER):
                            self._ebenen_tabelle()
                        with karte("Feineinstellungen", GRAU, offen=False):
                            g = cfg["gelaende"]
                            with ui.row().classes("gap-2"):
                                ui.number("Min. Stegbreite Gelände mm").bind_value(g, "min_breite_mm").classes("w-56")
                                ui.number("Min. Inselfläche mm²").bind_value(g, "min_flaeche_mm2").classes("w-48")
                                ui.number("DGM glätten m").bind_value(cfg["dgm"], "glaettung_m").classes("w-40")
                            ui.checkbox("Gebäude auf höheren Schichten aussparen (stehen eben)").bind_value(g, "gebaeude_aussparen")
                            ui.checkbox("lange dünne Ringe teilen (packt dichter)").bind_value(cfg["laser"], "ringe_teilen")
                            ui.checkbox("zusätzlich DXF (Kontrolle in Archicad)").bind_value(cfg["laser"], "ausgabe_dxf")
                    finally:
                        _UNTER["an"] = False
            teile["laser"] = a_laser
            with abschnitt(lambda: ausg.get("laser") or ausg.get("druck")) as a_holz:
                self._karte_holz()
            teile["holz"] = a_holz
            with abschnitt(lambda: ausg.get("druck")) as a_druck:
                self._karte_gebaeude()
                if not ausg.get("laser"):
                    with karte("Maßstab", TERRA):
                        hinweis("Der Maßstab steht auf der Seite „Gebiet“.")
            teile["druck"] = a_druck
        wurzel.teile = teile
        ui.timer(0.5, self._schicht_info)

        def aktualisieren():
            for el, f in regeln:
                el.set_visibility(bool(f()))
        ui.timer(0.4, aktualisieren)
        aktualisieren()
        return wurzel
