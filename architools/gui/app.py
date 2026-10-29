"""Zacharias Tools – Oberfläche (NiceGUI, eigenes Fenster; Fallback: Browser)."""
import os

from nicegui import ui

from .. import VERSION
from . import assistent, eier, einst, export, quellen_seite, start as start_seite, stil, zustand as Z
from .einst_modell import ModellEinst
from .gebiet import Gebiet
from .stil import AKZENT, BG, CSS, GRAU, INK, LINIE, NATIVE, OCKER, SCHIEFER, TERRA, TEXT, WASSERZEICHEN
from .werkzeuge import Werkzeuge

ABLAUF = [("start", "1 · Start", "flag"), ("gebiet", "2 · Gebiet", "map"),
          ("einst", "3 · Einstellungen", "tune"), ("export", "4 · Vorschau & Export", "view_in_ar")]
WERKZEUGE = [("layout", "Lasercut-Layout", "grid_view"), ("druck3d", "3D-Druck-Layout", "view_in_ar"),
             ("bib", "Materialbibliothek", "inventory_2"), ("prog", "Einstellungen", "settings"),
             ("quellen", "Quellen", "menu_book")]


def seite():
    for el in (ui.input, ui.number, ui.select):
        el.default_props("dense")
    ui.add_css(CSS)
    ui.colors(primary=AKZENT, secondary=TERRA, accent=OCKER)
    ui.query("body").style(f"background:{BG}; color:{TEXT}")
    p = Z.projekt()
    ui.page_title(f"Zacharias Tools – {WASSERZEICHEN}")

    def speichern():
        try:
            Z.speichern(p)
        except Exception:
            pass

    with ui.header().classes("items-center gap-3 py-2").style(f"background:{INK}"):
        ui.label("Zacharias Tools").classes("text-h6 text-white cursor-default") \
            .style("font-family: Georgia, serif; font-style: italic").on("click", eier.titel_klicks())
        ui.label(WASSERZEICHEN).style(
            "position:absolute; left:50%; top:50%; transform:translate(-50%,-50%); text-decoration:underline; "
            "text-underline-offset:3px; color:#c9d3dd; font-size:13px; letter-spacing:.06em; pointer-events:none")
        ui.space()
        lbl = ui.label("").classes("text-caption").style("color:#c9d3dd")
        stand = {"zeit": ""}

        def status():
            if p.get("_pfad"):
                lbl.text = f"{p['name']}  ·  gespeichert {stand['zeit']}" if stand["zeit"] else p["name"]
            else:
                lbl.text = p["name"] + "  ·  noch nicht gespeichert"
        ui.timer(0.8, status)

        def sp(still=False):
            try:
                Z.speichern(p)
            except Exception as e:
                ui.notify(f"Speichern nicht möglich: {e}", type="negative")
                return
            import time
            stand["zeit"] = time.strftime("%H:%M")
            if not still:
                ui.notify(f"Gespeichert: {p.get('_pfad', '')}", type="positive")
        upd_btn = ui.button("Update verfügbar", icon="system_update_alt") \
            .props("unelevated dense no-caps color=secondary").classes("q-px-sm")
        upd_btn.set_visibility(False)

        async def update_pruefen():
            from .. import STAND, updatehinweis as UH, einstellungen as _ES
            from nicegui import run
            es = _ES.laden()
            if not es.get("update_pruefen", True):
                return
            info = await run.io_bound(UH.neueste)
            if not UH.ist_neuer(info, STAND, es.get("update_ignoriert", 0)):
                return
            upd_btn.text = f"Update: Build {info['stand']}"
            upd_btn.set_visibility(True)

            with ui.dialog() as dlg, ui.card().style("width:460px"):
                ui.label(f"Neuer Build {info['stand']} verfügbar").classes("text-h6")
                ui.label(f"Installiert ist Build {STAND}. Auf GitHub liegt „{info['titel']}“.").classes("text-body2")
                ui.label("So aktualisierst du: Download-Seite öffnen, das Paket für dein System laden (Windows oder Mac), entpacken und "
                         "wie gewohnt starten. Deine Projekte und Einstellungen bleiben unberührt (sie liegen in deinem Projektordner "
                         "und in .architools im Benutzerordner).").classes("text-body2").style("color:#6b737b")
                with ui.row().classes("w-full justify-end gap-2"):
                    def spaeter_nie():
                        e2 = _ES.laden()
                        e2["update_ignoriert"] = info["stand"]
                        _ES.speichern(e2)
                        upd_btn.set_visibility(False)
                        dlg.close()
                    ui.button("Nicht mehr erinnern", on_click=spaeter_nie).props("flat no-caps")
                    ui.button("Später", on_click=dlg.close).props("flat no-caps")
                    ui.button("Download-Seite öffnen", icon="open_in_new",
                              on_click=lambda: ui.navigate.to(info["url"], new_tab=True)).props("unelevated no-caps color=primary")
            upd_btn.on_click(dlg.open)
        ui.timer(3.0, update_pruefen, once=True)
        ui.button(icon="save", on_click=lambda: sp()).props("flat round color=white dense").tooltip("Speichern (geschieht auch automatisch)")

        def beenden():
            sp(True)
            from nicegui import app as _a
            _a.shutdown()
        ui.button(icon="power_settings_new", on_click=beenden).props("flat round color=white dense") \
            .tooltip("Programm beenden (speichert vorher)")

    panels = None
    tabs_w = None
    sperre = {"an": False}
    items = {}
    arbeit = [k for k, _, _ in ABLAUF]

    def wechsel(name):
        if panels is None:
            return
        sperre["an"] = True
        panels.value = name
        tabs_w.value = name if name in arbeit else None
        for k, it in items.items():
            it.props(add="active" if k == name else None, remove=None if k == name else "active")
        sperre["an"] = False
        assistent.zu(name)

    # ---- Werkzeug-Leiste links: eingeklappt nur Symbole, ausgeklappt mit Namen
    with ui.left_drawer(value=True, fixed=True, bordered=False).props("mini width=232 mini-width=58 behavior=desktop") \
            .classes("p-0").style(f"background:{INK}; color:#dbe3ea") as leiste:
        mini = {"an": True}

        def umschalten():
            mini["an"] = not mini["an"]
            leiste.props(add="mini" if mini["an"] else None, remove=None if mini["an"] else "mini")
            knopf.props(f"icon={'chevron_right' if mini['an'] else 'chevron_left'}")
        with ui.row().classes("w-full items-center no-wrap").style("padding:6px 8px; min-height:48px"):
            knopf = ui.button(icon="chevron_right", on_click=umschalten).props("flat round dense color=white") \
                .tooltip("Werkzeuge ein-/ausklappen")
            ui.label("Werkzeuge").classes("text-caption text-uppercase").style("color:#9fb0bf; letter-spacing:.08em; white-space:nowrap")
        with ui.list().props("dense").classes("w-full"):
            for k, t, ic in WERKZEUGE:
                it = ui.item(on_click=lambda k=k: wechsel(k)).props("clickable").style("color:#dbe3ea")
                with it:
                    with ui.item_section().props("avatar").style("min-width:34px"):
                        ui.icon(ic).style("font-size:24px")
                    with ui.item_section():
                        ui.label(t).style("white-space:nowrap")
                    ui.tooltip(t).props("anchor=center right self=center left")
                items[k] = it

    with ui.row().classes("w-full items-center no-wrap gap-0 q-px-sm").style(f"background:#fff; border-bottom:1px solid {LINIE}"):
        with ui.tabs(value="start", on_change=lambda e: (not sperre["an"]) and e.value and wechsel(e.value)) \
                .props("align=left active-color=primary indicator-color=primary dense inline-label no-caps").style(f"color:{GRAU}") as tabs_w:
            for k, t, ic in ABLAUF:
                ui.tab(k, label=t, icon=ic).classes("schritt-tab")

    me = ModellEinst(p)
    wz = Werkzeuge(p, me)
    with ui.tab_panels(value="start").classes("w-full bg-transparent").props("keep-alive") as panels:
        with ui.tab_panel("start").classes("py-2"):
            start_seite.seite(wechsel, lambda *a, **k: None)
        with ui.tab_panel("gebiet").classes("py-2"):
            Gebiet(p, speichern, wechsel).seite()
        with ui.tab_panel("einst").classes("py-2"):
            einst.seite(p, wechsel)
        with ui.tab_panel("export").classes("py-2"):
            export.seite(p, speichern)
        with ui.tab_panel("layout").classes("py-2"):
            wz.seite_layout()
        with ui.tab_panel("druck3d").classes("py-2"):
            wz.seite_druck()
        with ui.tab_panel("bib").classes("py-2"):
            wz.seite_bibliothek()
        with ui.tab_panel("quellen").classes("py-2"):
            quellen_seite.seite()
        with ui.tab_panel("prog").classes("py-2"):
            wz.seite_einstellungen()
    eier.fuss()
    assistent.start(p)
    ui.timer(12, lambda: sp(True) if p.get("_pfad") else None)


