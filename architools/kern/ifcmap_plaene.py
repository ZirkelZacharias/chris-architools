# -*- coding: utf-8 -*-
"""IFCmap - fertige 2D-Plaene als DXF (R2010): Lageplan und Schwarzplan.

Regeln: Flaechen sind ausschliesslich Schraffuren (Vollton, ggf. transparent); Linien nur fuer die duenne Gebaeudekontur (Lageplan),
Baumkronen, Dachfirste/-kehlen, Sonnenbahnen (keine Rahmen). Flurstuecke kommen im Lageplan NICHT vor. Gebaeudegrundrisse werden NIRGENDS aus anderen Flaechen herausgeschnitten - die Flaechen
laufen darunter durch, die Gebaeude liegen als oberste Flaechenschicht darueber (Reihenfolge = Zeichenreihenfolge in der Datei).

Lageplan (von unten nach oben): Grund (alles uebrige hellgrau) - Natur (Gruentoene) - Wasser (blau) - Bahn (grau, mit lila Gleisachsen) - Fahrbahn - Gehweg / Wege (zwei Grautoene) -
Schatten (transparent) - Gebaeude (weiss) - Dachschattierung - Gebaeudekontur (duenn schwarz) - Dachlinien - Baumkronen - Sonnenbahnen
Schwarzplan: Wasser (dunkelblau) - Gleisachsen (Neonviolett, nur Linien) - Schatten (transparent) - Gebaeude (schwarz) - Sonnenbahnen
"""
import math
import re

import numpy as np
import shapely
from shapely.geometry import box
from shapely.ops import unary_union

import ifcmap_kern as K
import ifcmap_schatten as SC
import ifcmap_bruecken as BR

LAGE = {
    "grund": (226, 226, 226), "fahrbahn": (246, 246, 246), "gehweg": (206, 206, 206),
    "wasser": (150, 190, 235), "bahn": (172, 172, 176), "gleis": (191, 0, 255), "gebaeude": (255, 255, 255), "schatten": (70, 70, 85), "schatten_transp": 0.55,
    "natur": [("Wald", (146, 193, 126)), ("Gehoelz", (164, 205, 144)), ("Gruen", (190, 224, 162)),
              ("Landwirtschaft", (208, 226, 172)), ("Brache_Unland", (201, 221, 166))],
    "dach_dunkel": (170, 170, 172), "dach_hell": (252, 252, 252), "firste": (80, 80, 85), "kehlen": (140, 140, 145),
    "krone": (70, 150, 70), "kontur": (0, 0, 0), "rahmen": (120, 120, 120),
}
SCHWARZ = {"wasser": (15, 35, 120), "bahn": (191, 0, 255), "gebaeude": (0, 0, 0), "schatten": (110, 110, 110), "schatten_transp": 0.5,
           "rahmen": (0, 0, 0)}

INDOOR_FGN = {"ifgt", "ifgz", "iga", "ikga", "ivbz", "unbk"}      # EL_LAGE-Werte des Berliner Fussgaengernetzes, die keine Wege im Freien sind


# ----------------------------------------------------------------------------------------------
# Buergersteige
# ----------------------------------------------------------------------------------------------

def _geo_leer():
    return shapely.Polygon()


def _ueber_rand_verlaengern(strasse, rect, tiefe):
    """Strassen, die am Rand des Plangebiets abgeschnitten sind, ueber den Rand hinaus verlaengern - sonst entstuende am Rand eine
    Querkante aus Gehweg (die Strasse geht ja weiter)."""
    from shapely.affinity import translate
    x0, y0, x1, y1 = rect.bounds
    teile = [strasse]
    for (sx, sy, strip) in ((-1, 0, box(x0, y0 - 1, x0 + 0.2, y1 + 1)), (1, 0, box(x1 - 0.2, y0 - 1, x1, y1 + 1)),
                            (0, -1, box(x0 - 1, y0, x1 + 1, y0 + 0.2)), (0, 1, box(x0 - 1, y1 - 0.2, x1 + 1, y1))):
        e = strasse.intersection(strip)
        for p in K._polys(e):
            q = translate(p, sx * tiefe, sy * tiefe)
            teile.append(unary_union([p, q]).convex_hull)
    return unary_union(teile)


