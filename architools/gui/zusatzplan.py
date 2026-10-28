"""Zusatzpläne (PDF, Bilder) mit Passpunkten im Gebiet verorten – wird als eigene DXF ausgegeben."""
import os
import sys

from nicegui import ui

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


async def dialog(p, plan=None, datei=None):
    """Verortungs-Dialog. -> Plan-Dict oder None."""
    ZU = _zu()
    plan = dict(plan or {})
    datei = datei or plan.get("datei")
    if not datei or not os.path.exists(datei):
        ui.notify("Plan-Datei nicht gefunden", type="negative")
        return None
    if ZU.ist_pdf(datei) and not ZU.pdf_vorhanden():
        ui.notify("PDF-Pläne brauchen das Paket PyMuPDF (pip install pymupdf). Bilder gehen auch ohne.", type="warning")
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
    zustand = {"offen": None, "ergebnis": None}                         # offen = Punkt im Plan, wartet auf Kartenpunkt
    mitte = p["gebiet"]["mitte_en"]

    def vorschau_png():
        im, faktor = ZU.bild_laden(datei, int(plan["seite"]), 1600)
        ziel = os.path.join(os.path.expanduser("~"), ".architools", "vorschau_plan.png")
        os.makedirs(os.path.dirname(ziel), exist_ok=True)
        im.convert("RGB").save(ziel)
        return ziel, faktor, im.size
    png, faktor, (bw, bh) = vorschau_png()

    with ui.dialog().props("maximized") as dlg, ui.card().classes("w-full h-full no-wrap"):
        with ui.row().classes("w-full items-center"):
            ui.label("Zusatzplan einpassen").classes("text-h6")
            ui.space()
            ui.button("Abbrechen", on_click=lambda: dlg.close()).props("flat")
            ok = ui.button("Übernehmen", icon="check").props("unelevated")
        with ui.row().classes("w-full items-end gap-3"):
            ui.input("Name").bind_value(plan, "name").classes("w-52")
            if ZU.ist_pdf(datei):
                ui.number("Seite", min=1, max=ZU.seitenzahl(datei), step=1).bind_value(plan, "seite").classes("w-24")
                ui.select({"vektor": "Vektoren (echte Linien)", "bild": "als Bild"}, label="Ausgabe") \
                    .bind_value(plan, "modus").classes("w-52")
                ui.number("Maßstab 1:", min=1).bind_value(plan, "massstab").classes("w-28") \
                    .tooltip("Nur PDF: mit bekanntem Maßstab reicht ein Passpunkt")
                ui.number("Drehung °", step=1).bind_value(plan, "drehung").classes("w-28")
            ui.checkbox("Weiß ausblenden (Bild)").bind_value(plan, "weiss_ausblenden")
            ui.checkbox("Text übernehmen (PDF)").bind_value(plan, "text")
        status = hinweis("Schritt 1: im Plan (links) einen Punkt anklicken. Schritt 2: dieselbe Stelle in der Karte (rechts) anklicken.")
        with ui.row().classes("w-full no-wrap gap-3").style("flex:1 1 auto; min-height:0"):
            with ui.column().classes("w-1/2 h-full"):
                bild = ui.interactive_image(url(png), cross=True, on_mouse=lambda e: plan_klick(e), events=["click"]) \
                    .classes("w-full").style("max-height:70vh")
            with ui.column().classes("w-1/2 h-full"):
                lat, lon = en_zu_ll(*mitte)
                karte_ = ui.leaflet(center=(lat, lon), zoom=17).classes("w-full").style("height:62vh")
                karte_umriss = {"layer": None}
        tabelle = ui.column().classes("w-full gap-0")

    def marker():
        svg = ""
        for i, pt in enumerate(plan["punkte"]):
            x, y = pt["x"] * faktor, pt["y"] * faktor
            svg += (f'<circle cx="{x}" cy="{y}" r="9" fill="none" stroke="#c8643b" stroke-width="3"/>'
                    f'<text x="{x + 12}" y="{y - 8}" fill="#c8643b" font-size="26" font-weight="bold">{i + 1}</text>')
        if zustand["offen"]:
            x, y = zustand["offen"][0] * faktor, zustand["offen"][1] * faktor
            svg += f'<circle cx="{x}" cy="{y}" r="9" fill="none" stroke="#1f6f78" stroke-width="3" stroke-dasharray="4"/>'
        bild.content = svg

    def liste():
        tabelle.clear()
        with tabelle:
            for i, pt in enumerate(plan["punkte"]):
                with ui.row().classes("items-center gap-3"):
                    ui.label(f"Punkt {i + 1}: Plan ({pt['x']:.0f}, {pt['y']:.0f}) ↔ Ost {pt['E']:.1f}, Nord {pt['N']:.1f}").classes("text-body2")
                    ui.button(icon="close", on_click=lambda i=i: loeschen(i)).props("flat dense round")
        umriss()

    def loeschen(i):
        del plan["punkte"][i]
        marker()
        liste()

    def umriss():
        if karte_umriss["layer"] is not None:
            karte_.remove_layer(karte_umriss["layer"])
            karte_umriss["layer"] = None
        try:
            k = ZU.kenngroessen(plan)
        except Exception as e:
            status.text = str(e) if len(plan["punkte"]) >= 2 else status.text
            return
        ll = [list(en_zu_ll(x, y)) for x, y in k["umriss"]]
        karte_umriss["layer"] = karte_.generic_layer(name="polygon", args=[ll, {"color": "#c8643b", "weight": 2, "fillOpacity": 0.15}])
        t = f"Plan liegt {k['breite_m']:.0f} × {k['hoehe_m']:.0f} m groß, gedreht {k['drehung']:.1f}°"
        if "massstab_1_zu" in k:
            t += f", Maßstab ca. 1:{k['massstab_1_zu']:.0f}"
        status.text = t

    def plan_klick(e):
        x, y = float(e.image_x) / faktor, float(e.image_y) / faktor
        zustand["offen"] = (x, y)
        status.text = "Jetzt dieselbe Stelle in der Karte (rechts) anklicken."
        marker()

    def karte_klick(e):
        ll = e.args.get("latlng") or {}
        if "lat" not in ll:
            return
        if not zustand["offen"]:
            status.text = "Erst im Plan (links) einen Punkt anklicken."
            return
        E, N = ll_zu_en(ll["lat"], ll["lng"])
        x, y = zustand["offen"]
        plan["punkte"].append({"x": x, "y": y, "E": E, "N": N})
        zustand["offen"] = None
        marker()
        liste()
    karte_.on("map-click", karte_klick)

    def uebernehmen():
        try:
            ZU.transformation(plan)
        except Exception as ex:
            ui.notify(str(ex), type="warning")
            return
        plan["massstab"] = float(plan["massstab"]) if plan.get("massstab") else None
        plan["seite"] = int(plan.get("seite") or 1)
        zustand["ergebnis"] = plan
        dlg.close()
    ok.on_click(uebernehmen)
    marker()
    liste()
    dlg.open()
    await dlg
    erg = zustand["ergebnis"]
    dlg.delete()
    return erg
