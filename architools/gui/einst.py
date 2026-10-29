"""Seite „Einstellungen“: je gewählter Ausgabe die passenden Karten."""
from nicegui import ui

from .. import projekt as P
from . import einst_umgebung, voreinstellungen, eier
from .. import einstellungen as ES
from .. import formate as FM
from .einst_modell import ModellEinst
from .stil import AKZENT, GRAU, HOEHE, INK, MASSSTAEBE, SCHIEFER, TERRA, hinweis, karte


_dwg_updates = []


def _format_gruppe(titel, tabelle, liste, empfohlen, brauche_oda=False):
    """Mehrfach-Auswahl der Formate. Ein kleines Icon von Zirkel Zacharias (ohne ein Wort) markiert die für Archicad beste Wahl."""
    from .. import dwg, dwg_direkt
    oda = dwg.finden(ES.laden().get("oda_pfad", ""))
    ui.label(titel).classes("text-subtitle2")
    boxen = {}
    with ui.row().classes("gap-5 items-center"):
        for key, (name, text) in tabelle.items():
            def umschalten(e, key=key):
                if e.value and key not in liste:
                    liste.append(key)
                elif not e.value and key in liste:
                    liste.remove(key)
                for u in _dwg_updates:
                    u()
            with ui.row().classes("items-center no-wrap gap-1"):
                cb = ui.checkbox(name, value=key in liste, on_change=umschalten).tooltip(text)
                boxen[key] = cb
                if key == empfohlen:
                    eier.zeiger()
    dwg_hinweis = hinweis("") if brauche_oda else None

    def dwg_text(_=None):
        if dwg_hinweis is None:
            return
        dwg_hinweis.text = "" if "dwg" not in liste else "DWG: " + (
            "ODA File Converter gefunden – volle Farben." if oda else
            "kein ODA File Converter – das Programm schreibt die DWG selbst (R2000, Farben auf AutoCAD-Standardfarben gerundet, "
            "keine Transparenz)." if dwg_direkt.verfuegbar() else
            "weder ODA File Converter noch eingebautes DWG-Modul – es bleibt bei DXF.")
    dwg_text()
    _dwg_updates.append(dwg_text)
    hinweis("Mehrere möglich. Mit der Maus über einem Format steht, was es kann.")
    return boxen


def _profile_leiste(p, boxen2, boxen3):
    """Export-Profile: ein Klick stellt die Formate für das Zielprogramm ein; eigene Profile lassen sich speichern."""
    f = p["formate"]
    es = ES.laden()
    eigene = es.setdefault("export_profile", {})
    zeile = ui.row().classes("w-full items-center gap-1")
    info = hinweis("")

    def anwenden(zwei, drei, text=""):
        for key, cb in boxen2.items():
            cb.value = key in zwei
        for key, cb in boxen3.items():
            cb.value = key in drei
        info.text = text

    def speichern_dlg():
        with ui.dialog() as dlg, ui.card():
            ui.label("Aktuelle Formate als Profil speichern").classes("text-subtitle1")
            name = ui.input("Name des Profils").classes("w-64")

            def ok():
                n = (name.value or "").strip()
                if not n:
                    return
                eigene[n] = {"zweid": list(f["zweid"]), "dreid": list(f["dreid"])}
                ES.speichern(es)
                dlg.close()
                zeichnen()
            with ui.row().classes("justify-end w-full"):
                ui.button("Abbrechen", on_click=dlg.close).props("flat no-caps")
                ui.button("Speichern", on_click=ok).props("unelevated no-caps color=primary")
        dlg.open()

    def loeschen(n):
        eigene.pop(n, None)
        ES.speichern(es)
        zeichnen()

    def zeichnen():
        zeile.clear()
        with zeile:
            ui.label("Profil:").classes("text-caption").style(f"color:{GRAU}")
            for n, (zwei, drei, text) in FM.PROFILE.items():
                ui.chip(n, on_click=lambda zwei=zwei, drei=drei, text=text: anwenden(zwei, drei, text)) \
                    .props("dense outline clickable color=primary")
            for n, e in eigene.items():
                ui.chip(n, icon="bookmark", removable=True, on_click=lambda e=e: anwenden(e["zweid"], e["dreid"], "Eigenes Profil"),
                        on_value_change=lambda ev, n=n: loeschen(n) if not ev.value else None) \
                    .props("dense outline clickable color=secondary")
            ui.button(icon="add", on_click=speichern_dlg).props("flat round dense size=sm").tooltip("Aktuelle Auswahl als eigenes Profil speichern")
    zeichnen()


