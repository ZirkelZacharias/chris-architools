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
    land = LD.land_am_punkt(lon, lat, prof)
    if land:
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
        try:                                      # Land-Plugin ohne automatischen Download: ehrlich sagen, dass die Dateien von Hand kommen
            import ifcmap_laender as LD
            pr = LD.profile().get(land, {})
            if all((pr.get(t) or {}).get("art") == "manuell" for t in ("dgm", "lod2")):
                return "ungetestet", ("%s: Gelände und Gebäude werden hier noch nicht automatisch geladen. Das Programm nennt dir die "
                                      "benötigten Kacheln im Protokoll – lade sie beim Landesportal und füge sie unter „Eigene Dateien“ hinzu. "
                                      "Sonst springt OpenStreetMap ein." % name)
        except Exception:
            pass
        return "ok", ""
    if land:
        return "ungetestet", ("%s: Die amtlichen Daten (Gelände, Gebäude, Nutzung) sind im Programm neu eingebaut und noch nicht gegen die Live-Dienste "
                              "geprüft. Fehlt etwas, springt OpenStreetMap ein – oder du gibst eigene Dateien an." % name)
    return "fremd", ("Hier gibt es noch keine amtlichen Daten im Programm – nur Berlin ist erprobt. Gebäude kommen aus OpenStreetMap "
                     "(Höhen nur, wo dort eingetragen), das Gelände grob aus Copernicus (30 m, mit Gebäuden und Bäumen darin). "
                     "Das Koordinatensystem stellt sich selbst auf die passende UTM-Zone. Bessere Daten kannst du als eigene Dateien angeben.")
