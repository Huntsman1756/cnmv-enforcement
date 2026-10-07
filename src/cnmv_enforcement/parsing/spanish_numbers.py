"""Spanish cardinal → int for amounts written in words.

Deterministic subset covering sanction amounts: units, tens, hundreds,
thousands and millions. Returns ``None`` on any unrecognized token —
``UNKNOWN`` is never silently filled.
"""

from __future__ import annotations

import re

_UNITS = {
    "cero": 0,
    "un": 1,
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
}
_TEENS = {
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciséis": 16,
    "dieciseis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
}
_TENS = {
    "veinte": 20,
    "veintiún": 21,
    "veintiun": 21,
    "veintiuno": 21,
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
    "sesenta": 60,
    "setenta": 70,
    "ochenta": 80,
    "noventa": 90,
}
_HUNDREDS = {
    "cien": 100,
    "ciento": 100,
    "cientos": 100,
    "doscientos": 200,
    "doscientas": 200,
    "trescientos": 300,
    "trescientas": 300,
    "cuatrocientos": 400,
    "cuatrocientas": 400,
    "quinientos": 500,
    "quinientas": 500,
    "seiscientos": 600,
    "seiscientas": 600,
    "setecientos": 700,
    "setecientas": 700,
    "ochocientos": 800,
    "ochocientas": 800,
    "novecientos": 900,
    "novecientas": 900,
}
_VEINTI_RE = re.compile(r"veinti([a-záéíóú]+)$")


def spanish_words_to_int(text: str) -> int | None:
    """'cincuenta mil' → 50000; 'quinientos cincuenta mil euros' handled
    upstream (strip 'euros'). Returns None if any token is unknown."""
    t = text.strip().lower()
    t = re.sub(r"\beuros?\b|\bde\b|\by\b", " ", t)
    tokens = [w for w in re.split(r"[\s-]+", t) if w]
    if not tokens:
        return None
    total = 0
    current = 0
    for w in tokens:
        if w in _UNITS:
            current += _UNITS[w]
        elif w in _TEENS:
            current += _TEENS[w]
        elif w in _TENS:
            current += _TENS[w]
        elif (vm := _VEINTI_RE.match(w)) and vm.group(1) in _UNITS:
            current += 20 + _UNITS[vm.group(1)]
        elif w in _HUNDREDS:
            current += _HUNDREDS[w]
        elif w == "mil":
            current = (current or 1) * 1000
            total += current
            current = 0
        elif w in ("millón", "millones"):
            current = (current or 1) * 1_000_000
            total += current
            current = 0
        else:
            return None
    return total + current
