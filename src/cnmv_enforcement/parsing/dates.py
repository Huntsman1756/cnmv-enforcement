"""Spanish date parsing. Legal dates are ``date`` — never timestamps."""

from __future__ import annotations

import re
from datetime import date

MONTHS_ES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_LONG_RE = re.compile(
    r"(\d{1,2})\s+de\s+(" + "|".join(MONTHS_ES) + r")\s+de\s+(\d{4})",
    re.IGNORECASE,
)
_SLASH_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_COMPACT_RE = re.compile(r"\b(\d{4})(\d{2})(\d{2})\b")


def parse_long_es(text: str) -> date | None:
    """Parse '17 de julio de 2026' (first match)."""
    m = _LONG_RE.search(text)
    if not m:
        return None
    d, month, y = int(m.group(1)), MONTHS_ES[m.group(2).lower()], int(m.group(3))
    try:
        return date(y, month, d)
    except ValueError:
        return None


def parse_slash_es(text: str) -> date | None:
    """Parse '17/07/2026' (dd/mm/yyyy)."""
    m = _SLASH_RE.search(text)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def parse_boe_compact(text: str) -> date | None:
    """Parse BOE metadata '20260803'."""
    m = _COMPACT_RE.match(text.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_any_es(text: str) -> date | None:
    return parse_long_es(text) or parse_slash_es(text) or parse_boe_compact(text)


# ---- conduct-period extraction ------------------------------------------
# Conservative: only unambiguous Spanish date mentions inside the conduct
# clause are collected; conduct_start = earliest, conduct_end = latest.
# Precision is preserved for downstream rule-version resolution.

_MONTH = "|".join(MONTHS_ES)
# 'los días 7 y 13 de diciembre de 2017' / '18, 19, 25 y 26 de octubre de 2017'
# / 'del 14 al 22 de noviembre de 2022' / '1 de julio de 2018'
_DAY_LIST_RE = re.compile(
    rf"(\d{{1,2}}(?:\s*(?:,|y|e|al)\s*\d{{1,2}})*)\s+de\s+({_MONTH})\s+de\s+"
    r"(\d{4})",
    re.IGNORECASE,
)
# cross-month lists: '9 de marzo y 29 de mayo de 2020' / '19 de noviembre
# y 23 de diciembre de 2021' — one shared year at the end
_CROSS_MONTH_RE = re.compile(
    rf"(\d{{1,2}})\s+de\s+({_MONTH})\s*(?:,|y)\s*"
    rf"(?:el\s+)?(?:(\d{{1,2}})\s+de\s+({_MONTH})\s*(?:,|y)\s*(?:el\s+)?)*"
    r"(\d{1,2})\s+de\s+(" + _MONTH + r")\s+de\s+(\d{4})",
    re.IGNORECASE,
)
# day list without 'de' before month: '8 y 9 junio de 2020'
_DAY_NODE_RE = re.compile(
    rf"(\d{{1,2}}(?:\s*(?:,|y|e)\s*\d{{1,2}})*)\s+({_MONTH})\s+de\s+"
    r"(\d{4})",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
# a date is instrument-context when a statute keyword precedes it within the
# same clause (e.g. 'del Reglamento (UE) 596/2014, de 16 de abril de 2014')
_STATUTE_CTX_RE = re.compile(
    r"(?i)(reglamento|ley\b|decreto|directiva|circular|acuerdo|norma\b|"
    r"texto\s+refundido|disposici[oó]n|trlmv|lmv)"
)


def _day(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def extract_conduct_period(
    conduct: str,
) -> tuple[date | None, date | None, str | None]:
    """(start, end, precision) — earliest/latest conduct date observed.

    precision: 'day' | 'year'. Returns (None, None, None) when nothing
    unambiguous is found — absence of dates is itself informative.
    """
    days: list[date] = []
    seen: set[tuple[int, int, int]] = set()
    for m in _DAY_LIST_RE.finditer(conduct):
        window = conduct[max(0, m.start() - 120) : m.start()]
        clause = window.rsplit(".", 1)[-1]
        if _STATUTE_CTX_RE.search(clause):
            continue  # belongs to an instrument title, not the conduct
        month = MONTHS_ES[m.group(2).lower()]
        year = int(m.group(3))
        for dm in re.finditer(r"\d{1,2}", m.group(1)):
            d = _day(year, month, int(dm.group(0)))
            if d and (d.year, d.month, d.day) not in seen:
                seen.add((d.year, d.month, d.day))
                days.append(d)
    # cross-month lists the flat regex can't reach ('9 de marzo y 29 de
    # mayo de 2020')
    for m in _CROSS_MONTH_RE.finditer(conduct):
        window = conduct[max(0, m.start() - 120) : m.start()]
        clause = window.rsplit(".", 1)[-1]
        if _STATUTE_CTX_RE.search(clause):
            continue
        year = int(m.group(7))
        for dm in re.finditer(
            rf"(\d{{1,2}})\s+de\s+({_MONTH})", m.group(0), re.IGNORECASE
        ):
            d = _day(year, MONTHS_ES[dm.group(2).lower()], int(dm.group(1)))
            if d and (d.year, d.month, d.day) not in seen:
                seen.add((d.year, d.month, d.day))
                days.append(d)
    # '8 y 9 junio de 2020' — day list without 'de' before the month
    for m in _DAY_NODE_RE.finditer(conduct):
        window = conduct[max(0, m.start() - 120) : m.start()]
        clause = window.rsplit(".", 1)[-1]
        if _STATUTE_CTX_RE.search(clause):
            continue
        month = MONTHS_ES[m.group(2).lower()]
        year = int(m.group(3))
        for dm in re.finditer(r"\d{1,2}", m.group(1)):
            d = _day(year, month, int(dm.group(0)))
            if d and (d.year, d.month, d.day) not in seen:
                seen.add((d.year, d.month, d.day))
                days.append(d)
    if days:
        return min(days), max(days), "day"
    years = []
    for m in _YEAR_RE.finditer(conduct):
        window = conduct[max(0, m.start() - 80) : m.start()]
        if not _STATUTE_CTX_RE.search(window.rsplit(".", 1)[-1]):
            years.append(int(m.group(1)))
    if years:
        return (
            date(min(years), 1, 1),
            date(max(years), 12, 31),
            "year",
        )
    return None, None, None
