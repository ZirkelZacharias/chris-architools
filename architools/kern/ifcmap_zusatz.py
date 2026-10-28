# -*- coding: utf-8 -*-
"""IFCmap - Zusatzplaene (PDF, Bilder) einpassen und als eigene DXF ausgeben.

Ein Zusatzplan ist ein Plan, den es nicht als Geodaten gibt: ein Lageplan als PDF (z. B. Planung Pankower Tor), ein Screenshot, ein Foto
einer Karte. Er wird ueber Passpunkte (ein Punkt im Plan = ein Punkt im Gebiet) im Projekt-KBS verortet - Verschiebung, Drehung und
Massstab, nie verzerrt - und wie alle anderen Ausgaben im lokalen Nullpunkt (E0/N0) in eine eigene DXF geschrieben:
  * PDF mit Vektorzeichnung -> echte DXF-Linien, Schraffuren und Text (Layer je Plan und Farbgruppe)
  * Bild (oder PDF ohne Vektoren) -> PNG + DXF-Bildverweis + Umriss-Rahmen + World-File (.pgw)

Ein Plan ist ein dict:
  datei, seite (1 = erste), name, modus ("vektor" | "bild"), punkte [{"x","y","E","N"}] (x, y in Planeinheiten, y nach unten:
  PDF = Punkt (1/72 Zoll), Bild = Pixel), massstab (None oder Zahl N fuer 1:N, nur PDF), drehung (Grad gegen den Uhrzeigersinn,
  nur zusammen mit massstab), weiss_ausblenden (bool), text (bool)."""
import math
import os
import time
import re

import numpy as np

PT_M = 0.0254 / 72.0                  # ein PDF-Punkt auf dem Papier in Metern
MAX_BILD = 4096                       # laengste Seite des ausgegebenen PNG (Pixel)
MAX_PFADE = 400000
MAX_TEXTE = 8000


# ------------------------------------------------------------------ Dateien lesen
def _pdf():
    try:
        import pymupdf
        return pymupdf
    except ImportError:
        try:
            import fitz
            return fitz
        except ImportError:
            return None


def ist_pdf(datei):
    return str(datei).lower().endswith(".pdf")


def pdf_vorhanden():
    return _pdf() is not None


def _pdf_oeffnen(datei):
    m = _pdf()
    if m is None:
        raise RuntimeError("PDF-Plaene brauchen das Paket PyMuPDF (Windows: py -3.12 -m pip install pymupdf; Mac: python3 -m pip install pymupdf). "
                           "Bilder (PNG, JPG) gehen auch ohne.")
    return m.open(datei)


def seitenzahl(datei):
    if ist_pdf(datei):
        with _pdf_oeffnen(datei) as doc:
            return len(doc)
    return 1


def seiten_groesse(datei, seite=1):
    """(Breite, Hoehe) in Planeinheiten: PDF = Punkte, Bild = Pixel"""
    if ist_pdf(datei):
        with _pdf_oeffnen(datei) as doc:
            r = doc[max(0, seite - 1)].rect
            return float(r.width), float(r.height)
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(datei) as im:
        return float(im.width), float(im.height)


def vektor_anzahl(datei, seite=1):
    """Anzahl der Zeichenpfade einer PDF-Seite (0 = reines Bild/Scan)"""
    if not ist_pdf(datei):
        return 0
    with _pdf_oeffnen(datei) as doc:
        try:
            return len(doc[max(0, seite - 1)].get_drawings())
        except Exception:
            return 0


def bild_laden(datei, seite=1, max_px=1600, weiss_transparent=False, tol=18):
    """Seite als PIL-Bild; Rueckgabe (bild, px_je_einheit)"""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    if ist_pdf(datei):
        with _pdf_oeffnen(datei) as doc:
            p = doc[max(0, seite - 1)]
            r = p.rect
            f = max_px / max(r.width, r.height)
            pix = p.get_pixmap(matrix=_pdf().Matrix(f, f), alpha=False)
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        faktor = im.width / float(r.width)
    else:
        with Image.open(datei) as o:
            im = o.convert("RGBA" if "A" in o.getbands() else "RGB")
            w0 = im.width
        f = min(1.0, max_px / float(max(im.size)))
        if f < 1.0:
            im = im.resize((max(1, int(im.width * f)), max(1, int(im.height * f))), Image.LANCZOS)
        faktor = im.width / float(w0)
    if weiss_transparent:
        im = weiss_frei(im, tol)
    return im, faktor


