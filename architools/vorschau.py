"""Vorschau der Umgebungsdaten: 2D-Plan (PNG) und 3D-Modell (GLB) aus den geladenen IFCmap-Daten."""
import os

import numpy as np

from .projekt import kern


def _farbe(K, kat):
    try:
        return tuple(int(x) for x in K.IFC_FARBEN.get(kat) or K.kat_info(kat)[1])
    except Exception:
        return (200, 200, 200)


def _tri(poly):
    """Polygon (Nx3) -> Dreiecke (Fächer; für die Vorschau genügt das)."""
    p = np.asarray(poly, float)
    if len(p) < 3:
        return []
    return [(p[0], p[i], p[i + 1]) for i in range(1, len(p) - 1)]


def _licht(tris, rgb):
    """Flächenfarbe mit einfacher Schattierung nach Neigung."""
    licht = np.array([-0.45, -0.55, 0.7])
    licht /= np.linalg.norm(licht)
    cols = []
    for a, b, c in tris:
        n = np.cross(b - a, c - a)
        nl = np.linalg.norm(n)
        f = 0.55 + 0.45 * abs(float(n @ licht) / nl) if nl > 1e-9 else 0.8
        cols.append(np.clip(np.asarray(rgb, float) * f, 0, 255))
    return cols


def _glb_material(pfad):
    """Ohne Material zeigt der Betrachter die Flächen als dunkles Metall. Hier: mattes Material, beidseitig sichtbar –
    nur für Flächen mit Eckfarben; das Gelände mit Textur behält sein eigenes Material."""
    import json
    import struct
    b = open(pfad, "rb").read()
    laenge_json, typ = struct.unpack_from("<II", b, 12)
    j = json.loads(b[20:20 + laenge_json].decode("utf-8"))
    mats = j.setdefault("materials", [])
    mats.append({"pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0.0, "roughnessFactor": 0.95},
                 "doubleSided": True})
    idx = len(mats) - 1
    for m in j.get("meshes", []):
        for pr in m.get("primitives", []):
            if "COLOR_0" in (pr.get("attributes") or {}) or "material" not in pr:
                pr["material"] = idx
    neu = json.dumps(j, separators=(",", ":")).encode("utf-8")
    neu += b" " * ((4 - len(neu) % 4) % 4)
    rest = b[20 + laenge_json:]
    kopf = b[:8] + struct.pack("<I", 12 + 8 + len(neu) + len(rest))
    with open(pfad, "wb") as f:
        f.write(kopf + struct.pack("<II", len(neu), typ) + neu + rest)