def _frei(port):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as so:
        if os.name != "nt":                                   # unter Linux/Mac zählt ein gerade erst beendetes Programm nicht als „belegt“
            so.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            so.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _laeuft_schon(port):
    """Antwortet auf diesem Port schon dieselbe Programmkopie? -> True"""
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_architools", timeout=2) as r:
            d = json.loads(r.read().decode("utf-8"))
        return d.get("programm") == "ArchItools" and d.get("pfad") == stil.PAKET
    except Exception:
        return False


def _wache_starten(port, sekunden=60):
    """Meldet sich innerhalb von `sekunden` kein Fenster beim Server, öffnet sich die Weboberfläche im Browser."""
    from nicegui import background_tasks

    async def _wache():
        import asyncio
        await asyncio.sleep(sekunden)
        try:
            from nicegui import Client
            verbunden = any(getattr(c, "has_socket_connection", False) for c in list(Client.instances.values()))
        except Exception:
            verbunden = True
        if not verbunden:
            print("Kein Programmfenster erschienen – die Weboberfläche öffnet sich im Browser.", flush=True)
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{port}/")
    background_tasks.create(_wache(), name="fenster-wache")


def start(native=None, port=None, show=True):
    import multiprocessing
    if multiprocessing.current_process().name != "MainProcess":
        # Das Programmfenster läuft als eigener Prozess und lädt dieses Modul noch einmal. Hier darf nichts passieren – sonst fände es
        # den Port belegt und würde zusätzlich die Weboberfläche im Browser öffnen.
        return
    if native is None:
        try:
            import webview  # noqa: F401
            native = True
        except Exception:
            native = False
    if native and os.name == "nt":
        try:                                                  # pythonnet/.NET kann blockiert sein (aus dem Internet geladene Dateien)
            import clr  # noqa: F401
        except Exception as e:
            print("Programmfenster nicht möglich (" + str(e)[:160] + ") – das Programm öffnet sich im Browser.")
            native = False
    NATIVE["an"] = bool(native)
    # Port: ist 8765 belegt (z. B. von einer noch laufenden Kopie), nicht abbrechen
    wunsch = port or 8765
    if not _frei(wunsch):
        if _laeuft_schon(wunsch):
            print(f"Zacharias Tools läuft schon (Port {wunsch}) – öffne die laufende Kopie im Browser.")
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{wunsch}/")
            return
        for p_ in range(wunsch + 1, wunsch + 60):
            if _frei(p_):
                print(f"Port {wunsch} ist belegt – nehme Port {p_}.")
                wunsch = p_
                break
    port = wunsch
    from nicegui import app as _app

    @_app.get("/_architools")
    def _kennung():
        return {"programm": "ArchItools", "pfad": stil.PAKET, "stand": VERSION}
    ui.page("/")(seite)
    kw = dict(title=f"Zacharias Tools – {WASSERZEICHEN}", reload=False, language="de", show_welcome_message=False,
              favicon="📐")
    if native:
        # Nur das Programmfenster öffnen (kein zusätzlicher Browser-Tab). Meldet sich innerhalb von 30 s kein Fenster beim Server, klappt das
        # Fenster nicht (z. B. fehlende WebView-Komponenten): dann öffnet sich die Weboberfläche im Browser.
        _app.on_startup(lambda: _wache_starten(port))
        ui.run(native=True, show=False, window_size=(1500, 950), port=port, **kw)
    else:
        ui.run(port=port, show=show, **kw)