def weiss_frei(im, tol=18):
    """Fast weisse Pixel durchsichtig machen (Screenshots und Plaene mit weissem Grund)"""
    a = np.asarray(im.convert("RGBA")).copy()
    weiss = (a[:, :, :3] >= 255 - tol).all(axis=2)
    a[weiss, 3] = 0
    from PIL import Image
    return Image.fromarray(a, "RGBA")


# ------------------------------------------------------------------ Passpunkte -> Transformation
def transformation(plan):
    """-> (a, b): komplexe Zahlen; Welt = a * (x - 1j*y) + b (E = Re, N = Im). Wirft ValueError, wenn die Angaben nicht reichen."""
    pts = [p for p in (plan.get("punkte") or []) if all(k in p for k in ("x", "y", "E", "N"))]
    z = np.array([complex(p["x"], -p["y"]) for p in pts])
    w = np.array([complex(p["E"], p["N"]) for p in pts])
    n = len(pts)
    if n >= 2 and abs(z[1:] - z[0]).max() > 1e-9:
        zm, wm = z.mean(), w.mean()
        zz = z - zm
        a = np.sum((w - wm) * np.conj(zz)) / np.sum(np.abs(zz) ** 2)         # Kleinste Quadrate fuer Drehung + Massstab
        if abs(a) < 1e-12:
            raise ValueError("Die Passpunkte liegen in der Karte alle an derselben Stelle.")
        return complex(a), complex(wm - a * zm)
    if n >= 1 and plan.get("massstab") and ist_pdf(plan.get("datei", "")):
        s = PT_M * float(plan["massstab"])
        a = s * complex(math.cos(math.radians(float(plan.get("drehung") or 0))), math.sin(math.radians(float(plan.get("drehung") or 0))))
        return a, complex(w[0] - a * z[0])
    raise ValueError("Zu wenige Passpunkte: zwei Punkte (oder bei PDF ein Punkt plus Massstab) setzen.")


def abbildung(plan):
    """Funktion f(x, y) -> (E, N) (Arrays moeglich)"""
    a, b = transformation(plan)

    def f(x, y):
        w = a * (np.asarray(x, float) - 1j * np.asarray(y, float)) + b
        return w.real, w.imag
    return f


def kenngroessen(plan):
    """Massstab (m je Planeinheit), Drehung (Grad), Umriss der Seite (4 Punkte E/N) - fuer Anzeige und Pruefung"""
    a, b = transformation(plan)
    w, h = seiten_groesse(plan["datei"], int(plan.get("seite") or 1))
    f = abbildung(plan)
    ecken = [f(0, 0), f(w, 0), f(w, h), f(0, h)]
    kenn = dict(m_je_einheit=abs(a), drehung=math.degrees(math.atan2(a.imag, a.real)), umriss=[(float(x), float(y)) for x, y in ecken],
                breite_m=w * abs(a), hoehe_m=h * abs(a))
    if ist_pdf(plan["datei"]):
        kenn["massstab_1_zu"] = abs(a) / PT_M
    return kenn


# ------------------------------------------------------------------ Hilfen
def sauberer_name(s, fallback="Plan"):
    n = re.sub(r"[^0-9A-Za-z_]+", "_", str(s or "").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("Ä", "Ae")
               .replace("Ö", "Oe").replace("Ü", "Ue").replace("ß", "ss")).strip("_")
    return n[:40] or fallback


