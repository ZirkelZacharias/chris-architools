"""Die Figuren: Zirkel Zacharias (2D und schlecht gerendert in 3D) und seine platonische Freundin Gerda Geodreieck.
Alles wird beim ersten Gebrauch mit PIL/numpy gezeichnet (keine Bilddateien im Programm)."""
import math
import os

import numpy as np

ORDNER = os.path.join(os.path.expanduser("~"), ".architools")
PAPIER = (244, 241, 236)


AUFLOESUNG = 4        # gezeichnet wird 4-fach und dann weich verkleinert (kein Pixelbrei)


class Zeichner:
    """Wie ImageDraw, aber in Koordinaten von 96 × 96 und mit weichen Kanten (4-fach gezeichnet, dann verkleinert)."""

    def __init__(self, breite=96, hoehe=96, hintergrund=PAPIER, k=AUFLOESUNG, ausgabe=2):
        from PIL import Image, ImageDraw
        self.k, self.aus = k, ausgabe
        self.im = Image.new("RGB", (breite * k, hoehe * k), hintergrund)
        self.d = ImageDraw.Draw(self.im)

    def _p(self, v):
        if isinstance(v[0], (tuple, list)):
            return [(x * self.k, y * self.k) for x, y in v]
        if len(v) == 4:
            return [v[0] * self.k, v[1] * self.k, v[2] * self.k, v[3] * self.k]
        return [(v[0] * self.k, v[1] * self.k)]

    def line(self, xy, fill=None, width=1):
        self.d.line(self._p(xy), fill=fill, width=max(1, round(width * self.k)), joint="curve")

    def polygon(self, xy, fill=None, outline=None):
        self.d.polygon(self._p(xy), fill=fill, outline=None)
        if outline:
            self.d.line(self._p(list(xy) + [xy[0]]), fill=outline, width=self.k, joint="curve")

    def ellipse(self, xy, fill=None, outline=None):
        self.d.ellipse(self._p(xy), fill=fill, outline=outline, width=self.k if outline else 0)

    def rectangle(self, xy, fill=None, outline=None):
        self.d.rectangle(self._p(xy), fill=fill, outline=outline, width=self.k if outline else 0)

    def arc(self, xy, start, end, fill=None, width=1):
        self.d.arc(self._p(xy), start, end, fill=fill, width=max(1, round(width * self.k)))

    def text(self, xy, t, fill=None):
        from PIL import ImageFont
        try:
            font = ImageFont.load_default(size=9 * self.k)
        except Exception:
            font = None
        self.d.text((xy[0] * self.k, xy[1] * self.k), t, fill=fill, font=font)

    def fertig(self):
        from PIL import Image
        w, h = self.im.size
        z = (w // self.k * self.aus, h // self.k * self.aus)
        return self.im.resize(z, Image.LANCZOS)


def _speichern(frames, ziel, dauern, farben=64):
    """GIF mit gemeinsamer Palette (kein Flackern), weich verkleinerte Bilder."""
    from PIL import Image
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    frames = [f.convert("RGB") for f in frames]
    pal = frames[0].quantize(colors=farben, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    # Palette aus allen Bildern: nebeneinander legen und gemeinsam quantisieren
    w, h = frames[0].size
    streifen = Image.new("RGB", (w * len(frames), h))
    for i, f in enumerate(frames):
        streifen.paste(f, (i * w, 0))
    pal = streifen.quantize(colors=farben, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    q = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    q[0].save(ziel, save_all=True, append_images=q[1:], duration=dauern, loop=0, disposal=2)
    return ziel


# ------------------------------------------------------------------ Gerda Geodreieck (2D)
def gerda(ziel=os.path.join(ORDNER, "gerda_geodreieck.gif")):
    """Ein Geodreieck mit Kulleraugen und Schleife. Wippt, blinzelt zu anderen Zeiten als Zirkel Zacharias."""
    frames = []
    wipp = [0, 2, 4, 2, 0, -2, -4, -2]
    for i, w in enumerate(wipp):
        d = Zeichner()
        x0 = 14 + w // 2
        u = 88 - abs(w)
        d.polygon([(x0, 8), (x0, u), (84 + w // 2, u)], fill=(190, 230, 235), outline=(40, 90, 100))
        d.polygon([(x0 + 8, 30), (x0 + 8, u - 10), (60 + w // 2, u - 10)], fill=(225, 245, 247), outline=(120, 170, 180))
        for k in range(0, 70, 7):                                    # Skalenstriche an der Unterkante
            d.line([(x0 + 2 + k, u), (x0 + 2 + k, u - 5 - (3 if k % 14 == 0 else 0))], fill=(40, 90, 100))
        cx, cy = x0 + 24, 56
        for ex in (-8, 8):
            ax, ay = cx + ex, cy - 4
            if i == 2:
                d.line([(ax - 4, ay), (ax + 4, ay)], fill=(0, 0, 0), width=1.6)
            else:
                d.ellipse([ax - 5, ay - 5, ax + 5, ay + 5], fill=(255, 255, 255), outline=(0, 0, 0))
                px = ax + (2 if i % 4 < 2 else -2)
                d.ellipse([px - 2.2, ay - 2.2, px + 2.2, ay + 2.2], fill=(0, 0, 0))
        d.arc([cx - 7, cy + 2, cx + 7, cy + 12], 10, 170, fill=(110, 30, 50), width=1.6)
        d.polygon([(cx - 16, 30), (cx - 4, 36), (cx - 16, 42)], fill=(200, 60, 100), outline=(110, 20, 50))
        d.polygon([(cx + 8, 30), (cx - 4, 36), (cx + 8, 42)], fill=(200, 60, 100), outline=(110, 20, 50))
        d.ellipse([cx - 7, 33, cx - 1, 39], fill=(230, 100, 140))
        frames.append(d.fertig())
    return _speichern(frames, ziel, [130, 130, 130, 220, 130, 130, 90, 180])


# ---- Zirkel Zacharias, schlecht gerendert (3D)
class _Bau:
    """Kleiner Baukasten für die groben 3D-Figuren."""

    def __init__(self):
        self.M = []

    def kugel(self, r, pos, farbe, teilung=1):
        import trimesh
        m = trimesh.creation.icosphere(subdivisions=teilung, radius=r)
        m.apply_translation(pos)
        self.M.append((m, farbe))

    def stab(self, a, b, r, farbe):
        import trimesh
        a, b = np.array(a, float), np.array(b, float)
        L = np.linalg.norm(b - a)
        m = trimesh.creation.cylinder(radius=r, height=L, sections=5)
        T = trimesh.geometry.align_vectors([0, 0, 1], (b - a) / L)
        T[:3, 3] = (a + b) / 2
        m.apply_transform(T)
        self.M.append((m, farbe))

    def quader(self, ausdehnung, pos, farbe):
        import trimesh
        m = trimesh.creation.box(extents=ausdehnung)
        m.apply_translation(pos)
        self.M.append((m, farbe))


def _netze():
    """Zirkel Zacharias."""
    B = _Bau()
    kopf = (0.0, 0.0, 2.3)
    B.kugel(0.8, kopf, (240, 200, 60), 1)
    B.stab(kopf, (-1.3, 0.0, 0.0), 0.16, (90, 90, 100))
    B.stab(kopf, (1.3, 0.0, 0.0), 0.16, (90, 90, 100))
    B.stab((-0.7, 0, 1.0), (0.7, 0, 1.0), 0.07, (150, 150, 160))
    B.kugel(0.2, (-1.32, 0, 0.0), (30, 30, 30), 0)
    B.kugel(0.22, (1.32, 0, 0.0), (200, 60, 40), 0)
    for ex in (-0.3, 0.3):
        B.kugel(0.23, (ex, -0.62, 2.45), (255, 255, 255), 1)
        B.kugel(0.1, (ex, -0.82, 2.45), (0, 0, 0), 0)
    return B.M


def _netze_rosi():
    """Rosi Radiergummi: stehender Radiergummi – rosa Kopf, blaue Papierhülle mit Gesicht, Schleife, kleine Beine und Arme."""
    B = _Bau()
    rosa, blau = (240, 150, 175), (60, 110, 190)
    B.quader((1.1, 0.85, 1.9), (0, 0, 1.25), rosa)                     # Gummi
    B.quader((1.16, 0.91, 1.1), (0, 0, 0.8), blau)                     # Papierhülle (untere Hälfte)
    for ex in (-0.28, 0.28):                                           # Augen auf der Hülle
        B.kugel(0.2, (ex, -0.5, 1.05), (255, 255, 255), 1)
        B.kugel(0.09, (ex + 0.02, -0.68, 1.05), (0, 0, 0), 0)
    B.quader((0.34, 0.06, 0.08), (0, -0.47, 0.62), (120, 20, 40))      # Mund
    B.quader((1.1, 0.85, 0.06), (0, 0, 2.22), (225, 130, 155))         # abgeschrägte Kante oben
    B.kugel(0.17, (-0.22, -0.05, 2.35), (200, 40, 90), 0)              # Schleife
    B.kugel(0.17, (0.22, -0.05, 2.35), (200, 40, 90), 0)
    B.kugel(0.1, (0.0, -0.05, 2.35), (235, 110, 150), 0)
    B.stab((-0.55, 0, 1.0), (-1.05, 0, 0.55), 0.07, (90, 90, 100))     # Arme
    B.stab((0.55, 0, 1.0), (1.05, 0, 0.55), 0.07, (90, 90, 100))
    B.stab((-0.25, 0, 0.25), (-0.25, 0, -0.1), 0.09, (60, 60, 70))     # Beine
    B.stab((0.25, 0, 0.25), (0.25, 0, -0.1), 0.09, (60, 60, 70))
    return B.M


def _render3d(gruppen, ziel, breite=160, n=14, skala=34):
    """Absichtlich schlecht gerendert: wenig Flächen, Eckpunkte auf ein grobes Raster gerastet (PS1-Wackeln), flache
    Schattierung in 3 Stufen, Kanten ohne Glättung, ungleichmäßige Bildzeiten – aber in ordentlicher Auflösung.
    gruppen: [(Netze, x-Versatz, Drehphase)] – jede Figur dreht sich um ihre eigene Achse."""
    from PIL import Image, ImageDraw
    R = 160
    frames, dauern = [], []
    rng = np.random.default_rng(67)
    licht = np.array([0.4, -0.7, 0.6])
    licht /= np.linalg.norm(licht)
    neig = math.radians(-12)
    Rx = np.array([[1, 0, 0], [0, math.cos(neig), -math.sin(neig)], [0, math.sin(neig), math.cos(neig)]])
    for i in range(n):
        tris = []
        for netze, versatz, phase in gruppen:
            a = 2 * math.pi * i / n + phase
            ca, sa = math.cos(a), math.sin(a)
            Rz = np.array([[ca, -sa, 0], [sa, ca, 0], [0, 0, 1]])
            for m, farbe in netze:
                v = ((m.vertices @ Rz.T) + np.array([versatz, 0, 0])) @ Rx.T
                for fl in m.faces:
                    p = v[fl]
                    nrm = np.cross(p[1] - p[0], p[2] - p[0])
                    l = np.linalg.norm(nrm)
                    if l < 1e-9:
                        continue
                    s = float((nrm / l) @ licht)
                    stufe = 0.45 if s < 0.0 else (0.7 if s < 0.45 else 1.0)       # drei Helligkeitsstufen
                    tris.append((float(p[:, 1].mean()), p, tuple(int(c * stufe) for c in farbe)))
        tris.sort(key=lambda t: -t[0])                                         # Maler: hinten zuerst
        im = Image.new("RGB", (breite, R), PAPIER)
        d = ImageDraw.Draw(im)
        for _, p, farbe in tris:
            xy = [(round((breite / 2 + q[0] * skala) / 2) * 2, round((R - 12 - q[2] * skala) / 2) * 2) for q in p]   # Wackeln
            d.polygon(xy, fill=farbe)
        frames.append(im)
        dauern.append(int(rng.choice([40, 40, 70, 160, 250])))
    return _speichern(frames, ziel, dauern)


def zacharias_3d(ziel=os.path.join(ORDNER, "zacharias_3d.gif"), n=14):
    return _render3d([(_netze(), 0.0, 0.0)], ziel, 160, n)


def rosi_3d(ziel=os.path.join(ORDNER, "rosi_3d.gif"), n=14):
    return _render3d([(_netze_rosi(), 0.0, 0.0)], ziel, 160, n)


def duo_3d(ziel=os.path.join(ORDNER, "duo_3d.gif"), n=14):
    """Beide zusammen, jede(r) dreht sich um die eigene Achse."""
    return _render3d([(_netze(), -1.9, 0.0), (_netze_rosi(), 1.9, math.pi / 3)], ziel, 288, n, skala=34)


# ------------------------------------------------------------------ Duo
def duo(ziel=os.path.join(ORDNER, "duo.gif")):
    from PIL import Image
    from . import eier
    z = Image.open(eier.maskott_pfad())
    gerda_pfad = pfad("gerda")
    g = Image.open(gerda_pfad)
    n = max(z.n_frames, g.n_frames)
    frames = []
    for i in range(n):
        z.seek(i % z.n_frames)
        g.seek((i + 3) % g.n_frames)
        zi, gi = z.convert("RGB"), g.convert("RGB")
        bild = Image.new("RGB", (zi.width + gi.width, max(zi.height, gi.height)), PAPIER)
        bild.paste(zi, (0, 0))
        bild.paste(gi, (zi.width, 0))
        frames.append(bild)
    return _speichern(frames, ziel, [150, 110, 190, 110, 150, 90, 190, 110])


def icon(ziel=os.path.join(ORDNER, "zacharias_icon.webp")):
    """Zirkel Zacharias als kleines Icon: dieselbe 3D-Figur, zugeschnitten und mit durchsichtigem Hintergrund."""
    if os.path.exists(ziel):
        return ziel
    import numpy as np
    from PIL import Image
    quelle = Image.open(pfad("3d"))
    bilder, dauern = [], []
    for i in range(quelle.n_frames):
        quelle.seek(i)
        bilder.append(quelle.convert("RGB").copy())
        dauern.append(quelle.info.get("duration", 100))
    bg = np.array(PAPIER, dtype=int)
    masken = [np.abs(np.array(b).astype(int) - bg).sum(2) > 24 for b in bilder]
    alle = np.any(masken, axis=0)
    ys, xs = np.where(alle)
    x0, x1, y0, y1 = max(xs.min() - 2, 0), xs.max() + 3, max(ys.min() - 2, 0), ys.max() + 3
    ausgabe = []
    for b, m in zip(bilder, masken):
        a = np.array(b.convert("RGBA"))
        a[~m, 3] = 0
        ausgabe.append(Image.fromarray(a).crop((x0, y0, x1, y1)))
    ausgabe[0].save(ziel, save_all=True, append_images=ausgabe[1:], duration=dauern, loop=0, lossless=True)
    return ziel


def pfad(art):
    """art: 'gerda' | '3d' | 'duo' | 'rosi' | 'duo3d' -> GIF-Pfad (wird bei Bedarf gezeichnet)"""
    f = {"3d": ("zacharias_3d.gif", zacharias_3d), 
         "rosi": ("rosi_3d.gif", rosi_3d), "duo3d": ("duo_3d.gif", duo_3d)}[art]
    p = os.path.join(ORDNER, f[0])
    if not os.path.exists(p):
        f[1](p)
    return p
