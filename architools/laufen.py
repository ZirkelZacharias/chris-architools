"""Rechenläufe: Umgebung (IFCmap-Kern), Modellbau (Laser/3D-Druck), Schnitt – mit gemeinsamem Stand im Projekt."""
import copy
import os
import time

from . import einstellungen as ES
from . import projekt as P

_cache = {"key": None, "d": None}


# ------------------------------------------------------------------ Umgebung
def umgebung_laden(p, ausgaben, log=print, prog=None, test=False):
    """Daten laden (einmal je Einstellung; wiederholte Aufrufe nutzen das Ergebnis weiter)."""
    K = P.kern()
    prog = prog or (lambda *a, **k: None)
    cfg = P.umgebung_config(p, ausgaben, test=test)
    # Ebenen und Nutzungs-Zuordnung wirken erst nach dem Laden – sie gehören nicht in den Schlüssel
    key = repr(sorted(((k, v) for k, v in cfg.__dict__.items() if k not in ("ebenen", "overrides")), key=lambda kv: kv[0]))
    if _cache["key"] == key and _cache["d"] is not None:
        d = _cache["d"]
        neu_ue = dict(getattr(cfg, "overrides", None) or {})
        d.cfg.ebenen = getattr(cfg, "ebenen", None)
        if neu_ue != dict(getattr(d.cfg, "overrides", None) or {}):
            d.cfg.overrides = neu_ue
            K.zuordnen(d)
            log("Daten sind schon geladen – Nutzungs-Zuordnung neu angewendet.")
        else:
            log("Daten sind schon geladen (keine Änderung der Einstellungen) – wird weiterverwendet.")
        return d
    d = K.lade(cfg, log=log, prog=prog)
    _cache.update(key=key, d=d)
    return d


def vorschau_aus_daten(d, p, log=print, prog=None, ueberhoehung=1.0, lageplaene=()):
    """2D-Übersicht + 3D-Vorschau (GLB) aus bereits geladenen Umgebungsdaten; optional die fertigen Lagepläne (DXF) als Bild."""
    from . import vorschau as V
    prog = prog or (lambda *a, **k: None)
    ordner = os.path.join(p["ordner"], "ausgabe", ".vorschau")
    os.makedirs(ordner, exist_ok=True)
    prog(0.2, "2D-Übersicht …")
    png = V.plan_bauen(d, os.path.join(ordner, "umgebung.png"), log)
    prog(0.5, "3D-Vorschau …")
    try:
        g = V.glb_bauen(d, os.path.join(ordner, "umgebung.glb"), ueberhoehung, log)
    except Exception as e:
        log(f"  3D-Vorschau nicht möglich: {e}")
        g = {}
    bilder = []
    for i, f in enumerate(lageplaene):
        prog(0.7 + 0.25 * i / max(len(lageplaene), 1), "Lageplan als Bild …")
        b = V.dxf_bild(f, os.path.join(ordner, f"lageplan_{i + 1}.png"), log)
        if b:
            bilder.append(b)
    prog(1.0, "Vorschau fertig")
    return {"png": png, **g, "ordner": ordner, "lageplan_bilder": bilder}


def umgebung_vorschau(p, ausgaben, log=print, prog=None, ueberhoehung=1.0, test=False):
    prog = prog or (lambda *a, **k: None)
    d = umgebung_laden(p, ausgaben, log, lambda x, t="": prog(x * 0.8, t), test)
    r = vorschau_aus_daten(d, p, log, lambda x, t="": prog(0.8 + x * 0.2, t), ueberhoehung)
    return {**r, "daten": d}


def _ausgabe_zuordnen(dateien):
    z = {}
    for f in dateien:
        n = os.path.basename(f).lower()
        if n.endswith((".ifc", ".glb", ".obj", ".mtl", ".stl", ".ply")):
            z.setdefault("ifc", []).append(f)
        elif "lageplan" in n:
            z.setdefault("lageplan", []).append(f)
        elif "schwarzplan" in n:
            z.setdefault("schwarzplan", []).append(f)
        else:
            z.setdefault("info_dwg", []).append(f)
    return z


