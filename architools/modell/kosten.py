"""Zuschnitt- und Kostenliste als Text – wird erst geschrieben, wenn alles berechnet ist.

Alle Preise, Zeiten und die Plattenzahl sind SCHÄTZUNGEN (Richtwerte, siehe bibliothek.PREISE).
"""
import math

from . import blatt as BL
from . import bibliothek as BIB

HINWEIS = ("ACHTUNG – nur geschätzt: Preise, Laserzeit und Plattenzahl sind grobe Richtwerte und keine Kalkulation oder ein Angebot. "
           "Händlerpreise, Verschnitt, tatsächliche Laserzeit (die Werkstatt rechnet sekundengenau nach eigener Zeit ab) und Druckzeit "
           "können deutlich abweichen. Bitte vor dem Kauf Maße und Preise selbst prüfen; eigene Preise lassen sich in der Bibliothek "
           "(~/.architools/bibliothek.json, Schlüssel „preise“) eintragen.")


def _eur(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def _z(v, n=2):
    """Zahl mit Komma als Dezimalzeichen"""
    return f"{v:.{n}f}".replace(".", ",")


def _stueck_je_platte(teil, platte):
    """Wie oft passt ein Zuschnitt (B×H) auf eine Handelsplatte – beide Drehungen, einfache Reihen."""
    (w, h), (W, H) = teil, platte
    return max(int(W // w) * int(H // h), int(W // h) * int(H // w))


def _modus_name(m):
    return {"druck": "3D-Druck", "stapel": "Stapelmodell", "flaeche": "ebene Klebeflächen ohne Laschen",
            "falt": "Faltmodell"}.get(m, str(m))


def text(cfg, stats, platten, platten_e, drucke, platten_g=(), summe=None):
    """-> Text der Liste. summe: dict, das (wenn angegeben) netto, brutto, material, laser (Schätzungen in €) bekommt"""
    pr = BIB.preise()
    L = []
    add = L.append
    add(f"ZUSCHNITT- UND KOSTENLISTE – {cfg.get('projekt_name', 'Projekt')}")
    add("=" * 60)
    add(f"Maßstab 1:{cfg.get('massstab')}, Modellgröße {stats['modell_b']:.0f} × {stats['modell_h']:.0f} mm")
    add("")
    add(HINWEIS)
    add("")
    summe_netto = 0.0
    mat_eur = 0.0
    alle_pl = list(platten) + list(platten_e)
    if alle_pl:
        sorte, st, _ = BIB.material(cfg)
        add("LASERCUT")
        add("-" * 60)
        add(f"Material: {sorte}, {st:g} mm")
        n_form = {}
        rest_pl = [p for p in alle_pl if p.get("rest")]
        for p in alle_pl:
            if p.get("rest"):
                continue
            n_form[tuple(p["format"])] = n_form.get(tuple(p["format"]), 0) + 1
        for (w, h), c in n_form.items():
            add(f"Zuschnitte für den Laser: {c} × {w:.0f} × {h:.0f} mm  (davon Gelände {len(platten) - len(rest_pl)}, Einsatz {len(platten_e)})")
        for p in rest_pl:
            add(f"Restplatte „{p['rest']}“ ({p['format'][0]:.0f} × {p['format'][1]:.0f} mm): vorhanden, wird belegt – kein Kauf nötig")
        if stats.get("gebaeude_modus", "druck") != "druck" and not platten_g:
            add(f"Gebäude als Laserteile ({_modus_name(stats['gebaeude_modus'])}): {stats.get('n_geb_teile', 0)} Teile liegen auf diesen Platten")
        flaeche_m2 = sum(w * h * c for (w, h), c in n_form.items()) / 1e6
        add(f"Plattenfläche gesamt: {_z(flaeche_m2)} m²  (reine Teilefläche {_z(stats['teile_flaeche'] / 1e6, 3)} m²)")
        hp = pr["handelsplatte_mm"]
        je = min((_stueck_je_platte((w, h), hp) for (w, h) in n_form) or [0]) if n_form else 0
        if je:
            gesamt = sum(math.ceil(c / _stueck_je_platte((w, h), hp)) for (w, h), c in n_form.items() if _stueck_je_platte((w, h), hp))
            add(f"Handelsplatten {hp[0] / 10:.0f} × {hp[1] / 10:.0f} cm: ca. {gesamt} Stück (zzgl. etwa eine Reserve-Platte; Plattenzahl geschätzt)")
            fl_kauf = gesamt * hp[0] * hp[1] / 1e6
        else:
            add(f"Handelsplatte {hp[0] / 10:.0f} × {hp[1] / 10:.0f} cm: die Zuschnitte sind größer – Plattenzahl bitte mit dem Händler klären")
            fl_kauf = flaeche_m2
        preis_m2 = pr["material_eur_m2_je_mm"].get(sorte)
        if preis_m2 is not None:
            mat_brutto = fl_kauf * preis_m2 * st
            mat_eur = mat_brutto
            add(f"Materialkosten (Schätzung): ca. {_eur(mat_brutto)} brutto  ({_z(preis_m2, 1)} €/m² je mm × {_z(st, 1)} mm × {_z(fl_kauf)} m²)")
            summe_netto += mat_brutto / (1 + BIB.WERKSTATT["mwst"])
        else:
            add(f"Materialkosten: kein Richtwert für „{sorte}“ hinterlegt")
        lz = stats.get("laser")
        if lz:
            add(f"Laserzeit (Schätzung): ca. {lz['s'] / 60:.0f} min (Spanne {lz['s_lo'] / 60:.0f}–{lz['s_hi'] / 60:.0f} min)")
            add(f"Laserkosten (Schätzung): ca. {_eur(lz['netto'])} netto = {_eur(lz['netto'] * (1 + lz['mwst']))} brutto "
                f"({_z(lz['preis_min'])} €/min zzgl. MwSt.)")
            summe_netto += lz["netto"]
            if (cfg.get("raster_bild") or {}).get("aktiv"):
                gz = lz.get("teile", {}).get("gravieren", 0) / 60
                add(f"  darin Gravur/Rastergravur: ca. {gz:.0f} min – Rastergravur ist EXPERIMENTELL; sie kostet nach Fläche, nicht nach Bildinhalt. "
                    "Erst den Teststreifen (100 × 100 mm) lasern lassen und die Werkstatt nach Zeit und Bitmap/Vektor fragen.")
        add("")
        add("Platte | Teile | Belegung | Laserzeit (ca.)")
        for i, p in enumerate(alle_pl, 1):
            W, H = p["format"]
            belegt = sum(t["poly"].area for t in p["teile"]) / (W * H) * 100
            try:
                zt = BL.laserzeit([p], sorte, st)[0] / 60
            except Exception:
                zt = float("nan")
            name = (("R" + str(p["rest"])[:4]) if p.get("rest") else f"{i:02d}") if i <= len(platten) else f"E{i - len(platten):02d}"
            add(f"{name:>6} | {len(p['teile']):>5} | {belegt:>6.0f} % | {_z(zt, 1):>6} min")
        add("")
    if platten_g:
        add("LASERCUT – GEBÄUDE (anderes Material)")
        add("-" * 60)
        sg = stats.get("gebaeude_material", "")
        add(f"Material: {sg}, Gebäude als {_modus_name(stats.get('gebaeude_modus'))}: {stats.get('n_geb_teile', 0)} Teile")
        ng = {}
        for p in platten_g:
            ng[tuple(p["format"])] = ng.get(tuple(p["format"]), 0) + 1
        for (w, h), c in ng.items():
            add(f"Zuschnitte für den Laser: {c} × {w:.0f} × {h:.0f} mm")
        sorte_g = (cfg["gebaeude"].get("material") or "")
        st_g = float(cfg["gebaeude"].get("staerke_mm") or 0) or None
        pm2 = pr["material_eur_m2_je_mm"].get(sorte_g)
        if pm2 is not None and st_g:
            hp = pr["handelsplatte_mm"]
            fl = sum(w * h * c for (w, h), c in ng.items()) / 1e6
            add(f"Materialkosten (Schätzung): ca. {_eur(fl * pm2 * st_g)} brutto (nur Plattenfläche, ohne Verschnitt zur Handelsplatte)")
            summe_netto += fl * pm2 * st_g / (1 + BIB.WERKSTATT["mwst"])
        add("")
    if stats.get("gebaeude_modus", "druck") == "druck" and (drucke or stats.get("n_druck")):
        add("3D-DRUCK")
        add("-" * 60)
        add(f"Gebäude gedruckt: {stats['n_druck']}, Druckplatten: {stats['n_druckplatten']} ({cfg['druck'].get('geraet', '')}, "
            f"{cfg['druck'].get('filament', 'PLA')})")
        g = stats["filament_g"]
        add(f"Filament (Schätzung): ca. {g:.0f} g")
        fk = g / 1000.0 * pr["filament_eur_kg"]
        add(f"Filamentkosten (Schätzung): ca. {_eur(fk)} brutto  ({_z(pr['filament_eur_kg'], 0)} €/kg)")
        summe_netto += fk / (1 + BIB.WERKSTATT["mwst"])
        add("")
    if stats.get("holz"):
        add("HOLZ (Rahmenleisten / Podest)")
        add("-" * 60)
        add("Zuschnittliste und Zeichnung liegen im Ordner „holz“. Holz wird nicht gelasert; Holzpreise sind hier nicht eingerechnet.")
        add("")
    add("SUMME (Schätzung)")
    add("-" * 60)
    mw = BIB.WERKSTATT["mwst"]
    add(f"ca. {_eur(summe_netto)} netto, {_eur(summe_netto * (1 + mw))} brutto ({mw * 100:.0f} % MwSt.)")
    if summe is not None:
        lz_ = stats.get("laser")
        summe.update(netto=summe_netto, brutto=summe_netto * (1 + mw), material=mat_eur,
                     laser=(lz_["netto"] * (1 + lz_["mwst"]) if lz_ else 0.0))
    add("")
    add(HINWEIS)
    return "\n".join(L) + "\n"


def schreiben(pfad, cfg, stats, platten, platten_e, drucke, platten_g=(), summe=None):
    t = text(cfg, stats, platten, platten_e, drucke, platten_g, summe)
    with open(pfad, "w", encoding="utf-8") as f:
        f.write(t)
    return t
