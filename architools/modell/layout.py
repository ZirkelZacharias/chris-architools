"""Werkzeug „Lasercut-Layout“: beliebige Teile (DXF, PDF, SVG) nach Werkstatt-Regeln auf Platten verteilen.

Erkennung je Linie/Fläche:
  rot  bzw. Layer mit „schneid|cut“    -> Schneiden (geschlossene Konturen bilden die Teile)
  blau bzw. Layer mit „ritz|score“     -> Ritzen
  schwarze Füllung / Schraffur bzw. „grav“ -> Gravieren
Alles andere wird je nach Einstellung als Schneiden behandelt oder ignoriert.
Teile werden aus den Schnittkonturen gebildet (gerade/ungerade-Regel: Löcher in Teilen bleiben Löcher).
"""
import os
import re

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon
from shapely.ops import linemerge, polygonize

from . import bibliothek as BIB
from . import blatt as BL
from .geomutil import lines, polys

RX = {"schneiden": re.compile(r"schneid|cut|kontur|outline", re.I),
      "ritzen": re.compile(r"ritz|score|engrav.*line|falz", re.I),
      "gravieren": re.compile(r"grav|raster|fill|schraff|hatch", re.I)}


def _art_aus_farbe(rgb, gefuellt=False):
    if rgb is None:
        return None
    r, g, b = rgb
    if gefuellt and r < 0.2 and g < 0.2 and b < 0.2:
        return "gravieren"
    if r > 0.7 and g < 0.3 and b < 0.3:
        return "schneiden"
    if b > 0.7 and r < 0.3 and g < 0.3:
        return "ritzen"
    if r < 0.2 and g < 0.2 and b < 0.2:
        return "gravieren" if gefuellt else None
    return None


# ------------------------------------------------------------------ Einlesen
def lies_dxf(pfad, log=print):
    """-> Liste (art|None, geometrie) in Zeichnungseinheiten."""
    import ezdxf
    from ezdxf import path as ezpath
    from ezdxf.colors import aci2rgb
    doc = ezdxf.readfile(pfad)
    out = []
    for e in doc.modelspace():
        lay = e.dxf.get("layer", "")
        art = None
        for k, rx in RX.items():
            if rx.search(lay):
                art = k
                break
        try:
            if e.dxf.hasattr("true_color"):
                c = e.rgb
            else:
                aci = e.dxf.get("color", 256)
                if aci == 256:
                    aci = doc.layers.get(lay).color if lay in doc.layers else 7
                c = aci2rgb(aci) if aci not in (0, 7) else (0, 0, 0)       # 7 = schwarz/weiß -> schwarz
            rgb = tuple(v / 255.0 for v in c)
        except Exception:
            rgb = None
        typ = e.dxftype()
        if typ == "HATCH":
            art_h = art or _art_aus_farbe(rgb, True) or "gravieren"
            ringe = []
            for p in e.paths.rendering_paths(e.dxf.hatch_style):
                pts = [(v.x, v.y) for v in ezpath.from_hatch_boundary_path(p).flattening(0.05)]
                if len(pts) >= 3:
                    ringe.append(Polygon(pts))
            g = Polygon()
            for r in ringe:
                if r.is_valid and r.area > 0:
                    g = g.symmetric_difference(r)
            if not g.is_empty:
                out.append((art_h, g))
            continue
        if typ in ("TEXT", "MTEXT", "DIMENSION", "INSERT", "POINT", "VIEWPORT"):
            continue
        try:
            p = ezpath.make_path(e)
            pts = [(v.x, v.y) for v in p.flattening(0.05)]
        except Exception:
            continue
        if len(pts) < 2:
            continue
        out.append((art or _art_aus_farbe(rgb), LineString(pts)))
    log(f"  DXF {os.path.basename(pfad)}: {len(out)} Elemente")
    return out


