# -*- coding: utf-8 -*-
"""IFCmap - Bruecken fuer die 2D-Plaene.

ALKIS-Nutzung und OSM-Flaechen kennen keine Bruecken: das, was unter einer Bruecke liegt (Bahn, Wasser, eine andere Strasse), laeuft
im Plan durch, und der Weg oder die Strasse auf der Bruecke bricht am Rand ab. Hier werden die Bruecken eigens bestimmt und in den Plaenen
OBERHALB aller Gelaende-/Nutzungsflaechen gezeichnet - zusammen mit dem, was sie tragen: Fahrbahn mit Gehwegen, ein Fussweg oder die Bahn.

Quellen (beide zusammen): ALKIS-Bauwerke (Berlin; Objekte mit "Bruecke" in den Attributen = die echte Umringsform) und OpenStreetMap
(bridge=*, Linien auf Fahrbahn-/Gleisbreite gepuffert, man_made=bridge als Flaeche). Wo beide dieselbe Bruecke kennen, gilt der ALKIS-Umring,
und OSM liefert die Art (Strasse/Weg/Bahn) und die Lage der Fahrbahn.
Ergebnis: Liste von dicts  typ ('strasse'|'weg'|'bahn'), deck (Gesamtflaeche), fahrbahn, gehweg (Polygone oder None), quelle.
"""
import re

import numpy as np
import shapely
from shapely.geometry import Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

import ifcmap_kern as K

WEG_BREITE = {"footway": 3.0, "path": 2.5, "cycleway": 3.0, "pedestrian": 4.0, "steps": 2.5, "bridleway": 2.5, "corridor": 2.5, "track": 3.0}
GLEIS_BREITE = 4.6          # m je Gleis (Bahn) bzw. 3,2 m (Strassenbahn)
GEHWEG_BRUECKE = 2.0        # m je Seite, wenn OSM keine Angabe hat (nicht an Autobahnen/Schnellstrassen)
KEIN_GEHWEG = {"motorway", "motorway_link", "trunk", "trunk_link", "service", "track"}
MIN_FLAECHE = 6.0           # m2: kleinere Brueckenreste werden nicht gezeichnet
_BRUECKE = re.compile(r"br(ü|ue|u)cke|viadukt|\bbruecke", re.I)


def _zahl(v, vorgabe=None):
    try:
        return float(str(v).replace(",", ".").split()[0])
    except Exception:
        return vorgabe


def _osm_posten(g, t):
    """OSM-Bruecke -> dict(art 'linie'|'flaeche', typ, geom (Linie bzw. Flaeche), fb (Fahrbahnbreite), gw (Gehwegbreite je Seite)) oder None"""
    hw, rw = t.get("highway"), t.get("railway")
    if g.geom_type in ("Polygon", "MultiPolygon"):
        return dict(art="flaeche", typ=None, geom=g, fb=0.0, gw=0.0)
    if t.get("tunnel") in ("yes", "building_passage", "culvert"):
        return None
    if rw in ("rail", "light_rail", "subway", "narrow_gauge", "funicular", "tram"):
        b = _zahl(t.get("width"), None) or (3.2 if rw == "tram" else GLEIS_BREITE)
        return dict(art="linie", typ="bahn", geom=g, fb=b, gw=0.0)
    if hw:
        if hw in WEG_BREITE:
            return dict(art="linie", typ="weg", geom=g, fb=_zahl(t.get("width"), None) or WEG_BREITE[hw], gw=0.0)
        fb = _zahl(t.get("width"), None)
        if fb is None:
            lanes = _zahl(t.get("lanes"), None)
            fb = (lanes * 3.25) if lanes else K.STRASSENBREITE.get(hw, 6.5)
        gw = 0.0 if hw in KEIN_GEHWEG else GEHWEG_BRUECKE
        if str(t.get("sidewalk", "")).lower() == "no":
            gw = 0.0
        return dict(art="linie", typ="strasse", geom=g, fb=max(fb, 3.0), gw=gw)
    return None


