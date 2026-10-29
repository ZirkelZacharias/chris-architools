"""Plausibilitäts-Prüfer: sucht in den geladenen Umgebungsdaten nach Ausreißern bei Gebäudehöhen, Dachformen, Grundrissen und Gelände.

Er ändert nichts – er meldet nur, was man sich vor der Abgabe ansehen sollte (z. B. eine Kuppel oder ein Rundlokschuppen mit sehr vielen
Dachflächen, ein Gebäude mit 400 m Höhe, eine Geländespitze von 80 m in der Ebene). Das Ergebnis steht im Bericht (Abschnitt 6) und im Protokoll.
"""
import numpy as np

MAX_ZEILEN = 25


def _flaeche(ring):
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def _gebaeude(t):
    """-> dict mit Kennung, Höhe, Grundfläche, Dachflächen, Dachhub, Bodenhöhe, Mitte; None bei unbrauchbaren Daten."""
    try:
        gr = [np.asarray(e, float) for e, _ in (t.get("ground") or [])]
        if not gr:
            return None
        ring = gr[0]
        roof = [np.asarray(e, float) for e, _ in (t.get("roof") or [])]
        zr = np.concatenate([r[:, 2] for r in roof]) if roof else np.array([])
        zg = float(ring[:, 2].min())
        return {"id": str(t.get("gebaeude") or t.get("id") or "?"), "h": float(t.get("h") or 0.0), "flaeche": _flaeche(ring),
                "n_dach": len(roof), "dachhub": float(zr.max() - zr.min()) if len(zr) else 0.0, "zg": zg,
                "mitte": (float(ring[:, 0].mean()), float(ring[:, 1].mean())),
                "ausdehnung": float(max(np.ptp(ring[:, 0]), np.ptp(ring[:, 1]))), "quelle": str(t.get("quelle") or ""),
                "ring": ring}
    except Exception:
        return None


