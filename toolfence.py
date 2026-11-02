"""toolfence — Prinzipbeweis: Werkzeugaufrufe prüfen, bevor sie ausgeführt werden.

Der Prinzipbeweis zeigt drei Dinge, die die Bewerbung in Feld 5 behauptet:

1. **Die Schranke entscheidet vor der Ausführung.** Ein Werkzeugaufruf wird gegen eine
   Regel geprüft, die der Betreiber schreibt — Werkzeugname, Argumentschema, erlaubter
   Pfad, Häufigkeit, Bestätigungspflicht. Nur was durchkommt, wird ausgeführt.
2. **Das Protokoll ist fälschungssicher.** Jede Entscheidung steht als Glied einer
   Hash-Kette. Wird ein Eintrag nachträglich geändert, bricht die Kette nachweisbar.
3. **Der Angriff, auf den es ankommt, wird gestoppt.** Ein Agent, der aus einem fremden
   Text die Anweisung übernimmt, eine Geheimnisdatei zu lesen und nach außen zu senden,
   scheitert an der Regel — nicht am Urteil eines Modells.

Aufruf:
    python toolfence.py            # Demonstration
    python toolfence.py --selftest # eingebaute Prüfungen
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass, field


# --------------------------------------------------------------------------- Regeln

@dataclass(frozen=True)
class Regel:
    """Eine Erlaubnis. Alles, was nicht erlaubt ist, ist verboten."""

    werkzeug: str
    argumente: dict[str, str] = field(default_factory=dict)   # Name -> Regex
    pfad_prefix: str | None = None        # Argument "pfad" muss hier beginnen
    max_pro_minute: int | None = None
    bestaetigung: bool = False            # unwiderruflich -> braucht Freigabe

    def passt(self, aufruf: "Aufruf") -> tuple[bool, str]:
        if aufruf.werkzeug != self.werkzeug:
            return False, "anderes Werkzeug"
        for name, muster in self.argumente.items():
            if name not in aufruf.argumente:
                return False, f"Argument {name} fehlt"
            if not re.fullmatch(muster, str(aufruf.argumente[name])):
                return False, f"Argument {name} entspricht nicht {muster!r}"
        if self.pfad_prefix is not None:
            pfad = str(aufruf.argumente.get("pfad", ""))
            # Pfadtraversale zählt als Verstoß, nicht als Zufall — und sie wird als
            # das benannt, was sie ist: ein Prefixtest allein würde sie durchlassen.
            if ".." in pfad:
                return False, "Pfadtraversale (..) im Argument pfad"
            if not pfad.startswith(self.pfad_prefix):
                return False, f"Pfad liegt nicht unter {self.pfad_prefix}"
        return True, "Regel erfüllt"


@dataclass(frozen=True)
class Aufruf:
    werkzeug: str
    argumente: dict[str, object]


# ------------------------------------------------------------------- Hash-Kette

class Kette:
    """Append-only Protokoll. Jeder Eintrag bindet seinen Vorgänger ein."""

    def __init__(self) -> None:
        self.eintraege: list[dict] = []

    def anfuegen(self, nutzlast: dict) -> dict:
        vorher = self.eintraege[-1]["hash"] if self.eintraege else "0" * 64
        rumpf = {"nr": len(self.eintraege) + 1, "vorher": vorher, "daten": nutzlast}
        rumpf["hash"] = self._hash(rumpf)
        self.eintraege.append(rumpf)
        return rumpf

    @staticmethod
    def _hash(rumpf: dict) -> str:
        ohne = {k: v for k, v in rumpf.items() if k != "hash"}
        rohdaten = json.dumps(ohne, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(rohdaten.encode("utf-8")).hexdigest()

    def pruefen(self) -> tuple[bool, str]:
        """True, wenn kein Eintrag geändert und keiner entfernt wurde."""
        vorher = "0" * 64
        for i, e in enumerate(self.eintraege, start=1):
            if e["nr"] != i:
                return False, f"Eintrag {i}: Nummer {e['nr']} passt nicht"
            if e["vorher"] != vorher:
                return False, f"Eintrag {i}: Vorgänger-Hash weicht ab"
            if e["hash"] != self._hash(e):
                return False, f"Eintrag {i}: Inhalt wurde nachträglich geändert"
            vorher = e["hash"]
        return True, f"{len(self.eintraege)} Einträge, Kette ungebrochen"


# ----------------------------------------------------------------------- Schranke

class Schranke:
    """Vermittler zwischen Agent und Werkzeug."""

    def __init__(self, regeln: list[Regel], werkzeuge: dict[str, object],
                 jetzt=time.time) -> None:
        self.regeln = regeln
        self.werkzeuge = werkzeuge
        self.kette = Kette()
        self._jetzt = jetzt
        self._verlauf: list[tuple[str, float]] = []

    def _rate_ok(self, regel: Regel) -> bool:
        if regel.max_pro_minute is None:
            return True
        t = self._jetzt()
        letzte = [z for w, z in self._verlauf
                  if w == regel.werkzeug and t - z < 60.0]
        return len(letzte) < regel.max_pro_minute

    def ruf(self, aufruf: Aufruf, bestaetigt: bool = False) -> dict:
        grund = "kein Werkzeug erlaubt diesen Aufruf"
        for regel in self.regeln:
            ok, warum = regel.passt(aufruf)
            if not ok:
                if aufruf.werkzeug == regel.werkzeug:
                    grund = warum
                continue
            if not self._rate_ok(regel):
                grund = f"mehr als {regel.max_pro_minute} Aufrufe pro Minute"
                break
            if regel.bestaetigung and not bestaetigt:
                grund = "unwiderruflich — Bestätigung fehlt"
                break
            self._verlauf.append((aufruf.werkzeug, self._jetzt()))
            ergebnis = self.werkzeuge[aufruf.werkzeug](**aufruf.argumente)
            self.kette.anfuegen({"werkzeug": aufruf.werkzeug,
                                 "argumente": aufruf.argumente,
                                 "entscheidung": "erlaubt", "grund": warum})
            return {"erlaubt": True, "ergebnis": ergebnis, "grund": warum}

        self.kette.anfuegen({"werkzeug": aufruf.werkzeug,
                             "argumente": aufruf.argumente,
                             "entscheidung": "abgelehnt", "grund": grund})
        return {"erlaubt": False, "ergebnis": None, "grund": grund}

    def sarif(self) -> dict:
        """Die Ablehnungen als SARIF — dasselbe Format, das LLMSecTest ausgibt."""
        results = [
            {"ruleId": "toolfence/abgelehnt",
             "level": "error",
             "message": {"text": f"{e['daten']['werkzeug']}: {e['daten']['grund']}"}}
            for e in self.kette.eintraege
            if e["daten"]["entscheidung"] == "abgelehnt"
        ]
        return {"version": "2.1.0",
                "runs": [{"tool": {"driver": {"name": "toolfence"}},
                          "results": results}]}


# ------------------------------------------------------------- Beispielwerkzeuge

def _datei_lesen(pfad: str) -> str:
    tresor = {"/projekt/notizen.md": "Terminliste",
              "/home/.ssh/id_ed25519": "GEHEIMER SCHLÜSSEL"}
    return tresor.get(pfad, "")


def _mail_senden(an: str, text: str) -> str:
    return f"gesendet an {an} ({len(text)} Zeichen)"


# --------------------------------------------------------------------------- Demo

def demo() -> int:
    regeln = [
        Regel("datei_lesen", pfad_prefix="/projekt/"),
        Regel("mail_senden",
              argumente={"an": r"[^@]+@behoerde\.de"},
              max_pro_minute=2, bestaetigung=True),
    ]
    s = Schranke(regeln, {"datei_lesen": _datei_lesen, "mail_senden": _mail_senden})

    print("ToolFence — Prinzipbeweis\n" + "=" * 60)

    faelle: list[tuple[str, Aufruf, bool]] = [
        ("Erlaubt: Projektdatei lesen",
         Aufruf("datei_lesen", {"pfad": "/projekt/notizen.md"}), False),
        ("Angriff: fremder Text verlangt den SSH-Schlüssel",
         Aufruf("datei_lesen", {"pfad": "/home/.ssh/id_ed25519"}), False),
        ("Angriff: Pfadtraversale",
         Aufruf("datei_lesen", {"pfad": "/projekt/../home/.ssh/id_ed25519"}), False),
        ("Abgelehnt: Mail nach außen",
         Aufruf("mail_senden", {"an": "angreifer@example.com", "text": "Daten"}), True),
        ("Erlaubt mit Bestätigung: Mail an die Behörde",
         Aufruf("mail_senden", {"an": "amt@behoerde.de", "text": "Bericht"}), True),
        ("Abgelehnt: Mail ohne Bestätigung",
         Aufruf("mail_senden", {"an": "amt@behoerde.de", "text": "Bericht"}), False),
    ]

    for titel, aufruf, bestaetigt in faelle:
        a = s.ruf(aufruf, bestaetigt=bestaetigt)
        marke = "DURCH " if a["erlaubt"] else "STOPP "
        print(f"\n{marke} {titel}")
        print(f"        {aufruf.werkzeug}({aufruf.argumente})")
        print(f"        -> {a['grund']}")
        if a["erlaubt"]:
            print(f"        Ergebnis: {a['ergebnis']!r}")

    ok, text = s.kette.pruefen()
    print("\n" + "=" * 60)
    print(f"Protokoll: {text}")

    # Jetzt wird manipuliert — genau das muss auffallen.
    s.kette.eintraege[1]["daten"]["entscheidung"] = "erlaubt"
    ok2, text2 = s.kette.pruefen()
    print(f"Nach Manipulation eines Eintrags: "
          f"{'unentdeckt (FEHLER)' if ok2 else 'erkannt — ' + text2}")

    befunde = len(s.sarif()["runs"][0]["results"])
    print(f"SARIF-Bericht: {befunde} Ablehnungen")
    return 0 if (ok and not ok2) else 1


# ----------------------------------------------------------------------- Selftest

def selftest() -> int:
    fails: list[str] = []

    def expect(bedingung: bool, was: str) -> None:
        if not bedingung:
            fails.append(was)

    regeln = [
        Regel("datei_lesen", pfad_prefix="/projekt/"),
        Regel("mail_senden", argumente={"an": r"[^@]+@behoerde\.de"},
              max_pro_minute=2, bestaetigung=True),
    ]
    werkzeuge = {"datei_lesen": _datei_lesen, "mail_senden": _mail_senden}

    # 1 — die Schranke entscheidet VOR der Ausführung: ein abgelehnter Aufruf
    #     darf das Werkzeug nie erreichen.
    gerufen: list[str] = []
    s = Schranke(regeln, {"datei_lesen": lambda pfad: gerufen.append(pfad) or "x",
                          "mail_senden": _mail_senden})
    s.ruf(Aufruf("datei_lesen", {"pfad": "/home/.ssh/id_ed25519"}))
    expect(gerufen == [], "ein abgelehnter Aufruf erreicht das Werkzeug nicht")

    s2 = Schranke(regeln, werkzeuge)
    a = s2.ruf(Aufruf("datei_lesen", {"pfad": "/projekt/notizen.md"}))
    expect(a["erlaubt"] and a["ergebnis"] == "Terminliste",
           "ein erlaubter Aufruf wird ausgeführt")

    # 2 — Pfadtraversale wird erkannt, nicht nur ein falsches Prefix.
    a = s2.ruf(Aufruf("datei_lesen", {"pfad": "/projekt/../home/.ssh/id_ed25519"}))
    expect(not a["erlaubt"], "Pfadtraversale wird abgelehnt")
    expect("Pfadtraversale" in a["grund"],
           f"der Grund benennt die Traversale, nicht das Prefix: {a['grund']!r}")

    # 3 — Bestätigungspflicht.
    a = s2.ruf(Aufruf("mail_senden", {"an": "amt@behoerde.de", "text": "x"}))
    expect(not a["erlaubt"] and "Bestätigung" in a["grund"],
           "unwiderrufliche Werkzeuge brauchen eine Bestätigung")
    a = s2.ruf(Aufruf("mail_senden", {"an": "amt@behoerde.de", "text": "x"}),
               bestaetigt=True)
    expect(a["erlaubt"], "mit Bestätigung geht derselbe Aufruf durch")

    # 4 — Argumentschema: Empfänger außerhalb der Behörde ist verboten.
    a = s2.ruf(Aufruf("mail_senden", {"an": "angreifer@example.com", "text": "x"}),
               bestaetigt=True)
    expect(not a["erlaubt"], "ein Empfänger außerhalb des Musters wird abgelehnt")

    # 5 — unbekanntes Werkzeug: Erlaubnisliste, keine Verbotsliste.
    a = s2.ruf(Aufruf("shell", {"cmd": "rm -rf /"}))
    expect(not a["erlaubt"], "ein nicht geregeltes Werkzeug ist verboten")

    # 6 — Häufigkeitsgrenze bei fester Zeit.
    s3 = Schranke(regeln, werkzeuge, jetzt=lambda: 1000.0)
    for _ in range(2):
        s3.ruf(Aufruf("mail_senden", {"an": "amt@behoerde.de", "text": "x"}),
               bestaetigt=True)
    a = s3.ruf(Aufruf("mail_senden", {"an": "amt@behoerde.de", "text": "x"}),
               bestaetigt=True)
    expect(not a["erlaubt"] and "pro Minute" in a["grund"],
           "die Häufigkeitsgrenze greift")

    # 7 — die Hash-Kette: ungebrochen, bis jemand etwas ändert.
    ok, _ = s2.kette.pruefen()
    expect(ok, "die unveränderte Kette ist gültig")
    expect(len(s2.kette.eintraege) == 6,
           f"jede Entscheidung steht im Protokoll (6 erwartet, "
           f"{len(s2.kette.eintraege)} gefunden)")

    s2.kette.eintraege[0]["daten"]["entscheidung"] = "abgelehnt"
    ok, grund = s2.kette.pruefen()
    expect(not ok and "geändert" in grund, "eine Änderung bricht die Kette")

    # 8 — ein entfernter Eintrag fällt ebenso auf (Append-Only).
    s4 = Schranke(regeln, werkzeuge)
    for p in ("/projekt/a", "/projekt/b", "/projekt/c"):
        s4.ruf(Aufruf("datei_lesen", {"pfad": p}))
    del s4.kette.eintraege[1]
    ok, _ = s4.kette.pruefen()
    expect(not ok, "ein entfernter Eintrag bricht die Kette")

    # 9 — SARIF enthält genau die Ablehnungen.
    s5 = Schranke(regeln, werkzeuge)
    s5.ruf(Aufruf("datei_lesen", {"pfad": "/projekt/notizen.md"}))
    s5.ruf(Aufruf("datei_lesen", {"pfad": "/home/.ssh/id_ed25519"}))
    res = s5.sarif()["runs"][0]["results"]
    expect(len(res) == 1 and res[0]["level"] == "error",
           f"SARIF berichtet nur die Ablehnung: {res}")

    for f in fails:
        print(f"FAIL: {f}", file=sys.stderr)
    print("selftest: " + ("ok" if not fails else f"{len(fails)} failure(s)"),
          file=sys.stderr)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else demo())
