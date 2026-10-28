"""DXF -> DWG direkt im Programm (ohne ODA File Converter), mit der Bibliothek ezdwg.

Grenzen (Format R2000, AC1015): keine echten RGB-Farben (Farben werden auf die nächste AutoCAD-Standardfarbe gerundet),
keine Transparenz. Unterstützt werden die Elemente, die dieses Programm schreibt: Flächenfüllungen (HATCH), Polylinien,
Linien, Kreise, Bögen, Texte, Punkte. Alles andere (z. B. eingebettete Bilder) wird übersprungen und im Protokoll genannt.
"""
import collections
import os


def verfuegbar():
    try:
        import ezdwg  # noqa: F401
        return True
    except Exception:
        return False


_PAL = {}


def aci_aus_rgb(wert):
    """Nächste AutoCAD-Standardfarbe. Schwarz -> 7 (erscheint auf hellem Papier schwarz), Weiß -> 255 (nicht 7, das auf
    hellem Papier schwarz erscheinen würde)."""
    r, g, b = (wert >> 16) & 255, (wert >> 8) & 255, wert & 255
    if (r, g, b) == (0, 0, 0):
        return 7
    if not _PAL:
        try:
            from ezdwg._aci import aci_palette
            _PAL.update({k: v for k, v in aci_palette().items() if k != 7})
        except Exception:
            _PAL.update({1: (255, 0, 0), 2: (255, 255, 0), 3: (0, 255, 0), 4: (0, 255, 255), 5: (0, 0, 255), 6: (255, 0, 255),
                         8: (128, 128, 128), 9: (192, 192, 192), 255: (255, 255, 255)})
    return min(_PAL, key=lambda k: (_PAL[k][0] - r) ** 2 + (_PAL[k][1] - g) ** 2 + (_PAL[k][2] - b) ** 2)


def _gemeinsam(e):
    d = e.dxf
    a = {"layer": d.layer}
    tc = d.get("true_color")
    if tc is not None:
        a["color_index"] = aci_aus_rgb(int(tc))
    elif d.get("color") not in (None, 256):
        a["color_index"] = int(d.color)
    lw = d.get("lineweight")
    if lw is not None and lw >= 0:
        a["lineweight"] = int(lw)
    return a


def konvertieren(dxf, ziel=None, log=print):
    """Schreibt <dxf>.dwg. -> Pfad der DWG oder None."""
    import ezdwg
    import ezdxf
    ziel = ziel or os.path.splitext(dxf)[0] + ".dwg"
    doc = ezdxf.readfile(dxf)
    dwg = ezdwg.new()
    for l in doc.layers:
        n = l.dxf.name
        if n == "0":
            continue
        zeile = {"color_index": abs(int(l.dxf.color)) or 7}
        tc = l.dxf.get("true_color")
        if tc is not None:
            zeile = {"color_index": aci_aus_rgb(int(tc))}
        dwg.layers[n] = zeile
    ms = dwg.modelspace()
    n_ok, uebersprungen = 0, collections.Counter()
    for e in doc.modelspace():
        t = e.dxftype()
        a = _gemeinsam(e)
        try:
            if t == "LWPOLYLINE":
                pts = e.get_points("xyb")
                kw = {"closed": bool(e.closed)}
                bul = [p[2] for p in pts]
                if any(bul):
                    kw["bulges"] = bul
                if e.dxf.get("const_width"):
                    kw["const_width"] = float(e.dxf.const_width)
                ms.add_lwpolyline([(p[0], p[1]) for p in pts], **kw, **a)
            elif t == "HATCH":
                pfade = []
                for p in e.paths:
                    if getattr(p, "vertices", None) is None or not hasattr(p, "has_bulge"):
                        uebersprungen["HATCH-Kantenpfad"] += 1
                        continue
                    v = list(p.vertices)
                    d = {"points": [(q[0], q[1]) for q in v], "closed": True}
                    if p.has_bulge:
                        d["bulges"] = [q[2] if len(q) > 2 else 0.0 for q in v]
                    pfade.append(d)
                if not pfade:
                    continue
                if e.dxf.solid_fill:
                    ms.add_hatch(pfade, **a)
                else:
                    ms.add_hatch(pfade, pattern=e.dxf.pattern_name, pattern_angle=float(e.dxf.get("pattern_angle", 0)),
                                 pattern_scale=float(e.dxf.get("pattern_scale", 1)), **a)
            elif t == "LINE":
                ms.add_line(tuple(e.dxf.start), tuple(e.dxf.end), **a)
            elif t == "CIRCLE":
                ms.add_circle(tuple(e.dxf.center), float(e.dxf.radius), **a)
            elif t == "ARC":
                ms.add_arc(tuple(e.dxf.center), float(e.dxf.radius), float(e.dxf.start_angle), float(e.dxf.end_angle), **a)
            elif t == "POINT":
                ms.add_point(tuple(e.dxf.location), **a)
            elif t == "TEXT":
                ms.add_text(e.dxf.text, tuple(e.dxf.insert), float(e.dxf.height), rotation=float(e.dxf.get("rotation", 0)), **a)
            elif t == "MTEXT":
                ms.add_mtext(e.text, tuple(e.dxf.insert), float(e.dxf.get("char_height", 1)), **a)
            else:
                uebersprungen[t] += 1
                continue
            n_ok += 1
        except Exception as ex:
            uebersprungen[t + " (Fehler)"] += 1
            if uebersprungen[t + " (Fehler)"] == 1:
                log(f"  DWG direkt: {t} nicht übernommen ({ex})")
    res = dwg.save(ziel, strict=False)
    log(f"  DWG direkt (R2000, Farben vereinfacht): {os.path.basename(ziel)} mit {n_ok} Elementen"
        + (f"; übersprungen: {dict(uebersprungen)}" if uebersprungen else ""))
    return ziel