def pruefen(d, log=None):
    """-> Liste von Zeilen (Text). Leer = nichts Auffälliges."""
    out = []

    def melde(text):
        out.append(text)

    geb = [g for g in (_gebaeude(t) for t in list(d.near) + list(d.far)) if g]
    if geb:
        hs = np.array([g["h"] for g in geb])
        med = float(np.median(hs))
        mad = float(np.median(np.abs(hs - med))) or 1.0
        # 1 Gebäudehöhen
        hoch = [g for g in geb if g["h"] > 120 or (g["h"] > med + 8 * mad and g["h"] > 45)]
        for g in sorted(hoch, key=lambda g: -g["h"])[:6]:
            melde(f"Gebäudehöhe: {g['id']} ist {g['h']:.0f} m hoch (Mittel der Umgebung {med:.0f} m) – Turm, Hochhaus oder Datenfehler? ({g['quelle']})")
        niedrig = [g for g in geb if g["h"] < 2.0 and g["flaeche"] > 15]
        if niedrig:
            melde(f"Gebäudehöhe: {len(niedrig)} Gebäude sind niedriger als 2 m (z. B. {niedrig[0]['id']}: {niedrig[0]['h']:.1f} m) – Höhe fehlt oder ist falsch?")
        # 2 Dachformen
        for g in sorted([g for g in geb if g["n_dach"] > 40], key=lambda g: -g["n_dach"])[:5]:
            melde(f"Dachform: {g['id']} hat {g['n_dach']} Dachflächen (kuppel- oder ringförmig, z. B. Rundlokschuppen) – die Form bitte im 3D-Modell prüfen.")
        for g in sorted([g for g in geb if g["ausdehnung"] > 0 and g["dachhub"] > 0.9 * g["ausdehnung"] and g["dachhub"] > 8], key=lambda g: -g["dachhub"])[:4]:
            melde(f"Dachform: {g['id']}: Das Dach steigt {g['dachhub']:.0f} m bei {g['ausdehnung']:.0f} m Ausdehnung – Turmhaube oder falsche Dachhöhe?")
        # 3 Grundrisse
        klein = [g for g in geb if g["flaeche"] < 4.0]
        if klein:
            melde(f"Grundriss: {len(klein)} Gebäude mit weniger als 4 m² (z. B. {klein[0]['id']}) – Splitter, kaum sichtbar im Modell.")
        for g in sorted([g for g in geb if g["flaeche"] > 25000], key=lambda g: -g["flaeche"])[:3]:
            melde(f"Grundriss: {g['id']} hat {g['flaeche']:.0f} m² – sehr großes Gebäude (Halle, Bahnhof?) oder zusammengefasste Daten.")
        # 4 Gebäude gegen Gelände
        try:
            if getattr(d, "px", None) is not None and len(d.px):
                from scipy.spatial import cKDTree
                idx = np.arange(len(d.px))
                if len(idx) > 300000:
                    idx = np.random.default_rng(1).choice(idx, 300000, replace=False)
                baum = cKDTree(np.column_stack([d.px[idx], d.py[idx]]))
                pts = np.array([g["mitte"] for g in geb])
                dist, ii = baum.query(pts, k=1)
                dz = np.array([g["zg"] for g in geb]) - np.asarray(d.pz)[idx][ii]
                schlecht = [(g, z) for g, z, ds in zip(geb, dz, dist) if abs(z) > 4.0 and ds < 15]
                for g, z in sorted(schlecht, key=lambda gz: -abs(gz[1]))[:5]:
                    melde(f"Gelände/Gebäude: {g['id']} steht {z:+.1f} m über bzw. unter dem Gelände (Sockel {g['zg']:.1f} m ü. NHN) – Hang, Einschnitt oder Höhenfehler?")
        except Exception:
            pass

    # 5 Geländeausreißer (Spitzen, Löcher)
    try:
        if getattr(d, "px", None) is not None and len(d.px) > 50:
            from scipy.spatial import cKDTree
            px, py, pz = np.asarray(d.px, float), np.asarray(d.py, float), np.asarray(d.pz, float)
            n = len(px)
            sel = np.arange(n) if n <= 200000 else np.random.default_rng(2).choice(n, 200000, replace=False)
            baum = cKDTree(np.column_stack([px[sel], py[sel]]))
            _, nb = baum.query(np.column_stack([px[sel], py[sel]]), k=9)
            med = np.median(pz[sel][nb[:, 1:]], axis=1)
            ab = pz[sel] - med
            schlimm = np.nonzero(np.abs(ab) > 6.0)[0]
            if len(schlimm):
                j = schlimm[np.argmax(np.abs(ab[schlimm]))]
                melde(f"Gelände: {len(schlimm)} Höhenpunkte weichen mehr als 6 m von ihren Nachbarn ab (größte: {ab[j]:+.0f} m bei Ost {px[sel][j]:.0f}, "
                      f"Nord {py[sel][j]:.0f}) – Messfehler, Brücke oder Bauwerk im Geländemodell?")
            spanne = float(pz.max() - pz.min())
            if spanne > 120:
                melde(f"Gelände: Höhenunterschied im Gebiet {spanne:.0f} m – für ein Stadtgebiet ungewöhnlich, bitte Geländedaten und Gebiet prüfen.")
    except Exception:
        pass

    # 6 Bäume
    try:
        bm = list(d.baeume or [])
        if bm:
            ho = np.array([float(b[3]) for b in bm])
            hoch = int((ho > 45).sum())
            if hoch:
                melde(f"Bäume: {hoch} von {len(bm)} Bäumen sind höher als 45 m (höchster {ho.max():.0f} m) – Baumhöhen aus dem Raster evtl. mit Gebäuden vermischt.")
    except Exception:
        pass

    if len(out) > MAX_ZEILEN:
        rest = len(out) - MAX_ZEILEN
        out = out[:MAX_ZEILEN] + [f"… und {rest} weitere Hinweise"]
    return out
