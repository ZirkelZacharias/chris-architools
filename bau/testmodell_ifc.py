"""Kleines Test-IFC wie aus Archicad (Projekteinheit Millimeter) für das Werkzeug „CAD zu Lasercut“, Bauweise „Bauteile aus IFC“.

Haus 10 × 8 m: Außenwände 30 cm (Ziegel) mit Fenster- und Türöffnungen, Innenwand 11,5 cm, Bodenplatte und Geschossdecke
(Beton, Treppenloch), Satteldach aus zwei geneigten Dachplatten (Dachziegel), Gelände als TIN (Rasen) und ein Weg als Mesh
(Pflaster), etwas über dem Gelände. Aufruf:  python bau/testmodell_ifc.py ziel.ifc
"""
import math
import sys

import numpy as np


def bauen(pfad):
    import ifcopenshell
    import ifcopenshell.api
    import ifcopenshell.api.aggregate
    import ifcopenshell.api.context
    import ifcopenshell.api.feature
    import ifcopenshell.api.geometry
    import ifcopenshell.api.material
    import ifcopenshell.api.project
    import ifcopenshell.api.root
    import ifcopenshell.api.spatial
    import ifcopenshell.api.unit

    f = ifcopenshell.api.project.create_file(version="IFC4")
    proj = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="Testhaus")
    ifcopenshell.api.unit.assign_unit(f)                                   # Millimeter wie Archicad
    model = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW",
                                                parent=model)
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="Grundstück")
    bau = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuilding", name="Haus")
    eg = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey", name="EG")
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=proj)
    ifcopenshell.api.aggregate.assign_object(f, products=[bau], relating_object=site)
    ifcopenshell.api.aggregate.assign_object(f, products=[eg], relating_object=bau)
    mats = {n: ifcopenshell.api.material.add_material(f, name=n) for n in
            ("Ziegel", "Kalksandstein", "Beton", "Dachziegel", "Rasen", "Betonpflaster")}

    def platz(el, M):
        ifcopenshell.api.geometry.edit_object_placement(f, product=el, matrix=M)

    def matrix(x=0.0, y=0.0, z=0.0, drehz=0.0, drehx=0.0):
        cz, sz = math.cos(drehz), math.sin(drehz)
        cx, sx = math.cos(drehx), math.sin(drehx)
        Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1.0]])
        Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
        M = np.eye(4)
        M[:3, :3] = Rz @ Rx
        M[:3, 3] = [x, y, z]
        return M

    def element(cls, name, rep, M, mat, typ=None):
        el = ifcopenshell.api.root.create_entity(f, ifc_class=cls, name=name, predefined_type=typ)
        ifcopenshell.api.spatial.assign_container(f, products=[el], relating_structure=eg)
        ifcopenshell.api.geometry.assign_representation(f, product=el, representation=rep)
        platz(el, M)
        ifcopenshell.api.material.assign_material(f, products=[el], type="IfcMaterial", material=mats[mat])
        return el

    def oeffnung(wand, x, z, b, h, d):
        op = ifcopenshell.api.root.create_entity(f, ifc_class="IfcOpeningElement", name="Öffnung")
        rep = ifcopenshell.api.geometry.add_wall_representation(f, context=body, length=b, height=h, thickness=d + 0.2)
        ifcopenshell.api.geometry.assign_representation(f, product=op, representation=rep)
        M = np.array(wand.ObjectPlacement and ifcopenshell.util.placement.get_local_placement(wand.ObjectPlacement), float)
        M = M.copy()
        M[:3, 3] /= 1000.0                                                 # Platzierung ist in mm, edit_object_placement will Meter
        T = matrix(x, -0.1, z)
        platz(op, M @ T)
        ifcopenshell.api.feature.add_feature(f, feature=op, element=wand)

    import ifcopenshell.util.placement
    d, H = 0.30, 2.80
    L, B = 10.0, 8.0
    # Außenwände: Nord- und Südwand laufen durch, Ost/West dazwischen (stumpfer Stoß wie oft in Archicad)
    waende = []
    for name, x, y, lng, dz in (("Süd", 0, 0, L, 0.0), ("Nord", L, B, L, math.pi), ("West", 0, B - d, B - 2 * d, -math.pi / 2),
                                ("Ost", L, d, B - 2 * d, math.pi / 2)):
        rep = ifcopenshell.api.geometry.add_wall_representation(f, context=body, length=lng, height=H, thickness=d)
        waende.append(element("IfcWall", "Außenwand " + name, rep, matrix(x, y, 0.0, dz), "Ziegel"))
    oeffnung(waende[0], 1.5, 0.9, 1.5, 1.3, d)              # Fenster Süd
    oeffnung(waende[0], 6.0, 0.9, 2.5, 1.3, d)
    oeffnung(waende[0], 4.0, 0.0, 1.0, 2.1, d)              # Tür
    oeffnung(waende[1], 3.0, 0.9, 1.5, 1.3, d)              # Fenster Nord
    oeffnung(waende[3], 2.5, 0.9, 1.25, 1.3, d)             # Fenster Ost
    rep = ifcopenshell.api.geometry.add_wall_representation(f, context=body, length=B - 2 * d, height=H, thickness=0.115)
    element("IfcWall", "Innenwand", rep, matrix(5.0, d, 0.0, math.pi / 2), "Kalksandstein")
    # Bodenplatte und Geschossdecke (Treppenloch)
    rep = ifcopenshell.api.geometry.add_slab_representation(f, context=body, depth=0.25,
                                                            polyline=[(0, 0), (L, 0), (L, B), (0, B), (0, 0)])
    element("IfcSlab", "Bodenplatte", rep, matrix(0, 0, -0.25), "Beton", "BASESLAB")
    rep = ifcopenshell.api.geometry.add_slab_representation(f, context=body, depth=0.22,
                                                            polyline=[(0, 0), (L, 0), (L, B), (0, B), (0, 0)])
    decke = element("IfcSlab", "Geschossdecke", rep, matrix(0, 0, H), "Beton", "FLOOR")
    op = ifcopenshell.api.root.create_entity(f, ifc_class="IfcOpeningElement", name="Treppenloch")
    rep = ifcopenshell.api.geometry.add_slab_representation(f, context=body, depth=0.5, polyline=[(0, 0), (2.5, 0), (2.5, 1.2), (0, 1.2), (0, 0)])
    ifcopenshell.api.geometry.assign_representation(f, product=op, representation=rep)
    platz(op, matrix(6.5, 5.5, H - 0.1))
    ifcopenshell.api.feature.add_feature(f, feature=op, element=decke)
    # Satteldach: zwei geneigte Platten 20 cm, 35°, First in x-Richtung, 40 cm Überstand
    neig = math.radians(35)
    ue = 0.4
    tiefe = (B / 2 + ue) / math.cos(neig)
    roof = ifcopenshell.api.root.create_entity(f, ifc_class="IfcRoof", name="Dach")
    ifcopenshell.api.spatial.assign_container(f, products=[roof], relating_structure=eg)
    z0 = H + 0.22
    teile = []
    for seite, (y0, drehz) in enumerate(((-ue, 0.0), (B + ue, math.pi))):
        rep = ifcopenshell.api.geometry.add_slab_representation(f, context=body, depth=0.20,
                                                                polyline=[(0, 0), (L + 2 * ue, 0), (L + 2 * ue, tiefe), (0, tiefe), (0, 0)])
        x0 = -ue if seite == 0 else L + ue
        el = element("IfcSlab", "Dachfläche " + ("Süd" if seite == 0 else "Nord"), rep,
                     matrix(x0, y0, z0 - ue * math.tan(neig), drehz, neig), "Dachziegel", "ROOF")
        teile.append(el)
    ifcopenshell.api.aggregate.assign_object(f, products=teile, relating_object=roof)
    # Gelände (TIN, leicht geneigt, 30 x 24 m) und Weg (Mesh 1,5 m breit von der Tür nach Süden)
    nx, ny = 13, 11
    xs, ys = np.linspace(-10, 20, nx), np.linspace(-12, 12 + B / 2, ny)
    V = [[x, y, -0.35 + 0.04 * (x + 10) - 0.05 * (y + 12) + 0.25 * math.sin(x / 3) * math.cos(y / 4)] for y in ys for x in xs]
    F = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = j * nx + i
            F += [[a, a + 1, a + nx + 1], [a, a + nx + 1, a + nx]]
    rep = ifcopenshell.api.geometry.add_mesh_representation(f, context=body, vertices=[V], faces=[F])
    gel = ifcopenshell.api.root.create_entity(f, ifc_class="IfcGeographicElement", name="Gelände", predefined_type="TERRAIN")
    ifcopenshell.api.spatial.assign_container(f, products=[gel], relating_structure=site)
    ifcopenshell.api.geometry.assign_representation(f, product=gel, representation=rep)
    platz(gel, np.eye(4))
    ifcopenshell.api.material.assign_material(f, products=[gel], type="IfcMaterial", material=mats["Rasen"])

    def zg(x, y):
        return -0.35 + 0.04 * (x + 10) - 0.05 * (y + 12) + 0.25 * math.sin(x / 3) * math.cos(y / 4) + 0.03
    wv = []
    for y in np.linspace(-10, 0, 6):
        for x in (3.75, 5.25):
            wv.append([x, y, zg(x, y)])
    wf = [[2 * k, 2 * k + 1, 2 * k + 3, 2 * k + 2] for k in range(5)]
    rep = ifcopenshell.api.geometry.add_mesh_representation(f, context=body, vertices=[wv], faces=[wf])
    weg = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingElementProxy", name="Weg (Mesh)")
    ifcopenshell.api.spatial.assign_container(f, products=[weg], relating_structure=site)
    ifcopenshell.api.geometry.assign_representation(f, product=weg, representation=rep)
    platz(weg, np.eye(4))
    ifcopenshell.api.material.assign_material(f, products=[weg], type="IfcMaterial", material=mats["Betonpflaster"])
    f.write(pfad)
    return pfad


if __name__ == "__main__":
    print(bauen(sys.argv[1] if len(sys.argv) > 1 else "testhaus.ifc"))
