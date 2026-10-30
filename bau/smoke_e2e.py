import sys, os, shutil, json, time
sys.path.insert(0, os.getcwd())
from architools import projekt as P, laufen as L
from architools.modell import config as MC
import shapely.geometry as SG
from architools import projekt as _P
_K=_P.kern()
def _f(basis,typ,bbox,cafile,unsicher,log=print,notfall_ohne_bbox=False):
    if typ.endswith(":radverkehrsnetz"):
        return {"features":[{"type":"Feature","geometry":SG.mapping(SG.LineString([(393500,5826520),(393700,5826560)])),"properties":{"art":"Radweg"}}]}
    if typ.endswith(":radfernwege"):
        return {"features":[{"type":"Feature","geometry":SG.mapping(SG.LineString([(393520,5826600),(393690,5826610)])),"properties":{}}]}
    return None
_K.wfs_laden=_f
_K.wfs_typnamen=lambda b,c:[]
import numpy as np, rasterio
from rasterio.transform import from_origin
RX, RY = 393450, 5826400
import tempfile
TMP = tempfile.mkdtemp()
VEG = os.path.join(TMP, "veg.tif")
yy, xx = np.mgrid[0:300, 0:300]
arr = (np.where(((xx-150)**2+(yy-100)**2)<400, 14.0, 0)*10).astype("uint16") + (np.where(((xx-60)**2+(yy-200)**2)<100, 11.0, 0)*10).astype("uint16")
with rasterio.open(VEG,"w",driver="GTiff",height=300,width=300,count=1,dtype="uint16",crs="EPSG:25833",transform=from_origin(RX,RY+300,1,1),nodata=0) as ds: ds.write(arr,1)
_old=_f
def _f2(basis,typ,bbox,cafile,unsicher,log=print,notfall_ohne_bbox=False):
    if typ in _K.WFS_BAUM_TYPEN:
        return {"features":[{"type":"Feature","geometry":SG.mapping(SG.Point(393600,5826500)),"properties":{"baumart":"Linde"}}]}
    if typ == _K.WFS_NUTZUNG_TYP:
        return {"features":[{"type":"Feature","geometry":SG.mapping(SG.box(393450,5826400,393750,5826700)),"properties":{"nutzung":"Gruenanlage"}}]}
    return _old(basis,typ,bbox,cafile,unsicher,log,notfall_ohne_bbox)
_K.wfs_laden=_f2
_K.osm_laden=lambda *a, **k: ([], [(SG.Point(393500,5826450), {"natural":"tree"}), (SG.Point(393600.5,5826500.5), {"natural":"tree"})])

B = os.path.abspath("beispiel")
MUSS = {"ifc","lageplan","info_dwg","laser","druck","schnitt","hoehenlinien"}
ordner = os.path.join(TMP, "proj"); shutil.rmtree(ordner, ignore_errors=True)
p = P.neues_projekt("E2E", ordner)
p["gebiet"]["mitte_en"] = [393600.0, 5826550.0]
u = p["umgebung"]
u.update(land="berlin", quelle="berlin", online_dgm=False, online_lod2=False, dgm=[B + "/testdaten/dgm1.tif"],
         lod2=[B + "/testdaten/lod2_waende.gml"], breite=300.0, hoehe=300.0, nah_breite=200.0, nah_hoehe=200.0,
         dgm_notfall=False, markant=False, alkis_zusatz=False, lod2_luecken=False, grundrisse_abgleich=False,
         buergersteige="keine", schatten="aus")
u["zusatz"] = {"fassaden": {"ifc": True}}     # Plugin-Hook ifc_ende MUSS laufen (Regression: Namenskonflikt mit dem Ordner "zusatz")
m = MC.load(B + "/beispiel_projekt.json")
m["gebiet"] = p["gebiet"]; p["gebiet"].update(breite_cm=80.0, hoehe_cm=60.0)
for k in ("dgm", "gebaeude", "einsatz", "laser", "druck", "gelaende", "ebenen", "markierungen", "bauwerke", "quelle"):
    p["modell"][k] = m[k]
