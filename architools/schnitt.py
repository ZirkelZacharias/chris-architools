"""Geländeschnitt: Profil durch Gelände und Gebäude entlang einer Linie (SVG, DXF, PNG)."""
import copy
import math
import os

import numpy as np


def linie(p):
    """Schnittlinie [[E, N], [E, N]] aus den Einstellungen; ohne eigene Linie quer durch die Mitte."""
    s = p["schnitt"]
    if s.get("linie_en") and len(s["linie_en"]) == 2:
        (x0, y0), (x1, y1) = s["linie_en"]
        return (float(x0), float(y0)), (float(x1), float(y1))
    e, n = p["gebiet"]["mitte_en"]
    r = float(s.get("laenge_m") or 200.0) / 2
    a = math.radians(float(s.get("richtung_grad") or 0))
    return (e - r * math.cos(a), n - r * math.sin(a)), (e + r * math.cos(a), n + r * math.sin(a))


def ansicht_einst(p):
    """(an?, Tiefe m, Seite 'links'|'rechts', Bäume markieren?) für die Ansicht der dahinterliegenden Gebäude"""
    s = p["schnitt"]
    an = bool(s.get("ansicht", True))
    tiefe = float(s.get("tiefe_m") or 0) or 100.0
    seite = s.get("seite") or "links"
    return an, tiefe, ("rechts" if seite == "rechts" else "links"), bool(s.get("baeume", True))


def _normale(a, b, seite):
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    d = np.array([(b[0] - a[0]) / L, (b[1] - a[1]) / L])
    n = np.array([-d[1], d[0]]) * (1.0 if seite == "links" else -1.0)
    return d, n


def szene_fuer_linie(p, a, b, log):
    """Daten nur für einen Streifen um die Linie laden (über die Modellbau-Datenwege); mit Ansicht: auf der Blickseite bis zur Tiefe."""
    from .modell import pipeline
    cfg = copy.deepcopy(p["modell"])
    pad = 25.0
    an, tiefe, seite, _ = ansicht_einst(p)
    xs, ys = [a[0], b[0]], [a[1], b[1]]
    if an:
        d, n = _normale(a, b, seite)
        for q in (a, b):
            xs.append(q[0] + n[0] * tiefe)
            ys.append(q[1] + n[1] * tiefe)
    x0, x1 = min(xs) - pad, max(xs) + pad
    y0, y1 = min(ys) - pad, max(ys) + pad
    cfg["massstab"] = 1000
    cfg["gebiet"] = {"mitte_en": [(x0 + x1) / 2, (y0 + y1) / 2], "drehung_grad": 0.0,
                     "breite_cm": (x1 - x0) * 100 / 1000.0, "hoehe_cm": (y1 - y0) * 100 / 1000.0}
    cfg["_basis"] = p["ordner"]
    u = p.get("umgebung", {})
    cfg["netz"] = {"cafile": u.get("cafile", "") or "", "unsicher": bool(u.get("unsicher", False))}
    return pipeline.szene_laden(cfg, log)


def profil(szene, a, b, abstand=0.5):
    """Stationen entlang der Linie: s, Geländehöhe, je Gebäude die Dachhöhe (NaN = nicht geschnitten)."""
    from scipy.interpolate import RegularGridInterpolator
    import shapely
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    n = max(2, int(L / abstand) + 1)
    s = np.linspace(0, L, n)
    x = a[0] + (b[0] - a[0]) * s / L
    y = a[1] + (b[1] - a[1]) * s / L
    g = szene["dgm"]
    f = RegularGridInterpolator((g["y"], g["x"]), g["z"], bounds_error=False, fill_value=None)
    zg = f(np.column_stack([y, x]))
    bauten = []
    for geb in szene.get("gebaeude") or []:
        zr = np.full(n, np.nan)
        for ext, holes in geb.get("roofs") or []:
            ext = np.asarray(ext, float)
            if len(ext) < 3:
                continue
            try:
                poly = shapely.Polygon(ext[:, :2], [np.asarray(h)[:, :2] for h in holes])
                if not poly.is_valid or poly.is_empty:
                    poly = poly.buffer(0)
                m = shapely.contains_xy(poly, x, y)
            except Exception:
                continue
            if not m.any():
                continue
            A = np.column_stack([ext[:, 0], ext[:, 1], np.ones(len(ext))])
            coef, *_ = np.linalg.lstsq(A, ext[:, 2], rcond=None)
            z = coef[0] * x[m] + coef[1] * y[m] + coef[2]
            zr[m] = np.fmax(zr[m], z) if np.isfinite(zr[m]).any() else z
        if np.isfinite(zr).any():
            bauten.append({"id": geb.get("id"), "zr": zr, "zmin": geb.get("zmin")})
    pr = {"s": s, "x": x, "y": y, "zg": zg, "bauten": bauten, "laenge": L, "hinten": None, "baeume": []}
    return pr


