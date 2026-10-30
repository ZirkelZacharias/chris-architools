"""Werkzeug „CAD zu Lasercut“: einen 3D-Entwurf (IFC, OBJ, STL, 3MF, PLY, GLB, DXF mit 3D-Flächen) automatisch in ebene
Lasercut-Teile zerlegen, auf Platten legen und die Kosten schätzen.

Zerlegung (Modus):
  flaeche  jede ebene Fläche des Entwurfs wird ein Teil (ohne Laschen, zum Kleben auf Stoss)
  falt     wie „flaeche“, an Kanten zu Nachbarflächen aber mit Klebelasche und Ritzlinie (Faltkante)
  stapel   waagerechte Schichten in der Materialstärke (Schichtenmodell)
Leicht gekrümmte Flächen (Kuppeln, runde Gebäude) werden zu Streifen zusammengefasst, solange sie innerhalb von
`winkel` Grad und `ebenheit_mm` Millimetern eben sind; stärker gekrümmte Flächen zerfallen in mehrere Teile.

Alle Masse sind Modell-Millimeter (Entwurf / Massstab). Preise, Laserzeit und Plattenzahl sind SCHÄTZUNGEN (kosten.py).
"""
import csv
import math
import os
import re

import numpy as np
import shapely
import trimesh
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge

from . import bibliothek as BIB
from . import blatt as BL
from . import gebaeude_laser as GL
from . import kosten as KO
from .geomutil import lines, polys

STANDARD = {"dateien": [], "einheit": "m", "massstab": 200, "modus": "falt", "umwandlung": "massiv",
            "winkel": 3.0, "ebenheit_mm": 0.3, "min_flaeche_mm2": 20.0, "lasche_mm": 4.0, "beschriften": True,
            "anzahl": 1, "ausgabe_ordner": "", "name": "cad"}

MAX_PLATTEN_3D = 4000            # darüber wird die 3D-Vorschau aus den Originalflächen statt aus Platten gebaut
ART_NAME = {"W": "Wand", "D": "Dach/Decke", "B": "Boden", "S": "Schicht"}


# ------------------------------------------------------------------ Einlesen
def _dxf_3d(pfad, log):
    """3DFACE, MESH und POLYFACE einer DXF -> [(name, Trimesh)] in Zeichnungseinheiten"""
    import ezdxf
    doc = ezdxf.readfile(pfad)
    verts, faces = [], []

    def tri(pts):
        i0 = len(verts)
        verts.extend(pts)
        n = len(pts)
        if n >= 3:
            faces.extend([(i0, i0 + k, i0 + k + 1) for k in range(1, n - 1)])

    for e in doc.modelspace():
        t = e.dxftype()
        try:
            if t == "3DFACE":
                pts = [tuple(v) for v in e.wcs_vertices()]
                if len(pts) == 4 and np.allclose(pts[2], pts[3]):
                    pts = pts[:3]
                tri(pts)
            elif t == "MESH":
                vs = [tuple(v) for v in e.vertices]
                for f in e.faces:
                    tri([vs[i] for i in f])
            elif t == "POLYLINE" and e.is_poly_face_mesh:
                for f in e.indexed_faces():
                    tri([tuple(v.dxf.location) for v in f.points()] if hasattr(f, "points") else [])
        except Exception:
            continue
    if not faces:
        raise ValueError(f"{os.path.basename(pfad)}: keine 3D-Flächen (3DFACE, MESH) gefunden - in ArchiCAD als IFC speichern")
    m = trimesh.Trimesh(np.array(verts, float), np.array(faces, int), process=True)
    log(f"  DXF: {len(m.faces)} Dreiecke aus 3D-Flächen")
    return [("dxf", m)]


def laden(w, log=print):
    """-> [(name, Trimesh)] in Modell-mm (Entwurf / Massstab), ohne Verschiebung"""
    from . import druck as D
    f_mm = {"m": 1000.0, "cm": 10.0, "mm": 1.0}[w.get("einheit", "m")]
    massstab = float(w.get("massstab") or 1)
    out = []
    for p in w["dateien"]:
        low = p.lower()
        log(f"Lesen: {os.path.basename(p)}")
        if low.endswith(".ifc"):
            roh, f = D._laden_ifc(p, log), 1000.0 / massstab                 # IFC wird immer in Metern geliefert
        elif low.endswith(".dxf"):
            roh, f = _dxf_3d(p, log), f_mm / massstab
        else:
            roh, f = D._laden_trimesh(p), f_mm / massstab
        for name, m in roh:
            m = m.copy()
            m.apply_scale(f)
            out.append((name, m))
    if not out:
        raise ValueError("Keine 3D-Körper gefunden")
    return out