MC.resolve_paths(p["modell"]) if False else None
p["modell"]["dgm"]["datei"] = B + "/testdaten/dgm1.tif"
p["modell"]["gebaeude"]["citygml"] = [B + "/testdaten/lod2.gml"]
p["modell"]["quelle"] = "dateien"
for lst in ("markierungen", "bauwerke"):
    for it in p["modell"][lst]:
        if it.get("datei") and not os.path.isabs(it["datei"]): it["datei"] = os.path.join(B, it["datei"])
v = p["modell"]["einsatz"].get("flurstuecke_datei")
if v and not os.path.isabs(v): p["modell"]["einsatz"]["flurstuecke_datei"] = os.path.join(B, v)
g = p["modell"]["gebaeude"]
if g.get("grundriss_datei") and not os.path.isabs(g["grundriss_datei"]): g["grundriss_datei"] = os.path.join(B, g["grundriss_datei"])
for lst in ("markierungen", "bauwerke"):
    for it in p["modell"][lst]:
        if it.get("datei") and not os.path.isabs(it["datei"]): it["datei"] = os.path.join(B, it["datei"])
for k in ("flurstuecke_datei",):
    v = p["modell"]["einsatz"].get(k)
    if v and not os.path.isabs(v): p["modell"]["einsatz"][k] = os.path.join(B, v)
g = p["modell"]["gebaeude"]
if g.get("grundriss_datei") and not os.path.isabs(g["grundriss_datei"]): g["grundriss_datei"] = os.path.join(B, g["grundriss_datei"])
p["formate"]={"zweid":["dxf","dwg","pdf"],"dreid":["ifc","glb"]}; u["extra"]=["radverkehr"]; u["ua_gebaeudehoehen"]=True; u["ua_vegetationshoehen"]=True
p["formate"]={"zweid":["dxf"],"dreid":["ifc"]}; u["extra"]=["radverkehr"]; u["ua_vegetationsraster"]=True; u["veg_raster_dateien"]=[VEG]; u["rad_wege"]=True
p["ausgaben"].update(ifc=True, lageplan=True, schwarzplan=True, info_dwg=True, laser=True, druck=True, schnitt=True, hoehenlinien=True)
u["wms_karten"] = ["luftbild"]                      # Kartenbild (Dienst gestellt)
u["geschosslinien"] = True; u["fenstermuster"] = True; u["lp_text"] = True                                                       # Lageplan-Beschriftung
mg = p["modell"]["gebaeude"]
mg.update(modus="falt", material="Bristolkarton", staerke_mm=0.5, lasche_mm=3.0, fenstermuster=True)       # Gebäude als Faltmodell (Laser)
p["modell"]["laser"]["rahmen"] = {"aktiv": True, "ueberstand_mm": 0.0}
p["modell"]["laser"]["hoehenlinien"] = {"aktiv": True, "aequidistanz_m": 1.0, "haupt_alle": 5, "haupt": "gravieren", "neben": "ritzen"}
p["modell"]["laser"]["restplatten"] = [{"name": "Rest A", "b_mm": 400, "h_mm": 300, "anzahl": 1}]
from PIL import Image
_rj = os.path.join(TMP, "rasterbild.jpg")
Image.fromarray((np.add.outer(np.arange(120), np.arange(160)) % 255).astype("uint8")).save(_rj)    # Verlaufsbild für die Rastergravur
p["modell"]["raster_bild"] = {"aktiv": True, "quelle": "datei", "datei": _rj, "weite_mm": 0.8, "teststreifen": True}
p["modell"].setdefault("ebenen", {})["Gebäudenummern"] = "raster"
p["modell"]["holz"]["rahmen"]["aktiv"] = True; p["modell"]["holz"]["podest"]["aktiv"] = True
import ifcmap_wms as WM, io
from PIL import Image
# Nachgebauter Dienst: erst eine Hilfsebene (einfarbige Befliegungsübersicht), dann die Bildebene "x" mit Struktur.
# Die Hilfsebene hat absichtlich einen neutralen Namen: die Luftbildsuche muss sie am Probebild erkennen und überspringen.
_CAP = (b'<WMT_MS_Capabilities version="1.1.1"><Capability><Layer><SRS>EPSG:25833</SRS>'
        b'<Layer><Name>ebene_a</Name><Title>a</Title></Layer><Layer><Name>x</Name><Title>x</Title></Layer>'
        b'</Layer></Capability></WMT_MS_Capabilities>')
