"""Montageplan als PDF (Übersicht, Schichten, Laserplatten, Druckplatten)."""
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import PathPatch, Rectangle
from matplotlib.path import Path
import numpy as np
from shapely.geometry import Polygon

from .geomutil import lines, polys

A3 = (16.54, 11.69)


def _patch(poly, **kw):
    verts, codes = [], []
    for ring in [poly.exterior] + list(poly.interiors):
        c = np.asarray(ring.coords)
        verts += list(c)
        codes += [Path.MOVETO] + [Path.LINETO] * (len(c) - 2) + [Path.CLOSEPOLY]
    return PathPatch(Path(verts, codes), **kw)


def _draw_viele(ax, geoms, **kw):
    """Viele Flächen (Raster aus Linien oder Punkten) als EINE Sammlung – Zehntausende einzelne Patches brauchen Minuten."""
    from matplotlib.collections import PolyCollection
    ringe = [np.asarray(p.exterior.coords) for g in geoms for p in polys(g)]
    if ringe:
        # ab einigen Tausend Flächen als Bild in die Übersicht (die echten Vektoren stehen in DXF/SVG, hier zählt nur der Überblick)
        ax.add_collection(PolyCollection(ringe, facecolors=kw.get("facecolor", "#000"), edgecolors="none", linewidths=0,
                                         rasterized=len(ringe) > 3000), autolim=False)


def _draw(ax, g, **kw):
    for p in polys(g):
        ax.add_patch(_patch(p, **kw))


def _lines(ax, ls, **kw):
    ls = list(ls)
    if len(ls) > 50:  # viele Linien: eine Sammlung statt je ein Plot-Aufruf
        from matplotlib.collections import LineCollection
        segs = [np.asarray(l.coords)[:, :2] for l in ls if not l.is_empty]
        ax.add_collection(LineCollection(segs, colors=kw.get("color", "#000"), linewidths=kw.get("lw", 0.5),
                                         rasterized=len(segs) > 3000), autolim=False)
        return
    for l in ls:
        x, y = l.xy
        ax.plot(x, y, **kw)


def _setup(ax, bounds, title):
    xmin, ymin, xmax, ymax = bounds
    ax.set_xlim(xmin - 5, xmax + 5)
    ax.set_ylim(ymin - 5, ymax + 5)
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=10, loc="left")
    ax.tick_params(labelsize=6)


def _grid_pages(pdf, n, per_page=4):
    pages = []
    for start in range(0, n, per_page):
        cnt = min(per_page, n - start)
        cols = 1 if cnt == 1 else 2
        rows = math.ceil(cnt / cols)
        fig, axs = plt.subplots(rows, cols, figsize=A3)
        axs = np.atleast_1d(axs).ravel()
        for a in axs[cnt:]:
            a.axis("off")
        pages.append((fig, axs[:cnt], start))
    return pages


