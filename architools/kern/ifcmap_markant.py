# -*- coding: utf-8 -*-
"""IFCmap - Markante Gebaeude (Kirchtuerme, Kuppeln, Denkmale, Gebaeude mit komplexem Dach ...) besonders detailliert.

Ausloeser (kein Hoehenkriterium mehr):
  - eigene Liste (Name: Breite, Laenge)
  - OpenStreetMap-Merkmale (Kirche, Turm, Planetarium, Kuppel/Zwiebel/Kegel/Spitze als Dachform, Burg, Museum ...)
  - Denkmalkarte (Berlin: amtlich; sonst OSM-Tag heritage=*)
  - ungewoehnlich komplexes LoD2-Dach (viele Dachflaechen in vielen Richtungen oder grosser Anteil steiler Flaechen)
Standard: nur im Nahbereich ausformuliert; ueber 'markant_fern' auch im Fernbereich.
Ablauf je markantem Gebaeude (beste Quelle zuerst):
  1. Form aus dem Oberflaechenmodell (DOM, Laserscan-Hoehenraster, 1 m) - wenn Daten vorhanden und plausibel
  2. OpenStreetMap in 3D (building, building:part, height, roof:shape ...) - wenn die Tags brauchbar sind
  3. sonst bleibt das volle LoD2
Alles hier arbeitet in absoluten Projektkoordinaten (wie das LoD2); Hoehen in m ueber NHN.
"""
import math
import os
import re
import time
from types import SimpleNamespace

import numpy as np
import shapely
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from scipy.spatial import Delaunay, cKDTree
from scipy.interpolate import LinearNDInterpolator
from scipy.ndimage import maximum_filter

MAX_MARKANT = 40                      # Standard: hoechstens so viele Gebaeude (Rangfolge: Liste, OSM-Merkmal, Denkmal, Dachform)
OSM_TYPEN = {"cathedral", "church", "chapel", "mosque", "synagogue", "temple", "monastery", "shrine"}
OSM_MANMADE = {"tower", "campanile", "lighthouse", "observation"}
OSM_DACH_MARKANT = {"dome", "onion", "cone", "spire"}
OSM_AMENITY = {"planetarium", "place_of_worship", "theatre", "townhall", "courthouse"}
OSM_TOURISM = {"attraction", "museum"}
OSM_HISTORIC = {"castle", "monument", "tower", "city_gate", "fort", "palace", "manor"}
DACH_N, DACH_K, DACH_STEIL = 40, 10, 0.30    # komplexes Dach: >= N Flaechen in >= K Richtungsklassen, oder >= 30 % steile Flaeche (und >= 8 Flaechen)
RX_DOM_NAME = re.compile(r"(^|[_\-. ])dom\d*([_\-. ]|$)", re.I)


def ist_dom_datei(pfad):
    """Dateiname deutet auf ein Oberflaechenmodell (dom1_..., DOM1_...), nicht auf ein Gelaendemodell."""
    b = os.path.basename(pfad)
    return bool(RX_DOM_NAME.search(b)) and not re.search(r"dgm", b, re.I)


# ----------------------------------------------------------------------------------------------
# Auswahl
# ----------------------------------------------------------------------------------------------

def parse_liste(text, epsg):
    """'Name: 52.5, 13.4; Name2: 393000 5826000' -> [(name, x, y)] im Projekt-KBS."""
    out = []
    if not text or not text.strip():
        return out
    from pyproj import Transformer
    for i, teil in enumerate(re.split(r"[;\n]+", text)):
        teil = teil.strip()
        if not teil:
            continue
        name = ""
        m = re.match(r"^([^0-9\-+][^:]*):\s*(.*)$", teil)
        if m:
            name, teil = m.group(1).strip(), m.group(2)
        z = [float(x.replace(",", ".")) for x in re.findall(r"[-+]?\d+(?:[.,]\d+)?", teil.replace(", ", " ").replace(";", " "))]
        if len(z) < 2:
            continue
        a, b = z[0], z[1]
        if abs(a) <= 90 and abs(b) <= 180:                      # Breite, Laenge
            x, y = Transformer.from_crs("EPSG:4326", "EPSG:%d" % epsg, always_xy=True).transform(b, a)
        else:
            x, y = a, b
        out.append((name or "Liste_%d" % (i + 1), x, y))
    return out


def gebaeude_gruppen(d, nur_nah=False, cfg=None, mit_dach=True):
    """LoD2-Teile je Gebaeude zusammenfassen -> [dict(gid, teile, fp, zg, zmax, H, c, dach)]
    nur_nah: nur Gebaeude, deren Teile im Nahbereich liegen (spart im Fernbereich viel Rechenzeit)."""
    import ifcmap_kern as K
    gr = {}
    for t in d.teile:
        if nur_nah and cfg is not None and not K.nah_enthaelt(cfg, d, t["c"][0], t["c"][1]):
            continue
        gr.setdefault(t["gebaeude"] or t["id"], []).append(t)
    out = []
    for gid, teile in gr.items():
        polys, zs, zmax = [], [], None
        for t in teile:
            quelle = t["ground"] or t["roof"] or t["wall"]
            for e, h in quelle:
                if len(e) >= 3:
                    polys.append(Polygon(e[:, :2], [x[:, :2] for x in h if len(x) >= 3]).buffer(0))
            if t["ground"]:
                zs.append(min(e[:, 2].min() for e, h in t["ground"]))
            elif quelle:
                zs.append(min(e[:, 2].min() for e, h in quelle))
            if t.get("roofz"):
                zm = t["roofz"][1]
            elif t["roof"]:
                zm = max(e[:, 2].max() for e, h in t["roof"])
            elif zs and t.get("h"):
                zm = zs[-1] + t["h"]
            else:
                zm = None
            if zm is not None:
                zmax = zm if zmax is None else max(zmax, zm)
        if not polys or not zs:
            continue
        fp = unary_union(polys)
        if fp.is_empty:
            continue
        zg = min(zs)
        if zmax is None:
            zmax = zg + 3.0
        dach = K.dach_komplexitaet(teile) if mit_dach else (0, 0, 0.0)
        out.append(dict(gid=gid, teile=teile, fp=fp, zg=zg, zmax=zmax, H=zmax - zg, c=fp.centroid, dach=dach))
    return out


def _osm_matches(g, osm):
    """OSM-Objekte, die zum LoD2-Gebaeude g gehoeren -> (outlines, parts)"""
    if not osm:
        return [], []
    fp = g["fp"]
    outl, parts = [], []
    for i in osm["tree"].query(fp, predicate="intersects"):
        o = osm["objekte"][int(i)]
        gm = o["geom"]
        try:
            ov = gm.intersection(fp).area
        except Exception:
            continue
        if gm.area <= 0:
            continue
        if o["art"] == "part" and ov >= 0.5 * gm.area:
            parts.append(o)
        elif o["art"] == "building" and ov >= 0.4 * min(gm.area, fp.area):
            outl.append(o)
    return outl, parts


def osm_kriterium(objekte):
    """Markante OSM-Tags -> Text oder None"""
    for o in objekte:
        t = o["tags"]
        if t.get("building") in OSM_TYPEN:
            return "OSM building=%s" % t["building"]
        if t.get("amenity") in OSM_AMENITY:
            return "OSM amenity=%s" % t["amenity"]
        if t.get("man_made") in OSM_MANMADE:
            return "OSM man_made=%s" % t["man_made"]
        if t.get("roof:shape") in OSM_DACH_MARKANT:
            return "OSM roof:shape=%s" % t["roof:shape"]
        if t.get("tourism") in OSM_TOURISM:
            return "OSM tourism=%s" % t["tourism"]
        if t.get("historic") in OSM_HISTORIC:
            return "OSM historic=%s" % t["historic"]
    return None


def osm_denkmal(objekte):
    for o in objekte:
        if o["tags"].get("heritage") or o["tags"].get("heritage:operator"):
            return "OSM heritage=%s" % (o["tags"].get("heritage") or "ja")
    return None


def dach_komplex(dach):
    """dach = (n, k, steil) aus K.dach_komplexitaet -> Text oder None"""
    n, k, steil = dach
    if n >= DACH_N and k >= DACH_K:
        return "komplexe Dachform (%d Dachflaechen in %d Richtungen)" % (n, k)
    if n >= 8 and steil >= DACH_STEIL:
        return "komplexe Dachform (%d Dachflaechen, %.0f %% steil)" % (n, 100 * steil)
    return None


