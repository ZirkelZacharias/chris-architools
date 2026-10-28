# -*- coding: utf-8 -*-
"""IFCmap - Sonnenstand (eigene Rechnung), Schatten, Dachlinien und Dachschattierung fuer die 2D-Plaene.

Der Sonnenstand wird hier UNABHAENGIG vom Sonnenbahn-Diagramm des Hauptprogramms berechnet (Formeln des US Naval Observatory, Genauigkeit < 0,05 Grad),
ebenso die Sommerzeit (EU-Regel: letzter Sonntag im Maerz bis letzter Sonntag im Oktober, jeweils 01:00 UTC).
Die Oberflaeche verbindet beide Funktionen nur ueber das Datum: Waehlt man einen Zeitpunkt fuer den Schatten, springt der Monat des
Sonnenbahn-Diagramms mit und umgekehrt.

Schatten: Jede Gebaeudeflaeche (Wand, Dach) wird entlang der Sonnenstrahlen auf die Bodenebene des Gebaeudes projiziert; die Vereinigung
aller Projektionen ist der Schatten. Gebaeudegrundrisse werden nirgends abgezogen (die Gebaeude liegen im Plan oben auf). (Gelaendeneigung wird nicht beruecksichtigt - die Plaene sind 2D.)
"""
import datetime as dt
import math

import numpy as np
import shapely
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union

STANDARD_DATUM = (7, 6)            # 6. Juli
STANDARD_ZEIT = (16, 17)           # 16:17 Uhr (Ortszeit, MEZ/MESZ)
MEZ_STUNDEN = 1                    # UTC+1


# ----------------------------------------------------------------------------------------------
# Zeit
# ----------------------------------------------------------------------------------------------

def _letzter_sonntag(jahr, monat):
    d = dt.date(jahr, monat, 31)
    while d.weekday() != 6:
        d -= dt.timedelta(days=1)
    return d


def ist_sommerzeit_utc(utc):
    """EU-Sommerzeit: ab letztem Sonntag im Maerz 01:00 UTC bis letztem Sonntag im Oktober 01:00 UTC."""
    start = dt.datetime.combine(_letzter_sonntag(utc.year, 3), dt.time(1, 0))
    ende = dt.datetime.combine(_letzter_sonntag(utc.year, 10), dt.time(1, 0))
    return start <= utc.replace(tzinfo=None) < ende


def lokal_nach_utc(lokal):
    """Ortszeit (naiv, MEZ bzw. MESZ) -> UTC (naiv)."""
    mez = lokal - dt.timedelta(hours=MEZ_STUNDEN)
    if ist_sommerzeit_utc(mez - dt.timedelta(hours=1)):
        return mez - dt.timedelta(hours=1)
    return mez


def zeitzone_text(lokal):
    return "MESZ (UTC+2)" if ist_sommerzeit_utc(lokal - dt.timedelta(hours=MEZ_STUNDEN) - dt.timedelta(hours=1)) else "MEZ (UTC+1)"


def parse_datum(text):
    """'6.7.' / '06.07' / '6.7.2026' -> (Monat, Tag) oder None"""
    import re
    m = re.match(r"^\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})", str(text or ""))
    if not m:
        return None
    tag, mon = int(m.group(1)), int(m.group(2))
    if not (1 <= mon <= 12 and 1 <= tag <= 31):
        return None
    try:
        dt.date(2001 if mon != 2 or tag < 29 else 2000, mon, tag)
    except ValueError:
        return None
    return mon, tag


def parse_zeit(text):
    """'16:17' / '16.17' / '9' -> (Stunde, Minute) oder None"""
    import re
    m = re.match(r"^\s*(\d{1,2})\s*(?:[:.hH]\s*(\d{1,2}))?\s*(?:Uhr)?\s*$", str(text or ""))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if h > 23 or mi > 59:
        return None
    return h, mi


