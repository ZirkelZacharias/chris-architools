"""Laserteile bereinigen, auf Platten verteilen und als Werkstatt-Datei ausgeben.

Ein Laserteil ist ein dict:
    id        Teile-ID (Text)
    poly      Schnittkontur als shapely-Polygon (Löcher = Innenschnitte)
    ritzen    [LineString]   blaue Linien
    gravieren [Polygon]      schwarze Flächen (inkl. Beschriftung als Pfade)
Alles in Millimetern. Dieses Modul kennt kein Gelände – es wird auch vom Werkzeug
„Lasercut-Layout“ für beliebige Teile benutzt.
"""

import os

import shapely
from shapely.geometry import MultiLineString, Polygon
from shapely.ops import linemerge

from . import nesting as N
from .bibliothek import WERKSTATT
from .geomutil import lines, polys

RASTER = 0.005          # mm: Koordinaten werden darauf gerundet (gegen Fast-Doppellinien)


def _linien_vereinigen(ls):
    if not ls:
        return []
    g = shapely.set_precision(MultiLineString([l for l in ls if l.length > 0]), RASTER)
    g = shapely.union_all([g])
    try:
        g = linemerge(g) if g.geom_type == "MultiLineString" else g
    except Exception:
        pass
    return lines(g)


def bereinigen(teil, min_steg=WERKSTATT["min_steg_mm"], protokoll=None):
    """Werkstatt-Regeln durchsetzen. Ändert das Teil und gibt es zurück.

    - Stege schmaler als min_steg werden entfernt (morphologisches Öffnen der Kontur)
    - Gravurflächen werden vereinigt und auf das Teil begrenzt (keine Überlagerung)
    - Ritzlinien: Doppelte zusammengeführt, nichts auf Schnittkanten, nichts unter Gravurflächen
    """
    p = teil["poly"]
    r = min_steg / 2.0
    if r > 0:
        offen = p.buffer(-r, join_style="mitre", mitre_limit=3).buffer(r, join_style="mitre", mitre_limit=3)
        offen = shapely.make_valid(offen)
        diff = p.symmetric_difference(offen).area
        if diff > 0.02:
            stuecke = [q for q in polys(offen) if q.area > 1.0]
            if stuecke:
                p = max(stuecke, key=lambda q: q.area)
                if protokoll is not None and diff > 1.0:
                    protokoll.append(f"{teil.get('id', '?')}: Stege unter {min_steg} mm entfernt "
                                     f"({diff:.1f} mm² geändert)")
    p = shapely.set_precision(p, RASTER)
    p = max(polys(p), key=lambda q: q.area) if polys(p) else p
    teil["poly"] = p
    innen = p.buffer(-0.15)
    grav = [g for g in teil.get("gravieren", []) if g is not None and not g.is_empty]
    gv = shapely.union_all(grav).intersection(p.buffer(-0.2)) if grav else Polygon()
    gv = shapely.union_all([q for q in polys(gv) if q.area > 0.05]) if not gv.is_empty else gv
    teil["gravieren"] = polys(gv)
    rz = _linien_vereinigen(teil.get("ritzen", []))
    if rz:
        g = shapely.union_all(rz).intersection(innen)
        if not gv.is_empty:
            g = g.difference(gv.buffer(0.05))
        rz = [l for l in lines(g) if l.length >= 0.3]
    teil["ritzen"] = rz
    return teil


def _verschieben(teil, ang, dx, dy):
    mv = lambda g: N.place(g, ang, dx, dy)
    return {"id": teil.get("id", ""), "poly": mv(teil["poly"]),
            "ritzen": [mv(l) for l in teil.get("ritzen", [])],
            "gravieren": [mv(g) for g in teil.get("gravieren", [])]}


def anordnen(teile, formate, cfg, log=print, filler=None, n_filler=0):
    """Teile auf Platten verteilen. Rückgabe: Liste Platten dict(format, teile=[verschobene Teile])."""
    lc = cfg["laser"]
    items = [N.Item(i, t["poly"], lc.get("drehungen", [0, 90, 180, 270])) for i, t in enumerate(teile)]
    sheets, rest = N.nest(items, formate, float(lc.get("rand_mm", WERKSTATT["rand_mm"])),
                          float(lc.get("abstand_mm", 2.0)), float(lc.get("nesting_raster_mm", 1.0)),
                          log, "Laserplatte", filler=filler, n_filler=n_filler)
    out = []
    for si, s in enumerate(sheets, 1):
        drin = []
        for it, ang, dx, dy in s["placements"]:
            teile[it.key]["platte"] = si
            drin.append(_verschieben(teile[it.key], ang, dx, dy))
        for dx, dy in s.get("filler", []):
            drin.append({"id": "", "poly": N.place(filler, 0, dx, dy), "ritzen": [], "gravieren": []})
        out.append({"format": s["format"], "teile": drin})
    if rest:
        log(f"  WARNUNG: {len(rest)} Teile passen auf keine Platte: "
            + ", ".join(str(teile[i.key].get('id')) for i in rest[:10]))
    return out, [teile[i.key] for i in rest]