def _gelaende_textur(K, d, X, Y, Z, farbe_basis):
    """Texturbild des Geländes: Nutzungsflächen scharf gezeichnet (statt grober Farbkacheln), dazu Schummerung aus der Neigung."""
    from PIL import Image
    import rasterio.features
    from rasterio.transform import from_bounds
    W, H = d.xmax - d.xmin, d.ymax - d.ymin
    px = int(min(4096, max(768, round(max(W, H) / 0.4))))
    bw, bh = (px, max(2, int(round(px * H / W)))) if W >= H else (max(2, int(round(px * W / H))), px)
    img = np.empty((bh, bw, 3), np.uint8)
    img[:] = np.asarray(farbe_basis, np.uint8)
    tr = from_bounds(d.xmin, d.ymin, d.xmax, d.ymax, bw, bh)
    for kat, reg in (d.regionen or {}).items():
        try:
            m = rasterio.features.rasterize([(reg, 1)], out_shape=(bh, bw), transform=tr, fill=0, dtype="uint8").astype(bool)
            if m.any():
                img[m] = _farbe(K, kat)
        except Exception:
            pass
    # Schummerung aus dem Gitter (weich hochgerechnet)
    zz = np.where(np.isnan(Z), np.nanmean(Z) if np.isfinite(Z).any() else 0.0, Z)
    dy, dx = np.gradient(zz, Y[:, 0], X[0, :])
    n = np.dstack([-dx, -dy, np.ones_like(dx)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    licht = np.array([-0.45, -0.55, 0.7]); licht /= np.linalg.norm(licht)
    sh = np.clip(n @ licht, 0, 1)
    sh = 0.62 + 0.38 * sh / max(float((np.array([0, 0, 1.0]) @ licht)), 1e-6)
    sh_img = Image.fromarray(np.clip(sh[::-1] * 255, 0, 255).astype(np.uint8)).resize((bw, bh), Image.BICUBIC)
    f = (np.asarray(sh_img, float) / 255.0)[..., None]
    img = np.clip(img.astype(float) * np.minimum(f, 1.08), 0, 255).astype(np.uint8)
    return Image.fromarray(img)


def glb_bauen(d, ziel, ueberhoehung=1.0, log=print, max_baeume=1200):
    """3D-Vorschau (GLB, Z nach oben, Ursprung = Gebietsmitte). Gelände nach Nutzung gefärbt, Gebäude, Bäume."""
    import shapely
    import trimesh
    from scipy.interpolate import LinearNDInterpolator
    K = kern()
    ce, cn = (d.xmin + d.xmax) / 2, (d.ymin + d.ymax) / 2
    off = np.array([ce, cn, 0.0])
    tris, cols = [], []

    # Gelände
    zg = [float(min(e[:, 2].min() for e, h in t["ground"])) for t in d.near + d.far if t.get("ground")]
    step = max(2.0, max(d.xmax - d.xmin, d.ymax - d.ymin) / 220)
    xs = np.linspace(d.xmin, d.xmax, int(np.ceil((d.xmax - d.xmin) / step)) + 1)
    ys = np.linspace(d.ymin, d.ymax, int(np.ceil((d.ymax - d.ymin) / step)) + 1)
    X, Y = np.meshgrid(xs, ys)
    if getattr(d, "px", None) is not None and len(d.px):
        f = LinearNDInterpolator(np.column_stack([d.px, d.py]), d.pz)
        Z = f(X, Y)
    else:
        f = None
        Z = np.full(X.shape, (np.percentile(zg, 10) if zg else 0.0))
    ok = ~np.isnan(Z)
    zmin = float(np.nanmin(Z)) if ok.any() else 0.0
    zbasis = zmin
    gut = ok[:-1, :-1] & ok[1:, :-1] & ok[:-1, 1:] & ok[1:, 1:]
    zoff = np.array([0.0, 0.0, zbasis])
    k = float(ueberhoehung or 1.0)

    def lift(p):
        q = np.asarray(p, float) - off - zoff
        q[..., 2] *= k
        return q
    # Gelände: ein glattes Netz mit Texturbild (Nutzung scharf + Schummerung); Löcher dort, wo es keine Höhen gibt
    ny, nx = X.shape
    gv = np.dstack([X, np.where(ok, Y, Y), np.where(ok, Z, zmin)]).reshape(-1, 3)
    gv = lift(gv)
    uv = np.column_stack([((X - d.xmin) / max(d.xmax - d.xmin, 1e-6)).ravel(), ((Y - d.ymin) / max(d.ymax - d.ymin, 1e-6)).ravel()])
    ii, jj = np.nonzero(gut)
    a = ii * nx + jj
    gf = np.concatenate([np.column_stack([a, a + 1, a + nx + 1]), np.column_stack([a, a + nx + 1, a + nx])])
    textur = None
    try:
        textur = _gelaende_textur(K, d, X, Y, Z, K.IFC_FARBEN.get("Gelaende", (196, 205, 176)))
    except Exception as e:
        log(f"  3D-Vorschau: Gelände-Textur nicht möglich ({e}) – grobe Farbflächen")
    if textur is not None and len(gf):
        gelaende = trimesh.Trimesh(vertices=gv, faces=gf, process=False)
        gelaende.visual = trimesh.visual.TextureVisuals(
            uv=np.clip(uv, 0, 1), material=trimesh.visual.material.PBRMaterial(
                baseColorTexture=textur, metallicFactor=0.0, roughnessFactor=0.95, doubleSided=True))
    else:
        gelaende = None
        farbe = np.tile(np.array(K.IFC_FARBEN.get("Gelaende", (196, 205, 176)), float), (*gut.shape, 1))
        cx, cy = (X[:-1, :-1] + X[1:, 1:]) / 2, (Y[:-1, :-1] + Y[1:, 1:]) / 2
        for kat, reg in (d.regionen or {}).items():
            try:
                m = shapely.contains_xy(reg, cx, cy)
                if m.any():
                    farbe[m] = _farbe(K, kat)
            except Exception:
                pass
        for i, j in zip(*np.nonzero(gut)):
            for t in ((gv[i * nx + j], gv[i * nx + j + 1], gv[(i + 1) * nx + j + 1]),
                      (gv[i * nx + j], gv[(i + 1) * nx + j + 1], gv[(i + 1) * nx + j])):
                tris.append(t)
                cols.append(_licht([t], farbe[i, j])[0])

    # Gebäude
    modus = getattr(d.cfg, "fern_gebaeude", "bloecke")
    gruppen = []
    near = []
    for t in d.near:
        near += K.lod2_faces(t)
    gruppen.append((near, K.IFC_FARBEN.get("Gebaeude_Nah", (235, 235, 235))))
    fern = []
    for t in d.far:
        if modus == "keine" or not t.get("ground"):
            continue
        try:
            fern += K.lod2_faces(t) if (modus == "lod2" and not t.get("kompakt")) else K.block_faces(t)[0]
        except Exception:
            pass
    gruppen.append((fern, K.IFC_FARBEN.get("Gebaeude_Fern", (215, 215, 215))))
    n_geb = 0
    for liste, rgb in gruppen:
        for p in liste:
            pt = _tri(lift(np.asarray(p, float)))
            n_geb += 1
            tris += pt
            cols += _licht(pt, rgb)
    # Bäume als Pyramiden
    for (x, y, kr, ho, st, _) in (d.baeume or [])[:max_baeume]:
        z = zmin
        if f is not None:
            zz = float(f(x, y))
            z = zz if not np.isnan(zz) else zmin
        r = max(kr, 5.0) / 2
        ho = max(ho, 6.0)
        base = [np.array([x + r * np.cos(a), y + r * np.sin(a), z + ho * 0.3]) for a in (0, np.pi / 2, np.pi, 1.5 * np.pi)]
        top = np.array([x, y, z + ho])
        for i in range(4):
            t = tuple(lift(q) for q in (base[i], base[(i + 1) % 4], top))
            tris.append(t)
            cols.append(_licht([t], (40, 110, 50))[0])
    if not tris and gelaende is None:
        raise RuntimeError("Keine Flächen für die 3D-Vorschau")
    szene = trimesh.Scene()
    n_dr = 0
    if gelaende is not None:
        szene.add_geometry(gelaende, node_name="gelaende")
        n_dr += len(gelaende.faces)
    if tris:
        V = np.array(tris, float).reshape(-1, 3)
        F = np.arange(len(V)).reshape(-1, 3)
        C = np.repeat(np.array(cols, float), 3, axis=0)
        C = 255.0 * (np.clip(C, 0, 255) / 255.0) ** 2.2                # glTF-Farben sind linear: sonst wirkt alles ausgewaschen
        C = np.column_stack([C, np.full(len(C), 255.0)]).astype(np.uint8)
        szene.add_geometry(trimesh.Trimesh(vertices=V, faces=F, vertex_colors=C, process=False), node_name="bauten")
        n_dr += len(F)
    szene.export(ziel)
    _glb_material(ziel)
    log(f"  3D-Vorschau: {n_dr} Dreiecke, {n_geb} Gebäudeteile ({os.path.getsize(ziel) / 1e6:.1f} MB)")
    return {"glb": ziel, "b": d.xmax - d.xmin, "h": d.ymax - d.ymin, "n_dreiecke": int(n_dr)}


def plan_bauen(d, ziel, log=print):
    """2D-Übersicht (PNG): Nutzung, Gebäude, Bäume, Nahbereich."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import PathPatch, Rectangle
    from matplotlib.path import Path
    K = kern()

    def ringe(g):
        out = []
        for p in getattr(g, "geoms", [g]):
            if p.geom_type != "Polygon" or p.is_empty:
                continue
            out.append(p)
        return out

    def patch(p, **kw):
        verts, codes = [], []
        for ring in [p.exterior] + list(p.interiors):
            c = np.asarray(ring.coords)
            verts += list(c)
            codes += [Path.MOVETO] + [Path.LINETO] * (len(c) - 2) + [Path.CLOSEPOLY]
        return PathPatch(Path(verts, codes), **kw)

    fig, ax = plt.subplots(figsize=(9, 9 * (d.ymax - d.ymin) / max(d.xmax - d.xmin, 1)), dpi=110)
    ax.set_facecolor("#f6f4ee")
    for kat, reg in (d.regionen or {}).items():
        rgb = np.array(_farbe(K, kat)) / 255.0
        for p in ringe(reg):
            ax.add_patch(patch(p, facecolor=rgb, edgecolor="none", linewidth=0, alpha=0.9))
    n_geb = 0
    for t in list(d.far) + list(d.near):
        for e, h in t.get("ground") or []:
            c = np.asarray(e)[:, :2]
            ax.add_patch(plt.Polygon(c, closed=True, facecolor="#e8e6e0" if t in d.far else "#fafafa",
                                     edgecolor="#555", linewidth=0.3))
        n_geb += 1
    if d.baeume:
        b = np.array([(x, y, max(kr, 3.0)) for (x, y, kr, ho, st, _) in d.baeume[:6000]])
        ax.scatter(b[:, 0], b[:, 1], s=np.clip(b[:, 2] ** 2 * 0.2, 1, 30), c="#2f7d3b", alpha=0.55, linewidths=0)
    nr = d.nah_rect.bounds
    ax.add_patch(Rectangle((nr[0], nr[1]), nr[2] - nr[0], nr[3] - nr[1], fill=False, edgecolor="#1f6f78", linestyle="--", linewidth=1.2))
    ax.set_xlim(d.xmin, d.xmax)
    ax.set_ylim(d.ymin, d.ymax)
    ax.set_aspect("equal")
    ax.tick_params(labelsize=7)
    ax.set_title("Gebiet (gestrichelt: Nahbereich)", fontsize=9)
    fig.tight_layout()
    fig.savefig(ziel)
    plt.close(fig)
    log(f"  2D-Übersicht: {n_geb} Gebäude")
    return ziel


def dxf_bild(dxf, ziel, log=print, breite_px=1800):
    """Fertige 2D-Zeichnung (DXF, z. B. der Lageplan) als PNG – so wie sie in CAD aussieht (Ebenenfarben, weißer Grund).
    Fehler werden gemeldet, nicht geworfen: die Vorschau darf nie einen Export verhindern. -> Pfad oder None"""
    try:
        import ezdxf
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from ezdxf.addons.drawing import Frontend, RenderContext
        from ezdxf.addons.drawing import config as dcfg
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
        doc = ezdxf.readfile(dxf)
        fig = plt.figure(figsize=(breite_px / 150, breite_px / 150), dpi=150)
        ax = fig.add_axes([0, 0, 1, 1])
        ctx = RenderContext(doc)
        cfg = dcfg.Configuration(background_policy=dcfg.BackgroundPolicy.WHITE, color_policy=dcfg.ColorPolicy.COLOR)
        Frontend(ctx, MatplotlibBackend(ax), config=cfg).draw_layout(doc.modelspace(), finalize=True)
        ax.set_aspect("equal")
        ax.axis("off")
        fig.savefig(ziel, facecolor="white", bbox_inches="tight", pad_inches=0.05)
        plt.close(fig)
        log(f"  2D-Vorschau: {os.path.basename(dxf)}")
        return ziel
    except Exception as e:
        log(f"  2D-Vorschau von {os.path.basename(dxf)} nicht möglich: {str(e)[:100]}")
        return None