def zeitpunkt(cfg, jahr=None, auch_aus=False):
    """Zeitpunkt der Schattenberechnung aus der Konfiguration -> (naives Datum/Uhrzeit in Ortszeit) oder None, wenn Schatten aus sind.
    auch_aus=True: bei "aus" den Standardzeitpunkt liefern (z. B. fuer die Dachschattierung ohne Schatten)."""
    modus = getattr(cfg, "schatten", "aus")
    if modus == "aus" and not auch_aus:
        return None
    jahr = jahr or dt.date.today().year
    mon, tag = STANDARD_DATUM[0], STANDARD_DATUM[1]
    h, mi = STANDARD_ZEIT
    if modus == "eigen":
        mon, tag = parse_datum(getattr(cfg, "schatten_datum", "")) or (mon, tag)
        h, mi = parse_zeit(getattr(cfg, "schatten_zeit", "")) or (h, mi)
    return dt.datetime(jahr, mon, tag, h, mi)


# ----------------------------------------------------------------------------------------------
# Sonnenstand (NOAA)
# ----------------------------------------------------------------------------------------------

def sonnenstand(breite, laenge, utc):
    """Sonnenstand fuer Breite/Laenge (Grad, Ost positiv) zur UTC-Zeit (naiv) -> (Azimut in Grad von Nord im Uhrzeigersinn, Hoehe in Grad).
    Rechnung nach den niedrig-genauen Formeln des US Naval Observatory (ekliptikale Laenge, Rektaszension, Zeitgleichung); Fehler < 0,05 Grad.
    Keine Refraktionskorrektur (fuer Schatten unerheblich)."""
    D = (utc - dt.datetime(2000, 1, 1, 12)).total_seconds() / 86400.0          # Tage seit J2000.0
    g = math.radians((357.529 + 0.98560028 * D) % 360.0)                        # mittlere Anomalie
    q = (280.459 + 0.98564736 * D) % 360.0                                      # mittlere Laenge
    lam = math.radians(q + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))       # ekliptikale Laenge
    eps = math.radians(23.439 - 3.6e-7 * D)                                     # Schiefe der Ekliptik
    ra = math.degrees(math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))) % 360.0
    dekl = math.asin(math.sin(eps) * math.sin(lam))
    zeitgl = (q - ra + 180.0) % 360.0 - 180.0                                   # Zeitgleichung in Grad (4 Minuten je Grad)
    wahre_sonnenzeit = utc.hour * 60 + utc.minute + utc.second / 60.0 + 4.0 * laenge + 4.0 * zeitgl      # Minuten
    stundenwinkel = math.radians((wahre_sonnenzeit % 1440.0) / 4.0 - 180.0)
    phi = math.radians(breite)
    cos_z = math.sin(phi) * math.sin(dekl) + math.cos(phi) * math.cos(dekl) * math.cos(stundenwinkel)
    cos_z = max(-1.0, min(1.0, cos_z))
    zenit = math.acos(cos_z)
    hoehe = 90.0 - math.degrees(zenit)
    sin_z = math.sin(zenit)
    if sin_z < 1e-9:
        return 180.0, hoehe
    cos_az = (math.sin(phi) * cos_z - math.sin(dekl)) / (math.cos(phi) * sin_z)
    az = math.degrees(math.acos(max(-1.0, min(1.0, cos_az))))
    az = (az + 180.0) % 360.0 if stundenwinkel > 0 else (540.0 - az) % 360.0       # nachmittags westlich, vormittags oestlich
    return az, hoehe


def sonne_zum_zeitpunkt(breite, laenge, lokal):
    """Ortszeit (naiv) -> (Azimut, Hoehe)"""
    return sonnenstand(breite, laenge, lokal_nach_utc(lokal))