def write_pdf(path, cfg, info, Q, parts, sheets, buildings, plates, features, stats, stuetzen=()):
    with PdfPages(path) as pdf:
        # --- Seite 1: Zusammenfassung
        fig = plt.figure(figsize=A3)
        fig.text(0.05, 0.93, f"{cfg['projekt_name']} – Montageplan", fontsize=22, weight="bold")
        rows = [
            ("Maßstab", f"1:{cfg['massstab']}"),
            ("Modellgröße", f"{stats['modell_b']:.0f} x {stats['modell_h']:.0f} mm"),
            ("Schichtdicke", f"{cfg['gelaende']['schichtdicke_mm']} mm  = {info['dz_m']:.2f} m Gelände je Schicht"),
            ("Überhöhung", f"{info['ueberhoehung']:g}-fach"),
            ("Geländehöhe", f"{info['z_min']:.1f} – {info['z_max']:.1f} m, Basis {info['basis_m']:.2f} m"),
            ("Schichten", f"{len(Q)} (inkl. Grundplatte S00)"),
            ("Laserteile", f"{len(parts)}"),
            ("Platten", ", ".join(f"{c} x {w:.0f}x{h:.0f} mm" for (w, h), c in stats["platten"].items())),
            ("Materialfläche Teile", f"{stats['teile_flaeche']/1e6:.3f} m²  "
                                      f"(volle Schichten wären {stats['voll_flaeche']/1e6:.3f} m²)"),
            ("Material", stats["material"]),
            ("Bauweise", {"voll": "volle Schichten", "steckrippen": f"hohl mit Steckrippen ({stats['n_rippen']} Rippen)",
                          "stuetzkloetze": f"hohl mit Stützklötzen ({stats['n_stuetzen']} Klötze à "
                                           f"{cfg['gelaende'].get('stuetze_mm', 15):.0f} mm)"}.get(stats["bauweise"], stats["bauweise"])
                         + (f" – {stats['ersparnis']:.0f} % weniger Teilefläche als volle Schichten" if stats["bauweise"] != "voll" else "")),
            ("Gebäude/Bauwerke", f"{stats['n_druck']} gedruckt, {stats['n_gravur']} nur graviert, "
                                  f"{stats['n_platz']} Platzhalter"),
            ("Druckplatten", f"{stats['n_druckplatten']} ({cfg['druck'].get('geraet', '')}, {cfg['druck'].get('filament', 'PLA')})"),
            ("Druckvolumen", f"{stats['volumen_cm3']:.0f} cm³  ≈ {stats['filament_g']:.0f} g Filament (grob)"),
        ]
        lz = stats.get("laser")
        if lz:
            mm = lambda v: f"{v:.2f}".replace(".", ",")
            rows += [
                ("Laserzeit (Schätzung)", f"ca. {lz['s'] / 60:.0f} min (Spanne {lz['s_lo'] / 60:.0f}–{lz['s_hi'] / 60:.0f} min) – "
                                          f"Schneiden {lz['teile']['schneiden'] / 60:.0f}, Ritzen {lz['teile']['ritzen'] / 60:.0f}, "
                                          f"Gravieren {lz['teile']['gravieren'] / 60:.0f}, Anfahren {lz['teile']['anfahren'] / 60:.0f} min"),
                ("Laserkosten (Schätzung)", f"ca. {mm(lz['netto'])} € zzgl. MwSt. = {mm(lz['netto'] * (1 + lz['mwst']))} € brutto "
                                            f"(Spanne {mm(lz['netto_lo'])}–{mm(lz['netto_hi'])} € netto; "
                                            f"{mm(lz['preis_min'])} €/min zzgl. MwSt.)"),
            ]
        y = 0.87
        for k, v in rows:
            fig.text(0.05, y, k, fontsize=11, weight="bold")
            fig.text(0.24, y, v, fontsize=11)
            y -= 0.035
        y -= 0.02
        hints = [
            "Laserkosten: grobe Schätzung aus Schnitt-/Ritzlängen und Gravurfläche mit Erfahrungswerten je Material.",
            "  Die Werkstatt ermittelt die Zeit mit Ruby und rechnet sekundengenau ab – auf Wunsch schätzt sie vorab selbst.",
            "Farben Laser (Werkstatt): Rot = Schneiden, Blau = Ritzen, Schwarz = Gravieren (Fläche).",
            "Teile-ID: S<Schicht>-<Nr>. Die Beschriftung liegt nach Möglichkeit verdeckt unter der nächsten Schicht.",
            "Blaue Linie auf jeder Schicht = Anlegekante der nächsthöheren Schicht.",
            "Passlöcher: von unten Stifte stecken, Schicht für Schicht auffädeln. Oberste Schicht hat kein Loch.",
            "Gebäude-Nummern (G…/B…) sind auf die Platte graviert und stehen im STL-Dateinamen.",
            "Steckrippen: Rippen RA.. (eine Richtung) und RB.. (quer) an den Schlitzen ineinanderstecken und auf die",
            "  geritzten Linien der Grundplatte stellen; die Nummer steht neben der Linie. Danach Schichten auflegen.",
            "Stützklötze (falls gewählt): auf den geritzten Quadraten zu Säulen stapeln.",
            "Die 3D-Vorschau (STL) zeigt das zusammengesetzte Modell.",
        ]
        for h in hints:
            fig.text(0.05, y, "• " + h, fontsize=10)
            y -= 0.03
        pdf.savefig(fig)
        plt.close(fig)

        # --- Draufsicht und Schnitte
        for pfad in stats.get("ansichten") or []:
            try:
                img = plt.imread(pfad)
                fig = plt.figure(figsize=A3)
                ax = fig.add_axes([0.03, 0.03, 0.94, 0.94])
                ax.imshow(img)
                ax.axis("off")
                pdf.savefig(fig)
                plt.close(fig)
            except Exception:
                pass

        # --- Seite 2: Übersicht
        fig, ax = plt.subplots(figsize=A3)
        cmap = plt.get_cmap("YlGn")
        for k, g in enumerate(Q):
            _draw(ax, g, facecolor=cmap(0.15 + 0.7 * k / max(1, len(Q) - 1)), edgecolor="#555", lw=0.3)
        for f in features:
            if f["typ"] == "punkt":
                for p in getattr(f["geom"], "geoms", [f["geom"]]):
                    ax.plot(p.x, p.y, ".", color="#2a7", ms=2)
            else:
                _lines(ax, lines(f["geom"]), color="#46a", lw=0.4)
        for b in buildings:
            fc = {"druck": "#333", "gravur": "#bbb", "platzhalter": "none"}[b["status"]]
            _draw(ax, b["footprint"], facecolor=fc, edgecolor="#c00" if b["status"] == "platzhalter" else "#000",
                  lw=0.4, hatch="///" if b["status"] == "platzhalter" else None)
            c = b["footprint"].representative_point()
            ax.text(c.x, c.y, b["nr"], fontsize=4, color="#fff" if b["status"] == "druck" else "#000",
                    ha="center", va="center")
        _setup(ax, Q[0].bounds, "Übersicht – Schichten (dunkler = höher), Gebäude mit Nummer")
        pdf.savefig(fig)
        plt.close(fig)

        # --- Schichten
        for fig, axs, start in _grid_pages(pdf, len(Q)):
            for i, ax in enumerate(axs):
                k = start + i
                if k > 0:
                    _draw(ax, Q[k - 1], facecolor="#f2f2f2", edgecolor="#aaa", lw=0.3)
                for p in parts:
                    if p.get("rippe") or p["layer"] != k:
                        continue
                    _draw(ax, p["poly"], facecolor="#e8c48a", edgecolor="#000", lw=0.4)
                    c = p["poly"].representative_point()
                    ax.text(c.x, c.y, p["id"], fontsize=6, ha="center", va="center")
                for st in stuetzen:
                    if st["layer"] == k:
                        x, y = st["pos"]
                        h = cfg["gelaende"].get("stuetze_mm", 15) / 2
                        ax.add_patch(Rectangle((x - h, y - h), 2 * h, 2 * h, fc="#c96", ec="#000", lw=0.3))
                _setup(ax, Q[0].bounds, f"Schicht S{k:02d}" + (" (Grundplatte)" if k == 0 else
                                                               f" – liegt auf S{k-1:02d} (grau)"))
            pdf.savefig(fig)
            plt.close(fig)

        # --- Laserplatten
        for fig, axs, start in _grid_pages(pdf, len(sheets)):
            for i, ax in enumerate(axs):
                s = sheets[start + i]
                W, H = s["format"]
                ax.add_patch(Rectangle((0, 0), W, H, fill=False, ec="#888", lw=0.6))
                for pp in s["teile"]:
                    _draw(ax, pp["poly"], facecolor="#f5e3c4", edgecolor="#d00", lw=0.4)
                    _lines(ax, pp.get("ritzen", []), color="#00c", lw=0.25)
                    _draw_viele(ax, pp.get("gravieren", []), facecolor="#000", edgecolor="none", lw=0)
                    if pp.get("id"):
                        c = pp["poly"].representative_point()
                        ax.text(c.x, c.y, pp["id"], fontsize=5, ha="center", va="center", color="#555")
                ax.set_xlim(-5, W + 5)
                ax.set_ylim(-5, H + 5)
                ax.set_aspect("equal")
                ax.set_title(f"Laserplatte {start + i + 1:02d} – {W:.0f} x {H:.0f} mm", fontsize=10, loc="left")
                ax.tick_params(labelsize=6)
            pdf.savefig(fig)
            plt.close(fig)

        # --- Druckplatten
        for fig, axs, start in _grid_pages(pdf, len(plates)):
            for i, ax in enumerate(axs):
                pl = plates[start + i]
                W, H = pl["format"]
                ax.add_patch(Rectangle((0, 0), W, H, fill=False, ec="#888", lw=0.6))
                for nr, coords in pl["teile"]:
                    fp = Polygon(coords)
                    _draw(ax, fp, facecolor="#9ab", edgecolor="#123", lw=0.4)
                    c = fp.representative_point()
                    ax.text(c.x, c.y, nr, fontsize=6, ha="center", va="center")
                ax.set_xlim(-5, W + 5)
                ax.set_ylim(-5, H + 5)
                ax.set_aspect("equal")
                ax.set_title(f"Druckplatte {pl['name']}", fontsize=10, loc="left")
                ax.tick_params(labelsize=6)
            pdf.savefig(fig)
            plt.close(fig)