def lies_pdf(pfad, log=print, seite=None):
    """PDF-Zeichnung (z. B. ArchiCAD-Export) -> Liste (art, geometrie) in mm."""
    from .blatt import _pdfmodul
    pymupdf = _pdfmodul()
    k = 25.4 / 72.0
    doc = pymupdf.open(pfad)
    out = []
    for si, page in enumerate(doc):
        if seite is not None and si != seite:
            continue
        H = page.rect.height
        for d in page.get_drawings():
            ringe, offen = [], []
            for it in d["items"]:
                pts = []
                if it[0] == "l":
                    pts = [it[1], it[2]]
                elif it[0] == "c":
                    p0, c1, c2, p1 = it[1:5]
                    for tt in np.linspace(0, 1, 12):
                        x = (1 - tt) ** 3 * p0.x + 3 * (1 - tt) ** 2 * tt * c1.x + 3 * (1 - tt) * tt ** 2 * c2.x + tt ** 3 * p1.x
                        y = (1 - tt) ** 3 * p0.y + 3 * (1 - tt) ** 2 * tt * c1.y + 3 * (1 - tt) * tt ** 2 * c2.y + tt ** 3 * p1.y
                        pts.append(pymupdf.Point(x, y))
                elif it[0] == "re":
                    r = it[1]
                    pts = [r.tl, r.tr, r.br, r.bl, r.tl]
                elif it[0] == "qu":
                    q = it[1]
                    pts = [q.ul, q.ur, q.lr, q.ll, q.ul]
                if pts:
                    offen.append([(p.x * k, (H - p.y) * k) for p in pts])
            if not offen:
                continue
            gefuellt = d.get("fill") is not None
            art = _art_aus_farbe(d.get("fill") if gefuellt else d.get("color"), gefuellt)
            if gefuellt:
                linien = shapely.union_all([LineString(o) for o in offen if len(o) >= 2])
                g = Polygon()
                for pg in polygonize(lines(linien)):
                    g = g.symmetric_difference(Polygon(pg.exterior))
                if not g.is_empty:
                    out.append((art or "gravieren", g))
            else:
                for o in offen:
                    out.append((art, LineString(o)))
    log(f"  PDF {os.path.basename(pfad)}: {len(out)} Elemente")
    return out


def lies_svg(pfad, log=print):
    try:
        import svgelements as se
    except ImportError:
        raise RuntimeError("Für SVG wird das Paket svgelements gebraucht")
    svg = se.SVG.parse(pfad, ppi=25.4)            # Einheiten in mm
    out = []
    H = svg.height or 0
    for el in svg.elements():
        if not isinstance(el, se.Shape):
            continue
        try:
            p = se.Path(el)
            p.reify()
        except Exception:
            continue
        stroke = el.stroke if el.stroke is not None and el.stroke.value is not None else None
        fill = el.fill if el.fill is not None and el.fill.value is not None else None
        for sub in p.as_subpaths():
            sp = se.Path(sub)
            n = max(8, int(sp.length() / 0.5)) if sp.length() else 8
            pts = [(q.x, H - q.y) for q in (sp.point(t) for t in np.linspace(0, 1, n))]
            if len(pts) < 2:
                continue
            if fill is not None and fill.alpha > 0:
                art = _art_aus_farbe((fill.red / 255, fill.green / 255, fill.blue / 255), True)
                if len(pts) >= 3:
                    out.append((art or "gravieren", Polygon(pts)))
            if stroke is not None:
                art = _art_aus_farbe((stroke.red / 255, stroke.green / 255, stroke.blue / 255))
                out.append((art, LineString(pts)))
    log(f"  SVG {os.path.basename(pfad)}: {len(out)} Elemente")
    return out


# ------------------------------------------------------------------ Teile bilden
def teile_bilden(elemente, faktor=1.0, unbekannt="schneiden", log=print, praefix="T"):
    """Elemente -> Laserteile. faktor skaliert (z. B. 1:100-Zeichnung in m -> mm)."""
    sk = lambda g: shapely.affinity.scale(g, faktor, faktor, origin=(0, 0)) if faktor != 1 else g
    schnitt, ritz, grav = [], [], []
    for art, g in elemente:
        art = art or (unbekannt if unbekannt != "ignorieren" else None)
        if art is None:
            continue
        g = sk(g)
        if art == "schneiden":
            schnitt += lines(g) if g.geom_type != "Polygon" else lines(g.boundary)
        elif art == "ritzen":
            ritz += lines(g) if g.geom_type != "Polygon" else lines(g.boundary)
        else:
            grav += polys(g) if "Polygon" in g.geom_type else []
    if not schnitt:
        raise ValueError("Keine Schnittkonturen gefunden (rote Linien bzw. Layer „schneiden“)")
    # Fast-geschlossene Konturen schließen und Fläche nach gerade/ungerade-Regel bilden
    netz = shapely.union_all([shapely.set_precision(l, 0.01) for l in schnitt])
    ringe = [Polygon(r.exterior) for r in polygonize(lines(linemerge(netz) if netz.geom_type == "MultiLineString" else netz))]
    ringe.sort(key=lambda p: -p.area)
    material = Polygon()
    for r in ringe:
        material = material.symmetric_difference(r)
    stuecke = [p for p in polys(material) if p.area > 0.5]
    offen = sum(1 for l in lines(netz) if not l.is_ring)
    if offen and not stuecke:
        log(f"  WARNUNG: {offen} Schnittlinien sind nicht geschlossen")
    teile = []
    for i, p in enumerate(sorted(stuecke, key=lambda p: (-p.bounds[3], p.bounds[0])), 1):
        c = p.buffer(0.02)
        teile.append({"id": f"{praefix}{i:03d}", "poly": p,
                      "ritzen": [x for l in ritz if l.intersects(c) for x in lines(l.intersection(c))],
                      "gravieren": [x for g in grav if g.intersects(p) for x in polys(g.intersection(p))]})
    log(f"  {len(teile)} Teile erkannt" + (f", {len(ritz)} Ritzlinien, {len(grav)} Gravurflächen" if ritz or grav else ""))
    return teile


