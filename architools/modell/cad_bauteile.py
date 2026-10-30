"""„CAD zu Lasercut“, Bauweise „Bauteile aus IFC“: das IFC kennt Wände, Decken, Dächer und Gelände - daraus werden Laserteile
in der echten Bauteilstärke.

  Wände, Decken, Böden, Dachflächen: als ebene Platten. Die Hauptfläche (Außenseite bzw. Oberseite) und die gegenüberliegende
      Fläche ergeben die echte Stärke; daraus werden Lagen in Materialstärke (Anzahl = Stärke / Materialstärke, gerundet, mind. 1).
      Jede Lage ist ein Schnitt durch das Bauteil parallel zur Hauptfläche - Öffnungen, Gehrungen und Stöße an den Ecken stimmen
      dadurch so, wie sie im CAD modelliert sind.
  Dach: wie oben, die Teile sind als „abnehmbar“ markiert (nicht mit den Wänden verkleben; in der Vorschau anhebbar).
  Gelände und Freiflächen (unebene Flächen: IfcSite, IfcGeographicElement, unebene Meshes): Höhenschichten in Materialstärke;
      unter den Gebäuden ausgespart.
  Material: der Name aus dem IFC wird je Teil mitgegeben; Zusatzmodule können daraus eine Rastergravur machen (Haken cad_material).

Alle Maße in Modell-mm (Entwurf / Maßstab). Für Laserteile gilt dieselbe Form wie in cad_lasercut (id, poly, ritzen, gravieren, art)
plus Lage im Modell für die 3D-Vorschau (o, u, v, n; Platte von s0 bis s0 + Materialstärke entlang n).
"""
import math

import numpy as np
import shapely
import trimesh
from shapely.geometry import Polygon

from .geomutil import lines, polys

GRUPPEN = {"wand": "Wände", "decke": "Decken und Böden", "dach": "Dach (abnehmbar)", "gelaende": "Gelände und Freiflächen",
           "sonst": "Sonstige Bauteile"}
KUERZEL = {"wand": "W", "decke": "D", "dach": "R", "gelaende": "G", "sonst": "X"}
OHNE = ("IfcOpeningElement", "IfcSpace", "IfcWindow", "IfcDoor", "IfcFurnishingElement", "IfcAnnotation", "IfcGrid",
        "IfcVirtualElement", "IfcDistributionElement", "IfcFlowTerminal", "IfcZone")
MAX_LAGEN = 60


# ------------------------------------------------------------------ Einlesen
def _material(el):
    try:
        import ifcopenshell.util.element as UE
        m = UE.get_material(el, should_skip_usage=True)
    except Exception:
        m = None
    if m is None:
        return ""
    if m.is_a("IfcMaterial"):
        return m.Name or ""
    if m.is_a("IfcMaterialLayerSet"):
        ls = [l for l in (m.MaterialLayers or []) if l.Material]
        if not ls:
            return ""
        # Außenseite: die erste Schicht, die keine Dämmung/Luft ist, von außen gezählt (Archicad: Schichtfolge von außen)
        for l in ls:
            if not any(w in (l.Material.Name or "").lower() for w in ("dämm", "daemm", "insul", "luft", "air")):
                return l.Material.Name or ""
        return ls[0].Material.Name or ""
    for att in ("Materials",):
        if hasattr(m, att) and getattr(m, att):
            return getattr(m, att)[0].Name or ""
    if m.is_a("IfcMaterialConstituentSet") and m.MaterialConstituents:
        c = m.MaterialConstituents[0]
        return (c.Material.Name if c.Material else "") or ""
    return getattr(m, "Name", "") or ""


def _im_dach(el):
    try:
        import ifcopenshell.util.element as UE
        p = UE.get_aggregate(el)
        return p is not None and p.is_a("IfcRoof")
    except Exception:
        return False


