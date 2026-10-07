"""Deterministic legal-reference normalization.

Rules:

- ``raw`` is never destroyed; ``normalized`` is a pure function of ``raw``.
- Letter suffixes are significant: ``94.o`` ≠ ``94.0``; ``94.ñ`` stays ``ñ``.
- ``bis``/``ter``/``quater``/``quinquies`` are preserved: ``94 bis`` → ``94.bis``.
- Ordinals/apartados stay numeric: ``92.1``, ``115.5``, ``13.2``.
- EU instruments keep their CE-style number: ``Reglamento (UE) 596/2014``.
"""

from __future__ import annotations

import re

_WORD_SUFFIX = (
    r"bis|ter|qu[aá]ter|quinquies|sexies|septies|octies|nonies|decies|"
    r"undecies|duodecies|tredecies"
)

# Article body: number followed by any mix of ".part" where part is
# letters (a, ñ, o, bis, ter…) or digits (13.2, 92.1, 115.5, 99.bis.1).
_BODY = r"\d{1,3}(?:\.[A-Za-z\u00f1\u00d10-9]{1,10})*"

# word/letter suffixes: '94 bis', '83 ter', '107 quáter', '99 z'.
# Space-separated single letters exclude a/e/i/o/u/y — those are
# conjunctions in article lists ('67 y 71', '45 y 48')
_WORDS = rf"(?:{_WORD_SUFFIX}|[b-df-hj-np-tv-xzñ](?![a-záéíóúñ]))"
# apartado digit + optional letter: '83 ter 1', '107 quáter 3.c'
_APART = r"(?:\s+\d(?:\.[A-Za-z\u00f1])?)?"

_ARTICLE_TOKEN_RE = re.compile(
    rf"(?P<body>{_BODY})(?P<words>(?:\s+{_WORDS})*)(?P<apart>{_APART})",
    re.IGNORECASE,
)

_ARTICLE_FULL_RE = re.compile(
    rf"^\s*\)?\s*(?P<body>{_BODY})(?P<words>(?:\s+{_WORDS})*)"
    rf"(?P<apart>{_APART})\s*\)?\s*$",
    re.IGNORECASE,
)


_WORD_SUFFIX_NORM = {
    "quáter": "quater",
}


def _normalized_from_match(m: re.Match[str]) -> str:
    out = m.group("body").strip()
    words = re.sub(r"\s+", " ", (m.group("words") or "").strip()).lower()
    if words:
        out += "." + ".".join(
            _WORD_SUFFIX_NORM.get(w, w) for w in words.split()
        )
    apart = re.sub(r"\s+", " ", (m.groupdict().get("apart") or "").strip())
    if apart:
        out += "." + apart.replace(" ", ".")
    return out


def normalize_article(raw: str) -> str | None:
    """'93.a)' → '93.a'; '94 bis' → '94.bis'; '13.2' → '13.2'; '94.o)' → '94.o';
    '99, letra o)' → '99.o'; '83 ter 1' → '83.ter.1'."""
    m = _ARTICLE_FULL_RE.match(raw)
    if m:
        return _normalized_from_match(m)
    # '99, letra o)' / '99, letra o) bis' — comma-letter style
    lm = re.match(
        rf"^\s*(?P<body>{_BODY})(?P<words>(?:\s+(?:{_WORD_SUFFIX}))*)\s*,?\s*"
        r"letra\s+(?P<letter>[a-zñ])\s*\)?\s*$",
        raw,
        re.IGNORECASE,
    )
    if lm:
        words = re.sub(
            r"\s+", " ", (lm.group("words") or "").strip()
        ).lower()
        out = lm.group("body")
        if words:
            out += "." + ".".join(
                _WORD_SUFFIX_NORM.get(w, w) for w in words.split()
            )
        return f"{out}.{lm.group('letter').lower()}"
    return None


def extract_article(fragment: str) -> str | None:
    """Extract the article token at the start of a fragment like
    '93.a)' or '94.o) en relación…'."""
    t = fragment.strip()
    m = _ARTICLE_TOKEN_RE.match(t)
    if not m:
        return None
    return _normalized_from_match(m)


