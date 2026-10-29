"""Baut das portable Paket (eigenes Python + alle Bibliotheken, keine Installation nötig) für das System, auf dem es läuft.

  python bau/portable.py [--test]        ->  dist/ZachariasTools_<System>.zip

Läuft in GitHub Actions auf Windows, macOS (Apple Silicon) und macOS (Intel); lokal geht es auf Linux zum Ausprobieren.
Voraussetzung: uv (https://docs.astral.sh/uv/) – holt ein eigenständiges, verschiebbares Python 3.12.
"""
import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
NAME = "ZachariasTools"
PYVER = "3.12"
PRUEF = ("import numpy, scipy, shapely, rasterio, pyogrio, contourpy, matplotlib, trimesh, ezdxf, ezdwg, pymupdf, pandas, pyproj, "
         "PIL, ifcopenshell, nicegui, webview; print('Bibliotheken ok')")


def run(cmd, **kw):
    print("+", " ".join(map(str, cmd)), flush=True)
    return subprocess.run(cmd, check=True, **kw)


def system():
    s, m = platform.system(), platform.machine().lower()
    if s == "Windows":
        return "Windows"
    if s == "Darwin":
        return "Mac_AppleSilicon" if m in ("arm64", "aarch64") else "Mac_Intel"
    return "Linux"


def python_holen():
    run(["uv", "python", "install", PYVER])
    out = subprocess.check_output(["uv", "python", "find", PYVER, "--managed-python"], text=True).strip().splitlines()[-1]
    py = os.path.realpath(out)
    wurzel = os.path.dirname(py) if os.name == "nt" else os.path.dirname(os.path.dirname(py))
    print("Python:", py, "->", wurzel)
    return wurzel


def bauen():
    sysname = system()
    win = sysname == "Windows"
    ziel = os.path.join(DIST, NAME)
    shutil.rmtree(ziel, ignore_errors=True)
    prog = os.path.join(ziel, "programm")                      # alles Technische liegt hier; oben nur Starter und Anleitung
    os.makedirs(prog)
    t0 = time.time()
    # 1) eigenes Python
    shutil.copytree(python_holen(), os.path.join(prog, "python"), symlinks=True)
    for f in glob.glob(os.path.join(prog, "python", "**", "EXTERNALLY-MANAGED"), recursive=True):
        os.remove(f)
    py = os.path.join(prog, "python", "python.exe") if win else os.path.join(prog, "python", "bin", "python3")
    if not os.path.exists(py):
        cand = glob.glob(os.path.join(prog, "python", "bin", "python3*"))
        py = sorted(cand)[0]
    # 2) Bibliotheken
    req = os.path.join(ROOT, "requirements.txt")
    try:
        run(["uv", "pip", "install", "--python", py, "--break-system-packages", "--prefer-binary" if False else "--no-progress", "-r", req])
    except subprocess.CalledProcessError:
        print("uv pip hat nicht geklappt - versuche pip", flush=True)
        run([py, "-m", "ensurepip", "--upgrade"])
        run([py, "-m", "pip", "install", "--prefer-binary", "-r", req])
    # 3) Programm
    for n in ("architools", "beispiel"):
        shutil.copytree(os.path.join(ROOT, n), os.path.join(prog, n),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "projekte", ".vorschau"))
    for n in ("architools_app.py", "architools_update.py", "requirements.txt"):
        shutil.copy2(os.path.join(ROOT, n), os.path.join(prog, n))
    build = int(os.environ.get("ARCHITOOLS_BUILD") or open(os.path.join(ROOT, "stand.txt")).read().strip())
    json.dump({"build": build, "version": "0.1", "zeit": time.strftime("%Y-%m-%d")}, open(os.path.join(prog, "stand.json"), "w"))
    # 4) Starter + Anleitung
    start = "Zacharias Tools starten.bat" if win else "Zacharias Tools starten.command"
    a = open(os.path.join(ROOT, "docs", "ANLEITUNG_portabel.md"), encoding="utf-8").read().replace("@START@", start)
    a = re.sub(r"<!--WINDOWS-->(.*?)<!--MAC-->(.*?)<!--ENDE-->", lambda m: m.group(1) if win else m.group(2), a, flags=re.S)
    open(os.path.join(ziel, "ANLEITUNG.md"), "w", encoding="utf-8").write(a)
    shutil.copy2(os.path.join(ROOT, "docs", "entscheidungen.md"), os.path.join(prog, "ENTSCHEIDUNGEN.md"))
    if win:
        unblock = ('if not exist ".entsperrt" (\r\n'
                   '  echo Beim ersten Start wird das Programm fuer Windows freigegeben - das dauert etwa eine halbe Minute ...\r\n'
                   '  powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -Recurse -File -Include *.dll,*.exe,*.pyd,*.py | Unblock-File" >nul 2>&1\r\n'
                   '  echo ok> .entsperrt\r\n)\r\n')
        open(os.path.join(ziel, start), "w", newline="\r\n").write(
            '@echo off\r\ncd /d "%~dp0programm"\r\nset PYTHONUTF8=1\r\n' + unblock +
            'python\\python.exe architools_update.py\r\n'
            'start "" python\\pythonw.exe architools_app.py\r\n')
        open(os.path.join(prog, "Mit Fehlerfenster starten.bat"), "w", newline="\r\n").write(
            '@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\nset PYTHONUTF8=1\r\n' + unblock +
            'python\\python.exe architools_update.py\r\n'
            'python\\python.exe architools_app.py\r\npause\r\n')
        open(os.path.join(prog, "Im Browser starten.bat"), "w", newline="\r\n").write(
            '@echo off\r\ncd /d "%~dp0"\r\nset PYTHONUTF8=1\r\npython\\python.exe architools_app.py --browser\r\npause\r\n')
    else:
        p = os.path.join(ziel, start)
        open(p, "w", newline="\n").write(
            '#!/bin/bash\nDIR="$(cd "$(dirname "$0")" && pwd)"\n'
            'xattr -dr com.apple.quarantine "$DIR" >/dev/null 2>&1\ncd "$DIR/programm" || exit 1\nexport PYTHONUTF8=1\n'
            'PY=python/bin/python3\n"$PY" architools_update.py\n'
            '"$PY" architools_app.py "$@" || { echo; read -r -p "Fehler - Enter ..." _; }\n')
        os.chmod(p, 0o755)
    schlank(prog)
    print(f"Paket gebaut in {time.time() - t0:.0f} s", flush=True)
    return sysname, ziel, prog, py


