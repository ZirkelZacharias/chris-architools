"""Gemeinsame Bausteine der Oberfläche: Farben, Hilfsfunktionen, Dateiauswahl, Hintergrundlauf, 3D-Ansicht."""
import os
import queue
import subprocess
import sys
import traceback

from nicegui import app, run, ui

# Farbwelt wie IFCmap / Modellbau-Toolbox
# Schlichte Farbwelt: Graphit und Weiß, zwei Akzente – Petrol (Auswahl, Navigation) und Terrakotta (Hauptaktion, Zeichnen)
BG, KARTE, AKZENT, AKZENT_HELL = "#f6f6f4", "#ffffff", "#1f6f78", "#e5f0f1"
TEXT, GRAU, LINIE = "#1d2329", "#6b737b", "#e4e4df"
INK, TERRA, OCKER, SALBEI, SCHIEFER = "#1d2329", "#c8643b", "#d19a2b", "#5f8f6b", "#3d6a9e"
FARBE_LASER, FARBE_DRUCK, FARBE_GRAVUR = "#d6bf96", "#7fb3c4", "#2b2f33"

WASSERZEICHEN = "Archicad-Bildungsversion"
PAKET = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BILD = os.path.join(PAKET, "system", "bilder", "abschluss.jpg")
MASKOTT = os.path.join(PAKET, "system", "bilder", "maskottchen.gif")
NATIVE = {"an": False}
FREIGABE = set()                         # Ordner, deren Dateien die Oberfläche anzeigen darf
HOEHE = "calc(100vh - 156px)"            # Arbeitsbereich unter Kopf und Reitern

AKTION_TEXT = {"ritzen": "ritzen (blau)", "gravieren": "gravieren (schwarze Fläche)",
               "raster": "Raster-Gravur (experimentell)",
               "schneiden": "schneiden (rot)", "aus": "aus"}


def _ohne_raster():
    """Die Aktion „Raster-Gravur“ gibt es nur, wenn das Zusatzmodul (Rastergravur) installiert ist."""
    try:
        from .. import zusatz
        if not zusatz.hat("raster_flaechen"):
            AKTION_TEXT.pop("raster", None)
    except Exception:
        AKTION_TEXT.pop("raster", None)


_ohne_raster()


def aktion_ok(d, key):
    """Gespeicherte Aktion „raster“ ohne Zusatzmodul -> „gravieren“ (sonst kennt die Auswahl den Wert nicht)."""
    if d.get(key) == "raster" and "raster" not in AKTION_TEXT:
        d[key] = "gravieren"


MASSSTAEBE = {50: "1:50", 100: "1:100", 200: "1:200", 250: "1:250", 500: "1:500", 750: "1:750", 1000: "1:1000",
              1250: "1:1250", 2000: "1:2000", 2500: "1:2500", 5000: "1:5000", 10000: "1:10000"}

CSS = f"""
.stempel {{ position:absolute; z-index:650; pointer-events:none; left:12px; bottom:52px;
  border:1px solid #3f4fae; color:#3f4fae; padding:1px 6px;
  font: 600 8px/1.2 Arial, sans-serif; letter-spacing:.05em; opacity:.4; background:rgba(255,255,255,.35); }}
.log-bild {{ background-image: linear-gradient(rgba(255,255,255,.88), rgba(255,255,255,.88)), url('/bild/abschluss.jpg');
  background-size: cover; background-position: center; }}
.q-field--disabled {{ opacity: .45 !important; }}
.gesperrt {{ opacity: .4; pointer-events: none; filter: grayscale(1); }}
.fertig-stempel {{ position:absolute; right:28px; bottom:22px; transform: rotate(-6deg);
  border:4px solid {SALBEI}; color:{SALBEI}; padding:4px 18px; font: 700 28px Arial; letter-spacing:.12em;
  background: rgba(255,255,255,.75); pointer-events:none; z-index:5; }}
.ausgabe-kachel {{ border: 1.5px solid {LINIE}; transition: border-color .15s, background .15s; cursor:pointer; }}
.ausgabe-kachel:hover {{ border-color: #b9c4c6; }}
.ausgabe-kachel.an {{ background: {AKZENT_HELL}; border-color: {AKZENT}; }}
body, .q-field, .q-btn, .q-tab {{ font-family: -apple-system, "Segoe UI", "Helvetica Neue", Roboto, Arial, sans-serif; }}
.q-card {{ box-shadow: none !important; border: 1px solid {LINIE}; border-radius: 12px; }}
.q-expansion-item {{ border: 1px solid {LINIE}; border-radius: 12px; background:#fff; overflow:hidden; }}
.q-expansion-item .q-item {{ min-height: 44px; }}
.schwebend {{ position:absolute; z-index:1200; }}
.glas {{ background: rgba(255,255,255,.96); border-radius: 12px; box-shadow: 0 4px 18px rgba(20,30,40,.18); }}
.q-tabs--dense .q-tab {{ min-height: 42px; }}
.schritt-tab {{ color:{GRAU}; text-transform:none; }}
.q-btn.hauptaktion {{ background: {TERRA} !important; color:#fff; font-weight:600; }}

@keyframes zeiger {{ 0%,100% {{ transform: translateX(0); }} 50% {{ transform: translateX(-3px); }} }}
.maskott {{ position:fixed; right:18px; bottom:42px; z-index:3000; cursor:pointer; filter: drop-shadow(0 2px 4px rgba(0,0,0,.3)); }}
.q-drawer .q-item {{ border-radius: 8px; margin: 2px 6px; }}
.q-drawer .q-item--active {{ background: rgba(255,255,255,.14); color: #fff !important; }}
.q-drawer .q-item:hover {{ background: rgba(255,255,255,.08); }}
html, body {{ overflow: hidden; }}
"""