# 'artículo(s) X' mention inside free text
ARTICLE_MENTION_RE = re.compile(
    rf"art[ií]culos?\s+({_BODY}(?:\s+(?:{_WORD_SUFFIX}))*)\s*\)?",
    re.IGNORECASE,
)

_STATUTE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"\bReglamento\s+Delegado\s*\(\s*UE\s*\)\s*(\d+/\d{4})",
            re.IGNORECASE,
        ),
        "Reglamento Delegado (UE) {}",
    ),
    (
        re.compile(
            r"\bReglamento\s+de\s+Ejecuci[oó]n\s*\(\s*UE\s*\)\s*(\d+/\d{4})",
            re.IGNORECASE,
        ),
        "Reglamento de Ejecución (UE) {}",
    ),
    (
        re.compile(
            r"\bReglamento\s*\(\s*UE\s*\)\s*"
            r"(?:n\.?[ºo]\.?|número|núm\.?)?\s*(\d+/\d{4})",
            re.IGNORECASE,
        ),
        "Reglamento (UE) {}",
    ),
    (
        re.compile(r"\bDirectiva\s+(\d{4}/\d+/\w+)", re.IGNORECASE),
        "Directiva {}",
    ),
    (
        re.compile(
            r"\bReal\s+Decreto-Ley\s+(\d+/\d{4})",
            re.IGNORECASE,
        ),
        "Real Decreto-ley {}",
    ),
    (
        re.compile(
            r"\bReal\s+Decreto\s+legislativo\s+(\d+/\d{4})",
            re.IGNORECASE,
        ),
        "Real Decreto Legislativo {}",
    ),
    (
        re.compile(r"\bReal\s+Decreto\s+(\d+/\d{4})", re.IGNORECASE),
        "Real Decreto {}",
    ),
    (
        re.compile(r"\bLey\s+(\d+/\d{4})", re.IGNORECASE),
        "Ley {}",
    ),
    (
        re.compile(r"\bDirectiva\s+(\d+/\d+)", re.IGNORECASE),
        "Directiva {}",
    ),
    # named instruments without number — normalization keeps the name; the
    # temporal version is resolved by the legal-rules layer, never guessed.
    (
        re.compile(
            r"\bLey\s+del\s+Mercado\s+de\s+Valores(?:\s+y\s+de\s+los\s+"
            r"Servicios\s+de\s+Inversi[oó]n)?",
            re.IGNORECASE,
        ),
        "Ley del Mercado de Valores",
    ),
    (
        re.compile(r"\bLMV(?:SI)?\b", re.IGNORECASE),
        "Ley del Mercado de Valores",
    ),
    (
        re.compile(
            r"\bLey\s+de\s+Instituciones\s+de\s+Inversi[oó]n\s+Colectiva",
            re.IGNORECASE,
        ),
        "Ley de Instituciones de Inversión Colectiva",
    ),
    (
        re.compile(r"\bLey\s+de\s+Sociedades\s+de\s+Capital", re.IGNORECASE),
        "Ley de Sociedades de Capital",
    ),
    (
        re.compile(r"\bLey\s+Concursal\b", re.IGNORECASE),
        "Ley Concursal",
    ),
    (
        re.compile(r"\bCircular\s+(\d+/\d{4})", re.IGNORECASE),
        "Circular {}",
    ),
    (
        re.compile(r"\bNorma\s+(\d+)\s+de\s+la\s+Circular", re.IGNORECASE),
        "Norma {}",
    ),
]


def normalize_statute(raw: str) -> str | None:
    """'Ley 22/2014, de 12 de noviembre, por la que…' → 'Ley 22/2014'."""
    for pat, fmt in _STATUTE_PATTERNS:
        m = pat.search(raw)
        if m:
            return fmt.format(m.group(1) if m.groups() else "")
    return None


def find_statute_mentions(text: str) -> list[str]:
    """All normalized statute mentions in a text, in order, deduplicated."""
    out: list[str] = []
    for pat, fmt in _STATUTE_PATTERNS:
        for m in pat.finditer(text):
            ref = fmt.format(m.group(1))
            if ref not in out:
                out.append(ref)
    return out