def layout(cfg_w, cfg, log=print):
    """cfg_w: dateien, einheit ("mm"|"cm"|"m"), massstab (1 = Zeichnung ist schon 1:1 in mm),
    unbekannt ("schneiden"|"ignorieren"), anzahl (Exemplare), ausgabe_ordner, name"""
    f_einheit = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "pt": 25.4 / 72}[cfg_w.get("einheit", "mm")]
    faktor = f_einheit / float(cfg_w.get("massstab", 1) or 1)
    teile = []
    for i, p in enumerate(cfg_w["dateien"]):
        low = p.lower()
        log(f"Lesen: {os.path.basename(p)}")
        if low.endswith(".dxf"):
            el = lies_dxf(p, log)
        elif low.endswith(".pdf"):
            from .blatt import _pdfmodul
            n_s = len(_pdfmodul().open(p))
            faktor_d = 1.0 / float(cfg_w.get("massstab", 1) or 1)
            for si in range(n_s):
                el = lies_pdf(p, log, seite=si)
                if el:
                    teile += teile_bilden(el, faktor_d, cfg_w.get("unbekannt", "schneiden"), log,
                                          f"D{i + 1}-{si + 1}-" if n_s > 1 else f"D{i + 1}-")
            continue
        elif low.endswith(".svg"):
            el = lies_svg(p, log)
        else:
            raise ValueError(f"Format nicht unterstützt: {p}")
        teile += teile_bilden(el, faktor, cfg_w.get("unbekannt", "schneiden"), log, f"D{i + 1}-")
    n = max(1, int(cfg_w.get("anzahl", 1)))
    import copy
    alle = [copy.copy(t) for _ in range(n) for t in teile]
    meld = []
    for t in alle:
        BL.bereinigen(t, protokoll=meld)
    for m in meld[:10]:
        log("  " + m)
    formate = BIB.plattenformate(cfg)
    platten, rest = BL.anordnen(alle, formate, cfg, log)
    out = os.path.abspath(cfg_w.get("ausgabe_ordner") or "ausgabe_layout")
    os.makedirs(out, exist_ok=True)
    sorte, st, _ = BIB.material(cfg)
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", cfg_w.get("name", "layout"))
    from .pipeline import mm
    pdfs = BL.pdfs_schreiben(out, f"{name}_{re.sub(r'[^A-Za-z0-9_.-]+', '_', sorte)}_{mm(st)}mm", platten,
                             f"{cfg_w.get('name', 'Layout')} – {sorte} {mm(st)} mm", log)
    svgs = []
    for i, pl in enumerate(platten, 1):
        s = os.path.join(out, f"{name}_platte_{i:02d}.svg")
        BL.svg_schreiben(s, pl, titel=f"Platte {i}")
        svgs.append(s)
    fl = sum(t["poly"].area for pl in platten for t in pl["teile"])
    gesamt = sum(p["format"][0] * p["format"][1] for p in platten)
    log(f"Fertig: {len(alle)} Teile auf {len(platten)} Platten, Ausnutzung {100 * fl / max(gesamt, 1):.0f} % · {out}")
    return {"laser_pdfs": pdfs, "laser_ordner": out, "svgs": svgs, "platten": len(platten), "teile": len(alle), "rest": len(rest), "ausgabe": out}