def ansicht_dahinter(szene, a, b, an, tiefe, seite, baeume_zeigen, abstand=2.0):
    """Ansicht (senkrechte Projektion auf die Schnittebene) der Gebäude und Bäume HINTER der Linie bis zur Tiefe.
    -> dict(gebaeude=[dict(poly (s,z), u)], baeume=[dict(s, z, ho, kr, schnitt)], zg_hinten=Array bei s)"""
    from scipy.interpolate import RegularGridInterpolator
    from shapely.geometry import MultiPoint, box
    from shapely.ops import unary_union
    if not an:
        return {"gebaeude": [], "baeume": [], "zg_hinten": None}
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    d, n = _normale(a, b, seite)
    a_ = np.asarray(a, float)
    gl = szene["dgm"]
    f = RegularGridInterpolator((gl["y"], gl["x"]), gl["z"], bounds_error=False, fill_value=None)
    st = np.linspace(0, L, max(2, int(L / abstand) + 1))
    # Gelaende hinter der Linie: hoechster Wert je Station ueber alle Abstaende (Silhouette)
    zh = np.full(len(st), -np.inf)
    for off in np.arange(abstand * 2, tiefe + 0.1, 5.0):
        xy = a_[None, :] + np.outer(st, d) + n[None, :] * off
        z = f(np.column_stack([xy[:, 1], xy[:, 0]]))
        zh = np.fmax(zh, np.where(np.isfinite(z), z, -np.inf))
    zh = np.where(np.isfinite(zh), zh, np.nan)
    geb = []
    for g in szene.get("gebaeude") or []:
        roofs = [np.asarray(e, float) for e, _ in (g.get("roofs") or []) if len(e) >= 3]
        gr = [np.asarray(e, float) for e, _ in (g.get("grounds") or []) if len(e) >= 3]
        ref_l = gr or roofs
        if not ref_l:
            continue
        ref = np.vstack([e[:, :2] for e in ref_l])
        u = (ref - a_) @ n
        sx = (ref - a_) @ d
        if u.max() <= 0.2 or u.min() > tiefe or sx.max() < 0 or sx.min() > L:
            continue
        zb = float(g.get("zmin", 0.0))
        polys = []
        if roofs:
            for ext in roofs:
                sp = (ext[:, :2] - a_) @ d
                pts = np.column_stack([np.r_[sp, sp], np.r_[ext[:, 2], np.full(len(sp), zb)]])
                try:
                    polys.append(MultiPoint(pts).convex_hull)
                except Exception:
                    pass
        else:
            polys.append(box(sx.min(), zb, sx.max(), float(g.get("zmax", zb))))
        polys = [q for q in polys if q.geom_type == "Polygon" and q.area > 1e-6]
        if not polys:
            continue
        sil = unary_union(polys).intersection(box(0, -1e4, L, 1e4))
        if not sil.is_empty:
            geb.append({"poly": sil, "u": float(max(0.0, u.min())), "id": g.get("id")})
    geb.sort(key=lambda t: -t["u"])
    bm = []
    if baeume_zeigen:
        for (x, y, kr, ho) in _baeume_der_szene(szene):
            q = np.array([x, y]) - a_
            sx, u = float(q @ d), float(q @ n)
            kr = max(float(kr), 2.0)
            if u < -kr / 2 or u > tiefe or sx < -kr / 2 or sx > L + kr / 2:
                continue
            z = float(f([[y, x]])[0])
            if not np.isfinite(z):
                continue
            bm.append({"s": sx, "z": z, "ho": max(float(ho), 2.0), "kr": kr, "schnitt": abs(u) <= kr / 2, "u": u})
        bm.sort(key=lambda t: -t["u"])
    return {"gebaeude": geb, "baeume": bm, "zg_hinten": (st, zh)}


