"""PDF lesen und schreiben – ohne PyMuPDF (AGPL, ~115 MB).

Lesen: pypdfium2 (Apache-2.0/BSD, ~8 MB). Die Klassen unten ahmen den kleinen Ausschnitt der PyMuPDF-Schnittstelle nach, den das Programm
braucht (Seiten, Größe, Zeichenpfade, Text, Bild der Seite), damit der übrige Code unverändert bleibt:

    doc = ifcmap_pdf.open(pfad)        # len(doc), doc[i], for seite in doc, with ... as doc
    seite.rect                         # Rect (Punkte; y zeigt wie in PyMuPDF nach unten)
    seite.get_drawings()               # Liste von dict: items [("l", p0, p1), ("c", p0, c1, c2, p1)], fill, color, width, type, ...
    seite.get_text() / get_text("dict")
    seite.render(faktor)               # PIL-Bild (faktor = Pixel je Punkt)

Schreiben: schreiben(pfad, seiten, titel) – ein minimaler PDF-Schreiber für Werkstatt-PDFs (Vektorlinien und Flächen in RGB).
"""
import builtins
import ctypes
import math
import zlib
from collections import namedtuple

Point = namedtuple("Point", "x y")
Rect = namedtuple("Rect", "x0 y0 x1 y1")
Rect.width = property(lambda r: r.x1 - r.x0)
Rect.height = property(lambda r: r.y1 - r.y0)

BEZIER_SCHRITTE = 12


def _pdfium():
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw
    return pdfium, raw


def verfuegbar():
    try:
        _pdfium()
        return True
    except Exception:
        return False


def open(pfad):          # noqa: A001 – gleicher Name wie in PyMuPDF
    return Dokument(pfad)


class Dokument:
    def __init__(self, pfad):
        pdfium, _ = _pdfium()
        self._pdf = pdfium.PdfDocument(str(pfad))

    def __len__(self):
        return len(self._pdf)

    def __getitem__(self, i):
        if i < 0 or i >= len(self):
            raise IndexError(i)
        return Seite(self._pdf, i)

    def __iter__(self):
        for i in range(len(self)):
            yield self[i]

    def close(self):
        try:
            self._pdf.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _farbe(raw, fn, o):
    r, g, b, a = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
    if fn(o, ctypes.byref(r), ctypes.byref(g), ctypes.byref(b), ctypes.byref(a)):
        return (r.value / 255.0, g.value / 255.0, b.value / 255.0), a.value / 255.0
    return None, 1.0


def _mul(a, b):
    """Matrix a, danach b (PDF-Matrizen (a, b, c, d, e, f))"""
    return (a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3], a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5])