def _rgb255(c, standard=(0, 0, 0)):
    if c is None:
        return standard
    try:
        return tuple(max(0, min(255, int(round(float(v) * 255)))) for v in c[:3])
    except Exception:
        return standard


def _palette(zaehler, n):
    """zaehler: {rgb: Anzahl} -> {rgb: Vertreter}; die n haeufigsten bleiben, der Rest wird der naechsten Farbe zugeordnet"""
    if not zaehler:
        return {}
    haupt = [c for c, _ in sorted(zaehler.items(), key=lambda kv: -kv[1])[:n]]
    h = np.array(haupt, float)
    abb = {}
    for c in zaehler:
        if c in haupt:
            abb[c] = c
        else:
            abb[c] = haupt[int(np.argmin(((h - np.array(c, float)) ** 2).sum(axis=1)))]
    return abb


def _bezier(p0, p1, p2, p3, n=6):
    t = np.linspace(0.0, 1.0, n + 1)[1:, None]
    p0, p1, p2, p3 = (np.asarray(p, float) for p in (p0, p1, p2, p3))
    pts = (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3
    return [tuple(p) for p in pts]


def _pfad_zu_linienzuegen(items):
    """Zeichenpfad (PyMuPDF-Items) -> Liste von Punktfolgen (Planeinheiten, y nach unten)"""
    zuege, akt = [], []
    for it in items:
        art = it[0]
        if art == "l":
            p1, p2 = (it[1].x, it[1].y), (it[2].x, it[2].y)
            if not akt or math.hypot(akt[-1][0] - p1[0], akt[-1][1] - p1[1]) > 1e-6:
                if len(akt) > 1:
                    zuege.append(akt)
                akt = [p1]
            akt.append(p2)
        elif art == "c":
            p1, c1, c2, p2 = ((q.x, q.y) for q in it[1:5])
            if not akt or math.hypot(akt[-1][0] - p1[0], akt[-1][1] - p1[1]) > 1e-6:
                if len(akt) > 1:
                    zuege.append(akt)
                akt = [p1]
            akt.extend(_bezier(p1, c1, c2, p2))
        elif art == "re":
            if len(akt) > 1:
                zuege.append(akt)
            r = it[1]
            zuege.append([(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1), (r.x0, r.y0)])
            akt = []
        elif art == "qu":
            if len(akt) > 1:
                zuege.append(akt)
            q = it[1]
            zuege.append([(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y), (q.ul.x, q.ul.y)])
            akt = []
    if len(akt) > 1:
        zuege.append(akt)
    return zuege


def _ist_weiss(rgb, tol=12):
    return all(v >= 255 - tol for v in rgb)


# ------------------------------------------------------------------ Vektor-Plan -> DXF
def zeichne_vektoren(z, plan, log=print, max_farben=12):
    """PDF-Seite als Linien, Schraffuren und Text in den Zeichner z (Klasse Zeichner aus ifcmap_kern). -> dict mit Zaehlern"""
    from shapely.geometry import Polygon
    from shapely.validation import make_valid
    name = sauberer_name(plan.get("name"))
    f = abbildung(plan)
    a, b = transformation(plan)
    seite = int(plan.get("seite") or 1)
    weiss_aus = plan.get("weiss_ausblenden", True)
    zaehl = dict(flaechen=0, linien=0, texte=0, weiss=0, ausserhalb=0)
    with _pdf_oeffnen(plan["datei"]) as doc:
        page = doc[max(0, seite - 1)]
        t_lesen = time.time()
        pfade = page.get_drawings()
        if len(pfade) > MAX_PFADE:
            log("  Zusatzplan %s: %d Zeichenpfade - es werden nur die ersten %d uebernommen" % (name, len(pfade), MAX_PFADE))
            pfade = pfade[:MAX_PFADE]
        # Farben zaehlen -> Farbgruppen (Layer)
        fz, lz = {}, {}
        for p in pfade:
            if p.get("fill") is not None:
                c = _rgb255(p["fill"])
                fz[c] = fz.get(c, 0) + 1
            if p.get("color") is not None:
                c = _rgb255(p["color"])
                lz[c] = lz.get(c, 0) + 1
        fab, lab = _palette(fz, max_farben), _palette(lz, max_farben)
        seite_flaeche = page.rect.width * page.rect.height
        offen = {}                                              # offene Linien je Layer sammeln und am Ende zusammenhaengend verbinden
        t_schleife = time.time()
        log("  Zusatzplan %s: %d Zeichenpfade gelesen (%.0f s)" % (name, len(pfade), t_schleife - t_lesen))
        for n_p, p in enumerate(pfade):
            if n_p and n_p % 50000 == 0:
                log("    ... %d von %d Pfaden (%.0f s)" % (n_p, len(pfade), time.time() - t_schleife))
            zuege = _pfad_zu_linienzuegen(p.get("items") or [])
            if not zuege:
                continue
            fuell = _rgb255(p["fill"]) if p.get("fill") is not None else None
            if fuell is not None:
                if weiss_aus and _ist_weiss(fuell):
                    fuell_zeichnen = False
                    zaehl["weiss"] += 1
                else:
                    fuell_zeichnen = True
                if fuell_zeichnen:
                    for zug in zuege:
                        if len(zug) < 3:
                            continue
                        xs, ys = f(np.array([q[0] for q in zug]), np.array([q[1] for q in zug]))
                        try:
                            poly = Polygon(list(zip(xs, ys)))
                            if not poly.is_valid:
                                poly = make_valid(poly)
                            if poly.is_empty or poly.area < 1e-4:
                                continue
                        except Exception:
                            continue
                        rep = fab[fuell]
                        alpha = p.get("fill_opacity")
                        trans = 0.0 if alpha is None else max(0.0, min(1.0, 1.0 - float(alpha)))
                        zaehl["flaechen"] += z.flaeche(poly, "2D_Zusatz_%s_Flaeche_%02X%02X%02X" % ((name,) + rep), rep, transparenz=trans,
                                                        min_flaeche=0.0, min_loch=0.0, sauber=False)
            if p.get("color") is not None and (p.get("type") in ("s", "fs") or p.get("fill") is None):
                strich = _rgb255(p["color"])
                if weiss_aus and _ist_weiss(strich):
                    continue
                rep = lab[strich]
                geschl = bool(p.get("closePath"))
                for zug in zuege:
                    xs, ys = f(np.array([q[0] for q in zug]), np.array([q[1] for q in zug]))
                    ko = np.column_stack([xs, ys])
                    lay = "2D_Zusatz_%s_Linie_%02X%02X%02X" % ((name,) + rep)
                    if not geschl and len(ko) >= 2:
                        offen.setdefault(lay, (rep, []))[1].append(ko)
                    elif z.linie(ko, lay, rep, geschlossen=geschl):
                        zaehl["linien"] += 1
        # Zusammenhaengende offene Linien (Strassenzuege, Gebaeudekanten aus Einzelstrichen) zu langen Polylinien verbinden:
        # weniger Objekte, kleinere Datei, schnellerer Import
        n_roh = sum(len(v[1]) for v in offen.values())
        for lay, (rep, listen) in offen.items():
            try:
                import shapely
                teile = shapely.line_merge(shapely.multilinestrings([shapely.linestrings(k) for k in listen if len(k) >= 2]))
                teile = [g for g in (teile.geoms if hasattr(teile, "geoms") else [teile]) if g.geom_type == "LineString"]
                koords = [np.asarray(g.coords) for g in teile]
            except Exception:
                koords = listen
            for ko in koords:
                if z.linie(ko, lay, rep, geschlossen=False):
                    zaehl["linien"] += 1
        if n_roh:
            log("  Zusatzplan %s: %d Einzelstriche zu %d Linien verbunden (%.0f s)" % (name, n_roh, zaehl["linien"], time.time() - t_schleife))
        if plan.get("text", True):
            try:
                td = page.get_text("dict")
            except Exception:
                td = {"blocks": []}
            for blk in td.get("blocks", []):
                for ln in blk.get("lines", []):
                    dx, dy = ln.get("dir", (1.0, 0.0))
                    for sp in ln.get("spans", []):
                        t = (sp.get("text") or "").strip()
                        if not t or zaehl["texte"] >= MAX_TEXTE:
                            continue
                        ox, oy = sp.get("origin", (sp["bbox"][0], sp["bbox"][3]))
                        e, n = f(ox, oy)
                        winkel = math.degrees(math.atan2((a * complex(dx, -dy)).imag, (a * complex(dx, -dy)).real))
                        hoehe = float(sp.get("size", 8.0)) * abs(a)
                        col = sp.get("color", 0)
                        rgb = ((col >> 16) & 255, (col >> 8) & 255, col & 255)
                        layer = z.layer("2D_Zusatz_%s_Text" % name, rgb)
                        x0, y0 = z.loc(np.array([[float(e), float(n)]]))[0]
                        te = z.msp.add_text(t, height=max(hoehe, 0.01), rotation=winkel, dxfattribs={"layer": layer, "insert": (x0, y0)})
                        te.rgb = rgb
                        zaehl["texte"] += 1
    return zaehl


# ------------------------------------------------------------------ Bild-Plan -> PNG + DXF-Bildverweis
def schreibe_bild(z, plan, ordner, log=print, praefix=""):
    """Bild/PDF-Seite als PNG, DXF-IMAGE und Rahmen; World-File daneben. -> Liste der geschriebenen Dateien (ohne die DXF selbst)"""
    name = sauberer_name(plan.get("name"))
    a, b = transformation(plan)
    im, faktor = bild_laden(plan["datei"], int(plan.get("seite") or 1), MAX_BILD, bool(plan.get("weiss_ausblenden", False)))
    png = os.path.join(ordner, "%sifcmap_zusatz_%s.png" % (praefix, name))
    im.save(png)
    W, H = im.size
    # Pixel (Spalte, Zeile) -> Plan-Einheit (/faktor) -> Welt
    unten_links = a * complex(0.0, -H / faktor) + b
    ll = z.loc(np.array([[unten_links.real, unten_links.imag]]))[0]
    breite_m, hoehe_m = W / faktor * abs(a), H / faktor * abs(a)
    winkel = math.degrees(math.atan2(a.imag, a.real))
    layer = z.layer("2D_Zusatz_%s_Bild" % name, (120, 120, 120))
    idef = z.doc.add_image_def(filename=os.path.basename(png), size_in_pixel=(W, H), name="ifcmap_zusatz_%s" % name)
    z.msp.add_image(idef, insert=(ll[0], ll[1]), size_in_units=(breite_m, hoehe_m), rotation=winkel, dxfattribs={"layer": layer})
    # Rahmen: bleibt auch dann sichtbar, wenn das CAD-Programm Bilder aus DXF nicht uebernimmt
    f = abbildung(plan)
    w0, h0 = seiten_groesse(plan["datei"], int(plan.get("seite") or 1))
    ex, ey = f([0, w0, w0, 0, 0], [0, 0, h0, h0, 0])
    z.linie(np.column_stack([ex, ey]), "2D_Zusatz_%s_Rahmen" % name, (200, 60, 60))
    # World-File (Drehung moeglich): Pixel (Spalte c, Zeile r) -> E = A c + B r + C, N = D c + E r + F
    ar, ai = a.real / faktor, a.imag / faktor
    A, B, D, E = ar, ai, ai, -ar
    C, F = b.real + 0.5 * (A + B), b.imag + 0.5 * (D + E)
    pgw = os.path.splitext(png)[0] + ".pgw"
    with open(pgw, "w") as fh:
        fh.write("\n".join("%.9f" % v for v in (A, D, B, E, C, F)) + "\n")
    log("  Zusatzplan %s: Bild %dx%d Pixel, %.2f m je Pixel, %.0f x %.0f m, gedreht um %.1f Grad (PNG und World-File liegen neben der DXF)"
        % (name, W, H, abs(a) / faktor, breite_m, hoehe_m, winkel))
    return [png, pgw]


# ------------------------------------------------------------------ Ausgabe
def pruefe_lage(d, plan, log=print):
    """Warnung, wenn der Plan nicht im Gebiet liegt oder der Massstab abwegig ist"""
    from shapely.geometry import Polygon, box
    try:
        k = kenngroessen(plan)
    except Exception as e:
        log("  Zusatzplan %s: Passpunkte unvollstaendig (%s)" % (plan.get("name"), e))
        return False
    um = Polygon(k["umriss"])
    gebiet = box(d.xmin, d.ymin, d.xmax, d.ymax)
    if um.is_empty:
        return False
    if not um.intersects(gebiet):
        log("  WARNUNG Zusatzplan %s: liegt vollstaendig ausserhalb des Gebiets (Abstand %.0f m) - Passpunkte pruefen" % (plan.get("name"), um.distance(gebiet)))
    elif um.intersection(gebiet).area < 0.05 * um.area:
        log("  Zusatzplan %s: nur ein kleiner Teil (%.0f %%) liegt im Gebiet" % (plan.get("name"), 100 * um.intersection(gebiet).area / um.area))
    if "massstab_1_zu" in k:
        log("  Zusatzplan %s: entspricht Massstab 1:%.0f bei Ausdruck in Originalgroesse, Drehung %.1f Grad" % (plan.get("name"), k["massstab_1_zu"], k["drehung"]))
    return True


def schreibe_zusatzplaene(d, plaene, ordner, log=print, praefix="", Zeichner=None):
    """Je Plan eine DXF ifcmap_zusatz_<name>.dxf (plus PNG/PGW bei Bildern). -> Liste der erzeugten Dateien"""
    if Zeichner is None:
        import ifcmap_kern as K
        Zeichner = K.Zeichner
    erzeugt, benutzt = [], set()
    for plan in plaene:
        if not plan.get("datei") or not os.path.exists(plan["datei"]):
            log("  Zusatzplan %s: Datei nicht gefunden (%s) - uebersprungen" % (plan.get("name") or "?", plan.get("datei")))
            continue
        name = sauberer_name(plan.get("name"))
        n0 = name
        i = 2
        while name in benutzt:
            name = "%s_%d" % (n0, i)
            i += 1
        benutzt.add(name)
        plan = dict(plan, name=name)
        try:
            transformation(plan)
        except ValueError as e:
            log("  Zusatzplan %s: %s - uebersprungen" % (name, e))
            continue
        pruefe_lage(d, plan, log)
        z = Zeichner(d)
        try:
            modus = plan.get("modus") or "bild"
            if modus == "vektor" and ist_pdf(plan["datei"]):
                k = zeichne_vektoren(z, plan, log)
                if k["flaechen"] + k["linien"] + k["texte"] == 0:
                    log("  Zusatzplan %s: keine Vektoren gefunden (Scan?) - es wird stattdessen das Bild eingefuegt" % name)
                    dateien = schreibe_bild(z, plan, ordner, log, praefix)
                else:
                    dateien = []
                    log("  Zusatzplan %s: %d Schraffuren, %d Linien, %d Texte (%d weisse Flaechen weggelassen)"
                        % (name, k["flaechen"], k["linien"], k["texte"], k["weiss"]))
            else:
                dateien = schreibe_bild(z, plan, ordner, log, praefix)
            pfad = os.path.join(ordner, "%sifcmap_zusatz_%s.dxf" % (praefix, name))
            t_sp = time.time()
            z.doc.saveas(pfad)
            log("  Zusatzplan: %s (%.1f MB, Speichern %.0f s)" % (os.path.basename(pfad), os.path.getsize(pfad) / 1e6, time.time() - t_sp))
            erzeugt.append(pfad)
            erzeugt.extend(dateien)
        except Exception as e:
            log("  FEHLER beim Zusatzplan %s: %s" % (name, e))
    return erzeugt