def formate_karte(p):
    f = p["formate"]
    ausg = p["ausgaben"]
    with ui.column().classes("w-full") as wurzel:
        with karte("Dateiformate", INK):
            profile_ort = ui.column().classes("w-full")
            z = ui.column().classes("w-full gap-1")
            with z:
                boxen2 = _format_gruppe("2D-Zeichnungen (Lageplan, Schwarzplan, Informations-DWG, Höhenlinien)", FM.FORMATE_2D, f["zweid"], FM.EMPFEHLUNG_2D, brauche_oda=True)
            d = ui.column().classes("w-full gap-1")
            with d:
                ui.separator()
                boxen3 = _format_gruppe("3D-Modell der Umgebung", FM.FORMATE_3D, f["dreid"], FM.EMPFEHLUNG_3D)
            with profile_ort:
                _profile_leiste(p, boxen2, boxen3)
            warn = ui.label("").classes("text-caption").style("color:#b00020")

            def pruefen():
                z.set_visibility(bool(ausg.get("lageplan") or ausg.get("schwarzplan") or ausg.get("info_dwg") or ausg.get("hoehenlinien")))
                d.set_visibility(bool(ausg.get("ifc")))
                bad = (not f["zweid"] and z.visible) or (not f["dreid"] and d.visible)
                warn.text = "Bitte mindestens ein Format wählen – sonst gibt es keine Datei." if bad else ""
            ui.timer(0.5, pruefen)
    wurzel.set_visibility(True)
    return wurzel


def schnitt_karte(p):
    s = p["schnitt"]
    with ui.column().classes("w-full") as wurzel:
        with karte("Geländeschnitt / Abwicklung: Ausgabe", TERRA, offen=False):
            with ui.row().classes("gap-2 items-end"):
                ui.select(MASSSTAEBE, label="Maßstab", new_value_mode="add-unique", with_input=True) \
                    .bind_value(s, "massstab").classes("w-32")
                ui.number("Abstand m", step=0.1, min=0.1).bind_value(s, "abstand_m").classes("w-28") \
                    .tooltip("Rasterabstand entlang der Linie")
                ui.select({"dxf": "DXF (empfohlen)", "dwg": "DWG", "pdf": "PDF", "svg": "SVG"}, multiple=True, label="Formate") \
                    .bind_value(s, "format").classes("w-64")
            hinweis("Die Schnittlinie zeichnest du auf der Seite „Gebiet“ direkt in der Karte – dort stellst du auch die Blickrichtung ein.")
    return wurzel