_NAMEN = {"ifcmap.ifc": "Umgebung.ifc", "ifcmap_2d.dxf": "Informations-DWG.dxf", "ifcmap_lageplan.dxf": "Lageplan.dxf",
          "ifcmap_schwarzplan.dxf": "Schwarzplan.dxf"}


def _umbenennen(dateien, name):
    """Die Dateien des Rechenkerns heißen ifcmap*.* - hier bekommen sie den Projektnamen."""
    out = []
    for f in dateien:
        neu = _NAMEN.get(os.path.basename(f))
        if neu and os.path.exists(f):
            ziel = os.path.join(os.path.dirname(f), f"{name}_{neu}")
            try:
                os.replace(f, ziel)
                f = ziel
            except OSError:
                pass
        out.append(f)
    return out


def umgebung_export(p, ausgaben, log=print, prog=None, test=False):
    K = P.kern()
    prog = prog or (lambda *a, **k: None)
    ausgaben = [a for a in ausgaben if P.AUSGABEN[a][4] == "umgebung"]
    if not ausgaben:
        return {"dateien": []}
    d = umgebung_laden(p, ausgaben, log, lambda x, t="": prog(x * 0.5, t), test)
    erzeugt = K.exportiere(d, log=log, prog=lambda x, t="": prog(0.5 + x * 0.5, t)) or []
    erzeugt = _umbenennen([str(f) for f in erzeugt], P.sicher(p["name"]))
    from . import formate as FM
    fm = p.get("formate") or {}
    oda = ES.laden().get("oda_pfad", "")
    neu = []
    for f in erzeugt:
        if f.lower().endswith(".dxf"):
            neu += FM.zweid_umwandeln([f], fm.get("zweid"), oda, log)
        elif f.lower().endswith(".ifc"):
            neu += FM.ifc_umwandeln(f, fm.get("dreid"), log)
        else:
            neu.append(f)
    erzeugt = neu
    zu = _ausgabe_zuordnen(erzeugt)
    for a in ausgaben:
        if zu.get(a):
            P.stand_setzen(p, a, zu[a])
    return {"dateien": erzeugt, "ordner": d.cfg.ausgabe, "d": d}


# ------------------------------------------------------------------ Modell
def modell_export(p, ausgaben, log=print, prog=None, vorschau=False):
    """Modellbau rechnen. vorschau=True: in den Vorschau-Ordner schreiben und den Stand des Projekts nicht verändern."""
    from .modell import pipeline
    prog = prog or (lambda *a, **k: None)
    laser, druck = "laser" in ausgaben, "druck" in ausgaben
    if not (laser or druck):
        return {}
    cfg = copy.deepcopy(p["modell"])
    cfg["gebiet"] = dict(p["gebiet"])
    cfg["ausgabe_ordner"] = os.path.join(p["ordner"], "ausgabe", ".vorschau", "modell") if vorschau \
        else os.path.join(P.ausgabe_basis(p), "modell")
    cfg["projekt_name"] = P.sicher(p["name"])
    cfg["_basis"] = p["ordner"]
    u = p.get("umgebung", {})                                       # gleiche Netzwerk-Einstellungen wie bei der Umgebung
    cfg["netz"] = {"cafile": u.get("cafile", "") or "", "unsicher": bool(u.get("unsicher", False))}
    prog(0.05, "Gelände und Gebäude laden …")
    szene = pipeline.szene_laden(cfg, log)
    prog(0.3, "Modell berechnen …")
    stats = pipeline.run(cfg, log=log, szene=szene, laser=laser, druck=druck)
    prog(1.0, "Fertig")
    out = stats.get("ausgabe") or cfg["ausgabe_ordner"]
    if vorschau:
        return stats
    for a in ("laser", "druck"):
        if a in ausgaben:
            dat = []
            sub = os.path.join(out, "laser" if (a == "druck" and cfg["gebaeude"].get("modus", "druck") != "druck") else a)
            for r, _, fs in os.walk(sub):
                dat += [os.path.join(r, f) for f in fs][:100]
            P.stand_setzen(p, a, dat, sub)
    return stats