# ------------------------------------------------------------------ Koordinaten
def _trans():
    from pyproj import Transformer
    if not hasattr(_trans, "t"):
        _trans.t = (Transformer.from_crs("EPSG:25833", "EPSG:4326", always_xy=True),
                    Transformer.from_crs("EPSG:4326", "EPSG:25833", always_xy=True))
    return _trans.t


def en_zu_ll(e, n):
    lon, lat = _trans()[0].transform(e, n)
    return lat, lon


def ll_zu_en(lat, lon):
    return _trans()[1].transform(lon, lat)


def konvergenz(e, n):
    """Winkel (Grad) zwischen Gitter-Nord (UTM) und wahrem Norden am Punkt; negativ = Gitter-Nord liegt westlich."""
    import math
    lat0, lon0 = en_zu_ll(e, n)
    lat1, lon1 = en_zu_ll(e, n + 1000.0)
    return math.degrees(math.atan2((lon1 - lon0) * math.cos(math.radians(lat0)), lat1 - lat0))


def mm_text(v):
    return f"{float(v):g}".replace(".", ",")


# ------------------------------------------------------------------ Dateien
def oeffnen(pfad):
    if not pfad or not os.path.exists(pfad):
        ui.notify("Datei/Ordner nicht gefunden", type="warning")
        return
    if sys.platform.startswith("win"):
        os.startfile(pfad)
    elif sys.platform == "darwin":
        subprocess.call(["open", pfad])
    else:
        subprocess.call(["xdg-open", pfad])


def url(pfad):
    FREIGABE.add(os.path.dirname(os.path.abspath(pfad)))
    from urllib.parse import quote
    return "/datei?p=" + quote(os.path.abspath(pfad)) + f"&t={os.path.getmtime(pfad):.0f}"


@app.get("/datei")
def _datei(p: str, t: str = ""):
    from fastapi.responses import FileResponse, Response
    p = os.path.abspath(p)
    if os.path.dirname(p) not in FREIGABE or not os.path.isfile(p):
        return Response(status_code=404)
    return FileResponse(p)


@app.get("/bild/abschluss.jpg")
def _bild():
    from fastapi.responses import FileResponse, Response
    return FileResponse(BILD) if os.path.exists(BILD) else Response(status_code=404)


@app.get("/bild/maskottchen.gif")
def _maskott():
    from fastapi.responses import FileResponse, Response
    return FileResponse(MASKOTT) if os.path.exists(MASKOTT) else Response(status_code=404)