def _baeume_der_szene(szene):
    """Bäume aus der Szene: aus den Geodaten (sz['baeume']) oder - bei eigenen Dateien - aus der Ebene 'Bäume' (Hoehe/Krone aus den Attributen, sonst 10 m / 6 m)"""
    if szene.get("baeume"):
        return list(szene["baeume"])
    out = []
    for e in szene.get("ebenen") or []:
        if "baum" not in str(e.get("name", "")).lower().replace("ä", "a"):
            continue
        for g, props in e.get("items") or []:
            pts = list(getattr(g, "geoms", [g]))
            ho = kr = None
            for k, v in (props or {}).items():
                try:
                    x = float(str(v).replace(",", "."))
                except (TypeError, ValueError):
                    continue
                kl = str(k).lower()
                if x > 0 and ("hoehe" in kl.replace("ö", "oe") or "height" in kl):
                    ho = x
                if x > 0 and ("krone" in kl or "crown" in kl):
                    kr = x
            for q in pts:
                if q.geom_type == "Point":
                    out.append((q.x, q.y, kr or 6.0, ho or 10.0))
    return out


def _krone(t, ue, zbasis, n=28):
    """Kronenellipse als Punktliste (s, z) - Hoehen ueberhoeht gemaess ue (nur fuer die Zeichnung)"""
    zc = t["z"] + 0.65 * t["ho"]
    rv, rh = 0.35 * t["ho"], t["kr"] / 2
    return [(t["s"] + rh * math.cos(w), zc + rv * math.sin(w)) for w in np.linspace(0, 2 * math.pi, n, endpoint=False)]


def _laeufe(zr):
    m = np.isfinite(zr)
    i = 0
    while i < len(m):
        if m[i]:
            j = i
            while j + 1 < len(m) and m[j + 1]:
                j += 1
            yield i, j
            i = j + 1
        else:
            i += 1


