"""Optionale Zusatzmodule: werden nur geladen, wenn sie neben dem Programm liegen. Sie sind nicht Teil des öffentlichen Repositories.

Suchorte (in dieser Reihenfolge): Umgebungsvariable ZACHARIAS_ZUSATZ, Ordner `zusatz/` neben dem Paket `architools`,
`~/.zacharias-tools/zusatz`. Jedes Modul ist ein Python-Paket (Ordner mit __init__.py) und darf folgende Funktionen anbieten:

    NAME, VERSION, BESCHREIBUNG           Anzeigename, Version, ein Satz (erscheint unter Einstellungen -> Zusatzmodule)
    gui_umgebung(ui, u)                   zusätzliche Einstellungen im Reiter Umgebung (u = Einstellungen, Schlüssel "zusatz")
    gui_modell(ui, g)                     zusätzliche Einstellungen im Reiter Modellbau (g = Einstellungen der Gebäude)
    ifc_ende(ctx)                         nach dem Schreiben der IFC-Elemente (ctx: dict, siehe ifcmap_kern.schreibe_ifc)
    modell_wand(b, ri, i, prof, L, cfg)   Gravurflächen (shapely, Wandkoordinaten s/z in mm) für eine Wand des Modellbaus
    modell_ende(ctx)                      nach dem Modellbau-Lauf (ctx: cfg, buildings, ausgabe, log)
    gui_laser(ui, cfg, h)                 zusätzliche Karte bei den Gelände-Lasercut-Einstellungen (cfg = Modell-Einstellungen,
                                          h = Hilfen der Oberfläche: karte, hinweis, feld_pfad, ausgrauen, TERRA ...)
    raster_flaechen(geom, grau, weite)    Fläche als Linienraster füllen (Aktion "Raster-Gravur"); fehlt das Modul, wird voll graviert
    modell_raster_bild(cfg, welt_grenzen, ausdehnung_mm, zu_welt, log)
                                          Bild als Rastergravur auf die Geländeschichten -> dict(region=Funktion Region->Polygone,
                                          teststreifen=[Teile]) oder None
    gui_layout(ui, w, h)                  zusätzliche Karte im Werkzeug „Lasercut-Layout“ (w = Werkzeug-Einstellungen, h wie bei gui_laser)
    layout_hat_teile(w)                   True, wenn das Modul im Lasercut-Layout eigene Teile beisteuert (dann sind Dateien kein Muss)
    layout_teile(teile, w, cfg, log)      Lasercut-Layout: darf die gelesenen Teile ergänzen (z. B. Rastergravur eines Bildes) -> Liste
                                          zusätzlicher Teile oder None
    LAENDER                               (Dict) Länderprofile wie in ifcmap_laender.PROFILE, z. B. {"sachsen": dict(name=..., epsg=..., ...)}
    WERKZEUGE                             (Liste) eigene Seiten in der linken Werkzeugleiste: je Eintrag ein Dict
                                          {"schluessel": "videoscan", "titel": "Video → 3D", "icon": "videocam",
                                           "seite": f(p, h)}  (p = Projekt, h = Hilfen der Oberfläche, siehe werkzeug_hilfen)

Ein fehlerhaftes Modul bricht nie einen Lauf ab: der Fehler steht im Protokoll.
"""
import importlib.util
import os
import sys

_GELADEN = None


def suchordner():
    out = []
    e = os.environ.get("ZACHARIAS_ZUSATZ")
    if e:
        out.append(e)
    out.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "zusatz"))
    out.append(os.path.join(os.path.expanduser("~"), ".zacharias-tools", "zusatz"))
    return [o for o in out if os.path.isdir(o)]


def module():
    """{Ordnername: Modul}"""
    global _GELADEN
    if _GELADEN is not None:
        return _GELADEN
    _GELADEN = {}
    for ordner in suchordner():
        for n in sorted(os.listdir(ordner)):
            init = os.path.join(ordner, n, "__init__.py")
            if n.startswith((".", "_")) or not os.path.isfile(init) or n in _GELADEN:
                continue
            try:
                spec = importlib.util.spec_from_file_location("zusatz_" + n, init, submodule_search_locations=[os.path.join(ordner, n)])
                m = importlib.util.module_from_spec(spec)
                sys.modules["zusatz_" + n] = m
                spec.loader.exec_module(m)
                _GELADEN[n] = m
            except Exception as e:                       # kaputtes Modul: überspringen
                print("Zusatzmodul %s nicht geladen: %s" % (n, str(e)[:120]), flush=True)
    return _GELADEN


def vorhanden(name=None):
    return bool(module().get(name)) if name else bool(module())


def erstes(hook, *a, log=print, **k):
    """Ergebnis des ersten Moduls, das `hook` anbietet und nicht None zurückgibt; sonst None (Fehler werden protokolliert)."""
    for r in rufe(hook, *a, log=log, **k):
        if r is not None:
            return r
    return None


def hat(hook):
    """True, wenn mindestens ein geladenes Modul den Haken anbietet."""
    return any(callable(getattr(m, hook, None)) for m in module().values())


def liste():
    """[(Ordnername, Name, Version, Beschreibung, Pfad)] aller geladenen Module (für die Anzeige in den Einstellungen)"""
    out = []
    for n, m in module().items():
        out.append((n, getattr(m, "NAME", n), str(getattr(m, "VERSION", "")), getattr(m, "BESCHREIBUNG", ""),
                    os.path.dirname(getattr(m, "__file__", "") or "")))
    return out


def rufe(hook, *a, log=print, **k):
    """Ruft `hook` in allen Modulen auf, die ihn anbieten. -> Liste der Rückgaben (Fehler werden protokolliert)"""
    out = []
    for n, m in module().items():
        fn = getattr(m, hook, None)
        if not callable(fn):
            continue
        try:
            out.append(fn(*a, **k))
        except Exception as e:
            try:
                log("  HINWEIS: Zusatzmodul %s (%s) fehlgeschlagen: %s" % (n, hook, str(e)[:160]))
            except Exception:
                pass
    return out


def werkzeuge():
    """Seiten der Zusatzmodule für die linke Werkzeugleiste -> [dict(schluessel, titel, icon, seite, modul)].
    Ungültige Einträge werden still übergangen; Schlüssel der eingebauten Werkzeuge sind gesperrt."""
    vergeben = {"start", "gebiet", "einst", "export", "layout", "druck3d", "bib", "prog", "quellen"}
    out = []
    for n, m in module().items():
        for w in (getattr(m, "WERKZEUGE", None) or []):
            try:
                k = "zusatz_" + str(w["schluessel"])
                if k in vergeben or not callable(w.get("seite")):
                    continue
                vergeben.add(k)
                out.append({"schluessel": k, "titel": str(w.get("titel") or w["schluessel"]),
                            "icon": str(w.get("icon") or "extension"), "seite": w["seite"], "modul": n})
            except (KeyError, TypeError):
                continue
    return out
