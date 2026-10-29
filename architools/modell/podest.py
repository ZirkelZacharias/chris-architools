"""Holz fürs Modell: Grundpodest (nur Zuschnittliste und Zeichnung, nichts wird gelasert). Der Rahmen ums Modell wird nicht mehr aus Holz
geschnitten, sondern mitgelasert (laser.rahmen); das Podest richtet sich dann nach dessen Außenmaß.

Das Podest hat Deckplatte, Rahmenbretter ringsum und bei Bedarf Stützrahmen im Unterbau – aber keinen Boden.
Alle Maße in mm; Längen sind Zuschnittlängen (Gehrung: längste Kante).
"""
import csv
import math
import os

SPIEL = 0.5          # Luft zwischen Modellplatte und Rahmen je Seite


def berechnen(cfg, modell_b, modell_h, stapel_hoehe):
    """-> dict(teile=[...], rahmen=dict|None, podest=dict|None, hinweise=[...]).
    Ein Teil: dict(pos, name, stueck, laenge, breite, dicke, bemerkung)"""
    hc = cfg.get("holz") or {}
    pc = hc.get("podest") or {}
    rc = {}                                                    # Holz-Rahmenleisten gibt es nicht mehr
    lr = (cfg.get("laser") or {}).get("rahmen") or {}
    teile, hinweise = [], []
    aussen_b, aussen_h = modell_b, modell_h
    res = {"teile": teile, "rahmen": None, "podest": None, "hinweise": hinweise}
    if rc.get("aktiv"):
        bl = float(rc.get("breite_mm") or 20.0)                 # Breite der Leiste von oben gesehen
        hl = float(rc.get("hoehe_mm") or 0) or float(stapel_hoehe)   # Höhe der Leiste
        gehr = bool(rc.get("gehrung", True))
        ib, ih = modell_b + 2 * SPIEL, modell_h + 2 * SPIEL     # Innenmaß des Rahmens
        if gehr:
            lang_b, lang_h = ib + 2 * bl, ih + 2 * bl
            bem = "Gehrung 45° an beiden Enden, Maß = längste Kante"
        else:
            lang_b, lang_h = ib + 2 * bl, ih
            bem = "stumpf: die langen Leisten laufen durch, die kurzen sitzen dazwischen"
        teile.append({"pos": "R1", "name": "Rahmenleiste lang", "stueck": 2, "laenge": lang_b, "breite": bl, "dicke": hl, "bemerkung": bem})
        teile.append({"pos": "R2", "name": "Rahmenleiste kurz", "stueck": 2, "laenge": lang_h, "breite": bl, "dicke": hl,
                      "bemerkung": bem})
        aussen_b, aussen_h = ib + 2 * bl, ih + 2 * bl
        res["rahmen"] = {"innen": (ib, ih), "aussen": (aussen_b, aussen_h), "leiste": (bl, hl)}
        if hl < stapel_hoehe - 0.01:
            hinweise.append(f"Rahmenleiste ({hl:.0f} mm hoch) ist niedriger als der Geländestapel ({stapel_hoehe:.0f} mm)")
    if lr.get("aktiv"):
        bl = float(lr.get("breite_mm") or 15.0)
        aussen_b, aussen_h = modell_b + 2 * SPIEL + 2 * bl, modell_h + 2 * SPIEL + 2 * bl
        res["rahmen"] = {"innen": (modell_b + 2 * SPIEL, modell_h + 2 * SPIEL), "aussen": (aussen_b, aussen_h), "leiste": (bl, stapel_hoehe)}
    if pc.get("aktiv"):
        H = float(pc.get("hoehe_mm") or 80.0)
        D = float(pc.get("deckplatte_mm") or 12.0)
        U = float(pc.get("ueberstand_mm") or 0.0)
        s = float(pc.get("rahmenholz_breite_mm") or 12.0)
        ab = float(pc.get("stuetz_abstand_mm") or 300.0)
        hu = H - D                                           # Höhe des Unterbaus
        if hu < 10:
            hinweise.append(f"Podesthöhe {H:.0f} mm ist zu niedrig für Deckplatte {D:.0f} mm und einen Unterbau")
            hu = max(hu, 10.0)
        db, dh = aussen_b + 2 * U, aussen_h + 2 * U
        teile.append({"pos": "P1", "name": "Deckplatte", "stueck": 1, "laenge": db, "breite": dh, "dicke": D,
                      "bemerkung": f"steht {U:.0f} mm über {'den Rahmen' if res['rahmen'] else 'das Modell'} hinaus"})
        ub, uh = aussen_b, aussen_h                         # Unterbau bündig mit dem Modell/Rahmen
        teile.append({"pos": "P2", "name": "Rahmenbrett lang", "stueck": 2, "laenge": ub, "breite": hu, "dicke": s,
                      "bemerkung": "Unterbau, außen, Oberkante bündig unter der Deckplatte"})
        teile.append({"pos": "P3", "name": "Rahmenbrett kurz", "stueck": 2, "laenge": uh - 2 * s, "breite": hu, "dicke": s,
                      "bemerkung": "zwischen den langen Brettern"})
        nx = max(0, math.ceil((ub - 2 * s) / ab) - 1)        # Stützen quer (Abstand der Reihen entlang der langen Seite)
        ny = max(0, math.ceil((uh - 2 * s) / ab) - 1)
        if nx:
            teile.append({"pos": "P4", "name": "Stützrahmen quer", "stueck": nx, "laenge": uh - 2 * s, "breite": hu, "dicke": s,
                          "bemerkung": f"gleichmäßig verteilt, Abstand ca. {(ub - 2 * s) / (nx + 1):.0f} mm"})
        if ny:
            seg = ((ub - 2 * s) - nx * s) / (nx + 1)
            teile.append({"pos": "P5", "name": "Stützrahmen längs (Stücke)", "stueck": ny * (nx + 1), "laenge": seg, "breite": hu, "dicke": s,
                          "bemerkung": f"{ny} Reihen, zwischen den Querstützen eingesetzt"})
        res["podest"] = {"hoehe": H, "deck": (db, dh), "unterbau": (ub, uh), "n_quer": nx, "n_laengs": ny, "hu": hu, "s": s, "D": D}
        hinweise.append("Das Podest hat keinen Boden. Das Modell liegt auf der Deckplatte (im Rahmen, falls gewählt).")
    return res