def _in_flaechen(g, flaechen, anteil=0.4):
    """Liegt das Gebaeude (Grundriss g["fp"]) zu mindestens `anteil` in einer der Flaechen? -> Index oder None"""
    fp = g["fp"]
    if fp.area <= 0:
        return None
    for i in flaechen["tree"].query(fp, predicate="intersects"):
        try:
            if flaechen["geoms"][int(i)].intersection(fp).area >= anteil * fp.area:
                return int(i)
        except Exception:
            continue
    return None


def bestimmen(d, cfg, log, osm=None, denkmal=None):
    """-> Liste markanter Gebaeude (dicts aus gebaeude_gruppen + name, grund, rang). Rang: 0 Liste, 1 OSM-Merkmal, 2 Denkmal, 3 Dachform.
    Es gibt kein Hoehenkriterium mehr. Standard nur Nahbereich (cfg.markant_fern: auch Fernbereich)."""
    liste = parse_liste(getattr(cfg, "markant_liste", ""), cfg.epsg)
    gruppen = gebaeude_gruppen(d, nur_nah=not getattr(cfg, "markant_fern", False), cfg=cfg)
    wahl = []
    n_geprueft = len(gruppen)
    for g in gruppen:
        grund, name, rang = [], "", 9
        buf = g["fp"].buffer(2.0)
        for n, x, y in liste:
            if buf.contains(Point(x, y)):
                grund.append("eigene Liste: %s" % n)
                name = n
                rang = min(rang, 0)
        outl, parts = ([], [])
        if osm is not None:
            outl, parts = _osm_matches(g, osm)
            k = osm_kriterium(outl + parts) if g["H"] >= 4 else None
            if k:
                grund.append(k)
                rang = min(rang, 1)
            if not name:
                for o in outl + parts:
                    if o["tags"].get("name"):
                        name = o["tags"]["name"]
                        break
        if getattr(cfg, "markant_denkmal", True):
            dk = None
            if denkmal is not None:
                i = _in_flaechen(g, denkmal)
                if i is not None:
                    dk = "Denkmalkarte: %s" % (denkmal["namen"][i] or "Baudenkmal")
                    if not name and denkmal["namen"][i]:
                        name = denkmal["namen"][i]
            if dk is None and osm is not None:
                dk = osm_denkmal(outl + parts)
            if dk:
                grund.append(dk)
                rang = min(rang, 2)
        if getattr(cfg, "markant_dach", True):
            dkx = dach_komplex(g["dach"])
            if dkx:
                grund.append(dkx)
                rang = min(rang, 3)
        if grund:
            g["grund"] = "; ".join(grund)
            g["name"] = name
            g["rang"] = rang
            wahl.append(g)
    nicht = [n for n, x, y in liste if not any(("eigene Liste: %s" % n) in g["grund"] for g in wahl)]
    for n in nicht:
        log("  Eigene Liste: '%s' liegt in keinem Gebaeude im %s - uebersprungen" % (n, "Rechteck" if cfg.markant_fern else "Nahbereich"))
    wahl.sort(key=lambda g: (g["rang"], -g["H"]))
    mx = int(getattr(cfg, "markant_max", MAX_MARKANT) or MAX_MARKANT)
    log("  %d Gebaeude geprueft (%s), %d markant" % (n_geprueft, "ganzes Rechteck" if cfg.markant_fern else "Nahbereich", len(wahl)))
    if len(wahl) > mx:
        log("  mehr als %d markante Gebaeude - ausgearbeitet werden nur die ersten %d (Rangfolge: eigene Liste, OSM-Merkmal, Denkmal, Dachform; dann nach Hoehe). "
            "Anzahl unter 'Markante Gebaeude' erhoehen oder die Liste nutzen." % (mx, mx))
        wahl = wahl[:mx]
    for g in wahl:
        if not g["name"]:
            g["name"] = str(g["gid"])[-10:]
    return wahl


# ----------------------------------------------------------------------------------------------
# OpenStreetMap 3D
# ----------------------------------------------------------------------------------------------

def osm_gebaeude_laden(d, cfg, log, K=None):
    """Alle Gebaeude und Gebaeudeteile des Rechtecks von Overpass -> dict(objekte, tree) oder None.
    (Zwischenspeicher, Zeitlimits und Ausfallschutz stecken in K.osm_abfragen.)"""
    import ifcmap_kern as K
    teile = ['way["building"]', 'relation["building"]', 'way["building:part"]', 'relation["building:part"]']
    ph = SimpleNamespace(xmin=d.xmin, xmax=d.xmax, ymin=d.ymin, ymax=d.ymax)
    el = K._osm_elemente(teile, cfg, ph, log)
    if not el:
        return None
    geo = K._osm_geometrien(el, cfg.epsg)
    objekte, verworfen = [], 0
    ohne_flaeche = sorted({"%s%s" % (e.get("type", "?") + "/" + str(e.get("id", "?")), (" '%s'" % e["tags"]["name"]) if (e.get("tags") or {}).get("name") else "")
                           for e in el if any(k in (e.get("tags") or {}) for k in ("building", "building:part"))}
                          - {"%s%s" % (g_t.get("_osm", "?"), (" '%s'" % g_t["name"]) if g_t.get("name") else "") for g_, g_t in geo if g_.geom_type in ("Polygon", "MultiPolygon")})
    if ohne_flaeche:
        log("  OpenStreetMap: %d Gebaeude/-teile ohne verwertbare Flaeche (z. B. Relation, deren Ringe nicht schliessen, weil Teile ausserhalb des Rechtecks liegen): %s%s"
            % (len(ohne_flaeche), ", ".join(ohne_flaeche[:6]), " ..." if len(ohne_flaeche) > 6 else ""))
    for g, t in geo:
        if g.geom_type not in ("Polygon", "MultiPolygon") or g.is_empty:
            continue
        if not g.is_valid:
            g = shapely.make_valid(g)
        polys = _polys_aus(g)                              # make_valid kann GeometryCollections liefern
        if not polys:
            verworfen += 1
            continue
        g = polys[0] if len(polys) == 1 else shapely.MultiPolygon(polys)
        if g.area < 1.0:
            verworfen += 1
            continue
        art = "part" if "building:part" in t else ("building" if "building" in t else None)
        if art:
            objekte.append(dict(geom=g, tags=t, art=art, id=t.get("_osm", "")))
    if not objekte:
        return None
    log("  OpenStreetMap: %d Gebaeude/-teile im Rechteck%s" % (len(objekte), (" (%d unbrauchbare Geometrien verworfen)" % verworfen) if verworfen else ""))
    return dict(objekte=objekte, tree=shapely.STRtree([o["geom"] for o in objekte]))


def _polys_aus(g):
    """Alle Polygone einer (auch gemischten) Geometrie"""
    if g.geom_type == "Polygon":
        return [g] if not g.is_empty else []
    if hasattr(g, "geoms"):
        out = []
        for x in g.geoms:
            out += _polys_aus(x)
        return out
    return []


def _hoehe(txt):
    """OSM-Zahl: '12', '12.5', '12,5 m', '40 ft', "130'" -> Meter (None, wenn keine Zahl)"""
    if txt is None:
        return None
    t = str(txt).strip().lower()
    m = re.search(r"\d+(?:[.,]\d+)?", t)
    if not m:
        return None
    v = float(m.group(0).replace(",", "."))
    if re.search(r"(ft|feet|foot|')", t[m.end():]):
        v *= 0.3048
    return v


TYP_HOEHEN = {"house": 8.0, "detached": 8.0, "semidetached_house": 8.0, "terrace": 9.0, "residential": 12.0, "apartments": 16.0,
              "dormitory": 14.0, "garage": 3.0, "garages": 3.0, "carport": 3.0, "shed": 3.0, "hut": 3.0, "cabin": 3.5, "roof": 3.0,
              "allotment_house": 3.0, "garden_house": 3.0, "garden_shed": 2.5, "greenhouse": 3.0, "kiosk": 3.0, "gazebo": 3.0, "pavilion": 4.0,
              "toilets": 3.0, "static_caravan": 3.0, "service": 4.0, "industrial": 9.0, "warehouse": 8.0, "commercial": 14.0, "office": 16.0, "retail": 8.0, "supermarket": 7.0,
              "school": 12.0, "kindergarten": 7.0, "hospital": 18.0, "church": 18.0, "chapel": 9.0, "hotel": 18.0, "yes": 10.0}


# Dachhoehe, die aus der Gebaeudebreite GESCHAETZT wird (kein roof:height im OSM), nie hoeher als dieser Wert je Dachform (m)
DACH_DECKEL = {"dome": 10.0, "onion": 12.0, "cone": 14.0, "spire": 25.0}
DACH_DECKEL_STANDARD = 8.0
HOEHE_OHNE_ANGABE = 2.2      # m: Gebaeude ohne Hoehe, Geschosse und Typ (wird aus cfg.hoehe_ohne_angabe gesetzt)
KLEINBAU_FLAECHE = ((25.0, 2.8), (50.0, 3.6), (90.0, 5.0))      # (Grundriss bis m2, Hoehe bis m): geschaetzte Hoehe kleiner Bauten (Gartenhaeuser, Schuppen)