def hoehenlinien_karte(p):
    h = p["hoehenlinien"]
    with ui.column().classes("w-full") as wurzel:
        with karte("Höhenlinien: Ausgabe", TERRA, offen=False):
            with ui.row().classes("gap-2 items-end"):
                ui.number("Abstand der Linien (m)", step=0.5, min=0.1).bind_value(h, "aequidistanz_m").classes("w-44") \
                    .tooltip("Äquidistanz: Höhenunterschied zwischen zwei Linien – 1 m ist für Stadtgebiete üblich, 0,5 m für flaches Gelände")
                ui.number("Hauptlinie alle … Linien", step=1, min=1, format="%.0f").bind_value(h, "haupt_alle").classes("w-48") \
                    .tooltip("Jede n-te Linie wird stärker gezeichnet und beschriftet")
                ui.select(MASSSTAEBE, label="Maßstab (Schriftgröße)", new_value_mode="add-unique", with_input=True) \
                    .bind_value(h, "massstab").classes("w-44")
            with ui.row().classes("gap-4 items-center"):
                ui.checkbox("Höhenkoten beschriften").bind_value(h, "beschriften")
                ui.checkbox("leicht glätten").bind_value(h, "glaetten") \
                    .tooltip("Das Gelände-Raster ist stufig – leichtes Glätten gibt ruhigere Linien")
            hinweis("Eigene Zeichnung (DXF/DWG je nach „Dateiformate“), Gebiet = Größe der Umgebung. Jede Linie liegt in ihrer wahren Höhe (m ü. NHN), "
                    "Nullpunkt in Ost/Nord wie bei den anderen Plänen.")
            with ui.expansion("Höhen auf einen Nullpunkt beziehen (optional)").classes("w-full").props("dense"):
                ui.number("Z-Nullpunkt (m ü. NHN)", step=1).bind_value(h, "z_null").classes("w-56") \
                    .tooltip("Leer = wahre Höhen. Mit Wert: Höhe minus Wert – z. B. der Nullpunkt Z0 aus dem IFC-Bericht")
    return wurzel


SPRUNG = [("Formate", "Dateiformate"), ("Daten", "Daten"), ("Modelleinstellungen", "#kat-modell"), ("IFC", "Archicad-IFC"),
          ("2D-Pläne", "#kat-2d"), ("Informations-DWG", "Informations-DWG"), ("Modellbau", "#kat-modellbau"),
          ("Erweitert", "#kat-erweitert")]


def _springen(ziel):
    js = ("(()=>{const t=%r; let el=null; if(t.startsWith('#')){el=document.querySelector(t);} else {"
          "el=[...document.querySelectorAll('.q-expansion-item')].find(e=>e.offsetParent&&e.innerText.trim().startsWith(t));"
          "if(el&&!el.classList.contains('q-expansion-item--expanded')){const h=el.querySelector('.q-item'); if(h)h.click();}}"
          "if(el)el.scrollIntoView({behavior:'smooth',block:'start'});})()") % ziel
    ui.run_javascript(js)


def ebenen_karte(p):
    """Auswahl der Ebenen (welche Teile in IFC und DXF) – gehört zu den Einstellungen; gefüllt, sobald Daten geladen sind."""
    from . import ebenen
    with ui.column().classes("w-full") as wurzel:
        with karte("Ebenen: welche Teile in IFC und DXF", SCHIEFER, offen=False):
            box = ui.column().classes("w-full")
            ebenen.registrieren(box, p)
    return wurzel


def _unter_stil(col):
    """Karte, die in eine Sammelkarte wandert: eingerückt mit farbigem Streifen links."""
    for e in col.descendants():
        if isinstance(e, ui.expansion):
            e.style(f"border-left:3px solid {INK}; background:#fafbfb")
            break