def vorbereiten(koerper, w, log=print):
    """Umwandlung: „massiv“ = Aussenform (alle Bauteile zusammen, ohne Innenräume), „original“ = jedes Bauteil für sich."""
    from . import druck as D
    if w.get("umwandlung", "massiv") == "massiv":
        ms = [m for _, m in koerper]
        gesamt = trimesh.util.concatenate(ms) if len(ms) > 1 else ms[0]
        try:
            m = D._massiv(gesamt)
        except Exception as e:
            log(f"  HINWEIS: Aussenform nicht berechenbar ({str(e)[:80]}) - Bauteile unverändert")
            m = None
        if m is not None and len(m.faces):
            log(f"  Aussenform: {len(gesamt.faces)} -> {len(m.faces)} Dreiecke (Innenräume und verdeckte Flächen entfallen)")
            return [("entwurf", m)]
        log("  HINWEIS: keine nach oben zeigenden Flächen - Bauteile unverändert verwendet")
    out = []
    for n, m in koerper:
        try:
            m = D._reparieren(m)
        except Exception:
            m = m.copy()
        if len(m.faces):
            out.append((n, m))
    log(f"  {len(out)} Bauteile einzeln zerlegt")
    return out


# ------------------------------------------------------------------ Flächen erkennen
def regionen(mesh, winkel, ebenheit):
    """Dreiecke zu ebenen Gebieten zusammenfassen. -> (Gebiets-Nr je Dreieck, Anzahl Gebiete)
    Ein Dreieck kommt zu einem Gebiet, wenn seine Normale höchstens `winkel` Grad von der des Ausgangsdreiecks abweicht und alle
    seine Ecken höchstens `ebenheit` mm von dessen Ebene entfernt liegen (so wächst eine Krümmung nicht unbemerkt weiter)."""
    F, V = mesh.faces, mesh.vertices
    n, A = mesh.face_normals, mesh.area_faces
    tri = V[F]
    nb = [[] for _ in range(len(F))]
    for a, b in mesh.face_adjacency:
        nb[a].append(b)
        nb[b].append(a)
    reg = np.full(len(F), -1, int)
    cosw = math.cos(math.radians(max(float(winkel), 0.01)))
    k = 0
    for s in np.argsort(-A):
        if reg[s] >= 0:
            continue
        reg[s] = k
        ns, p0 = n[s], tri[s][0]
        stack = [s]
        while stack:
            f = stack.pop()
            for g in nb[f]:
                if reg[g] >= 0 or n[g] @ ns < cosw:
                    continue
                if np.abs((tri[g] - p0) @ ns).max() > ebenheit:
                    continue
                reg[g] = k
                stack.append(g)
        k += 1
    return reg, k


def _basis(nm):
    """Ebenenachsen u, v zur Normalen: Wände stehen aufrecht (v zeigt nach oben), waagerechte Flächen: u = x"""
    if abs(nm[2]) > 0.99:
        u = np.array([1.0, 0.0, 0.0])
    else:
        u = np.cross([0.0, 0.0, 1.0], nm)
        u /= np.linalg.norm(u)
    v = np.cross(nm, u)
    return u, v


def _art(nm):
    if nm[2] > 0.5:
        return "D"
    if nm[2] < -0.5:
        return "B"
    return "W"


def _tabs(stuecke_poly, segmente2d, breite):
    """Klebelaschen und Ritzlinien an den Kanten (2D-Strecken) eines Teils -> (Teil mit Laschen, Ritzlinien)"""
    if not segmente2d:
        return stuecke_poly, []
    netz = shapely.union_all([LineString(s) for s in segmente2d if s[0] != s[1]])
    if netz.geom_type == "MultiLineString":
        netz = linemerge(netz)
    ls = lines(netz)
    ritz, laschen = [], []
    for l in ls:
        l = l.simplify(0.02)
        c = list(l.coords)
        for a, b in zip(c[:-1], c[1:]):
            if math.dist(a, b) < max(2.0, breite * 0.6):
                continue
            lash = GL._lasche(a, b, breite, stuecke_poly)
            if lash is None or lash.is_empty:
                continue
            laschen.append(lash.buffer(0.02, join_style=2))          # _lasche lässt 0,01 mm Spalt zum Teil: überbrücken
            ritz.append(LineString([a, b]))
    ps = polys(shapely.union_all([stuecke_poly] + laschen))
    if not ps:
        return stuecke_poly, []
    return max(ps, key=lambda p: p.area), ritz