# Gehwegbreite nach Strassenbreite. Orientierung: Berliner "AV Geh- und Radwege" (2023), Teil A Kap. I Nr. 2: fuer NEUBAU mindestens 3,20 m,
# Richtwerte Siedlungsstrasse 3,20-4,00 m, Hauptverkehrsstrasse 4,00-5,00 m. Im aelteren Bestand sind Gehwege oft schmaler - deshalb
# bewusst kleinere Werte (2,0 / 3,0 / 4,0 m); anpassbar hier.
# Die ALKIS-Strassenflaeche ist der ganze Strassenraum (Fahrbahn + beide Gehwege): je breiter er ist, desto breiter der Gehweg.
# (Strassenraum von ... m, Gehwegbreite m)
GEHWEG_KLASSEN = ((0.0, 2.0), (14.0, 3.0), (24.0, 4.0))


def strassen_zonen(strasse, rect=None):
    """Teilt die Strassenflaeche nach der oertlichen Breite des Strassenraums in die Klassen von GEHWEG_KLASSEN.
    -> [(Zone (Polygon), Gehwegbreite m, Strassenraum ab m)] - die Zonen decken die Strassenflaeche vollstaendig ab, die breiteste zuerst."""
    if strasse is None or strasse.is_empty:
        return []
    maxb = GEHWEG_KLASSEN[-1][1]
    ext = _ueber_rand_verlaengern(strasse, rect, 40.0) if rect is not None else strasse
    zonen, bedeckt = [], None
    for ab, gb in reversed(GEHWEG_KLASSEN[1:]):
        r = ab / 2.0
        kern = ext.buffer(-r, join_style=2, mitre_limit=2.0).buffer(r + 0.5, join_style=2, mitre_limit=2.0).intersection(strasse)
        if bedeckt is not None:
            kern = kern.difference(bedeckt)
        if not kern.is_empty:
            zonen.append((kern, gb, ab))
            bedeckt = kern if bedeckt is None else unary_union([bedeckt, kern])
    rest = strasse if bedeckt is None else strasse.difference(bedeckt)
    zonen.append((rest, GEHWEG_KLASSEN[0][1], GEHWEG_KLASSEN[0][0]))
    return zonen


def gehweg_naeherung(strasse, b, rect=None, zonen=None):
    """Mit zonen (aus strassen_zonen) bekommt jede Zone ihre eigene Gehwegbreite, b gilt dann nicht."""
    if zonen:
        teile = [gehweg_naeherung(strasse, gb, rect)[1].intersection(zone) for zone, gb, _ in zonen if not zone.is_empty]
        gw = unary_union([t for t in teile if not t.is_empty]) if teile else _geo_leer()
        return strasse.difference(gw), gw
    return _gehweg_naeherung(strasse, b, rect)


def _gehweg_naeherung(strasse, b, rect=None):
    """Naeherung ohne Zusatzdaten: Streifen der Breite b an den Raendern breiter Strassen. Schmale Strassen (Kern < 3 m) bleiben Fahrbahn.
    -> (fahrbahn, gehweg)"""
    if strasse is None or strasse.is_empty:
        return strasse, _geo_leer()
    ext = _ueber_rand_verlaengern(strasse, rect, b + 5.0) if rect is not None else strasse
    kern = ext.buffer(-b, join_style=2, mitre_limit=2.0).buffer(-1.5, join_style=2).buffer(1.5, join_style=2)     # Kern >= 3 m breit
    if kern.is_empty:
        return strasse, _geo_leer()
    gehweg = kern.buffer(b + 0.05, join_style=2, mitre_limit=2.0).intersection(strasse).difference(kern)
    return strasse.difference(gehweg), gehweg


