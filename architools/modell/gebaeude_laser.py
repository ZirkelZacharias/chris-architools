"""Gebäude als Laserteile: Stapelmodell, ebene Flächen zum Kleben (ohne Laschen) und Faltmodell (mit Laschen).

Eingang ist je Gebäude das Ergebnis von buildings.build_buildings (Modell-mm):
    footprint  Grundriss (Polygon)           height_mm  Höhe über der Unterkante
    prismen    [(Dachgrundriss, (a, b, c))]  Dachebene z = a x + b y + c, z in mm über der Unterkante  (nur LoD2 im Nahbereich)
    dach3d     [(xyz-Ring, [Innenringe])]    Dachflächen als 3D-Ringe in Modell-mm
Ohne Dachdaten (Blöcke) ist das Dach flach in height_mm.

Ein Laserteil ist wie überall ein dict (id, poly, ritzen, gravieren); dazu "gebaeude" (Nummer) und "art".
Alle Wand- und Dachflächen sind in wahrer Größe (abgewickelt), nicht in der Draufsicht.
"""
import math

import numpy as np
import shapely
import shapely.affinity
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient

from .geomutil import polys

MIN_TEIL_MM = 1.0           # kleinere Teile werden weggelassen


# ------------------------------------------------------------------ Stapelmodell
def _halbebene(a, b, c, z, gross=1e5):
    """Gebiet, in dem die Dachebene z = a x + b y + c mindestens z erreicht"""
    n = math.hypot(a, b)
    if n < 1e-9:
        return Polygon([(-gross, -gross), (gross, -gross), (gross, gross), (-gross, gross)]) if c >= z else Polygon()
    nx, ny = a / n, b / n
    p0 = np.array([nx, ny]) * (z - c) / n
    d = np.array([-ny, nx])
    nv = np.array([nx, ny])
    return Polygon([p0 - d * gross, p0 + d * gross, p0 + d * gross + nv * gross, p0 - d * gross + nv * gross])


def schicht_polygone(b, t):
    """[(k, Polygon)] des Gebäudes in Schichten der Dicke t (k = 0 unten)"""
    h = float(b["height_mm"])
    n = max(1, int(math.ceil((h - 0.02) / t)))
    fp = b["footprint"]
    out = []
    for k in range(n):
        z = (k + 0.5) * t if k < n - 1 else min(h - 0.05, (k + 0.5) * t)
        if b.get("prismen"):
            teile = []
            for poly, (pa, pb, pc) in b["prismen"]:
                q = poly.intersection(_halbebene(pa, pb, pc, z))
                if not q.is_empty:
                    teile.append(q)
            g = shapely.union_all(teile).intersection(fp.buffer(0.02)) if teile else Polygon()
        else:
            g = fp
        pg = [q for q in polys(g) if q.area >= MIN_TEIL_MM]
        if pg:
            out.append((k, shapely.union_all(pg)))
    return out


def stapel_teile(b, t, beschriften=True):
    teile = []
    for k, g in schicht_polygone(b, t):
        for i, q in enumerate(polys(g), 1):
            teile.append(_teil(f"{b['nr']}-S{k + 1:02d}" + (f"_{i}" if len(polys(g)) > 1 else ""), q, b, "Stapel"))
    if beschriften:
        for tl in teile:
            _beschriften(tl)
    return teile


# ------------------------------------------------------------------ Wände
def _ring_kanten(fp):
    """Ringe des Grundrisses als Punktfolgen, so orientiert, dass das Innere links der Laufrichtung liegt"""
    out = []
    for q in polys(orient(fp, 1.0)):
        out.append(list(q.exterior.coords)[:-1])
        for i in q.interiors:
            out.append(list(i.coords)[:-1])
    return out


def _hoehe_an(b, x, y):
    """Dachhöhe an einem Punkt (leicht im Gebäude)"""
    if not b.get("prismen"):
        return float(b["height_mm"])
    best = None
    pt = Point(x, y)
    for poly, (a, bb, c) in b["prismen"]:
        if poly.contains(pt) or poly.distance(pt) < 0.08:
            v = a * x + bb * y + c
            best = v if best is None else max(best, v)
    if best is None:
        return float(b["height_mm"])
    return max(0.3, float(best))


