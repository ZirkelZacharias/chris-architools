"""DXF -> DWG. Erste Wahl: der kostenlose ODA File Converter (volle Farben). Fehlt er, schreibt dwg_direkt.py die DWG im
Programm selbst (R2000, Farben vereinfacht). Klappt auch das nicht, bleibt es bei DXF."""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

SUCHE = [
    r"C:\Program Files\ODA\ODAFileConverter*\ODAFileConverter.exe",
    r"C:\Program Files (x86)\ODA\ODAFileConverter*\ODAFileConverter.exe",
    "/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter",
    "/usr/bin/ODAFileConverter", "/opt/ODAFileConverter/ODAFileConverter",
]


def finden(vorgabe=""):
    if vorgabe and os.path.exists(vorgabe):
        return vorgabe
    w = shutil.which("ODAFileConverter")
    if w:
        return w
    for m in SUCHE:
        t = sorted(glob.glob(m))
        if t:
            return t[-1]
    return None


def konvertieren(dxfs, oda=None, version="ACAD2018", log=print):
    """Schreibt neben jede DXF eine DWG. -> Liste der DWG-Dateien (leer, wenn der Konverter fehlt)."""
    oda = finden(oda or "")
    if not oda:
        from . import dwg_direkt
        out = []
        if not dwg_direkt.verfuegbar():
            log("  DWG: weder ODA File Converter noch das eingebaute DWG-Modul (ezdwg) gefunden – es bleibt bei DXF.")
            return []
        log("  DWG: ODA File Converter nicht gefunden – DWG wird direkt im Programm geschrieben (R2000, Farben vereinfacht).")
        for dxf in dxfs:
            if not dxf.lower().endswith(".dxf") or not os.path.exists(dxf):
                continue
            try:
                out.append(dwg_direkt.konvertieren(dxf, None, log))
            except Exception as e:
                log(f"  DWG direkt: {os.path.basename(dxf)} nicht möglich ({e}) – bleibt bei DXF.")
        return out
    out = []
    for dxf in dxfs:
        if not dxf.lower().endswith(".dxf") or not os.path.exists(dxf):
            continue
        quelle = tempfile.mkdtemp(prefix="oda_in_")
        ziel = tempfile.mkdtemp(prefix="oda_out_")
        try:
            shutil.copy(dxf, quelle)
            cmd = [oda, quelle, ziel, version, "DWG", "0", "1", os.path.basename(dxf)]
            if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
                xv = shutil.which("xvfb-run")
                if xv:
                    cmd = [xv, "-a"] + cmd
            subprocess.run(cmd, timeout=300, capture_output=True)
            dwg = os.path.join(ziel, os.path.splitext(os.path.basename(dxf))[0] + ".dwg")
            if os.path.exists(dwg):
                z = os.path.splitext(dxf)[0] + ".dwg"
                shutil.move(dwg, z)
                out.append(z)
            else:
                log(f"  DWG: {os.path.basename(dxf)} konnte nicht umgewandelt werden")
        except Exception as e:
            log(f"  DWG-Umwandlung fehlgeschlagen ({e})")
        finally:
            shutil.rmtree(quelle, ignore_errors=True)
            shutil.rmtree(ziel, ignore_errors=True)
    if out:
        log(f"  DWG: {len(out)} Datei(en) geschrieben")
    return out