def gitter_drehung(cfg, d):
    """Gitter-Azimut von "wahr Nord" in Grad (Meridiankonvergenz) am Mittelpunkt -> (drehung, breite, laenge)"""
    from pyproj import Transformer
    lon, lat = Transformer.from_crs("EPSG:%d" % cfg.epsg, "EPSG:4326", always_xy=True).transform(d.ce, d.cn)
    e2, n2 = Transformer.from_crs("EPSG:4326", "EPSG:%d" % cfg.epsg, always_xy=True).transform(lon, lat + 0.0005)
    return math.degrees(math.atan2(e2 - d.ce, n2 - d.cn)), lat, lon


def sonne_fuer_plan(cfg, d, auch_aus=False):
    """Sonnenstand zum eingestellten Schattenzeitpunkt, auf Plan-Nord (Gitter) bezogen.
    -> dict(lokal, az, el, az_wahr, text, breite, laenge, drehung) oder None, wenn Schatten aus sind"""
    lokal = zeitpunkt(cfg, auch_aus=auch_aus)
    if lokal is None:
        return None
    dreh, lat, lon = gitter_drehung(cfg, d)
    az_w, el = sonne_zum_zeitpunkt(lat, lon, lokal)
    az = (az_w + dreh) % 360.0
    text = "%d.%d. %02d:%02d Uhr %s - Sonne Azimut %.1f Grad, Hoehe %.1f Grad" % (
        lokal.day, lokal.month, lokal.hour, lokal.minute, zeitzone_text(lokal), az_w, el)
    return dict(lokal=lokal, az=az, el=el, az_wahr=az_w, text=text, breite=lat, laenge=lon, drehung=dreh)