WMS_EBENEN = []
def _wms_fake(url, ctx, timeout=90):
    if "GetCapabilities" in url:
        return _CAP, "text/xml"
    w = int(url.split("WIDTH=")[1].split("&")[0]); h = int(url.split("HEIGHT=")[1].split("&")[0])
    ebene = url.split("LAYERS=")[1].split("&")[0]; WMS_EBENEN.append(ebene)
    if ebene == "x":
        yy, xx = np.mgrid[0:h, 0:w]
        im = Image.fromarray(((np.sin(xx / 7.0) * np.cos(yy / 11.0) + 1) * 110 + np.random.default_rng(len(WMS_EBENEN)).normal(0, 12, (h, w))).clip(0, 255).astype("uint8")).convert("RGB")
    else:
        im = Image.new("RGB", (w, h), (120, 160, 200))
    b = io.BytesIO(); im.save(b, "PNG"); return b.getvalue(), "image/png"
WM._holen = _wms_fake
u["gelaende_luftbild"] = True; u["luftbild_aufloesung"] = 2.0
p["schnitt"]["seite"]="rechts"; p["ziel"]={"ordner":os.path.join(TMP,"ziel"),"name":"MeinExport"}
p["schnitt"]["linie_en"] = [[393450, 5826550], [393750, 5826550]]
t0 = time.time()
LOG = []
log = lambda s: (LOG.append(str(s)), print(s, flush=True))
erg = L.alles(p, P.gewaehlt(p), log, lambda x, t="": None)
print("FERTIG", round(time.time() - t0), {k: (list(v)[:8] if isinstance(v, dict) else v) for k, v in erg.items()})
print(json.dumps({k: v["zeit"] for k, v in p["stand"].items()}))
for r, _, fs in os.walk(ordner):
    for f in fs[:40]:
        print(os.path.join(r, f).replace(ordner, ""), os.path.getsize(os.path.join(r, f)))