def wand_profil(b, p, q, schritt=None):
    """Wand über der Kante p->q: Liste (s, z) der Oberkante von s = 0 (bei p) bis L"""
    p, q = np.asarray(p, float), np.asarray(q, float)
    L = float(np.hypot(*(q - p)))
    if L < 1e-6:
        return None, 0.0
    d = (q - p) / L
    nl = np.array([-d[1], d[0]])               # Innenseite (links)
    if not b.get("prismen"):
        return [(0.0, float(b["height_mm"])), (L, float(b["height_mm"]))], L
    n = max(2, int(math.ceil(L / (schritt or max(0.6, L / 80.0)))) + 1)
    pts = []
    for s in np.linspace(0, L, n):
        m = p + d * s + nl * 0.1
        pts.append((float(s), _hoehe_an(b, m[0], m[1])))
    ls = LineString(pts).simplify(0.12)
    return [tuple(c) for c in ls.coords], L


def wand_polygon(profil, L):
    pts = [(0.0, 0.0), (L, 0.0)] + [(s, z) for s, z in reversed(profil)]
    pg = Polygon(pts)
    if not pg.is_valid:
        pg = pg.buffer(0)
    return pg


def waende(b):
    """[(ring_index, kante_index, profil, L)] aller Wände"""
    out = []
    for ri, ring in enumerate(_ring_kanten(b["footprint"])):
        n = len(ring)
        for i in range(n):
            prof, L = wand_profil(b, ring[i], ring[(i + 1) % n])
            if prof is None or L < 0.4:
                continue
            out.append((ri, i, prof, L))
    return out


# ------------------------------------------------------------------ Dächer
def _flach_2d(xyz):
    """Dachring (3D) in die eigene Ebene legen (wahre Grösse). -> Nx2"""
    c = xyz.mean(axis=0)
    n = np.zeros(3)
    for i in range(len(xyz)):
        n += np.cross(xyz[i], xyz[(i + 1) % len(xyz)])
    ln = np.linalg.norm(n)
    if ln < 1e-9:
        return xyz[:, :2]
    n /= ln
    if abs(n[2]) > 0.9999:
        return xyz[:, :2] if n[2] > 0 else xyz[:, :2] * [1, 1]
    u = np.cross([0, 0, 1.0], n)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    return np.c_[(xyz - c) @ u, (xyz - c) @ v]


def dach_flaechen(b):
    """[(Polygon in wahrer Grösse, xyz-Ring)] aller Dachflächen; Blöcke: ein flaches Dach über dem Grundriss"""
    out = []
    if b.get("dach3d"):
        for xyz, ints in b["dach3d"]:
            xyz = np.asarray(xyz, float)
            if len(xyz) > 1 and np.allclose(xyz[0], xyz[-1]):
                xyz = xyz[:-1]
            if len(xyz) < 3:
                continue
            p2 = _flach_2d(xyz)
            pg = Polygon(p2)
            if not pg.is_valid:
                pg = pg.buffer(0)
            pg = shapely.union_all(polys(pg)) if not pg.is_empty else pg
            if pg.is_empty or pg.area < MIN_TEIL_MM:
                continue
            out.append((pg, xyz))
    else:
        fp = b["footprint"]
        h = float(b["height_mm"])
        for q in polys(fp):
            xyz = np.c_[np.asarray(q.exterior.coords)[:-1], np.full(len(q.exterior.coords) - 1, h)]
            out.append((q, xyz))
    return out


# ------------------------------------------------------------------ Teile
# ------------------------------------------------------------------ Fenstermuster (Rastergravur-Variante: gravierte Rechtecke)
GESCHOSS_M, ACHSE_M = 3.1, 3.0
FENSTER_B, FENSTER_H, BRUESTUNG = 1.2, 1.4, 0.9
TUER_B, TUER_H = 1.0, 2.1
MIN_FENSTER_MM = 0.8