def schaetz_hoehe_klein(flaeche, h):
    """Geschaetzte Hoehe h (m) eines Gebaeudes ohne Hoehenangabe: kleine Grundrisse (Laube, Schuppen) sind niedrig, egal was der Typ sagt"""
    for fl, hm in KLEINBAU_FLAECHE:
        if flaeche < fl:
            return min(h, hm)
    return h


def osm_hoehen(t, h_ref, breite, flaeche=None):
    """Tags -> (min_h, gesamt_h, dach_h, form, richtung, geschaetzt).
    gesamt_h = Hoehe bis zum First (OSM 'height'); aus building:levels (Geschosse ohne Dach) wird Traufe = Geschosse x 3 m, das Dach kommt dazu.
    Fehlen Hoehe und Geschosse, gilt h_ref (ein Wert in m, oder None -> Typ-Schaetzwert); geschaetzt=True."""
    mn = _hoehe(t.get("min_height")) or 0.0
    h = _hoehe(t.get("height"))
    form = (t.get("roof:shape") or "flat").lower().split(";")[0].strip()
    rh = _hoehe(t.get("roof:height"))
    if rh is None and t.get("roof:levels"):
        rh = (_hoehe(t.get("roof:levels")) or 0) * 1.5
    rh_abgeleitet = rh is None
    if rh is None:
        w = max(breite, 1.0) / 2.0
        ang = _hoehe(t.get("roof:angle")) or 30.0
        rh = {"flat": 0.0, "dome": w, "onion": w * 2.2, "cone": w * 2.5, "spire": w * 6.0, "pyramidal": w * math.tan(math.radians(ang)),
              "hipped": w * math.tan(math.radians(ang)), "gabled": w * math.tan(math.radians(ang)), "skillion": w * 0.3,
              "round": w * 0.8, "half-hipped": w * math.tan(math.radians(ang)) * 0.8, "gambrel": w * 0.7, "mansard": w * 0.6}.get(form, 0.0)
        rh = min(rh, DACH_DECKEL.get(form, DACH_DECKEL_STANDARD))        # breite Bauten (Rundschuppen, Hallen): kein riesiges Dach aus der Breite
    geschaetzt = False
    if h is None:
        lv = _hoehe(t.get("building:levels"))
        if lv:
            h = lv * 3.0 + rh
        else:
            geschaetzt = True
            typ = str(t.get("building", "yes"))
            if not h_ref and typ in ("yes", "", "true", "1"):
                h = HOEHE_OHNE_ANGABE                                    # Grundriss ohne jede Hoehenangabe und ohne Typ: einheitliche niedrige Hoehe
            else:
                h = h_ref if h_ref else TYP_HOEHEN.get(typ, 10.0)
                if flaeche is not None:
                    h = schaetz_hoehe_klein(flaeche, h)
    if h is not None and rh > 0:
        rh = min(rh, (0.6 if rh_abgeleitet else 0.9) * max(h - mn, 0.5))        # das Dach kann nicht hoeher sein als das Gebaeude
    r = t.get("roof:direction")
    richt = _hoehe(r) if r is not None and re.match(r"^[\d.]+$", str(r)) else None
    return mn, h, rh, form, richt, geschaetzt


def _dichte(poly):
    mnr = poly.minimum_rotated_rectangle
    xs, ys = mnr.exterior.coords.xy
    seiten = sorted([math.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i]) for i in range(2)])
    return seiten[0], seiten[1], mnr


def _rand_dicht(ring, s):
    """Ring (Nx2) so verdichten, dass keine Kante laenger als s ist"""
    out = []
    for i in range(len(ring) - 1):
        a, b = np.array(ring[i]), np.array(ring[i + 1])
        n = max(1, int(math.ceil(np.hypot(*(b - a)) / s)))
        for k in range(n):
            out.append(a + (b - a) * k / n)
    return np.array(out)


def _polys(g):
    return [g] if g.geom_type == "Polygon" else [p for p in g.geoms if p.geom_type == "Polygon"]


def _delaunay_innen(P, poly, rahmen=3.0, tol=1e-5):
    """Delaunay-Dreiecke der Punkte P (Nx2), die im Polygon liegen -> Indexfeld (m, 3).
    Ein Rahmen aus Hilfspunkten ausserhalb sorgt dafuer, dass Qhull Randpunkte auf einer Geraden (Traufkanten) nicht als 'koplanar'
    weglaesst: jede Randkante ist dann eine Dreieckskante und die Huelle (Waende - Dach - Boden) schliesst."""
    P = np.asarray(P, float)
    M0 = P.mean(axis=0)                                  # Koordinaten (Ost/Nord in Millionen) vor Qhull zum Schwerpunkt verschieben: rechnet sonst auf wenige Mikrometer genau
    P, poly = P - M0, shapely.transform(poly, lambda c: c - M0)
    x0, y0, x1, y1 = P[:, 0].min() - rahmen, P[:, 1].min() - rahmen, P[:, 0].max() + rahmen, P[:, 1].max() + rahmen
    xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
    fr = np.array([[x0, y0], [xm, y0], [x1, y0], [x1, ym], [x1, y1], [xm, y1], [x0, y1], [x0, ym]])
    n = len(P)
    tri = Delaunay(np.vstack([P, fr]))
    S = tri.simplices
    S = S[(S < n).all(axis=1)]
    if not len(S):
        return S
    cen = P[S].mean(axis=1)
    ok = shapely.contains_xy((poly.buffer(tol) if tol else poly), cen[:, 0], cen[:, 1])
    return S[ok]


def _platte(poly, z, oben):
    """Waagerechte Flaeche (Dach oder Boden) in der Hoehe z; oben=True: Normale zeigt nach oben, sonst nach unten."""
    from ifcmap_kern import faces_poly3d
    from shapely.geometry.polygon import orient
    out = []
    for p in _polys(poly):
        p = orient(p, 1.0)
        if hasattr(shapely, "constrained_delaunay_triangles"):
            # Der uebliche Ohr-Zerleger (earcut) wirft (fast) geradlinige Randpunkte weg - dann passt der Boden nicht mehr zu den Waenden
            # (auch ohne Hof, bei gedrehten Grundrissen). Die eingeschraenkte Delaunay-Zerlegung behaelt jeden Randpunkt.
            try:
                tris = [t for t in shapely.constrained_delaunay_triangles(p).geoms if t.geom_type == "Polygon"]
                if tris and abs(sum(t.area for t in tris) - p.area) < 1e-6 * max(p.area, 1.0) + 1e-3:
                    for t in tris:
                        f = np.column_stack([np.array(t.exterior.coords)[:-1], np.full(3, z)])
                        a = 0.5 * float(np.sum(f[:, 0] * np.roll(f[:, 1], -1) - np.roll(f[:, 0], -1) * f[:, 1]))
                        out.append(f if (a > 0) == oben else f[::-1])
                    continue
            except Exception:
                pass
        e = np.column_stack([np.array(p.exterior.coords)[:-1], np.full(len(p.exterior.coords) - 1, z)])
        h = [np.column_stack([np.array(r.coords)[:-1], np.full(len(r.coords) - 1, z)]) for r in p.interiors]
        for f in faces_poly3d(e, h):
            f = np.asarray(f)
            a = 0.5 * float(np.sum(f[:, 0] * np.roll(f[:, 1], -1) - np.roll(f[:, 0], -1) * f[:, 1]))
            out.append(f if (a > 0) == oben else f[::-1])
    return out


