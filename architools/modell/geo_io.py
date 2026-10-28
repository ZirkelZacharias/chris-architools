"""Einlesen von DGM, Vektordaten und LoD2-CityGML."""
import glob
import os
import xml.etree.ElementTree as ET

import numpy as np
import shapely
from shapely.geometry import box

RASTER_EXT = (".tif", ".tiff", ".asc", ".vrt")
XYZ_EXT = (".xyz", ".txt", ".csv")


def _collect(path, exts):
    if os.path.isdir(path):
        files = []
        for e in exts:
            files += glob.glob(os.path.join(path, "**", "*" + e), recursive=True)
        return sorted(set(files))
    return [path]


# ---------------------------------------------------------------- DGM
def load_dgm(path, bounds, pad=20.0, log=print):
    """Liefert dict(x=Spaltenmitten aufsteigend, y=Zeilenmitten aufsteigend, z=2D-Array [y, x])."""
    if not path or not os.path.exists(path):
        raise FileNotFoundError(f"DGM nicht gefunden: {path}")
    xmin, ymin, xmax, ymax = bounds
    b = (xmin - pad, ymin - pad, xmax + pad, ymax + pad)
    files = _collect(path, RASTER_EXT + XYZ_EXT)
    rasters = [f for f in files if f.lower().endswith(RASTER_EXT)]
    xyz = [f for f in files if f.lower().endswith(XYZ_EXT)]
    if rasters:
        import rasterio
        from rasterio.merge import merge
        srcs = [rasterio.open(f) for f in rasters]
        crs = srcs[0].crs
        if crs is not None and "25833" not in str(crs.to_epsg() or crs):
            log(f"  Warnung: DGM-Koordinatensystem ist {crs}, erwartet EPSG:25833")
        arr, tr = merge(srcs, bounds=b, nodata=np.nan, dtype="float64")
        for s in srcs:
            s.close()
        z = arr[0].astype(float)
        res = tr.a
        x = tr.c + res * (np.arange(z.shape[1]) + 0.5)
        y = tr.f + tr.e * (np.arange(z.shape[0]) + 0.5)
    elif xyz:
        pts = []
        for f in xyz:
            d = np.loadtxt(f, usecols=(0, 1, 2), delimiter=None, comments="#",
                           ndmin=2, converters=None) if not f.lower().endswith(".csv") \
                else np.loadtxt(f, usecols=(0, 1, 2), delimiter=",", skiprows=1, ndmin=2)
            m = (d[:, 0] >= b[0]) & (d[:, 0] <= b[2]) & (d[:, 1] >= b[1]) & (d[:, 1] <= b[3])
            if m.any():
                pts.append(d[m])
        if not pts:
            raise ValueError("Keine DGM-Punkte im Ausschnitt gefunden")
        p = np.vstack(pts)
        ux = np.unique(p[:, 0])
        res = float(np.min(np.diff(ux))) if len(ux) > 1 else 1.0
        x0, y0 = p[:, 0].min(), p[:, 1].min()
        ci = np.round((p[:, 0] - x0) / res).astype(int)
        ri = np.round((p[:, 1] - y0) / res).astype(int)
        z = np.full((ri.max() + 1, ci.max() + 1), np.nan)
        z[ri, ci] = p[:, 2]
        x = x0 + res * np.arange(z.shape[1])
        y = y0 + res * np.arange(z.shape[0])
    else:
        raise ValueError(f"Keine lesbaren DGM-Dateien in {path}")

    # y aufsteigend sortieren
    if y[0] > y[-1]:
        y = y[::-1]
        z = z[::-1, :]
    # NoData mit nächstem Nachbarn füllen
    nan = ~np.isfinite(z)
    if nan.all():
        raise ValueError("DGM enthält im Ausschnitt nur NoData")
    if nan.any():
        from scipy.ndimage import distance_transform_edt
        idx = distance_transform_edt(nan, return_distances=False, return_indices=True)
        z = z[tuple(idx)]
    log(f"  DGM: {z.shape[1]} x {z.shape[0]} Zellen, Auflösung {abs(x[1]-x[0]):.2f} m, "
        f"Höhe {np.nanmin(z):.1f} – {np.nanmax(z):.1f} m")
    return {"x": np.asarray(x, float), "y": np.asarray(y, float), "z": z}


# ---------------------------------------------------------------- Vektor
def read_vector(path, layer="", bounds=None, log=print):
    """Liefert Liste von (shapely-Geometrie, Attribut-dict)."""
    import pyogrio
    if not path or not os.path.exists(path):
        raise FileNotFoundError(f"Vektordatei nicht gefunden: {path}")
    kw = {}
    if layer:
        kw["layer"] = layer
    if bounds is not None:
        kw["bbox"] = tuple(bounds)
    meta, _fids, geoms, fields = pyogrio.raw.read(path, **kw)
    crs = meta.get("crs") or ""
    if crs and "25833" not in str(crs):
        log(f"  Warnung: {os.path.basename(path)} hat {crs}, erwartet EPSG:25833")
    names = list(meta["fields"])
    out = []
    for i, wkb in enumerate(geoms):
        if wkb is None:
            continue
        g = shapely.from_wkb(wkb)
        if g is None or g.is_empty:
            continue
        g = shapely.force_2d(g)
        attrs = {n: fields[j][i] for j, n in enumerate(names)}
        out.append((g, attrs))
    return out


