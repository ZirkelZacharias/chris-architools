"""Standort-Prüfung für den Reiter „Gebiet“: liegt der Mittelpunkt in Berlin, in einem Land mit Plugin oder ganz woanders?

Zirkel Zacharias meldet sich nur klein, wenn es für den Ort keine fertig erprobten amtlichen Daten gibt.
"""
from .. import zusatz as Z


def land_am_ort(lat, lon):
    """-> (Kennung oder None, Anzeigename)"""
    from .. import projekt as P
    L = P.kern()
    import ifcmap_laender as LD
    prof = LD.profile()
    kandidaten = list(LD.REIHENFOLGE) + [k for k in prof if k not in LD.REIHENFOLGE]
    for land in kandidaten:
        box = LD.BERLIN_BOX if land == "berlin" else tuple(prof.get(land, {}).get("box") or ())
        if len(box) == 4 and box[0] <= lon <= box[2] and box[1] <= lat <= box[3]:
            return land, (LD.NAMEN.get(land) or prof.get(land, {}).get("name", land))
    return None, ""


def _plugin_laender():
    out = set()
    for m in Z.module().values():
        out.update((getattr(m, "LAENDER", None) or {}).keys())
    return out


def pruefen(lat, lon):
    """-> (stufe, text); stufe: "ok" (nichts anzeigen), "ungetestet", "fremd"."""
    try:
        land, name = land_am_ort(lat, lon)
    except Exception:
        return "ok", ""
    if land == "berlin":
        return "ok", ""
    if land and land in _plugin_laender():
        return "ok", ""
    if land:
        return "ungetestet", ("%s: Die amtlichen Daten (Gelände, Gebäude, Nutzung) sind im Programm neu eingebaut und noch nicht gegen die Live-Dienste "
                              "geprüft. Fehlt etwas, springt OpenStreetMap ein – oder du gibst eigene Dateien an." % name)
    return "fremd", ("Hier gibt es noch keine amtlichen Daten im Programm – nur Berlin ist erprobt. Es bleibt OpenStreetMap "
                     "(Gebäude ohne Höhen, kein Gelände) oder du gibst eigene Dateien an.")
