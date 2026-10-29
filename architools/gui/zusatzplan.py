"""Zusatzpläne (PDF, Bilder) mit Passpunkten im Gebiet verorten – wird als eigene DXF ausgegeben."""
import math
import os
import sys

import numpy as np
from nicegui import run, ui

from .. import projekt as P
from .stil import (AKZENT, GRAU, TERRA, en_zu_ll, feld_pfad, hinweis, karte, ll_zu_en, url, waehlen)


def _zu():
    P.kern()
    import ifcmap_zusatz as ZU
    return ZU


def liste_karte(p):
    """Karte in den Umgebungs-Einstellungen: Liste der Zusatzpläne."""
    u = p["umgebung"]
    u.setdefault("zusatzplaene", [])
    with karte("Zusatzpläne (PDF, Bilder) – eigene Pläne einpassen", TERRA, offen=False) as k:
        cb = ui.checkbox("Zusatzpläne mit ausgeben (je Plan eine eigene DXF)").bind_value(u, "zusatzplaene_aktiv")
        box = ui.column().classes("w-full gap-0")

        def zeichnen():
            box.clear()
            with box:
                if not u["zusatzplaene"]:
                    hinweis("Noch kein Plan eingepasst.")
                for i, pl in enumerate(u["zusatzplaene"]):
                    with ui.row().classes("w-full items-center no-wrap").style("border-bottom:1px solid #eee"):
                        ui.icon("map").style(f"color:{TERRA}")
                        ui.label(pl.get("name", "Plan")).classes("grow text-body2")
                        ui.label("Vektoren" if pl.get("modus") == "vektor" else "Bild").classes("text-caption")
                        ui.label(f"{len(pl.get('punkte') or [])} Punkte").classes("text-caption")
                        ui.label(os.path.basename(pl.get("datei", ""))).classes("text-caption").style(f"color:{GRAU}")
                        ui.button(icon="edit", on_click=lambda i=i: bearbeiten(i)).props("flat dense round")
                        ui.button(icon="delete", on_click=lambda i=i: entfernen(i)).props("flat dense round")

        async def neu():
            r = await waehlen("datei", typen=("Pläne (*.pdf;*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.bmp)",))
            if not r:
                return
            await oeffnen_dialog(datei=r)

        async def oeffnen_dialog(datei=None, plan=None, index=None):
            erg = await dialog(p, plan=plan, datei=datei)
            if erg:
                if index is None:
                    u["zusatzplaene"].append(erg)
                    u["zusatzplaene_aktiv"] = True
                else:
                    u["zusatzplaene"][index] = erg
                zeichnen()

        async def bearbeiten(i):
            await oeffnen_dialog(plan=u["zusatzplaene"][i], index=i)

        def entfernen(i):
            del u["zusatzplaene"][i]
            if not u["zusatzplaene"]:
                u["zusatzplaene_aktiv"] = False
            zeichnen()
        with ui.row().classes("gap-2"):
            ui.button("Plan hinzufügen …", icon="add", on_click=neu).props("flat dense")
            pfad = ui.input("… oder Pfad eintippen").classes("w-72")

            async def mit_pfad():
                if pfad.value and os.path.exists(pfad.value):
                    await oeffnen_dialog(datei=pfad.value)
                else:
                    ui.notify("Datei nicht gefunden", type="warning")
            ui.button(icon="check", on_click=mit_pfad).props("flat dense round")
        hinweis("Für Pläne, die es nicht als Geodaten gibt (z. B. ein Lageplan als PDF, ein Screenshot). Du setzt zwei Punkte im "
                "Plan und die passenden in der Karte; der Plan wird verschoben, gedreht und skaliert – nie verzerrt.")
        zeichnen()
    return k


def _merc(lat, lon):
    R = 6378137.0
    return math.radians(lon) * R, R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _merc_zurueck(x, y):
    R = 6378137.0
    return math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2), math.degrees(x / R)


