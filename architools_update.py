"""Spielt Update-Dateien ein (nur Python-Standardbibliothek).

Eine Update-Datei ist eine ZIP mit update.json und nur den geänderten oder neuen Dateien (gleiche Ordnerstruktur wie das
Programm). Das Programm bleibt sonst unverändert; Projekte, Einstellungen und die Python-Umgebung (.venv) werden nie angefasst.

  * Datei in den Ordner  updates/  legen und das Programm starten (START.bat / START.command) – oder
  * in der Oberfläche: Einstellungen → Programm-Update → Update einspielen.

Ersetzte Dateien landen vorher in  updates/_sicherung/stand_<alt>/ ; eingespielte Updates in  updates/_eingespielt/ .
Ablauf per Hand ist auch möglich: ZIP entpacken und den Ordner „ChrisArchItools“ über den vorhandenen kopieren
(stand.json wird dabei mit aktualisiert).
"""
import hashlib
import json
import os
import shutil
import sys
import time
import zipfile

HIER = os.path.dirname(os.path.abspath(__file__))
STAND = os.path.join(HIER, "stand.json")
UPDATES = os.path.join(HIER, "updates")
WURZEL = "ChrisArchItools/"
GESCHUETZT = (".venv", "projekte", "updates", ".git")


def stand_lesen():
    """Aktueller Stand (Build-Nummer) des Programms; ohne stand.json gilt Stand 1 (erste Auslieferung)."""
    try:
        with open(STAND, encoding="utf-8") as fh:
            return int(json.load(fh).get("build", 1))
    except (OSError, ValueError):
        return 1


def _sha(daten):
    return hashlib.sha256(daten).hexdigest()


def _info(z):
    namen = z.namelist()
    pre = WURZEL if any(n.startswith(WURZEL) for n in namen) else ""
    for n in (pre + "update.json", "update.json"):
        if n in namen:
            return json.loads(z.read(n).decode("utf-8")), pre
    raise ValueError("update.json fehlt – das ist keine Update-Datei von Chris ArchItools.")


def pruefen(pfad):
    """-> (info, praefix) oder wirft ValueError mit verständlicher Meldung."""
    try:
        z = zipfile.ZipFile(pfad)
    except (OSError, zipfile.BadZipFile) as e:
        raise ValueError(f"{os.path.basename(pfad)} lässt sich nicht öffnen ({e}).")
    with z:
        info, pre = _info(z)
        if z.testzip():
            raise ValueError(f"{os.path.basename(pfad)} ist beschädigt – bitte neu herunterladen.")
    return info, pre


def anwenden(pfad, log=print):
    """Spielt eine Update-Datei ein. -> (True/False, Meldung). Bei Fehlern wird nichts halb verändert (erst prüfen, dann schreiben)."""
    try:
        info, pre = pruefen(pfad)
    except ValueError as e:
        return False, str(e)
    jetzt, von, nach = stand_lesen(), int(info.get("von", 0)), int(info.get("nach", 0))
    name = os.path.basename(pfad)
    if nach <= jetzt:
        return True, f"{name}: schon eingespielt (Stand {jetzt})."
    if von != jetzt:
        return False, (f"{name} baut auf Stand {von} auf, installiert ist Stand {jetzt}. "
                       + (f"Bitte erst das Update für Stand {jetzt} → {jetzt + 1} einspielen." if von > jetzt else
                          "Diese Datei passt nicht zur installierten Version."))
    with zipfile.ZipFile(pfad) as z:
        dateien = info.get("dateien", {})
        neu = {}
        for rel, soll in dateien.items():
            daten = z.read(pre + rel)
            if soll and _sha(daten) != soll:
                return False, f"{name}: Datei {rel} ist beschädigt – bitte das Update neu herunterladen. Es wurde nichts verändert."
            neu[rel] = daten
        sich = os.path.join(UPDATES, "_sicherung", f"stand_{jetzt}")
        geaendert, req_alt = 0, None
        rp = os.path.join(HIER, "requirements.txt")
        if os.path.exists(rp):
            req_alt = open(rp, "rb").read()
        loeschen = [r for r in info.get("loeschen", []) if not r.split("/")[0] in GESCHUETZT]
        for rel in list(neu) + loeschen:
            if rel.split("/")[0] in GESCHUETZT or ".." in rel.split("/") or os.path.isabs(rel):
                return False, f"{name}: unzulässiger Pfad {rel}."
            ziel = os.path.join(HIER, *rel.split("/"))
            if os.path.exists(ziel):                                       # Sicherung der alten Datei
                s = os.path.join(sich, *rel.split("/"))
                os.makedirs(os.path.dirname(s), exist_ok=True)
                shutil.copy2(ziel, s)
        for rel, daten in neu.items():
            ziel = os.path.join(HIER, *rel.split("/"))
            os.makedirs(os.path.dirname(ziel), exist_ok=True)
            tmp = ziel + ".neu"
            with open(tmp, "wb") as fh:
                fh.write(daten)
            if rel.endswith(".command") or rel.endswith(".sh"):
                os.chmod(tmp, 0o755)
            os.replace(tmp, ziel)
            geaendert += 1
        for rel in loeschen:
            ziel = os.path.join(HIER, *rel.split("/"))
            if os.path.isfile(ziel):
                os.remove(ziel)
        with open(STAND, "w", encoding="utf-8") as fh:
            json.dump({"build": nach, "version": info.get("version", ""), "zeit": time.strftime("%Y-%m-%d %H:%M")}, fh)
    meldung = f"{name}: Stand {jetzt} → {nach} eingespielt ({geaendert} Dateien geändert oder neu, {len(loeschen)} entfernt)."
    if os.path.exists(rp) and open(rp, "rb").read() != req_alt:
        open(os.path.join(HIER, "pakete_neu.txt"), "w").write("requirements.txt hat sich geändert\n")
        meldung += " Die Python-Pakete werden beim nächsten Start nachinstalliert."
    if info.get("hinweis"):
        meldung += "\n" + info["hinweis"]
    return True, meldung


def ausstehend():
    """Update-Dateien im Ordner updates/, nach Zielstand sortiert."""
    if not os.path.isdir(UPDATES):
        return []
    out = []
    for f in os.listdir(UPDATES):
        p = os.path.join(UPDATES, f)
        if f.lower().endswith(".zip") and os.path.isfile(p):
            try:
                info, _ = pruefen(p)
                out.append((int(info.get("nach", 0)), p))
            except (ValueError, OSError):
                out.append((10 ** 9, p))
    return [p for _, p in sorted(out)]


def alle_anwenden(log=print):
    """Alle Update-Dateien aus updates/ der Reihe nach einspielen. -> Liste der Meldungen."""
    meldungen = []
    for p in ausstehend():
        ok, m = anwenden(p, log)
        meldungen.append(m)
        log(m)
        if ok:
            ziel = os.path.join(UPDATES, "_eingespielt")
            os.makedirs(ziel, exist_ok=True)
            try:
                shutil.move(p, os.path.join(ziel, os.path.basename(p)))
            except OSError:
                pass
        else:
            break
    return meldungen


if __name__ == "__main__":
    if len(sys.argv) > 1:                                                  # python architools_update.py <Datei.zip>
        print(anwenden(sys.argv[1])[1])
    else:
        alle_anwenden()
