"""Beschriftung des Lageplans: Flurstuecksnummern (ALKIS), Hausnummern und Strassennamen (OpenStreetMap), Gebaeudehoehen (LoD2).

Jede Art liegt auf eigener Ebene (2D_Text_...), Texthoehe = 2,5 mm auf dem Papier im gewaehlten Massstab.
Die Hausnummern und Strassennamen stehen nur in OpenStreetMap-Daten bereit (ein amtlicher Dienst dafuer ist nicht hinterlegt);
wo OpenStreetMap nichts hat, bleibt der Text weg. Die Flurstuecksnummern kommen aus den ALKIS-Flurstuecken (Berlin), sofern der Haken
fuer die ALKIS-Zusatzdaten gesetzt ist.
"""
import math

import numpy as np
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

TEXT_MM = 2.5


def _z(v, nk=1):
    return ("%.*f" % (nk, v)).replace(".", ",")


def _lese(props, *namen):
    low = {str(k).lower(): v for k, v in (props or {}).items()}
    for n in namen:
        for k, v in low.items():
            if n in k and v not in (None, "", " "):
                return v
    return None


def flurstuecksnummer(props):
    """'zaehler/nenner' aus den ALKIS-Attributen (Namen werden tolerant gesucht); sonst die letzte Kennzeichen-Gruppe"""
    zaehler = _lese(props, "zaehler", "zähler")
    nenner = _lese(props, "nenner")
    if zaehler not in (None, ""):
        try:
            zz = str(int(float(zaehler)))
        except (TypeError, ValueError):
            zz = str(zaehler)
        try:
            nn = int(float(nenner)) if nenner not in (None, "") else 0
        except (TypeError, ValueError):
            nn = 0
        return "%s/%d" % (zz, nn) if nn else zz
    nr = _lese(props, "flurstuecksnummer", "flstnr", "flurstueck_nr", "nummer")
    if nr not in (None, ""):
        return str(nr)
    kz = _lese(props, "kennzeichen", "kennz", "flstkennz")
    if kz:
        t = str(kz).replace(" ", "")
        for tr in ("-", "_"):
            if tr in t:
                return t.rsplit(tr, 1)[-1].lstrip("0") or t
        return t[-6:].lstrip("0") or t
    return None


def _text(z, d, txt, x, y, layer, hoehe, drehung=0.0, rgb=(40, 40, 40)):
    from ezdxf.enums import TextEntityAlignment
    z.layer(layer, rgb)
    t = z.msp.add_text(txt, height=hoehe, rotation=drehung, dxfattribs={"layer": layer})
    t.set_placement((round(x - d.e0, 3), round(y - d.n0, 3)), align=TextEntityAlignment.MIDDLE_CENTER)


def _lesbar(w):
    """Drehwinkel so, dass der Text nie auf dem Kopf steht"""
    while w > 90:
        w -= 180
    while w <= -90:
        w += 180
    return w


def gebaeudehoehen(d):
    """[(x, y, traufe, first, gelaende)] je Gebaeude (nur Teile mit Dach), Mittelpunkt = Punkt im Grundriss"""
    je = {}
    for t in d.teile:
        je.setdefault(t.get("gebaeude") or t["id"], []).append(t)
    out = []
    for gid, ts in je.items():
        gr = [e for t in ts for e, h in (t.get("ground") or []) if len(e) >= 3]
        if not gr:
            continue
        flaeche = unary_union([Polygon(e[:, :2]).buffer(0) for e in gr])
        if flaeche.is_empty or flaeche.area < 20.0:
            continue
        z_g = float(min(e[:, 2].min() for e in gr))
        tr, fi = [], []
        for t in ts:
            if t.get("roofz"):
                tr.append(t["roofz"][0])
                fi.append(t["roofz"][1])
            elif t.get("roof"):
                tr.append(float(min(e[:, 2].min() for e, h in t["roof"])))
                fi.append(float(max(e[:, 2].max() for e, h in t["roof"])))
        if not tr:
            continue
        p = flaeche.representative_point()
        out.append((p.x, p.y, float(min(tr)), float(max(fi)), z_g))
    return out


