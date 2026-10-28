"""Baut das portable Paket (eigenes Python + alle Bibliotheken, keine Installation nötig) für das System, auf dem es läuft.

  python bau/portable.py [--test]        ->  dist/ChrisArchItools_<System>.zip

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
NAME = "ChrisArchItools"
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
    os.makedirs(ziel)
    t0 = time.time()
    # 1) eigenes Python
    shutil.copytree(python_holen(), os.path.join(ziel, "python"), symlinks=True)
    for f in glob.glob(os.path.join(ziel, "python", "**", "EXTERNALLY-MANAGED"), recursive=True):
        os.remove(f)
    py = os.path.join(ziel, "python", "python.exe") if win else os.path.join(ziel, "python", "bin", "python3")
    if not os.path.exists(py):
        cand = glob.glob(os.path.join(ziel, "python", "bin", "python3*"))
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
        shutil.copytree(os.path.join(ROOT, n), os.path.join(ziel, n),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "projekte", ".vorschau"))
    for n in ("architools_app.py", "architools_update.py", "requirements.txt"):
        shutil.copy2(os.path.join(ROOT, n), os.path.join(ziel, n))
    build = int(os.environ.get("ARCHITOOLS_BUILD") or open(os.path.join(ROOT, "stand.txt")).read().strip())
    json.dump({"build": build, "version": "0.1", "zeit": time.strftime("%Y-%m-%d")}, open(os.path.join(ziel, "stand.json"), "w"))
    # 4) Starter + Anleitung
    start = "Chris ArchItools starten.bat" if win else "Chris ArchItools starten.command"
    a = open(os.path.join(ROOT, "docs", "ANLEITUNG_portabel.md"), encoding="utf-8").read().replace("@START@", start)
    a = re.sub(r"<!--WINDOWS-->(.*?)<!--MAC-->(.*?)<!--ENDE-->", lambda m: m.group(1) if win else m.group(2), a, flags=re.S)
    open(os.path.join(ziel, "ANLEITUNG.md"), "w", encoding="utf-8").write(a)
    shutil.copy2(os.path.join(ROOT, "docs", "entscheidungen.md"), os.path.join(ziel, "ENTSCHEIDUNGEN.md"))
    if win:
        open(os.path.join(ziel, start), "w", newline="\r\n").write(
            '@echo off\r\ncd /d "%~dp0"\r\npython\\python.exe architools_update.py\r\n'
            'start "" python\\pythonw.exe architools_app.py\r\n')
        open(os.path.join(ziel, "Chris ArchItools mit Fehlerfenster.bat"), "w", newline="\r\n").write(
            '@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\npython\\python.exe architools_update.py\r\n'
            'python\\python.exe architools_app.py\r\npause\r\n')
    else:
        p = os.path.join(ziel, start)
        open(p, "w", newline="\n").write(
            '#!/bin/bash\ncd "$(dirname "$0")" || exit 1\n'
            'xattr -dr com.apple.quarantine . >/dev/null 2>&1\n'
            'PY=python/bin/python3\n"$PY" architools_update.py\n'
            '"$PY" architools_app.py "$@" || { echo; read -r -p "Fehler - Enter ..." _; }\n')
        os.chmod(p, 0o755)
    print(f"Paket gebaut in {time.time() - t0:.0f} s", flush=True)
    return sysname, ziel, py


def packen(sysname, ziel):
    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, f"{NAME}_{sysname}_portabel.zip")
    if os.path.exists(out):
        os.remove(out)
    if os.name == "nt":
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for r, _, fs in os.walk(ziel):
                for f in fs:
                    voll = os.path.join(r, f)
                    z.write(voll, os.path.relpath(voll, DIST))
    else:                                                     # zip erhält Symlinks und Ausführrechte
        run(["zip", "-r", "-y", "-q", out, NAME], cwd=DIST)
    print("ZIP:", out, round(os.path.getsize(out) / 1e6), "MB", flush=True)
    return out


def testen(py, ziel):
    """Prüft das fertige Paket mit seinem eigenen Python (so, wie es bei dir läuft)."""
    ok = True
    run([py, "-c", PRUEF], cwd=ziel)
    run([py, os.path.join(ROOT, "bau", "smoke_e2e.py"), ziel], cwd=ziel)
    # Server starten und die Startseite abrufen
    port = 8799
    logd = open(os.path.join(DIST, "server.log"), "w")
    proc = subprocess.Popen([py, "architools_app.py", "--browser", "--ohne-fenster", "--port", str(port)], cwd=ziel,
                            stdout=logd, stderr=subprocess.STDOUT)
    try:
        for _ in range(90):
            time.sleep(1)
            try:
                code = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3).status
                print("Startseite antwortet:", code, flush=True)
                ok = code == 200
                break
            except Exception:
                if proc.poll() is not None:
                    break
        else:
            ok = False
    finally:
        proc.terminate()
        try:
            proc.wait(15)
        except Exception:
            proc.kill()
        logd.close()
    log = open(os.path.join(DIST, "server.log"), encoding="utf-8", errors="replace").read()
    print("--- Server-Log ---\n" + log[-2500:], flush=True)
    if not ok or "Traceback" in log:
        raise SystemExit("Programmstart fehlgeschlagen")


if __name__ == "__main__":
    s, z, py = bauen()
    if "--test" in sys.argv:
        testen(py, z)
    packen(s, z)