def laden(pfade, massstab, log=print):
    """IFC -> [dict(name, klasse, typ, material, im_dach, mesh (Modell-mm))]"""
    import ifcopenshell
    import ifcopenshell.geom
    f_mm = 1000.0 / float(massstab)
    out = []
    for pfad in pfade:
        f = ifcopenshell.open(pfad)
        st = ifcopenshell.geom.settings()
        st.set("use-world-coords", True)
        prod = [e for e in f.by_type("IfcProduct") if e.Representation is not None and not any(e.is_a(k) for k in OHNE)]
        if not prod:
            continue
        it = ifcopenshell.geom.iterator(st, f, include=prod)
        if not it.initialize():
            continue
        while True:
            sh = it.get()
            el = f.by_id(sh.id)
            v = np.array(sh.geometry.verts, float).reshape(-1, 3) * f_mm
            fc = np.array(sh.geometry.faces, int).reshape(-1, 3)
            if len(fc):
                out.append({"name": el.Name or el.GlobalId, "klasse": el.is_a(), "typ": str(getattr(el, "PredefinedType", "") or ""),
                            "material": _material(el), "im_dach": _im_dach(el),
                            "mesh": trimesh.Trimesh(v, fc, process=True)})
            if not it.next():
                break
    log(f"  IFC: {len(out)} Bauteile mit Geometrie gelesen (Öffnungen, Räume, Fenster, Türen und Möbel ausgelassen)")
    return out


# ------------------------------------------------------------------ Einordnen
def _oben_flaechig(m):
    """Anteil der nach oben zeigenden Fläche und ob die Oberseite eben ist (eine Ebene)"""
    A, N = m.area_faces, m.face_normals
    oben = N[:, 2] > 0.2
    if not oben.any():
        return 0.0, True
    nz, Ao = N[oben], A[oben]
    haupt = nz[np.argmax(Ao)]                                        # Normale der größten Fläche
    in_ebene = (nz @ haupt) > math.cos(math.radians(3))
    eben = float(Ao[in_ebene].sum() / Ao.sum()) > 0.9                # 90 % der Oberseite in einer Ebene (Stirnflächen zählen nicht)
    return float(Ao.sum() / A.sum()), eben


def einordnen(b):
    """-> 'wand' | 'decke' | 'dach' | 'gelaende' | 'sonst'"""
    k, typ, m = b["klasse"], (b["typ"] or "").upper(), b["mesh"]
    if k in ("IfcSite", "IfcGeographicElement"):
        return "gelaende"
    if k == "IfcRoof" or b["im_dach"] or typ == "ROOF" or (k == "IfcCovering" and typ == "ROOFING"):
        return "dach"
    anteil, eben = _oben_flaechig(m)
    offen = not m.is_watertight
    if (offen and anteil > 0.6) or (k in ("IfcBuildingElementProxy", "IfcSlab", "IfcCovering") and not eben and anteil > 0.3
                                   and m.extents[2] < 0.5 * max(m.extents[0], m.extents[1])):
        return "gelaende"                                   # unebene oder offene Fläche: Mesh (Gelände, Weg, Platz, Böschung)
    if k.startswith("IfcWall") or k in ("IfcCurtainWall", "IfcPlate", "IfcMember"):
        return "wand"
    if k in ("IfcSlab", "IfcCovering"):
        return "decke"
    return "sonst"


# ------------------------------------------------------------------ Platten
def _basis(n):
    if abs(n[2]) > 0.99:
        u = np.array([1.0, 0.0, 0.0])
    else:
        u = np.cross([0.0, 0.0, 1.0], n)
        u /= np.linalg.norm(u)
    v = np.cross(n, u)
    return u, v