def flaechen(mesh, w, log=print, zaehler=None, praefix=""):
    """Ebene Teile (modus flaeche/falt) eines Körpers. Teil: id, poly, ritzen, gravieren, art, layer; dazu für die 3D-Vorschau
    o, u, v, n (Lage der Teilebene im Modell)."""
    zaehler = zaehler if zaehler is not None else {}
    reg, nreg = regionen(mesh, w.get("winkel", 3.0), w.get("ebenheit_mm", 0.3))
    F, V = mesh.faces, mesh.vertices
    A, N = mesh.area_faces, mesh.face_normals
    tri = V[F]
    falt = w.get("modus") == "falt"
    breite = float(w.get("lasche_mm") or 4.0)
    min_fl = float(w.get("min_flaeche_mm2") or 0)
    # Kanten zwischen verschiedenen Gebieten: die Lasche sitzt am Gebiet mit der kleineren Nummer
    kanten = {}
    if falt:
        adj, ae = mesh.face_adjacency, mesh.face_adjacency_edges
        for (a, b), (e0, e1) in zip(adj, ae):
            if reg[a] != reg[b]:
                kanten.setdefault(min(reg[a], reg[b]), []).append((V[e0], V[e1]))
    reihenfolge = np.argsort([-A[reg == k].sum() for k in range(nreg)])
    teile, klein, krumm = [], 0, 0
    for k in reihenfolge:
        idx = np.where(reg == k)[0]
        if A[idx].sum() < min_fl:
            klein += 1
            continue
        nm = (N[idx] * A[idx][:, None]).sum(axis=0)
        if np.linalg.norm(nm) < 1e-9:
            continue
        nm /= np.linalg.norm(nm)
        u, v = _basis(nm)
        o = tri[idx[0]][0]
        P = np.einsum("fij,jk->fik", tri[idx] - o, np.c_[u, v])
        ring = np.concatenate([P, P[:, :1]], axis=1)
        pg = shapely.polygons(ring)
        pg = pg[shapely.area(pg) > 1e-9]
        if not len(pg):
            continue
        g = shapely.union_all(pg).buffer(0.02, join_style=2).buffer(-0.02, join_style=2).simplify(0.02)
        art = _art(nm)
        for piece in polys(g):
            if piece.area < min_fl:
                klein += 1
                continue
            segs = []
            for a3, b3 in kanten.get(k, []):
                s = [((a3 - o) @ u, (a3 - o) @ v), ((b3 - o) @ u, (b3 - o) @ v)]
                if piece.boundary.distance(Point(*s[0])) < 0.05 and piece.boundary.distance(Point(*s[1])) < 0.05:
                    segs.append(s)
            ritz, piece0 = [], piece
            if falt and segs:
                piece, ritz = _tabs(piece, segs, breite)
            zaehler[art] = zaehler.get(art, 0) + 1
            teile.append({"id": f"{praefix}{art}{zaehler[art]:03d}", "poly": piece, "poly0": piece0, "ritzen": ritz, "gravieren": [],
                          "art": ART_NAME[art], "layer": -1, "o": o, "u": u, "v": v, "n": nm, "flaeche_3d": float(A[idx].sum())})
    if klein:
        log(f"  {klein} Flächen unter {min_fl:g} mm² weggelassen")
    return teile


def schichten(mesh, t, w, log=print, praefix=""):
    """Waagerechte Schichten der Dicke t (Modus stapel): jede Schicht schneidet den Körper in halber Schichthöhe."""
    z0, z1 = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
    n = max(1, int(math.ceil((z1 - z0) / t - 1e-6)))
    if n > 400:
        raise ValueError(f"{n} Schichten bei {t:g} mm Stärke - zu viele; größeren Maßstab oder dickeres Material wählen")
    hs = [z0 + (k + 0.5) * t for k in range(n)]
    teile = []
    min_fl = float(w.get("min_flaeche_mm2") or 0)
    for k, h in enumerate(hs):
        try:
            sec = mesh.section(plane_origin=[0, 0, h], plane_normal=[0, 0, 1])
        except Exception:
            sec = None
        if sec is None:
            continue
        ringe = []                                     # Schnittlinien -> Flächen nach gerade/ungerade-Regel (Löcher bleiben Löcher)
        for pts in sec.discrete:
            if len(pts) >= 4:
                r = Polygon(pts[:, :2])
                if r.is_valid and r.area > 1e-6:
                    ringe.append(r)
        ringe.sort(key=lambda r: -r.area)
        flaeche = Polygon()
        for r in ringe:
            flaeche = flaeche.symmetric_difference(r)
        stuecke = polys(flaeche)
        for i, q in enumerate(stuecke, 1):
            if q.area < min_fl:
                continue
            teile.append({"id": f"{praefix}S{k + 1:02d}" + (f"-{i}" if len(stuecke) > 1 else ""),
                          "poly": q, "ritzen": [], "gravieren": [], "art": ART_NAME["S"], "layer": k, "z": z0 + k * t})
    return teile