def bahn_tag(breite, laenge, monat, tag, jahr=None, schritt_min=10):
    """Sonnenbahn eines Tages: Liste (Ortszeit-Stunde als float, Azimut, Hoehe) fuer Hoehe >= 0"""
    jahr = jahr or dt.date.today().year
    out = []
    for m in range(0, 24 * 60, schritt_min):
        lokal = dt.datetime(jahr, monat, tag, m // 60, m % 60)
        az, el = sonne_zum_zeitpunkt(breite, laenge, lokal)
        if el >= 0:
            out.append((m / 60.0, az, el))
    return out


# ----------------------------------------------------------------------------------------------
# Gebaeudeflaechen sammeln
# ----------------------------------------------------------------------------------------------

def _polys(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g]
    return [p for x in getattr(g, "geoms", []) for p in _polys(x)]


def _projizieren(faces, richtung, zg):
    """3D-Flaechen (Liste Nx3) entlang der Sonnenrichtung auf die Ebene z = zg -> Liste Polygone. richtung = Verschiebung je Meter Hoehe (dx, dy)."""
    out = []
    dx, dy = richtung
    for f in faces:
        f = np.asarray(f, float)
        if len(f) < 3:
            continue
        h = f[:, 2] - zg
        xy = np.column_stack([f[:, 0] + dx * h, f[:, 1] + dy * h])
        try:
            p = Polygon(xy)
            if not p.is_valid:
                p = p.buffer(0)
            if not p.is_empty and p.area > 1e-4:
                out.append(p)
        except Exception:
            continue
    return out


def gebaeude_koerper(d):
    """-> Liste von dicts (gid, zg, fp = Grundriss (shapely), faces [3D-Flaechen], nah, markant) fuer alle Gebaeude.
    Nahbereich: Wand- und Dachflaechen; Fernbereich: Block bis zur Traufe. Markante Gebaeude mit ihrer Detailform (DOM/OSM/LoD2)."""
    import ifcmap_kern as K
    cfg = d.cfg
    je = {}
    for t in d.teile:
        je.setdefault(t["gebaeude"] or t["id"], []).append(t)
    mark = {m["gid"]: m for m in (getattr(d, "markant", None) or [])}
    out = []
    for gid, teile in je.items():
        fp_list, faces, zgs = [], [], []
        for t in teile:
            if not t["ground"]:
                continue
            zg = min(e[:, 2].min() for e, h in t["ground"])
            zgs.append(zg)
            for e, h in t["ground"]:
                if len(e) >= 3:
                    p = Polygon(e[:, :2], [x[:, :2] for x in h if len(x) >= 3])
                    fp_list.append(p if p.is_valid else p.buffer(0))
            if gid in mark:
                continue
            if t.get("kompakt") or not (t["wall"] or t["roof"]):
                try:
                    faces += K.block_faces(t)[0]
                except Exception:
                    pass
            else:
                faces += K.lod2_faces(t)
        if gid in mark:
            faces = [np.asarray(f, float) for f in mark[gid]["faces"]]
        if not fp_list or not faces:
            continue
        fp = unary_union(fp_list)
        c = fp.representative_point()
        out.append(dict(gid=gid, zg=min(zgs), fp=fp, faces=faces, nah=K.nah_enthaelt(cfg, d, c.x, c.y), markant=gid in mark))
    return out


# ----------------------------------------------------------------------------------------------
# Schatten
# ----------------------------------------------------------------------------------------------

def schatten_geometrie(d, az, el, mit_baeumen=False, log=None, max_laenge=200.0, koerper=None, baum_bereich=None):
    """Schattenflaeche (shapely, absolute Koordinaten) fuer Sonnenazimut az (Plan-Nord) / -hoehe el (Grad).
    Die Gebaeudegrundrisse werden NICHT abgezogen - der Schatten laeuft unter den Gebaeuden durch, die Gebaeude liegen im Plan darueber.
    -> Geometrie oder None"""
    if el < 2.0:
        if log:
            log("  Schatten: Sonne steht nur %.1f Grad ueber dem Horizont - keine sinnvollen Schatten" % el)
        return None
    t = 1.0 / math.tan(math.radians(el))
    k = min(t, max_laenge / 30.0)                                            # Schattenlaenge je Meter Hoehe (begrenzt)
    richtung = (-math.sin(math.radians(az)) * k, -math.cos(math.radians(az)) * k)
    teile = []
    for g in (koerper if koerper is not None else gebaeude_koerper(d)):
        pr = _projizieren(g["faces"], richtung, g["zg"])
        pr.append(g["fp"])                                                   # Grundriss gehoert zum Schattenwerfer (lueckenlos am Gebaeudefuss)
        try:
            teile.append(unary_union(pr))
        except Exception:
            teile += pr
    if mit_baeumen and getattr(d, "baeume", None):
        import shapely.affinity as A
        nahr = baum_bereich                                                     # Baumschatten nur in diesem Bereich (Nahbereich + Uebergang), None = ueberall
        for (x, y, kr, ho, st, _) in d.baeume:
            if nahr is not None and not nahr.covers(shapely.Point(x, y)):
                continue
            r = max(kr, 1.0) / 2.0
            zc = max(ho - r, 1.0)                                             # Hoehe der Kronenmitte
            cx, cy = x + richtung[0] * zc, y + richtung[1] * zc
            c = shapely.Point(cx, cy).buffer(r, 12)
            ell = A.scale(c, xfact=1.0 / max(math.sin(math.radians(el)), 0.2), yfact=1.0, origin="center")
            ell = A.rotate(ell, math.degrees(math.atan2(richtung[1], richtung[0])), origin=(cx, cy))
            if nahr is not None:
                ell = ell.intersection(nahr)                                    # auch der Schatten bleibt im Nahbereich
                if ell.is_empty:
                    continue
            teile.append(ell)
    if not teile:
        return None
    s = unary_union(teile).intersection(d.rect)
    return None if s.is_empty else s


# ----------------------------------------------------------------------------------------------
# Dachlinien (Firste, Grate, Kehlen)
# ----------------------------------------------------------------------------------------------

def dachlinien(flaechen_je_gebaeude, min_winkel=12.0, min_laenge=0.8):
    """flaechen_je_gebaeude: Liste von Flaechenlisten (je Gebaeude Liste Nx3-Arrays). Findet Kanten, an denen zwei Dachflaechen mit
    unterschiedlicher Neigung aneinanderstossen (Firste/Grate: Dach faellt nach beiden Seiten ab; Kehlen: umgekehrt).
    -> (firste [LineString], kehlen [LineString]) in absoluten Koordinaten (2D)"""
    firste, kehlen = [], []
    for faces in flaechen_je_gebaeude:
        kanten = {}
        normalen = []
        for fi, f in enumerate(faces):
            f = np.asarray(f, float)
            if len(f) < 3:
                normalen.append(None)
                continue
            nv = np.zeros(3)
            for i in range(len(f)):
                nv += np.cross(f[i], f[(i + 1) % len(f)])
            L = np.linalg.norm(nv)
            if L < 1e-6 or nv[2] / L < 0.05:                                 # nur Dachflaechen (nach oben zeigend)
                normalen.append(None)
                continue
            normalen.append(nv / L)
            for i in range(len(f)):
                a, b = f[i], f[(i + 1) % len(f)]
                ka, kb = tuple(np.round(a, 2)), tuple(np.round(b, 2))
                if ka == kb:
                    continue
                kanten.setdefault((min(ka, kb), max(ka, kb)), []).append(fi)
        for (ka, kb), fl in kanten.items():
            if len(fl) != 2:
                continue
            n1, n2 = normalen[fl[0]], normalen[fl[1]]
            if n1 is None or n2 is None:
                continue
            ang = math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(n1, n2))))))
            if ang < min_winkel:
                continue
            if math.hypot(ka[0] - kb[0], ka[1] - kb[1]) < min_laenge:
                continue
            mitte = (np.array(ka) + np.array(kb)) / 2.0
            c1 = np.asarray(faces[fl[0]], float).mean(axis=0)
            konvex = float(np.dot(c1 - mitte, n2)) < 0                       # Flaeche 1 liegt unterhalb der Ebene 2 -> Rueckgrat
            (firste if konvex else kehlen).append(LineString([ka[:2], kb[:2]]))
    return firste, kehlen