def schlank(prog):
    """Entfernt, was zur Laufzeit nie gebraucht wird (Tests der Bibliotheken, Beispieldaten, Tcl/Tk, IDLE, Python-Tests, Zwischenspeicher
    der Installation). Das Paket wird so kleiner, das Programm läuft unverändert; der Rauchtest danach prüft das."""
    vorher = _groesse(prog)
    py = os.path.join(prog, "python")
    weg = []
    for r, ds, _ in os.walk(py):
        in_sp = "site-packages" in r.replace("\\", "/")
        for d in ds:
            if in_sp and d in ("tests", "test"):                           # Tests der Bibliotheken
                weg.append(os.path.join(r, d))
            elif not in_sp and d in ("test", "idlelib", "tkinter", "turtledemo", "lib2to3"):   # Pythons Tests, IDLE, Tk-Oberfläche
                weg.append(os.path.join(r, d))
            elif d == "sample_data" and os.path.basename(r) == "mpl-data":
                weg.append(os.path.join(r, d))
            elif not in_sp and (d in ("tcl", "tk") or d.startswith(("tcl8", "tk8"))):
                weg.append(os.path.join(r, d))
    for pfad in {w for w in weg if os.path.exists(w)}:
        shutil.rmtree(pfad, ignore_errors=True)
    for f in glob.glob(os.path.join(py, "**", "*"), recursive=True):
        n = os.path.basename(f).lower()
        if n in ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "_tkinter.so") or re.match(r"lib(tcl|tk)\d", n) or n.endswith(".pyi"):
            try:
                os.remove(f)
            except OSError:
                pass
    print(f"Schlank gemacht: {vorher:.0f} MB -> {_groesse(prog):.0f} MB", flush=True)


def _groesse(pfad):
    n = 0
    for r, _, fs in os.walk(pfad):
        for f in fs:
            try:
                n += os.path.getsize(os.path.join(r, f))
            except OSError:
                pass
    return n / 1e6


def packen(sysname, ziel):
    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, f"{NAME}_{sysname}_portabel.zip")
    if os.path.exists(out):
        os.remove(out)
    if os.name == "nt":
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for r, _, fs in os.walk(ziel):
                for f in fs:
                    voll = os.path.join(r, f)
                    z.write(voll, os.path.relpath(voll, DIST))
    else:                                                     # zip erhält Symlinks und Ausführrechte
        run(["zip", "-r", "-y", "-q", "-9", out, NAME], cwd=DIST)
    print("ZIP:", out, round(os.path.getsize(out) / 1e6), "MB", flush=True)
    return out


def testen(py, ziel):
    """Prüft das fertige Paket mit seinem eigenen Python (so, wie es bei dir läuft)."""
    ok = True
    run([py, "-c", PRUEF], cwd=ziel)
    if os.name == "nt":                                       # Programmfenster (pythonnet): nur melden, der Start fällt sonst auf den Browser zurück
        r = subprocess.run([py, "-c", "import clr; print('pythonnet (Programmfenster) ok')"], cwd=ziel, capture_output=True, text=True)
        print("pythonnet-Test:", (r.stdout + r.stderr).strip()[-600:], flush=True)
    run([py, os.path.join(ROOT, "bau", "smoke_e2e.py"), ziel], cwd=ziel)
    starter = [("python", py)]
    if os.name == "nt":
        starter.append(("pythonw", os.path.join(os.path.dirname(py), "pythonw.exe")))
    for name, exe in starter:
        serverpruefen(name, exe, ziel)


def serverpruefen(name, exe, ziel):
    port = 8799
    logname = os.path.join(DIST, f"server_{name}.log")
    logd = open(logname, "w")
    proc = subprocess.Popen([exe, "architools_app.py", "--browser", "--ohne-fenster", "--port", str(port)], cwd=ziel,
                            stdout=logd, stderr=subprocess.STDOUT)
    ok = False
    try:
        for _ in range(90):
            time.sleep(1)
            try:
                code = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3).status
                print(f"Startseite antwortet ({name}):", code, flush=True)
                ok = code == 200
                break
            except Exception:
                if proc.poll() is not None:
                    break
    finally:
        proc.terminate()
        try:
            proc.wait(15)
        except Exception:
            proc.kill()
        logd.close()
    log = open(logname, encoding="utf-8", errors="replace").read()
    print(f"--- Server-Log ({name}) ---\n" + log[-2500:], flush=True)
    if not ok or "Traceback" in log:
        raise SystemExit(f"Programmstart ({name}) fehlgeschlagen")


if __name__ == "__main__":
    s, z, prog, py = bauen()
    if "--test" in sys.argv:
        testen(py, prog)
    packen(s, z)
