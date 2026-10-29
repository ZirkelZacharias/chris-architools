"""bericht.txt – der lesbare Bericht zu einem Export (für den Nutzer, nicht zur Fehlersuche).

Inhalt: Überblick, Ergebnisse, Kosten- und Materialschätzung, verwendete Datenquellen, Hinweise zur Datenqualität, Laufzeiten.
Das Programmprotokoll (jede Zeile des Rechenkerns, für die Fehlersuche) steht getrennt in protokoll.txt.
Alle Zahlen zu Kosten und Material sind Schätzungen; der Bericht sagt das an jeder Stelle.
"""
import datetime
import os
import re

from . import projekt as P

# Stichwort im Protokoll -> (Quelle, Vermerk). Es kommt nur in den Bericht, was im Lauf tatsächlich vorkam.
_QUELLEN = [
    (r"DGM1|Gelände|Gelaende|\.tif", "Geländemodell DGM1 (Geoportal Berlin / Landesvermessung)", "dl-de/zero-2-0 (Berlin); andere Länder siehe QUELLEN.txt"),
    (r"LoD2", "3D-Gebäudemodelle LoD2 (Geoportal Berlin)", "dl-de/zero-2-0"),
    (r"ALKIS", "ALKIS (Flurstücke, Gebäudegrundrisse, tatsächliche Nutzung)", "dl-de/zero-2-0"),
    (r"Baumbestand|Bäume|Baeume|Strassenbaeume|Anlagenbaeume", "Baumbestand Berlin (Straßen- und Anlagenbäume)",
     "Straßenbäume dl-de/zero-2-0; Anlagenbäume Grün Berlin GmbH mit Namensnennung"),
    (r"OpenStreetMap|OSM|Overpass", "OpenStreetMap (Ergänzungen: Gebäude, Gleise, Brücken …)", "© OpenStreetMap-Mitwirkende, ODbL 1.0"),
    (r"Umweltatlas", "Umweltatlas Berlin (Gebäude-/Vegetationshöhen)", "dl-de/by-2-0 bzw. zero – siehe QUELLEN.txt"),
    (r"Fussgaengernetz|Fußgängernetz|Gehweg", "Fußgängernetz Berlin (Gehwege)", "dl-de/zero-2-0"),
    (r"Radverkehr", "Radverkehrsnetz Berlin", "dl-de/zero-2-0"),
    (r"WMS|Luftbild|Kartenbild", "Kartenbilder / Luftbilder (WMS Geoportal Berlin)", "je nach Dienst; K5 mit Namensnennung (dl-de/by-2-0)"),
    (r"Copernicus", "Copernicus-Geländemodell GLO-30", "Contains modified Copernicus DEM data (GLO-30), EU/ESA"),
]

# Zeilen des Protokolls, die dem Nutzer auffallen sollen
_AUFFAELLIG = re.compile(r"HINWEIS|Hinweis|WARNUNG|ACHTUNG|FEHLER|FEHLT|geschaetzt|geschätzt|vermutlich|ungetestet|nicht moeglich|nicht möglich|"
                         r"übersprungen|uebersprungen|Gelaende hoeher|unvollstaendig", re.I)


def _groesse(pfad):
    try:
        n = os.path.getsize(pfad)
    except OSError:
        return ""
    return f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{max(n / 1e3, 0.1):.0f} KB"


def _dateien(p, erg, key):
    """Erzeugte Dateien einer Ausgabe (absolute Pfade, soweit vorhanden)."""
    s = (p.get("stand") or {}).get(key) or {}
    out = []
    for f in s.get("dateien") or []:
        f = f if os.path.isabs(f) else os.path.join(p["ordner"], f)
        out.append(f)
    return out


def _kuerzen(z, n=170):
    z = " ".join(str(z).split())
    return z if len(z) <= n else z[:n - 1] + "…"


