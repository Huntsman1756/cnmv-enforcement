"""Parser for BOE *publication resolutions* (``BOE_PUBLICATION_RESOLUTION``).

Input: the ``diario_boe/xml.php`` document — clean metadatos + tagged
paragraphs (``<p class="parrafo|parrafo_2">``). PDF is an artifact, never
the parse source.

Observed dispositive grammar across the 91-document register corpus:

A. ``N. Imponer por la comisión de una infracción … :`` + subject-first
   bullets ``– A <subject>: <sanction>.``
B. Same header + sanction-first bullets ``– Multa por importe de N euros a
   <subject>.``
C. ``Imponer a <subject>:`` header + ``– Por la comisión de una infracción
   … , una multa por importe de N euros.`` bullets (each bullet is a
   self-contained infringement+sanction; the subject comes from the header).
D. ``Imponer a <subject(s)> por la comisión … <conduct> , multa|una multa
   por importe de N euros.`` — sanction inline at sentence end.
E. ``Imponer a <subject> por la comisión de dos infracciones … ; dos multas
   por importe de N euros cada una.`` — multi-infringement impose.
F. Lettered sanction bullets ``a) Multa …`` / ``b) Suspensión …`` —
   subject inherited from the impose header.
G. Bullet-prefixed impose lines: ``«Imponer``, ``− Imponer``, ``- Imponer``.

Severity word order variants observed:

- ``infracción muy grave tipificada en el artículo X``
- ``infracción continuada, tipificada como muy grave en el artículo X``
- ``infracción grave del artículo X``
- ``infracción muy grave de las previstas en el artículo X``
- ``por la comisión, de una infracción …`` (comma)

Nothing is assumed: one paragraph ≠ one sanction; one case ≠ one
respondent; one infringement ≠ one fine. Unrecognized tails surface as
``parse_issues`` — never silently dropped.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from lxml import etree

from cnmv_enforcement.domain.case import LegalReference
from cnmv_enforcement.domain.enums import (
    RespondentType,
    SanctionType,
    Severity,
)
from cnmv_enforcement.normalize.legal import (
    normalize_article,
    normalize_statute,
)
from cnmv_enforcement.parsing.dates import (
    extract_conduct_period,
    parse_boe_compact,
    parse_long_es,
)
from cnmv_enforcement.parsing.money import parse_es_number
from cnmv_enforcement.parsing.spanish_numbers import spanish_words_to_int
from cnmv_enforcement.parsing.text import collapse_ws

log = logging.getLogger("cnmv_enforcement.parsing.boe_publication")

_XML_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)

_BULLETS = "«\"'\\-–—−•·●\u2022\u2013\u2014\u2212"
_IMPOSE_START_RE = re.compile(
    rf"^\s*(?:\d{{1,2}}\s*[.)]?\s*)?[{_BULLETS}\s]*Imponer\b",
    re.IGNORECASE,
)
_POR_COMISION_BULLET_RE = re.compile(
    rf"^\s*(?:\d{{1,2}}\s*[.)]\s*|[a-f]\)\s*)?[{_BULLETS}\s]*"
    r"Por\s+la\s+comisi[oó]n\b",
    re.IGNORECASE,
)
_LETTERED_BULLET_RE = re.compile(
    r"^([a-f]|[ivx]{1,3})\)\s*(.+?)\.?\s*$", re.IGNORECASE | re.DOTALL
)
_SUBJECT_FIRST_RE = re.compile(
    rf"^[{_BULLETS}\s]*A\s+(.+?):\s*(.+?)\.?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_SUBJ_START = (
    r"don|doña|d\.|dña|de\s+|la\s+|las\s+|los\s+|el\s+|cada\s+|"
    r"[A-ZÁÉÍÓÚÑ]"
)
# sanction-first bullet; trailing 'a <subject>' optional — when absent the
# subjects of the enclosing impose/header are inherited.
_SANCTION_FIRST_RE = re.compile(
    rf"^[{_BULLETS}\s]*"
    r"((?:Multas?|Inhabilitaci[oó]n(?:es)?|Amonestaci[oó]n(?:es)?|"
    r"Sanci[oó]n(?:es)?|Suspensi[oó]n(?:es)?|"
    r"Separaci[oó]n(?:es)?|Restituci[oó]n(?:es)?|Confiscaci[oó]n(?:es)?|"
    r"Comiso)\b"
    r"(?:\.(?=[a-zA-Z0-9])|[^.;])*?)"
    rf"(?:\s+a\s+((?:{_SUBJ_START}).+?)|\s+(do[nñ]a?\s.+?))?\s*"
    r"[.,;]?\s*(?:y)?\s*$",
    re.IGNORECASE | re.DOTALL,
)

_COUNT_WORDS = {
    "una": 1,
    "un": 1,
    "uno": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
}
_COUNT_RE = "|".join(_COUNT_WORDS)

# 'por la comisión de (una|dos|…) infracción(es) [continuada]' — comma after
# 'comisión' observed ('por la comisión, de una infracción').
_COMISION_RE = re.compile(
    rf"por\s+la\s+comisi[oó]n\s*,?\s*"
    rf"(?:cada\s+uno\s+de\s+ellos\s*,?\s*|respectivamente\s*,?\s*)?de\s+"
    rf"(?P<count>{_COUNT_RE}|\d{{1,2}})\s+infracci[oó]n(?:es)?"
    rf"(?P<cont>\s+continuada)?",
    re.IGNORECASE,
)
# severity — after _COMISION_RE consumes 'una infracción', ``rest`` starts
# right at the severity word (' muy grave tipificada…', ' graves tipificadas',
# ' continuada, tipificada como muy grave…').
_SEV_RES = [
    re.compile(
        r"^\W*(?:continuada\s*,?\s*)?tipificad[ao]s?\s+como\s+"
        r"(?P<sev>muy\s+graves?|graves?|leves?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\W*(?:continuada\s*,?\s*)?(?P<sev>muy\s+graves?|graves?|leves?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"tipificad[ao]s?\s+como\s+(?P<sev>muy\s+graves?|graves?|leves?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"infracci[oó]n(?:es)?\s+(?:continuada\s*,?\s*)?"
        r"(?P<sev>muy\s+graves?|graves?|leves?)\b",
        re.IGNORECASE,
    ),
]
# typifying article anchors
_TYPIFY_ART_RE = re.compile(
    r"(?:tipificad[ao]s?\s+(?:en\s+(?:el|los|la|las)\s+|como\s+(?:[a-záéíóúñ]+"
    r"\s+){0,2}graves?\s+en\s+(?:el|los|la|las)\s+)"
    r"|de\s+las\s+previstas\s+en\s+(?:el|los|la|las)\s+"
    r"|previst[ao]s?\s+en\s+(?:el|los|la|las)\s+"
    r"|del?\s+)"
    r"art[ií]culo\s+(?:del?\s+|de\s+la\s+)?(?P<article>\d)",
    re.IGNORECASE,
)
_ARTICLE_TOKEN_RE = re.compile(
    r"\d{1,3}(?:\.[A-Za-z\u00f1\u00d10-9]{1,10})*"
    r"(?:\s+(?:bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies))*"
)
_RELACION_RE = re.compile(r"en\s+relaci[oó]n\s+con\s+", re.IGNORECASE)
_CONDUCT_SPLIT_RE = re.compile(
    r"[,;.]\s*(?:y\s+)?(?:por\s+(?!la\s+que\b|el\s+que\b|los\s+que\b|"
    r"las\s+que\b|lo\s+que\b|l[ao]s?\s+cual\b|tanto\b|consiguiente\b|ello\b|"
    r"ejemplo\b)|al\s+(?:haber|incumplir|realizar|utilizar|no|vulnerar|"
    r"adquirir|comunicar|disponer|transmitir|eludir|omitir))",
    re.IGNORECASE,
)
# sanction clause at the end of an impose/por-comisión sentence
_SANCTION_TAIL_RE = re.compile(
    r"\b(?P<count>una|un|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|\d{1,2})?\s*"
    r"(?P<kind>multas?|sanci[oó]n(?:es)?(?:\s+de\s+\w+)?|inhabilitaci[oó]n(?:es)?|"
    r"amonestaci[oó]n(?:es)?(?:\s+p[uú]blica)?|suspensi[oó]n(?:es)?|"
    r"separaci[oó]n(?:es)?(?:\s+del?\s+cargo)?|confiscaci[oó]n(?:es)?|comiso|"
    r"restituci[oó]n(?:es)?)\b"
    r"(?P<tail>(?:\.(?=\d)|[^.;])*)",
    re.IGNORECASE,
)
_SANCTION_SPLIT_RE = re.compile(
    rf"(?:[,;]\s*(?:y\s+)?|\s+y\s+)(?=(?:{_COUNT_RE}|\d+)?\s*"
    r"(?:sanci[oó]n(?:es)?\s+de\s+|multas?|"
    r"inhabilitaci[oó]n|amonestaci[oó]n|suspensi[oó]n|separaci[oó]n|"
    r"confiscaci[oó]n|comiso|restituci[oó]n))",
    re.IGNORECASE,
)
_AMOUNT_RES = [
    # (10.000 €) — parenthesized digits + €
    re.compile(r"\((\d[\d.]*(?:,\d+)?)\s*€\s*\)"),
    # 5.000.000 (cinco millones) de euros | 5.000.000 de euros |
    # 15.000 (quince mil) euros | 50.000 euros
    re.compile(
        r"(\d[\d.]*(?:,\d+)?)\s*(?:\([^)]*\)\s*)?(?:de\s+)?euros?",
        re.IGNORECASE,
    ),
    re.compile(r"(\d[\d.]*(?:,\d+)?)\s*€", re.IGNORECASE),
]
_WORDS_EUROS_RE = re.compile(
    r"([a-záéíóúüñ\s-]{4,60}?)\s*\(?\s*euros?\)?",
    re.IGNORECASE,
)
_SANCTIONING_RES_RE = re.compile(
    r"Resoluci[oó]n\s+del\s+Consejo\s+de\s+la\s+CNMV\s+de\s+fecha\s+"
    r"(\d{1,2}\s+de\s+\w+\s+de\s+\d{4})",
    re.IGNORECASE,
)
_FINALITY_RES = [
    re.compile(r"firmes?\s+en\s+dicha\s+v[ií]a", re.IGNORECASE),
    re.compile(r"firme\s+en\s+v[ií]a\s+administrativa", re.IGNORECASE),
    re.compile(r"firme\s+a\s+todos\s+los\s+efectos", re.IGNORECASE),
]
_JUDICIAL_REVIEW_RES = [
    re.compile(r"susceptible\s+de\s+revisi[oó]n\s+jurisdiccional", re.IGNORECASE),
    re.compile(r"recurso\s+contencioso-administrativo", re.IGNORECASE),
    re.compile(r"Sala\s+de\s+lo\s+Contencioso-Administrativo", re.IGNORECASE),
]
_ADMIN_APPEAL_RES = [
    re.compile(
        r"interpuesto\s+recurso\s+de\s+(?:alzada|reposici[oó]n)", re.IGNORECASE
    ),
    re.compile(r"recurso\s+extraordinario\s+de\s+revisi[oó]n", re.IGNORECASE),
]
_PERSON_MARK_RE = re.compile(r"^(?:don|doña|d\.|dña|d\u00f1a)\b", re.IGNORECASE)
_ANON_RE = re.compile(
    r"identidad\s+an[oó]nima|anonimato|se\s+preserva\s+su\s+identidad|"
    r"persona\s+an[oó]nima|no\s+se\s+identifica",
    re.IGNORECASE,
)
_ENTITY_HINT_RE = re.compile(
    r"\b(S\.?\s?A\.?U?E?\.?|S\.?\s?L\.?L?\.?|SGIIC|SGEIC|SGECR|SGR|FCR|FICC|"
    r"Socimi|SICAV|SIMCAV|A\.?\s?V\.?|SV\b|SIM\b|Banco|Bank|Limited|Ltd\.?|"
    r"Fondos?|Gestora|Sucursal|EAFI?|Cartera)\b",
    re.IGNORECASE,
)
_ROLE_SPLIT_RE = re.compile(
    r",\s*(?=(?:en\s+su\s+calidad\s+de|en\s+su\s+condici[oó]n\s+de|"
    r"como\s+(?:consejero|administrador|director|presidente|apoderado)|"
    r"consejero|consejeros|administrador(?:es)?|director(?:es)?|presidente|"
    r"secretario|apoderado|miembros?\b|cargo\s+de|directivo))",
    re.IGNORECASE,
)
# same-statute shorthands in related provisions
_SAME_STATUTE_RE = re.compile(
    r"mismo\s+texto\s+legal|misma\s+ley|citad[ao]s?\s+(?:texto\s+legal|ley|"
    r"reglamento|norma)|del?\s+citad[ao]",
    re.IGNORECASE,
)


@dataclass
class ParsedParagraph:
    index: int
    css_class: str
    text: str


@dataclass
class ParsedSanctionLine:
    subject_raw: str
    sanction_raw: str
    sanction_type: SanctionType
    amount: Decimal | None
    currency: str | None
    amount_raw: str | None
    paragraph_index: int
    excerpt: str
    ordinal: int = 0
    duration_raw: str | None = None


@dataclass
class ParsedBlock:
    ordinal: int
    paragraph_index: int
    header_text: str
    severity: Severity
    statute_raw: str | None
    article_raw: str | None
    statute_normalized: str | None
    article_normalized: str | None
    related: list[LegalReference] = field(default_factory=list)
    conduct_raw: str | None = None
    conduct_start: date | None = None
    conduct_end: date | None = None
    conduct_precision: str | None = None  # 'day' | 'year'
    subjects_inline: list[str] = field(default_factory=list)
    sanctions: list[ParsedSanctionLine] = field(default_factory=list)


@dataclass
class ParsedPublication:
    boe_id: str | None
    title: str | None
    publication_date: date | None
    document_date: date | None
    sanctioning_resolution_date: date | None
    blocks: list[ParsedBlock] = field(default_factory=list)
    paragraphs: list[ParsedParagraph] = field(default_factory=list)
    administrative_finality: bool = False
    judicial_review_possible: bool = False
    administrative_appeal: bool = False
    underlying_resolutions: list[str] = field(default_factory=list)
    parse_issues: list[str] = field(default_factory=list)


def _severity_from(text: str) -> Severity:
    for rx in _SEV_RES:
        m = rx.search(text)
        if m:
            key = collapse_ws(m.group("sev")).lower()
            if key.startswith("muy"):
                return Severity.VERY_SERIOUS
            if key.startswith("grave"):
                return Severity.SERIOUS
            if key.startswith("leve"):
                return Severity.MINOR
    return Severity.UNKNOWN


def _count_of(word: str | None) -> int:
    if not word:
        return 1
    w = word.strip().lower()
    if w.isdigit():
        return int(w)
    return _COUNT_WORDS.get(w, 1)


def classify_subject(name_raw: str) -> RespondentType:
    if _ANON_RE.search(name_raw):
        return RespondentType.ANONYMIZED_PERSON
    if _PERSON_MARK_RE.match(name_raw.strip()):
        return RespondentType.NATURAL_PERSON
    if _ENTITY_HINT_RE.search(name_raw):
        return RespondentType.LEGAL_PERSON
    return RespondentType.UNKNOWN


def split_subject_role(chunk: str) -> tuple[str, str | None]:
    """Split 'X, en su calidad de consejero' / 'X (consejero delegado)'
    → ('X', role). Parenthesized roles are extracted FIRST so the comma
    split can never cut inside them."""
    role = None
    name = chunk
    m = re.match(
        r"^(.*?)\s*\(([^)]*(?:consejero|administrador|director|presidente|"
        r"secretario|apoderado|directivo|condici[oó]n|calidad)[^)]*)\)\s*$",
        chunk,
        re.IGNORECASE,
    )
    if m:
        name, role = m.group(1).strip(), m.group(2).strip()
    if role is None:
        parts = _ROLE_SPLIT_RE.split(chunk, maxsplit=1)
        name = parts[0].strip().rstrip(",")
        role = parts[1].strip().rstrip(",.") if len(parts) > 1 else None
    return name, role


def split_subjects(raw: str) -> list[str]:
    """'a X, a Y y a Z' or 'X, Y' → subject chunks (names may contain
    commas like 'Gesconsult, SA, SGIIC')."""
    raw = re.sub(r"^a\s+", "", raw.strip(), flags=re.IGNORECASE)
    parts = re.split(
        r",\s+(?=a\s+|de\s+|el\s+|la\s+|don\b|doña\b|d\.\s|dña\b)|"
        r"\s+y\s+a\s+|\s+e\s+a\s+|"
        r"\s+[ye]\s+(?=don\b|doña\b|d\.\s|dña\b)",
        raw,
        flags=re.IGNORECASE,
    )
    out = []
    for part in parts:
        p = re.sub(r"^a\s+", "", part.strip().rstrip(","), flags=re.IGNORECASE)
        if p:
            out.append(p)
    return out


def parse_amount(tail: str) -> tuple[Decimal | None, str | None]:
    """Extract a euro amount from a sanction tail.

    Handles: '50.000 euros', '(10.000 €)', '5.000.000 (cinco millones) de
    euros', and word-only 'diez mil euros'.
    """
    for rx in _AMOUNT_RES:
        m = rx.search(tail)
        if m:
            num = next(g for g in m.groups() if g)
            amount = parse_es_number(num)
            if amount is not None:
                return amount, m.group(0).strip()
    # word-only fallback: 'diez mil euros', 'cincuenta mil euros'
    m = _WORDS_EUROS_RE.search(tail)
    if m:
        n = spanish_words_to_int(m.group(1))
        if n is not None:
            return Decimal(n), m.group(0).strip()
    return None, None


def _sanction_kind(kind: str) -> SanctionType:
    k = collapse_ws(kind).lower()
    if k.startswith(("sanción de ", "sancion de ")):
        k = k.split(" de ", 1)[1]
    if k.startswith("multa"):
        return SanctionType.MONETARY_FINE
    if k.startswith(("inhabilit", "separaci")):
        return SanctionType.DISQUALIFICATION
    if k.startswith("amonest"):
        return SanctionType.PUBLIC_REPRIMAND
    if k.startswith("suspens"):
        return SanctionType.SUSPENSION
    if any(k.startswith(w) for w in ("confisca", "comiso", "restitu")):
        return SanctionType.DISGORGEMENT
    return SanctionType.UNKNOWN


def parse_sanction_tail(
    zone: str,
    subjects: list[str],
    paragraph_index: int,
    excerpt: str,
    ordinal_start: int,
) -> list[ParsedSanctionLine]:
    """Expand a sanction zone — possibly several sanction clauses joined by
    ', y' or ';' — into per-(subject,count) sanction lines.

    'sanción de separación del cargo …, y sanción de multa por importe de
    40.000 euros' → 2 sanctions.
    'dos multas por importe de 10.000 € cada una' → 2 sanctions.
    """
    lines: list[ParsedSanctionLine] = []
    ord_ = ordinal_start
    for raw_seg in _SANCTION_SPLIT_RE.split(zone):
        seg = raw_seg.strip().lstrip(",;").strip()
        if not seg:
            continue
        m = _SANCTION_TAIL_RE.match(seg)
        if not m:
            continue
        tail = m.group("tail") or ""
        count = _count_of(m.group("count"))
        kind = m.group("kind")
        st = _sanction_kind(kind)
        amount, amount_raw = parse_amount(tail + " " + kind)
        duration_raw = None
        dm = re.search(
            r"(por\s+(?:un\s+)?(?:plazo|per[ií]odo)\s+de\s+[^.;]+)",
            tail,
            re.IGNORECASE,
        )
        if dm:
            duration_raw = dm.group(1).strip()
        raw = m.group(0).strip()
        sm = re.search(r"\ba\s+((?:don|doña|d\.|dña|[A-ZÁÉÍÓÚÑ])[^.;]*)$", tail)
        line_subjects = subjects
        if sm and sm.group(1).strip():
            line_subjects = [sm.group(1).strip()]
        n_subj = max(1, len(line_subjects))
        per = count // n_subj if count % n_subj == 0 else count
        for subj in line_subjects or [""]:
            for _ in range(max(1, per)):
                ord_ += 1
                lines.append(
                    ParsedSanctionLine(
                        subject_raw=subj,
                        sanction_raw=raw,
                        sanction_type=st,
                        amount=amount,
                        currency="EUR" if amount is not None else None,
                        amount_raw=amount_raw,
                        paragraph_index=paragraph_index,
                        excerpt=excerpt,
                        ordinal=ord_,
                        duration_raw=duration_raw,
                    )
                )
    return lines


# cut a statute segment at the first conduct boundary (', por X' / ', al X')
_STATUTE_TAIL_CUT_RE = re.compile(
    r"[,;]\s*(?:y\s+)?(?:por\s+(?!la\s+que\b|el\s+que\b|los\s+que\b|"
    r"las\s+que\b|lo\s+que\b|l[ao]s?\s+cual\b)|al\s+)",
    re.IGNORECASE,
)
_CONDUCT_ART_RE = re.compile(
    r"(?:(?:vulneraci[oó]n|incumplimiento|incumpliendo|incumplir)\s+de[l]?\s*"
    r"(?:la|los|las|el)?\s*|establecid[ao]s?\s+en\s+(?:el|los|la|las)\s+)"
    r"art[ií]culo\s+",
    re.IGNORECASE,
)


def _related_refs(
    segment: str, default_statute: tuple[str | None, str | None]
) -> list[LegalReference]:
    """Articles inside an 'en relación con' segment + their statute context.

    The segment may carry its own instrument ('del Reglamento (UE) n.º
    596/2014…'), a same-statute shorthand ('ambos del mismo texto legal'),
    or nothing (inherit).
    """
    refs: list[LegalReference] = []
    stat_norm = normalize_statute(segment)
    if _SAME_STATUTE_RE.search(segment):
        stat_raw, stat_n = default_statute
        stat_norm = stat_n
        stat_raw_use = stat_raw or segment
    else:
        stat_raw_use = segment if stat_norm else (default_statute[0] or segment)
        stat_norm = stat_norm or default_statute[1]
    # anchored extraction: articles only after 'artículo(s)' — dates and law
    # numbers elsewhere in the segment must never become provisions.
    for anchor in re.finditer(r"art[ií]culo(?:s)?\s+", segment, re.IGNORECASE):
        pos = anchor.end()
        # consume an article list: '45, 47 y 48' / '13.2 y 45' / '240 bis'
        while True:
            m = _ARTICLE_TOKEN_RE.match(segment, pos)
            if not m:
                break
            raw = m.group(0)
            refs.append(
                LegalReference(
                    statute_raw=stat_raw_use,
                    article_raw=raw,
                    statute_normalized=stat_norm,
                    article_normalized=normalize_article(raw),
                    relation="RELATED",
                )
            )
            pos = m.end()
            sep = re.match(
                r"\s*(?:,|y\b|e\b)\s*(?:los\s+|el\s+|las\s+|la\s+)?",
                segment[pos:],
                re.IGNORECASE,
            )
            if not sep:
                break
            pos += sep.end()
            if pos >= len(segment) or not segment[pos].isdigit():
                break
    return refs


def parse_comision(
    text: str,
) -> tuple[
    Severity,
    int,
    str | None,
    str | None,
    str | None,
    list[LegalReference],
    str | None,
    str,
]:
    """Parse the part after 'por la comisión'.

    Returns (severity, n_infringements, statute_raw, article_raw,
    statute_norm, related, conduct_raw, sanction_tail_text).
    """
    m = _COMISION_RE.search(text)
    if not m:
        return Severity.UNKNOWN, 1, None, None, None, [], None, text
    n_infr = _count_of(m.group("count"))
    rest = text[m.end() :]
    severity = _severity_from(rest)
    # sanction zone: FIRST sanction clause with a real boundary ('…, una
    # sanción de separación …, y sanción de multa…' starts a 2-clause zone).
    # Missing-comma tolerance: a year or closing paren before the clause.
    sanction_tail = ""
    zone_start: int | None = None
    candidates = list(_SANCTION_TAIL_RE.finditer(rest))
    for cand in candidates:
        before = rest[: cand.start()].rstrip()
        if before and before[-1] in ",;.":
            zone_start = cand.start()
            break
    if zone_start is None and candidates:
        last = candidates[-1]
        before = rest[: last.start()].rstrip()
        if re.search(r"\d{4}\s*$|\)\s*$", before):
            zone_start = last.start()
    if zone_start is not None:
        sanction_tail = rest[zone_start:]
        rest = rest[:zone_start].rstrip()
    # conduct clause: starts at the FIRST ', por/al <verb>' boundary — the
    # whole remainder (possibly several ', por' parts) describes the conduct
    conduct_raw = None
    cands = list(_CONDUCT_SPLIT_RE.finditer(rest))
    if cands:
        first = cands[0]
        head = rest[: first.start()]
        conduct_raw = rest[first.end() :].strip().rstrip(":.").strip() or None
    else:
        head = rest
    # typifying article
    article_raw = statute_raw = statute_norm = None
    related: list[LegalReference] = []
    tm = _TYPIFY_ART_RE.search(head)
    if tm:
        atok = _ARTICLE_TOKEN_RE.match(head, tm.end() - 1)
        art_end = atok.end() if atok else tm.end()
        if atok:
            article_raw = atok.group(0).rstrip(")").strip()
            # space-separated letter suffix: '282.16 c)' → '282.16.c'
            lt = re.match(r"\s+([a-zñ])\s*\)", head[atok.end() :], re.IGNORECASE)
            if lt:
                article_raw = f"{article_raw}.{lt.group(1).lower()}"
                art_end = atok.end() + lt.end()
        after = head[art_end:]
        rel_parts = _RELACION_RE.split(after)
        first_seg = rel_parts[0]
        # cut at the conduct boundary BEFORE normalizing — a statute mention
        # inside the conduct clause must never become the typifying statute
        stat_seg = _STATUTE_TAIL_CUT_RE.split(first_seg, maxsplit=1)[0]
        sn = normalize_statute(stat_seg)
        if sn or not _SAME_STATUTE_RE.search(first_seg):
            statute_raw = stat_seg.strip().rstrip(",;.").strip() or None
            statute_norm = sn
        for seg in rel_parts[1:]:
            related.extend(_related_refs(seg, (statute_raw, statute_norm)))
    # conduct-article refs: 'por vulneración del artículo 15' —
    # the breached provision; statute = first instrument mentioned AFTER the
    # token, else the typifying statute when 'la misma norma'/'mismo texto'.
    for vm in _CONDUCT_ART_RE.finditer(rest):
        tok = _ARTICLE_TOKEN_RE.search(rest, vm.end() - 1)
        if tok:
            after_tok = rest[tok.end() :]
            if _SAME_STATUTE_RE.search(after_tok):
                cstat = statute_norm
            else:
                cstat = normalize_statute(after_tok)
            related.append(
                LegalReference(
                    statute_raw=after_tok.strip(),
                    article_raw=tok.group(0),
                    statute_normalized=cstat,
                    article_normalized=normalize_article(tok.group(0)),
                    relation="CONDUCT",
                )
            )
    return (
        severity,
        n_infr,
        statute_raw,
        article_raw,
        statute_norm,
        related,
        conduct_raw,
        sanction_tail,
    )


def parse_publication_xml(
    xml_bytes: bytes, observed_at: datetime | None = None
) -> ParsedPublication:
    observed_at = observed_at or datetime.now(UTC)
    root = etree.fromstring(xml_bytes, parser=_XML_PARSER)
    meta = root.find("metadatos")

    def mtext(name: str) -> str | None:
        if meta is None:
            return None
        el = meta.find(name)
        if el is None or el.text is None:
            return None
        return el.text.strip() or None

    pub = ParsedPublication(
        boe_id=mtext("identificador"),
        title=mtext("titulo"),
        publication_date=parse_boe_compact(mtext("fecha_publicacion") or ""),
        document_date=parse_boe_compact(mtext("fecha_disposicion") or ""),
        sanctioning_resolution_date=None,
    )
    texto = root.find("texto")
    if texto is None:
        pub.parse_issues.append("no <texto> element")
        return pub
    for i, p in enumerate(texto.findall("p")):
        txt = collapse_ws("".join(p.itertext()))
        if txt:
            pub.paragraphs.append(
                ParsedParagraph(index=i, css_class=p.get("class", ""), text=txt)
            )

    full_text = "\n".join(p.text for p in pub.paragraphs)
    m = _SANCTIONING_RES_RE.search(full_text)
    if m:
        pub.sanctioning_resolution_date = parse_long_es(m.group(1))
    pub.administrative_finality = any(r.search(full_text) for r in _FINALITY_RES)
    pub.judicial_review_possible = any(
        r.search(full_text) for r in _JUDICIAL_REVIEW_RES
    )
    pub.administrative_appeal = any(r.search(full_text) for r in _ADMIN_APPEAL_RES)

    current: ParsedBlock | None = None
    context_subjects: list[str] = []
    sanction_ord = 0
    impose_ord = 0

    def new_blocks(para: ParsedParagraph, subjects: list[str]) -> list[ParsedBlock]:
        nonlocal impose_ord, sanction_ord
        (
            sev,
            n_infr,
            statute_raw,
            article_raw,
            statute_norm,
            related,
            conduct,
            tail,
        ) = parse_comision(para.text)
        c_start = c_end = None
        c_prec = None
        if conduct:
            c_start, c_end, c_prec = extract_conduct_period(conduct)
        tail_lines = (
            parse_sanction_tail(tail, subjects, para.index, para.text, sanction_ord)
            if tail
            else []
        )
        sanction_ord += len(tail_lines)

        def make_block(sanctions: list[ParsedSanctionLine]) -> ParsedBlock:
            nonlocal impose_ord
            impose_ord += 1
            return ParsedBlock(
                ordinal=impose_ord,
                paragraph_index=para.index,
                header_text=para.text,
                severity=sev,
                statute_raw=statute_raw,
                article_raw=article_raw,
                statute_normalized=statute_norm,
                article_normalized=(
                    normalize_article(article_raw) if article_raw else None
                ),
                related=related,
                conduct_raw=conduct,
                conduct_start=c_start,
                conduct_end=c_end,
                conduct_precision=c_prec,
                subjects_inline=subjects,
                sanctions=sanctions,
            )

        # 'N infracciones' + 'N multas … cada una' → N infringements, 1 fine
        # each. Otherwise a single block carries what the sentence gives.
        if n_infr > 1 and len(tail_lines) == n_infr:
            return [make_block([line]) for line in tail_lines]
        if n_infr > 1:
            pub.parse_issues.append(
                f"impose declares {n_infr} infringements but "
                f"{len(tail_lines)} sanctions parsed (para {para.index})"
            )
        return [make_block(tail_lines)]

    for para in pub.paragraphs:
        t = para.text
        if _IMPOSE_START_RE.match(t):
            subj_part = ""
            cm = _COMISION_RE.search(t)
            if cm:
                subj_part = t[: cm.start()]
            else:
                # 'Imponer a X:' subjects-only header (no 'por la comisión')
                sm = re.match(
                    rf"^\s*(?:\d{{1,2}}\s*[.)]\s*)?[{_BULLETS}\s]*"
                    r"Imponer\s+a\s+(.+?)[:.]?\s*$",
                    t,
                    re.IGNORECASE,
                )
                if sm:
                    context_subjects = split_subjects(sm.group(1))
                    current = None
                    continue
            subs = []
            if subj_part:
                sm2 = re.search(r"Imponer\s+a\s+(.+)$", subj_part, re.IGNORECASE)
                if sm2:
                    subs = split_subjects(sm2.group(1))
            if subs:
                context_subjects = subs
            blocks = new_blocks(para, subs)
            pub.blocks.extend(blocks)
            current = blocks[-1]
            continue
        if _POR_COMISION_BULLET_RE.match(t):
            # standalone infringement+sanction bullet; inherits header subject
            blocks = new_blocks(para, context_subjects)
            pub.blocks.extend(blocks)
            current = blocks[-1]
            continue
        if current is None:
            continue
        # subject-first bullet: '– A <subj>: <sanction>'
        msubj = _SUBJECT_FIRST_RE.match(t)
        if msubj:
            sanction_ord += 1
            tail_txt = msubj.group(2)
            st, amt, amt_raw, dur = _line_sanction(tail_txt)
            current.sanctions.append(
                ParsedSanctionLine(
                    subject_raw=msubj.group(1).strip(),
                    sanction_raw=collapse_ws(tail_txt),
                    sanction_type=st,
                    amount=amt,
                    currency="EUR" if amt is not None else None,
                    amount_raw=amt_raw,
                    paragraph_index=para.index,
                    excerpt=t,
                    ordinal=sanction_ord,
                    duration_raw=dur,
                )
            )
            continue
        ml = _LETTERED_BULLET_RE.match(t)
        if ml:
            body = ml.group(2).strip()
            # lettered subject-first: 'a) A don X, multa por importe de…'
            mlet_subj = re.match(r"(?i)a\s+(.+?),\s*(.+)$", body, re.DOTALL)
            if mlet_subj:
                sanction_ord += 1
                st, amt, amt_raw, dur = _line_sanction(mlet_subj.group(2))
                current.sanctions.append(
                    ParsedSanctionLine(
                        subject_raw=mlet_subj.group(1).strip(),
                        sanction_raw=collapse_ws(mlet_subj.group(2)),
                        sanction_type=st,
                        amount=amt,
                        currency="EUR" if amt is not None else None,
                        amount_raw=amt_raw,
                        paragraph_index=para.index,
                        excerpt=t,
                        ordinal=sanction_ord,
                        duration_raw=dur,
                    )
                )
                continue
            if re.match(
                r"(?i)(multa|inhabilitaci|amonestaci|sancion|suspensi|confisca|"
                r"comiso|restitu)",
                body,
            ):
                # sanction text may embed its own subject: 'Multa … a don X'
                emb = re.search(
                    r"^(.*?)\s+a\s+((?:don|doña|d\.|dña|[A-ZÁÉÍÓÚÑ])"
                    r"[^.;]+?)\.?\s*$",
                    body,
                    re.DOTALL,
                )
                emb_subj = None
                sanc_txt = body
                if emb and emb.group(1) and not emb.group(1).strip().endswith(
                    ("de", "del", "para", "por")
                ):
                    emb_subj = emb.group(2).strip()
                    sanc_txt = emb.group(1)
                st, amt, amt_raw, dur = _line_sanction(sanc_txt)
                for subj in [emb_subj] if emb_subj else (context_subjects or [""]):
                    sanction_ord += 1
                    current.sanctions.append(
                        ParsedSanctionLine(
                            subject_raw=subj,
                            sanction_raw=collapse_ws(sanc_txt),
                            sanction_type=st,
                            amount=amt,
                            currency="EUR" if amt is not None else None,
                            amount_raw=amt_raw,
                            paragraph_index=para.index,
                            excerpt=t,
                            ordinal=sanction_ord,
                            duration_raw=dur,
                        )
                    )
                continue
        # sanction-first bullet: '– Multa por importe de N euros a <subj>.'
        # subject optional — inherits the enclosing header's subjects; a
        # bullet may hold several clauses ('… y sanción de separación…')
        msanc = _SANCTION_FIRST_RE.match(t)
        if msanc:
            subj_part = msanc.group(2) or msanc.group(3)
            if subj_part and ":" in subj_part:
                # 'a cada uno de los siguientes miembros…: <member list>'
                subj_part = subj_part.split(":", 1)[1]
            line_subjects = (
                split_subjects(subj_part)
                if subj_part
                else (context_subjects or [""])
            )
            for seg_ in _SANCTION_SPLIT_RE.split(msanc.group(1)):
                seg = seg_.strip().lstrip(",;").strip()
                if not seg:
                    continue
                st, amt, amt_raw, dur = _line_sanction(seg)
                for subj in line_subjects:
                    sanction_ord += 1
                    current.sanctions.append(
                        ParsedSanctionLine(
                            subject_raw=subj,
                            sanction_raw=collapse_ws(seg),
                            sanction_type=st,
                            amount=amt,
                            currency="EUR" if amt is not None else None,
                            amount_raw=amt_raw,
                            paragraph_index=para.index,
                            excerpt=t,
                            ordinal=sanction_ord,
                            duration_raw=dur,
                        )
                    )
            continue
        # 'N. Resolución del Consejo …' — the underlying sanctioning
        # resolutions the publication covers; metadata, not a sanction line
        if re.match(r"^\s*\d{1,2}\.\s*Resoluci[oó]n\b", t):
            pub.underlying_resolutions.append(t)
            continue
        # safety net: a bullet/numbered-looking line under an open block
        # that matched nothing must surface, never drop silently
        if re.match(rf"^\s*(?:[{_BULLETS}]|[a-f]\)|\d{{1,2}}\s*[.)])", t):
            pub.parse_issues.append(
                f"unhandled line under block {current.ordinal} "
                f"(para {para.index}): {t[:100]}"
            )
    # ---- document-level statute context -------------------------------
    # In-document references are resolved deterministically, raw text kept:
    # 1. 'todos ellos/ambos de <LAW>' in a related segment covers the
    #    typifying article too (explicit universal quantifier).
    # 2. the preamble may restate the same article WITH its statute
    #    ('del artículo 282.3 de la Ley del Mercado de Valores') — a
    #    same-article match adopts that statute.
    # 3. 'del mismo texto legal' shorthand inherits the statute of the
    #    nearest earlier block.
    block_paras = {b.paragraph_index for b in pub.blocks}
    preamble_art_stat: dict[str, tuple[str, str]] = {}
    for para in pub.paragraphs:
        if para.index in block_paras:
            continue
        for m in _TYPIFY_ART_RE.finditer(para.text):
            tok = _ARTICLE_TOKEN_RE.match(para.text, m.end() - 1)
            if not tok:
                continue
            art_n = normalize_article(tok.group(0).rstrip(")"))
            stat_seg = para.text[tok.end() : tok.end() + 220]
            stat_seg = _STATUTE_TAIL_CUT_RE.split(stat_seg, maxsplit=1)[0]
            sn = normalize_statute(stat_seg)
            if sn and art_n:
                preamble_art_stat[art_n] = (stat_seg[:120], sn)
    last_stat: str | None = None
    for b in pub.blocks:
        if b.statute_normalized is None:
            for r in b.related:
                if r.statute_normalized and re.search(
                    r"tod[ao]s\s+ell[ao]s|ambo[as]s?", r.statute_raw or "", re.I
                ):
                    b.statute_normalized = r.statute_normalized
                    if not b.statute_raw or b.statute_raw == ")":
                        b.statute_raw = r.statute_raw
                    break
        if b.statute_normalized is None and b.article_normalized in preamble_art_stat:
            raw, sn = preamble_art_stat[b.article_normalized]
            b.statute_normalized = sn
            if not b.statute_raw or b.statute_raw == ")":
                b.statute_raw = raw
        if b.statute_normalized is None:
            b.statute_normalized = last_stat
        if b.statute_normalized:
            last_stat = b.statute_normalized
    return pub


def _line_sanction(
    text: str,
) -> tuple[SanctionType, Decimal | None, str | None, str | None]:
    """Type + amount + duration for a standalone sanction phrase."""
    km = re.match(
        r"(?i)\s*(multa|inhabilitaci[oó]n|amonestaci[oó]n|"
        r"sanci[oó]n(?:\s+de\s+\w+)?|"
        r"suspensi[oó]n|confiscaci[oó]n|comiso|restituci[oó]n|"
        r"separaci[oó]n(?:\s+del?\s+cargo)?)",
        text,
    )
    st = _sanction_kind(km.group(1)) if km else SanctionType.UNKNOWN
    amount, amount_raw = parse_amount(text)
    duration_raw = None
    dm = re.search(
        r"(por\s+(?:un\s+)?(?:plazo|per[ií]odo)\s+de\s+[^.;]+)",
        text,
        re.IGNORECASE,
    )
    if dm:
        duration_raw = dm.group(1).strip()
    # bare amount after subject colon ('● A X: 100.000 euros') is a fine
    if st == SanctionType.UNKNOWN and amount is not None:
        st = SanctionType.MONETARY_FINE
    return st, amount, amount_raw, duration_raw