def zeichnen(pr, p, ordner, name="Schnitt", log=print):
    """Schreibt SVG (mit Maßstab), DXF (1:1 in Metern) und eine PNG-Vorschau."""
    sc = p["schnitt"]
    M = float(sc.get("massstab") or 500)
    ue = 1.0                                            # der Schnitt wird nie überhöht (Wunsch 12:47)
    os.makedirs(ordner, exist_ok=True)
    s, zg = pr["s"], pr["zg"]
    zbasis = math.floor(np.nanmin(zg) - 2.0)
    zmax = float(np.nanmax(zg))
    gebaeude = []
    if sc.get("gebaeude", True):
        for b in pr["bauten"]:
            for i, j in _laeufe(b["zr"]):
                top = [(s[k], b["zr"][k]) for k in range(i, j + 1)]
                bot = [(s[k], zg[k]) for k in range(j, i - 1, -1)]
                gebaeude.append(top + bot)
                zmax = max(zmax, max(z for _, z in top))
    # Ansicht dahinter: Gebaeude-Silhouetten, Bäume, Gelaende
    from shapely.geometry import box as _box
    hin = pr.get("hinten") or {}
    dah = []
    for g in hin.get("gebaeude", []):
        q = g["poly"].intersection(_box(0, zbasis, pr["laenge"], 1e4))
        if not q.is_empty:
            dah.append(q)
            zmax = max(zmax, q.bounds[3])
    baeume = hin.get("baeume", [])
    for t in baeume:
        zmax = max(zmax, t["z"] + t["ho"])
    zh = hin.get("zg_hinten")
    seite_txt = "links" if (sc.get("seite") or "links") != "rechts" else "rechts"

    def ringe(q):
        return [list(pg.exterior.coords) for pg in getattr(q, "geoms", [q]) if pg.geom_type == "Polygon" and not pg.is_empty]
    hoehe = (zmax - zbasis) * ue
    teile = []
    # ---------- SVG (mm auf dem Papier im Maßstab 1:M)
    k = 1000.0 / M
    rand = 12.0
    W = pr["laenge"] * k + 2 * rand
    H = hoehe * k + 2 * rand + 8
    X = lambda v: rand + v * k
    Y = lambda z: rand + 4 + (zmax - z) * ue * k
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.2f}mm" height="{H:.2f}mm" viewBox="0 0 {W:.2f} {H:.2f}">',
           '<rect width="100%" height="100%" fill="white"/>']
    svg.append('<g id="HINTERGRUND">')                                  # Ansicht dahinter: eigene Ebene
    if zh is not None and np.isfinite(zh[1]).any():                      # Gelaende dahinter (Silhouette)
        st_, zh_ = zh
        ok = np.isfinite(zh_)
        pts = [(X(a), Y(max(z, zbasis))) for a, z in zip(st_[ok], zh_[ok])]
        if len(pts) > 1:
            pts += [(pts[-1][0], Y(zbasis)), (pts[0][0], Y(zbasis))]
            svg.append('<polygon fill="#ece6d8" stroke="none" points="' + " ".join(f"{x:.3f},{y:.3f}" for x, y in pts) + '"/>')
    for q in dah:
        for ring in ringe(q):
            svg.append('<polygon fill="#d6d6d6" stroke="#8c8c8c" stroke-width="0.12" points="'
                       + " ".join(f"{X(a):.3f},{Y(z):.3f}" for a, z in ring) + '"/>')
    for t in baeume:
        if not t["schnitt"]:
            svg.append(f'<line x1="{X(t["s"]):.3f}" y1="{Y(t["z"]):.3f}" x2="{X(t["s"]):.3f}" y2="{Y(t["z"] + 0.3 * t["ho"]):.3f}" stroke="#8a7a60" stroke-width="0.15"/>')
            svg.append('<polygon fill="#c4e0c0" stroke="#6aa56a" stroke-width="0.15" points="'
                       + " ".join(f"{X(a):.3f},{Y(z):.3f}" for a, z in _krone(t, ue, zbasis)) + '"/>')
    svg.append('</g>')
    svg.append('<g id="SCHNITT">')                                       # Vordergrund: der Schnitt selbst
    gel = [(X(a), Y(z)) for a, z in zip(s, zg)]
    flaeche = gel + [(X(s[-1]), Y(zbasis)), (X(s[0]), Y(zbasis))]
    svg.append('<polygon fill="#d8d2c4" stroke="none" points="' + " ".join(f"{x:.3f},{y:.3f}" for x, y in flaeche) + '"/>')
    for poly in gebaeude:
        svg.append('<polygon fill="#bbbbbb" stroke="#222" stroke-width="0.25" points="'
                   + " ".join(f"{X(a):.3f},{Y(z):.3f}" for a, z in poly) + '"/>')
    svg.append('<polyline fill="none" stroke="#000" stroke-width="0.5" points="' + " ".join(f"{x:.3f},{y:.3f}" for x, y in gel) + '"/>')
    for t in baeume:                                                       # Bäume, die von der Schnittlinie getroffen werden
        if t["schnitt"]:
            svg.append(f'<line x1="{X(t["s"]):.3f}" y1="{Y(t["z"]):.3f}" x2="{X(t["s"]):.3f}" y2="{Y(t["z"] + 0.3 * t["ho"]):.3f}" stroke="#5a3b1e" stroke-width="0.35"/>')
            svg.append('<polygon fill="#4f9a4f" fill-opacity="0.75" stroke="#1e5a1e" stroke-width="0.25" points="'
                       + " ".join(f"{X(a):.3f},{Y(z):.3f}" for a, z in _krone(t, ue, zbasis)) + '"/>')
    svg.append(f'<line x1="{X(0):.3f}" y1="{Y(zbasis):.3f}" x2="{X(s[-1]):.3f}" y2="{Y(zbasis):.3f}" stroke="#000" stroke-width="0.35"/>')
    svg.append('</g>')
    # Höhenkoten
    zs = int(zbasis)
    schritt = 5 if (zmax - zbasis) * ue <= 60 else 10
    z = zs + (schritt - zs % schritt) % schritt
    while z <= zmax:
        yy = Y(z)
        svg.append(f'<line x1="{X(0):.3f}" y1="{yy:.3f}" x2="{X(0) - 2:.3f}" y2="{yy:.3f}" stroke="#000" stroke-width="0.2"/>')
        svg.append(f'<text x="{X(0) - 2.5:.3f}" y="{yy + 1:.3f}" font-size="2.5" text-anchor="end" font-family="Arial">{z:+.0f}</text>')
        z += schritt
    svg.append(f'<text x="{rand:.2f}" y="{H - 2:.2f}" font-size="3" font-family="Arial">{name} · 1:{M:g}'
               + (f" · {ue:g}-fach überhöht" if ue != 1 else "") + f" · Länge {pr['laenge']:.0f} m · Höhen in m ü. NHN"
               + (f" · Ansicht nach {seite_txt} (hellgrau), Bäume: dunkelgrün = im Schnitt, hellgrün = dahinter" if (dah or baeume) else "") + "</text>")
    svg.append("</svg>")
    fm = sc.get("format") or ["dxf"]
    f_svg = os.path.join(ordner, f"{name}.svg")
    with open(f_svg, "w", encoding="utf-8") as f:
        f.write("\n".join(svg))
    if "svg" in fm:
        teile.append(f_svg)
    # ---------- DXF (1:1, Meter, Höhen überhöht)
    if any(x in fm for x in ("dxf", "dwg", "pdf")):
        import ezdxf
        doc = ezdxf.new("R2010")
        doc.units = ezdxf.units.M
        msp = doc.modelspace()
        for lay, col in (("SCHNITT_GELAENDE", 7), ("SCHNITT_GEBAEUDE", 8), ("HOEHEN", 3), ("TEXT", 7), ("HINTERGRUND_GELAENDE", 9), ("HINTERGRUND_GEBAEUDE", 9),
                         ("HINTERGRUND_BAEUME", 94), ("SCHNITT_BAEUME", 3)):
            doc.layers.add(lay, color=col)
        if zh is not None:
            st_, zh_ = zh
            ok = np.isfinite(zh_)
            if ok.sum() > 1:
                msp.add_lwpolyline([(a, (max(z, zbasis) - zbasis) * ue) for a, z in zip(st_[ok], zh_[ok])], dxfattribs={"layer": "HINTERGRUND_GELAENDE"})
        for q in dah:
            for ring in ringe(q):
                msp.add_lwpolyline([(a, (z - zbasis) * ue) for a, z in ring], close=True, dxfattribs={"layer": "HINTERGRUND_GEBAEUDE"})
        for t in baeume:
            lay = "SCHNITT_BAEUME" if t["schnitt"] else "HINTERGRUND_BAEUME"
            msp.add_lwpolyline([(a, (z - zbasis) * ue) for a, z in _krone(t, ue, zbasis)], close=True, dxfattribs={"layer": lay})
            msp.add_line((t["s"], (t["z"] - zbasis) * ue), (t["s"], (t["z"] + 0.3 * t["ho"] - zbasis) * ue), dxfattribs={"layer": lay})
        msp.add_lwpolyline([(a, (z - zbasis) * ue) for a, z in zip(s, zg)], dxfattribs={"layer": "SCHNITT_GELAENDE"})
        msp.add_line((s[0], 0), (s[-1], 0), dxfattribs={"layer": "SCHNITT_GELAENDE"})
        for poly in gebaeude:
            msp.add_lwpolyline([(a, (z - zbasis) * ue) for a, z in poly], close=True, dxfattribs={"layer": "SCHNITT_GEBAEUDE"})
        z = zs + (schritt - zs % schritt) % schritt
        while z <= zmax:
            yy = (z - zbasis) * ue
            msp.add_line((0, yy), (-3, yy), dxfattribs={"layer": "HOEHEN"})
            msp.add_text(f"{z:+.0f}", dxfattribs={"layer": "HOEHEN", "height": 2.0, "insert": (-4, yy - 1)})
            z += schritt
        msp.add_text(f"{name} 1:{M:g}", dxfattribs={"layer": "TEXT", "height": 3.0, "insert": (0, -8)})
        f_dxf = os.path.join(ordner, f"{name}.dxf")
        doc.saveas(f_dxf)
        from . import einstellungen as ES
        from .formate import zweid_umwandeln
        teile += zweid_umwandeln([f_dxf], [x for x in fm if x in ("dxf", "dwg", "pdf")], ES.laden().get("oda_pfad", ""), log)
    # ---------- PNG-Vorschau
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(11, max(2.5, 11 * hoehe / max(pr["laenge"], 1) + 1)), dpi=100)
    if zh is not None:
        st_, zh_ = zh
        ok = np.isfinite(zh_)
        if ok.sum() > 1:
            ax.fill_between(st_[ok], np.maximum(zh_[ok], zbasis), zbasis, color="#ece6d8", lw=0)
    for q in dah:
        for ring in ringe(q):
            a_, z_ = zip(*ring)
            ax.fill(a_, z_, color="#d6d6d6", ec="#8c8c8c", lw=0.4)
    for t in baeume:
        if not t["schnitt"]:
            a_, z_ = zip(*_krone(t, ue, zbasis))
            ax.fill(a_, z_, color="#c4e0c0", ec="#6aa56a", lw=0.5)
            ax.plot([t["s"], t["s"]], [t["z"], t["z"] + 0.3 * t["ho"]], color="#8a7a60", lw=0.6)
    ax.fill_between(s, zg, zbasis, color="#d8d2c4")
    for poly in gebaeude:
        a, z = zip(*poly)
        ax.fill(a, z, color="#bbbbbb", ec="#222", lw=0.6)
    ax.plot(s, zg, color="k", lw=1.2)
    for t in baeume:
        if t["schnitt"]:
            a_, z_ = zip(*_krone(t, ue, zbasis))
            ax.fill(a_, z_, color="#4f9a4f", alpha=0.75, ec="#1e5a1e", lw=0.8)
            ax.plot([t["s"], t["s"]], [t["z"], t["z"] + 0.3 * t["ho"]], color="#5a3b1e", lw=1.2)
    ax.set_xlim(0, pr["laenge"])
    ax.set_ylim(zbasis, zmax + 2)
    ax.set_aspect(ue, adjustable="box")
    ax.set_xlabel("Länge (m)")
    ax.set_ylabel("m ü. NHN")
    ax.set_title(f"{name} · 1:{M:g}" + (f" · {ue:g}-fach überhöht" if ue != 1 else "")
                 + (f"\nAnsicht nach {seite_txt} (hellgrau) · Bäume: dunkelgrün = im Schnitt, hellgrün = dahinter" if (dah or baeume) else ""), fontsize=9)
    fig.tight_layout()
    f_png = os.path.join(ordner, f"{name}.png")
    fig.savefig(f_png)
    plt.close(fig)
    teile.append(f_png)
    log(f"  Schnitt {pr['laenge']:.0f} m lang, {len(gebaeude)} Gebäudeschnitte, {len(dah)} Gebäude und {len(baeume)} Bäume in der Ansicht dahinter, "
        f"Gelände {np.nanmin(zg):.1f}–{np.nanmax(zg):.1f} m")
    return {"dateien": teile, "png": f_png, "svg": f_svg}


