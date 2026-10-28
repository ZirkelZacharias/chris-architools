# -*- coding: utf-8 -*-
"""IFCmap - Luecken im LoD2 fuellen.

Wo das amtliche LoD2 ein Gebaeude nicht kennt (neu gebaut, nicht erfasst, Kuppeln wie das Zeiss-Grossplanetarium ...), wird es ergaenzt.
Reihenfolge der Quellen: amtlich zuerst, OpenStreetMap nur fuer das, was es amtlich nicht gibt:
  - Umriss: ALKIS-Grundriss (Berlin); OSM-Umriss nur, wo es keinen passenden ALKIS-Grundriss gibt
  - Hoehe/Dachform: Umweltatlas-Gebaeudehoehen (Firsthoehe + Dachart, wenn gewaehlt), sonst OSM (Hoehe, Geschosse, roof:shape,
    Gebaeudeteile building:part), sonst ALKIS-Geschosse (aog) x 3 m, ohne Angabe 2,2 m - als 'geschaetzt' markiert
Quelle im Ergebnis: 'ALKIS+UA', 'ALKIS+OSM', 'OSM' oder 'ALKIS'.
Hat ein Gebiet gar kein LoD2 (z. B. Hamburg ohne automatischen Download), werden alle Gebaeude aus OpenStreetMap gebaut.
Die Ergebnisse haben dieselbe Form wie LoD2-Teile (wall/roof/ground) und laufen durch die Nah-/Fernbereich-Logik des Programms:
im Nahbereich mit Dachform, im Fernbereich als Block bis zur Traufe.
"""
import math
import re
import time

import numpy as np
import shapely
from shapely.geometry import Polygon
from shapely.ops import unary_union
from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator
from scipy.spatial import cKDTree

import ifcmap_markant as M

MIN_FLAECHE = 12.0                 # m2: kleinere OSM-Gebaeude (Huetten) werden nicht ergaenzt
MIN_FLAECHE_ALKIS = 15.0
ABDECKUNG = 0.30                   # Anteil des Umrisses, der schon durch LoD2 belegt ist -> dann keine Luecke
SKIP_BUILDING = {"no", "demolished", "collapsed", "construction", "proposed"}      # Ruinen, Dachflaechen (roof) und verlassene Bauten stehen noch -> werden gebaut


def gelaende_hoehe(d, cfg=None):
    """-> f(x, y): Gelaendehoehe (Array-faehig). Aus dem DGM, sonst aus den Grundflaechen der vorhandenen LoD2-Gebaeude, sonst d.z0."""
    if getattr(d, "px", None) is not None and len(d.px) >= 4:
        xy = np.column_stack([d.px, d.py])
        lin = LinearNDInterpolator(xy, d.pz)
        nn = NearestNDInterpolator(xy, d.pz)

        def f(x, y):
            x, y = np.asarray(x, float), np.asarray(y, float)
            z = lin(x, y)
            return np.where(np.isnan(z), nn(x, y), z)
        return f
    pts = []
    for t in d.teile:
        if t.get("ground"):
            pts.append((t["c"][0], t["c"][1], float(min(e[:, 2].min() for e, h in t["ground"]))))
    if pts:
        a = np.array(pts)
        kd = cKDTree(a[:, :2])

        def f(x, y):
            x, y = np.atleast_1d(np.asarray(x, float)), np.atleast_1d(np.asarray(y, float))
            _, idx = kd.query(np.column_stack([x, y]), k=min(5, len(a)))
            return np.median(a[:, 2][np.atleast_2d(idx.T).T], axis=1) if idx.ndim > 1 else a[:, 2][idx]
        return f
    z0 = float(getattr(d, "z0", 0.0) or 0.0)
    return lambda x, y: np.full(np.shape(np.atleast_1d(x)), z0)


