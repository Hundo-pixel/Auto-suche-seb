"""Regelbasierte Textanalyse: Normalisierung, Reifen, Kennzeichen, Warn-Schlagworte.

Alles bewusst ohne KI-API: reguläre Ausdrücke mit einfacher Negationserkennung
("kein Export", "ohne Motorschaden" werden NICHT als Warnung gewertet).
"""
from __future__ import annotations

import re
import unicodedata
from html import unescape

from .models import ACCIDENT_FREE, ACCIDENT_UNKNOWN, ACCIDENT_YES

# ------------------------------------------------------------------ Basics

def strip_html(html: str) -> str:
    if not html:
        return ""
    t = re.sub(r"<br\s*/?>|</p>|</li>|<hr\s*/?>", "\n", html, flags=re.I)
    t = re.sub(r"<li[^>]*>", "• ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = unescape(t)
    t = re.sub(r"[ \t ]+", " ", t)
    t = re.sub(r"\n\s*\n\s*\n+", "\n\n", t)
    return t.strip()


def parse_int(s) -> int | None:
    """'174.917 km' -> 174917, '€ 5.990' -> 5990, '1.234 € VB' -> 1234."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return int(s)
    digits = re.sub(r"[^\d]", "", str(s))
    return int(digits) if digits else None


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return s


MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12,
}


def parse_first_registration(s: str | None) -> str | None:
    """'09/2012', '2012-09-01', 'Januar 2009', 'EZ 02/2005', '2009' -> 'YYYY-MM'."""
    if not s:
        return None
    s = str(s).strip().lower()
    m = re.search(r"(\d{4})-(\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.search(r"(\d{1,2})\s*[/.]\s*(\d{4})", s)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    for name, num in MONTHS.items():
        m = re.search(name + r"\s+(\d{4})", s)
        if m:
            return f"{m.group(1)}-{num:02d}"
    m = re.search(r"\b(19[5-9]\d|20[0-4]\d)\b", s)
    if m:
        return f"{m.group(1)}-01"
    return None


def normalize_fuel(s: str | None) -> str:
    if not s:
        return ""
    t = s.lower()
    if "hybrid" in t or "elektro/" in t or "/elektro" in t or "plug-in" in t:
        return "Hybrid"
    if "elektro" in t or t in ("e", "electric", "ev"):
        return "Elektro"
    if "diesel" in t:
        return "Diesel"
    if "lpg" in t or "autogas" in t:
        return "LPG"
    if "cng" in t or "erdgas" in t:
        return "CNG"
    if "wasserstoff" in t or "hydrogen" in t:
        return "Wasserstoff"
    if "benzin" in t or "super" in t or "petrol" in t or "gasoline" in t:
        return "Benzin"
    return "Sonstige"


def normalize_gearbox(s: str | None) -> str:
    if not s:
        return ""
    t = s.lower()
    if "halbautomat" in t or "semi" in t:
        return "Halbautomatik"
    if "automat" in t or t in ("a", "automatic"):
        return "Automatik"
    if "schalt" in t or "manuell" in t or t in ("m", "manual"):
        return "Schaltgetriebe"
    return ""


def parse_power(s: str | None) -> tuple[int | None, int | None]:
    """'105 kW (143 PS)' -> (105, 143); '75 PS' -> (55, 75)."""
    if not s:
        return None, None
    kw = re.search(r"(\d+)\s*kw", s, re.I)
    ps = re.search(r"(\d+)\s*ps", s, re.I)
    kwv = int(kw.group(1)) if kw else None
    psv = int(ps.group(1)) if ps else None
    if kwv and not psv:
        psv = round(kwv * 1.35962)
    if psv and not kwv:
        kwv = round(psv / 1.35962)
    return kwv, psv


def model_key(make: str, model: str, model_group: str = "") -> str:
    """Vereinheitlicht Modellnamen über Portale hinweg ("3er Reihe" ~ "3er", "C-Klasse" ~ "C Klasse")."""
    m = (model_group or model or "").lower()
    m = unicodedata.normalize("NFKD", m).encode("ascii", "ignore").decode()
    m = re.sub(r"\b(reihe|serie|series|klasse|class|modell)\b", "", m)
    m = re.sub(r"[^a-z0-9]+", "", m)
    # Sammelbegriffe sind keine vergleichbaren Modelle
    if m in ("sonstige", "andere", "weitere", "others", "other", "diverse"):
        return ""
    return m


def make_key(make: str) -> str:
    k = slugify(make or "")
    aliases = {"vw": "volkswagen", "mercedes": "mercedes-benz", "mercedes-amg": "mercedes-benz",
               "citroen": "citroen", "skoda": "skoda", "mini": "mini"}
    return aliases.get(k, k)


# ------------------------------------------------------------------ Negation

NEGATION = re.compile(r"\b(kein|keine|keinen|keiner|ohne|nicht|nie|frei von|no)\b[\w\s,./-]{0,25}$", re.I)


def _negated(text: str, start: int) -> bool:
    window = text[max(0, start - 30):start]
    return bool(NEGATION.search(window))


def find_terms(text: str, patterns: list[tuple[str, str]], allow_negation_check: bool = True) -> list[tuple[str, str]]:
    """Gibt (label, Fundstelle) für jedes nicht verneinte Muster zurück."""
    hits = []
    for label, pat in patterns:
        for m in re.finditer(pat, text, re.I):
            if allow_negation_check and _negated(text, m.start()):
                continue
            snippet = text[max(0, m.start() - 25): m.end() + 25].replace("\n", " ").strip()
            hits.append((label, snippet))
            break
    return hits


# ------------------------------------------------------------------ Kennzeichen

PLATE_PATTERNS = [
    ("Kurzzeitkennzeichen", r"kurzzeit[\s-]*(kennzeichen|zulassung|nummer)|\bkurzzeitkennz"),
    ("Ausfuhrkennzeichen", r"ausfuhr[\s-]*(kennzeichen|zulassung)|zollkennzeichen|export[\s-]*kennzeichen"),
    ("Rotes Kennzeichen", r"rote[sn]?\s+(kennzeichen|nummer)|\b07er[\s-]*kennzeichen|\b06er[\s-]*kennzeichen"),
    ("Händlerkennzeichen", r"händler[\s-]*kennzeichen|haendlerkennzeichen|überführungskennzeichen"),
    ("Auslandszulassung", r"ausl(and|ändisch)\w*[\s-]*(zulassung|zugelassen|kennzeichen|papiere|brief)|"
                          r"(zulassung|zugelassen|papiere)\s+(in|aus)\s+(polen|litauen|rumänien|bulgarien|tschechien|"
                          r"niederlande|holland|belgien|frankreich|italien|spanien|österreich|schweiz|dänemark|ukraine)|"
                          r"\b(pl|lt|ro|bg|nl|cz)[\s-]*(papiere|zulassung|kennzeichen)\b"),
]


def plate_hints(text: str) -> list[dict]:
    return [{"type": label, "evidence": snip} for label, snip in find_terms(text, PLATE_PATTERNS)]


# ------------------------------------------------------------------ Warn-Schlagworte

KEYWORD_PATTERNS = [
    ("Export", r"\bexport\b|nur\s+für\s+(den\s+)?export|export\s*preis|für\s+export"),
    ("Defekt", r"\bdefekt\w*"),
    ("Motorschaden", r"motor\s*schaden|motorproblem|motor\s+(defekt|kaputt|klopft)"),
    ("Getriebeschaden", r"getriebe\s*schaden|getriebe\s+(defekt|kaputt)"),
    ("Bastlerfahrzeug", r"\bbastler\w*|für\s+bastler|schlachtfest|teileträger|ersatzteilspender"),
    ("Nicht fahrbereit", r"nicht\s+fahrbereit|nicht\s+fahrtüchtig|springt\s+nicht\s+an"),
    ("Ohne TÜV", r"ohne\s+t[üu]e?v|kein\s+t[üu]e?v|t[üu]e?v\s+abgelaufen"),
    ("Wasserschaden", r"wasser\s*schaden|hochwasser\s*fahrzeug|flutschaden"),
]

# Diese Muster sind selbst schon "negativ" formuliert -> keine Negationsprüfung
_SELF_NEGATIVE = {"Nicht fahrbereit", "Ohne TÜV"}


def keyword_warnings(text: str) -> list[dict]:
    out = []
    for label, pat in KEYWORD_PATTERNS:
        hits = find_terms(text, [(label, pat)], allow_negation_check=label not in _SELF_NEGATIVE)
        out += [{"type": label, "evidence": snip} for _, snip in hits]
    return out


# ------------------------------------------------------------------ Unfall aus Text

ACCIDENT_YES_PAT = [("Unfall", r"unfallwagen|unfallfahrzeug|unfallschaden|hatte\s+(einen\s+)?unfall|"
                               r"(front|heck|seiten)schaden|beschädigtes\s+fahrzeug|\bunfall\b")]
ACCIDENT_FREE_PAT = r"unfallfrei|unfall\s*:?\s*(nein|keine?)\b|keine?n?\s+unfall|nie\s+einen\s+unfall|ohne\s+unfall|unbeschädigtes\s+fahrzeug"


def accident_from_text(text: str) -> str:
    t = text or ""
    if re.search(ACCIDENT_FREE_PAT, t, re.I):
        # "unfallfrei" gewinnt nur, wenn kein eindeutiger Unfallhinweis daneben steht
        if not find_terms(re.sub(ACCIDENT_FREE_PAT, "", t, flags=re.I), ACCIDENT_YES_PAT):
            return ACCIDENT_FREE
    if find_terms(t, ACCIDENT_YES_PAT):
        return ACCIDENT_YES
    return ACCIDENT_UNKNOWN


# ------------------------------------------------------------------ Reifen

def tyre_info(text: str) -> dict:
    """Erkennt Reifensätze aus Freitext.

    Rückgabe: {"sets": int|None, "labels": [...], "evidence": str}
      sets = Anzahl erkannter Reifensätze (1 = nur ein Satz, 2 = z. B. Sommer+Winter)
    """
    t = (text or "").lower()
    labels: list[str] = []
    evidence = []

    def has(pat: str) -> re.Match | None:
        m = re.search(pat, t, re.I)
        if m and not _negated(t, m.start()):
            evidence.append(t[max(0, m.start() - 20): m.end() + 20].replace("\n", " ").strip())
            return m
        return None

    sep = r"\s*-?\s*(und|\+|&|/|,|-)\s*"
    both = has(r"sommer" + sep + r"winter(reifen|räder|kompletträder)?|"
               r"winter" + sep + r"sommer(reifen|räder)?|"
               r"(2|zwei|beide)\s*(reifen)?sätze|8[\s-]*fach\s+bereift|8\s*reifen|"
               r"zusätzlich\w*\s+(eine?n?\s+)?(satz\s+)?(winter|sommer)(reifen|räder)|"
               r"(winter|sommer)(reifen|räder|kompletträder)\s+(auf\s+felgen\s+)?(sind\s+)?(dabei|inklusive|inkl|anbei|vorhanden)")
    summer = has(r"sommer(reifen|räder|kompletträder|\s*-\s*(und|/|&)\s*winter)")
    winter = has(r"winter(reifen|räder|kompletträder|\s*-\s*(und|/|&)\s*sommer)|m\+s")
    allseason = has(r"ganzjahres?(reifen|räder)?|allwetter(reifen)?|all[\s-]?season")
    complete = has(r"komplett(rad)?(satz|räder)|kompletträder|auf\s+(alu)?felgen")

    if summer:
        labels.append("Sommer")
    if winter:
        labels.append("Winter")
    if allseason:
        labels.append("Ganzjahr")
    if complete:
        labels.append("Kompletträder")

    sets = None
    if both or (summer and winter):
        sets = 2
    elif summer or winter or allseason:
        sets = 1
    if re.search(r"(3|drei)\s*(reifen)?sätze", t):
        sets = 3
    return {"sets": sets, "labels": labels, "evidence": evidence[0] if evidence else ""}
