# -*- coding: utf-8 -*-
"""IFCmap - Abhaengigkeiten der Schalter im Reiter Ausgabe (ohne Oberflaeche, damit sie sich testen lassen).

regeln(w, geaendert) bekommt die aktuellen Werte (Codes statt Anzeigetexte) und liefert
  setze    {Name: Wert}  - Folgen einer Benutzeraenderung (gegenseitiger Ausschluss: der andere Haken wird automatisch an-/abgehakt)
  erzwinge {Name: Wert}  - gilt solange eine Bedingung besteht; die Oberflaeche merkt sich den alten Wert und stellt ihn danach wieder her
  aktiv    {Gruppe: bool} - welche Gruppen von Bedienelementen bedienbar sind (sonst ausgegraut)
geaendert = (Name, neuer Wert) der letzten Benutzeraenderung oder None."""

# Schluessel, deren Aenderung die Regeln neu auswertet
BEOBACHTET = ("ifc", "dxf2d", "plan_lageplan", "plan_schwarzplan", "aufteilung", "fern_gebaeude", "buergersteige", "gehweg_auto",
              "schatten", "schatten_lageplan", "schatten_schwarzplan", "schatten_baeume", "baumschatten_lageplan", "baumschatten_schwarzplan",
              "sonne", "markant")


def regeln(w, geaendert=None):
    g = lambda k, vorgabe=False: w.get(k, vorgabe)
    ifc, dxf2d = bool(g("ifc")), bool(g("dxf2d"))
    lage, schwarz = bool(g("plan_lageplan")), bool(g("plan_schwarzplan"))
    teilen = g("aufteilung", "strassen") != "keine"
    fern_aus = g("fern_gebaeude", "bloecke") == "keine"
    gw_modus = g("buergersteige", "fgn")
    schatten = g("schatten", "aus")
    plan = lage or schwarz

    # ---- Folgen einer Benutzeraenderung (gegenseitiger Ausschluss) ------------------------------------------------------------------------
    setze = {}
    if geaendert:
        name, neu = geaendert
        t_l, t_s = bool(g("schatten_lageplan")), bool(g("schatten_schwarzplan"))
        gewaehlt_an = (lage and t_l) or (schwarz and t_s)
        if name == "schatten" and neu != "aus" and plan and not gewaehlt_an:
            # Schatten eingeschaltet, aber fuer keinen gewaehlten Plan angehakt -> fuer die gewaehlten Plaene anhaken
            if lage:
                setze["schatten_lageplan"] = True
            if schwarz:
                setze["schatten_schwarzplan"] = True
        elif name in ("schatten_lageplan", "schatten_schwarzplan") and schatten != "aus" and plan and not gewaehlt_an:
            setze["schatten"] = "aus"                                 # alle Plan-Haken abgewaehlt -> kein Schatten
        elif name in ("plan_lageplan", "plan_schwarzplan"):
            if neu and schatten != "aus":
                setze["schatten_lageplan" if name == "plan_lageplan" else "schatten_schwarzplan"] = True   # neuer Plan bekommt den Schatten mit
            elif not neu and schatten != "aus" and not plan:
                setze["schatten"] = "aus"                             # letzter Plan abgewaehlt -> Schatten hat kein Ziel mehr
        elif name == "gehweg_auto" and neu is False:
            pass                                                      # feste Breite wird bedienbar (siehe aktiv)

    # ---- Zustand, der ueber Haken und Auswahl folgt ----------------------------------------------------------------------------------------
    erzwinge = {}
    if fern_aus:
        erzwinge["fern_zusammenfassen"] = False
        erzwinge["markant_fern"] = False
    if not bool(g("markant")):
        erzwinge["markant_fern"] = False
    if gw_modus == "keine":
        erzwinge["gehweg_ueberall"] = False

    gehweg_frage = lage or (ifc and teilen)                          # Buergersteige zeichnet der Lageplan und teilt das IFC-Gelaende
    gehweg_an = gehweg_frage and gw_modus != "keine"
    schatten_an = plan
    schatten_wahl = plan and schatten != "aus"
    aktiv = {
        "ifc": ifc,
        "ifc_bordstein": ifc and teilen,
        "ifc_fern_zusammenfassen": ifc and not fern_aus,
        "lageplan": lage,
        "gehweg": gehweg_frage,
        "gehweg_optionen": gehweg_an,
        "gehweg_breite": gehweg_an and not bool(g("gehweg_auto")),
        "schatten": schatten_an,
        "schatten_zeit": schatten_an and schatten == "eigen",
        "schatten_lageplan": schatten_wahl and lage,
        "schatten_schwarzplan": schatten_wahl and schwarz,
        "baumschatten": schatten_wahl,
        "baumschatten_optionen": schatten_wahl and bool(g("schatten_baeume")),
        "baumschatten_lageplan": schatten_wahl and bool(g("schatten_baeume")) and lage and bool(g("schatten_lageplan")),
        "baumschatten_schwarzplan": schatten_wahl and bool(g("schatten_baeume")) and schwarz and bool(g("schatten_schwarzplan")),
        "sonne": bool(g("sonne")),
        "markant": bool(g("markant")),
        "markant_fern": bool(g("markant")) and not fern_aus,
        "dxf2d": dxf2d,
        "alkis": dxf2d or plan,
    }
    return setze, erzwinge, aktiv