def _flaechen(m, winkel=3.0, ebenheit=0.3):
    """Ebene Gebiete: [(Normale, Abstand d = n·p, Fläche, Dreiecks-Indizes)], größte zuerst"""
    from .cad_lasercut import regionen
    reg, nreg = regionen(m, winkel, ebenheit)
    A, N, V, F = m.area_faces, m.face_normals, m.vertices, m.faces
    out = []
    for k in range(nreg):
        idx = np.where(reg == k)[0]
        a = float(A[idx].sum())
        n = (N[idx] * A[idx][:, None]).sum(0)
        if np.linalg.norm(n) < 1e-9:
            continue
        n /= np.linalg.norm(n)
        d = float(np.average(V[F[idx]].mean(1) @ n, weights=A[idx]))
        out.append((n, d, a, idx))
    out.sort(key=lambda t: -t[2])
    return out


def _schnitt(m, n, s, u, v):
    """Schnitt des Körpers mit der Ebene n·p = s -> Polygon in (u, v) (gerade/ungerade-Regel: Öffnungen bleiben Löcher)"""
    try:
        sec = m.section(plane_origin=n * s, plane_normal=n)
    except Exception:
        sec = None
    if sec is None:
        return Polygon()
    ringe = []
    for pts in sec.discrete:
        if len(pts) >= 4:
            P = np.c_[pts @ u, pts @ v]
            r = Polygon(P)
            if not r.is_valid:
                r = r.buffer(0)
            if not r.is_empty and r.area > 1e-6:
                ringe += polys(r)
    ringe.sort(key=lambda r: -r.area)
    g = Polygon()
    for r in ringe:
        g = g.symmetric_difference(r)
    return g.buffer(0)


def platten(b, gruppe, t, mitte_xy, log, min_fl=2.0):
    """Ebene Platten eines Bauteils (Wand, Decke, Dachfläche, Sonstiges) in Lagen der Materialstärke t -> [Teil]"""
    m = b["mesh"]
    fl = _flaechen(m)
    if not fl:
        return []
    groesste = fl[0][2]
    haupt = [f for f in fl if f[2] >= 0.12 * groesste]
    benutzt, teile = set(), []
    for i, (n, d, a, idx) in enumerate(haupt):
        if i in benutzt:
            continue
        # Gegenfläche: parallel, entgegengesetzt
        gegen = [j for j, g in enumerate(haupt) if j != i and j not in benutzt and float(g[0] @ n) < -0.985]
        j = min(gegen, key=lambda j: abs(-haupt[j][1] - d)) if gegen else None
        benutzt.add(i)
        if j is not None:
            benutzt.add(j)
            # nur ein dünnes Paar ist eine Platte (Wandflächen, Deckenober-/unterseite) - Ober- und Unterkante einer Wand nicht
            if abs(d + haupt[j][1]) > 0.35 * math.sqrt(a):
                continue
        elif teile:
            continue                                            # einzelne Restflächen nach der Hauptplatte: keine eigene Platte
        # Außenseite wählen: Wände weg von der Gebäudemitte, sonst nach oben
        if j is not None:
            nj, dj = haupt[j][0], haupt[j][1]
            if gruppe == "wand":
                c = m.vertices[m.faces[idx]].reshape(-1, 3).mean(0)
                aussen = float((c[:2] - mitte_xy) @ n[:2]) >= 0
            else:
                aussen = n[2] >= nj[2]
            if not aussen:
                n, d, nj, dj, idx = nj, dj, n, d, haupt[j][3]
            dicke = d + dj                                          # n·p = d außen, (-n)·p = dj innen -> innen bei n·p = -dj
        else:
            if gruppe == "wand" and float((m.vertices[m.faces[idx]].reshape(-1, 3).mean(0)[:2] - mitte_xy) @ n[:2]) < 0:
                n, d = -n, -d
            P = m.vertices @ n
            dicke = max(t, float(d - P.min()))
        dicke = max(dicke, 1e-3)
        k = int(max(1, round(dicke / t)))
        if k > MAX_LAGEN:
            log(f"  HINWEIS: {b['name']}: {k} Lagen bei {t:g} mm Material - auf {MAX_LAGEN} begrenzt (dickeres Material wählen)")
            k = MAX_LAGEN
        u, v = _basis(n)
        s_innen, s_aussen = d - dicke, d
        mitte_s = (s_innen + s_aussen) / 2.0
        # bei mehreren Hauptflächen (z. B. Satteldach als ein Bauteil): Schnitt auf das Gebiet dieser Fläche begrenzen
        grenze = None
        if len(haupt) > 2:
            tri = m.vertices[m.faces[idx]]
            P2 = np.einsum("fij,jk->fik", tri, np.c_[u, v])
            grenze = shapely.union_all(shapely.polygons(np.concatenate([P2, P2[:, :1]], axis=1))).buffer(dicke * 1.5 + 0.5)
        for lage in range(k):
            s0 = mitte_s - k * t / 2.0 + lage * t                     # Platte von s0 bis s0 + t (Lagen um die Wandmitte)
            s_schnitt = min(max(s0 + t / 2.0, s_innen + 0.02), s_aussen - 0.02) if dicke > 0.05 else d - dicke / 2
            g = _schnitt(m, n, s_schnitt, u, v)
            if grenze is not None:
                g = g.intersection(grenze)
            for st, q in enumerate([q for q in polys(g) if q.area >= min_fl]):
                teile.append({"poly": q, "poly0": q, "ritzen": [], "gravieren": [], "gruppe": gruppe, "material": b["material"],
                              "element": b["name"], "lage": lage + 1, "lagen": k, "aussen": lage == k - 1,
                              "u": u, "v": v, "n": n, "s0": s0, "dicke_real": dicke})
    return teile