def ueberlagerung(ZU, plan, basis, ziel, max_px=1400):
    """Plan so verzerrungsfrei umgerechnet, dass er als Bild-Overlay genau auf der Karte (Web-Mercator) liegt.
    -> (bounds [[lat0, lon0], [lat1, lon1]]) und schreibt ziel (PNG mit Transparenz)."""
    from PIL import Image
    k = ZU.kenngroessen(plan)
    m = [_merc(*en_zu_ll(*pt)) for pt in k["umriss"]]                      # oben links, oben rechts, unten rechts, unten links
    xs, ys = [a for a, _ in m], [b for _, b in m]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    sk = max_px / max(x1 - x0, y1 - y0)
    W, H = max(2, int((x1 - x0) * sk)), max(2, int((y1 - y0) * sk))
    iw, ih = basis.size
    uv = np.array([[(a - x0) * W / (x1 - x0), (y1 - b) * H / (y1 - y0), 1.0] for a, b in m])
    quelle = np.array([[0, 0], [iw, 0], [iw, ih], [0, ih]], float)
    koef, *_ = np.linalg.lstsq(uv, quelle, rcond=None)                     # Ausgabe-Pixel -> Plan-Pixel
    daten = (koef[0, 0], koef[1, 0], koef[2, 0], koef[0, 1], koef[1, 1], koef[2, 1])
    out = basis.convert("RGBA").transform((W, H), Image.AFFINE, daten, resample=Image.BILINEAR)
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    out.save(ziel)
    return [list(_merc_zurueck(x0, y0)), list(_merc_zurueck(x1, y1))]


