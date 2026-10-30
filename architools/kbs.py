"""Koordinatensystem des Projekts passend zum Ort.

Alle im Projekt gespeicherten Ost/Nord-Werte (Mittelpunkt, Schnittlinie, Passpunkte der Zusatzpläne) stehen im System
p["umgebung"]["epsg"]. Bis Build 9 war das immer UTM 33 (Berlin). Liegt der Ort woanders, passt UTM 33 nicht (Verzerrung,
gedrehter Norden), und der Rechenkern hat dann in einem anderen System gerechnet als Karte und Modellbau.

angleichen(p) stellt das Projekt auf das richtige System um (Landesprofil, sonst UTM-Zone am Mittelpunkt) und rechnet alle
gespeicherten Koordinaten mit um. In Berlin ändert sich nichts. Bei "Anderes Land: nur eigene Dateien" bleibt das
eingestellte System (die eigenen Dateien bestimmen es).
"""

AKTUELL = {"epsg": 25833}            # System der Oberfläche (Karte <-> Ost/Nord), siehe gui/stil.py


def aktuell():
    return int(AKTUELL["epsg"])


def setzen(epsg):
    AKTUELL["epsg"] = int(epsg or 25833)
    try:
        from .gui import stil
        stil.kbs_neu()
    except Exception:
        pass


def _kern():
    from . import projekt as P
    P.kern()
    import ifcmap_laender as L
    import ifcmap_ausland as A
    return L, A


def ziel_epsg(p):
    """Passendes System für den Mittelpunkt des Projekts -> (epsg, land oder None)."""
    from pyproj import Transformer
    L, A = _kern()
    u = p["umgebung"]
    alt = int(u.get("epsg") or 25833)
    wahl = u.get("land") or "auto"
    if wahl == "keins":
        return alt, None
    e, n = (float(v) for v in p["gebiet"]["mitte_en"])
    lon, lat = Transformer.from_crs("EPSG:%d" % alt, "EPSG:4326", always_xy=True).transform(e, n)
    prof = L.profile()
    land = wahl if wahl != "auto" else L.land_am_punkt(lon, lat, prof)
    if land == "berlin":
        return 25833, land
    ep = (prof.get(land) or {}).get("epsg") if land else None
    if ep in (None, "", "utm"):
        ep = A.utm_epsg(lon, lat)
    return int(ep), land


def _umrechnen(t, pt):
    x, y = t.transform(float(pt[0]), float(pt[1]))
    return [round(x, 3), round(y, 3)]


def angleichen(p, log=None):
    """Projekt auf das passende Koordinatensystem stellen. -> (alt, neu) wenn umgestellt, sonst None."""
    from pyproj import Transformer
    u = p["umgebung"]
    alt = int(u.get("epsg") or 25833)
    try:
        neu, land = ziel_epsg(p)
    except Exception as ex:
        if log:
            log("Koordinatensystem: Prüfung nicht möglich (%s) – bleibt EPSG:%d" % (ex, alt))
        neu = alt
    p["modell"]["kbs"] = neu
    if neu == alt:
        return None
    t = Transformer.from_crs("EPSG:%d" % alt, "EPSG:%d" % neu, always_xy=True)
    p["gebiet"]["mitte_en"] = _umrechnen(t, p["gebiet"]["mitte_en"])
    s = p.get("schnitt") or {}
    if s.get("linie_en"):
        s["linie_en"] = [_umrechnen(t, q) for q in s["linie_en"]]
    for plan in u.get("zusatzplaene") or []:
        for pt in (plan.get("punkte") or []) if isinstance(plan, dict) else []:
            if isinstance(pt, dict) and "E" in pt and "N" in pt:
                pt["E"], pt["N"] = _umrechnen(t, (pt["E"], pt["N"]))
    if u.get("e0n0"):                                        # Nullpunkt von Hand: mitnehmen (auf ganze Meter)
        x, y = t.transform(float(u["e0n0"][0]), float(u["e0n0"][1]))
        u["e0n0"] = (float(round(x)), float(round(y)))
    u["epsg"] = neu
    if log:
        log("Koordinatensystem des Projekts: EPSG:%d -> EPSG:%d (passend zum Ort); Mittelpunkt, Schnittlinie und Passpunkte umgerechnet"
            % (alt, neu))
    return alt, neu