def dach_z(poly, form, rh, richtung, pts):
    """Dachhoehe ueber der Traufe an den Punkten pts (Nx2) fuer die Dachform"""
    if form == "flat" or rh <= 0:
        return np.zeros(len(pts))
    P = shapely.points(pts[:, 0], pts[:, 1])
    dist = shapely.distance(P, poly.exterior)
    for r in poly.interiors:
        dist = np.minimum(dist, shapely.distance(P, shapely.LinearRing(r.coords)))
    # Normierung an der Form (groesster Abstand zum Rand = Radius des Innenkreises), NICHT an den gerade abgefragten Punkten -
    # sonst bekaemen Waende (nur Randpunkte) und Dach (alle Punkte) verschiedene Hoehen am Rand
    try:
        from shapely.algorithms.polylabel import polylabel
        pol = polylabel(poly, tolerance=max(0.02, 0.01 * math.sqrt(poly.area)))
        dmax = float(poly.boundary.distance(pol))
    except Exception:
        dmax = float(dist.max())
    dmax = max(dmax, 1e-6)
    t = np.clip(dist / dmax, 0, 1)
    if form in ("pyramidal", "hipped", "cone", "spire", "half-hipped", "mansard", "gambrel"):
        return rh * t
    if form == "dome":
        return rh * np.sqrt(np.clip(1 - (1 - t) ** 2, 0, 1))
    if form == "onion":
        return rh * (0.65 * np.sqrt(np.clip(1 - (1 - t) ** 2, 0, 1)) + 0.35 * t)
    # Formen mit Firstachse: gabled, round, skillion
    w, l, mnr = _dichte(poly)
    xs, ys = mnr.exterior.coords.xy
    seg = [(xs[i + 1] - xs[i], ys[i + 1] - ys[i]) for i in range(2)]
    lang = max(seg, key=lambda s: math.hypot(*s))
    ang = math.atan2(lang[1], lang[0])
    if richtung is not None:                            # roof:direction = Himmelsrichtung der Dachflaeche (Grad, 0 = Nord)
        ang = math.radians(90 - richtung) + (math.pi / 2 if form != "skillion" else 0)
    c = np.array(poly.centroid.coords[0])
    u = (pts[:, 0] - c[0]) * (-math.sin(ang)) + (pts[:, 1] - c[1]) * math.cos(ang)    # quer zum First
    hw = max(np.abs(u).max(), 1e-6)
    if form == "skillion":
        return rh * (u + hw) / (2 * hw)
    if form == "round":
        return rh * np.sqrt(np.clip(1 - (u / hw) ** 2, 0, 1))
    return rh * (1 - np.abs(u) / hw)                    # gabled


def teil_faces(poly, z0, z_traufe, rh, form, richtung, bodenplatte=True):
    """Ein Gebaeude(teil) als Flaechen: Waende von z0 bis zur Dachkante, Dach nach Form, Boden. poly = shapely Polygon (absolut)."""
    faces = []
    if poly.is_empty or poly.area < 0.5:
        return faces
    from shapely.geometry.polygon import orient
    if poly.geom_type != "Polygon":
        for p in _polys(poly):
            faces += teil_faces(p, z0, z_traufe, rh, form, richtung, bodenplatte)
        return faces
    poly = orient(poly, 1.0)
    breite, lang, _ = _dichte(poly)
    s = float(np.clip(breite / 10.0, 0.6, 3.0))
    ringe = [poly.exterior] + list(poly.interiors)
    flach = form == "flat" or rh <= 0.05
    rand_pts = []
    for r in ringe:
        # flaches Dach: Ecken genuegen (Dach, Waende und Boden teilen dieselben Punkte -> geschlossene Huelle); sonst Kante verdichten
        rand_pts.append(np.round(np.array(r.coords)[:-1] if flach else _rand_dicht(list(r.coords), s), 4))   # auf 0,1 mm gerundet: Wand, Dach und Boden teilen exakt dieselben Punkte
    # Waende
    for k, rp in enumerate(rand_pts):
        n = len(rp)
        zr = z_traufe + (np.zeros(n) if flach else dach_z(poly, form, rh, richtung, rp))
        for i in range(n):
            a, b = rp[i], rp[(i + 1) % n]
            if math.hypot(*(a - b)) < 1e-4:
                continue
            faces.append(np.array([[a[0], a[1], z0], [b[0], b[1], z0], [b[0], b[1], zr[(i + 1) % n]], [a[0], a[1], zr[i]]]))
    # Dach
    if flach:
        faces += _platte(poly, z_traufe, True)
    else:
        gx = np.arange(poly.bounds[0] + s / 2, poly.bounds[2], s)
        gy = np.arange(poly.bounds[1] + s / 2, poly.bounds[3], s)
        X, Y = np.meshgrid(gx, gy)
        inn = shapely.contains_xy(poly.buffer(-s * 0.75), X.ravel(), Y.ravel())
        innen = np.column_stack([X.ravel()[inn], Y.ravel()[inn]])
        # Scheitel (hoechster Punkt) sicher dabei
        try:
            ip = poly.representative_point()
            innen = np.vstack([innen, [[ip.x, ip.y]]]) if len(innen) else np.array([[ip.x, ip.y]])
        except Exception:
            pass
        allp = np.vstack([np.vstack(rand_pts), innen]) if len(innen) else np.vstack(rand_pts)
        allp = np.unique(np.round(allp, 4), axis=0)
        if len(allp) >= 3:
            z = z_traufe + dach_z(poly, form, rh, richtung, allp)
            try:
                for sx in _delaunay_innen(allp, poly, 3 * s):
                    q = np.column_stack([allp[sx], z[sx]])
                    nz = np.cross(q[1] - q[0], q[2] - q[0])[2]
                    faces.append(q if nz >= 0 else q[::-1])
            except Exception:
                pass
    if bodenplatte:
        boden = poly
        if not flach:                                     # Boden mit denselben (verdichteten) Randpunkten wie Waende und Dach
            try:
                dp = Polygon(rand_pts[0], [r for r in rand_pts[1:] if len(r) >= 3])
                if dp.is_valid and abs(dp.area - poly.area) < 0.02 * poly.area:
                    boden = dp
            except Exception:
                pass
        faces += _platte(boden, z0, False)
    return faces


def osm_koerper(outl, parts, fp, zg, h_ref=None):
    """Koerper aus OSM-Umriss(en) und -Teilen (building:part mit min_height, height, roof:shape ...) ueber Boden zg (absolut).
    h_ref = Ersatzhoehe, wenn Tags fehlen. -> dict(faces, zmax, n, n_h, formen, geschaetzt) oder None"""
    nutz = list(parts)
    if parts:
        deck = unary_union([p["geom"] for p in parts]).intersection(fp).area
        if deck < 0.85 * fp.area:                          # Teile decken nicht alles: Umriss ergaenzt den Rest
            nutz += outl
    else:
        nutz = outl
    faces, zmax, n_h, n, gesch = [], zg, 0, 0, False
    for o in nutz:
        gm = o["geom"]
        polys = _polys_aus(gm)
        t = o["tags"]
        for pg in polys:
            if pg.area < 1.0:
                continue
            breite = _dichte(pg)[0]
            mn, h, rh, form, richt, ges = osm_hoehen(t, h_ref, breite, pg.area)
            if not ges:
                n_h += 1
            if o["art"] == "part" or not ges or len(nutz) == 1:
                z0 = zg + mn
                z_tr = zg + max(h - rh, mn + 0.5)
                faces += teil_faces(pg, z0, z_tr, rh, form, richt, bodenplatte=(mn <= 0.01))
                zmax = max(zmax, z_tr + rh)
                gesch = gesch or ges
                n += 1
    if n == 0 or not faces:
        return None
    formen = sorted({(o["tags"].get("roof:shape") or "flat") for o in nutz})
    return dict(faces=faces, zmax=zmax, n=n, n_h=n_h, formen=formen, geschaetzt=gesch)


def osm_detail(g, osm, log):
    """OSM-3D-Gebaeude fuer das markante Gebaeude g -> (faces, zmax_abs, text) / ("abgelehnt", Grund) / None"""
    outl, parts = _osm_matches(g, osm)
    if not outl and not parts:
        return ("leer", "kein OpenStreetMap-Gebaeude oder -Teil liegt auf dem Grundriss")
    r = osm_koerper(outl, parts, g["fp"], g["zg"], g["H"])
    if r is None or (r["n_h"] == 0 and not parts):
        return ("leer", "OpenStreetMap kennt hier weder Hoehe noch Etagen noch Gebaeudeteile - nichts zu uebernehmen")
    # Bringt OSM nichts Neues (keine Gebaeudeteile, nur ein flacher Quader mit Hoehe), ist das LoD2 besser: es hat die echte Dachform.
    # Sonst wuerde das markante Gebaeude durch den OSM-Block ERSETZT und verlore sein Dach.
    if not parts and all(f == "flat" for f in r["formen"]):
        return ("abgelehnt", "OSM kennt nur einen flachen Umriss mit Hoehe - das LoD2 (mit Dachform) bleibt")
    if not (0.55 * g["H"] <= r["zmax"] - g["zg"] <= 1.7 * g["H"]):
        return ("abgelehnt", "OSM-Hoehe %.0f m passt nicht zum LoD2 (%.0f m)" % (r["zmax"] - g["zg"], g["H"]))
    return r["faces"], r["zmax"], "%d Teile, Dachformen: %s" % (r["n"], ", ".join(r["formen"]))


# ----------------------------------------------------------------------------------------------
# DOM
# ----------------------------------------------------------------------------------------------

