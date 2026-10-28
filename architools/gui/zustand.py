"""Gemeinsamer Zustand: das geöffnete Projekt (ein Fenster = ein Projekt)."""
import os

from .. import projekt as P

Z = {"p": None}


def projekt():
    if Z["p"] is None:
        liste = P.zuletzt()
        Z["p"] = None
        for pfad in liste:
            try:
                Z["p"] = P.laden(pfad)
                break
            except Exception:
                continue
        if Z["p"] is None:
            Z["p"] = P.neues_projekt("Neues Projekt")
    return Z["p"]


def neu(name="Neues Projekt"):
    Z["p"] = P.neues_projekt(name)
    return Z["p"]


def oeffnen(pfad):
    Z["p"] = P.laden(pfad)
    return Z["p"]


def speichern(p=None):
    p = p or projekt()
    ziel = os.path.join(p["ordner"], P.sicher(p["name"]) + P.ENDUNG)
    return P.speichern(p, ziel)