# Abwicklung (Schnitt-Werkzeug mit mehrpunktiger Linie)
p["schnitt"].update(art="abwicklung", seite="beide", tiefe_m=60.0, linie_en=[[393450, 5826520], [393600, 5826540], [393700, 5826600]])
ab = L.schnitt_export(p, log)
assert any("Abwicklung" in os.path.basename(f) for f in ab["dateien"]), ab
print("ABWICKLUNG OK", [os.path.basename(f) for f in ab["dateien"]])
wm = [f for r_, _, fs_ in os.walk(TMP) for f in fs_ if f.startswith("ifcmap_zusatz_Karte_") and f.endswith(".dxf")]
assert wm, "Kartenbild-DXF fehlt"
print("KARTENBILD OK")
kl = [f for r_, _, fs_ in os.walk(os.path.join(TMP, "ziel")) for f in fs_ if f.endswith("zuschnitt_und_kosten.txt")]
assert kl, "Kostenliste fehlt"
print("KOSTENLISTE OK")
gl = [f for r_, _, fs_ in os.walk(os.path.join(TMP, "ziel")) for f in fs_ if "Gebaeude_Bristolkarton" in f and f.endswith(".pdf")]
assert gl, "Gebäude-Laserplatte (Faltmodell) fehlt"
hz = [f for r_, _, fs_ in os.walk(os.path.join(TMP, "ziel")) for f in fs_ if f.endswith("holz_zuschnitt.txt")]
assert hz, "Holz-Zuschnittliste fehlt"
rp = [f for r_, _, fs_ in os.walk(os.path.join(TMP, "ziel")) for f in fs_ if "Restplatte01" in f and f.endswith(".pdf")]
assert rp, "Restplatten-PDF fehlt"
lt = [f for r_, _, fs_ in os.walk(TMP) for f in fs_ if f.endswith("lageplan.dxf") or f.endswith("Lageplan.dxf")]
print("GEBAEUDE-LASER, HOLZ, RESTPLATTEN OK")
assert any("Rahmen mitgelasert: 4 stehende Wände" in x for x in LOG), "Laser-Rahmen wurde nicht erzeugt"
print("LASER-RAHMEN OK")
_ifcs = [os.path.join(r_, f_) for r_, _, fs_ in os.walk(os.path.join(TMP, "ziel")) for f_ in fs_ if f_.endswith(".ifc")]
assert _ifcs, "keine IFC"
_txt = open(_ifcs[0], encoding="utf-8", errors="ignore").read()
assert "IFCINDEXEDTRIANGLETEXTUREMAP" in _txt and "IFCIMAGETEXTURE" in _txt, "IFC ohne Luftbild-Textur"
assert [f_ for r_, _, fs_ in os.walk(os.path.join(TMP, "ziel")) for f_ in fs_ if f_.endswith("_luftbild.jpg")], "Luftbild-Datei fehlt"
assert any("ebene_a: kein Luftbild" in x for x in LOG) and any("Ebene x: Luftbild erkannt" in x for x in LOG), "Luftbildsuche hat die Hilfsebene nicht übersprungen"
print("LUFTBILD-EBENENWAHL OK (Befliegungsübersicht übersprungen)")
import ifcopenshell as _io
_m = _io.open(_ifcs[0]); assert _m.by_type("IfcIndexedTriangleTextureMap"), "Texturzuordnung fehlt"
print("LUFTBILD-TEXTUR IM IFC OK", len(_m.by_type("IfcIndexedTriangleTextureMap")))
assert any("Höhenlinien auf den Platten" in x for x in LOG), "Höhenlinien auf den Platten fehlen"
print("HOEHENLINIEN-GRAVUR OK")
from architools import zusatz as _Z
assert not any("FEHLER in umgebung" in x for x in LOG), "Umgebung ist abgestürzt (Plugin-Hook?)"
if _Z.hat("ifc_ende"):
    assert any("Fassadenfotos" in x for x in LOG), "Plugin-Hook ifc_ende wurde nicht aufgerufen"
    print("PLUGIN-HOOK IFC OK")
if _Z.hat("modell_raster_bild"):
    assert any("Teststreifen" in x for x in LOG), "Rastergravur (Zusatzmodul) hat keinen Teststreifen erzeugt"
    print("RASTERGRAVUR (ZUSATZMODUL) OK")
else:
    assert any("Zusatzmodul dafür ist nicht installiert" in x for x in LOG), "Hinweis zur fehlenden Rastergravur fehlt"
    print("RASTERGRAVUR OHNE ZUSATZMODUL: Hinweis und Rückfall OK")

fehler = [k for k, v in erg.items() if isinstance(v, dict) and v.get("fehler")]
fehlend = [k for k in MUSS if k not in p["stand"]]
if fehler or fehlend:
    raise SystemExit(f"Smoke-Test fehlgeschlagen: Fehler in {fehler}, nicht erzeugt: {fehlend}")
print("SMOKE-TEST OK")

# Regression (Build 7): die Datei-Routen der Oberfläche (/datei, /bild/...) werden nur über Dekoratoren angemeldet und sahen für
# Aufräum-Werkzeuge "ungenutzt" aus. Ohne sie bleiben Vorschau und Ergebnis leer.
from nicegui import app as _ng_app
from architools.gui import stil as _stil
_routen = {getattr(r, "path", "") for r in _ng_app.routes}
assert {"/datei", "/bild/abschluss.jpg", "/bild/maskottchen.gif"} <= _routen, _routen
_t = os.path.join(TMP, "route_test.txt"); open(_t, "w").write("x")
assert _stil.url(_t).startswith("/datei?p="), "url()"
print("OBERFLAECHEN-ROUTEN OK")

# CAD zu Lasercut (Build 10): Probe-Entwurf (Haus mit Satteldach, Anbau, runder Turm) in allen drei Bauweisen zerlegen
import numpy as _np
import trimesh as _tm
from architools.modell import cad_lasercut as _CAD
from architools.modell.config import default_config as _dc
_v = _np.array([[0, 0, 0], [12, 0, 0], [12, 8, 0], [0, 8, 0], [0, 0, 6], [12, 0, 6], [12, 8, 6], [0, 8, 6], [0, 4, 9], [12, 4, 9]], float)
_f = [[0, 2, 1], [0, 3, 2], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7],
      [4, 5, 9], [4, 9, 8], [7, 8, 9], [7, 9, 6], [4, 8, 7], [5, 6, 9]]