def dom_dateien(cfg, d, ziele, log, K):
    """Alle nutzbaren DOM-Dateien: eigene (cfg.dom, ZIPs werden entpackt) + automatisch geholte des Landes - EINE Abfrage fuer alle
    markanten Gebaeude zusammen (Kacheln, die nicht gebraucht werden, nicht). -> Liste von Pfaden"""
    import ifcmap_laender as L
    out = []
    for p in getattr(cfg, "dom", []) or []:
        if p.lower().endswith(".zip"):
            out += L._dgm_dateien_aus(p, None)
        else:
            out.append(p)
    grund = ""
    land = getattr(d, "land", None)
    if not land or land == "keins":
        grund = "kein Bundesland erkannt - kein automatischer Download"
    elif not cfg.online_dgm:
        grund = "automatischer Download ist abgeschaltet (Haken 'Gelaende online laden')"
    elif ziele:
        prof = L.profile(log).get(land) or {}
        if prof.get("dom"):
            b = unary_union([g["fp"].buffer(4) for g in ziele]).bounds
            _, _, fehlt = L.kacheln_holen(cfg, land, b, log, K, dgm=False, lod2=False, dom=True)
            neu = [f for f in L._DOM_LETZTE if f not in out]
            out += neu
            if not neu:
                grund = "Download von %s lieferte keine Datei (%s)" % (prof.get("name", land), "; ".join(fehlt)[:200] if fehlt else "siehe Zeilen darueber")
        else:
            grund = "fuer %s ist kein DOM-Download hinterlegt" % prof.get("name", land)
            log("  Fuer %s ist kein DOM-Download hinterlegt (eigene DOM-Dateien koennen angegeben werden)." % prof.get("name", land))
    if not out and not grund:
        grund = "keine DOM-Dateien angegeben"
    return out, grund


class DomPunkte:
    """Die DOM-Punkte aller markanten Gebaeude EINMAL lesen (nicht je Gebaeude die ganze Kachel) und dann ausschneiden."""

    def __init__(self, dateien, bbox, K, log):
        x0, y0, x1, y1 = bbox
        keep, skip = K.dgm_filtern(dateien, bbox, log)
        if skip:
            log("  DOM: %d Datei(en) liegen nicht in der Naehe der markanten Gebaeude und werden nicht gelesen" % len(skip))
        teile = []
        for p in keep:
            t0 = time.time()
            try:
                pts = K.lade_xyz(p, (x0, x1, y0, y1))
            except Exception as e:
                log("    DOM %s nicht lesbar: %s" % (os.path.basename(p), str(e)[:150]))
                continue
            if len(pts):
                m = (pts[:, 0] >= x0) & (pts[:, 0] <= x1) & (pts[:, 1] >= y0) & (pts[:, 1] <= y1)
                if m.any():
                    teile.append(pts[m])
            log("    DOM %s: %d Punkte (%.0f s)" % (os.path.basename(p), len(pts), time.time() - t0))
        self.pts = np.vstack(teile) if teile else np.zeros((0, 3))

    def ausschnitt(self, x0, y0, x1, y1):
        p = self.pts
        if not len(p):
            return p
        m = (p[:, 0] >= x0) & (p[:, 0] <= x1) & (p[:, 1] >= y0) & (p[:, 1] <= y1)
        return p[m]


GLAETTEN = True          # DOM glaetten (Ausreisser, Nodata, Rand); nur der Test schaltet ab
DOM_TOL = 0.5            # erlaubte Abweichung des Netzes von den DOM-Zellen (m): groessere Flaechen, weniger Beulen
# Glaettungsstufen der Dachhaut: (Bildabstand sigma in m fuer die kantenerhaltende Glaettung, Durchgaenge, erlaubte Abweichung des Netzes in m)
STUFEN = {"fein": (0.5, 2, 0.5), "normal": (0.8, 3, 0.6), "stark": (1.4, 5, 0.9)}
STUFE = "normal"


def _fenster9(Z):
    """neun gegeneinander verschobene Kopien (NaN am Rand) -> (9, ny, nx)"""
    ny, nx = Z.shape
    P = np.full((ny + 2, nx + 2), np.nan)
    P[1:-1, 1:-1] = Z
    return np.stack([P[dy:dy + ny, dx:dx + nx] for dy in range(3) for dx in range(3)])


def dom_glaetten(Z, zg, schwelle=1.2):
    """Einzelne Ausreisser (Antennen, Voegel, Rauschen, Nodata-Zellen) des Rasters entfernen: eine Zelle, die mehr als `schwelle` m vom Median
    ihrer 3x3-Nachbarschaft abweicht und weniger als zwei Nachbarn in ihrer Naehe (0,8 m) hat, wird durch den Median ersetzt.
    Echte Formen (Kuppel, Giebel, Turm) bleiben, weil dort Nachbarzellen mitsteigen.
    Werte weit unter dem Boden (Nodata wie -9999, 0) werden vorher verworfen."""
    Z = np.where((Z < zg - 3.0) | (Z > zg + 400.0), np.nan, Z)
    W = _fenster9(Z)
    with np.errstate(all="ignore"):
        med = np.nanmedian(W, axis=0)
        aehnlich = np.nansum(np.abs(W - Z[None]) <= 0.8, axis=0) - 1          # Nachbarn (ohne die Zelle selbst) auf gleicher Hoehe
    aus = ~np.isnan(Z) & ~np.isnan(med) & (np.abs(Z - med) > schwelle) & (aehnlich < 2)
    return np.where(aus, med, Z)


def _fenster25(Z):
    """25 gegeneinander verschobene Kopien (NaN am Rand) -> (25, ny, nx)"""
    ny, nx = Z.shape
    P = np.full((ny + 4, nx + 4), np.nan)
    P[2:-2, 2:-2] = Z
    return np.stack([P[dy:dy + ny, dx:dx + nx] for dy in range(5) for dx in range(5)])


def dom_bereinigen(Z, zg, sigma_h=0.8, durchgaenge=3):
    """Das DOM-Raster fuer die Dachhaut vorbereiten (Photogrammetrie rauscht: Spitzen von Antennen/Baeumen/Voegeln, Loecher, Dachflicken):
    1. Nodata und Ausreisser raus (Dach-Spitzen, die keine Nachbarn auf gleicher Hoehe haben), auch Zweiergruppen (Median 5x5)
    2. kleine Loecher mit dem Median der Nachbarschaft fuellen
    3. kantenerhaltend glaetten (bilateral: Nachbarn mit anderer Hoehe zaehlen kaum, First, Traufe und Kuppelrand bleiben scharf)"""
    Z = dom_glaetten(Z, zg)
    Zroh = Z.copy()                                      # nach dem ersten Ausreisserschritt: Turmspitzen und Kuppelscheitel kommen daraus zurueck
    Z = dom_glaetten(Z, zg, schwelle=0.9)
    W = _fenster25(Z)
    with np.errstate(all="ignore"):
        med5 = np.nanmedian(W, axis=0)
        aehnl5 = np.nansum(np.abs(W - Z[None]) <= 0.6, axis=0) - 1
    aus = ~np.isnan(Z) & ~np.isnan(med5) & (np.abs(Z - med5) > 1.0) & (aehnl5 < 4)
    Z = np.where(aus, med5, Z)
    for _ in range(4):                                   # Loecher: nur wo mindestens 4 von 8 Nachbarn Werte haben
        W = _fenster9(Z)
        with np.errstate(all="ignore"):
            med = np.nanmedian(W, axis=0)
            n = np.sum(~np.isnan(W), axis=0)
        fuell = np.isnan(Z) & (n >= 4)
        if not fuell.any():
            break
        Z = np.where(fuell, med, Z)
    gew_ort = np.array([0.6, 0.8, 0.6, 0.8, 1.0, 0.8, 0.6, 0.8, 0.6]).reshape(9, 1, 1)
    for _ in range(durchgaenge):
        W = _fenster9(Z)
        dz = W - Z[None]
        w = gew_ort * np.exp(-0.5 * (dz / sigma_h) ** 2)
        w = np.where(np.isnan(W), 0.0, w)
        with np.errstate(all="ignore"):
            neu = np.nansum(np.where(np.isnan(W), 0.0, W) * w, axis=0) / np.sum(w, axis=0)
        Z = np.where(np.isnan(Z), Z, neu)
    # Spitzen und Scheitel (oberstes Zehntel der Gebaeudehoehe) nicht abrunden: Turmhelme sind steil und nur eine Zelle breit
    if np.isfinite(Zroh).any():
        zm_ = float(np.nanmax(Zroh))
        top = np.isfinite(Zroh) & (Zroh >= zm_ - max(2.0, 0.12 * (zm_ - zg)))
        Z = np.where(top & (np.isnan(Z) | (Zroh > Z)), Zroh, Z)
    return Z