def text(p, ausgaben, erg, zeilen, dauer, zeiten):
    from . import VERSION
    L = []
    add = L.append
    jetzt = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    add(f"BERICHT – {p.get('name', 'Projekt')}")
    add("=" * 60)
    add(f"Erstellt am {jetzt} mit Zacharias Tools {VERSION}. Dauer des Laufs: {_dauer(dauer)}.")
    add("Alles zu Kosten, Material und Zeit ist eine SCHÄTZUNG und keine Kalkulation. Daten amtlicher Stellen und aus OpenStreetMap "
        "können Lücken und Fehler haben – bitte vor Abgabe oder Bestellung prüfen.")
    add("(Das vollständige Programmprotokoll für die Fehlersuche steht in protokoll.txt.)")
    add("")

    # ------------------------------------------------------------ Überblick
    add("1  ÜBERBLICK")
    add("-" * 60)
    g = p.get("gebiet") or {}
    m = g.get("mitte_en")
    if m:
        add(f"Mittelpunkt (ETRS89/UTM 33N): Ost {m[0]:.0f}, Nord {m[1]:.0f}")
    u = p.get("umgebung") or {}
    if any(P.AUSGABEN[a][4] == "umgebung" for a in ausgaben):
        add(f"Umgebung: {u.get('breite', 0):.0f} × {u.get('hoehe', 0):.0f} m, davon Nahbereich {u.get('nah_breite', 0):.0f} × {u.get('nah_hoehe', 0):.0f} m")
    if "laser" in ausgaben or "druck" in ausgaben:
        add(f"Modell: Maßstab 1:{p['modell'].get('massstab')}, Platte {g.get('breite_cm', 0):.0f} × {g.get('hoehe_cm', 0):.0f} cm")
    add("Gewählte Ausgaben: " + ", ".join(P.AUSGABEN[a][0] for a in ausgaben))
    add("")

    # ------------------------------------------------------------ Ergebnisse
    add("2  ERGEBNISSE")
    add("-" * 60)
    gruppen = {"umgebung": "Umgebung", "modell": "Modellbau", "schnitt": "Geländeschnitt", "hoehenlinien": "Höhenlinien"}
    for g_, name in gruppen.items():
        if g_ not in erg:
            continue
        r = erg[g_] or {}
        t = zeiten.get(g_)
        zt = f" ({_dauer(t)})" if t else ""
        if r.get("fehler"):
            add(f"{name}{zt}: FEHLER – {_kuerzen(r['fehler'])}  (Einzelheiten in protokoll.txt)")
        else:
            add(f"{name}{zt}: fertig")
    add("")
    schon = set()
    for a in ausgaben:
        fs = [f for f in _dateien(p, erg, a) if os.path.exists(f) and f not in schon]
        schon.update(fs)
        if not fs:
            continue
        add(f"{P.AUSGABEN[a][0]}: {len(fs)} Datei(en)")
        for f in fs[:12]:
            add(f"    {os.path.relpath(f, P.ausgabe_basis(p)) if f.startswith(P.ausgabe_basis(p)) else f}  ({_groesse(f)})")
        if len(fs) > 12:
            add(f"    … und {len(fs) - 12} weitere")
    add("")

    # ------------------------------------------------------------ Kosten / Material
    add("3  KOSTEN- UND MATERIALSCHÄTZUNG")
    add("-" * 60)
    kt = ((erg.get("modell") or {}).get("kosten_text") or "").strip()
    if kt:
        add("Aus der Zuschnitt- und Kostenliste des Modellbaus (die ausführliche Liste liegt im Ordner modell):")
        add("")
        add(kt)
    else:
        if "laser" in ausgaben or "druck" in ausgaben:
            add("Für den Modellbau konnte keine Kostenliste erstellt werden (siehe protokoll.txt).")
        else:
            add("Kein Modellbau gewählt – damit entstehen keine Material- und Laserkosten, die das Programm schätzen kann.")
    sonst = [a for a in ausgaben if P.AUSGABEN[a][4] != "modell"]
    if sonst:
        add("")
        add("Plan- und Datenausgaben (IFC, Lageplan, Schwarzplan, Schnitt, Höhenlinien) sind digital; Plot-/Druckkosten schätzt das Programm nicht.")
    add("")

    # ------------------------------------------------------------ Quellen
    add("4  DATENQUELLEN DIESES LAUFS")
    add("-" * 60)
    voll = "\n".join(z for z in zeilen if not re.search(r"FEHLER|uebersprungen|übersprungen|nicht verfuegbar|nicht verfügbar|Kein ", str(z)))
    gefunden = [(n, v) for rx, n, v in _QUELLEN if re.search(rx, voll, re.I)]
    if gefunden:
        for n, v in gefunden:
            add(f"  - {n}\n      Vermerk: {v}")
    else:
        add("  (im Protokoll keine Datenquellen erkannt – siehe QUELLEN.txt)")
    add("(Erkannt anhand des Programmprotokolls. Eigene Dateien unterliegen den Rechten ihrer Urheber.)")
    add("Die vollständigen Vermerke und Lizenztexte stehen in QUELLEN.txt im Ausgabeordner. Für Pläne und Arbeiten bitte übernehmen, z. B.:")
    add('  "Datengrundlage: Geoportal Berlin (Datenlizenz Deutschland, Zero bzw. Namensnennung 2.0); © OpenStreetMap-Mitwirkende (ODbL)"')
    add("")

    # ------------------------------------------------------------ Hinweise
    add("5  HINWEISE ZUR DATENQUALITÄT")
    add("-" * 60)
    gesehen, n = set(), 0
    for z in zeilen:
        z = str(z).strip()
        if not z or not _AUFFAELLIG.search(z) or z.startswith("+ ") or z.startswith("==="):
            continue
        k = re.sub(r"\d+", "#", z)[:90]
        if k in gesehen:
            continue
        gesehen.add(k)
        add("  - " + _kuerzen(z))
        n += 1
        if n >= 40:
            add("  … weitere Hinweise stehen in protokoll.txt")
            break
    # Gelände über Gebäude-Oberkante: die betroffenen Gebäude nennen und sagen, was zu prüfen ist
    for i, z in enumerate(zeilen):
        if "Gelaende hoeher als die Gebaeude-Oberkante" in str(z):
            add("  - Zu den Gelände-Hinweisen: Betroffen sind die oben genannten Gebäude (Kennung, überdeckte Fläche, Höhenunterschied):")
            for w in zeilen[i + 1:i + 6]:
                if str(w).startswith("    ") and "m2" in str(w):
                    add("      " + _kuerzen(str(w).strip(), 150))
            add("    Bitte prüfen: Hang oder Einschnitt, Gleisbett, Brücke bzw. ein falsch gelesenes Geländeraster? Das Gelände wird nur dort "
                "ausgeschnitten, wo es über der Oberkante liegt; bei zu niedrig angesetzten Gebäudehöhen hilft „Höhe ohne LoD2“ in den Einstellungen.")
            n += 1
            break
    gesch = sum(int(m.group(1)) for m in (re.search(r"(\d+) mit geschaetzter Hoehe", str(z)) for z in zeilen) if m)
    ergaenzt = sum(int(m.group(1)) for m in (re.search(r"LoD2-Luecken gefuellt: (\d+) Gebaeude", str(z)) for z in zeilen) if m)
    if ergaenzt and gesch / ergaenzt > 0.5 and not (p.get("umgebung") or {}).get("ua_gebaeudehoehen"):
        add(f"  - TIPP: {gesch} von {ergaenzt} ergänzten Gebäuden (ohne LoD2) haben nur eine geschätzte Höhe. Bessere Höhen liefert in den Einstellungen "
            "„Gebäude ohne LoD2: Höhe und Dachform aus den Umweltatlas-Gebäudehöhen“.")
        n += 1
    if not n:
        add("  Keine Auffälligkeiten gemeldet.")
    add("")

    # ------------------------------------------------------------ Plausibilität
    pl = [str(z).replace("[Plausibilität] ", "", 1).strip() for z in zeilen if str(z).startswith("[Plausibilität] ")]
    ran = any("Plausibilitätsprüfung:" in str(z) for z in zeilen)
    if ran or pl:
        add("6  PLAUSIBILITÄTSPRÜFUNG (Ausreißer in den Daten)")
        add("-" * 60)
        add("Das Programm hat die geladenen Daten auf Auffälligkeiten durchsucht. Es ändert nichts – die Hinweise sind Anlässe zum Nachsehen, keine Fehler.")
        if pl:
            for z in pl:
                add("  - " + _kuerzen(z, 200))
        else:
            add("  Keine Ausreißer bei Gebäudehöhen, Dachformen, Grundrissen, Gelände und Bäumen gefunden.")
        add("")

    # ------------------------------------------------------------ Laufzeiten
    add("7  WEITERES")
    add("-" * 60)
    for g_, t in zeiten.items():
        add(f"  Laufzeit {gruppen.get(g_, g_)}: {_dauer(t)}")
    add(f"  Ausgabeordner: {P.ausgabe_basis(p)}")
    add("  protokoll.txt = Programmprotokoll (für die Fehlersuche weitergeben) · QUELLEN.txt = Lizenzvermerke")
    return "\n".join(L) + "\n"


def _dauer(s):
    s = float(s or 0)
    return f"{s:.0f} s" if s < 90 else f"{s / 60:.1f} min"


def schreiben(p, ausgaben, erg, zeilen, dauer, zeiten, ordner=None):
    """bericht.txt und protokoll.txt in den Ausgabeordner. Fehler werden verschluckt: der Bericht darf nie einen Export verhindern."""
    ordner = ordner or P.ausgabe_basis(p)
    try:
        os.makedirs(ordner, exist_ok=True)
        with open(os.path.join(ordner, "bericht.txt"), "w", encoding="utf-8") as f:
            f.write(text(p, ausgaben, erg, zeilen, dauer, zeiten))
        with open(os.path.join(ordner, "protokoll.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(str(z) for z in zeilen) + "\n")
        return os.path.join(ordner, "bericht.txt")
    except Exception:
        return None
