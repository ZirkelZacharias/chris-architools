"""Startet Chris ArchItools:  python architools_app.py  [--browser] [--port 8765]"""
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))

# pythonw.exe (Start ohne Konsolenfenster) hat keine Standardausgabe: Meldungen in eine Protokolldatei umleiten;
# überall UTF-8, damit Umlaute in Meldungen nie zu Fehlern führen.
if sys.stdout is None or sys.stderr is None:
    try:
        _ord = os.path.join(os.path.expanduser("~"), ".architools")
        os.makedirs(_ord, exist_ok=True)
        _log = open(os.path.join(_ord, "programm.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or _log
        sys.stderr = sys.stderr or _log
    except OSError:
        pass
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if HIER not in sys.path:
    sys.path.insert(0, HIER)

if __name__ in {"__main__", "__mp_main__"}:
    try:                                                      # Update-Dateien aus dem Ordner updates/ einspielen
        import architools_update
        architools_update.alle_anwenden()
    except Exception as e:                                    # ein kaputtes Update darf den Start nie verhindern
        print("Update konnte nicht eingespielt werden:", e)
    from architools.gui import app
    args = sys.argv[1:]
    port = int(args[args.index("--port") + 1]) if "--port" in args else None
    app.start(native=False if "--browser" in args else None, port=port, show="--ohne-fenster" not in args)
