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
p["modell"]["laser"]["rahmen"] = {"aktiv": True, "breite_mm": 15.0}
p["modell"]["laser"]["restplatten"] = [{"name": "Rest A", "b_mm": 400, "h_mm": 300, "anzahl": 1}]
from PIL import Image
_rj = os.path.join(TMP, "rasterbild.jpg")
Image.fromarray((np.add.outer(np.arange(120), np.arange(160)) % 255).astype("uint8")).save(_rj)    # Verlaufsbild für die Rastergravur
p["modell"]["raster_bild"] = {"aktiv": True, "quelle": "datei", "datei": _rj, "weite_mm": 0.8, "teststreifen": True}
p["modell"].setdefault("ebenen", {})["Gebäudenummern"] = "raster"
p["modell"]["holz"]["rahmen"]["aktiv"] = True; p["modell"]["holz"]["podest"]["aktiv"] = True
import ifcmap_wms as WM, io
from PIL import Image
_CAP = b'<WMT_MS_Capabilities version="1.1.1"><Capability><Layer><SRS>EPSG:25833</SRS><Layer><Name>x</Name><Title>x</Title></Layer></Layer></Capability></WMT_MS_Capabilities>'
def _wms_fake(url, ctx, timeout=90):
    if "GetCapabilities" in url:
        return _CAP, "text/xml"
    w = int(url.split("WIDTH=")[1].split("&")[0]); h = int(url.split("HEIGHT=")[1].split("&")[0])
    b = io.BytesIO(); Image.new("RGB", (w, h), (120, 160, 200)).save(b, "PNG"); return b.getvalue(), "image/png"
WM._holen = _wms_fake
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
assert any("Rahmen mitgelasert" in x for x in LOG), "Laser-Rahmen wurde nicht erzeugt"
print("LASER-RAHMEN OK")
from architools import zusatz as _Z
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