# ------------------------------------------------------------------ 3D-Vorschau
def _platte_3d(t, dicke, versatz=(0, 0, 0)):
    try:
        if "o" in t:                                   # ebenes Teil: Platte liegt hinter der Aussenfläche des Entwurfs
            m = trimesh.creation.extrude_polygon(t["poly0"], dicke)
            T = np.eye(4)
            T[:3, 0], T[:3, 1], T[:3, 2], T[:3, 3] = t["u"], t["v"], t["n"], t["o"] - t["n"] * dicke
        else:                                          # Schicht
            m = trimesh.creation.extrude_polygon(t["poly"], dicke)
            T = np.eye(4)
            T[2, 3] = t["z"]
        m.apply_transform(T)
        if any(versatz):
            m.apply_translation(versatz)
        return m
    except Exception:
        return None


def vorschau(teile, dicke, ordner, name, log=print):
    """Zusammengebaut und auseinandergezogen als STL (Platten mit der echten Materialstärke). -> (zusammen, explosion)"""
    if not teile or len(teile) > MAX_PLATTEN_3D:
        if teile:
            log(f"  3D-Vorschau: {len(teile)} Teile - zu viele für die Vorschau, wird ausgelassen")
        return None, None
    mitte3 = np.mean([t["o"] if "o" in t else np.array([0, 0, t["z"]]) for t in teile], axis=0)
    zus, expl = [], []
    for t in teile:
        m = _platte_3d(t, dicke)
        if m is None:
            continue
        zus.append(m)
        c = m.centroid
        if "o" in t:
            d = (c - mitte3)
            L = np.linalg.norm(d)
            d = d / L * 0.35 * max(L, 1.0) if L > 1e-6 else d
        else:
            d = np.array([0, 0, t["layer"] * dicke * 1.5])
        e = m.copy()
        e.apply_translation(d)
        expl.append(e)
    if not zus:
        return None, None
    p1 = os.path.join(ordner, f"{name}_vorschau_laser.stl")
    p2 = os.path.join(ordner, f"{name}_vorschau_explosion.stl")
    trimesh.util.concatenate(zus).export(p1)
    trimesh.util.concatenate(expl).export(p2)
    return p1, p2