# ------------------------------------------------------------------ Ausgabe
def _rgb(t):
    return tuple(c / 255.0 for c in t)


def pdf_schreiben(pfad, platten, titel=""):
    """PDF nach Werkstatt-Vorgabe (Seitengröße = Platte,
    RGB, Haarlinien, Rot schneiden, Blau ritzen, Schwarz gravieren (Fläche). Keine Rahmen, keine Texte."""
    import pymupdf
    k = 72.0 / 25.4
    lw = WERKSTATT["linienstaerke_mm"] * k
    rot, blau, schwarz = (_rgb(WERKSTATT[c]) for c in ("farbe_schneiden", "farbe_ritzen", "farbe_gravieren"))
    doc = pymupdf.open()
    for pl in platten:
        W, H = pl["format"]
        page = doc.new_page(width=W * k, height=H * k)

        def pt(x, y):
            return pymupdf.Point(x * k, (H - y) * k)

        sh = page.new_shape()
        # 1) Gravieren (Flächen, ohne Kontur)
        n = 0
        for t in pl["teile"]:
            for g in t.get("gravieren", []):
                for ring in [g.exterior] + list(g.interiors):
                    sh.draw_polyline([pt(x, y) for x, y in ring.coords])
                n += 1
        if n:
            sh.finish(color=None, fill=schwarz, even_odd=True, closePath=False, width=0)
        # 2) Ritzen
        n = 0
        for t in pl["teile"]:
            for l in t.get("ritzen", []):
                sh.draw_polyline([pt(x, y) for x, y in l.coords])
                n += 1
        if n:
            sh.finish(color=blau, fill=None, width=lw, closePath=False)
        # 3) Schneiden: erst Innen-, dann Außenkonturen
        n = 0
        for t in pl["teile"]:
            for ring in t["poly"].interiors:
                sh.draw_polyline([pt(x, y) for x, y in ring.coords])
                n += 1
        if n:
            sh.finish(color=rot, fill=None, width=lw, closePath=False)
        n = 0
        for t in pl["teile"]:
            sh.draw_polyline([pt(x, y) for x, y in t["poly"].exterior.coords])
            n += 1
        if n:
            sh.finish(color=rot, fill=None, width=lw, closePath=False)
        sh.commit()
    doc.set_metadata({"title": titel, "creator": "", "producer": ""})
    doc.save(pfad, garbage=3, deflate=True)
    doc.close()


def laengen(platte):
    """(Schnittlänge, Ritzlänge) einer Platte in mm – grobes Maß für die Laserzeit."""
    sch = sum(t["poly"].exterior.length + sum(i.length for i in t["poly"].interiors) for t in platte["teile"])
    rz = sum(l.length for t in platte["teile"] for l in t.get("ritzen", []))
    return sch, rz


def laserzeit(platten, material, staerke):
    """Grobe Schätzung der Laserzeit in Sekunden -> (mittel, untere, obere Schätzung, Teilzeiten)."""
    from . import bibliothek as B
    v = min(80.0, B.SCHNITT_K.get(material, 45) / max(float(staerke), 0.2))
    sch = rz = fl = 0.0
    kont = 0
    for pl in platten:
        a, b_ = laengen(pl)
        sch += a
        rz += b_
        fl += sum(g.area for t in pl["teile"] for g in t.get("gravieren", []))
        kont += sum(1 + len(t["poly"].interiors) + len(t.get("ritzen", [])) for t in pl["teile"])
    teile = {"schneiden": sch / v, "ritzen": rz / B.RITZEN_MM_S, "gravieren": fl * B.GRAVUR_S_MM2,
             "anfahren": kont * B.JE_KONTUR_S}
    m = sum(teile.values())
    return m, m * 0.7, m * 1.5, dict(teile, schnitt_mm=sch, ritz_mm=rz, gravur_mm2=fl, v_schnitt=v)


def pdfs_schreiben(ordner, basis, platten, titel="", log=print):
    """Eine PDF je Platte (Werkstatt-Vorgabe): <basis>_Platte01.pdf, <basis>_Platte02.pdf, …"""
    pfade = []
    n = len(platten)
    for i, pl in enumerate(platten, 1):
        p = os.path.join(ordner, f"{basis}_Platte{i:02d}.pdf")
        pdf_schreiben(p, [pl], f"{titel} – Platte {i} von {n}")
        for m in pruefen(p, [pl]):
            log(f"  PRÜFUNG Platte {i}: {m}")
        pfade.append(p)
    return pfade


