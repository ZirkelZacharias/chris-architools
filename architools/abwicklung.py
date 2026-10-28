"""Straßen- und Fassadenabwicklung: das Schnitt-Werkzeug mit einer Linie aus mehreren Punkten (Straßenachse).

Entlang der Linie werden die Gebäude und Bäume beider Straßenseiten (oder einer) als Ansicht aufgeklappt – wie die
Abwicklung einer Straße im Wettbewerbsplan. Jede Seite ist ein eigener Streifen; Gelände und Straßenachse stehen in
beiden Streifen. Nie überhöht. Gelände, Gebäude und Bäume liegen im DXF auf getrennten Ebenen je Seite.
"""
import copy
import math
import os

import numpy as np

from . import schnitt as SC

SEITEN = {"links": "Linke Straßenseite (in Richtung A → B)", "rechts": "Rechte Straßenseite (in Richtung A → B)"}


def punkte(p):
    """Punkte der Linie [(E, N), …]; ohne eigene Linie die Standardlinie (2 Punkte)."""
    s = p["schnitt"]
    li = s.get("linie_en")
    if li and len(li) >= 2:
        return [(float(x), float(y)) for x, y in li]
    a, b = SC.linie(p)
    return [a, b]


def seiten_der_wahl(p):
    w = p["schnitt"].get("seite") or "links"
    return ["links", "rechts"] if w == "beide" else [("rechts" if w == "rechts" else "links")]


def szene_fuer_punkte(p, pts, tiefe, log):
    from .modell import pipeline
    cfg = copy.deepcopy(p["modell"])
    pad = 25.0 + tiefe
    xs, ys = [q[0] for q in pts], [q[1] for q in pts]
    x0, x1, y0, y1 = min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad
    cfg["massstab"] = 1000
    cfg["gebiet"] = {"mitte_en": [(x0 + x1) / 2, (y0 + y1) / 2], "drehung_grad": 0.0,
                     "breite_cm": (x1 - x0) * 100 / 1000.0, "hoehe_cm": (y1 - y0) * 100 / 1000.0}
    cfg["_basis"] = p["ordner"]
    u = p.get("umgebung", {})
    cfg["netz"] = {"cafile": u.get("cafile", "") or "", "unsicher": bool(u.get("unsicher", False))}
    return pipeline.szene_laden(cfg, log)


def berechnen(szene, pts, seiten, tiefe, baeume_zeigen, abstand=0.5):
    """-> dict(s, zg, laenge, knicke=[s je Punkt], seiten={seite: dict(gebaeude=[(poly,u)], baeume=[…])})"""
    s_all, zg_all, knicke = [], [], [0.0]
    off = 0.0
    seg = []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        pr = SC.profil(szene, a, b, abstand)
        L = pr["laenge"]
        k = 1 if i > 0 else 0                       # doppelten Knickpunkt weglassen
        s_all.append(pr["s"][k:] + off)
        zg_all.append(pr["zg"][k:])
        seg.append((a, b, off, L))
        off += L
        knicke.append(off)
    out = {"s": np.concatenate(s_all), "zg": np.concatenate(zg_all), "laenge": off, "knicke": knicke, "seiten": {}}
    for seite in seiten:
        geb, bm = [], []
        for a, b, o, L in seg:
            if L < 1e-6:
                continue
            r = SC.ansicht_dahinter(szene, a, b, True, tiefe, seite, baeume_zeigen)
            for g in r["gebaeude"]:
                geb.append({"poly": g["poly"], "u": g["u"], "o": o, "id": g.get("id")})
            for t in r["baeume"]:
                t = dict(t)
                t["s"] += o
                bm.append(t)
        geb.sort(key=lambda t: -t["u"])
        bm.sort(key=lambda t: -t["u"])
        out["seiten"][seite] = {"gebaeude": geb, "baeume": bm}
    return out


def _ringe(q, o):
    return [[(x + o, z) for x, z in pg.exterior.coords]
            for pg in getattr(q, "geoms", [q]) if pg.geom_type == "Polygon" and not pg.is_empty]