def ring_glaetten(zr, fenster=5):
    """Hoehen entlang eines geschlossenen Rings mit gleitendem Median glaetten (Traufkante ohne Zacken)"""
    n = len(zr)
    if n < fenster + 2:
        return zr
    h = fenster // 2
    return np.array([np.median(zr[[(i + k) % n for k in range(-h, h + 1)]]) for i in range(n)])


def dom_detail(g, dom, log, K, tol=None, stufe=None):
    """Form des markanten Gebaeudes aus dem DOM -> (faces, zmax, text) / ("abgelehnt", Grund) / None.
    Die Dachhaut wird je nach Stufe (fein/normal/stark) geglaettet. Scheitert das Netz mit der gewaehlten Stufe (Randanbindung), folgt der Versuch mit
    der naechst feineren Stufe; so wird ein Gebaeude lieber etwas rauer als gar nicht aus dem DOM gebaut."""
    stufe = stufe if stufe in STUFEN else STUFE
    kette = {"stark": ["stark", "normal", "fein"], "normal": ["normal", "fein"], "fein": ["fein"]}[stufe]
    r = None
    for st in kette:
        r = _dom_detail_stufe(g, dom, log, K, tol, st)
        if r and r[0] not in ("abgelehnt", "leer"):
            return (r[0], r[1], r[2] + (" - Glaettung %s statt %s" % (st, stufe) if st != stufe else ""))
        if r and r[0] == "leer":
            return r
    return r


def _dom_detail_stufe(g, dom, log, K, tol=None, stufe="normal"):
    """ein Durchlauf mit fester Glaettungsstufe; bei Problemen am Rand folgen zwei Versuche mit leicht vereinfachtem Grundriss (0,2 m, dann 0,5 m)"""
    r = _dom_detail(g, dom, log, K, tol, stufe)
    if not (r and r[0] == "abgelehnt" and ("Rand" in r[1] or "nicht geschlossen" in r[1])):
        return r
    fp0 = g["fp"]
    for tol_s in (0.2, 0.5):
        try:
            fp2 = fp0.buffer(0.3 * tol_s / 0.2, join_style=2, mitre_limit=2.0).buffer(-0.3 * tol_s / 0.2, join_style=2, mitre_limit=2.0).simplify(tol_s)
            if fp2.geom_type != "Polygon" or fp2.is_empty or not fp2.is_valid or abs(fp2.area - fp0.area) > 0.08 * fp0.area:
                continue
        except Exception:
            continue
        r2 = _dom_detail(dict(g, fp=fp2), dom, log, K, tol, stufe)
        if r2 and r2[0] != "abgelehnt" and r2[0] != "leer":
            return r2[0], r2[1], r2[2] + " (Grundriss um %.1f m vereinfacht)" % tol_s
    return r