def gehweg_fgn(strasse, linien, b, zonen=None):
    """Gehweg = Mittellinien des Fussgaengernetzes, auf die Breite b gepuffert, innerhalb der Strassenflaeche. -> (fahrbahn, gehweg)
    Mit zonen (aus strassen_zonen) wird jede Linie je Zone mit deren Gehwegbreite gepuffert."""
    if strasse is None or strasse.is_empty:
        return strasse, _geo_leer()
    if zonen:
        baender = []
        for zone, gb, _ in zonen:
            if zone.is_empty:
                continue
            zp = zone.buffer(0.01)
            for ln in linien:
                s = ln.intersection(zp)
                for l2 in _linien_von(s):
                    baender.append(l2.buffer(gb / 2.0, cap_style=1))
        band = unary_union(baender) if baender else _geo_leer()
    else:
        band = unary_union([ln.buffer(b / 2.0, cap_style=1) for ln in linien])
    gehweg = band.intersection(strasse)
    return strasse.difference(gehweg), gehweg


QUER_WINKEL = 50.0        # Grad: Linien, die im Mittel steiler als dieser Winkel auf den Strassenrand treffen, sind Querungen
QUER_MINDESTLAENGE = 2.5  # m innerhalb der Strassenflaeche
QUER_STUMMEL = 12.0       # m: so viel ausserhalb der Strasse darf eine Querung ueberstehen (Enden an den Gehwegen) und wird ganz verworfen