# ------------------------------------------------------------------ Schnitt
def schnitt_export(p, log=print, prog=None):
    if p["schnitt"].get("art") == "abwicklung":
        from . import abwicklung as schnitt
    else:
        from . import schnitt
    r = schnitt.erzeugen(p, log, prog or (lambda *a, **k: None))
    P.stand_setzen(p, "schnitt", r["dateien"], r["ordner"])
    return r


# ------------------------------------------------------------------ Höhenlinien
def hoehenlinien_export(p, log=print, prog=None):
    from . import hoehenlinien
    r = hoehenlinien.erzeugen(p, log, prog or (lambda *a, **k: None))
    P.stand_setzen(p, "hoehenlinien", r["dateien"], r["ordner"])
    return r


# ------------------------------------------------------------------ alles
def alles(p, ausgaben, log=print, prog=None, speichern=True, test=False):
    """Alle gewählten Ausgaben nacheinander. -> {Ausgabe: Ergebnis}"""
    prog = prog or (lambda *a, **k: None)
    log0 = log or print
    zeilen = []

    def log(s=""):                                   # jede Zeile auch für bericht.txt / protokoll.txt merken
        zeilen.append(str(s))
        log0(s)
    gruppen = []
    if any(P.AUSGABEN[a][4] == "umgebung" for a in ausgaben):
        gruppen.append("umgebung")
    if "laser" in ausgaben or "druck" in ausgaben:
        gruppen.append("modell")
    if "schnitt" in ausgaben:
        gruppen.append("schnitt")
    if "hoehenlinien" in ausgaben:
        gruppen.append("hoehenlinien")
    erg = {}
    zeiten = {}
    t0 = time.time()
    for i, g in enumerate(gruppen):
        tg = time.time()
        a0, a1 = i / len(gruppen), (i + 1) / len(gruppen)
        pg = lambda x, t="", a0=a0, a1=a1: prog(a0 + (a1 - a0) * float(x), t)
        log(f"=== {dict(umgebung='Umgebung', modell='Modellbau', schnitt='Geländeschnitt', hoehenlinien='Höhenlinien')[g]} ===")
        try:
            if g == "umgebung":
                erg["umgebung"] = umgebung_export(p, ausgaben, log, pg, test=test)
                try:                                         # Plausibilitäts-Prüfer: meldet Ausreißer (Höhen, Dachformen, Gelände), ändert nichts
                    from . import plausibilitaet
                    meldungen = plausibilitaet.pruefen(erg["umgebung"].get("d"))
                    log(f"Plausibilitätsprüfung: {len(meldungen)} Hinweis(e)")
                    for m in meldungen:
                        log("[Plausibilität] " + m)
                except Exception as e:
                    log(f"Plausibilitätsprüfung nicht möglich: {e}")
            elif g == "modell":
                erg["modell"] = modell_export(p, ausgaben, log, pg)
            elif g == "schnitt":
                erg["schnitt"] = schnitt_export(p, log, pg)
            else:
                erg["hoehenlinien"] = hoehenlinien_export(p, log, pg)
        except Exception as e:
            import traceback
            log(f"FEHLER in {g}: {e}")
            log(traceback.format_exc()[-1800:])
            erg[g] = {"fehler": str(e)}
        zeiten[g] = time.time() - tg
        if speichern:
            try:
                P.speichern(p)
            except Exception as e:
                log(f"Projekt konnte nicht gespeichert werden: {e}")
    try:
        from . import quellen
        quellen.schreiben(P.ausgabe_basis(p))
    except Exception:
        pass
    log(f"Fertig in {time.time() - t0:.0f} s")
    from . import bericht
    bericht.schreiben(p, ausgaben, erg, zeilen, time.time() - t0, zeiten)
    return erg