def _dom_detail(g, dom, log, K, tol=None, stufe="normal"):
    """Form des markanten Gebaeudes aus dem DOM -> (faces, zmax, text) / ("abgelehnt", Grund) / None"""
    sig_h, n_durch, tol_s = STUFEN.get(stufe, STUFEN["normal"])
    tol = tol_s if tol is None else tol
    fp = g["fp"]
    pg = fp.buffer(0.6, join_style=2, mitre_limit=2.0).simplify(0.04)       # spitze Ecken (keine Rundungen: winzige Bogenstuecke ergaeben Sliver-Dreiecke)
    if pg.is_empty or not pg.is_valid:
        pg = fp.buffer(0.6, join_style=2, mitre_limit=2.0).buffer(0)
    x0, y0, x1, y1 = pg.bounds
    pts = dom.ausschnitt(x0 - 2, y0 - 2, x1 + 2, y1 + 2)
    if len(pts) < 20:
        return ("leer", "nur %d DOM-Punkte am Gebaeude - die geladenen Kacheln decken es nicht ab" % len(pts))
    s, xo, yo = K.raster_schritt(pts)
    ix = np.rint((pts[:, 0] - xo) / s).astype(np.int64)
    iy = np.rint((pts[:, 1] - yo) / s).astype(np.int64)
    if s < 0.75:                                          # feines DOM (0,25/0,5 m) auf ca. 1 m ausduennen: genug fuer Morphs, und die Ringpunkte bleiben frei
        k = int(round(1.0 / s))
        m_ = (ix % k == 0) & (iy % k == 0)
        pts, ix, iy = pts[m_], ix[m_] // k, iy[m_] // k
        s, xo, yo = s * k, xo, yo
        if len(pts) < 20:
            return ("leer", "nur %d DOM-Punkte am Gebaeude" % len(pts))
    nx, ny = int(ix.max()) + 1, int(iy.max()) + 1
    if nx * ny > 4e6:
        return ("abgelehnt", "DOM-Ausschnitt zu gross")
    Z = np.full((ny, nx), np.nan)
    Z[iy, ix] = pts[:, 2]
    if GLAETTEN:
        Z = dom_bereinigen(Z, g["zg"], sig_h, n_durch)
    Xc = xo + np.arange(nx)[None, :] * s
    Yc = yo + np.arange(ny)[:, None] * s
    XX, YY = np.broadcast_arrays(Xc, Yc)
    # nur Zellen, die wirklich im Grundriss liegen (nicht im Randpuffer: dort steht Boden/Nachbarschaft und ergaebe einen Absatz am Rand)
    innen = shapely.contains_xy(fp.buffer(-0.05), XX.ravel(), YY.ravel()).reshape(Z.shape) & ~np.isnan(Z)
    erwartet = max(fp.area / (s * s), 1.0)
    if innen.sum() < 0.6 * erwartet:
        return ("abgelehnt", "DOM deckt nur %.0f %% des Grundrisses" % (100.0 * innen.sum() / erwartet))
    zmax = float(Z[innen].max())
    if abs(zmax - g["zmax"]) > max(5.0, 0.25 * g["H"]):
        return ("abgelehnt", "DOM-Hoehe %.0f m passt nicht zum LoD2 (%.0f m) - anderer Stand?" % (zmax - g["zg"], g["H"]))
    Zv = np.where(innen, Z, np.nan)
    gy, gx = np.nonzero(~np.isnan(Zv))
    gz = Zv[gy, gx]
    wahl = np.zeros(Z.shape, dtype=bool)
    st = max(1, int(round(6 / s)))
    wahl[::st, ::st] = True
    # Rand der gueltigen Zellen immer waehlen
    m = ~np.isnan(Zv)
    rand = m & ~(np.roll(m, 1, 0) & np.roll(m, -1, 0) & np.roll(m, 1, 1) & np.roll(m, -1, 1))
    wahl |= rand
    wahl &= m
    # Gipfel immer behalten (Spitzen, Kuppelscheitel): hoechste Zelle und lokale Hoehepunkte ueber 85 % der Gebaeudehoehe
    gip = m & (Zv == maximum_filter(np.where(m, Zv, -1e9), size=5)) & (Zv >= zmax - 0.15 * max(zmax - g["zg"], 1.0))
    wahl |= gip
    wahl[np.unravel_index(np.nanargmax(np.where(m, Zv, np.nan)), Z.shape)] = True
    for it in range(1, 30):
        wy, wx = np.nonzero(wahl)
        if len(wx) < 4:
            break
        try:
            f = LinearNDInterpolator(np.column_stack([wx, wy]), Zv[wy, wx])
        except Exception:
            break
        fehler = np.zeros(Z.shape)
        fehler[gy, gx] = np.abs(np.nan_to_num(f(gx, gy) - gz, nan=0.0))
        fehler[wahl] = 0.0
        kand = (fehler > tol) & (fehler == maximum_filter(fehler, size=5 if it <= 6 else 3))
        if not kand.any():
            break
        wahl |= kand
    wy, wx = np.nonzero(wahl)
    P = np.column_stack([xo + wx * s, yo + wy * s])
    zP = Zv[wy, wx]
    from shapely.geometry.polygon import orient
    zg = g["zg"]
    kd = cKDTree(np.column_stack([xo + gx * s, yo + gy * s]))
    # Ring um das Gebaeude (Puffer 0,6 m = Dachueberstand) mit Punkten alle 0,8 m. Die Rasterpunkte liegen mindestens 0,5 m innerhalb
    # (Zellen nur im Grundriss), der Kreis ueber jedem Ringsegment (Radius 0,4 m) bleibt also leer: jede Ringkante ist eine Dreieckskante.
    ringe = []
    for p in _polys(pg):
        p = orient(p, 1.0)
        for ring in [p.exterior] + list(p.interiors):
            rp = _rand_dicht(list(ring.coords), 0.8)     # NICHT runden: schon 1 Mikrometer Abweichung macht gerade Randstuecke fuer Qhull zu Nadeldreiecken
            _, idx = kd.query(rp)
            zr0 = np.maximum(gz[idx], zg + 0.5)
            ringe.append([rp, ring_glaetten(zr0) if GLAETTEN else zr0])
    simp = None
    for versuch in range(12):
        PA = np.vstack([r[0] for r in ringe] + [P])          # Ringpunkte zuerst: bei gleicher Lage gewinnt ihre Hoehe (Dach = Wandoberkante)
        ZA = np.concatenate([r[1] for r in ringe] + [zP])
        PA, ui = np.unique(PA, axis=0, return_index=True)
        ZA = ZA[ui]
        try:
            # Innen/Aussen gegen den Umriss aus den (gerundeten) Ringpunkten selbst, nicht gegen den ungerundeten Puffer: sonst gelten
            # Nadeldreiecke auf geraden Randstuecken je nach Rundung mal als innen, mal als aussen -> doppelte Kanten
            pgr, i1 = [], 0
            for p_ in _polys(pg):
                k_n = 1 + len(p_.interiors)
                rr_ = [r_[0] for r_ in ringe[i1:i1 + k_n]]
                i1 += k_n
                pgr.append(Polygon(rr_[0], rr_[1:]))
            pgr = unary_union(pgr)
            simp = _delaunay_innen(PA, pgr if (pgr.is_valid and abs(pgr.area - pg.area) < 0.05 * pg.area) else pg, 3 * max(s, 1.0),
                                   tol=0.0 if (pgr.is_valid and abs(pgr.area - pg.area) < 0.05 * pg.area) else 1e-5)
        except Exception as e:
            return ("abgelehnt", "Dreiecksvermaschung des DOM fehlgeschlagen (%s)" % str(e)[:60])
        kanten = set()
        for t_ in simp:
            for k_ in range(3):
                a_, b_ = int(t_[k_]), int(t_[(k_ + 1) % 3])
                kanten.add((a_, b_) if a_ < b_ else (b_, a_))
        index = {(float(q[0]), float(q[1])): n_ for n_, q in enumerate(PA)}
        fehlend = []
        for ri, (rp, zr) in enumerate(ringe):
            n = len(rp)
            for k_ in range(n):
                a_, b_ = index.get((float(rp[k_][0]), float(rp[k_][1]))), index.get((float(rp[(k_ + 1) % n][0]), float(rp[(k_ + 1) % n][1])))
                if a_ is None or b_ is None or ((a_, b_) if a_ < b_ else (b_, a_)) not in kanten:
                    fehlend.append((ri, k_))
        if not fehlend:
            break
        lang = [(ri, k_) for ri, k_ in fehlend if np.hypot(*(ringe[ri][0][(k_ + 1) % len(ringe[ri][0])] - ringe[ri][0][k_])) > 0.25]
        if not lang:                                                           # nur winzige Segmente fehlen: Halbieren hilft nicht mehr
            # Mikro-Kanten (Versaetze, fast gerade Knicke im Grundriss): den hinteren Eckpunkt der fehlenden Kante weglassen (hoechstens
            # ~0,25 m Abweichung am Rand), Dach, Waende und Boden entstehen danach wieder aus denselben Ringpunkten
            weg = {}
            for ri, k_ in fehlend:
                weg.setdefault(ri, set()).add((k_ + 1) % len(ringe[ri][0]))
            for ri, ks in weg.items():
                rp, zr = ringe[ri]
                keep = [i for i in range(len(rp)) if i not in ks]
                if len(keep) < 4:
                    return ("abgelehnt", "DOM-Netz schliesst nicht an den Gebaeuderand an (%d winzige Randkanten fehlen)" % len(fehlend))
                ringe[ri][0], ringe[ri][1] = rp[keep], zr[keep]
            continue
        for ri, k_ in sorted(lang, key=lambda t: (t[0], -t[1])):           # Ringkante halbieren (von hinten, damit die Nummern stimmen)
            rp, zr = ringe[ri]
            n = len(rp)
            m_ = (rp[k_] + rp[(k_ + 1) % n]) / 2
            ringe[ri][0] = np.insert(rp, k_ + 1, m_, axis=0)
            ringe[ri][1] = np.insert(zr, k_ + 1, (zr[k_] + zr[(k_ + 1) % n]) / 2)
    else:
        return ("abgelehnt", "DOM-Netz schliesst nicht an den Gebaeuderand an (%d Randkanten fehlen)" % len(fehlend))
    faces = []
    for sx in simp:
        q = np.column_stack([PA[sx], ZA[sx]])
        nz = np.cross(q[1] - q[0], q[2] - q[0])[2]
        if abs(nz) < 1e-9:
            continue
        faces.append(q if nz > 0 else q[::-1])
    for rp, zr in ringe:                                  # Waende vom LoD2-Boden bis zur Dachkante des DOM (gleiche Punkte wie das Dach)
        n = len(rp)
        for i in range(n):
            a_, b_ = rp[i], rp[(i + 1) % n]
            faces.append(np.array([[a_[0], a_[1], zg], [b_[0], b_[1], zg], [b_[0], b_[1], zr[(i + 1) % n]], [a_[0], a_[1], zr[i]]]))
    boden = []
    i0 = 0
    for p in _polys(pg):
        k = 1 + len(p.interiors)
        rr = [r[0] for r in ringe[i0:i0 + k]]
        i0 += k
        try:
            dp = Polygon(rr[0], rr[1:])
            boden.append(dp if dp.is_valid and abs(dp.area - p.area) < 0.02 * p.area else p)
        except Exception:
            boden.append(p)
    for b_ in boden:
        faces += _platte(b_, zg, False)
    offen = offene_kanten(faces)
    if offen:
        return ("abgelehnt", "DOM-Koerper nicht geschlossen (%d offene Kanten) - ArchiCAD wuerde ihn nicht als Koerper lesen" % offen)
    return faces, zmax, "DOM %g m, %d Punkte (von %d Zellen), geschlossen" % (s, len(P), len(gz))


def offene_kanten(faces, nd=3):
    """Anzahl Kanten einer Flaechenliste, zu denen die gegenlaeufige Kante fehlt (0 = geschlossener Koerper, Flaechen einheitlich orientiert)."""
    kt = {}
    for f in faces:
        f = np.asarray(f)
        n = len(f)
        for i in range(n):
            a = tuple(np.round(f[i], nd))
            b = tuple(np.round(f[(i + 1) % n], nd))
            if a != b:
                kt[(a, b)] = kt.get((a, b), 0) + 1
    return sum(1 for (a, b), c in kt.items() if kt.get((b, a), 0) != c)


# ----------------------------------------------------------------------------------------------
# Gesamtablauf
# ----------------------------------------------------------------------------------------------

def lod2_voll(g):
    import ifcmap_kern as K
    faces = []
    for t in g["teile"]:
        if t.get("kompakt") or not (t["wall"] or t["roof"]):
            if t["ground"]:
                faces += K.block_faces(t)[0]
        else:
            faces += K.lod2_faces(t)
    return faces


def behalte_parameter(cfg, log=None):
    """Fuer lod2_lesen: Welche Gebaeude des FERNbereichs nicht zu Bloecken verdichtet werden (nur mit cfg.markant_fern):
    dict(punkte=[(x, y)], dach=True/False). Im Nahbereich wird nie verdichtet, dort ist nichts vorzubereiten. -> dict oder None"""
    if not (getattr(cfg, "markant", False) and getattr(cfg, "markant_fern", False)):
        return None
    try:
        pkt = [(x, y) for n_, x, y in parse_liste(cfg.markant_liste, cfg.epsg)]
    except Exception as e:
        if log:
            log("  HINWEIS: eigene Liste markanter Gebaeude nicht lesbar (%s)" % e)
        pkt = []
    return dict(punkte=pkt, dach=bool(getattr(cfg, "markant_dach", True)), flaechen=None)


def flaechen_aus(geoms, namen=None):
    geoms = [g for g in geoms if g is not None and not g.is_empty]
    if not geoms:
        return None
    return dict(geoms=geoms, tree=shapely.STRtree(geoms), namen=list(namen) if namen else [""] * len(geoms))