def seite(p, wechsel=None):
    ausg = p["ausgaben"]
    with ui.row().classes("w-full items-center gap-1 q-px-sm").style("max-width:960px; margin:0 auto"):
        ui.label("Springe zu:").classes("text-caption").style(f"color:{GRAU}")
        for text, ziel in SPRUNG:
            ui.chip(text, on_click=lambda z=ziel: _springen(z)).props("dense outline clickable color=primary")
    with ui.scroll_area().style(f"height:calc({HOEHE} - 96px)"):
        with ui.column().classes("w-full gap-3 pr-3").style("max-width:960px; margin:0 auto"):
            leer = ui.card().classes("w-full")
            with leer:
                ui.label("Noch nichts gewählt").classes("text-subtitle1")
                hinweis("Wähle auf der Startseite aus, was am Ende herauskommen soll – hier erscheinen dann die passenden Einstellungen.")

            # Reihenfolge: 1 Voreinstellungen · Kategorien: Daten & Formate · Modelleinstellungen · 2D Pläne · Modellbau · Erweitert
            kats = {}
            kat_regeln = []                                           # (Kopfspalte, Kinder)

            def kategorie(schluessel, titel):
                spalte = ui.column().classes("w-full gap-3")
                with spalte:
                    ui.label(titel).classes("text-subtitle1 text-weight-bold q-mt-md").style(f"color:{INK}") \
                        .props(f"id=kat-{schluessel}")
                    kats[schluessel] = ui.column().classes("w-full gap-3")
                return spalte

            vor = ui.column().classes("w-full gap-3")
            with vor:
                voreinstellungen.karte_zeigen(p, ui.navigate.reload)
            k_daten = kategorie("daten", "Daten & Formate")
            k_modell = kategorie("modell", "Modelleinstellungen")
            k_2d = kategorie("2d", "2D Pläne")
            k_bau = kategorie("modellbau", "Modellbau")
            k_erw = kategorie("erweitert", "Erweitert")

            staging = ui.column().classes("w-full gap-3")
            with staging:
                fk = formate_karte(p)
                eu = einst_umgebung.seiten(p)
                me = ModellEinst(p).seite()
                ek = ebenen_karte(p)
                sk = schnitt_karte(p)
                hk = hoehenlinien_karte(p)
            T, PL = eu.teile, eu.platz
            zp = T.get("zusatzplan")
            zuordnung = {
                "daten": [fk, T.get("daten"), me.teile["modell_daten"]],
                "modell": [T.get("ifc"), T.get("markant"), T.get("genauigkeit"), T.get("buergersteige")],
                "2d": [T.get("lageplan"), T.get("schwarzplan"), T.get("info"), sk],
                "modellbau": [me.teile["laser"], me.teile["druck"], me.teile["holz"]],
                "erweitert": [T.get("koord"), T.get("sonne"), T.get("weitere")],
            }
            for name, kinder in zuordnung.items():
                for el in kinder:
                    if el is not None:
                        el.move(kats[name])
            # Ebenen, Höhenlinien und Zusatzpläne sitzen in der Informations-DWG-Karte, solange diese gewählt ist
            _unter_stil(ek)
            _unter_stil(hk)
            if zp is not None:
                _unter_stil(zp)
            ort = {}

            def platziere(el, name, innen, aussen):
                ziel = innen if innen is not None else aussen
                if ort.get(name) is not ziel:
                    el.move(ziel)
                    ort[name] = ziel

            def pruefen():
                leer.set_visibility(not P.gewaehlt(p))
                sk.set_visibility(bool(ausg.get("schnitt")))
                hk.set_visibility(bool(ausg.get("hoehenlinien")))
                ek.set_visibility(any(ausg.get(k) for k in ("ifc", "lageplan", "schwarzplan", "info_dwg")))
                info = bool(ausg.get("info_dwg"))
                plaene = bool(ausg.get("lageplan") or ausg.get("schwarzplan"))
                platziere(ek, "ebenen", PL["ebenen"] if info else None, kats["2d"] if plaene else kats["modell"])
                platziere(hk, "hoehen", PL["hoehenlinien"], PL["hoehenlinien"])
                if zp is not None:
                    platziere(zp, "zp", PL["zusatzplan"] if info else None, kats["2d"])
                # Kopf einer Kategorie nur, wenn mindestens eine ihrer Karten sichtbar ist
                for name, kinder in zuordnung.items():
                    kats[name].parent_slot.parent.set_visibility(
                        any(el is not None and el.visible for el in kinder) or
                        (name == "modell" and ek.visible and ort.get("ebenen") is kats["modell"]) or
                        (name == "2d" and zp is not None and zp.visible and ort.get("zp") is kats["2d"]) or
                        (name == "2d" and ek.visible and ort.get("ebenen") is kats["2d"]))
            ui.timer(0.4, pruefen)
            pruefen()
    if wechsel:
        with ui.row().classes("w-full justify-end").style("max-width:960px; margin:0 auto; padding:6px 12px 0"):
            ui.button("Weiter: Vorschau & Export", icon="arrow_forward", on_click=lambda: wechsel("export")) \
                .props("unelevated no-caps color=primary")