def erzeugen(p, log=print, prog=lambda *a: None):
    a, b = linie(p)
    prog(0.05, "Daten für den Schnitt laden …")
    log(f"Geländeschnitt von ({a[0]:.0f}, {a[1]:.0f}) nach ({b[0]:.0f}, {b[1]:.0f})")
    szene = szene_fuer_linie(p, a, b, log)
    prog(0.6, "Profil berechnen …")
    pr = profil(szene, a, b, float(p["schnitt"].get("abstand_m") or 0.5))
    an, tiefe, seite, bz = ansicht_einst(p)
    try:
        pr["hinten"] = ansicht_dahinter(szene, a, b, an, tiefe, seite, bz)
    except Exception as e:
        import traceback
        log(f"  Ansicht der dahinterliegenden Gebäude nicht möglich ({str(e)[:120]}) - nur der Schnitt wird gezeichnet")
        log(traceback.format_exc()[-400:])
        pr["hinten"] = None
    if pr["hinten"]:
        h = pr["hinten"]
        log(f"  Ansicht dahinter ({seite}, {tiefe:.0f} m Tiefe): {len(h['gebaeude'])} Gebäude, {len(h['baeume'])} Bäume "
            f"({sum(1 for t in h['baeume'] if t['schnitt'])} davon im Schnitt)")
    prog(0.8, "Zeichnen …")
    from .projekt import ausgabe_ordner, sicher
    ordner = ausgabe_ordner(p, "schnitt")
    r = zeichnen(pr, p, ordner, sicher(p["name"]) + "_Schnitt", log)
    prog(1.0, "Fertig")
    return {"ordner": ordner, **r}