def verbessern(d, cfg, log, prog=None):
    """Markante Gebaeude bestimmen und mit der besten Quelle ausarbeiten.
    Setzt d.markant (Liste dicts: name, gid, quelle, grund, faces, H, text) und d.markant_ids.
    Benutzt d.osm_geb (OSM-Gebaeude, falls geladen) und d.denkmal (Flaechen der Denkmalkarte, falls geladen)."""
    import ifcmap_kern as K
    d.markant, d.markant_ids = [], set()
    if not getattr(cfg, "markant", False) or not d.teile:
        return
    log("Markante Gebaeude (%s):" % ("Nah- und Fernbereich" if getattr(cfg, "markant_fern", False) else "nur Nahbereich"))
    t0 = time.time()
    osm = getattr(d, "osm_geb", None) if cfg.markant_osm else None
    if cfg.markant_osm and osm is None:
        log("  OpenStreetMap-Gebaeude nicht verfuegbar - OSM-Merkmale und OSM-3D entfallen")
    t1 = time.time()
    ziele = bestimmen(d, cfg, log, osm, getattr(d, "denkmal", None))
    log("  Auswahl dauerte %.1f s" % (time.time() - t1))
    if not ziele:
        log("  keine markanten Gebaeude gefunden (eigene Liste leer, keine OSM-Merkmale, kein Denkmal, kein komplexes Dach)")
        return
    for g in ziele:
        log("   - %s: %s" % (g["name"], g["grund"]))
    quelle_wahl = getattr(cfg, "markant_quelle", "auto") or "auto"
    if quelle_wahl not in ("auto", "dom_zuerst", "dom", "osm", "lod2"):
        quelle_wahl = "auto"
    if quelle_wahl == "auto":
        log("  Quelle der Form: OpenStreetMap -> LoD2 (das DOM ist nur noch auf Wunsch dabei: 'DOM zuerst')")
    elif quelle_wahl != "dom_zuerst":
        log("  Quelle der Form: %s" % {"dom": "NUR DOM (Test)", "osm": "NUR OpenStreetMap (Test)", "lod2": "NUR LoD2 (Test)"}[quelle_wahl])
    dom, dom_grund = None, ""
    if quelle_wahl == "auto":
        dom_grund = "nicht im Standard (Lueftungsanlagen und Daecher mit zu vielen Versprungen werden falsch gelesen) - Einstellung 'DOM zuerst'"
    elif quelle_wahl in ("osm", "lod2"):
        dom_grund = "Quelle der Form ist auf '%s' gestellt" % ("nur OpenStreetMap" if quelle_wahl == "osm" else "nur LoD2")
    elif not cfg.markant_dom:
        dom_grund = "abgeschaltet (Haken 'aus dem Oberflaechenmodell')"
    else:
        t1 = time.time()
        try:
            dateien, dom_grund = dom_dateien(cfg, d, ziele, log, K)
            if dateien:
                bb = unary_union([g["fp"].buffer(4) for g in ziele]).bounds
                dom = DomPunkte(dateien, bb, K, log)
                if not len(dom.pts):
                    dom = None
                    dom_grund = "%d Datei(en) gelesen, aber keine Punkte im Bereich der markanten Gebaeude" % len(dateien)
        except Exception as e:
            dom_grund = "Fehler beim Laden/Lesen: %s" % str(e)[:150]
            log("  DOM nicht verfuegbar: %s" % e)
        log("  DOM: %s (%.0f s)" % ("%d Punkte" % len(dom.pts) if dom else "keine Daten - %s - Form kommt aus OpenStreetMap bzw. LoD2" % dom_grund, time.time() - t1))
    osm_form = osm
    osm_grund = ""
    if quelle_wahl in ("dom", "lod2"):
        osm_form = None
        osm_grund = "Quelle der Form ist auf '%s' gestellt" % ("nur DOM" if quelle_wahl == "dom" else "nur LoD2")
    elif not cfg.markant_osm:
        osm_grund = "abgeschaltet (Haken 'OpenStreetMap-Merkmal')"
    elif osm is None:
        osm_grund = "OpenStreetMap-Gebaeude nicht geladen (Overpass nicht erreichbar oder keine Gebaeude - siehe Zeilen weiter oben)"
    n_q = {"DOM": 0, "OSM": 0, "LoD2": 0}
    zeilen = []
    for i, g in enumerate(ziele):
        if prog:
            prog(0.93 + 0.05 * i / len(ziele), "Markantes Gebaeude %d/%d ..." % (i + 1, len(ziele)))
        faces, quelle, text, hinweis = None, "LoD2", "", []
        dom_s = "nicht versucht: " + dom_grund if dom is None else ""
        osm_s = "nicht versucht: " + osm_grund if osm_form is None else ""
        if dom is not None:
            try:
                r = dom_detail(g, dom, log, K, stufe=getattr(cfg, "markant_glaettung", None))
            except Exception as e:
                r = ("abgelehnt", "Fehler: %s" % str(e)[:100])
            if r and r[0] in ("abgelehnt", "leer"):
                hinweis.append("DOM: " + r[1])
                dom_s = ("abgelehnt: " if r[0] == "abgelehnt" else "keine Daten: ") + r[1]
            elif r:
                faces, zmax, text = r
                quelle = "DOM"
                dom_s = "genutzt: " + text
        if faces is None and osm_form is not None:
            try:
                r = osm_detail(g, osm_form, log)
            except Exception as e:
                r = ("abgelehnt", "Fehler: %s" % str(e)[:100])
            if r and r[0] in ("abgelehnt", "leer"):
                hinweis.append("OSM: " + r[1])
                osm_s = ("abgelehnt: " if r[0] == "abgelehnt" else "keine Daten: ") + r[1]
            elif r:
                faces, zmax, text = r
                quelle = "OSM"
                osm_s = "genutzt: " + text
        elif faces is not None and osm_form is not None:
            osm_s = "nicht noetig (DOM genutzt)"
        if faces is None:
            faces = lod2_voll(g)
            text = "volles LoD2" if not any(t.get("kompakt") for t in g["teile"]) else "LoD2 nur als Block (Fernbereich)"
        n_q[quelle if quelle in n_q else "LoD2"] += 1
        log("  %s (%.0f m, %s): %s - %s%s" % (g["name"], g["H"], g["grund"], quelle, text, ("  [" + "; ".join(hinweis) + "]") if hinweis else ""))
        zeilen.append((g["name"], g["H"], g["grund"], dom_s, osm_s, quelle))
        d.markant.append(dict(name=g["name"], gid=g["gid"], quelle=quelle, grund=g["grund"], faces=faces, H=g["H"], text=text,
                              c=(g["c"].x, g["c"].y)))
        d.markant_ids.add(g["gid"])
    log("  Quellen: DOM %d, OpenStreetMap %d, LoD2 %d (%.0f s)" % (n_q["DOM"], n_q["OSM"], n_q["LoD2"], time.time() - t0))
    for z in auswertung(zeilen, dom, dom_grund, osm_form, osm_grund, n_q):
        log(z)


def auswertung(zeilen, dom, dom_grund, osm, osm_grund, n_q):
    """Klartext-Auswertung: woran scheitern DOM und OpenStreetMap? zeilen = [(Name, Hoehe, Auswahlgrund, DOM-Status, OSM-Status, Quelle)]"""
    n = len(zeilen)
    out = ["  --- Auswertung markante Gebaeude: warum kommt die Form woher? ---"]
    out.append("  DOM:   %s" % (("%d Punkte geladen, genutzt bei %d von %d Gebaeuden" % (len(dom.pts), n_q["DOM"], n)) if dom else "KEINE Daten - " + dom_grund))
    out.append("  OSM:   %s" % (("Gebaeude geladen (%d Objekte), genutzt bei %d von %d Gebaeuden" % (len(osm["objekte"]), n_q["OSM"], n)) if osm else "KEINE Daten - " + osm_grund))
    for name, h, grund, dom_s, osm_s, quelle in zeilen:
        out.append("   %s (%.0f m) -> %s" % (name, h, quelle))
        out.append("       Auswahl: %s" % grund)
        out.append("       DOM:     %s" % dom_s)
        out.append("       OSM:     %s" % osm_s)
    if n_q["LoD2"] == n and n:
        urs = []
        if not dom:
            urs.append("DOM fehlt (%s)" % dom_grund)
        if not osm:
            urs.append("OSM fehlt (%s)" % osm_grund)
        if dom or osm:
            urs.append("die vorhandenen Quellen wurden je Gebaeude abgelehnt (Gruende oben)")
        out.append("  FAZIT: %s bleibt beim normalen LoD2 - %s." % ("Das Gebaeude" if n == 1 else "Alle %d Gebaeude" % n, "; ".join(urs)))
    elif n:
        out.append("  FAZIT: %d von %d Gebaeuden haben eine eigene Form (DOM %d, OpenStreetMap %d), %d bleiben LoD2." % (n - n_q["LoD2"], n, n_q["DOM"], n_q["OSM"], n_q["LoD2"]))
    return out