async def waehlen(art="datei", mehrere=False, typen=(), name="projekt.architools.json"):
    """Datei-/Ordnerdialog des Fensters. Im Browser-Modus: Hinweis, Pfad bitte eintippen."""
    if not NATIVE["an"]:
        ui.notify("Dateiauswahl gibt es nur im Programmfenster – bitte den Pfad ins Feld eintragen.", type="info")
        return None
    import webview
    FD = getattr(webview, "FileDialog", None)
    t = {"datei": FD.OPEN if FD else webview.OPEN_DIALOG, "ordner": FD.FOLDER if FD else webview.FOLDER_DIALOG,
         "speichern": FD.SAVE if FD else webview.SAVE_DIALOG}[art]
    kw = {"allow_multiple": mehrere}
    if typen:
        kw["file_types"] = tuple(typen) + ("Alle Dateien (*.*)",)
    if art == "speichern":
        kw = {"save_filename": name}
    r = await app.native.main_window.create_file_dialog(t, **kw)
    if not r:
        return None
    if isinstance(r, str):
        r = [r]
    return list(r) if mehrere else r[0]


# ------------------------------------------------------------------ Bausteine
def karte(titel, farbe=AKZENT, offen=True):
    """Aufklappbare Karte im IFCmap-Stil (farbiger Streifen links)."""
    return ui.expansion(titel, value=offen).classes("w-full").props("header-class=text-weight-medium dense")


def ausgrauen(bereich, schalter):
    """Bereich grau und nicht bedienbar, solange der Schalter aus ist."""
    def f(_=None):
        if schalter.value:
            bereich.classes(remove="gesperrt")
        else:
            bereich.classes(add="gesperrt")
    schalter.on_value_change(f)
    f()


def hinweis(text):
    return ui.label(text).classes("text-caption").style(f"color:{GRAU}")


def hinweis_info(kurz, lang):
    """Kurzer Hinweis, der ganze Erklärtext steht im Info-Symbol (schont die Übersicht)."""
    with ui.row().classes("items-center gap-1 no-wrap"):
        ui.label(kurz).classes("text-caption").style(f"color:{GRAU}")
        ic = ui.icon("info_outline", size="xs").style(f"color:{GRAU}; cursor:help")
        ic.tooltip(lang).classes("text-body2").style("max-width:360px")


def feld_pfad(label, obj, key, art="datei", typen=(), mehrere=False):
    with ui.row().classes("w-full items-center no-wrap gap-1") as zeile:
        if mehrere:
            inp = ui.input(label, value="; ".join(obj.get(key) or [])).classes("grow")
            inp.on_value_change(lambda e: obj.__setitem__(key, [x.strip() for x in str(e.value).split(";") if x.strip()]))
        else:
            inp = ui.input(label).bind_value(obj, key).classes("grow")

        async def wahl():
            r = await waehlen(art, mehrere, typen)
            if r:
                if mehrere:
                    obj[key] = list(obj.get(key) or []) + r
                    inp.value = "; ".join(obj[key])
                else:
                    obj[key] = r
                    inp.value = r
        ui.button(icon="folder_open", on_click=wahl).props("flat dense round").tooltip("Auswählen")
    return zeile


def zahl_feld(label, obj, key, breite="w-28", **kw):
    """Zahlenfeld, das auch leer sein darf (None) und Komma als Dezimaltrenner versteht."""
    return ui.number(label, **kw).bind_value(obj, key).classes(breite)