def dach_flaechen_tonwerte(flaechen_je_gebaeude, az, el, stufen=7, tief=(120, 120, 120), hell=(250, 250, 250)):
    """Dachflaechen nach Ausrichtung zur Sonne schattieren. -> {Stufe: [Polygon]} (Stufe 0 = dunkel ... stufen-1 = hell), Tonwerte ueber tonwert()"""
    sx = math.sin(math.radians(az)) * math.cos(math.radians(el))
    sy = math.cos(math.radians(az)) * math.cos(math.radians(el))
    sz = math.sin(math.radians(el))
    s = np.array([sx, sy, sz])
    out = {}
    for faces in flaechen_je_gebaeude:
        for f in faces:
            f = np.asarray(f, float)
            if len(f) < 3:
                continue
            nv = np.zeros(3)
            for i in range(len(f)):
                nv += np.cross(f[i], f[(i + 1) % len(f)])
            L = np.linalg.norm(nv)
            if L < 1e-6 or nv[2] / L < 0.05:
                continue
            licht = max(0.0, float(np.dot(nv / L, s)))                       # 0 (abgewandt) ... 1 (senkrecht zur Sonne)
            stufe = min(stufen - 1, int(licht * stufen))
            try:
                p = Polygon(f[:, :2])
                if not p.is_valid:
                    p = p.buffer(0)
                if not p.is_empty and p.area > 1e-3:
                    out.setdefault(stufe, []).append(p)
            except Exception:
                continue
    return out


def tonwert(stufe, stufen=7, dunkel=(150, 150, 150), hell=(250, 250, 250)):
    t = stufe / max(stufen - 1, 1)
    return tuple(int(round(dunkel[i] + (hell[i] - dunkel[i]) * t)) for i in range(3))