# ------------------------------------------------------------------ Gelände
def _ueber(tri, h):
    """Teil eines 3D-Dreiecks mit z >= h als 2D-Polygon (xy) oder None"""
    z = tri[:, 2]
    if z.min() >= h:
        return tri[:, :2]
    if z.max() < h:
        return None
    out = []
    for i in range(3):
        a, b_ = tri[i], tri[(i + 1) % 3]
        if a[2] >= h:
            out.append(a[:2])
        if (a[2] >= h) != (b_[2] >= h):
            r = (h - a[2]) / (b_[2] - a[2])
            out.append((a + (b_ - a) * r)[:2])
    return np.array(out) if len(out) >= 3 else None


def _bereich_ueber(tris, h):
    ps = []
    ganz = tris[:, :, 2].min(1) >= h
    if ganz.any():
        T = tris[ganz][:, :, :2]
        ps.append(shapely.polygons(np.concatenate([T, T[:, :1]], axis=1)))
    for tri in tris[~ganz & (tris[:, :, 2].max(1) >= h)]:
        p = _ueber(tri, h)
        if p is not None:
            ps.append(np.array([Polygon(p)], dtype=object))
    if not ps:
        return Polygon()
    a = np.concatenate(ps)
    a = a[shapely.area(a) > 1e-8]
    return shapely.union_all(a).buffer(0.01, join_style=2).buffer(-0.01, join_style=2) if len(a) else Polygon()