def schreiben(ordner, name, res, log=print):
    """Zuschnittliste (.txt, .csv) und Zeichnung (.pdf) -> Liste der Dateien"""
    if not res["teile"]:
        return []
    os.makedirs(ordner, exist_ok=True)
    out = []
    fz = lambda v: ("%.1f" % v).replace(".", ",")
    zeilen = [f"HOLZ: RAHMENLEISTEN UND PODEST – {name}", "=" * 60,
              "Zuschnittliste (Maße in mm; Länge × Breite × Dicke). Holzart und Sägezugabe selbst festlegen.", ""]
    zeilen.append(f"{'Pos':<4} {'Teil':<28} {'Stk':>3}  {'Länge':>8} {'Breite':>8} {'Dicke':>7}  Bemerkung")
    for t in res["teile"]:
        zeilen.append(f"{t['pos']:<4} {t['name']:<28} {t['stueck']:>3}  {fz(t['laenge']):>8} {fz(t['breite']):>8} {fz(t['dicke']):>7}  {t['bemerkung']}")
    vol = sum(t["stueck"] * t["laenge"] * t["breite"] * t["dicke"] for t in res["teile"]) / 1e6
    zeilen += ["", f"Holzvolumen gesamt ca. {fz(vol)} dm³ (ohne Verschnitt)"]
    for h in res["hinweise"]:
        zeilen.append("Hinweis: " + h)
    zeilen.append("Maße sind Rechenwerte ohne Sägezugabe und noch nicht am gebauten Modell geprüft.")
    p = os.path.join(ordner, f"{name}_holz_zuschnitt.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(zeilen) + "\n")
    out.append(p)
    p = os.path.join(ordner, f"{name}_holz_zuschnitt.csv")
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Pos", "Teil", "Stück", "Länge mm", "Breite mm", "Dicke mm", "Bemerkung"])
        for t in res["teile"]:
            w.writerow([t["pos"], t["name"], t["stueck"], fz(t["laenge"]), fz(t["breite"]), fz(t["dicke"]), t["bemerkung"]])
    out.append(p)
    try:
        out.append(_zeichnung(os.path.join(ordner, f"{name}_holz_zeichnung.pdf"), name, res))
    except Exception as e:
        log(f"  Hinweis: Holz-Zeichnung nicht erzeugt ({e})")
    log(f"  Holz: {sum(t['stueck'] for t in res['teile'])} Zuschnitte, Zuschnittliste und Zeichnung in {ordner}")
    return out


def _zeichnung(pfad, name, res):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.69, 8.27))
    pod, rah = res.get("podest"), res.get("rahmen")
    if pod:
        db, dh = pod["deck"]
    elif rah:
        db, dh = rah["aussen"]
    else:
        db = dh = 0
    # Draufsicht
    a1.set_title("Draufsicht (mm)", fontsize=9)
    if pod:
        a1.add_patch(Rectangle((0, 0), db, dh, fill=False, ec="#a0522d", lw=1.2))
        ub, uh = pod["unterbau"]
        ox, oy = (db - ub) / 2, (dh - uh) / 2
        s = pod["s"]
        a1.add_patch(Rectangle((ox, oy), ub, uh, fill=False, ec="#a0522d", lw=0.8, ls="--"))
        a1.add_patch(Rectangle((ox + s, oy + s), ub - 2 * s, uh - 2 * s, fill=False, ec="#a0522d", lw=0.5, ls="--"))
        n = pod["n_quer"]
        for i in range(1, n + 1):
            x = ox + s + i * (ub - 2 * s) / (n + 1)
            a1.plot([x, x], [oy + s, oy + uh - s], color="#a0522d", lw=0.6, ls="--")
        m = pod["n_laengs"]
        for j in range(1, m + 1):
            y = oy + s + j * (uh - 2 * s) / (m + 1)
            a1.plot([ox + s, ox + ub - s], [y, y], color="#a0522d", lw=0.6, ls="--")
    if rah:
        ab, ah = rah["aussen"]
        ib, ih = rah["innen"]
        cx, cy = db / 2, dh / 2
        a1.add_patch(Rectangle((cx - ab / 2, cy - ah / 2), ab, ah, fill=False, ec="#444", lw=1.0))
        a1.add_patch(Rectangle((cx - ib / 2, cy - ih / 2), ib, ih, fill=False, ec="#c00", lw=0.8))
        a1.text(cx, cy, "Modell", ha="center", va="center", fontsize=9, color="#c00")
    a1.set_aspect("equal")
    a1.autoscale()
    a1.invert_yaxis()
    # Schnitt (Seitenansicht)
    a2.set_title("Schnitt längs (mm)", fontsize=9)
    if pod:
        H, D, hu = pod["hoehe"], pod["D"], pod["hu"]
        a2.add_patch(Rectangle((0, hu), db, D, fc="#e8d3b0", ec="#a0522d"))
        ub = pod["unterbau"][0]
        ox, s = (db - ub) / 2, pod["s"]
        a2.add_patch(Rectangle((ox, 0), s, hu, fc="#e8d3b0", ec="#a0522d"))
        a2.add_patch(Rectangle((ox + ub - s, 0), s, hu, fc="#e8d3b0", ec="#a0522d"))
        n = pod["n_quer"]
        for i in range(1, n + 1):
            x = ox + s + i * (ub - 2 * s) / (n + 1) - s / 2
            a2.add_patch(Rectangle((x, 0), s, hu, fc="#f3e6cc", ec="#a0522d", lw=0.6))
        top = H
    else:
        top = 0
    if rah:
        bl, hl = rah["leiste"]
        ab = rah["aussen"][0]
        x0 = (db - ab) / 2
        a2.add_patch(Rectangle((x0, top), bl, hl, fc="#d8c9a8", ec="#444"))
        a2.add_patch(Rectangle((x0 + ab - bl, top), bl, hl, fc="#d8c9a8", ec="#444"))
        a2.text(db / 2, top + hl / 2, "Modell", ha="center", va="center", fontsize=9, color="#c00")
    a2.set_aspect("equal")
    a2.autoscale()
    fig.suptitle(f"{name} – Holz: Rahmenleisten und Podest (ungetestet, ohne Sägezugabe)", fontsize=10)
    fig.savefig(pfad, format="pdf")
    plt.close(fig)
    return pfad