class Lauf:
    """Rechnen im Hintergrund mit Protokoll-Ausgabe und Fortschritt."""

    def __init__(self, logel, knoepfe, spinner, fertig=None, balken=None, status=None):
        self.q = queue.Queue()
        self.log, self.knoepfe, self.spinner, self.fertig = logel, list(knoepfe), spinner, fertig
        self.balken, self.status = balken, status
        self.fortschritt = (0.0, "")
        self.pop_67 = None                    # wird von eier.py gesetzt
        self.bericht_pfad = None              # Funktion -> Pfad der protokoll.txt (None: kein Protokoll)
        self.zeilen = []
        self.anhaengen = False
        ui.timer(0.2, self._leeren)

    def prog(self, x, text=""):
        self.fortschritt = (float(x), text or self.fortschritt[1])

    def _leeren(self):
        n = 0
        while not self.q.empty() and n < 400:
            self.log.push(self.q.get())
            n += 1
        if self.balken is not None and self.spinner.visible:
            self.balken.value = self.fortschritt[0]
            if self.status is not None:
                self.status.text = self.fortschritt[1]
            if self.pop_67 is not None:
                self.pop_67(self.fortschritt[0])

    async def starten(self, fn, *args):
        if self.anhaengen:                    # zweiter Teil desselben Vorgangs: Protokoll und Bericht weiterführen
            self.anhaengen = False
            self.zeilen.append("")
        else:
            self.log.clear()
            self.zeilen = []
        self.fortschritt = (0.0, "")
        if self.fertig is not None:
            self.fertig.set_visibility(False)
        for k in self.knoepfe:
            k.disable()
        self.spinner.set_visibility(True)
        if self.balken is not None:
            self.balken.set_visibility(True)
        try:
            def _put(z):
                self.zeilen.append(str(z))
                self.q.put(z)
            r = await run.io_bound(fn, *args, _put, self.prog)
            if self.fertig is not None and r:
                self.fertig.set_visibility(True)
            return r
        except Exception as e:
            self.q.put(f"FEHLER: {e}")
            self.q.put(traceback.format_exc()[-2500:])
            ui.notify(f"Fehler: {e}", type="negative", multi_line=True)
            return None
        finally:
            for k in self.knoepfe:
                k.enable()
            self.spinner.set_visibility(False)
            if self.balken is not None:
                self.balken.set_visibility(False)
            if self.status is not None:
                self.status.text = ""
            self._leeren()
            self.bericht_schreiben()

    def bericht_schreiben(self):
        """Das Programmprotokoll des letzten Laufs als protokoll.txt in den Ausgabeordner – zum Weitergeben bei Fehlern."""
        if not self.bericht_pfad or not self.zeilen:
            return
        try:
            pfad = self.bericht_pfad()
            os.makedirs(os.path.dirname(pfad), exist_ok=True)
            with open(pfad, "w", encoding="utf-8") as fh:
                fh.write("\n".join(self.zeilen) + "\n")
        except Exception:
            pass


def vorschau_svgs(svgs, ordner):
    """Laser-SVGs mit sichtbar dicken Linien für die Anzeige (Original bleibt Haarlinie)."""
    os.makedirs(ordner, exist_ok=True)
    out = []
    for s in svgs:
        try:
            t = open(s, encoding="utf-8").read().replace('stroke-width="0.001"', 'stroke-width="0.6"')
            ziel = os.path.join(ordner, os.path.basename(s))
            open(ziel, "w", encoding="utf-8").write(t)
            out.append(ziel)
        except OSError:
            pass
    return out


def szene3d(teile, b, h, hoehe=520, breite=None, mitte=None, z_faktor=1.0, zoom=True):
    """3D-Ansicht. teile: [(Pfad, Farbe oder None)]: .stl mit Farbe, .glb/.gltf mit eigenen Farben.
    Weite Sichtweite, Kamera passend zur Modellgröße. zoom=False: das Mausrad zoomt nicht, sondern blättert die Seite weiter
    (für Ansichten in langen Seiten wie dem Ergebnis, damit man durch alle Ergebnisse scrollen kann)."""
    L_ = max(b, h, 50.0)
    cam = ui.scene.perspective_camera(fov=45, near=max(0.05, L_ / 2000), far=L_ * 40)
    kw = {"width": breite} if breite else {}
    with ui.scene(height=hoehe, grid=False, background_color="#eef1f3", camera=cam, **kw) \
            .classes("w-full" if not breite else "") as sc:
        sc.spot_light(distance=L_ * 20, intensity=0.15).move(L_, -L_, L_ * 2)
        for pfad, farbe in teile:
            if not pfad or not os.path.exists(pfad):
                continue
            if pfad.lower().endswith((".glb", ".gltf")):
                o = sc.gltf(url(pfad))
            else:
                o = sc.stl(url(pfad)).material(farbe or FARBE_LASER)
            if z_faktor and abs(z_faktor - 1.0) > 1e-6:               # Ansicht künstlich überhöhen (nur die Darstellung, nicht die Dateien)
                o.scale(1, 1, float(z_faktor))
    if not zoom:
        ui.run_javascript("setTimeout(()=>{const e=document.getElementById('c%d'); if(e) e.addEventListener('wheel', "
                          "ev=>ev.stopImmediatePropagation(), {capture:true, passive:true});}, 300)" % sc.id)
    cx, cy = mitte if mitte else (b / 2, h / 2)
    sc.move_camera(x=cx, y=cy - L_ * 0.95, z=L_ * 1.1, look_at_x=cx, look_at_y=cy, look_at_z=0, duration=0)
    return sc