# ------------------------------------------------------------------ Gesamtablauf
def lasercut(w, cfg, log=print):
    """w: siehe STANDARD. cfg: Projekt-Einstellungen (laser: Material/Platte). -> Ergebnis-dict wie die anderen Werkzeuge"""
    from . import laser as LA
    from .pipeline import mm
    if not w.get("dateien"):
        raise ValueError("Keine Dateien angegeben")
    cfg = {**cfg, "massstab": float(w.get("massstab") or 1)}
    sorte, t, hinw = BIB.material(cfg)
    for h in hinw:
        log("  HINWEIS: " + h)
    formate = BIB.plattenformate(cfg)
    rand = float(cfg["laser"].get("rand_mm", BIB.WERKSTATT["rand_mm"]))
    modus = w.get("modus", "falt")
    # 1 Einlesen und Aussenform
    koerper = vorbereiten(laden(w, log), w, log)
    allm = trimesh.util.concatenate([m for _, m in koerper])
    lo = allm.bounds[0].copy()
    log(f"Entwurf im Modell: {allm.extents[0]:.0f} × {allm.extents[1]:.0f} × {allm.extents[2]:.0f} mm (1:{w.get('massstab'):g})")
    # 2 Zerlegen
    teile, zaehler = [], {}
    for i, (n, m) in enumerate(koerper):
        m = m.copy()
        m.apply_translation(-lo)
        pre = f"{i + 1}-" if len(koerper) > 1 else ""
        if modus == "stapel":
            teile += schichten(m, t, w, log, pre)
        else:
            teile += flaechen(m, w, log, zaehler, pre)
    if not teile:
        raise ValueError("Keine Laserteile entstanden - Entwurf leer oder alle Flächen kleiner als die Mindestfläche")
    teile_roh = list(teile)
    arten = {}
    for tl in teile:
        arten[tl["art"]] = arten.get(tl["art"], 0) + 1
    log("Zerlegt in " + str(len(teile)) + " Teile: " + ", ".join(f"{v} {k}" for k, v in arten.items()))
    if modus != "stapel":
        tri = sum(tl["flaeche_3d"] for tl in teile)
        log(f"  Flächen zusammen {tri / 1e6:.3f} m²" )
    # 3 Beschriften, zu große Teile kacheln, auf Platten legen
    if w.get("beschriften", True):
        for tl in teile:
            GL._beschriften(tl)
    teile = LA.tile_parts(teile, formate, rand, log, split_sparse=False)
    n = max(1, int(w.get("anzahl", 1) or 1))
    import copy
    alle = [copy.copy(tl) for _ in range(n) for tl in teile]
    meld = []
    for tl in alle:
        BL.bereinigen(tl, protokoll=meld)
    for m_ in meld[:8]:
        log("  " + m_)
    if len(alle) > 500:
        log(f"  HINWEIS: {len(alle)} Teile - das Anordnen auf den Platten dauert einige Minuten. Schneller: „Kleinste Fläche“ erhöhen, "
            "„Winkel“ vergrößern oder in den Einstellungen die Anordnung „schnell“ wählen.")
    platten, rest = BL.anordnen(alle, formate, cfg, log)
    # 4 Ausgabe
    out = os.path.abspath(w.get("ausgabe_ordner") or "ausgabe_cad")
    os.makedirs(out, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", w.get("name") or "cad")
    basis = f"{name}_{re.sub(r'[^A-Za-z0-9_.-]+', '_', sorte)}_{mm(t)}mm"
    titel = f"{w.get('name') or 'CAD'} – {sorte} {mm(t)} mm"
    pdfs = BL.pdfs_schreiben(out, basis, platten, titel, log)
    svgs = []
    for i, pl in enumerate(platten, 1):
        s = os.path.join(out, f"{name}_platte_{i:02d}.svg")
        BL.svg_schreiben(s, pl, titel=f"Platte {i}")
        svgs.append(s)
    dxf = os.path.join(out, f"{name}_platten.dxf")
    BL.dxf_schreiben(dxf, platten)
    with open(os.path.join(out, f"{name}_teileliste.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        cw = csv.writer(fh, delimiter=";")
        cw.writerow(["ID", "Art", "Platte", "Fläche mm²", "Breite mm", "Höhe mm"])
        for tl in alle:
            b = tl["poly"].bounds
            cw.writerow([tl["id"], tl.get("art", ""), tl.get("platte", "-"), f"{tl['poly'].area:.0f}",
                         f"{b[2] - b[0]:.1f}", f"{b[3] - b[1]:.1f}"])
    z_stat = vorschau(teile_roh, t, out, name, log)
    # 5 Kosten
    fl = sum(tl["poly"].area for pl in platten for tl in pl["teile"])
    zeit, z_lo, z_hi, zt = BL.laserzeit(platten, sorte, t)
    pm, mw = BIB.WERKSTATT["preis_min_netto"], BIB.WERKSTATT["mwst"]
    stats = {"modell_b": float(allm.extents[0]), "modell_h": float(allm.extents[1]), "teile_flaeche": fl,
             "gebaeude_modus": "druck", "n_druck": 0,
             "laser": {"s": zeit, "s_lo": z_lo, "s_hi": z_hi, "teile": zt, "netto": zeit / 60 * pm,
                       "netto_lo": z_lo / 60 * pm, "netto_hi": z_hi / 60 * pm, "preis_min": pm, "mwst": mw}}
    summe = {}
    kost = os.path.join(out, f"{name}_zuschnitt_und_kosten.txt")
    text = KO.schreiben(kost, cfg, stats, platten, [], [], summe=summe)
    gesamt = sum(p["format"][0] * p["format"][1] for p in platten)
    log(f"Fertig: {len(alle)} Teile auf {len(platten)} Platten, Ausnutzung {100 * fl / max(gesamt, 1):.0f} % · "
        f"geschätzt ca. {summe.get('brutto', 0):,.0f} € brutto · {out}".replace(",", "."))
    return {"ausgabe": out, "laser_ordner": out, "laser_pdfs": pdfs, "svgs": svgs, "platten": len(platten), "teile": len(alle),
            "n_rest": len(rest), "dxf": dxf, "kostenliste": kost, "kosten_text": text, "kosten": summe,
            "vorschau_laser": z_stat[0], "vorschau_explosion": z_stat[1], "material": f"{sorte} {mm(t)} mm",
            "material_farbe": BIB.farbe(sorte), "modell_b": stats["modell_b"], "modell_h": stats["modell_h"],
            "modell_z": float(allm.extents[2]), "laserzeit_min": zeit / 60}
