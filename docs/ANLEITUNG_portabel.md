# Chris ArchItools (portable Version)

Kein Python und keine Installation nötig. Oben liegen nur der Starter und diese Anleitung; alles Technische steckt im Ordner **programm** (bitte nichts darin verschieben).

## Starten
<!--WINDOWS-->
1. ZIP entpacken (an einen Ort mit viel Platz, z. B. `C:\ArchItools`; nicht in einen Ordner mit Leerzeichen und Umlauten mit Schreibschutz).
2. Doppelklick auf **@START@**. Es öffnet sich das Programmfenster.
3. Falls Windows warnt („Der Computer wurde durch Windows geschützt“): „Weitere Informationen“ → „Trotzdem ausführen“.
4. Beim ersten Start gibt das Programm sich selbst für Windows frei (ca. 30 Sekunden, einmalig).
5. Öffnet sich das Programmfenster nicht, startet das Programm automatisch im Browser. Zusätzlich im Ordner **programm**: **Im Browser starten.bat** und **Mit Fehlerfenster starten.bat** (zeigt Fehlermeldungen).
<!--MAC-->
1. ZIP entpacken (Doppelklick).
2. Rechtsklick auf **@START@** → „Öffnen“ → „Öffnen“ (nur beim ersten Mal; macOS prüft unsignierte Programme). Sperrt macOS weiter, im Terminal:
   `xattr -dr com.apple.quarantine <Ordner>`
3. Es öffnet sich das Programmfenster.
<!--ENDE-->

## Updates
Eine Datei **ChrisArchItools_Update_…zip** in den Ordner **programm/updates** legen und das Programm starten (oder Werkzeuge → Einstellungen → Programm-Update). Projekte und Einstellungen bleiben unberührt.

Bei bestehender Internetverbindung zeigt das Programm in der Kopfleiste **Update: Stand N**, sobald auf GitHub ein neueres Paket liegt (abschaltbar unter Werkzeuge → Einstellungen → Programm-Update). Es wird nichts automatisch installiert: Download-Seite öffnen, das Paket laden, entpacken, starten.

## Wenn etwas nicht klappt
Nach jedem Lauf liegt die Datei **bericht.txt** im Ausgabeordner. Einfach weitergeben.

Alles Weitere (Bedienung, Ausgaben, Formate): siehe programm/ENTSCHEIDUNGEN.md und die Hinweise im Programm.
