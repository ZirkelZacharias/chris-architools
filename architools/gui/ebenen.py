"""Ebenen (welche Teile in IFC und DXF) und Nutzungsarten-Zuordnung – nach „Vorschau laden“."""
from nicegui import ui

from .. import projekt as P
from .stil import AKZENT, GRAU, hinweis

EXTRA_NAMEN = {"denkmal": "Denkmalkarte", "fnp": "Flächennutzungsplan", "laerm": "Lärmkarte", "oepnv": "ÖPNV",
               "gewaesser": "Gewässernetz", "radverkehr": "Radverkehrsnetz"}


def _vorgabe(K, u, art, key):
    if art == "ifc" and key.startswith("Gelaende:"):
        erl = K.AUFTEILUNG.get(u.get("aufteilung") or "strassen", K.AUFTEILUNG["strassen"])
        return erl is None or key.split(":", 1)[1] in erl
    if art == "dxf" and key == "Nutzung_Grenzen":
        return False                       # Flächen sind Schraffuren; Grenzlinien nur auf Wunsch
    return True


def ebenen_panel(box, p, d):
    """Tabelle: je Ebene ein Haken für IFC und einer für DXF. Gespeichert wird nur, was von der Vorgabe abweicht."""
    K = P.kern()
    u = p["umgebung"]
    eb = u.setdefault("ebenen", {})
    eb.setdefault("ifc", {})
    eb.setdefault("dxf", {})
    box.clear()
    with box:
        if d is None:
            hinweis("Erst „Vorschau laden“ – dann erscheinen hier alle Ebenen.")
            return
        zellen = []                                           # (art, key, checkbox)

        def alle(art, wert):
            for a, k, cb in zellen:
                if a == art:
                    cb.value = wert

        def reset():
            eb["ifc"].clear()
            eb["dxf"].clear()
            ebenen_panel(box, p, d)
        with ui.row().classes("items-center gap-2"):
            for art, txt in (("ifc", "IFC"), ("dxf", "DXF")):
                ui.button(f"{txt}: alle an", on_click=lambda a=art: alle(a, True)).props("flat dense no-caps")
                ui.button(f"{txt}: alle aus", on_click=lambda a=art: alle(a, False)).props("flat dense no-caps")
            ui.button("Zurücksetzen", icon="restart_alt", on_click=reset).props("flat dense no-caps")
        hinweis("Welche Ebenen sollen in die IFC und welche in die 2D-Zeichnungen (Informations-DWG, Lageplan, Schwarzplan)? "
                "Die Liste richtet sich nach den geladenen Daten.")
        grid = ui.column().classes("w-full gap-0")

        def kopf(text):
            with grid:
                ui.label(text).classes("text-weight-bold q-px-sm q-py-xs mt-2").style(f"background:#dcebec; color:#15555c")

        def reihe(label, ifc_key=None, dxf_key=None):
            with grid:
                with ui.row().classes("w-full items-center no-wrap gap-0").style("border-bottom:1px solid #eee"):
                    for art, key in (("ifc", ifc_key), ("dxf", dxf_key)):
                        with ui.element("div").style("width:56px; text-align:center"):
                            if key is None:
                                ui.label("–").style("color:#b5bbc4")
                                continue
                            vor = _vorgabe(K, u, art, key)

                            def geaendert(e, art=art, key=key, vor=vor):
                                if bool(e.value) == vor:
                                    eb[art].pop(key, None)
                                else:
                                    eb[art][key] = bool(e.value)
                            cb = ui.checkbox(value=bool(eb[art].get(key, vor)), on_change=geaendert).props("dense")
                            zellen.append((art, key, cb))
                    ui.label(label).classes("text-body2 q-pl-sm")

        modus = d.cfg.fern_gebaeude
        with ui.row().classes("items-center gap-0 w-full").style("margin-top:6px"):
            ui.label("IFC").style("width:56px; text-align:center").classes("text-caption text-weight-bold")
            ui.label("DXF").style("width:56px; text-align:center").classes("text-caption text-weight-bold")
        kopf("Gebäude, Bäume, Rahmen")
        reihe("Gebäude im Nahbereich (LoD2-Dächer): %d Teile" % len(d.near), "Gebaeude_Nah", "Gebaeude_Nah")
        reihe("Gebäude im Fernbereich (%s): %d Teile" % ({"bloecke": "Blöcke", "lod2": "LoD2", "keine": "weggelassen"}[modus], len(d.far)),
              "Gebaeude_Fern" if modus != "keine" else None, "Gebaeude_Fern")
        if getattr(d, "markant", None):
            reihe("Markante Gebäude (Detailform): %d – %s" % (len(d.markant), ", ".join(sorted({m["quelle"] for m in d.markant}))),
                  "Gebaeude_Markant", None)
        if getattr(d.cfg, "geschosslinien", False):
            reihe("Geschosslinien an den Wänden (nur Nahbereich)", "Gebaeude_Geschosse", None)
        reihe("Bäume: %d (2D: nur Baumkronen als Kreise)" % len(d.baeume), "Baeume", "Baeume")
        reihe("Rahmen von Gebiet und Nahbereich", None, "Rahmen")
        reihe("Brücken (2D: oberhalb von Gelände, Wasser und Bahn)", None, "Bruecken")
        reihe("Sonnenbahn-Diagramm (nur wenn eingeschaltet)", "Sonne", "Sonne")
        if d.regionen:
            kopf("Nutzungsarten (IFC: eigenes Geländeteil, DXF: Schraffur)")
            fl = {k: v.area / 1e4 for k, v in d.regionen.items()}
            for kat in sorted(d.regionen, key=lambda k: -fl[k]):
                reihe("%s – %.2f ha" % (kat.replace("_", " "), fl[kat]), "Gelaende:" + kat, "Nutzung:" + kat)
            reihe("Nutzungsgrenzen als Linien (Flächen sind sonst reine Schraffuren)", None, "Nutzung_Grenzen")
        zus = getattr(d, "zusatz", {}) or {}
        if zus.get("Flurstuecke") or zus.get("Bauwerke"):
            kopf("Zusatz aus ALKIS (nur 2D)")
            if zus.get("Flurstuecke"):
                reihe("Flurstücke: %d" % len(zus["Flurstuecke"]), None, "ALKIS_Flurstuecke")
            if zus.get("Bauwerke"):
                reihe("Bauwerke: %d" % len(zus["Bauwerke"]), None, "ALKIS_Bauwerke")
        extra = getattr(d, "extra", {}) or {}
        if extra:
            kopf("Zusatzdaten (nur 2D)")
            for key, items in extra.items():
                reihe("%s: %d Objekte" % (EXTRA_NAMEN.get(key, key), len(items)), None, "Extra:" + key)
                for sub in sorted({s for s, *_ in items if s}):
                    n = sum(1 for s, *_ in items if s == sub)
                    txt = sub.replace("_", " ")
                    if key == "laerm" and sub[:2].isdigit():
                        von, _, bis = sub.partition("_")
                        txt = "%s – %s dB" % (von, bis.replace("ueber_", "über "))
                    reihe("      ↳ %s (%d)" % (txt, n), None, "Extra:%s:%s" % (key, sub))