def _linien(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == "LineString":
        return [g]
    return [x for x in getattr(g, "geoms", []) if x.geom_type == "LineString"]


def _alkis_bruecken(d, log):
    out = []
    for g, props in (getattr(d, "zusatz", {}) or {}).get("Bauwerke", []) or []:
        txt = " ".join(str(v) for v in (props or {}).values() if isinstance(v, str))
        if _BRUECKE.search(txt):
            out += [p for p in K._polys(g) if p.area >= MIN_FLAECHE]
    return out


def _nachbar_typ(d, poly):
    """Art einer ALKIS-Bruecke ohne OSM-Angabe: was liegt an ihren Enden (Strasse, Weg, Bahn)?"""
    ring = poly.buffer(4.0).difference(poly)
    reg = d.regionen or {}
    a = {}
    for kat, typ in (("Strasse", "strasse"), ("Weg_Platz", "weg"), ("Bahn", "bahn")):
        g = reg.get(kat)
        a[typ] = ring.intersection(g).area if g is not None and not g.is_empty else 0.0
    if a["bahn"] > 0.5 * ring.area:
        return "bahn"
    if a["strasse"] >= a["weg"] and a["strasse"] > 1.0:
        return "strasse"
    if a["weg"] > 1.0:
        return "weg"
    return "strasse" if poly.area > 60 else "weg"


def _teilen(d, deck, linien, nur_nah_gehweg):
    """Strassenbruecke -> (fahrbahn, gehweg). linien = [(LineString, fb, gw)] der OSM-Fahrbahnen auf der Bruecke."""
    gehweg = None
    if linien:
        fb = unary_union([ln.buffer(w / 2.0, cap_style=2) for ln, w, _ in linien]).intersection(deck)
        if any(gw > 0 for _, _, gw in linien):
            gw_ = deck.difference(fb.buffer(0.05, join_style=2))
            gw_ = gw_.buffer(-0.35, join_style=2).buffer(0.35, join_style=2)
            gehweg = gw_ if not gw_.is_empty and gw_.area >= 1.0 else None
    else:
        fgn = getattr(d, "fgn", None)
        if fgn:
            import ifcmap_plaene as PL
            wege, _ = PL.fgn_bereinigen(deck, fgn)
            fb_, gw_ = PL.gehweg_fgn(deck, wege, 2.0)
            gehweg = gw_ if gw_ is not None and not gw_.is_empty else None
    if gehweg is not None and nur_nah_gehweg is not None:
        gehweg = gehweg.intersection(nur_nah_gehweg)
        gehweg = gehweg if not gehweg.is_empty else None
    fahrbahn = deck if gehweg is None else deck.difference(gehweg)
    return fahrbahn, gehweg


def decks_vereint(d):
    """Alle Brueckenflaechen als EIN Polygon (oder None) - ohne Netzabfrage, nur mit dem, was schon geladen ist (ALKIS-Bauwerke, bereits
    geholte OSM-Bruecken). Fuer das IFC-Gelaende: unter/auf Bruecken keine Buergersteige und kein Bordstein."""
    teile = list(_alkis_bruecken(d, lambda *a: None))
    for g, t in getattr(d, "_osm_bruecken", None) or []:
        p = _osm_posten(g, t)
        if p is None:
            continue
        if p["art"] == "flaeche":
            teile += K._polys(p["geom"])
        else:
            hb = p["fb"] / 2.0 + (p["gw"] if p["typ"] == "strasse" else 0.0)
            teile.append(p["geom"].buffer(hb, cap_style=2))
    teile = [t for t in teile if t is not None and not t.is_empty]
    return unary_union(teile) if teile else None


def bruecken(d, cfg, log=print):
    """Alle Bruecken im Gebiet (am Datensatz d gemerkt). -> Liste von dicts (siehe Modulkopf)"""
    if getattr(d, "_bruecken", None) is not None:
        return d._bruecken
    try:
        K.bahn_achsen(d, cfg, log)                                    # laedt ggf. auch die OSM-Bruecken (eine Abfrage)
    except Exception as e:
        log("  OSM-Bruecken nicht verfuegbar (%s)" % str(e)[:80])
    osm = []
    for g, t in getattr(d, "_osm_bruecken", None) or []:
        p = _osm_posten(g, t)
        if p is not None:
            osm.append(p)
    alk = _alkis_bruecken(d, log)
    ueberall = bool(getattr(cfg, "gehweg_ueberall", False))
    bereich = getattr(d, "detail_rect", None) or getattr(d, "nah_rect", None)
    nah = None if ueberall or bereich is None else bereich.buffer(0)
    erg = []
    benutzt = set()
    # 1) ALKIS-Umringe: Art und Fahrbahnlage aus den OSM-Linien darauf (eine OSM-Linie kann laenger sein als die Bruecke: der Rest
    #    ausserhalb des Umrings bleibt eine eigene OSM-Bruecke)
    zonen_alle = []
    for A in alk:
        zone = A.buffer(1.5)
        zonen_alle.append(zone)
        treffer = []
        for i, p in enumerate(osm):
            if p["art"] != "linie":
                continue
            ln = p["geom"]
            if ln.length > 0 and ln.intersection(zone).length >= min(0.5 * ln.length, 6.0):
                treffer.append(i)
        if treffer:
            gew = {"bahn": 0.0, "strasse": 0.0, "weg": 0.0}
            for i in treffer:
                gew[osm[i]["typ"]] += osm[i]["geom"].intersection(zone).length
            typ = "bahn" if gew["bahn"] > 0 else ("strasse" if gew["strasse"] > 0 else "weg")
            benutzt.update(treffer)
            quelle = "ALKIS + OSM"
        else:
            typ, quelle = _nachbar_typ(d, A), "ALKIS"
        linien = [(osm[i]["geom"], osm[i]["fb"], osm[i]["gw"]) for i in treffer if osm[i]["typ"] == "strasse"] if typ == "strasse" else []
        e = dict(typ=typ, deck=A, quelle=quelle, fahrbahn=A, gehweg=None)
        if typ == "strasse":
            e["fahrbahn"], e["gehweg"] = _teilen(d, A, linien, nah)
        erg.append(e)
    # Reste langer OSM-Linien ausserhalb der ALKIS-Umringe
    if zonen_alle:
        zu = unary_union(zonen_alle).buffer(2.0)
        for i in sorted(benutzt):
            p = osm[i]
            for rest in _linien(p["geom"].difference(zu)):
                if rest.length >= 4.0:
                    osm.append(dict(p, geom=rest))
    # 2) uebrige OSM-Bruecken (nicht von einem ALKIS-Umring erfasst)
    flaechen = [p for p in osm if p["art"] == "flaeche"]
    for i, p in enumerate(osm):
        if p["art"] != "linie" or i in benutzt:
            continue
        ln = p["geom"]
        if p["typ"] == "strasse":
            hb = p["fb"] / 2.0 + p["gw"]
        else:
            hb = p["fb"] / 2.0
        deck = ln.buffer(hb, cap_style=2).intersection(d.rect)
        for q in K._polys(deck):
            if q.area < MIN_FLAECHE:
                continue
            e = dict(typ=p["typ"], deck=q, quelle="OSM", fahrbahn=q, gehweg=None)
            if p["typ"] == "strasse":
                e["fahrbahn"], e["gehweg"] = _teilen(d, q, [(ln, p["fb"], p["gw"])], nah)
            erg.append(e)
    # 3) man_made=bridge-Flaechen, die weder ALKIS noch eine OSM-Linie abdeckt
    if flaechen:
        bekannt = unary_union([e["deck"] for e in erg]) if erg else None
        for p in flaechen:
            g = p["geom"].intersection(d.rect)
            if bekannt is not None and not bekannt.is_empty:
                g = g.difference(bekannt.buffer(0.5))
            for q in K._polys(g):
                if q.area < 20.0:
                    continue
                typ = _nachbar_typ(d, q)
                e = dict(typ=typ, deck=q, quelle="OSM-Flaeche", fahrbahn=q, gehweg=None)
                if typ == "strasse":
                    e["fahrbahn"], e["gehweg"] = _teilen(d, q, [], nah)
                erg.append(e)
    for e in erg:
        for k in ("deck", "fahrbahn", "gehweg"):
            if e[k] is not None:
                g = e[k].intersection(d.rect)
                e[k] = g if not g.is_empty else None
    erg = [e for e in erg if e["deck"] is not None and e["deck"].area >= MIN_FLAECHE]
    d._bruecken = erg
    if erg:
        n = {t: sum(1 for e in erg if e["typ"] == t) for t in ("strasse", "weg", "bahn")}
        log("  Bruecken fuer die 2D-Plaene: %d (Strasse %d, Weg %d, Bahn %d; %s) - liegen oberhalb von Gelaende, Wasser und Bahnflaeche" % (
            len(erg), n["strasse"], n["weg"], n["bahn"], ", ".join(sorted({e["quelle"] for e in erg}))))
    else:
        log("  Bruecken: keine gefunden (ALKIS-Bauwerke mit 'Bruecke' im Attribut oder OSM bridge=*)")
    return erg


# ----------------------------------------------------------------------------------------------
# IFC: Strasse / Weg ueber die Bruecke ziehen
# ----------------------------------------------------------------------------------------------
DECK_DICKE = 0.8            # m Brueckenplatte unter der Fahrbahn (nur als Koerper, keine Statik)


def ifc_decks_vorbereiten(d, cfg, reg_gel, fahrbahn, log=print):
    """Schritt 1 (vor dem Aufteilen des Gelaendes): Strassen- und Wegbruecken bestimmen und ihre Flaeche aus Strasse/Gehweg/Weg des
    Gelaendes herausnehmen (das DGM liegt dort in der Schlucht bzw. hat unter der Bruecke Luecken). -> (reg_gel, fahrbahn, decks)"""
    if not getattr(cfg, "bruecken_ifc", True):
        return reg_gel, fahrbahn, []
    try:
        br = bruecken(d, cfg, lambda *a: None)
    except Exception as e:
        log("  HINWEIS: Bruecken im IFC nicht beruecksichtigt (%s)" % str(e)[:80])
        return reg_gel, fahrbahn, []
    decks, alle_decks = [], []
    n_ohne = 0
    for e in br:
        if e["typ"] not in ("strasse", "weg") or e.get("deck") is None or e["deck"].area < 20.0:
            continue
        # Nur Bruecken, die im LoD2 als Koerper vorhanden sind, bekommen Fahrbahn/Gehweg obenauf. Wo der Koerper nicht erkannt wird, bleibt alles wie es
        # war (keine Fahrbahn ueber die Bruecke): eine Ebene aus den Gelaendehoehen laege sonst unter der LoD2-Platte.
        try:
            lod = _lod2_oberseite(d, e["deck"])
        except Exception:
            lod = None
        alle_decks.append(e["deck"])                          # Strasse/Gehweg/Weg werden auf JEDER Bruecke aus dem Gelaende genommen (nicht in die Schlucht)
        if lod is None:
            n_ohne += 1
            continue
        e["_lod"] = lod
        decks.append(e)
    if n_ohne:
        log("  %d Bruecke(n) ohne LoD2-Koerper: dort keine Fahrbahn/kein Gehweg (bleibt weg)" % n_ohne)
    if not alle_decks:
        return reg_gel, fahrbahn, []
    allv = unary_union(alle_decks)
    neu = {}
    for k, v in reg_gel.items():
        neu[k] = v.difference(allv) if k in ("Strasse", "Gehweg", "Weg_Platz") and v is not None and not v.is_empty else v
    if fahrbahn is not None and not fahrbahn.is_empty:
        fahrbahn = fahrbahn.difference(allv)
    return neu, fahrbahn, decks


def _lod2_oberseite(d, deck):
    """Ist die Bruecke im LoD2 als Koerper (Platte) vorhanden, liegt ihre Oberseite in den Dachflaechen der Teile. -> (Hoehenfunktion z(x, y), Anteil
    des Decks, der von Dachflaechen bedeckt ist) oder None. Die Fahrbahn wird dann auf diese Oberseite gelegt statt eine zweite Platte zu bauen."""
    from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator
    cache = getattr(d, "_dach_baum", None)
    if cache is None:
        polys, arrs = [], []
        for t in getattr(d, "teile", None) or []:
            for e, h in t.get("roof") or []:
                if len(e) >= 3:
                    try:
                        pg = Polygon(e[:, :2]).buffer(0)
                    except Exception:
                        continue
                    if not pg.is_empty:
                        polys.append(pg)
                        arrs.append(np.asarray(e, float))
        cache = d._dach_baum = (shapely.STRtree(polys) if polys else None, polys, arrs)
    baum, polys, arrs = cache
    if baum is None:
        return None
    idx = baum.query(deck, predicate="intersects")
    if not len(idx):
        return None
    ueb = unary_union([polys[i].intersection(deck) for i in idx])
    anteil = ueb.area / max(deck.area, 1e-6)
    if anteil < 0.4:
        return None
    V = np.vstack([arrs[i] for i in idx])
    if len(V) < 3:
        return None
    try:
        lin = LinearNDInterpolator(V[:, :2], V[:, 2])
        nn = NearestNDInterpolator(V[:, :2], V[:, 2])
    except Exception:
        return None

    def f(x, y):
        x, y = np.asarray(x, float), np.asarray(y, float)
        z = lin(x, y)
        return np.where(np.isnan(z), nn(x, y), z)
    return f, anteil


def ifc_decks_flaechen(d, decks, interp, log=print):
    """Schritt 2 (nach dem Aufteilen): Fahrbahn/Gehweg obenauf die LoD2-Bruecke legen (nur wo der LoD2-Koerper erkannt wurde; sonst weggelassen). Frueher: Ebene durch das Gelaende an
    beiden Enden der Bruecke. Fahrbahn und Gehweg liegen gleich hoch; darunter eine duenne Platte (Kategorie 'Bruecke').
    -> dict Kategorie -> Liste von Dreiecken (3,3)"""
    out = {}
    n_ok = 0
    for e in decks:
        lod = e.get("_lod")
        if lod is None:
            try:
                lod = _lod2_oberseite(d, e["deck"])
            except Exception:
                lod = None
        if lod is not None:                                   # Bruecke steckt schon als Koerper im LoD2: nur Fahrbahn/Gehweg obenauf
            fz, anteil = lod
            top = lambda x, y, fz=fz: np.asarray(fz(x, y), float) + 0.04
            teile = [("Strasse", e.get("fahrbahn")), ("Gehweg", e.get("gehweg"))] if e["typ"] == "strasse" else [("Weg_Platz", e.get("fahrbahn"))]
            nn_ = 0
            for kat, g in teile:
                if g is None or g.is_empty:
                    continue
                for pg in K._polys(g):
                    for tri in _tri_poly_fein(pg, top):
                        out.setdefault(kat, []).append(tri)
                        nn_ += 1
            if nn_:
                n_ok += 1
                log("  Bruecke (%s, %s) bei (%.0f, %.0f): %.0f m2 - im LoD2 als Koerper vorhanden (%.0f %% des Decks), Fahrbahn/Gehweg liegen auf der LoD2-Oberseite"
                    % (e["typ"], e["quelle"], e["deck"].centroid.x - d.e0, e["deck"].centroid.y - d.n0, e["deck"].area, 100 * anteil))
                continue
        log("  Bruecke bei (%.0f, %.0f): kein LoD2-Koerper gefunden - keine Fahrbahn ueber die Bruecke" % (e["deck"].centroid.x - d.e0, e["deck"].centroid.y - d.n0))
    return out


def _tri_poly_fein(pg, zf, raster=4.0):
    """wie _tri_poly, aber die Flaeche wird vorher an einem Raster von ca. 4 m zerschnitten - die Hoehe folgt so einer schraegen/geknickten Oberseite"""
    x0, y0, x1, y1 = pg.bounds
    res = []
    xs = np.arange(x0, x1 + raster, raster)
    ys = np.arange(y0, y1 + raster, raster)
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            teil = pg.intersection(box(xs[i], ys[j], xs[i + 1], ys[j + 1]))
            if teil.is_empty:
                continue
            for q in K._polys(teil):
                if q.area > 1e-3:
                    res += _tri_poly(q, zf)
    return res


def _tri_poly(pg, zf, unten=False):
    """Polygon (mit Loechern) -> Dreiecke (3,3) mit Hoehe zf(x, y); Normale nach oben (unten=True: nach unten)"""
    import mapbox_earcut as earcut
    rings = [np.asarray(pg.exterior.coords)[:-1]] + [np.asarray(i.coords)[:-1] for i in pg.interiors]
    v = np.vstack(rings)
    ends = np.cumsum([len(r) for r in rings]).astype(np.uint32)
    idx = earcut.triangulate_float64(np.ascontiguousarray(v, dtype=np.float64), ends).reshape(-1, 3)
    z = zf(v[:, 0], v[:, 1])
    P3 = np.column_stack([v, z])
    res = []
    for i in idx:
        t = P3[i].copy()
        a2 = (t[1, 0] - t[0, 0]) * (t[2, 1] - t[0, 1]) - (t[1, 1] - t[0, 1]) * (t[2, 0] - t[0, 0])
        if (a2 < 0) != bool(unten):
            t = t[[0, 2, 1]]
        res.append(t)
    return res


def zeichne(z, d, erg, S, lage, an, log=print):
    """Bruecken oberhalb aller Flaechen zeichnen. Lageplan: Fahrbahn, Gehweg, Weg, Bahn in den Farben der jeweiligen Ebenen plus duenne Kontur.
    Schwarzplan: nur dort, wo eine Bruecke Wasser quert, wird das Wasser unterbrochen (weisse Flaeche)."""
    import ifcmap_plaene as PL
    if not erg:
        return 0
    n = 0
    if lage:
        gruppen = (("strasse", "fahrbahn", "2D_Bruecke_Fahrbahn", S["fahrbahn"]), ("bahn", "fahrbahn", "2D_Bruecke_Bahn", S["bahn"]),
                   ("weg", "fahrbahn", "2D_Bruecke_Weg", S["gehweg"]))
        for typ, feld, name, rgb in gruppen:
            gs = [e[feld] for e in erg if e["typ"] == typ and e[feld] is not None]
            if gs:
                n += z.flaeche(unary_union(gs), name, rgb, min_flaeche=1.0, min_loch=1.0) or 0
        gw = [e["gehweg"] for e in erg if e["gehweg"] is not None]
        if gw:
            n += z.flaeche(unary_union(gw), "2D_Bruecke_Gehweg", S["gehweg"], min_flaeche=0.5, min_loch=0.5) or 0
        PL.zeichne_kontur(z, [e["deck"] for e in erg], (90, 90, 95), 13, "2D_Kontur_Bruecke")
    else:
        wasser = (d.regionen or {}).get("Gewaesser")
        if wasser is not None and not wasser.is_empty:
            ueber = unary_union([e["deck"] for e in erg]).intersection(wasser)
            if not ueber.is_empty and ueber.area > 1.0:
                n += z.flaeche(ueber.buffer(0.2, join_style=2), "2D_Bruecke", (255, 255, 255), min_flaeche=1.0, min_loch=1.0) or 0
    return n
