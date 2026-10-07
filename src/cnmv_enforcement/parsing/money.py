"""Monetary amounts. Always ``Decimal`` — never ``float``.

Spanish format: '.' thousands separator, ',' decimals: '50.000 euros',
'1.234.567,89 euros'. Also accepts ISO-ish '50000' and '50000.00'.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_NUM_ES_RE = re.compile(r"(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)")
_EURO_RE = re.compile(
    r"(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)\s*"
    r"(euros?|€|eur\b|de euros)",
    re.IGNORECASE,
)


def parse_es_number(text: str) -> Decimal | None:
    """Parse a Spanish-formatted number to Decimal. None if not parseable."""
    t = text.strip()
    if not t:
        return None
    if "," in t:
        int_part, _, frac = t.partition(",")
        int_part = int_part.replace(".", "")
        t = f"{int_part}.{frac}"
    else:
        # '300.506.05' — a dotted thousands group followed by a
        # 1–2-digit final group is a decimal ('…con cinco céntimos'),
        # not another thousands group
        m = re.fullmatch(r"(\d{1,3}(?:\.\d{3})+)\.(\d{1,2})", t)
        t = (
            f"{m.group(1).replace('.', '')}.{m.group(2)}"
            if m
            else t.replace(".", "")
        )
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def parse_euro_amount(text: str) -> tuple[Decimal, str] | None:
    """Find '<num> euros|€' in text → (Decimal, raw_match)."""
    m = _EURO_RE.search(text)
    if not m:
        return None
    num = parse_es_number(m.group(1))
    if num is None:
        return None
    return num, m.group(0)