async def _suchen(text):
    """Adresse oder Koordinate -> (lat, lon) oder None. Koordinaten gehen offline, Adressen über OpenStreetMap-Nominatim."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        from ..modell.ifcmap_adapter import _mitte
        latlon, en = _mitte(text)
        if en is not None:
            return en_zu_ll(*en)
        return tuple(latlon)
    except Exception:
        pass

    def holen():
        import json
        import urllib.parse
        import urllib.request
        q = urllib.parse.urlencode({"q": text, "format": "json", "limit": 1})
        r = urllib.request.Request("https://nominatim.openstreetmap.org/search?" + q,
                                   headers={"User-Agent": "ZachariasTools/0.1 (Studienprojekt)"})
        with urllib.request.urlopen(r, timeout=15) as f:
            d = json.loads(f.read().decode("utf-8"))
        return (float(d[0]["lat"]), float(d[0]["lon"])) if d else None
    try:
        return await run.io_bound(holen)
    except Exception:
        return None


async def dialog(p, plan=None, datei=None):
    """Einpass-Dialog: ein Punktepaar anklicken, der Plan erscheint durchscheinend auf der Karte, mit Pfeilen nachjustieren."""
    ZU = _zu()
    plan = dict(plan or {})
    datei = datei or plan.get("datei")
    if not datei or not os.path.exists(datei):
        ui.notify("Plan-Datei nicht gefunden", type="negative")
        return None
    if ZU.ist_pdf(datei) and not ZU.pdf_vorhanden():
        ui.notify("PDF-Pläne brauchen das Paket pypdfium2 (pip install pypdfium2). Bilder gehen auch ohne.", type="warning")
        return None
    plan.setdefault("punkte", [])
    plan.update(datei=datei)
    plan.setdefault("seite", 1)
    plan.setdefault("name", ZU.sauberer_name(os.path.splitext(os.path.basename(datei))[0]))
    plan.setdefault("modus", "vektor" if ZU.vektor_anzahl(datei, plan["seite"]) else "bild")
    plan.setdefault("weiss_ausblenden", False)
    plan.setdefault("text", True)
    plan.setdefault("massstab", None)
    plan.setdefault("drehung", 0.0)
    gelesen = None
    if ZU.ist_pdf(datei) and not plan.get("massstab"):
        gelesen = ZU.massstab_erkennen(datei, int(plan["seite"]))
        if gelesen:
            plan["massstab"] = gelesen
    z = {"plan": None, "karte": None, "ergebnis": None, "ovl": None, "pkt": [], "n": 0, "schritt": 5.0,
         "deckung": 0.6, "zoom": 1, "basis": None, "zuletzt": None}
    mitte = p["gebiet"]["mitte_en"]
    ziel_dir = os.path.join(os.path.expanduser("~"), ".architools")

    def vorschau_png():
        im, faktor = ZU.bild_laden(datei, int(plan["seite"]), 1600)
        ziel = os.path.join(ziel_dir, "vorschau_plan.png")
        os.makedirs(ziel_dir, exist_ok=True)
        im.convert("RGB").save(ziel)
        z["basis"] = ZU.weiss_frei(im.convert("RGB"), 18)                  # nur für die Karten-Überlagerung
        return ziel, faktor, im.size
    png, faktor, (bw, bh) = vorschau_png()

    with ui.dialog().props("maximized") as dlg, ui.card().classes("w-full h-full no-wrap gap-2"):
        with ui.row().classes("w-full items-center no-wrap"):
            ui.label("Plan einpassen").classes("text-h6")
            ui.input("Name").bind_value(plan, "name").classes("w-56").props("dense outlined")
            ui.space()
            ui.button("Abbrechen", on_click=lambda: dlg.close()).props("flat")
            ok = ui.button("Fertig – übernehmen", icon="check").props("unelevated color=primary")
        banner = ui.row().classes("w-full items-center no-wrap rounded-borders q-pa-sm").style("background:#fff4e5; border-left:6px solid #c8643b")
        with banner:
            schritt_ico = ui.icon("touch_app", size="md").style("color:#c8643b")
            status = ui.label("").classes("text-subtitle1 grow")
        with ui.row().classes("w-full no-wrap gap-3"):
            with ui.column().classes("gap-1").style("width:48%; min-width:0"):
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    ui.icon("description").style(f"color:{TERRA}")
                    ui.label("Plan").classes("text-weight-bold")
                    ui.space()
                    if ZU.ist_pdf(datei) and ZU.seitenzahl(datei) > 1:
                        ui.number("Seite", min=1, max=ZU.seitenzahl(datei), step=1, format="%.0f").bind_value(plan, "seite") \
                            .classes("w-20").props("dense outlined").on_value_change(lambda e: seite_neu())
                    ui.toggle({1: "1×", 2: "2×", 3: "3×"}, value=1, on_change=lambda e: zoom(e.value)) \
                        .props("dense no-caps size=sm").tooltip("Plan vergrößern, zum genaueren Anklicken")
                with ui.element("div").classes("w-full").style("overflow:auto; max-height:58vh; border:1px solid #ddd"):
                    bild = ui.interactive_image(url(png), cross=True, on_mouse=lambda e: plan_klick(e), events=["click"]) \
                        .style("width:100%")
            with ui.column().classes("gap-1").style("width:52%; min-width:0"):
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    ui.icon("map").style(f"color:{AKZENT}")
                    ui.label("Karte").classes("text-weight-bold")
                    such = ui.input(placeholder="Adresse oder Koordinate suchen …").props("dense outlined clearable").classes("grow")
                    ui.button(icon="search", on_click=lambda: suchen()).props("flat dense round")
                lat, lon = en_zu_ll(*mitte)
                karte_ = ui.leaflet(center=(lat, lon), zoom=17).classes("w-full").style("height:58vh")
                with ui.row().classes("w-full items-center gap-3 no-wrap"):
                    ui.icon("opacity")
                    ui.slider(min=0.1, max=1.0, step=0.05, value=z["deckung"],
                              on_change=lambda e: (z.__setitem__("deckung", e.value), ovl_zeigen())).props("dense").classes("w-40") \
                        .tooltip("Wie durchscheinend der Plan auf der Karte liegt")
                    ui.button("Karte zum Plan", icon="center_focus_strong", on_click=lambda: zum_plan()).props("flat dense no-caps")
        with ui.row().classes("w-full items-center gap-2"):
            ui.label("Feinjustieren").classes("text-weight-bold")
            sch = ui.toggle({0.5: "0,5 m", 2: "2 m", 5: "5 m", 25: "25 m"}, value=5, on_change=lambda e: z.__setitem__("schritt", e.value)) \
                .props("dense no-caps size=sm")
            for sym, dE, dN, tip in (("west", -1, 0, "nach Westen"), ("north", 0, 1, "nach Norden"), ("south", 0, -1, "nach Süden"),
                                     ("east", 1, 0, "nach Osten")):
                ui.button(icon=sym, on_click=lambda dE=dE, dN=dN: schieben(dE, dN)).props("flat dense round").tooltip("Plan " + tip)
            ui.button(icon="rotate_left", on_click=lambda: drehen(1.0)).props("flat dense round").tooltip("1° gegen den Uhrzeigersinn")
            ui.button(icon="rotate_right", on_click=lambda: drehen(-1.0)).props("flat dense round").tooltip("1° im Uhrzeigersinn")
            ui.space()
            ui.button("Punkte löschen", icon="restart_alt", on_click=lambda: neu_beginnen()).props("flat dense no-caps")
        punkte_row = ui.row().classes("w-full items-center gap-1")
        with ui.expansion("Weitere Optionen (Maßstab, Ausgabeform, Drehung)").classes("w-full").props("dense"):
            with ui.row().classes("w-full items-end gap-3"):
                if ZU.ist_pdf(datei):
                    ui.select({"vektor": "Vektoren (echte Linien)", "bild": "als Bild"}, label="Ausgabe") \
                        .bind_value(plan, "modus").classes("w-52")
                    ui.number("Maßstab 1:", min=1).bind_value(plan, "massstab").classes("w-28") \
                        .tooltip("Mit bekanntem Maßstab reicht ein Punktepaar") \
                        .on_value_change(lambda e: aktualisieren())
                    ui.number("Drehung °", step=1).bind_value(plan, "drehung").classes("w-28") \
                        .tooltip("Nur bei einem Punktepaar mit Maßstab: Drehung gegen den Uhrzeigersinn") \
                        .on_value_change(lambda e: aktualisieren())
                ui.checkbox("Weiß ausblenden (Bild)").bind_value(plan, "weiss_ausblenden")
                ui.checkbox("Text übernehmen (PDF)").bind_value(plan, "text")

    # ------------------------------------------------------------ Hilfen
    def meldung(text, farbe="orange", icon="touch_app"):
        status.text = text
        c = {"orange": ("#fff4e5", "#c8643b"), "gruen": ("#e8f4ea", "#2e7d32"), "rot": ("#fdecea", "#b00020")}[farbe]
        banner.style(f"background:{c[0]}; border-left:6px solid {c[1]}")
        schritt_ico.props(f"name={icon}")
        schritt_ico.style(f"color:{c[1]}")

    def marker():
        svg = ""
        for i, pt in enumerate(plan["punkte"]):
            x, y = pt["x"] * faktor, pt["y"] * faktor
            r = max(9, bw / 110)
            svg += (f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="#c8643b" stroke-width="{r / 3}"/>'
                    f'<text x="{x + r * 1.3}" y="{y - r}" fill="#c8643b" font-size="{r * 2.6}" font-weight="bold">{i + 1}</text>')
        if z["plan"]:
            x, y = z["plan"][0] * faktor, z["plan"][1] * faktor
            r = max(9, bw / 110)
            svg += f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="#1f6f78" stroke-width="{r / 3}" stroke-dasharray="4"/>'
        bild.content = svg

    def karte_punkte():
        for lay in z["pkt"]:
            karte_.remove_layer(lay)
        z["pkt"] = []
        for i, pt in enumerate(plan["punkte"]):
            la, lo = en_zu_ll(pt["E"], pt["N"])
            z["pkt"].append(karte_.generic_layer(name="circleMarker", args=[[la, lo], {"radius": 7, "color": "#c8643b", "weight": 3, "fillOpacity": 0.2}]))
        if z["karte"]:
            la, lo = z["karte"]
            z["pkt"].append(karte_.generic_layer(name="circleMarker", args=[[la, lo], {"radius": 7, "color": "#1f6f78", "weight": 3, "dashArray": "3", "fillOpacity": 0.2}]))

    def liste():
        punkte_row.clear()
        with punkte_row:
            for i, pt in enumerate(plan["punkte"]):
                with ui.chip(f"Punkt {i + 1}", icon="place", removable=True, on_value_change=lambda e, i=i: (not e.value) and loeschen(i)) \
                        .props("dense outline color=orange"):
                    pass

    def ovl_zeigen():
        if z["ovl"] is not None:
            karte_.remove_layer(z["ovl"])
            z["ovl"] = None
        if z["zuletzt"]:
            urlq, bounds = z["zuletzt"]
            z["ovl"] = karte_.generic_layer(name="imageOverlay", args=[urlq, bounds, {"opacity": z["deckung"]}])

    def aktualisieren(zoom_auf_plan=False):
        marker()
        karte_punkte()
        liste()
        ok_,n = False, len(plan["punkte"])
        try:
            k = ZU.kenngroessen(plan)
            ok_ = True
        except Exception:
            k = None
        if ok_:
            z["n"] += 1
            ziel = os.path.join(ziel_dir, f"ueber_{z['n'] % 4}.png")
            try:
                bounds = ueberlagerung(ZU, plan, z["basis"], ziel)
                z["zuletzt"] = (url(ziel), bounds)
            except Exception as ex:
                z["zuletzt"] = None
                ui.notify(f"Vorschau auf der Karte nicht möglich: {ex}", type="warning")
        else:
            z["zuletzt"] = None
        ovl_zeigen()
        if z["plan"] and not z["karte"]:
            meldung("② Klicke jetzt dieselbe Stelle in der Karte (rechts).", "orange", "ads_click")
        elif z["karte"] and not z["plan"]:
            meldung("② Klicke jetzt dieselbe Stelle im Plan (links).", "orange", "ads_click")
        elif ok_ and n >= 2:
            f = ZU.abbildung(plan)
            ab = 0.0
            for pt in plan["punkte"]:
                e, nn = f(pt["x"], pt["y"])
                ab = max(ab, math.hypot(float(e) - pt["E"], float(nn) - pt["N"]))
            t = f"Plan sitzt: {k['breite_m']:.0f} × {k['hoehe_m']:.0f} m"
            if "massstab_1_zu" in k:
                t += f", Maßstab 1:{k['massstab_1_zu']:.0f}"
            if n >= 3:
                t += f", größte Abweichung der Punkte {ab:.1f} m"
            t += "."
            if gelesen and "massstab_1_zu" in k and abs(k["massstab_1_zu"] / gelesen - 1) > 0.05:
                meldung(t + f" Achtung: im PDF steht 1:{gelesen} – ein Punkt sitzt wohl falsch (Punkt entfernen und neu setzen).", "rot", "warning")
            elif n >= 3 and ab > max(3.0, 0.01 * k["breite_m"]):
                meldung(t + " Das ist viel – ein Punkt sitzt wohl falsch (Punkt entfernen und neu setzen).", "rot", "warning")
            else:
                meldung(t + " Mit den Pfeilen nachjustieren, dann „Fertig“.", "gruen", "check_circle")
        elif ok_:
            t = "Der Plan liegt auf der Karte"
            if "massstab_1_zu" in k:
                t += f" (Maßstab 1:{k['massstab_1_zu']:.0f}"
                t += ", aus dem PDF gelesen" if gelesen and float(plan.get("massstab") or 0) == gelesen else ""
                t += ")"
            meldung(t + ". Passt es? Mit den Pfeilen verschieben und drehen – oder für genaue Passung einen zweiten Punkt setzen, weit weg vom ersten.",
                    "gruen", "check_circle")
        elif n == 1:
            meldung("③ Ein zweiter Punkt fehlt (Maßstab unbekannt): wähle eine Stelle weit weg vom ersten, im Plan und in der Karte.",
                    "orange", "ads_click")
        else:
            t = "① Klicke einen markanten Punkt im Plan (links), z. B. eine Gebäudeecke oder Kreuzung – dann dieselbe Stelle in der Karte (rechts)."
            if gelesen:
                t += f" Maßstab 1:{gelesen} wurde im PDF gefunden, ein Punktepaar reicht."
            meldung(t, "orange", "touch_app")
        if zoom_auf_plan and z["zuletzt"]:
            karte_.run_map_method("fitBounds", z["zuletzt"][1])

    def paar_pruefen():
        if z["plan"] and z["karte"]:
            E, N = ll_zu_en(*z["karte"])
            plan["punkte"].append({"x": z["plan"][0], "y": z["plan"][1], "E": E, "N": N})
            z["plan"] = z["karte"] = None
            aktualisieren(zoom_auf_plan=len(plan["punkte"]) == 1)
        else:
            aktualisieren()

    def plan_klick(e):
        z["plan"] = (float(e.image_x) / faktor, float(e.image_y) / faktor)
        paar_pruefen()

    def karte_klick(e):
        ll = (e.args or {}).get("latlng") or {}
        if "lat" not in ll:
            return
        z["karte"] = (ll["lat"], ll["lng"])
        paar_pruefen()
    karte_.on("map-click", karte_klick)

    def loeschen(i):
        if i < len(plan["punkte"]):
            del plan["punkte"][i]
            aktualisieren()

    def neu_beginnen():
        plan["punkte"] = []
        z["plan"] = z["karte"] = None
        aktualisieren()

    def schieben(dE, dN):
        if not plan["punkte"]:
            ui.notify("Erst ein Punktepaar setzen.", type="info")
            return
        for pt in plan["punkte"]:
            pt["E"] += dE * z["schritt"]
            pt["N"] += dN * z["schritt"]
        aktualisieren()

    def drehen(grad):
        pk = plan["punkte"]
        if not pk:
            ui.notify("Erst ein Punktepaar setzen.", type="info")
            return
        if len(pk) == 1:
            if not plan.get("massstab"):
                ui.notify("Mit einem Punkt und ohne Maßstab lässt sich nicht drehen – erst zweiten Punkt setzen.", type="info")
                return
            plan["drehung"] = round(float(plan.get("drehung") or 0) + grad, 3)
        else:
            e0 = sum(q["E"] for q in pk) / len(pk)
            n0 = sum(q["N"] for q in pk) / len(pk)
            c, s_ = math.cos(math.radians(grad)), math.sin(math.radians(grad))
            for q in pk:
                dx, dy = q["E"] - e0, q["N"] - n0
                q["E"], q["N"] = e0 + dx * c - dy * s_, n0 + dx * s_ + dy * c
        aktualisieren()

    def zoom(wert):
        bild.style(f"width:{int(wert) * 100}%")

    def seite_neu():
        nonlocal png, faktor, bw, bh
        try:
            plan["seite"] = int(plan["seite"] or 1)
        except (TypeError, ValueError):
            return
        png, faktor, (bw, bh) = vorschau_png()
        bild.set_source(url(png))
        neu_beginnen()

    def zum_plan():
        if z["zuletzt"]:
            karte_.run_map_method("fitBounds", z["zuletzt"][1])
        else:
            karte_.set_center(en_zu_ll(*mitte))

    async def suchen():
        r = await _suchen(such.value)
        if not r:
            ui.notify("Nichts gefunden – Adresse oder „Breite, Länge“ eintippen.", type="warning")
            return
        karte_.set_center(tuple(r))
        karte_.set_zoom(18)
    such.on("keydown.enter", suchen)

    def uebernehmen():
        try:
            ZU.transformation(plan)
        except Exception as ex:
            ui.notify(str(ex), type="warning")
            return
        plan["massstab"] = float(plan["massstab"]) if plan.get("massstab") else None
        plan["seite"] = int(plan.get("seite") or 1)
        z["ergebnis"] = plan
        dlg.close()
    ok.on_click(uebernehmen)
    aktualisieren(zoom_auf_plan=True)
    dlg.open()
    await dlg
    erg = z["ergebnis"]
    dlg.delete()
    return erg