def zeichnen(r, p, ordner, name, log=print):
    sc = p["schnitt"]
    M = float(sc.get("massstab") or 500)
    os.makedirs(ordner, exist_ok=True)
    s, zg, L = r["s"], r["zg"], r["laenge"]
    seiten = list(r["seiten"])
    zbasis = math.floor(np.nanmin(zg) - 2.0)
    zmax = float(np.nanmax(zg))
    ringe = {}
    for sd, d in r["seiten"].items():
        ringe[sd] = []
        for g in d["gebaeude"]:
            for ring in _ringe(g["poly"], g["o"]):
                ringe[sd].append((ring, g["u"]))
                zmax = max(zmax, max(z for _, z in ring))
        for t in d["baeume"]:
            zmax = max(zmax, t["z"] + t["ho"])
    hoehe = zmax - zbasis + 1.0
    luecke = 8.0
    # senkrechte Lage der Streifen: erster Streifen oben (Basis bei 0), weitere darunter
    basis = {sd: -i * (hoehe + luecke) for i, sd in enumerate(seiten)}
    gesamt_h = len(seiten) * hoehe + (len(seiten) - 1) * luecke
    fm = sc.get("format") or ["dxf"]
    teile = []
    # ---------------- SVG (mm im Maßstab 1:M)
    k = 1000.0 / M
    rand = 14.0
    W = L * k + 2 * rand
    H = gesamt_h * k + 2 * rand + 10
    X = lambda v: rand + v * k
    Y = lambda sd, z: rand + 4 + (-(basis[sd]) + (zmax + 1.0 - z)) * k
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.2f}mm" height="{H:.2f}mm" viewBox="0 0 {W:.2f} {H:.2f}">',
           '<rect width="100%" height="100%" fill="white"/>']
    for sd in seiten:
        svg.append(f'<g id="ABWICKLUNG_{sd.upper()}">')
        umax = max([u for _, u in ringe[sd]] + [1.0])
        for ring, u in ringe[sd]:                                       # fern -> nah (Liste ist so sortiert)
            grau = int(236 - 40 * (1 - min(u / umax, 1.0)))
            svg.append(f'<polygon fill="rgb({grau},{grau},{grau})" stroke="#555" stroke-width="0.15" points="'
                       + " ".join(f"{X(a):.3f},{Y(sd, z):.3f}" for a, z in ring) + '"/>')
        for t in r["seiten"][sd]["baeume"]:
            svg.append('<polygon fill="#bfdcb8" fill-opacity="0.85" stroke="#5a9a5a" stroke-width="0.15" points="'
                       + " ".join(f"{X(a):.3f},{Y(sd, z):.3f}" for a, z in SC._krone(t, 1.0, zbasis)) + '"/>')
            svg.append(f'<line x1="{X(t["s"]):.3f}" y1="{Y(sd, t["z"]):.3f}" x2="{X(t["s"]):.3f}" y2="{Y(sd, t["z"] + 0.3 * t["ho"]):.3f}" stroke="#8a7a60" stroke-width="0.15"/>')
        gel = [(X(a), Y(sd, z)) for a, z in zip(s, zg)]
        flaeche = gel + [(X(s[-1]), Y(sd, zbasis)), (X(s[0]), Y(sd, zbasis))]
        svg.append('<polygon fill="#d8d2c4" stroke="none" points="' + " ".join(f"{x:.3f},{y:.3f}" for x, y in flaeche) + '"/>')
        svg.append('<polyline fill="none" stroke="#000" stroke-width="0.5" points="' + " ".join(f"{x:.3f},{y:.3f}" for x, y in gel) + '"/>')
        svg.append(f'<line x1="{X(0):.3f}" y1="{Y(sd, zbasis):.3f}" x2="{X(L):.3f}" y2="{Y(sd, zbasis):.3f}" stroke="#000" stroke-width="0.35"/>')
        for i, kn in enumerate(r["knicke"]):                            # Knickpunkte der Linie
            svg.append(f'<line x1="{X(kn):.3f}" y1="{Y(sd, zbasis):.3f}" x2="{X(kn):.3f}" y2="{Y(sd, zmax + 1):.3f}" stroke="#c8643b" stroke-width="0.2" stroke-dasharray="1.5 1"/>')
            svg.append(f'<text x="{X(kn):.3f}" y="{Y(sd, zmax + 1) - 1:.3f}" font-size="3" text-anchor="middle" font-family="Arial" fill="#c8643b">{chr(65 + i) if i < 26 else i}</text>')
        svg.append(f'<text x="{rand:.2f}" y="{Y(sd, zmax + 1) - 1:.2f}" font-size="3" font-family="Arial">{SEITEN[sd]}</text>')
        # Stationierung
        schritt = 10 if L <= 150 else 20 if L <= 400 else 50
        v = 0.0
        while v <= L + 1e-6:
            svg.append(f'<line x1="{X(v):.3f}" y1="{Y(sd, zbasis):.3f}" x2="{X(v):.3f}" y2="{Y(sd, zbasis) + 1.5:.3f}" stroke="#000" stroke-width="0.2"/>')
            svg.append(f'<text x="{X(v):.3f}" y="{Y(sd, zbasis) + 4.5:.3f}" font-size="2.2" text-anchor="middle" font-family="Arial">{v:.0f}</text>')
            v += schritt
        svg.append('</g>')
    svg.append(f'<text x="{rand:.2f}" y="{H - 3:.2f}" font-size="3" font-family="Arial">{name} · 1:{M:g} · nicht überhöht · Länge {L:.0f} m · '
               f'Höhen in m ü. NHN (Basis {zbasis:+.0f}) · Gebäude: je dunkler, desto näher an der Linie · Bäume hellgrün</text>')
    svg.append("</svg>")
    f_svg = os.path.join(ordner, f"{name}.svg")
    with open(f_svg, "w", encoding="utf-8") as f:
        f.write("\n".join(svg))
    if "svg" in fm:
        teile.append(f_svg)
    # ---------------- DXF (1:1, Meter, Höhe = z - zbasis + Streifenbasis)
    if any(x in fm for x in ("dxf", "dwg", "pdf")):
        import ezdxf
        doc = ezdxf.new("R2010")
        doc.units = ezdxf.units.M
        msp = doc.modelspace()
        doc.layers.add("ABWICKLUNG_GELAENDE", color=7)
        doc.layers.add("ABWICKLUNG_KNICKPUNKTE", color=30)
        doc.layers.add("ABWICKLUNG_TEXT", color=7)
        for sd in seiten:
            doc.layers.add(f"ABWICKLUNG_{sd.upper()}_GEBAEUDE", color=8)
            doc.layers.add(f"ABWICKLUNG_{sd.upper()}_BAEUME", color=94)
        for sd in seiten:
            b0 = basis[sd] - zbasis
            for ring, u in ringe[sd]:
                msp.add_lwpolyline([(a, z + b0) for a, z in ring], close=True,
                                   dxfattribs={"layer": f"ABWICKLUNG_{sd.upper()}_GEBAEUDE"})
            for t in r["seiten"][sd]["baeume"]:
                lay = f"ABWICKLUNG_{sd.upper()}_BAEUME"
                msp.add_lwpolyline([(a, z + b0) for a, z in SC._krone(t, 1.0, zbasis)], close=True, dxfattribs={"layer": lay})
                msp.add_line((t["s"], t["z"] + b0), (t["s"], t["z"] + 0.3 * t["ho"] + b0), dxfattribs={"layer": lay})
            msp.add_lwpolyline([(a, z + b0) for a, z in zip(s, zg)], dxfattribs={"layer": "ABWICKLUNG_GELAENDE"})
            msp.add_line((s[0], basis[sd]), (s[-1], basis[sd]), dxfattribs={"layer": "ABWICKLUNG_GELAENDE"})
            for i, kn in enumerate(r["knicke"]):
                msp.add_line((kn, basis[sd]), (kn, basis[sd] + hoehe), dxfattribs={"layer": "ABWICKLUNG_KNICKPUNKTE"})
                msp.add_text(chr(65 + i) if i < 26 else str(i),
                             dxfattribs={"layer": "ABWICKLUNG_KNICKPUNKTE", "height": 2.0, "insert": (kn - 0.5, basis[sd] + hoehe + 0.5)})
            msp.add_text(SEITEN[sd], dxfattribs={"layer": "ABWICKLUNG_TEXT", "height": 2.5, "insert": (0, basis[sd] + hoehe + 3.0)})
        msp.add_text(f"{name} 1:{M:g} · Basis {zbasis:+.0f} m ü. NHN", dxfattribs={"layer": "ABWICKLUNG_TEXT", "height": 2.5,
                                                                               "insert": (0, basis[seiten[-1]] - 6)})
        f_dxf = os.path.join(ordner, f"{name}.dxf")
        doc.saveas(f_dxf)
        from . import einstellungen as ES
        from .formate import zweid_umwandeln
        teile += zweid_umwandeln([f_dxf], [x for x in fm if x in ("dxf", "dwg", "pdf")], ES.laden().get("oda_pfad", ""), log)
    # ---------------- PNG
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(len(seiten), 1, figsize=(11, max(2.4, (11 * hoehe / max(L, 1) + 0.8) * len(seiten))), squeeze=False, dpi=100)
    for ax, sd in zip(axs[:, 0], seiten):
        umax = max([u for _, u in ringe[sd]] + [1.0])
        for ring, u in ringe[sd]:
            a_, z_ = zip(*ring)
            g = 0.93 - 0.16 * (1 - min(u / umax, 1.0))
            ax.fill(a_, z_, color=(g, g, g), ec="#555", lw=0.4)
        for t in r["seiten"][sd]["baeume"]:
            a_, z_ = zip(*SC._krone(t, 1.0, zbasis))
            ax.fill(a_, z_, color="#bfdcb8", ec="#5a9a5a", lw=0.5, alpha=0.9)
        ax.fill_between(s, zg, zbasis, color="#d8d2c4")
        ax.plot(s, zg, color="k", lw=1.2)
        for kn in r["knicke"]:
            ax.axvline(kn, color="#c8643b", lw=0.6, ls=":")
        ax.set_xlim(0, L)
        ax.set_ylim(zbasis, zmax + 1)
        ax.set_aspect(1, adjustable="box")
        ax.set_title(SEITEN[sd], fontsize=9, loc="left")
        ax.set_ylabel("m ü. NHN")
    axs[-1, 0].set_xlabel("Länge entlang der Linie (m)")
    fig.suptitle(f"{name} · 1:{M:g} · nicht überhöht", fontsize=9)
    fig.tight_layout()
    f_png = os.path.join(ordner, f"{name}.png")
    fig.savefig(f_png)
    plt.close(fig)
    teile.append(f_png)
    log(f"  Abwicklung {L:.0f} m lang, {len(r['knicke']) - 1} Abschnitt(e); "
        + "; ".join(f"{SEITEN[sd].split(' (')[0]}: {len(r['seiten'][sd]['gebaeude'])} Gebäude, {len(r['seiten'][sd]['baeume'])} Bäume" for sd in seiten))
    return {"dateien": teile, "png": f_png, "svg": f_svg}


def erzeugen(p, log=print, prog=lambda *a: None):
    pts = punkte(p)
    s = p["schnitt"]
    tiefe = float(s.get("tiefe_m") or 0) or 40.0
    seiten = seiten_der_wahl(p)
    laenge = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))
    log(f"Straßen-/Fassadenabwicklung: {len(pts)} Punkte, {laenge:.0f} m, Seite(n): {', '.join(seiten)}, Tiefe {tiefe:.0f} m")
    prog(0.05, "Daten für die Abwicklung laden …")
    szene = szene_fuer_punkte(p, pts, tiefe, log)
    prog(0.6, "Abwicklung berechnen …")
    r = berechnen(szene, pts, seiten, tiefe, bool(s.get("baeume", True)), float(s.get("abstand_m") or 0.5))
    prog(0.8, "Zeichnen …")
    from .projekt import ausgabe_ordner, sicher
    ordner = ausgabe_ordner(p, "schnitt")
    res = zeichnen(r, p, ordner, sicher(p["name"]) + "_Abwicklung", log)
    prog(1.0, "Fertig")
    return {"ordner": ordner, **res}
