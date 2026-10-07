"""Text normalization helpers. Deterministic, no ML."""

from __future__ import annotations

import re
import unicodedata
from html import unescape

_WS_RE = re.compile(r"\s+")
_NBSP = "    "  # nbsp, narrow nbsp, figure space


def collapse_ws(text: str) -> str:
    """Collapse all whitespace (incl. NBSP variants) to single spaces."""
    for ch in _NBSP:
        text = text.replace(ch, " ")
    text = unescape(text)
    return _WS_RE.sub(" ", text).strip()


def strip_accents(text: str) -> str:
    """Remove accents but keep ñ/Ñ (they are legally significant)."""
    out = []
    for ch in unicodedata.normalize("NFD", text):
        base = unicodedata.normalize("NFC", ch)
        if base in "ñÑ":
            out.append(base)
            continue
        if unicodedata.category(ch) != "Mn":
            out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


def normalize_key(text: str) -> str:
    """Comparison key: lowercase, accents stripped (ñ kept), ws collapsed."""
    return collapse_ws(strip_accents(text)).lower()