def _grundhoehe(f, poly):
    """Gelaendehoehe fuer ein Polygon: niedrigster Wert entlang des Umrisses (das Haus steht am tiefsten Punkt)"""
    c = np.array(poly.exterior.coords)
    z = np.atleast_1d(f(c[:, 0], c[:, 1]))
    z = z[np.isfinite(z)]
    return float(z.min()) if len(z) else 0.0


def _teil_aus_faces(gid, tid, faces, polys, zg, quelle, h, geschaetzt, info):
    """Flaechenliste (aus teil_faces) -> LoD2-Teil: senkrechte Flaechen = Wand, nach oben = Dach, Boden aus dem Grundriss."""
    wall, roof = [], []
    for fc in faces:
        fc = np.asarray(fc, float)
        if len(fc) < 3:
            continue
        nv = np.zeros(3)
        for i in range(len(fc)):
            nv += np.cross(fc[i], fc[(i + 1) % len(fc)])
        L = float(np.linalg.norm(nv))
        if L < 1e-9:
            continue
        nz = nv[2] / L
        if abs(nz) < 0.05:
            wall.append((fc, []))
        elif nz > 0:
            roof.append((fc, []))
        else:
            wall.append((fc, []))                        # Bodenplatte: gleiche Randpunkte wie Waende und Dach -> geschlossene Huelle
    ground = _ground(polys, zg)
    if not ground:
        return None
    c = polys[0].centroid if len(polys) == 1 else unary_union(polys).centroid
    return dict(id=tid, gebaeude=gid, h=h, wall=wall, roof=roof, ground=ground, closure=[], c=(c.x, c.y),
                quelle=quelle, geschaetzt=geschaetzt, info=info, boden_dicht=True)


def _ground(polys, zg):
    out = []
    for p in polys:
        for pg in M._polys_aus(p):
            e = np.array(pg.exterior.coords)[:-1]
            if len(e) < 3:
                continue
            holes = [np.column_stack([np.array(r.coords)[:-1], np.full(len(r.coords) - 1, zg)]) for r in pg.interiors]
            out.append((np.column_stack([e, np.full(len(e), zg)]), holes))
    return out


def _teil_kompakt(gid, tid, polys, zg, z_traufe, z_first, quelle, h, geschaetzt, info):
    """Fernbereich: nur Grundriss + Dachhoehen (wie ein verdichtetes LoD2-Teil)"""
    ground = _ground(polys, zg)
    if not ground:
        return None
    c = unary_union(polys).centroid
    return dict(id=tid, gebaeude=gid, h=h, wall=[], roof=[], ground=ground, closure=[], c=(c.x, c.y), roofz=(z_traufe, z_first),
                kompakt=True, dachk=(0, set(), 0.0, 0.0), quelle=quelle, geschaetzt=geschaetzt, info=info)


def _aog(props):
    """Anzahl oberirdischer Geschosse aus den ALKIS-Attributen (aog / anzahlDerOberirdischenGeschosse)"""
    for k, v in props.items():
        kl = str(k).lower()
        if kl == "aog" or "oberirdisch" in kl:
            try:
                x = float(str(v).replace(",", "."))
                if 0 < x < 100:
                    return x
            except ValueError:
                pass
    return None


