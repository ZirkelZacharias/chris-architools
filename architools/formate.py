"""Ausgabeformate: 2D (DXF, DWG, PDF, SVG) und 3D (IFC, GLB, OBJ, STL, PLY) – Umwandlung aus dem, was der Rechenkern schreibt."""
import os

FORMATE_2D = {
    "dxf": ("DXF", "Archicad öffnet DXF direkt. Volle Farben und Transparenz, kein Zusatzprogramm, am schnellsten erzeugt."),
    "dwg": ("DWG", "Mit dem ODA File Converter volle Farben; ohne ihn schreibt das Programm selbst eine DWG im Format R2000 "
                   "(Farben auf AutoCAD-Standardfarben gerundet, keine Transparenz)."),
    "pdf": ("PDF", "Nur zum Anschauen und Drucken, nicht zum Weiterzeichnen."),
    "svg": ("SVG", "Vektorbild für Illustrator/Affinity/Inkscape, nicht zum Weiterzeichnen in Archicad."),
}
FORMATE_3D = {
    "ifc": ("IFC", "Gelände, Straßen, Gebäude als getrennte Teile mit Farben und Material – das Archicad-Format."),
    "glb": ("GLB", "Ein Netz mit Farben für Viewer, Blender, SketchUp-Plugins – ohne Bauteil-Information."),
    "obj": ("OBJ", "Netz mit Farben (mit .mtl) für SketchUp, Rhino, Blender."),
    "stl": ("STL", "Nur Form, keine Farben – für 3D-Druck und einfache Programme."),
    "ply": ("PLY", "Netz mit Farben, einfaches Austauschformat."),
}
STANDARD_2D = ["dxf"]
STANDARD_3D = ["ifc"]

# Zirkel Zacharias sagt nichts: sein kleines Icon markiert nur die für Archicad beste Auswahl (die Standardwahl).
EMPFEHLUNG_2D = "dxf"
EMPFEHLUNG_3D = "ifc"


# Export-Profile: Formate für das Programm, in dem es weitergeht. (2D-Formate, 3D-Formate, Hinweis)
PROFILE = {
    "Archicad": (["dxf"], ["ifc"], "Archicad öffnet DXF direkt; IFC bringt Gelände, Straßen und Gebäude als getrennte Teile."),
    "Vectorworks": (["dxf"], ["ifc"], "Vectorworks liest DXF/DWG und IFC; bei Farbproblemen zusätzlich DWG wählen."),
    "AutoCAD / Revit": (["dwg"], ["ifc"], "DWG für AutoCAD; IFC für Revit (Einfügen/Verknüpfen)."),
    "SketchUp": (["dxf"], ["obj"], "OBJ mit Farben (mit .mtl) importiert SketchUp; 2D als DXF."),
    "Rhino": (["dxf"], ["obj"], "OBJ mit Farben oder STL für Rhino; 2D als DXF/DWG."),
    "3D-Druck": ([], ["stl"], "Nur STL (Form ohne Farben) für Slicer."),
    "Illustrator / Affinity": (["svg", "pdf"], [], "Vektorbilder zum Gestalten von Plänen, nicht zum Weiterzeichnen."),
}


def zweid_umwandeln(dateien, formate, oda="", log=print):
    """DXF-Dateien in die gewählten Formate umwandeln. Ohne 'dxf' in formate wird die DXF am Ende entfernt.
    -> Liste aller Ergebnisdateien"""
    formate = [f for f in (formate or STANDARD_2D) if f in FORMATE_2D]
    out = []
    for dxf in dateien:
        if not dxf.lower().endswith(".dxf") or not os.path.exists(dxf):
            out.append(dxf)
            continue
        basis = os.path.splitext(dxf)[0]
        dwg_ok = False
        if "dwg" in formate:
            from . import dwg
            neu = dwg.konvertieren([dxf], oda, log=log)
            out += neu
            dwg_ok = bool(neu)
        behalten = "dxf" in formate or ("dwg" in formate and not dwg_ok)      # DWG nicht möglich -> DXF als Ersatz behalten
        if "dwg" in formate and not dwg_ok:
            log(f"  Ersatz: {os.path.basename(dxf)} bleibt als DXF erhalten (DWG war nicht möglich).")
        if behalten:
            out.append(dxf)
        for ext in ("pdf", "svg"):
            if ext in formate:
                try:
                    out.append(_zeichnen(dxf, basis + "." + ext, log))
                except Exception as e:
                    log(f"  {ext.upper()} aus {os.path.basename(dxf)} nicht möglich: {e}")
        if not behalten:
            try:
                os.remove(dxf)
            except OSError:
                pass
    return out