def strassen_und_nummern(d, cfg, log, strassen=True, nummern=True):
    """OpenStreetMap -> (Strassenlinien {Name: [LineString]}, Hausnummern [(x, y, Nummer)])"""
    import ifcmap_kern as K
    teile = []
    if strassen:
        teile.append('way["highway"]["name"]')
    if nummern:
        teile.append('nwr["addr:housenumber"]')
    el = K._osm_elemente(teile, cfg, d, log)
    geo = K._osm_geometrien(el, cfg.epsg) if el else []
    rect = d.rect
    lin, nr = {}, []
    for g, t in geo:
        if g.is_empty:
            continue
        if strassen and "highway" in t and t.get("name") and g.geom_type == "LineString":
            lin.setdefault(t["name"], []).append(g)
        elif nummern and t.get("addr:housenumber"):
            p = g.representative_point() if g.geom_type != "Point" else g
            if rect.contains(p):
                nr.append((p.x, p.y, str(t["addr:housenumber"])))
    return lin, nr


def zeichne(z, d, log=print):
    cfg = d.cfg
    M = float(getattr(cfg, "lp_text_massstab", 500) or 500)
    h = TEXT_MM * 1e-3 * M
    rect = d.rect
    n = {}
    # Flurstuecksnummern
    if getattr(cfg, "lp_text_flurstuecke", True):
        zus = (getattr(d, "zusatz", {}) or {}).get("Flurstuecke") or []
        k = 0
        for g, props in zus:
            nr = flurstuecksnummer(props)
            if not nr or g is None or g.is_empty:
                continue
            p = g.representative_point()
            if rect.contains(p):
                _text(z, d, nr, p.x, p.y, "2D_Text_Flurstuecke", h, rgb=(150, 90, 160))
                k += 1
        n["Flurstuecksnummern"] = k
        if zus and not k:
            log("  HINWEIS: in den ALKIS-Flurstuecken wurde keine Nummer gefunden (Attributnamen: %s)" % ", ".join(sorted(map(str, zus[0][1].keys()))[:12]))
        elif not zus:
            log("  HINWEIS: keine ALKIS-Flurstuecke geladen (Haken fuer die ALKIS-Zusatzdaten setzen, nur Berlin) - keine Flurstuecksnummern")
    # Hausnummern, Strassennamen
    want_s, want_n = getattr(cfg, "lp_text_strassen", True), getattr(cfg, "lp_text_hausnummern", True)
    if want_s or want_n:
        try:
            lin, nums = strassen_und_nummern(d, cfg, log, want_s, want_n)
        except Exception as e:
            log("  HINWEIS: Strassennamen/Hausnummern nicht verfuegbar (%s)" % str(e)[:100])
            lin, nums = {}, []
        if want_n:
            for x, y, nr in nums:
                _text(z, d, nr, x, y, "2D_Text_Hausnummern", h * 0.8, rgb=(60, 60, 60))
            n["Hausnummern"] = len(nums)
        if want_s:
            k = 0
            for name, ls in lin.items():
                best = None
                for g in ls:
                    ins = g.intersection(rect)
                    for part in getattr(ins, "geoms", [ins]):
                        if part.geom_type == "LineString" and (best is None or part.length > best.length):
                            best = part
                if best is None or best.length < len(name) * h * 0.7:
                    continue
                m = best.interpolate(0.5, normalized=True)
                a = best.interpolate(max(0.0, best.length / 2 - 1.0))
                b = best.interpolate(min(best.length, best.length / 2 + 1.0))
                w = _lesbar(math.degrees(math.atan2(b.y - a.y, b.x - a.x)))
                _text(z, d, name, m.x, m.y, "2D_Text_Strassen", h * 1.2, w, rgb=(30, 30, 30))
                k += 1
            n["Strassennamen"] = k
    # Gebaeudehoehen
    if getattr(cfg, "lp_text_hoehen", True):
        nhn = getattr(cfg, "lp_text_hoehen_art", "gelaende") == "nhn"
        k = 0
        for x, y, tr, fi, zg in gebaeudehoehen(d):
            if not rect.contains(Point(x, y)):
                continue
            if nhn:
                txt = "Tr %s / Fi %s" % (_z(tr), _z(fi))
            else:
                txt = "Tr %s / Fi %s" % (_z(tr - zg), _z(fi - zg))
            if abs(fi - tr) < 0.3:
                txt = "H %s" % (_z(fi) if nhn else _z(fi - zg))
            _text(z, d, txt, x, y, "2D_Text_Gebaeudehoehen", h * 0.8, rgb=(30, 60, 110))
            k += 1
        n["Gebaeudehoehen"] = k
    log("  Lageplan-Beschriftung: " + ", ".join("%d %s" % (v, k) for k, v in n.items()) +
        " (Hoehen: %s)" % ("m ue. NHN" if getattr(cfg, "lp_text_hoehen_art", "gelaende") == "nhn" else "ueber Gelaende; Tr = Traufe, Fi = First"))
    return n