# ---------------------------------------------------------------- CityGML
def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _ring_coords(ring):
    for el in ring.iter():
        n = _local(el.tag)
        if n == "posList":
            dim = int(el.get("srsDimension", "3"))
            v = np.array(el.text.split(), float)
            return v.reshape(-1, dim)[:, :3] if dim >= 3 else None
    pos = [np.array(el.text.split(), float) for el in ring.iter() if _local(el.tag) == "pos"]
    if pos:
        return np.array(pos)[:, :3]
    return None


def _polygons(elem):
    """Alle gml:Polygon unter elem als (exterior Nx3, [interiors])."""
    res = []
    for poly in elem.iter():
        if _local(poly.tag) != "Polygon":
            continue
        ext, ints = None, []
        for child in poly:
            n = _local(child.tag)
            if n == "exterior":
                ext = _ring_coords(child)
            elif n == "interior":
                c = _ring_coords(child)
                if c is not None:
                    ints.append(c)
        if ext is not None and len(ext) >= 4:
            res.append((ext, ints))
    return res


def _normal_z(ring):
    # Newell-Normale
    p = ring
    q = np.roll(p, -1, axis=0)
    n = np.array([np.sum((p[:, 1] - q[:, 1]) * (p[:, 2] + q[:, 2])),
                  np.sum((p[:, 2] - q[:, 2]) * (p[:, 0] + q[:, 0])),
                  np.sum((p[:, 0] - q[:, 0]) * (p[:, 1] + q[:, 1]))])
    ln = np.linalg.norm(n)
    return n[2] / ln if ln > 0 else 0.0


def read_citygml(paths, bounds, log=print):
    """Liest Gebäude (inkl. BuildingParts) aus CityGML-Dateien.

    Rückgabe: Liste dict(id, roofs=[(ext, ints)], grounds=[...], zmin, zmax, measured_height)
    """
    files = []
    for p in paths:
        if p:
            files += _collect(p, (".gml", ".xml", ".citygml"))
    bb = box(*bounds)
    out = []
    for f in files:
        n_file = 0
        for _ev, el in ET.iterparse(f, events=("end",)):
            if _local(el.tag) != "Building":
                continue
            bid = None
            for k, v in el.attrib.items():
                if _local(k) == "id":
                    bid = v
            roofs, grounds, walls, mh = [], [], [], None
            for sub in el.iter():
                n = _local(sub.tag)
                if n == "WallSurface":
                    walls += _polygons(sub)
                elif n == "RoofSurface":
                    roofs += _polygons(sub)
                elif n == "GroundSurface":
                    grounds += _polygons(sub)
                elif n == "measuredHeight" and sub.text:
                    try:
                        mh = float(sub.text)
                    except ValueError:
                        pass
            if not roofs:
                # ohne Semantik: nach oben zeigende Flächen als Dach
                for ext, ints in _polygons(el):
                    if _normal_z(ext) > 0.3:
                        roofs.append((ext, ints))
                    elif _normal_z(ext) < -0.3:
                        grounds.append((ext, ints))
            allp = roofs + grounds
            if not allp:
                el.clear()
                continue
            pts = np.vstack([e for e, _ in allp])
            fp_box = box(pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max())
            if not fp_box.intersects(bb):
                el.clear()
                continue
            zmin = min(e[:, 2].min() for e, _ in grounds) if grounds else pts[:, 2].min()
            out.append({"id": bid or f"bldg_{len(out)}", "roofs": roofs, "grounds": grounds, "walls": walls,
                        "zmin": float(zmin), "zmax": float(pts[:, 2].max()),
                        "measured_height": mh})
            n_file += 1
            el.clear()
        log(f"  CityGML {os.path.basename(f)}: {n_file} Gebäude im Ausschnitt")
    return out


def load_extent(cfg, log=print):
    """Ausschnitt als Polygon (Weltkoordinaten)."""
    if cfg.get("ausschnitt_datei"):
        gs = read_vector(cfg["ausschnitt_datei"], log=log)
        poly = shapely.union_all([g for g, _ in gs if g.geom_type in ("Polygon", "MultiPolygon")])
        if poly.is_empty:
            raise ValueError("Ausschnitt-Datei enthält keine Fläche")
        return poly
    a = cfg["ausschnitt"]
    if a["xmax"] <= a["xmin"] or a["ymax"] <= a["ymin"]:
        raise ValueError("Ausschnitt ist leer – bitte xmin/ymin/xmax/ymax angeben")
    return box(a["xmin"], a["ymin"], a["xmax"], a["ymax"])