def svg_schreiben(pfad, platte, linie_mm=None, titel="", plattenfarbe=None, teilefarbe=None):
    """Eine Platte als SVG (Vorschau oder für andere Werkstätten). Mit plattenfarbe/teilefarbe (#rrggbb) entsteht die
    Vorschau in Materialfarbe (Platte und ausgeschnittene Teile gefüllt) – die Werkstatt-Dateien bleiben ohne Füllung."""
    W, H = platte["format"]
    lw = linie_mm if linie_mm is not None else WERKSTATT["linienstaerke_mm"]
    hexf = lambda c: "#%02X%02X%02X" % c

    def ring(c):
        return "M" + " L".join(f"{x:.3f},{H - y:.3f}" for x, y in c) + " Z"

    def lin(c):
        return "M" + " L".join(f"{x:.3f},{H - y:.3f}" for x, y in c)

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" viewBox="0 0 {W} {H}">',
         f"<title>{titel}</title>"]
    if plattenfarbe:
        o.append(f'<rect width="{W}" height="{H}" fill="{plattenfarbe}"/>')
        if teilefarbe:
            o.append(f'<g fill="{teilefarbe}" stroke="none" fill-rule="evenodd">')
            for t in platte["teile"]:
                o.append('<path d="' + ring(t["poly"].exterior.coords) + "".join(ring(i.coords) for i in t["poly"].interiors) + '"/>')
            o.append("</g>")
    o.append(f'<g fill="{hexf(WERKSTATT["farbe_gravieren"])}" stroke="none" fill-rule="evenodd">')
    for t in platte["teile"]:
        for g in t.get("gravieren", []):
            o.append('<path d="' + ring(g.exterior.coords) + "".join(ring(i.coords) for i in g.interiors) + '"/>')
    o.append(f'</g><g fill="none" stroke="{hexf(WERKSTATT["farbe_ritzen"])}" stroke-width="{lw}">')
    for t in platte["teile"]:
        for l in t.get("ritzen", []):
            o.append(f'<path d="{lin(l.coords)}"/>')
    o.append(f'</g><g fill="none" stroke="{hexf(WERKSTATT["farbe_schneiden"])}" stroke-width="{lw}">')
    for t in platte["teile"]:
        for r in list(t["poly"].interiors) + [t["poly"].exterior]:
            o.append(f'<path d="{ring(r.coords)}"/>')
    o.append("</g></svg>")
    with open(pfad, "w", encoding="utf-8") as f:
        f.write("\n".join(o))


def dxf_schreiben(pfad, platten):
    """Alle Platten nebeneinander in einer DXF (mm), Layer SCHNEIDEN / RITZEN / GRAVIEREN, ohne Rahmen."""
    import ezdxf
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM
    for name, col in (("SCHNEIDEN", 1), ("RITZEN", 5), ("GRAVIEREN", 7)):
        doc.layers.add(name, color=col)
    msp = doc.modelspace()
    off = 0.0
    for pl in platten:
        W, H = pl["format"]
        for t in pl["teile"]:
            for g in t.get("gravieren", []):
                h = msp.add_hatch(color=7, dxfattribs={"layer": "GRAVIEREN"})
                h.paths.add_polyline_path([(x + off, y) for x, y in g.exterior.coords][:-1], is_closed=True, flags=1)
                for i in g.interiors:
                    h.paths.add_polyline_path([(x + off, y) for x, y in i.coords][:-1], is_closed=True, flags=16)
            for l in t.get("ritzen", []):
                msp.add_lwpolyline([(x + off, y) for x, y in l.coords], dxfattribs={"layer": "RITZEN"})
            for r in list(t["poly"].interiors) + [t["poly"].exterior]:
                msp.add_lwpolyline([(x + off, y) for x, y in r.coords][:-1], close=True,
                                   dxfattribs={"layer": "SCHNEIDEN"})
        off += W + 50
    doc.saveas(pfad)


def pruefen(pfad_pdf, platten):
    """Liest das PDF zurück und prüft Seitenzahl, Seitengrößen, Farben. -> Liste von Meldungen."""
    import pymupdf
    k = 72.0 / 25.4
    msg = []
    doc = pymupdf.open(pfad_pdf)
    if len(doc) != len(platten):
        msg.append(f"Seitenzahl {len(doc)} statt {len(platten)}")
    erlaubt = {_rgb(WERKSTATT[c]) for c in ("farbe_schneiden", "farbe_ritzen", "farbe_gravieren")}
    for i, (page, pl) in enumerate(zip(doc, platten), 1):
        W, H = pl["format"]
        if abs(page.rect.width / k - W) > 0.05 or abs(page.rect.height / k - H) > 0.05:
            msg.append(f"Seite {i}: Größe {page.rect.width / k:.1f} × {page.rect.height / k:.1f} mm statt {W} × {H}")
        for d in page.get_drawings():
            for c in (d.get("color"), d.get("fill")):
                if c is not None and tuple(round(v, 3) for v in c) not in erlaubt:
                    msg.append(f"Seite {i}: unerlaubte Farbe {c}")
                    break
    doc.close()
    return msg
