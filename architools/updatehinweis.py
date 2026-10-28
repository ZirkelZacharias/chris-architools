"""Update-Hinweis: fragt beim Start (im Hintergrund, ohne Anmeldung) bei GitHub nach der neuesten Veröffentlichung.

Es wird nichts heruntergeladen oder installiert – das Programm zeigt nur an, dass es einen neueren Stand gibt.
Ohne Internet oder bei Fehlern passiert still nichts.
"""
import json
import re
import urllib.request

REPO = "ZirkelZacharias/chris-architools"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
SEITE = f"https://github.com/{REPO}/releases/latest"


def neueste(timeout=6.0):
    """-> {"stand": int, "tag": str, "url": str, "titel": str} oder None (kein Internet / keine Veröffentlichung)."""
    try:
        req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json", "User-Agent": "ChrisArchItools"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        m = re.search(r"stand-(\d+)", d.get("tag_name", ""), re.I) or re.search(r"Stand\s+(\d+)", d.get("name", "") or "", re.I)
        if not m:
            return None
        return {"stand": int(m.group(1)), "tag": d.get("tag_name", ""), "url": d.get("html_url") or SEITE,
                "titel": d.get("name") or d.get("tag_name", "")}
    except Exception:
        return None


def ist_neuer(info, stand, ignoriert=0):
    return bool(info) and info["stand"] > int(stand) and info["stand"] != int(ignoriert or 0)