def _linien_von(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == "LineString":
        return [g]
    return [x for x in getattr(g, "geoms", []) if x.geom_type == "LineString"] + \
           [y for x in getattr(g, "geoms", []) if x.geom_type not in ("LineString", "Point") for y in _linien_von(x)]


def fgn_bereinigen(strasse, linien):
    """Trennt Fahrbahnquerungen (Fussgaengerueberwege, Furten) von den Gehwegen und Wegen.
    Eine Linie gilt als Querung, wenn ihr Teil in der Strassenflaeche mindestens QUER_MINDESTLAENGE lang ist und im Mittel (Median) um mehr
    als QUER_WINKEL gegen den naechsten Strassenrand geneigt ist - ein Gehweg laeuft dem Rand entlang, eine Querung quer darueber.
    -> (wege, querungen)"""
    if strasse is None or strasse.is_empty or not linien:
        return list(linien or []), []
    rand = _linien_von(strasse.boundary)
    if not rand:
        return list(linien), []
    baum = shapely.STRtree(rand)
    shapely.prepare(strasse)
    wege, quer = [], []
    for ln in linien:
        teile = _linien_von(ln.intersection(strasse))
        if sum(p.length for p in teile) < QUER_MINDESTLAENGE:
            wege.append(ln)
            continue
        winkel = []
        for p in teile:
            n = max(2, int(p.length // 1.5))
            for i in range(n):
                s = (i + 0.5) / n * p.length
                pt = p.interpolate(s)
                a, b = p.interpolate(max(0.0, s - 0.5)), p.interpolate(min(p.length, s + 0.5))
                v = (b.x - a.x, b.y - a.y)
                r = rand[int(baum.query_nearest(pt)[0])]
                tt = r.project(pt)
                e, f = r.interpolate(min(r.length, tt + 0.5)), r.interpolate(max(0.0, tt - 0.5))
                w = (e.x - f.x, e.y - f.y)
                nv, nw = math.hypot(*v), math.hypot(*w)
                if nv < 1e-6 or nw < 1e-6:
                    continue
                winkel.append(math.degrees(math.acos(min(1.0, abs(v[0] * w[0] + v[1] * w[1]) / (nv * nw)))))
        if winkel and float(np.median(winkel)) > QUER_WINKEL:
            quer.append(ln)
            lang = ln.length - sum(p.length for p in teile) > QUER_STUMMEL
            if lang:                                   # langer Weg, der nur eine Strasse kreuzt: der Rest ausserhalb bleibt ein Weg
                wege += [x for x in _linien_von(ln.difference(strasse)) if x.length > 0.5]
        else:
            wege.append(ln)
    return wege, quer


def wege_ausserhalb(d, linien, b, strasse):
    """Wege, die ausserhalb der ALKIS-Strassenflaeche liegen (Parkwege wie im Mauerpark, Gehwege, die in ALKIS als Weg/Platz/Gruen gefuehrt
    werden): die Linien auf Breite b gepuffert, ohne Strassenflaeche, Wege/Plaetze, Gewaesser und Bahn. -> Polygon oder None"""
    if not linien:
        return None
    band = unary_union([ln.buffer(b / 2.0, cap_style=1) for ln in linien]).intersection(d.rect)
    abzug = [strasse]
    for k in ("Weg_Platz", "Gewaesser", "Bahn"):
        g = (d.regionen or {}).get(k)
        if g is not None and not g.is_empty:
            abzug.append(g)
    rest = band.difference(unary_union([a for a in abzug if a is not None and not a.is_empty]))
    return rest if rest is not None and not rest.is_empty and rest.area > 0.5 else None


def buergersteige(d, strasse, log):
    """Teilt die Strassenflaeche in Fahrbahn und Gehweg -> (fahrbahn, gehweg, Hinweistext oder None)"""
    cfg = d.cfg
    modus = getattr(cfg, "buergersteige", "fgn")
    b = float(getattr(cfg, "gehweg_breite", 2.5) or 2.5)
    if strasse is None or strasse.is_empty or modus == "keine":
        return strasse, _geo_leer(), None
    # Lageplan (2D) und IFC-Gelaende teilen sich dieselbe Aufteilung - nur einmal rechnen
    auto = bool(getattr(cfg, "gehweg_auto", True))
    ueberall = bool(getattr(cfg, "gehweg_ueberall", False))
    schluessel = (modus, b, auto, ueberall, id(strasse), id(getattr(d, "fgn", None)))
    cache = getattr(d, "_gehweg_cache", None)
    if cache and cache[0] == schluessel:
        return cache[1]
    zonen = strassen_zonen(strasse, d.rect) if auto else None
    if zonen:
        log("  Buergersteige: Breite nach Strassenbreite (Berliner Richtwerte): " + ", ".join(
            "%s %.1f m (%.0f m2 Strassenflaeche)" % (("Strassenraum ab %.0f m" % ab) if ab else "schmale Strassen", gb, z_.area) for z_, gb, ab in zonen if not z_.is_empty))
    erg = _buergersteige(d, strasse, log, modus, b, zonen)
    bereich = getattr(d, "detail_rect", None) or getattr(d, "nah_rect", None)
    if not ueberall and bereich is not None:
        fb, gw, hint = erg
        if gw is not None and not gw.is_empty:
            gw2 = gw.intersection(bereich)
            wo = "Nah- und Mittelbereich" if getattr(d, "mittel_aktiv", False) else "Nahbereich"
            log("  Buergersteige: nur im %s (%.0f von %.0f m2 Gehweg; im Fernbereich ist alles Fahrbahn)" % (wo, gw2.area, gw.area))
            erg = (strasse.difference(gw2), gw2, (hint or "") + (" Buergersteige nur im %s." % wo if hint else ""))
    d._gehweg_cache = (schluessel, erg)
    return erg


def _buergersteige(d, strasse, log, modus, b, zonen=None):
    if modus == "fgn":
        fgn = getattr(d, "fgn", None)
        if fgn:
            wege, quer = fgn_bereinigen(strasse, fgn)
            fb, gw = gehweg_fgn(strasse, wege, b, zonen)
            extra = wege_ausserhalb(d, wege, b, strasse)
            n_extra = 0
            if extra is not None:
                gw = unary_union([gw, extra]) if gw is not None and not gw.is_empty else extra
                n_extra = len(K._polys(extra))
            log("  Buergersteige: Fussgaengernetz Berlin (%d Linien), Breite %s; %d Fahrbahnquerungen nicht als Gehweg gezeichnet, "
                "%d Wegflaechen ausserhalb der Strassenflaeche (Parkwege u. a.) ergaenzt" % (len(fgn), "nach Strassenbreite" if zonen else "%.1f m" % b, len(quer), n_extra))
            return fb, gw, ("Buergersteige und Wege aus dem Berliner Fussgaengernetz (Mittellinien, auf %s Breite gepuffert) - ohne Gewaehr, die Breite ist "
                            "angenommen. Fahrbahnquerungen sind herausgenommen (erkannt am Winkel zum Strassenrand)." % ("2,0 / 3,0 / 4,0 m je nach Strassenbreite" if zonen else "%.1f m" % b))
        log("  Buergersteige: Fussgaengernetz nicht verfuegbar (nur Berlin / Dienst nicht erreichbar) -> Naeherung aus der Strassenbreite")
        hinweis = "Fussgaengernetz nicht verfuegbar - Buergersteige NUR ALS NAEHERUNG aus der Strassenbreite (Streifen von %s am Rand breiter Strassen)." % ("2,0 / 3,0 / 4,0 m je nach Strassenbreite" if zonen else "%.1f m" % b)
    else:
        hinweis = "Buergersteige NUR ALS NAEHERUNG aus der Strassenbreite (Streifen von %s am Rand breiter Strassen), keine amtlichen Daten." % ("2,0 / 3,0 / 4,0 m je nach Strassenbreite" if zonen else "%.1f m" % b)
    fb, gw = gehweg_naeherung(strasse, b, d.rect, zonen)
    log("  Buergersteige (Naeherung): %.0f m2 Gehweg, %.0f m2 Fahrbahn" % (gw.area, fb.area))
    return fb, gw, hinweis


# ----------------------------------------------------------------------------------------------
# Zeichnen
# ----------------------------------------------------------------------------------------------

def _flaechen_ebene(cfg, key, vorgabe=True):
    return K.ebene_an(cfg, "dxf", key, vorgabe)


def zeichne_kontur(z, polygone, rgb, linienstaerke=9, name="2D_Kontur_Gebaeude"):
    """Duenne Konturlinie um alle Gebaeude. Die Ringe werden miteinander verknotet und entdoppelt (eine gemeinsame Wand zweier Gebaeude
    ergibt nur EINE Linie), Gebaeude bleiben einzeln erkennbar. linienstaerke in 1/100 mm (9 = 0,09 mm). -> Anzahl Linien"""
    from shapely.geometry import LineString
    from shapely.ops import linemerge
    ringe = []
    for g in polygone:
        for p in K._polys(g):
            ringe.append(LineString(p.exterior.coords))
            ringe += [LineString(i.coords) for i in p.interiors]
    if not ringe:
        return 0
    netz = unary_union(ringe)
    netz = linemerge(netz) if netz.geom_type == "MultiLineString" else netz       # (ein einzelner Ring ist schon eine Linie)
    linien = list(netz.geoms) if hasattr(netz, "geoms") else [netz]
    z.layer(name, rgb)
    try:
        z.doc.layers.get(name).dxf.lineweight = int(linienstaerke)
    except Exception:
        pass
    n = 0
    for ln in linien:
        c = list(ln.coords)
        if len(c) >= 2 and z.linie(c, name, rgb=rgb, geschlossen=bool(ln.is_ring)) is not None:
            n += 1
    return n


def _linienteile(g):
    """Alle LineStrings einer (auch gemischten) Geometrie"""
    if g is None or g.is_empty:
        return []
    if g.geom_type == "LineString":
        return [g]
    return [x for part in getattr(g, "geoms", []) for x in _linienteile(part)]


def zeichne(z, d, variante, log=print):
    cfg = d.cfg
    lage = variante == "lageplan"
    S = LAGE if lage else SCHWARZ
    reg = d.regionen or {}
    an = lambda k, v=True: _flaechen_ebene(cfg, k, v)
    hinweise = []

    # --- Grund + Natur + Wasser (+ Bahn im Schwarzplan)
    if lage:
        z.flaeche(d.rect, "2D_Plan_Grund", S["grund"], sauber=False)
        for kat, rgb in S["natur"]:
            if reg.get(kat) is not None and not reg[kat].is_empty and an("Nutzung:" + kat):
                z.flaeche(reg[kat], "2D_Natur_" + kat, rgb, min_flaeche=1.0, min_loch=2.0)
    wasser = reg.get("Gewaesser")
    if wasser is not None and not wasser.is_empty and an("Nutzung:Gewaesser"):
        z.flaeche(wasser, "2D_Wasser", S["wasser"], min_flaeche=1.0, min_loch=2.0)
    bahn = reg.get("Bahn")
    achsen, farbe = None, S["gleis"] if lage else S["bahn"]
    if an("Nutzung:Bahn"):
        if lage and bahn is not None and not bahn.is_empty:
            z.flaeche(bahn, "2D_Bahn", S["bahn"], min_flaeche=1.0, min_loch=2.0)          # Lageplan: graue Bahnflaeche, darauf die Gleisachsen
        try:
            achsen = K.bahn_achsen(d, cfg, log)
        except Exception as e:
            log("  Gleisachsen nicht verfuegbar (%s)" % str(e)[:80])
            achsen = None
        farbe = S["gleis"] if lage else S["bahn"]
        if not achsen and not lage and bahn is not None and not bahn.is_empty:
            hinweise.append("Schwarzplan: Gleisachsen aus OpenStreetMap nicht verfuegbar - Bahn ersatzweise als Flaeche gezeichnet.")
            log("  HINWEIS: Gleisachsen nicht verfuegbar (OpenStreetMap nicht erreichbar) - Bahn als Flaeche")
            z.flaeche(bahn, "2D_Bahn", S["bahn"], min_flaeche=1.0, min_loch=2.0)
        elif not achsen and lage and bahn is not None and not bahn.is_empty:
            log("  HINWEIS: Gleisachsen nicht verfuegbar (OpenStreetMap nicht erreichbar) - Lageplan zeigt nur die graue Bahnflaeche")

    def gleisachsen_zeichnen(br=None):
        """Gleisachsen liegen ueber allem, auch ueber Bahnbruecken - ausser dort, wo sie eine Strassen- oder Wegbruecke unterqueren: im Lageplan
        wird die Achse unter dem Brueckendeck weggelassen (wie unter einem undurchsichtigen Deck). Die weggelassenen Stuecke stehen auf dem
        ausgeschalteten Layer 2D_Gleisachsen_unter_Bruecken und lassen sich in ArchiCAD einblenden."""
        if not (achsen and an("Nutzung:Bahn")):
            return
        name = "2D_Gleisachsen"
        z.layer(name, farbe)
        try:
            z.doc.layers.get(name).dxf.lineweight = 35
        except Exception:
            pass
        sichtbar, unter = list(achsen), []
        if lage and br:
            try:
                decks = [e["deck"] for e in br if e["typ"] != "bahn" and e.get("deck") is not None]
                bahn_decks = [e["deck"].buffer(1.0) for e in br if e["typ"] == "bahn" and e.get("deck") is not None]
                if decks:
                    zone = unary_union(decks)
                    if bahn_decks:
                        zone = zone.difference(unary_union(bahn_decks))               # Gleise auf einer Bahnbruecke bleiben oben
                    sichtbar, unter = [], []
                    for ln in achsen:
                        if not ln.intersects(zone):
                            sichtbar.append(ln)
                            continue
                        unter += [g for g in _linienteile(ln.intersection(zone)) if g.length > 0.3]
                        sichtbar += [g for g in _linienteile(ln.difference(zone)) if g.length > 0.3]
                    if unter:
                        log("  Gleis-/OEPNV-Achsen unter Bruecken: %d Stuecke (%.0f m) liegen unter dem Brueckendeck und werden nicht gezeichnet (Layer 2D_Gleisachsen_unter_Bruecken, ausgeschaltet)"
                            % (len(unter), sum(g.length for g in unter)))
            except Exception as e:
                log("  HINWEIS: Achsen unter Bruecken nicht geprueft (%s)" % str(e)[:80])
                sichtbar, unter = list(achsen), []
        for ln in sichtbar:
            z.linie(list(ln.coords), name, rgb=farbe)
        if unter:
            n2 = "2D_Gleisachsen_unter_Bruecken"
            z.layer(n2, farbe)
            try:
                z.doc.layers.get(n2).off()
            except Exception:
                pass
            for ln in unter:
                z.linie(list(ln.coords), n2, rgb=farbe)

    # --- Strassen mit Buergersteigen, Wege (nur Lageplan)
    if lage:
        strasse = reg.get("Strasse")
        if strasse is not None and not strasse.is_empty and an("Nutzung:Strasse"):
            fb, gw, hint = buergersteige(d, strasse, log)
            if hint:
                hinweise.append(hint)
            z.flaeche(fb, "2D_Strasse_Fahrbahn", S["fahrbahn"], min_flaeche=0.5, min_loch=1.0)
            if gw is not None and not gw.is_empty:
                z.flaeche(gw, "2D_Strasse_Gehweg", S["gehweg"], min_flaeche=0.3, min_loch=0.5)
        wege = reg.get("Weg_Platz")
        if wege is not None and not wege.is_empty and an("Nutzung:Weg_Platz"):
            z.flaeche(wege, "2D_Weg_Platz", S["gehweg"], min_flaeche=0.5, min_loch=1.0)

    # --- Bruecken: oberhalb von Gelaende, Wasser, Bahn, Strasse und Weg - mit ihrer Fahrbahn/Gehweg, ihrem Weg oder ihrer Bahn
    br = None
    if an("Bruecken"):
        try:
            br = BR.bruecken(d, cfg, log)
            nb = BR.zeichne(z, d, br, S, lage, an, log)
            if br and lage:
                log("  Bruecken gezeichnet: %d Flaechen" % nb)
        except Exception as e:
            log("  FEHLER bei den Bruecken (%s) - Plan ohne Bruecken" % str(e)[:120])
    gleisachsen_zeichnen(br)

    # --- Schatten + Dach (Sonne)
    koerper = None
    schatten_hier = getattr(cfg, "schatten", "aus") != "aus" and bool(getattr(cfg, "schatten_lageplan" if lage else "schatten_schwarzplan", True))
    so_schatten = SC.sonne_fuer_plan(cfg, d) if schatten_hier else None
    if so_schatten or (lage and (cfg.dach_linien or cfg.dach_schattierung)):
        koerper = SC.gebaeude_koerper(d)
    if so_schatten:
        log("  Schatten: %s" % so_schatten["text"])
        sch = SC.schatten_geometrie(d, so_schatten["az"], so_schatten["el"], mit_baeumen=bool(cfg.schatten_baeume) and bool(getattr(cfg, "baumschatten_lageplan" if lage else "baumschatten_schwarzplan", True))
                                    and bool(d.baeume), log=log, koerper=koerper,
                                    baum_bereich=None if getattr(cfg, "schatten_baeume_bereich", "nah") == "alle" else getattr(d, "baum_zone", None))
        if sch is not None:
            n = z.flaeche(sch, "2D_Schatten", S["schatten"], transparenz=S["schatten_transp"], min_flaeche=0.5, min_loch=0.5)
            log("  Schatten: %d Flaechen (Schraffur, %d %% transparent; Gebaeudegrundrisse nicht abgezogen)" % (n, round(S["schatten_transp"] * 100)))
        d.schatten_info = so_schatten["text"]

    # --- Gebaeude: ganz oben unter den Flaechen
    nah, fern = K.gebaeude_umrisse(d)
    if getattr(d, "_umrisse_extra", 0) and not getattr(d, "_umrisse_gemeldet", False):
        d._umrisse_gemeldet = True
        log("  Gebaeude-Grundrisse: %d Gebaeude fehlen in ALKIS und kommen aus LoD2/OpenStreetMap dazu (Lauben, Neubauten) - sonst gaebe es Schatten ohne Gebaeude" % d._umrisse_extra)
    for name, liste in (("Nah", nah), ("Fern", fern)):
        if liste and an("Gebaeude_" + name):
            z.flaeche(K.gebaeude_vereint(liste), "2D_Gebaeude_" + name, S["gebaeude"], min_flaeche=1.0)

    # --- Gebaeudekontur (nur Lageplan): duenne schwarze Linie um jedes Gebaeude; gemeinsame Waende nur einmal
    if lage:
        kont = []
        for name, liste in (("Nah", nah), ("Fern", fern)):
            if liste and an("Gebaeude_" + name):
                kont += list(liste)
        if kont:
            n_k = zeichne_kontur(z, kont, S["kontur"])
            log("  Gebaeudekontur: %d Linien (duenn, schwarz)" % n_k)

    # --- Dachschattierung und Dachlinien (Lageplan, Nahbereich)
    if lage and koerper and (cfg.dach_linien or cfg.dach_schattierung):
        nahk = [g for g in koerper if g["nah"]]
        if cfg.dach_schattierung and nahk:
            so = so_schatten or SC.sonne_fuer_plan(cfg, d, auch_aus=True)
            if so_schatten is None:
                log("  Dachschattierung: Sonnenstand %s (Standardzeitpunkt, Schatten sind aus)" % so["text"])
            stufen = SC.dach_flaechen_tonwerte([g["faces"] for g in nahk], so["az"], so["el"], stufen=7)
            n = 0
            for st in sorted(stufen):
                rgb = SC.tonwert(st, 7, S["dach_dunkel"], S["dach_hell"])
                n += z.flaeche(unary_union(stufen[st]), "2D_Dach_Ton_%d" % st, rgb, min_flaeche=0.3, min_loch=0.3)
            log("  Dachschattierung: %d Flaechen in %d Tonstufen" % (n, len(stufen)))
        if cfg.dach_linien and nahk:
            fi, ke, fi_m, ke_m = [], [], [], []
            for g in nahk:
                a, b = SC.dachlinien([g["faces"]], min_winkel=30.0 if g["markant"] else 12.0, min_laenge=2.0 if g["markant"] else 0.8)
                fi += a
                ke += b
            ln_f = z.layer("2D_Dach_Firste", S["firste"])
            ln_k = z.layer("2D_Dach_Kehlen", S["kehlen"])
            for ln in fi:
                z.linie(ln.coords, ln_f, rgb=S["firste"])
            for ln in ke:
                z.linie(ln.coords, ln_k, rgb=S["kehlen"])
            log("  Dachlinien: %d Firste/Grate, %d Kehlen" % (len(fi), len(ke)))

    # --- Baeume (nur Kronen als Linien)
    if lage and cfg.lageplan_baeume and d.baeume and an("Baeume"):
        l_k = z.layer("2D_Baeume_Krone", S["krone"])
        for (x, y, kr, ho, st, _) in d.baeume:
            z.kreis(x, y, max(kr, 1.0) / 2, l_k, rgb=S["krone"])

    # --- Sonnenbahnen, Rahmen
    if getattr(cfg, "sonne", False) and an("Sonne"):
        try:
            K._dxf_sonne(z, d)
        except Exception as e:
            log("  FEHLER beim Sonnenbahn-Diagramm (DXF): %s" % e)
    # Rahmen von Gebiet/Nahbereich/Mittelbereich stehen NICHT in Lageplan und Schwarzplan (Nutzerwunsch); nur das Arbeits-DXF zeichnet sie
    d.plan_hinweise = hinweise
    return hinweise