def nutzung_panel(box, p, d, geaendert=None):
    """So wurden die Nutzungsarten zugeordnet; die Kategorie lässt sich je Zeile ändern."""
    K = P.kern()
    u = p["umgebung"]
    box.clear()
    with box:
        if d is None:
            hinweis("Erst „Vorschau laden“ – dann erscheint hier die Zuordnung der Nutzungsarten.")
            return
        if not getattr(d, "tabelle", None):
            hinweis("In den geladenen Daten gibt es keine Nutzungsarten zuzuordnen (z. B. bei eigenen Dateien ohne Nutzungsflächen).")
            return
        hinweis("So wurden die Nutzungsarten aus den Daten zugeordnet. Die Kategorie lässt sich je Zeile ändern "
                "(auch eigener Name möglich, z. B. „Hof“).")

        def aendern(text, wert):
            neu = str(wert or "").strip().replace(" ", "_")
            if not neu:
                return
            u.setdefault("overrides", {})[text] = neu
            d.cfg.overrides = dict(u["overrides"])
            K.zuordnen(d)
            if geaendert:
                geaendert()

        def zuruecksetzen():
            u["overrides"] = {}
            d.cfg.overrides = {}
            K.zuordnen(d)
            if geaendert:
                geaendert()
        ui.button("Zuordnung zurücksetzen", icon="restart_alt", on_click=zuruecksetzen).props("flat dense no-caps")
        with ui.row().classes("w-full items-center no-wrap q-px-sm").style("background:#dcebec"):
            ui.label("Nutzung").classes("text-weight-bold grow")
            ui.label("Kategorie").classes("text-weight-bold").style("width:240px")
            ui.label("Anzahl").classes("text-weight-bold").style("width:70px")
            ui.label("ha").classes("text-weight-bold").style("width:70px")
        for text, kat, n, ha in d.tabelle:
            with ui.row().classes("w-full items-center no-wrap q-px-sm").style("border-bottom:1px solid #eee"):
                ui.label(text).classes("text-body2 grow")
                ui.select(list(K.KATEGORIE_NAMEN), value=kat, new_value_mode="add-unique", with_input=True,
                          on_change=lambda e, t=text: aendern(t, e.value)).props("dense borderless").style("width:240px")
                ui.label(str(n)).style("width:70px")
                ui.label("%.2f" % ha).style("width:70px")