_haus = _tm.Trimesh(_v, _f); _haus.fix_normals()
_turm = _tm.creation.cylinder(radius=2, height=9, sections=24); _turm.apply_translation([-4, 4, 4.5])
_cad_datei = os.path.join(TMP, "cad_entwurf.obj")
_tm.util.concatenate([_haus, _turm]).export(_cad_datei)
for _modus in ("flaeche", "falt", "stapel"):
    _w = dict(_CAD.STANDARD, dateien=[_cad_datei], modus=_modus, massstab=200, ausgabe_ordner=os.path.join(TMP, "cad_" + _modus), name="t")
    _r = _CAD.lasercut(_w, _dc(), lambda *a: None)
    assert _r["teile"] > 10 and _r["platten"] >= 1, (_modus, _r["teile"], _r["platten"])
    assert _r["kosten"]["brutto"] > 0 and os.path.exists(_r["kostenliste"]), "Kostenschätzung fehlt"
    assert os.path.exists(_r["vorschau_laser"]) and os.path.exists(_r["vorschau_explosion"]), "3D-Vorschau fehlt"
    assert all(os.path.exists(x) for x in _r["laser_pdfs"]), "Platten-PDFs fehlen"
print("CAD ZU LASERCUT OK (flaeche, falt, stapel)")

# Die Knöpfe der Werkzeug-Seiten rufen ihre Funktion mit (…, log, prog) auf (Lauf.starten) – ein Argument zu wenig brach sie ab
import re as _re
_wz = open(os.path.join(os.path.dirname(_stil.__file__), "werkzeuge.py"), encoding="utf-8").read()
assert not _re.search(r"starten\(lambda w, cfg, log:", _wz), "Lauf.starten ruft mit log UND prog auf"
print("WERKZEUG-AUFRUFE OK")

# CAD zu Lasercut, Bauweise „Bauteile aus IFC“: Test-Haus (Wände mit Öffnungen, Decken, Satteldach, Gelände- und Weg-Mesh)
try:
    import ifcopenshell  # noqa: F401
    _hat_ifc = True
except ImportError:
    _hat_ifc = False
if _hat_ifc:
    sys.path.insert(0, os.path.join(os.getcwd(), "bau"))
    import testmodell_ifc
    from architools.modell import cad_lasercut as _CL, config as _MC
    _ifc = testmodell_ifc.bauen(os.path.join(TMP, "testhaus.ifc"))
    _cfg = _MC.default_config()
    _cfg["laser"]["material"], _cfg["laser"]["staerke_mm"] = "Graukarton", 1.0
    _w = dict(_CL.STANDARD, dateien=[_ifc], massstab=100, modus="flaeche", umwandlung="bauteile", ausgabe_ordner=os.path.join(TMP, "cadb"),
              name="haus", materialien=[{"sorte": "Finnpappe", "staerke_mm": 1.5}],
              gruppen_wahl={"wand": {"an": True, "material": 1}, "sonst": {"an": False}})
    _L = []
    _r = _CL.lasercut(_w, _cfg, _L.append)
    _ids = {}
    assert _r["teile"] > 20 and len(_r["materialien"]) == 2, (_r["teile"], _r.get("materialien"))
    assert any("Wände: 9 Teile" in x for x in _L), [x for x in _L if "Wände" in x]           # 30 cm / 1,5 mm = 2 Lagen
    assert any("27 Schichten" in x for x in _L), [x for x in _L if "Gelände" in x]
    assert set(_r["vorschau_gruppen"]) >= {"wand", "decke", "dach", "gelaende"}, _r["vorschau_gruppen"]
    print("CAD-BAUTEILE OK", _r["teile"], "Teile,", _r["material"])
else:
    print("CAD-BAUTEILE übersprungen (ifcopenshell fehlt)")