class Seite:
    def __init__(self, pdf, i):
        self._p = pdf[i]
        self._tp = None
        w, h = self._p.get_size()
        self.rect = Rect(0.0, 0.0, float(w), float(h))
        try:
            self._box = tuple(self._p.get_cropbox())            # (links, unten, rechts, oben)
        except Exception:
            self._box = (0.0, 0.0, float(w), float(h))
        try:
            self._rot = int(self._p.get_rotation()) % 360
        except Exception:
            self._rot = 0

    # PDF-Benutzerraum (y nach oben) -> Seitenraum wie in PyMuPDF (Ursprung oben links, gedreht wie angezeigt)
    def _punkt(self, x, y):
        l, u, r, o = self._box
        x0, y0 = x - l, o - y
        b0, h0 = r - l, o - u
        if self._rot == 90:
            return h0 - y0, x0
        if self._rot == 180:
            return b0 - x0, h0 - y0
        if self._rot == 270:
            return y0, b0 - x0
        return x0, y0

    def _objekte(self):
        """(Objekt, Matrix auf Seitenebene) für alle Seiten- und Formular-Objekte, verschachtelt aufgelöst"""
        _, R = _pdfium()
        out = []

        def lauf(anzahl, holen, M):
            for i in range(anzahl):
                o = holen(i)
                m = R.FS_MATRIX()
                R.FPDFPageObj_GetMatrix(o, ctypes.byref(m))
                mm = _mul((m.a, m.b, m.c, m.d, m.e, m.f), M)
                t = R.FPDFPageObj_GetType(o)
                if t == R.FPDF_PAGEOBJ_FORM:
                    lauf(R.FPDFFormObj_CountObjects(o), lambda j, o=o: R.FPDFFormObj_GetObject(o, j), mm)
                else:
                    out.append((o, t, mm))
        raw = self._p.raw
        lauf(R.FPDFPage_CountObjects(raw), lambda i: R.FPDFPage_GetObject(raw, i), (1, 0, 0, 1, 0, 0))
        return out

    # ---------------------------------------------------------------- Zeichenpfade
    def get_drawings(self):
        _, R = _pdfium()
        out = []
        for o, t, m in self._objekte():
            if t != R.FPDF_PAGEOBJ_PATH:
                continue
            n = R.FPDFPath_CountSegments(o)
            items, start, cur, bez = [], None, None, []
            for si in range(n):
                s = R.FPDFPath_GetPathSegment(o, si)
                ty = R.FPDFPathSegment_GetType(s)
                x, y = ctypes.c_float(), ctypes.c_float()
                R.FPDFPathSegment_GetPoint(s, ctypes.byref(x), ctypes.byref(y))
                px, py = x.value, y.value
                P = Point(*self._punkt(m[0] * px + m[2] * py + m[4], m[1] * px + m[3] * py + m[5]))
                if ty == R.FPDF_SEGMENT_MOVETO:
                    cur = start = P
                    bez = []
                elif ty == R.FPDF_SEGMENT_LINETO:
                    if cur is not None:
                        items.append(("l", cur, P))
                    else:
                        start = P
                    cur = P
                elif ty == R.FPDF_SEGMENT_BEZIERTO:
                    bez.append(P)
                    if len(bez) == 3:
                        items.append(("c", cur, bez[0], bez[1], bez[2]))
                        cur = bez[2]
                        bez = []
                if R.FPDFPathSegment_GetClose(s) and cur is not None and start is not None:
                    if math.hypot(cur.x - start.x, cur.y - start.y) > 1e-9:
                        items.append(("l", cur, start))
                    cur = start
            if not items:
                continue
            fm, sm = ctypes.c_int(), ctypes.c_int()
            R.FPDFPath_GetDrawMode(o, ctypes.byref(fm), ctypes.byref(sm))
            fuell, f_a = _farbe(R, R.FPDFPageObj_GetFillColor, o) if fm.value else (None, 1.0)
            strich, s_a = _farbe(R, R.FPDFPageObj_GetStrokeColor, o) if sm.value else (None, 1.0)
            w = ctypes.c_float()
            R.FPDFPageObj_GetStrokeWidth(o, ctypes.byref(w))
            skal = math.sqrt(abs(m[0] * m[3] - m[1] * m[2])) or 1.0
            typ = "fs" if (fuell is not None and strich is not None) else ("f" if fuell is not None else "s")
            out.append({"items": items, "fill": fuell, "color": strich, "width": w.value * skal if strich is not None else None,
                        "type": typ, "closePath": False, "fill_opacity": f_a if fuell is not None else None,
                        "stroke_opacity": s_a if strich is not None else None})
        return out

    # ---------------------------------------------------------------- Text
    def _textseite(self):
        if self._tp is None:
            self._tp = self._p.get_textpage()
        return self._tp

    def get_text(self, art="text"):
        if art == "dict":
            return self._text_dict()
        try:
            return self._textseite().get_text_range()
        except Exception:
            return ""

    def _text_dict(self):
        _, R = _pdfium()
        tp = self._textseite()
        zeilen = []
        for o, t, m in self._objekte():
            if t != R.FPDF_PAGEOBJ_TEXT:
                continue
            n = R.FPDFTextObj_GetText(o, tp.raw, None, 0)
            if not n or n <= 2:
                continue
            puffer = (ctypes.c_ushort * (n // 2 + 1))()
            R.FPDFTextObj_GetText(o, tp.raw, puffer, n)
            text = bytes(memoryview(puffer).cast("B"))[:n - 2].decode("utf-16le", errors="replace")
            gr = ctypes.c_float()
            R.FPDFTextObj_GetFontSize(o, ctypes.byref(gr))
            laenge = math.hypot(m[0], m[1]) or 1.0
            ox, oy = self._punkt(m[4], m[5])
            ex, ey = self._punkt(m[4] + m[0] / laenge, m[5] + m[1] / laenge)
            dx, dy = ex - ox, ey - oy
            fuell, _ = _farbe(R, R.FPDFPageObj_GetFillColor, o)
            fuell = fuell or (0.0, 0.0, 0.0)
            col = (int(round(fuell[0] * 255)) << 16) | (int(round(fuell[1] * 255)) << 8) | int(round(fuell[2] * 255))
            groesse = gr.value * laenge
            span = {"text": text, "origin": (ox, oy), "size": groesse, "color": col,
                    "bbox": (ox, oy - groesse, ox + groesse * 0.5 * len(text), oy)}
            zeilen.append({"dir": (dx, dy), "spans": [span]})
        return {"blocks": [{"lines": zeilen}] if zeilen else []}

    # ---------------------------------------------------------------- Bild
    def render(self, faktor):
        """Seite als PIL-Bild (RGB), faktor = Pixel je Punkt"""
        return self._p.render(scale=float(faktor)).to_pil().convert("RGB")


# ====================================================================== Schreiben
class SeiteSchreiben:
    """Eine Seite eines Werkstatt-PDFs: Breite/Höhe in Punkten, Zeichnen in Punkten mit Ursprung unten links."""

    def __init__(self, breite, hoehe):
        self.breite, self.hoehe = float(breite), float(hoehe)
        self.ops = []

    @staticmethod
    def _f(v):
        return ("%.3f" % v).rstrip("0").rstrip(".") if abs(v) >= 0.0005 else "0"

    def _pfad(self, ringe):
        ops = self.ops
        for pts in ringe:
            pts = list(pts)
            if len(pts) < 2:
                continue
            # schnell: je Ring ein Textstück (bei Zehntausenden Raster-Punkten zählt jede Mikrosekunde)
            ops.append("%.3f %.3f m %s" % (pts[0][0], pts[0][1], " ".join("%.3f %.3f l" % (x, y) for x, y in pts[1:])))

    def flaeche(self, ringe, rgb):
        """Fläche mit gerade/ungerade-Füllregel (Löcher bleiben frei), ohne Kontur"""
        ringe = [r for r in ringe if len(list(r)) >= 3]
        if not ringe:
            return
        self.ops.append("%s %s %s rg" % tuple(self._f(c) for c in rgb))
        self._pfad(ringe)
        self.ops.append("f*")

    def linien(self, polylinien, rgb, breite):
        """Offene Haarlinien (nicht geschlossen), Breite in Punkten"""
        polylinien = [p for p in polylinien if len(list(p)) >= 2]
        if not polylinien:
            return
        self.ops.append("%s %s %s RG" % tuple(self._f(c) for c in rgb))
        self.ops.append("%s w" % self._f(breite))
        self._pfad(polylinien)
        self.ops.append("S")


def schreiben(pfad, seiten, titel=""):
    """seiten: Liste SeiteSchreiben -> minimale, gültige PDF-Datei (Flate-komprimierte Inhalte)"""
    obj = []                                            # Bytes je Objekt; Objekt-Nr = Index + 1

    def neu(b):
        obj.append(b)
        return len(obj)
    katalog = neu(b"")                                  # 1: Katalog (später gefüllt)
    baum = neu(b"")                                     # 2: Seitenbaum
    kinder = []
    for s in seiten:
        inhalt = zlib.compress("\n".join(s.ops).encode("ascii"), 6)
        n_i = neu(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(inhalt) + inhalt + b"\nendstream")
        n_s = neu(("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.3f %.3f] /Resources << >> /Contents %d 0 R >>"
                   % (s.breite, s.hoehe, n_i)).encode("ascii"))
        kinder.append(n_s)
    obj[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    obj[1] = ("<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % k for k in kinder), len(kinder))).encode("ascii")
    info = ""
    if titel:
        t = "".join(c if ord(c) < 128 and c not in "()\\" else "?" for c in titel)
        info = "/Title (%s) " % t
    n_info = neu(("<< %s>>" % info).encode("ascii"))
    ausgabe = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    pos = []
    for i, b in enumerate(obj, 1):
        pos.append(len(ausgabe))
        ausgabe += b"%d 0 obj\n" % i + b + b"\nendobj\n"
    xref = len(ausgabe)
    ausgabe += b"xref\n0 %d\n0000000000 65535 f \n" % (len(obj) + 1)
    for p in pos:
        ausgabe += b"%010d 00000 n \n" % p
    ausgabe += (b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(obj) + 1, katalog, n_info, xref))
    with builtins.open(pfad, "wb") as f:
        f.write(bytes(ausgabe))
