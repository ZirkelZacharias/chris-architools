"""Zacharias Tools – Umgebung, Modellbau und Werkzeuge in einem Programm."""
import json as _json
import os as _os

try:                                                    # Stand (Build) aus stand.json, wird von Updates mitgeführt
    with open(_os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "stand.json"), encoding="utf-8") as _f:
        STAND = int(_json.load(_f).get("build", 1))
except (OSError, ValueError):
    STAND = 1
VERSION = f"0.1 · Stand {STAND}"
