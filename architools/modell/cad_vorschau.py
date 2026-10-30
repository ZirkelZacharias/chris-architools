"""3D-Vorschau für „CAD zu Lasercut“ je Bauteilgruppe (Gelände, Wände, Decken, Dach …): jede Platte als Körper in Materialstärke,
die Oberseite mit ihrer Gravur (Materialdarstellung, Ritzlinien, Nummern) als Bild in Materialfarbe. Eine GLB je Gruppe, damit die
Oberfläche Gruppen ein- und ausblenden und das Dach anheben kann. Die Laserdateien bleiben davon unberührt."""
import math
import os

import numpy as np
import trimesh

from .geomutil import lines, polys

ATLAS = 4096


def _farbe(hexfarbe, faktor=1.0):
    h = (hexfarbe or "#d9c7a3").lstrip("#")
    return tuple(int(min(255, int(h[i:i + 2], 16) * faktor)) for i in (0, 2, 4))


def _welt(t, xy, z):
    """Teil-Koordinaten (x, y in der Teilebene, z entlang n ab s0) -> Modell-mm"""
    xy = np.asarray(xy, float)
    return np.outer(xy[:, 0], t["u"]) + np.outer(xy[:, 1], t["v"]) + np.outer(np.full(len(xy), t["s0"] + z), t["n"])


def _grav(t):
    return t.get("_grav0", t.get("gravieren")) or []


def _ritz(t):
    return t.get("_ritz0", t.get("ritzen")) or []


def _hat_gravur(t):
    return bool(_grav(t) or _ritz(t))


def gruppe_glb(teile, dicke, ziel, farbe, px_mm=3.0, max_px=900):
    """Eine Gruppe -> GLB-Datei oder None"""
    from PIL import Image, ImageDraw
    if not teile:
        return None
    grund = _farbe(farbe)
    seite = _farbe(farbe, 0.82)
    brand, ritz = _farbe(farbe, 0.35), _farbe(farbe, 0.55)
    # Körper (Seiten und Unterseite; Oberseite ohne Gravur gleich mit)
    V, F, C = [], [], []
    nv = 0
    oben = []
    for t in teile:
        for q in polys(t.get("poly0", t["poly"])):
            try:
                m = trimesh.creation.extrude_polygon(q, dicke)
            except Exception:
                continue
            P = m.vertices
            W = _welt(t, P[:, :2], P[:, 2])
            fn = m.face_normals
            # Oberseite der gravierten Teile kommt als Bild dazu: hier weglassen
            keep = ~((fn[:, 2] > 0.99) & _hat_gravur(t))
            fc = m.faces[keep]
            V.append(W)
            F.append(fc + nv)
            col = np.where((np.abs(fn[keep, 2]) > 0.99)[:, None], np.array(grund), np.array(seite))
            C.append(col)
            nv += len(W)
        if _hat_gravur(t):
            oben.append(t)
    sz = trimesh.Scene()
    if V:
        Vs, Fs = np.vstack(V), np.vstack(F)
        mat_k = trimesh.visual.material.PBRMaterial(baseColorFactor=[*grund, 255], metallicFactor=0.0, roughnessFactor=1.0,
                                                    emissiveFactor=[c / 255.0 * 0.45 for c in grund], doubleSided=True)
        koerper = trimesh.Trimesh(Vs, Fs, process=False, visual=trimesh.visual.TextureVisuals(material=mat_k))
        sz.add_geometry(koerper, node_name="Platten")
    if oben:
        # Bildatlas der Oberseiten
        f = px_mm
        for _ in range(8):
            lage, x, y, zeile = [], 0, 0, 0
            for t in oben:
                b = t.get("poly0", t["poly"]).bounds
                ff = min(f, max_px / max(b[2] - b[0], b[3] - b[1], 1e-6))
                w_, h_ = max(2, int(math.ceil((b[2] - b[0]) * ff)) + 2), max(2, int(math.ceil((b[3] - b[1]) * ff)) + 2)
                if x + w_ > ATLAS:
                    x, y, zeile = 0, y + zeile, 0
                lage.append((x, y, w_, h_, ff))
                x += w_
                zeile = max(zeile, h_)
            if y + zeile <= ATLAS:
                break
            f *= 0.75
            max_px = int(max_px * 0.75)
        AH = max(2, min(y + zeile, ATLAS))
        im = Image.new("RGB", (ATLAS, AH), grund)
        dr = ImageDraw.Draw(im)
        TV, TF, TU, nt = [], [], [], 0
        for t, (ax, ay, w_, h_, ff) in zip(oben, lage):
            p0 = t.get("poly0", t["poly"])
            x0, y0, x1, y1 = p0.bounds

            def pix(cs, ax=ax, ay=ay, ff=ff, x0=x0, y1=y1):
                return [(ax + 1 + (cx - x0) * ff, ay + 1 + (y1 - cy) * ff) for cx, cy in cs]
            for g in _grav(t):
                for c in polys(g):
                    if len(c.exterior.coords) >= 3:
                        dr.polygon(pix(c.exterior.coords), fill=brand)
                        for r in c.interiors:
                            dr.polygon(pix(r.coords), fill=grund)
            for l in _ritz(t):
                for ln in lines(l):
                    dr.line(pix(ln.coords), fill=ritz, width=max(1, int(round(0.25 * ff))))
            for q in polys(p0):
                try:
                    v2, f2 = trimesh.creation.triangulate_polygon(q)
                except Exception:
                    continue
                if not len(f2):
                    continue
                TV.append(_welt(t, v2, dicke + 0.01))
                TU.append(np.c_[(ax + 1 + (v2[:, 0] - x0) * ff) / ATLAS, 1.0 - (ay + 1 + (y1 - v2[:, 1]) * ff) / AH])
                TF.append(f2 + nt)
                nt += len(v2)
        if TV:
            mat = trimesh.visual.material.PBRMaterial(baseColorTexture=im, baseColorFactor=[255, 255, 255, 255], metallicFactor=0.0,
                                                      roughnessFactor=1.0, emissiveTexture=im, emissiveFactor=[0.45, 0.45, 0.45],
                                                      doubleSided=True)
            top = trimesh.Trimesh(np.vstack(TV), np.vstack(TF), process=False,
                                  visual=trimesh.visual.TextureVisuals(uv=np.vstack(TU), material=mat))
            sz.add_geometry(top, node_name="Oberseiten")
    if not sz.geometry:
        return None
    sz.export(ziel)
    return ziel


def gruppen_glb(teile, dicke, ordner, name, farbe, log=print):
    """-> {Gruppe: Pfad} für alle Teile mit Lage im Modell (u, v, n, s0)"""
    from .cad_bauteile import GRUPPEN
    mit_lage = [t for t in teile if "s0" in t and "u" in t]
    if not mit_lage:
        return {}
    out = {}
    for g in GRUPPEN:
        ts = [t for t in mit_lage if t.get("gruppe") == g]
        if not ts:
            continue
        ziel = os.path.join(ordner, f"{name}_vorschau_{g}.glb")
        if os.path.exists(ziel):
            os.remove(ziel)
        p = gruppe_glb(ts, dicke, ziel, farbe)
        if p:
            out[g] = p
    if out:
        log("  3D-Vorschau je Gruppe: " + ", ".join(f"{GRUPPEN[g]} ({os.path.getsize(p) / 1e6:.1f} MB)" for g, p in out.items()))
    return out