def _zeichnen(dxf, ziel, log):
    import ezdxf
    from ezdxf.addons.drawing import matplotlib as ezm
    doc = ezdxf.readfile(dxf)
    msp = doc.modelspace()
    try:
        from ezdxf import bbox
        ext = bbox.extents(msp)
        w, h = ext.size.x, ext.size.y
        hoch = h > w
        groesse = (8.3, 11.7) if hoch else (11.7, 8.3)
    except Exception:
        groesse = (11.7, 8.3)
    ezm.qsave(msp, ziel, bg="#FFFFFF", size_inches=groesse, dpi=200)
    log(f"  {os.path.basename(ziel)} geschrieben")
    return ziel


def ifc_umwandeln(ifc, formate, log=print):
    """IFC -> Netzformate (GLB/OBJ/STL/PLY) über ifcopenshell + trimesh. Ohne 'ifc' in formate wird die IFC am Ende entfernt."""
    formate = [f for f in (formate or STANDARD_3D) if f in FORMATE_3D]
    out = [ifc] if "ifc" in formate else []
    netz = [f for f in formate if f != "ifc"]
    if netz and os.path.exists(ifc):
        try:
            mesh = _ifc_netz(ifc, log)
            basis = os.path.splitext(ifc)[0]
            for ext in netz:
                ziel = basis + "." + ext
                mesh.export(ziel)
                out.append(ziel)
                log(f"  {os.path.basename(ziel)}: {os.path.getsize(ziel) / 1e6:.1f} MB")
        except Exception as e:
            log(f"  Umwandlung der IFC in {', '.join(netz).upper()} nicht möglich: {e}")
    if "ifc" not in formate and out:
        try:
            os.remove(ifc)
        except OSError:
            pass
    return out


def _ifc_netz(ifc, log):
    import ifcopenshell
    import ifcopenshell.geom
    import numpy as np
    import trimesh
    f = ifcopenshell.open(ifc)
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)
    import multiprocessing
    it = ifcopenshell.geom.iterator(s, f, max(1, multiprocessing.cpu_count() - 1))
    V, F, C = [], [], []
    n0 = 0
    if it.initialize():
        while True:
            g = it.get().geometry
            v = np.array(g.verts, float).reshape(-1, 3)
            fa = np.array(g.faces, int).reshape(-1, 3)
            mid = np.array(g.material_ids, int) if len(g.material_ids) else np.zeros(len(fa), int)
            cols = []
            for m in g.materials:
                try:
                    d = m.diffuse
                    cols.append((int(d.r() * 255), int(d.g() * 255), int(d.b() * 255), 255))
                except Exception:
                    cols.append((200, 200, 200, 255))
            if not cols:
                cols = [(200, 200, 200, 255)]
            fc = np.array([cols[i if 0 <= i < len(cols) else 0] for i in mid], np.uint8)
            V.append(v)
            F.append(fa + n0)
            C.append(fc)
            n0 += len(v)
            if not it.next():
                break
    if not V:
        raise RuntimeError("keine Geometrie in der IFC")
    mesh = trimesh.Trimesh(vertices=np.vstack(V), faces=np.vstack(F), process=False)
    mesh.visual = trimesh.visual.ColorVisuals(mesh, face_colors=np.vstack(C))
    log(f"  Netz aus der IFC: {len(mesh.faces)} Dreiecke")
    return mesh