def luecken_fuellen(d, cfg, log, osm=None, alkis=None, nah=None, fern_modus="bloecke"):
    """Ergaenzt d.teile um Gebaeude aus OSM (osm = Ergebnis von M.osm_gebaeude_laden) und ALKIS-Grundrissen (alkis = [(Geometrie, Attribute)]).
    nah = (Ost, Nord, Breite, Hoehe) des Nahbereichs. -> Anzahl hinzugefuegter Gebaeude. d.luecken = Liste dict(gid, quelle, geschaetzt, text)"""
    import ifcmap_kern as K
    t0 = time.time()
    d.luecken = []
    if not getattr(cfg, "lod2_luecken", True):
        return 0
    if osm is None and not alkis:
        if not d.teile:
            log("  Keine LoD2-Gebaeude und keine Ersatzquelle (OpenStreetMap/ALKIS nicht verfuegbar) - es gibt keine Gebaeude.")
        return 0
    ohne_lod2 = not d.teile
    M.HOEHE_OHNE_ANGABE = float(getattr(cfg, "hoehe_ohne_angabe", 2.2) or 2.2)
    # --- was ist schon durch LoD2 belegt?
    polys = []
    for t in d.teile:
        for e, h in (t["ground"] or t["roof"]):
            if len(e) >= 3:
                try:
                    pg = Polygon(e[:, :2]).buffer(0)
                    if not pg.is_empty:
                        polys.append(pg)
                except Exception:
                    pass
    tree = shapely.STRtree(polys) if polys else None

    def belegt(geom, extra=None):
        a = geom.area
        if a <= 0:
            return 1.0
        inter = 0.0
        if tree is not None:
            hits = tree.query(geom, predicate="intersects")
            if len(hits):
                try:
                    inter = unary_union([polys[int(i)] for i in hits]).intersection(geom).area
                except Exception:
                    inter = 0.0
        if extra and inter < a:
            for g in extra:
                if g.intersects(geom):
                    try:
                        inter = max(inter, g.intersection(geom).area)
                    except Exception:
                        pass
        return inter / a

    gz = gelaende_hoehe(d, cfg)
    neu_fp = []                                           # Grundrisse der schon ergaenzten Gebaeude
    neue, texte = [], []
    stat = dict(osm=0, osm_hoehe=0, osm_gesch=0, alkis=0, alkis_osm=0, alkis_ua=0, klein=0, dach=0)

    def im_nah(c):
        return nah is None or (abs(c.x - nah[0]) <= nah[2] / 2 and abs(c.y - nah[1]) <= nah[3] / 2)

    # --- ALKIS-Geschosse fuer die Hoehenschaetzung der OSM-Gebaeude
    alk = None
    if alkis:
        gl = [g for g, p in alkis if g.geom_type in ("Polygon", "MultiPolygon") and not g.is_empty]
        pl = [p for g, p in alkis if g.geom_type in ("Polygon", "MultiPolygon") and not g.is_empty]
        if gl:
            alk = (shapely.STRtree(gl), gl, pl)

    def alkis_geschosse(geom):
        if alk is None:
            return None
        best, bo = None, 0.0
        for i in alk[0].query(geom, predicate="intersects"):
            try:
                o = alk[1][int(i)].intersection(geom).area
            except Exception:
                continue
            if o > bo:
                bo, best = o, int(i)
        if best is not None and bo >= 0.5 * geom.area:
            return _aog(alk[2][best])
        return None

    # --- 1. OpenStreetMap
    ausgelassen = []                                      # (Grund, OSM-Objekt) - nicht ergaenzte OSM-Gebaeude, fuer das Protokoll

    def alkis_passend(fp):
        """ALKIS-Grundriss, der zum OSM-Umriss fp passt (mind. 70 % von fp bedeckt, aehnliche Groesse) - sonst None"""
        if alk is None:
            return None
        best, bo = None, 0.0
        for i in alk[0].query(fp, predicate="intersects"):
            try:
                o = alk[1][int(i)].intersection(fp).area
            except Exception:
                continue
            if o > bo:
                bo, best = o, alk[1][int(i)]
        if best is None or bo < 0.7 * fp.area or not (0.6 <= best.area / fp.area <= 1.6) or best.geom_type not in ("Polygon", "MultiPolygon"):
            return None
        return best

    def bauen(outl, ps, fp, quelle_g="OSM"):
        """Ein Gebaeude aus Umriss(en)/Teilen bauen und zu 'neue' hinzufuegen. quelle_g: 'OSM'; 'ALKIS+OSM' = ALKIS-Umriss mit OSM-Details;
        'ALKIS+UA' = ALKIS-Umriss mit Hoehe/Dachform aus dem Umweltatlas. Ist der Umweltatlas aktiv, gilt seine Firsthoehe/Dachart (amtlich)
        vor den OSM-Angaben - ausser bei Gebaeuden mit OSM-Teilen (building:part), deren Detail bleibt."""
        if fp.area < MIN_FLAECHE:
            stat["klein"] += 1
            return
        bel = belegt(fp, neu_fp)
        if bel >= ABDECKUNG:
            ausgelassen.append(("%.0f %% schon durch LoD2 belegt" % (bel * 100), (outl[0] if outl else ps[0]), fp.area))
            return
        o0 = outl[0] if outl else ps[0]
        polys_fp = M._polys_aus(fp)
        if not polys_fp:
            return
        geom_c = fp.centroid
        zg = _grundhoehe(gz, max(polys_fp, key=lambda p: p.area))
        aog = alkis_geschosse(fp)
        h_ref = aog * 3.0 if aog else None
        ua = getattr(d, "ua_geb", None)
        ua_t = ua.treffer(fp) if ua else None
        h_ua = ua_t["hoehe"] if ua_t else None
        ua_dach = False
        if h_ua:
            h_ref = h_ua
            if not ps and outl:
                t2 = dict(outl[0]["tags"])
                t2["height"] = "%.1f" % h_ua
                alt = (t2.get("roof:shape") or "flat").split(";")[0].strip()
                if ua_t["dach"] and ua_t["dach"] != alt:
                    t2["roof:shape"] = ua_t["dach"]
                    for k in ("roof:height", "roof:levels", "roof:angle", "roof:direction"):
                        t2.pop(k, None)
                    ua_dach = True
                outl = [dict(outl[0], tags=t2)]
        if quelle_g == "OSM":
            gid = "OSM_" + str(o0.get("id") or "%.0f_%.0f" % (geom_c.x, geom_c.y)).replace("/", "_")
        else:
            gid = "ALKIS_%.0f_%.0f" % (geom_c.x, geom_c.y)
        nahb = im_nah(geom_c)
        try:
            kor = M.osm_koerper(outl, ps, fp, zg, h_ref)
        except Exception as e:
            log("    Gebaeude %s nicht gebaut: %s" % (gid, str(e)[:100]))
            ausgelassen.append(("Fehler beim Bauen: %s" % str(e)[:60], o0, fp.area))
            return
        if not kor:
            ausgelassen.append(("kein Koerper erzeugt", o0, fp.area))
            return
        ges = kor["geschaetzt"]
        hoehe = kor["zmax"] - zg
        kopf = {"OSM": "OSM %s" % (o0.get("id") or "?"), "ALKIS+OSM": "ALKIS-Grundriss, Details aus OSM %s" % (o0.get("id") or "?"),
                "ALKIS+UA": "ALKIS-Grundriss"}[quelle_g]
        if h_ua and not ps:
            rest = ", Hoehe %.1f m%s aus dem Umweltatlas" % (h_ua, " und Dachform" if ua_dach else "")
        elif ges and h_ua:
            rest = ", Hoehe %.1f m aus dem Umweltatlas (Firsthoehe)" % h_ua
        elif ges and aog:
            rest = ", Hoehe geschaetzt (ALKIS-Geschosse x 3 m)"
        else:
            rest = ", Hoehe geschaetzt (Gebaeudetyp)" if ges else ""
        info = "%s, Dachform %s%s" % (kopf, "/".join(kor["formen"]), rest)
        if nahb or fern_modus == "lod2":
            t = _teil_aus_faces(gid, gid + "_0", kor["faces"], polys_fp, zg, quelle_g, hoehe, ges, info)
        else:
            eave = zg + hoehe * 0.8 if kor["formen"] != ["flat"] else zg + hoehe
            t = _teil_kompakt(gid, gid + "_0", polys_fp, zg, eave, zg + hoehe, quelle_g, hoehe, ges, info)
        if t is None:
            ausgelassen.append(("Teil nicht erzeugbar", o0, fp.area))
            return
        neue.append(t)
        neu_fp.append(fp)
        stat["osm" if quelle_g == "OSM" else ("alkis_osm" if quelle_g == "ALKIS+OSM" else "alkis_ua")] += 1
        stat["osm_gesch" if ges else "osm_hoehe"] += 1
        if any(f != "flat" for f in kor["formen"]):
            stat["dach"] += 1
        d.luecken.append(dict(gid=gid, quelle=quelle_g, geschaetzt=ges, text=info, flaeche=fp.area, hoehe=hoehe))
        if len(texte) < 12:
            texte.append("%s (%.0f m2, %.0f m%s)" % (gid, fp.area, hoehe, ", geschaetzt" if ges else ""))

    if osm is not None:
        obj = osm["objekte"]
        bauten = [o for o in obj if o["art"] == "building" and o["tags"].get("building") not in SKIP_BUILDING
                  and o["tags"].get("location") != "underground"]
        for o in obj:                                     # Bauten, die wegen ihres Typs nicht gebaut werden (fuer das Protokoll)
            if o["art"] == "building" and (o["tags"].get("building") in SKIP_BUILDING or o["tags"].get("location") == "underground"):
                ausgelassen.append(("Typ building=%s" % (o["tags"].get("building") if o["tags"].get("building") in SKIP_BUILDING else "underground"), o))
        teile_o = [o for o in obj if o["art"] == "part"]
        ptree = shapely.STRtree([o["geom"] for o in teile_o]) if teile_o else None
        benutzt = set()
        gruppen = []                                      # (outline-Objekte, Teile, Footprint)
        for o in bauten:
            fp = o["geom"]
            ps = []
            if ptree is not None:
                for i in ptree.query(fp, predicate="intersects"):
                    pgm = teile_o[int(i)]["geom"]
                    try:
                        if pgm.intersection(fp).area >= 0.5 * pgm.area:
                            ps.append(teile_o[int(i)])
                            benutzt.add(int(i))
                    except Exception:
                        pass
            gruppen.append(([o], ps, fp))
        for i, o in enumerate(teile_o):                     # Teile ohne Umriss-Gebaeude
            if i not in benutzt and not o["tags"].get("level") and (o["tags"].get("min_height") in (None, "0", "0 m")):
                gruppen.append(([], [o], o["geom"]))
        for outl, ps, fp in gruppen:
            q = "OSM"
            if not ps and outl and alk is not None:            # amtlicher Umriss (ALKIS) vor dem OSM-Umriss, OSM liefert nur die Details
                ap = alkis_passend(fp)
                if ap is not None:
                    outl, fp, q = [dict(outl[0], geom=ap)], ap, "ALKIS+OSM"
            bauen(outl, ps, fp, q)

    # --- 1b. ALKIS-Grundrisse, fuer die der Umweltatlas Hoehe/Dachform kennt (amtlich vor pauschaler Schaetzung)
    ua = getattr(d, "ua_geb", None)
    if alk is not None and ua:
        for g, p in zip(alk[1], alk[2]):
            for pg in M._polys_aus(g):
                if pg.area < MIN_FLAECHE_ALKIS or belegt(pg, neu_fp) >= ABDECKUNG or ua.treffer(pg) is None:
                    continue
                o = dict(art="building", geom=pg, tags={"building": "yes", "_alkis": "1"}, id=None)
                bauen([o], [], pg, "ALKIS+UA")

    # --- 2. ALKIS-Grundrisse, die weder LoD2 noch OSM abdecken
    if alk is not None:
        for g, p in zip(alk[1], alk[2]):
            for pg in M._polys_aus(g):
                if pg.area < MIN_FLAECHE_ALKIS:
                    continue
                if belegt(pg, neu_fp) >= ABDECKUNG:
                    continue
                aog = _aog(p)
                h = aog * 3.0 if aog else M.HOEHE_OHNE_ANGABE
                ua = getattr(d, "ua_geb", None)
                h_ua = ua.hoehe(pg) if ua else None
                if h_ua:
                    h = h_ua
                c = pg.centroid
                zg = _grundhoehe(gz, pg)
                gid = "ALKIS_%.0f_%.0f" % (c.x, c.y)
                info = "ALKIS-Grundriss, Hoehe %s" % ("%.1f m aus dem Umweltatlas (Firsthoehe)" % h if h_ua else
                                                      "aus %g Geschossen x 3 m (geschaetzt)" % aog if aog else "pauschal %.1f m (geschaetzt, keine Geschosszahl)" % h)
                if im_nah(c) or fern_modus == "lod2":
                    faces = M.teil_faces(pg, zg, zg + h, 0.0, "flat", None, bodenplatte=False)
                    t = _teil_aus_faces(gid, gid + "_0", faces, [pg], zg, "ALKIS", h, True, info)
                else:
                    t = _teil_kompakt(gid, gid + "_0", [pg], zg, zg + h, zg + h, "ALKIS", h, True, info)
                if t is None:
                    continue
                neue.append(t)
                neu_fp.append(pg)
                stat["alkis"] += 1
                d.luecken.append(dict(gid=gid, quelle="ALKIS", geschaetzt=True, text=info, flaeche=pg.area, hoehe=h))
                if len(texte) < 12:
                    texte.append("%s (%.0f m2, %.0f m, geschaetzt)" % (gid, pg.area, h))
    # --- Protokoll: welche (groesseren) OSM-Gebaeude wurden NICHT ergaenzt und warum
    gross = []
    for a in ausgelassen:
        o = a[1]
        fl = a[2] if len(a) > 2 else o["geom"].area
        if fl >= 80:
            gross.append((fl, a[0], o))
    if gross or stat["klein"]:
        log("  OSM-Gebaeude nicht ergaenzt: %d unter %.0f m2, %d groessere:" % (stat["klein"], MIN_FLAECHE, len(gross)))
        for fl, grund, o in sorted(gross, key=lambda x: -x[0])[:10]:
            log("    - %s (%s%s, %.0f m2): %s" % (o["tags"].get("_osm", "?"), o["tags"].get("building", o["tags"].get("building:part", "?")),
                                              (", '%s'" % o["tags"]["name"]) if o["tags"].get("name") else "", fl, grund))
    d.teile = list(d.teile) + neue
    if ohne_lod2:
        log("  Kein LoD2 vorhanden - Gebaeude stattdessen aus OpenStreetMap%s: %d Gebaeude (%d mit Hoehe/Geschossen aus den OSM-Daten, %d Hoehe geschaetzt), "
            "davon %d mit Dachform" % (" und ALKIS" if (stat["alkis"] or stat["alkis_osm"] or stat["alkis_ua"]) else "", len(neue), stat["osm_hoehe"], stat["osm_gesch"] + stat["alkis"], stat["dach"]))
    elif neue:
        log("  LoD2-Luecken gefuellt: %d Gebaeude ergaenzt (ALKIS-Umriss mit OSM-Details %d, ALKIS-Umriss mit Umweltatlas-Hoehe/Dachform %d, "
            "nur OpenStreetMap %d, nur ALKIS-Grundriss %d; %d mit Dachform; %d mit geschaetzter Hoehe)"
            % (len(neue), stat["alkis_osm"], stat["alkis_ua"], stat["osm"], stat["alkis"], stat["dach"], stat["osm_gesch"] + stat["alkis"]))
    else:
        log("  LoD2-Luecken: keine (alle OSM-/ALKIS-Gebaeude sind im LoD2 vorhanden)")
    for tx in texte:
        log("    + " + tx)
    if len(neue) > len(texte):
        log("    + ... %d weitere (siehe Eigenschaft 'Quelle' in der IFC)" % (len(neue) - len(texte)))
    log("  (%.1f s)" % (time.time() - t0))
    return len(neue)
