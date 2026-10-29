"""Zirkel Zacharias als kleiner Assistent (Clippy-Stil, aber höflich): eine Figur unten rechts mit Sprechblase.

* Er meldet sich selten: jeden Tipp automatisch nur ein einziges Mal (gemerkt in den Programmeinstellungen), Blase verschwindet
  nach einigen Sekunden von selbst. Er unterbricht nie eine Berechnung und blockiert nichts.
* Ein Klick auf die Figur zeigt den Tipp zur aktuellen Seite (so oft man will).
* Abschalten: in der Blase („Nicht mehr melden“) oder unter Einstellungen → Weiteres. Dann bleibt nur ein kleines Symbol, das nichts sagt.
* Tipps stehen im Wörterbuch TIPPS; sie hängen vom Projekt ab (z. B. was in Schritt 1 gewählt ist).
"""
from nicegui import ui

from .. import einstellungen as ES
from .. import projekt as P
from .stil import GRAU

_A = {"p": None, "blase": None, "text": None, "figur": None, "timer": None, "tab": "start", "cfg": None, "es": None}


def _cfg():
    es = ES.laden()
    c = es.setdefault("assistent", {})
    c.setdefault("an", True)
    c.setdefault("gesehen", [])
    return es, c


# ---------------------------------------------------------------- Tipps
def _tipps(tab, p):
    """Liste (id, Text) der Tipps für diese Seite, abhängig vom Projekt. Der erste noch nicht gesehene wird automatisch gezeigt."""
    ausg = p.get("ausgaben", {})
    gew = [k for k in P.AUSGABEN if ausg.get(k)]
    hat_umg = any(P.AUSGABEN[k][4] == "umgebung" for k in gew)
    hat_modell = any(k in gew for k in ("laser", "druck"))
    t = []
    if tab == "start":
        if not gew:
            t.append(("start_leer", "Hallo, ich bin Zirkel Zacharias. Wähle hier, was am Ende herauskommen soll – die Einstellungen "
                                    "danach richten sich ganz nach deiner Auswahl."))
        else:
            t.append(("start_weiter", "Gut. Als Nächstes: der Reiter „Gebiet“ – dort legst du Mittelpunkt und Größe fest."))
    elif tab == "gebiet":
        t.append(("gebiet_karte", "Ein Klick in die Karte setzt den Mittelpunkt. Die Schnittlinie für Schnitt oder Abwicklung zeichnest du ebenfalls hier."))
        if hat_modell:
            t.append(("gebiet_massstab", "Der Maßstab des Modells steht auch hier – er bestimmt, wie viele Platten und wie viel Laserzeit es gibt."))
    elif tab == "einst":
        t.append(("einst_ordnung", "Die Kacheln folgen deiner Auswahl aus Schritt 1: oben das Allgemeine, danach je Export eine Kachel. "
                                   "Oben die „Springe zu“-Knöpfe helfen beim Navigieren."))
        if hat_umg:
            t.append(("einst_ebenen", "Welche Ebenen in IFC und DXF landen, wählst du in der Kachel „Ebenen“ – sie füllt sich, sobald Daten geladen sind."))
    elif tab == "export":
        t.append(("export_vorschau", "„Vorschau laden“ rechnet genauso lang wie der Export. Du kannst auch gleich exportieren – "
                                     "die 3D-Ansicht und der Lageplan erscheinen dann trotzdem."))
        t.append(("export_ordner", "Wohin der Export kommt, stellst du links unter „Wohin kommt der Export?“ ein."))
    elif tab == "quellen":
        t.append(("quellen", "Für Pläne und Arbeiten bitte die Quellenvermerke übernehmen – die fertige Fassung liegt als QUELLEN.txt im Ausgabeordner."))
    elif tab == "prog":
        t.append(("prog_aus", "Mich kannst du hier unter „Weiteres“ abschalten. Ich bin dann still."))
    elif tab in ("layout", "druck3d"):
        t.append((f"{tab}_info", "Hier legst du Teile von Hand auf Platten. Alles andere macht der Export ohnehin selbst."))
    return t


# ---------------------------------------------------------------- Anzeige
def _verstecken():
    b = _A["blase"]
    if b is not None:
        b.set_visibility(False)