def gelaende(bauteile, t, aussparen, log, min_fl=2.0):
    """Gelände und Freiflächen als Höhenschichten. bauteile: Liste dict wie aus laden (nur Gelände). aussparen: [(xy-Polygon, z_unten)]
    -> [Teil] (Teil hat zusätzlich 'bereiche' = [(Material, Polygon des Sichtbaren)] für die Materialdarstellung)"""
    if not bauteile:
        return []
    tri_all, oben = [], []
    for b in bauteile:
        m = b["mesh"]
        idx = m.face_normals[:, 2] > 0.05 if m.is_watertight else np.abs(m.face_normals[:, 2]) > 0.05
        tri = m.vertices[m.faces[idx]]
        if not len(tri):
            continue
        tri_all.append(tri)
        T = tri[:, :, :2]
        a = shapely.polygons(np.concatenate([T, T[:, :1]], axis=1))
        flaeche = shapely.union_all(a[shapely.area(a) > 1e-8]).buffer(0.01, join_style=2).buffer(-0.01, join_style=2)
        oben.append((float(tri[:, :, 2].mean()), b["material"] or "Gelände", flaeche))
    if not tri_all:
        return []
    tris = np.concatenate(tri_all)
    z0 = float(tris[:, :, 2].min())
    z1 = float(tris[:, :, 2].max())
    n = int(math.floor((z1 - z0) / t)) + 1
    if n > 200:
        log(f"  HINWEIS: Gelände ergäbe {n} Schichten - auf 200 begrenzt")
        n = 200
    # Material je Ort: das höher liegende Bauteil gewinnt (z. B. Weg über dem Rasen)
    oben.sort(key=lambda x: x[0])
    mat_bereiche = []
    for i, (zm, mat, g) in enumerate(oben):
        for zm2, mat2, g2 in oben[i + 1:]:
            g = g.difference(g2)
        if not g.is_empty:
            mat_bereiche.append((mat, g))
    schichten = [_bereich_ueber(tris, z0 + k * t) if k else shapely.union_all([g for _, _, g in oben]) for k in range(n)]
    schichten.append(Polygon())
    teile, n_aus = [], 0
    for k in range(n):
        g = schichten[k]
        h = z0 + k * t
        for xy, zu in aussparen:                        # Gebäude stehen auf ihrer Unterkante: Gelände darüber aussparen
            if zu < h - 1e-6:
                g2 = g.difference(xy)
                if g2.area < g.area - 0.01:
                    n_aus += 1
                g = g2
        sichtbar = g.difference(schichten[k + 1])
        for q in [q for q in polys(g) if q.area >= min_fl]:
            br = [(mat, q.intersection(sichtbar).intersection(mg)) for mat, mg in mat_bereiche]
            teile.append({"poly": q, "poly0": q, "ritzen": [], "gravieren": [], "gruppe": "gelaende", "material": "", "element": "Gelände",
                          "lage": k + 1, "lagen": n, "aussen": True, "u": np.array([1.0, 0, 0]), "v": np.array([0, 1.0, 0]),
                          "n": np.array([0, 0, 1.0]), "s0": h - t, "bereiche": [(m_, b_) for m_, b_ in br if not b_.is_empty],
                          "verdeckt": q.intersection(schichten[k + 1]) if not schichten[k + 1].is_empty else None})
    # Ritzlinie: Umriss der nächsthöheren Schicht als Anlegekante
    for tl in teile:
        k = tl["lage"]
        if k < n and not schichten[k].is_empty:
            kante = schichten[k].boundary.intersection(tl["poly"])
            if not kante.is_empty:
                tl["ritzen"] += [l for l in lines(kante) if l.length > 0.3]
    log(f"  Gelände: {len(bauteile)} Fläche(n), {z0 * 1:.1f}–{z1:.1f} mm hoch -> {n} Schichten à {t:g} mm"
        + (", Gebäude ausgespart" if n_aus else ""))
    return teile


# ------------------------------------------------------------------ Gesamt
def einlesen(pfade, massstab, log=print):
    """IFC-Dateien lesen, Ursprung an die untere Ecke, Bauteile einordnen -> (Bauteile, Zusammenfassung)"""
    bt = laden(pfade, massstab, log)
    if not bt:
        raise ValueError("Im IFC wurden keine Bauteile mit Geometrie gefunden")
    allm = trimesh.util.concatenate([b["mesh"] for b in bt])
    lo = allm.bounds[0].copy()
    for b in bt:                                                     # Ursprung an die untere Ecke (kleine Zahlen)
        b["mesh"].apply_translation(-lo)
        b["gruppe"] = einordnen(b)
    zahl = {}
    for b in bt:
        zahl[b["gruppe"]] = zahl.get(b["gruppe"], 0) + 1
    log("  Bauteile: " + ", ".join(f"{GRUPPEN[g]} {zahl[g]}" for g in GRUPPEN if g in zahl))
    mats = {}
    for b in bt:
        if b["material"]:
            mats.setdefault(b["gruppe"], set()).add(b["material"])
    zus = {"gruppen": zahl, "materialien": sorted({b["material"] for b in bt if b["material"]}), "ursprung": lo,
           "groesse": allm.extents, "materialien_je_gruppe": {g: sorted(v) for g, v in mats.items()}}
    return bt, zus