def fenster_muster(profil, L, massstab, x0=0.0):
    """Gravur-Rechtecke (Polygone in mm, um x0 verschoben) als MUSTER auf einer Wand mit Oberkantenprofil `profil`.
    KEINE Messung: nach Wandbreite und -hoehe (Achse 3 m, Fenster 1,2 x 1,4 m, Bruestung 0,9 m, Tuer im Erdgeschoss)."""
    k = 1000.0 / float(massstab)                                  # mm je m im Modell
    wand = wand_polygon(profil, L)
    if wand.is_empty:
        return []
    smin, zmin, smax, zmax = wand.bounds
    Wm, Hm = (smax - smin) / k, (zmax - zmin) / k
    if Wm < 3.2 or Hm < 3.0:
        return []
    tops = []
    for x in np.linspace(smin + 0.2 * k, smax - 0.2 * k, 9):
        seg = wand.intersection(LineString([(x, zmin - 1), (x, zmax + 1)]))
        if not seg.is_empty:
            tops.append(seg.bounds[3])
    if not tops:
        return []
    top = float(np.quantile(tops, 0.25))
    nfl = max(1, int(round((top - zmin) / k / GESCHOSS_M)))
    fh = (top - zmin) / nfl
    nax = max(1, int(Wm // ACHSE_M))
    a = (smax - smin) / nax
    fb = min(FENSTER_B * k, 0.55 * a)
    tuer_ax = nax // 2 if Wm >= 6.0 else -1
    innen = wand.buffer(-0.15 * k)
    out = []
    for j in range(nfl):
        z0 = zmin + j * fh
        for i in range(nax):
            sm = smin + a * (i + 0.5)
            if j == 0 and i == tuer_ax:
                b = (sm - TUER_B * k / 2, z0 + 0.2 * k, sm + TUER_B * k / 2, z0 + (0.2 + TUER_H) * k)
            else:
                b = (sm - fb / 2, z0 + BRUESTUNG * k, sm + fb / 2, z0 + (BRUESTUNG + FENSTER_H) * k)
            if b[2] - b[0] < MIN_FENSTER_MM or b[3] - b[1] < MIN_FENSTER_MM:
                continue
            bx = shapely.box(*b)
            if innen.contains(bx):
                out.append(shapely.affinity.translate(bx, xoff=x0))
    return out


_CTX = {"cfg": None}


def zusatz_gravur(b, ri, i, prof, L, x0=0.0):
    """Gravurflächen optionaler Zusatzmodule für eine Wand (Wandkoordinaten s/z in mm, um x0 verschoben)"""
    if not _CTX.get("zusatz"):
        return []
    try:
        from .. import zusatz as ZU
        out = []
        for r in ZU.rufe("modell_wand", b, ri, i, prof, L, _CTX["cfg"]):
            for g in (r or []):
                out.append(shapely.affinity.translate(g, xoff=x0) if x0 else g)
        return out
    except Exception:
        return []


def _teil(tid, poly, b, art, ritzen=None):
    return {"id": tid, "poly": poly, "ritzen": list(ritzen or []), "gravieren": [], "gebaeude": b["nr"], "art": art}


def _beschriften(teil, hoehe=1.6):
    """ID klein auf das Teil gravieren, wenn es dort Platz hat"""
    from .laser import _text
    r, g = _text(teil["id"], teil["poly"].buffer(-0.5), hoehe, "gravieren")
    teil["ritzen"] += r
    teil["gravieren"] += g


def flaechen_teile(b, beschriften=True, massstab=None):
    """Ebene Wand- und Dachflächen, einzeln, ohne Laschen"""
    teile = []
    for j, (ri, i, prof, L) in enumerate(waende(b), 1):
        pg = wand_polygon(prof, L)
        if pg.is_empty or pg.area < MIN_TEIL_MM:
            continue
        t = _teil(f"{b['nr']}-W{j:02d}", shapely.union_all(polys(pg)), b, "Wand")
        if massstab:
            t["gravieren"] += fenster_muster(prof, L, massstab)
        t["gravieren"] += zusatz_gravur(b, ri, i, prof, L)
        teile.append(t)
    for j, (pg, xyz) in enumerate(dach_flaechen(b), 1):
        teile.append(_teil(f"{b['nr']}-D{j:02d}", pg, b, "Dach"))
    if beschriften:
        for t in teile:
            _beschriften(t)
    return teile


# ------------------------------------------------------------------ Faltmodell
def _lasche(a, bb, breite, innen_pg, fase=0.7):
    """Trapez-Lasche an der Kante a->bb auf der Aussenseite von innen_pg. -> Polygon"""
    a, bb = np.asarray(a, float), np.asarray(bb, float)
    L = float(np.hypot(*(bb - a)))
    if L < 1.0:
        return None
    d = (bb - a) / L
    n = np.array([d[1], -d[0]])
    mitte = (a + bb) / 2 + n * 0.05
    if innen_pg.contains(Point(*mitte)):
        n = -n
    w = min(breite, L * 0.6)
    c = min(w * fase, L / 3.0)
    pg = Polygon([a, a + n * w + d * c, bb + n * w - d * c, bb])
    if not pg.is_valid or pg.area < 0.3:
        return None
    return pg.difference(innen_pg.buffer(0.01))


def _kante_gleich(p, q, r, s, tol=0.35):
    return (np.hypot(*(p - r)) < tol and np.hypot(*(q - s)) < tol) or (np.hypot(*(p - s)) < tol and np.hypot(*(q - r)) < tol)


def falt_teile(b, breite, max_laenge, beschriften=True, massstab=None):
    """Wandstreifen (Ringe, bei Bedarf geteilt) mit Faltlinien und einer Lasche je Streifen + Dachflächen mit Laschen"""
    teile = []
    # --- Wände je Ring als Streifen
    ringe = {}
    for ri, i, prof, L in waende(b):
        ringe.setdefault(ri, []).append((prof, L, i))
    nr = 0
    for ri, ws in ringe.items():
        # in Streifen höchstens max_laenge lang teilen
        gruppen, akt, lng = [], [], 0.0
        for prof, L, i_ in ws:
            if akt and lng + L > max_laenge:
                gruppen.append(akt)
                akt, lng = [], 0.0
            akt.append((prof, L, i_))
            lng += L
        if akt:
            gruppen.append(akt)
        for gr in gruppen:
            nr += 1
            x = 0.0
            oben, falten, fenster = [], [], []
            for prof, L, i_ in gr:
                if massstab:
                    fenster += fenster_muster(prof, L, massstab, x)
                fenster += zusatz_gravur(b, ri, i_, prof, L, x)
                for s, z in prof:
                    oben.append((x + s, z))
                falten.append(x)
                x += L
            falten.append(x)
            pts = [(0.0, 0.0), (x, 0.0)] + [p for p in reversed(oben)]
            pg = Polygon(pts)
            if not pg.is_valid:
                pg = pg.buffer(0)
            pg = shapely.union_all(polys(pg))
            ritz = []
            for fx in falten[1:-1]:
                zt = max(z for s, z in oben if abs(s - fx) < 1e-6) if any(abs(s - fx) < 1e-6 for s, z in oben) else 0
                if zt > 0:
                    ritz.append(LineString([(fx, 0.0), (fx, zt)]))
            # Lasche am rechten Ende (klebt innen an den Anfang des nächsten Streifens)
            z_end = oben[0][1]
            lash = _lasche((x, 0.0), (x, z_end), breite, pg)
            if lash is not None and not lash.is_empty:
                pg = shapely.union_all(polys(pg.union(lash)))
                ritz.append(LineString([(x, 0.0), (x, z_end)]))
            t = _teil(f"{b['nr']}-F{nr:02d}", pg, b, "Wandstreifen", ritz)
            t["gravieren"] += fenster
            teile.append(t)
    # --- Dächer mit Laschen
    daecher = dach_flaechen(b)
    kanten = []                                  # je Dach: Liste (p3, q3) der 3D-Kanten
    for pg, xyz in daecher:
        kanten.append([(xyz[i], xyz[(i + 1) % len(xyz)]) for i in range(len(xyz))])
    for j, (pg, xyz) in enumerate(daecher):
        ring2 = list(orient(Polygon(pg.exterior), 1.0).exterior.coords)[:-1]
        # Zuordnung 2D-Kante <-> 3D-Kante: die Ringe sind gleich geordnet (ggf. umgekehrt durch orient)
        xyz_l = xyz
        p2_orig = list(Polygon(pg.exterior).exterior.coords)[:-1]
        umgekehrt = Polygon(p2_orig).exterior.is_ccw is False
        gesamt = pg
        ritz = []
        n = len(p2_orig)
        for i in range(n):
            k3 = (xyz_l[i], xyz_l[(i + 1) % n])
            geteilt = False
            for jj, kj in enumerate(kanten):
                if jj == j:
                    continue
                for (r, s) in kj:
                    if _kante_gleich(k3[0], k3[1], r, s):
                        geteilt = True
                        break
                if geteilt:
                    if jj < j:                               # die Lasche sitzt am Dach mit dem kleineren Index
                        pass
                    break
            if geteilt and any(jj < j and any(_kante_gleich(k3[0], k3[1], r, s) for r, s in kanten[jj]) for jj in range(len(kanten))):
                continue                                     # Nachbar hat die Lasche
            a2, b2 = p2_orig[i], p2_orig[(i + 1) % n]
            lash = _lasche(a2, b2, breite, pg)
            if lash is None or lash.is_empty:
                continue
            gesamt = gesamt.union(lash)
            ritz.append(LineString([a2, b2]))
        gesamt = shapely.union_all(polys(gesamt))
        teile.append(_teil(f"{b['nr']}-D{j + 1:02d}", gesamt, b, "Dach", ritz))
    if beschriften:
        for t in teile:
            _beschriften(t)
    return teile


# ------------------------------------------------------------------ Gesamt
def teile_fuer(buildings, cfg, t_mm, formate, rand_mm, log=print):
    """Laserteile aller Gebäude im gewählten Modus (status == "druck"). -> Liste Teile"""
    gc = cfg["gebaeude"]
    modus = gc.get("modus", "druck")
    breite = float(gc.get("lasche_mm") or 3.0)
    max_l = max(f[0] for f in formate) - 2 * rand_mm - 6.0
    beschr = bool(gc.get("teile_beschriften", True))
    _CTX["cfg"] = cfg
    try:
        from .. import zusatz as ZU
        _CTX["zusatz"] = ZU.vorhanden() and modus in ("flaeche", "falt")
    except Exception:
        _CTX["zusatz"] = False
    massstab = float(cfg["massstab"]) if gc.get("fenstermuster") else None       # Fenstermuster: nur bei Flaechen/Faltmodell
    alle = []
    n_geb = 0
    for b in buildings:
        if b["status"] != "druck" or b.get("footprint") is None or b["footprint"].is_empty:
            continue
        try:
            if modus == "stapel":
                ts = stapel_teile(b, t_mm, beschr)
            elif modus == "flaeche":
                ts = flaechen_teile(b, beschr, massstab)
            elif modus == "falt":
                ts = falt_teile(b, breite, max_l, beschr, massstab)
            else:
                ts = []
        except Exception as e:
            log(f"  WARNUNG: Gebäude {b.get('nr')}: Laserteile nicht erzeugt ({str(e)[:80]})")
            ts = []
        for t in ts:
            t["layer"] = -1
        if ts:
            n_geb += 1
            alle += ts
    names = {"stapel": "Stapelmodell", "flaeche": "Klebeflächen ohne Laschen", "falt": "Faltmodell"}
    log(f"  Gebäude als {names.get(modus, modus)}: {len(alle)} Teile für {n_geb} Gebäude")
    if massstab and modus in ("flaeche", "falt"):
        log("  Fenstermuster: gravierte Rechtecke an den Wänden - ein MUSTER nach Wandbreite und -höhe, KEINE Messung (LoD2 enthält keine Öffnungen)")
    return alle