def sag(text, tipp_id=None, sekunden=16, immer=False):
    """Sprechblase zeigen. tipp_id: nur einmal je Installation (immer=True: egal). Ist der Assistent aus, bleibt er still."""
    if _A["blase"] is None:
        return
    es, c = _cfg()
    if not c["an"]:
        return
    if tipp_id and not immer and tipp_id in c["gesehen"]:
        return
    if tipp_id and tipp_id not in c["gesehen"]:
        c["gesehen"].append(tipp_id)
        ES.speichern(es)
    _A["text"].text = text
    _A["blase"].set_visibility(True)
    if _A["timer"] is not None:
        try:
            _A["timer"].cancel()
        except Exception:
            pass
    with _A["wurzel"]:
        _A["timer"] = ui.timer(sekunden, _verstecken, once=True)


def zu(tab):
    """Die Seite hat gewechselt: ein noch nicht gezeigter Tipp zu dieser Seite erscheint (nach kurzer Pause)."""
    if _A["blase"] is None:
        return
    _A["tab"] = tab
    _verstecken()
    es, c = _cfg()
    if not c["an"]:
        return

    def zeigen():
        if _A["tab"] != tab:
            return
        for tid, text in _tipps(tab, _A["p"]):
            if tid not in c["gesehen"] and tid not in _cfg()[1]["gesehen"]:
                sag(text, tid)
                return
    with _A["wurzel"]:
        ui.timer(1.2, zeigen, once=True)


def tipp_jetzt():
    """Klick auf die Figur: der erste Tipp zu dieser Seite (auch ein schon gesehener)."""
    es, c = _cfg()
    if not c["an"]:
        c["an"] = True
        ES.speichern(es)
        _A["figur"].classes(remove="assistent-still")
    tipps = _tipps(_A["tab"], _A["p"])
    if not tipps:
        sag("Hier fällt mir gerade nichts ein – frag mich auf einer anderen Seite.", immer=True)
        return
    # reihum durch die Tipps der Seite
    i = (_A.get("rund", {}).get(_A["tab"], -1) + 1) % len(tipps)
    _A.setdefault("rund", {})[_A["tab"]] = i
    sag(tipps[i][1], tipps[i][0], immer=True)


def ausschalten():
    es, c = _cfg()
    c["an"] = False
    ES.speichern(es)
    _verstecken()
    if _A["figur"] is not None:
        _A["figur"].classes(add="assistent-still")


def start(p):
    """Baut Figur und Blase (unten rechts, über allem, ohne Klicks zu blockieren)."""
    from . import eier
    _A["p"] = p
    es, c = _cfg()
    ui.add_css("""
    .assistent-figur { cursor:pointer; animation: assistent-wippen 4.5s ease-in-out infinite; }
    .assistent-figur.assistent-still { opacity:.35; animation:none; }
    .assistent-figur:hover { opacity:1; }
    @keyframes assistent-wippen { 0%,100% { transform:translateY(0) } 50% { transform:translateY(-3px) } }
    """)
    wurzel = ui.element("div").style("position:fixed; right:18px; bottom:66px; z-index:60; display:flex; flex-direction:column; "
                                     "align-items:flex-end; gap:4px; pointer-events:none")
    _A["wurzel"] = wurzel
    with wurzel:
        blase = ui.card().classes("p-3").style(f"max-width:300px; pointer-events:auto; border:1px solid {GRAU}55; "
                                               "border-radius:14px 14px 4px 14px; background:#fffef7")
        with blase:
            _A["text"] = ui.label("").classes("text-body2")
            with ui.row().classes("w-full justify-end gap-1 no-wrap"):
                ui.button("Nicht mehr melden", on_click=ausschalten).props("flat dense no-caps size=sm color=grey-7")
                ui.button("Ok", on_click=_verstecken).props("flat dense no-caps size=sm color=primary")
        blase.set_visibility(False)
        _A["blase"] = blase
        figur = ui.element("div").classes("assistent-figur").style("pointer-events:auto") \
            .tooltip("Zirkel Zacharias – ein Klick für einen Tipp zu dieser Seite")
        with figur:
            eier.icon(64)
        figur.on("click", tipp_jetzt)
        _A["figur"] = figur
        if not c["an"]:
            figur.classes(add="assistent-still")
    zu("start")