def zerlegen(pfade, massstab, t, log=print, gruppen_an=None, min_fl=2.0, bauteile=None):
    """IFC-Dateien (oder schon eingelesene Bauteile) -> (Teile, Zusammenfassung) in Modell-mm. Die Teile tragen ihre Lage im Modell
    (u, v, n, s0). gruppen_an: nur diese Bauteilgruppen zerlegen (die Gebäude werden trotzdem aus dem Gelände ausgespart)."""
    if bauteile is None:
        bt, zus = einlesen(pfade, massstab, log)
    else:
        bt, zus = bauteile
    an = set(gruppen_an or GRUPPEN)
    geb = [b for b in bt if b["gruppe"] in ("wand", "decke", "dach", "sonst")]
    mitte_xy = trimesh.util.concatenate([b["mesh"] for b in geb]).centroid[:2] if geb else np.zeros(2)
    teile = []
    for b in geb:
        if b["gruppe"] not in an:
            continue
        try:
            teile += platten(b, b["gruppe"], t, mitte_xy, log, min_fl)
        except Exception as e:
            log(f"  HINWEIS: {b['klasse']} „{b['name']}“ nicht zerlegt ({str(e)[:80]})")
    # Aussparung fürs Gelände: Grundriss der Gebäude-Bauteile mit ihrer Unterkante
    aussparen = []
    for b in geb:
        if b["gruppe"] in ("wand", "decke"):
            m = b["mesh"]
            T = m.vertices[m.faces][:, :, :2]
            a = shapely.polygons(np.concatenate([T, T[:, :1]], axis=1))
            g = shapely.union_all(a[shapely.area(a) > 1e-8])
            if not g.is_empty:
                aussparen.append((g.buffer(0.05), float(m.bounds[0][2])))
    if aussparen:                                                    # zusammenfassen: ein Umriss je Unterkante (schneller)
        zs = {}
        for g, z in aussparen:
            zs.setdefault(round(z, 1), []).append(g)
        aussparen = [(shapely.union_all(gs), z) for z, gs in zs.items()]
    if "gelaende" in an:
        teile += gelaende([b for b in bt if b["gruppe"] == "gelaende"], t, aussparen, log, min_fl)
    # Nummern: je Gruppe fortlaufend, Lage angehängt (W03-2 = Wand 3, Lage 2 von außen gezählt nach innen ... )
    nr, el_nr = {}, {}
    for tl in teile:
        g = tl["gruppe"]
        key = (g, tl["element"]) if g != "gelaende" else (g, tl["lage"])
        if key not in el_nr:
            nr[g] = nr.get(g, 0) + 1
            el_nr[key] = nr[g]
        tl["id"] = f"{KUERZEL[g]}{el_nr[key]:02d}" + (f"-{tl['lage']}" if tl["lagen"] > 1 and g != "gelaende" else "")
        tl["art"] = GRUPPEN[g].split(" (")[0]
        tl["layer"] = -1
        tl["o"] = tl["n"] * (tl["s0"] + t)                         # für cad_lasercut._platte_3d: Platte endet bei o (außen)
    lagen = {}
    for tl in teile:
        if tl["gruppe"] != "gelaende":
            lagen.setdefault(tl["gruppe"], set()).add(tl["lagen"])
    for g, ls in lagen.items():
        log(f"  {GRUPPEN[g]}: {sum(1 for tl in teile if tl['gruppe'] == g)} Teile, Lagen je Bauteil {', '.join(str(x) for x in sorted(ls))}"
            f" (echte Stärke / {t:g} mm, gerundet)")
    return teile, zus
