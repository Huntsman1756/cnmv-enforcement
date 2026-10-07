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

_BULLETS = r"«\"'\-–—−•·●•–—−‘’‚„“”"
_IMPOSE_START_RE = re.compile(
    rf"^(?:[{_BULLETS}\s]|(?:\d{{1,2}}|[a-zñ])\s*[.)]\s*)*Imponer\b",
    re.IGNORECASE,
)
# historical comision variants normalized before the canonical check:
# 'N. La comisión de una infracción…' → 'Por la comisión de una…';
# '• De una infracción…' → 'Por la comisión de una infracción…';
# 'X, como responsable de la comisión de…' → 'X, por la comisión de…'
_PRE_COMISION_NORM = re.compile(
    rf"^([{_BULLETS}\s]*(?:\d{{1,2}}\s*[.)]\s*|[a-f]\)\s*)?)"
    r"(?:La\s+comisi[oó]n\s+de\s+(?=una|dos|tres|cuatro|un\s+|infracci)|"
    r"De\s+(?=una\s+infracci[oó]n))",
    re.IGNORECASE,
)
# 'como responsable de la comisión de' == 'por la comisión de' —
# the imposition clause names the subject as responsible party
_PRE_RESPONSABLE_NORM = re.compile(
    r"como\s+responsable\s+de\s+la\s+comisi[oó]n(?=\s+de\b)",
    re.IGNORECASE,
)
# 'por comisión de' (no article) == 'por la comisión de' — older
# resolutions drop the 'la'
_PRE_COMISION_SIN_LA = re.compile(
    r"\bpor\s+comisi[oó]n(?=\s+de\b)", re.IGNORECASE
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
# historical variant: '• A <subj>, multa por importe de N' and
# '• A <subj> por importe de N euros' — no colon
_SUBJECT_FIRST2_RE = re.compile(
    rf"^[{_BULLETS}\s]*A\s+(.+?)\s*"
    r"(?:,\s*)?(?=(?:una\s+|dos\s+|tres\s+|cuatro\s+|cinco\s+|seis\s+|"
    r"siete\s+|ocho\s+|nueve\s+|diez\s+|"
    r"multa|sanci[oó]n|inhabilitaci|amonestaci|suspensi|restitu|comiso|"
    r"separaci)|"
    r"por\s+importe\s+de|\d[\d.]*\s+euros?)\s*"
    r"((?:una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+)?"
    r"(.*)$",
    re.IGNORECASE | re.DOTALL,
)
# 'Declarar la responsabilidad de <entity>[,] por la comisión de …' —
# historical (2015–2017) operative form: the DECLARATION carries the
# infringement; the sanction is imposed on a successor entity by a
# separate 'Imponer a <successor>, como sucesor…' clause.
_DECLARE_RESP_RE = re.compile(
    rf"^\s*(?:[{_BULLETS}\s]*(?:\d{{1,2}}\s*[.)]\s*)?)*"
    r"Declarar\s+la\s+responsabilidad\s+(?:de|del)\s+(.+?)\s*,?\s*"
    r"(?=por\s+la\s+comisi[oó]n\b)",
    re.IGNORECASE,
)
# 'Imponer a X, una multa…' / 'Imponer a X una multa de:' — sanction
# clause inline in the same paragraph (no 'Por la comisión' anywhere);
# the subject ends where the sanction vocabulary starts.
_IMPOSE_INLINE_SUBJ_RE = re.compile(
    r"Imponer\s+a\s+(.+?)\s*,?\s*(?=(?:una\s+|dos\s+|tres\s+|cuatro\s+|"
    r"cinco\s+|seis\s+|siete\s+|ocho\s+|nueve\s+|diez\s+|la\s+|las\s+|"
    r"los\s+)?(?:multa|sanci[oó]n|inhabilitaci|amonestaci|suspensi|"
    r"restitu|comiso|separaci)\b|\d[\d.]*\s*(?:de\s+)?euros?\b)",
    re.IGNORECASE,
)
# '– 250.000 euros (doscientos cincuenta mil euros), como sucesor en la
# responsabilidad declarada de Caja España.' — bare amount line where
# the sucesor clause selects the declared predecessor; the sanction
# lands on the current Imponer subject.
_AMOUNT_SUCC_LINE_RE = re.compile(
    rf"^[{_BULLETS}\s]*(\d[\d.]*(?:,\d+)?)\s*(?:de\s+)?euros?\s*"
    r"(?:\([^)]*\)\s*)?,?\s*como\s+sucesor[a-z]*\s+en\s+la\s+"
    r"responsabilidad\s+declarad[ao]\s+de\s+(.+?)\s*[.»]?\s*$",
    re.IGNORECASE | re.DOTALL,
)
# 'Bancaja, una multa por importe de un millón (1.000.000 de euros).'
# — bare subject-first fine line (no bullet, no 'A ' prefix) under a
# '…como sucesor en la responsabilidad declarada de:' list header.
_BARE_SUBJ_MULTA_RE = re.compile(
    r"^([A-ZÁÉÍÓÚÑ][^.,;]{2,80}?)\s*,\s*((?:una\s+)?multa\b.*)$",
    re.IGNORECASE | re.DOTALL,
)
# standalone fine clause under an open block: 'Una multa por importe
# de un millón (1.000.000 de euros).' — feeds the tail parser.
# 2006–2007 lettered form: 'b) Una sanción de suspensión…' too.
_BARE_MULTA_LINE_RE = re.compile(
    r"^\s*(?:[{«\"'\-–—−•·●‘’‚„“”}\s]|(?:\d{1,2}|[a-zñ])\s*[.)]\s*)*"
    r"(?:una|la|las|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|"
    r"diez)\s+(?:multa|sanci[oó]n)\b",
    re.IGNORECASE,
)
_SUCC_CLAUSE_RE = re.compile(
    r",?\s*como\s+sucesor[a-z]*\s+en\s+la\s+responsabilidad\s+"
    r"declarad[ao]\s+de\s+(.+?)(?=,\s*(?:una\b|\d)|\s+una\b|\s*,\s*"
    r"(?:la|las|los)\s|\.?\s*$)",
    re.IGNORECASE,
)


def strip_successor_clause(subject: str) -> tuple[str, str | None]:
    """'NCG Banco, S.A., como sucesor en la responsabilidad declarada de
    Caixa Galicia' → ('NCG Banco, S.A.', 'Caixa Galicia')."""
    # trailing '…declarada de(:)' — the predecessor name sits on the
    # NEXT line ('Imponer a BFA…, como sucesor en la responsabilidad
    # declarada de:' colon-list)
    m = re.search(
        r",?\s*como\s+sucesor[a-z]*\s+en\s+la\s+responsabilidad\s+"
        r"declarad[ao]\s+de\s*:?\s*$",
        subject,
        re.IGNORECASE,
    )
    if m:
        return subject[: m.start()].strip(" ,"), None
    m = _SUCC_CLAUSE_RE.search(subject)
    if not m:
        return subject, None
    return subject[: m.start()].strip(" ,"), m.group(1).strip(" ,.")


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
    rf"(?:cada\s+uno\s+de\s+ellos\s*,?\s*|respectivamente\s*,?\s*|"
    rf"(?:en|como)\s+[^,]{{1,90}},\s*|"
    rf"por\s+parte\s+de\s+[^,]{{1,120}}?|"
    rf"por\s+[^,]{{1,90}},\s*)?de\s+"
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
    r"|de\s+las\s+recogidas\s+en\s+(?:el|los|la|las)\s+"
    r"|del?\s+)"
    r"art[ií]culo\s+(?:del?\s+|de\s+la\s+)?(?P<article>\d)",
    re.IGNORECASE,
)
_ARTICLE_TOKEN_RE = re.compile(
    r"\d{1,3}(?:\.[A-Za-z\u00f1\u00d10-9]{1,10})*"
    r"(?:\s+(?:bis|ter|qu[aá]ter|quinquies|sexies|septies|octies|nonies|"
    r"decies|[b-df-hj-np-tv-xzñ](?![a-záéíóúñ])))*(?:\s+\d(?:\.[A-Za-z\u00f1])?)?"
    r"(?:,?\s*letra\s+[a-zñ]\s*\)?\s*(?:bis|ter|qu[aá]ter)?)?"
)
_RELACION_RE = re.compile(r"en\s+relaci[oó]n\s+con\s+", re.IGNORECASE)
_CONDUCT_SPLIT_RE = re.compile(
    r"[,;.]\s*(?:y\s+)?(?:por\s+(?!la\s+que\b|el\s+que\b|los\s+que\b|"
    r"las\s+que\b|lo\s+que\b|l[ao]s?\s+cual\b|tanto\b|consiguiente\b|ello\b|"
    r"ejemplo\b)|al\s+(?:haber|incumplir|realizar|utilizar|no|vulnerar|"
    r"adquirir|comunicar|disponer|transmitir|eludir|omitir|carecer|"
    r"presentar|efectuar|ejecutar|contratar|facilitar|remitir))",
    re.IGNORECASE,
)
# sanction clause at the end of an impose/por-comisión sentence
_SANCTION_TAIL_RE = re.compile(
    r"\b(?:de\s+|la\s+|las\s+|los\s+)?"
    r"(?:siguientes?\s+)?"
    r"(?P<count>una|un|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|\d{1,2})?\s*"
    r"(?P<kind>(?:sanciones?|multas?|sanci[oó]n(?:es)?"
    r"(?:\s*,?\s*a\s+cada\s+un[ao]"
    r"\s+de\s+(?:ellos|ellas|cada\s+una)\s*,?)?|"
    r"inhabilitaci[oó]n(?:es)?|"
    r"amonestaci[oó]n(?:es)?(?:\s+p[uú]blica)?"
    r"(?:\s+con\s+publicaci[oó]n\s+en\s+BOE)?|suspensi[oó]n(?:es)?|"
    r"separaci[oó]n(?:es)?(?:\s+del?\s+cargo)?|confiscaci[oó]n(?:es)?|comiso|"
    r"restituci[oó]n(?:es)?)"
    # 'sanción(es) de amonestación' — the kind may carry a 'de <word>'
    # suffix, but NEVER 'de 500' (that's the amount's 'de')
    r"(?:\s+(?:de|consistente\s+en)\s+[a-záéíóúñ][\w]*)?)\b"
    r"(?P<tail>(?:\.(?=\d)|[^.;])*)",
    re.IGNORECASE,
)
_SANCTION_SPLIT_RE = re.compile(
    # 'y' before a clause lets 'de/la/las/los' prefix the kind
    # ('y de multa', 'y la sanción de multa'); a bare ',' only splits
    # when a kind word directly follows — 'sanción, a cada uno de
    # ellos, de multa…' is ONE clause, not two
    rf"(?:[,;]\s*(?:y\s+)|\s+y\s+)(?=(?:{_COUNT_RE}|\d+)?\s*"
    r"(?:de\s+|la\s+|las\s+|los\s+)?(?:sanci[oó]n(?:es)?\s+de\s+|"
    r"multas?|inhabilitaci[oó]n|amonestaci[oó]n|suspensi[oó]n|"
    r"separaci[oó]n|confiscaci[oó]n|comiso|restituci[oó]n))"
    rf"|[,;]\s+(?=(?:{_COUNT_RE}|\d+)?\s*(?:sanci[oó]n(?:es)?\s+de\s+|"
    r"multas?|inhabilitaci[oó]n|amonestaci[oó]n|suspensi[oó]n|"
    r"separaci[oó]n|confiscaci[oó]n|comiso|restituci[oó]n))"
    # lettered sanction items: 'a) Una multa…' / 'b) Una sanción…'
    # (the kind-word lookahead keeps 'letra b)' legal refs intact)
    rf"|[.:]\s*[a-zñ]\)\s*(?=(?:{_COUNT_RE}|\d+)?\s*(?:sanci[oó]n|"
    r"multas?|inhabilitaci[oó]n|amonestaci[oó]n|suspensi[oó]n|"
    r"separaci[oó]n|confiscaci[oó]n|comiso|restituci[oó]n))",
    re.IGNORECASE,
)
_AMOUNT_RES = [
    # (10.000 €) — parenthesized digits + €
    re.compile(r"\((\d[\d.]*(?:,\d+)?)\s*€\s*\)"),
    # 'seiscientos cincuenta mil (650.000) euros' — written amount +
    # parenthesized digits
    re.compile(r"\((\d[\d.]*(?:,\d+)?)\)\s*(?:de\s+)?euros?", re.IGNORECASE),
    # 5.000.000 (cinco millones) de euros | 5.000.000 de euros |
    # 15.000 (quince mil) euros | 50.000 euros
    re.compile(
        r"(\d[\d.]*(?:,\d+)?)\s*(?:\([^)]*\)\s*)?(?:de\s+)?euros?",
        re.IGNORECASE,
    ),
    re.compile(r"(\d[\d.]*(?:,\d+)?)\s*€", re.IGNORECASE),
    # 'importe de 300.506,05 (trescientos mil quinientos seis con cinco
    # euros)' — comma-decimal, 'euros' only inside the words paren;
    # anchored on 'importe de' so it can't misread dates/refs
    re.compile(
        r"importe\s+de\s+(\d[\d.]*,\d{1,2})\s*\(", re.IGNORECASE
    ),
]
_WORDS_EUROS_RE = re.compile(
    r"([a-záéíóúüñ\s-]{4,60}?)\s*\(?\s*euros?\)?",
    re.IGNORECASE,
)
_DATE_ES = r"\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4}"
_SANCTIONING_RES_RE = re.compile(
    r"Resoluci[oó]n(?:es)?\s+"
    r"(?:del\s+Consejo\s+de\s+la\s+"
    r"(?:CNMV|Comisi[oó]n\s+Nacional\s+del\s+Mercado\s+de\s+Valores"
    r"(?:\s*\(CNMV\))?)\s*,?\s*)?"
    r"de\s+fecha\s+"
    r"((?:" + _DATE_ES + r")(?:\s+y\s+(?:" + _DATE_ES + r"))?)",
    re.IGNORECASE,
)
# 'las sanciones impuestas mediante Resolución de fecha X' — the Consejo
# qualifier is optional; require the 'mediante/impuestas' context to avoid
# matching the publication resolution's own 'Resolución de fecha' (title)
_SANCTIONING_RES_CTX_RE = re.compile(
    r"impuestas?\s+mediante\s+Resoluci[oó]n|impuestas?\s+por\s+(?:la\s+)?"
    r"(?:Comisi[oó]n|Consejo)",
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
# publication-level renunciation: 'habiéndose renunciado … los recursos
# administrativos' — the publication itself states the appeal was waived
_RENUNCIATION_RES = [
    re.compile(r"habi[ée]ndose\s+renunciado", re.IGNORECASE),
    re.compile(r"renunciado\s+a(?:l|\s+interponer|\s+los)", re.IGNORECASE),
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
    # when this sanction pays a DECLARED predecessor's infringement
    # ('250.000 euros, como sucesor … de Caja España') — the declared
    # entity name; the sanction subject stays the successor
    declared_subject: str | None = None


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
    # v0.6 historical grammar:
    # - declared=True → 'Declarar la responsabilidad de X' header
    #   (the block states an infringement, sanctions come later under a
    #   successor 'Imponer')
    # - declared_for → this successor-sanction block references the
    #   declared block's infringement ('como sucesor en la
    #   responsabilidad declarada de <declared subject>')
    declared: bool = False
    declared_for: ParsedBlock | None = None


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
    renunciation_stated: bool = False
    underlying_resolutions: list[str] = field(default_factory=list)
    parse_issues: list[str] = field(default_factory=list)
    document_kind: str = "SANCTION_PUBLICATION"  # | SUBSEQUENT_EVENT | OTHER
    corpus: str = "register_snapshot"  # | historical_backfill
    raw_sha256: str | None = None  # sha256 of the source artifact bytes


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
        # leading role prefix: 'su Presidente, don X' /
        # 'sus Consejeros, don A y don B' → role + name
        m = re.match(
            r"^((?:su|sus)\s+[^,]{2,40}?),\s+((?:don|doña|d\.|dña)\b.+)$",
            chunk,
            re.IGNORECASE,
        )
        if m and re.search(
            r"(?:presidente|consejer|administrador|director|secretari|"
            r"apoderad|delegad|comisari)\b",
            m.group(1),
            re.IGNORECASE,
        ):
            role = m.group(1).strip()
            name = m.group(2).strip()
    if role is None:
        # trailing quoted company affiliation: 'don X, «Kutxabank,
        # S.A.»' — the person represents the company in the organ
        m = re.match(
            r"^((?:don|doña|d\.|dña)\b.+?)\s*,\s*"
            r"([«‘“].+[»’”]|(?:S\.?\s?A\.?|S\.?\s?L\.?|S\.?\s?V\.?|"
            r"S\.?\s?A\.?\s?U\.?)\s*[»’”]?)\s*$",
            chunk,
            re.IGNORECASE,
        )
        if m:
            name, role = m.group(1).strip(), m.group(2).strip()
    if role is None:
        parts = _ROLE_SPLIT_RE.split(chunk, maxsplit=1)
        name = parts[0].strip().rstrip(",")
        role = parts[1].strip().rstrip(",.") if len(parts) > 1 else None
    # procedural boilerplate inside the name position
    name = re.sub(
        r"^(?:los|las|el|la|un|una)?\s*"
        r"(?:consejeros?|administradores?|miembros?|vocales|"
        r"directores?)\b.*?"
        r"(?=don\b|doña\b|d\.\s|dña\b)",
        "",
        name,
        flags=re.IGNORECASE,
    ).strip()
    name = re.sub(
        r",\s*las?\s+siguientes\s+sanciones\s*$",
        "",
        name,
        flags=re.IGNORECASE,
    ).strip()
    return name, role


def split_subjects(raw: str) -> list[str]:
    """'a X, a Y y a Z' or 'X, Y' → subject chunks (names may contain
    commas like 'Gesconsult, SA, SGIIC'). Parenthesized roles are masked
    so ', a la fecha' inside '(…, a la fecha de los hechos)' can never
    split; ' y ' splits only when both sides are multi-word (protects
    entity names like 'Riva y García' and surnames like 'Vidal y Ladrón').
    """
    raw = re.sub(r"^a\s+", "", raw.strip(), flags=re.IGNORECASE)
    parens: list[str] = []

    def _mask_paren(m: re.Match[str]) -> str:
        parens.append(m.group(0))
        return f"\x00{len(parens)-1}\x00"

    masked = re.sub(r"\([^()]*\)", _mask_paren, raw)
    # quoted entity names are atomic too: '«Construcciones y Auxiliar
    # de Ferrocarriles, S.A.»' and '‘‘Fergo Aisa, S. A.’’' contain both
    # ' y ' and ',' inside the quotes — mask them before splitting
    masked = re.sub(r"«[^»]*»|‘[^’]*’|“[^”]*”", _mask_paren, masked)
    parts = re.split(
        r",\s+(?=a\s+|de\s+|el\s+|la\s+|don\b|doña\b|d\.\s|dña\b)|"
        r"\s+y\s+a\s+|\s+e\s+a\s+|"
        r"\s+[ye]\s+(?=sus?\b(?:\s+\S+){0,3}\s*,?\s*(?:don|doña|d\.|dña)\b)|"
        r"\s+[ye]\s+(?=don\b|doña\b|d\.\s|dña\b)",
        masked,
        flags=re.IGNORECASE,
    )
    # 'su Presidente, don X' is ONE subject (role + name) — merge when a
    # chunk ends in a role word and the next starts with a name marker
    _role_end = re.compile(
        r"(?:presidente|vicepresidente|consejer[oa]s?|delegad[oa]s?|"
        r"director[ae]?s?|administrador[ae]?s?|secretari[oa]s?|"
        r"apoderad[oa]s?|comisari[oa]s?|presidenta)\s*$",
        re.IGNORECASE,
    )
    # '(el|los) miembro(s) del Consejo de X' as a whole chunk is a role
    # description of the NEXT subject, not a respondent itself
    _role_chunk = re.compile(
        r"^(?:los|las|el|la|un|una|al|a\s+los|a\s+las)?\s*miembros?"
        r"\s+(?:de[l]?\s+|de\s+la\s+|de\s+su\s+)(?:Consejo|Comit[eé])",
        re.IGNORECASE,
    )
    merged: list[str] = []
    for part in parts:
        if (
            merged
            and re.match(r"(?i)(?:don\b|doña\b|d\.\s|dña\b)", part)
            and _role_end.search(merged[-1].rstrip(","))
        ):
            merged[-1] = merged[-1].rstrip(",") + ", " + part
        elif (
            merged
            and re.match(r"(?i)(?:don\b|doña\b|d\.\s|dña\b)", part)
            and _role_chunk.match(merged[-1].lstrip())
            and not re.search(
                r"\b(?:don|doña|d\.|dña)\b", merged[-1], re.IGNORECASE
            )
        ):
            # drop the role-description chunk into the FIRST name chunk
            merged[-1] = merged[-1].rstrip(",") + ", " + part
        else:
            merged.append(part)
    parts = merged
    out: list[str] = []
    for part in parts:
        # ' y ' between two multi-word chunks is a list boundary —
        # EXCEPT 'don X … y García de los Ríos': a 'y' inside a
        # person's compound surname (right side has no don/doña
        # marker) never splits a name
        subparts = [part]
        for m in re.finditer(r"\s+y\s+", part):
            left, right = part[: m.start()], part[m.end() :]
            person_left = bool(
                re.match(r"(?i)(?:don|doña|d\.|dña)\b", left.strip())
            )
            don_marker = bool(
                re.match(r"(?i)(?:don|doña|d\.|dña|su\b)", right.lstrip())
            )
            # 'don X y Theatre Directorship SARL' — person + entity IS
            # a list; a corporate-form word on the right makes it a
            # join, never a surname continuation
            corp_right = bool(
                re.search(
                    r"\b(?:S\.?\s?A\.?(?:\s?U\.?)?|S\.?\s?L\.?|SARL|"
                    r"GmbH|Ltd|Inc\b|Foundation|Fundaci[oó]n|"
                    r"Sociedad|Compa[ñn][íi]a)\b",
                    right,
                    re.IGNORECASE,
                )
            )
            if (
                len(left.split()) >= 2
                and len(right.split()) >= 2
                # a comma on the left = role/company-form text already
                # present ('Alcalde, Presidente y Consejero Delegado')
                and "," not in left
                # 'y de|y la|y los…' continues an entity name
                # ('Banco Financiero y de Ahorro, S.A.')
                and right[:1].isupper()
                and (don_marker or corp_right or not person_left)
            ):
                subparts = [left, *subparts[1:]]
                subparts.extend(re.split(r"\s+y\s+(?=[A-ZÁÉÍÓÚÑ])", right))
                break
        for sp in subparts:
            p = re.sub(
                r"^a\s+", "", sp.strip().rstrip(","), flags=re.IGNORECASE
            )
            if p:
                for i, text in enumerate(parens):
                    p = p.replace(f"\x00{i}\x00", text)
                # organ-members enumeration: 'los miembros del Consejo
                # de Administración de X: don Ricardo…' → the role
                # header is context; the person after ':' is the
                # respondent (first member carries the fused prefix);
                # 'de su Consejo' (possessive) + 'al miembro' variants
                p = re.sub(
                    r"^(?:los|las|al|a\s+los|a\s+las|el|la|un|una)?\s*"
                    r"miembros?\s+(?:de[l]?\s+|de\s+la\s+|de\s+su\s+)"
                    r"(?:Consejo|Comit[eé])[^:]{5,150}:\s*",
                    "",
                    p,
                    flags=re.IGNORECASE,
                )
                # quote wrappers: '‘‘Fergo Aisa, S. A.’’' — the old
                # BOE doubles single curly quotes around entity names
                p = p.strip(" ‘’‚„“”«»'\"").strip()
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
    # 'sanción, a cada uno de ellos, de multa' → normalize to the
    # object clause before matching
    k = re.sub(
        r",\s*a\s+cada\s+un[ao]\s+de\s+(?:ellos|ellas|cada\s+una)\s*,?",
        "",
        k,
    )
    # 'sanción(es) consistente en multa' / 'las sanciones de multa' →
    # 'multa'
    k = re.sub(
        r"^(?:(?:la|las|los)\s+)?sanci[oó]n(?:es)?\s+"
        r"(?:consistente\s+en|de)\s+",
        "",
        k,
    )
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
    # 'respectivamente' = positional pairing: clause/amount k applies to
    # subject k — never a cross-product
    resp = bool(re.search(r"\brespectivamente\b", zone, re.IGNORECASE))
    pos_i = 0
    for raw_seg in _SANCTION_SPLIT_RE.split(zone):
        seg = raw_seg.strip().lstrip(",;").strip()
        # 'a)'/'b)'/'1.' item prefixes inside the sanction zone
        seg = re.sub(r"^(?:\d{1,2}|[a-zñ])\s*[.)]\s*", "", seg)
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
        # 'una sanción de multa por importe de:' / 'las siguientes
        # sanciones:' — colon-list headers, not sanctions: the items
        # that follow carry the amounts. The bare-kind check covers
        # headers whose ':' was eaten by the item split.
        if (
            amount is None
            and (
                re.search(r"(?:de|sanciones?)\s*:\s*[»’”]?\s*$", seg)
                or re.fullmatch(
                    r"(?:las?|los)?\s*(?:siguientes?\s+)?"
                    r"(?:sanciones?|multas?)\s*"
                    r"(?:de\s+(?:multa|inhabilitaci[oó]n|suspensi[oó]n|"
                    r"separaci[oó]n|amonestaci[oó]n))?\s*[:.]?",
                    seg.strip(),
                    re.IGNORECASE,
                )
            )
        ):
            continue
        duration_raw = None
        dm = re.search(
            r"(por\s+(?:un\s+)?(?:plazo|per[ií]odo)\s+de\s+[^.;]+)",
            tail,
            re.IGNORECASE,
        )
        if dm:
            duration_raw = dm.group(1).strip()
        raw = m.group(0).strip()
        # '…, a don X, por la comisión' — the comisión clause is scope
        # reference, not part of the name
        sm = re.search(
            r"\ba\s+((?:don|doña|d\.|dña|[A-ZÁÉÍÓÚÑ])[^.;]*?)"
            r"(?:\s*,\s*por\s+(?:la\s+)?comisi[oó]n\b.*)?$",
            tail,
        )
        line_subjects = subjects
        if sm and sm.group(1).strip():
            line_subjects = [sm.group(1).strip()]
        if resp and subjects:
            # positional pairing: collect every amount in this clause and
            # pair them in order with the header subjects
            amounts: list[tuple[Decimal | None, str | None]] = []
            for am in re.finditer(
                r"(\d[\d.]*(?:,\d+)?)\s*(?:\([^)]*\)\s*)?(?:de\s+)?euros?",
                tail,
                re.IGNORECASE,
            ):
                n = parse_es_number(am.group(1))
                if n is not None:
                    amounts.append((n, am.group(0).strip()))
            if not amounts:
                amounts = [(amount, amount_raw)]
            for amt, amt_raw in amounts:
                subj = (
                    subjects[pos_i]
                    if pos_i < len(subjects)
                    else subjects[-1]
                )
                pos_i += 1
                ord_ += 1
                lines.append(
                    ParsedSanctionLine(
                        subject_raw=subj,
                        sanction_raw=raw,
                        sanction_type=st,
                        amount=amt,
                        currency="EUR" if amt is not None else None,
                        amount_raw=amt_raw,
                        paragraph_index=paragraph_index,
                        excerpt=excerpt,
                        ordinal=ord_,
                        duration_raw=duration_raw,
                    )
                )
            continue
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
    anchors = list(re.finditer(r"art[ií]culo(?:s)?\s+", segment, re.IGNORECASE))
    seg_norm = normalize_statute(segment)
    # anchored extraction: articles only after 'artículo(s)' — dates and
    # law numbers elsewhere must never become provisions. The statute is
    # resolved PER CHUNK (from this anchor to the next 'artículo') —
    # 'del mismo texto legal' binds only the article it follows.
    for i, anchor in enumerate(anchors):
        pos = anchor.end()
        chunk_end = anchors[i + 1].start() if i + 1 < len(anchors) else len(segment)
        chunk = segment[anchor.start() : chunk_end]
        chunk_norm = normalize_statute(chunk)
        stat_norm: str | None
        stat_raw_use: str | None
        if chunk_norm:
            stat_norm, stat_raw_use = chunk_norm, chunk
        elif _SAME_STATUTE_RE.search(chunk) or _SAME_STATUTE_RE.search(segment):
            stat_norm = default_statute[1]
            stat_raw_use = default_statute[0] or chunk
        else:
            stat_norm = seg_norm or default_statute[1]
            stat_raw_use = segment if seg_norm else (
                default_statute[0] or segment
            )
        # consume an article list: '45, 47 y 48' / '13.2 y 45' / '240 bis'
        while True:
            m = _ARTICLE_TOKEN_RE.match(segment, pos)
            if not m:
                break
            raw = m.group(0)
            # space/dot-letter suffix: '81.2. a)' / '227.1. b)' — same
            # form the typify path already captures
            lt = re.match(
                r"\s*\.?\s*([a-zñ])\s*\)",
                segment[m.end() :],
                re.IGNORECASE,
            )
            if lt:
                raw = f"{raw.rstrip(' .)')}.{lt.group(1).lower()}"
            refs.append(
                LegalReference(
                    statute_raw=stat_raw_use,
                    article_raw=raw,
                    statute_normalized=stat_norm,
                    article_normalized=normalize_article(raw),
                    relation="RELATED",
                )
            )
            pos = m.end() + (lt.end() if lt else 0)
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
        # missing-comma tolerance: accept a count-word + sanction-kind
        # clause directly after name/year/paren text ('… SA una multa
        # por importe de…', '… 2017 multa por importe de…')
        for cand in candidates:
            seg0 = cand.group(0).strip().lower()
            if re.match(
                rf"(?:{_COUNT_RE}|\d{{1,2}})\s+(?:multas?|sanci[oó]n)",
                seg0,
                re.IGNORECASE,
            ):
                zone_start = cand.start()
                break
            before = rest[: cand.start()].rstrip()
            if re.search(r"\d{4}\s*$|\)\s*$", before):
                zone_start = cand.start()
                break
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
            # space/dot-letter suffix: '282.16 c)' / '282.16. a)' / '93. p)'
            lt = re.match(
                r"\s*\.?\s*([a-zñ])\s*\)", head[atok.end() :], re.IGNORECASE
            )
            if lt:
                article_raw = f"{article_raw}.{lt.group(1).lower()}"
                art_end = atok.end() + lt.end()
        after = head[art_end:]
        rel_parts = _RELACION_RE.split(after)
        first_seg = rel_parts[0]
        # cut at the conduct boundary BEFORE normalizing — a statute mention
        # inside the conduct clause must never become the typifying statute;
        # mask '(en la actualidad, … RDL)' equivalents so the successor law
        # is not mistaken for the typifying instrument
        stat_seg = _STATUTE_TAIL_CUT_RE.split(first_seg, maxsplit=1)[0]
        stat_seg = re.sub(
            r"\(en la actualidad[^)]*\)", "", stat_seg, flags=re.IGNORECASE
        )
        sn = normalize_statute(stat_seg)
        if sn or not _SAME_STATUTE_RE.search(first_seg):
            statute_raw = stat_seg.strip().rstrip(",;.").strip() or None
            statute_norm = sn
        # multi-letter typifying refs: '282.16 b) y c)' — the extra
        # letters are additional typified provisions, recorded as related
        if atok:
            for lm in re.finditer(
                r"\s+(?:,|y|e)\s*([a-zñ])\s*\)", after, re.IGNORECASE
            ):
                related.append(
                    LegalReference(
                        statute_raw=statute_raw,
                        article_raw=f"{atok.group(0)}.{lm.group(1)}",
                        statute_normalized=statute_norm,
                        article_normalized=normalize_article(
                            f"{atok.group(0)}.{lm.group(1)}"
                        ),
                        relation="RELATED",
                    )
                )
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
    if m and (
        "Consejo" in m.group(0) or _SANCTIONING_RES_CTX_RE.search(full_text)
    ):
        # plural 'Resoluciones … de fecha A y B' — take the most recent
        last = list(re.finditer(r"\d{1,2}\s+de\s+\w+\s+de\s+\d{4}", m.group(1)))
        pub.sanctioning_resolution_date = parse_long_es(last[-1].group(0))
    pub.administrative_finality = any(r.search(full_text) for r in _FINALITY_RES)
    pub.judicial_review_possible = any(
        r.search(full_text) for r in _JUDICIAL_REVIEW_RES
    )
    pub.administrative_appeal = any(r.search(full_text) for r in _ADMIN_APPEAL_RES)
    pub.renunciation_stated = any(
        r.search(full_text) for r in _RENUNCIATION_RES
    )
    # subsequent-event documents: revocation/rectification/correction of an
    # earlier publication — these are events about a case, not new cases
    if re.search(
        r"se\s+revoca\s+la\s+publicaci[oó]n|se\s+rectifica\s+la\s+publicaci[oó]n|"
        r"correcci[oó]n\s+de\s+errores|se\s+rectifica|se\s+corrige",
        (pub.title or "") + " " + full_text,
        re.IGNORECASE,
    ):
        pub.document_kind = "SUBSEQUENT_EVENT"

    current: ParsedBlock | None = None
    context_subjects: list[str] = []
    sanction_ord = 0
    impose_ord = 0
    # 'Imponer a <succ>, como sucesor en la responsabilidad declarada
    # de:' — the following bare 'X, una multa…' lines each pay one
    # declared predecessor's fine (succ_list mode)
    succ_list: bool = False
    succ_scope: str | None = None
    declaring_name: str | None = None

    def new_blocks(
        para: ParsedParagraph, subjects: list[str], text: str | None = None
    ) -> list[ParsedBlock]:
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
        ) = parse_comision(text if text is not None else para.text)
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

    def _dkey(name: str) -> str:
        return name.lower().strip(" ,").rstrip(".")

    # name -> declared infringement blocks (one per 'La comisión…'
    # item under a colon-scoped declaration)
    declared_blocks: dict[str, list[ParsedBlock]] = {}
    succ_items: list[ParsedBlock] | None = None
    succ_idx: int = 0

    def _link_successor(
        blocks: list[ParsedBlock], declared: dict[str, list[ParsedBlock]]
    ) -> None:
        """'Imponer a <succ>, como sucesor en la responsabilidad
        declarada de <declared>' — the sanction's legal target is the
        DECLARED entity's infringement, not a new one."""
        for b in blocks:
            for s in b.subjects_inline:
                _, pred = strip_successor_clause(s)
                if pred and _dkey(pred) in declared:
                    b.declared_for = declared[_dkey(pred)][-1]

    for para in pub.paragraphs:
        t = para.text
        # normalize historical comision phrasings to the canonical form
        t = _PRE_COMISION_NORM.sub(r"\g<1>Por la comisión de ", t)
        t = _PRE_RESPONSABLE_NORM.sub("por la comisión", t)
        t = _PRE_COMISION_SIN_LA.sub("por la comisión", t)
        # old PDF text extraction breaks words at line wraps:
        # 'artícu-lo 100' — rejoin when the right fragment is 1–2
        # lowercase chars (keeps 'López-García', 'de los' intact)
        t = re.sub(
            r"([a-záéíóúñ]{3,})-([a-záéíóúñ]{1,2}\b)", r"\1\2", t
        )
        # 'tipificada en la letra o) artículo 99' — 2010–2012 and
        # 'la letra n) del artículo 100' — 2006: reversed letter/
        # article order → normalize to 'artículo 99, letra o)'
        t = re.sub(
            r"letra\s+([a-zñ])\s*\)\s*(del?\s+|de\s+la\s+)?"
            r"art[ií]culo\s+(\d{1,3})",
            r"\2artículo \3, letra \1)",
            t,
            flags=re.IGNORECASE,
        )
        # 'Declarar que X (…), ha incurrido en la comisión de …' — same
        # responsibility declaration, alternate surface form
        dcl_que = re.match(
            rf"^(?:[{_BULLETS}\s]|\d{{1,2}}\s*[.)]\s*)*Declarar\s+que\s+"
            r"(.+?)\s*(?:\([^)]*\)\s*,?\s*)+"
            r"ha\s+incurrido\s+en\s+la\s+comisi[oó]n\b",
            t,
            re.IGNORECASE,
        )
        if dcl_que:
            subs = split_subjects(dcl_que.group(1))
            # match ends after 'comisión' — the remainder is
            # ' de una infracción…' → canonical 'Por la comisión de…'
            ctx = "Por la comisión" + t[dcl_que.end() :]
            blocks = new_blocks(para, subs, ctx)
            pub.blocks.extend(blocks)
            for b in blocks:
                b.declared = True
                for s in subs:
                    declared_blocks.setdefault(_dkey(s), []).append(b)
            current = blocks[-1]
            continue
        dcl = re.match(
            rf"^(?:[{_BULLETS}\s]|\d{{1,2}}\s*[.)]\s*)*"
            r"Declarar\s+la\s+responsabilidad\s+(?:de|del)\s+(.+?)\s*,?\s*"
            r"(?=por\s+la\s+comisi[oó]n\b)",
            t,
            re.IGNORECASE,
        )
        if dcl:
            # 'Declarar la responsabilidad de X, por la comisión de …'
            # — the infringement is stated here; the sanction on the
            # successor arrives under a separate 'Imponer' para.
            subs = split_subjects(dcl.group(1))
            # the regex stops before 'por la comisión' (lookahead) —
            # the remainder IS the canonical comision clause
            ctx = "Por " + t[dcl.end():].lstrip(" ,").removeprefix("por ")
            blocks = new_blocks(para, subs, ctx)
            pub.blocks.extend(blocks)
            for b in blocks:
                b.declared = True
                for s in subs:
                    declared_blocks.setdefault(_dkey(s), []).append(b)
            current = blocks[-1]
            continue
        if _IMPOSE_START_RE.match(t):
            declaring_name = None
            succ_scope = None
            succ_items = None
            subj_part = ""
            cm = _COMISION_RE.search(t)
            if cm:
                subj_part = t[: cm.start()]
            else:
                # 'N. Imponer a X (en liquidación):' — subjects-only
                # header ending in ':'; the '– Por la comisión' bullets
                # that follow inherit these subjects (no own block)
                if re.match(
                    rf"^(?:[{_BULLETS}\s]|\d{{1,2}}\s*[.)]\s*)*"
                    r"Imponer\s+a\s+.+[:.]\s*[»’”]?\s*$",
                    t,
                    re.IGNORECASE | re.DOTALL,
                ) and not re.search(
                    r"multa|sanci[oó]n|inhabilitaci|amonestaci|"
                    r"suspensi|restitu|comiso|separaci|"
                    # 'como sucesor en la responsabilidad declarada
                    # de:' ALSO ends with ':' — but it opens the
                    # successor colon-list (handled below), not a
                    # subjects-only header
                    r"como\s+sucesor",
                    t,
                    re.IGNORECASE,
                ):
                    sm4 = re.search(
                        r"Imponer\s+a\s+(.+?)\s*[:.]\s*[»’”]?\s*$",
                        t,
                        re.IGNORECASE | re.DOTALL,
                    )
                    if sm4:
                        hdr_subj = re.sub(
                            r",?\s*por\s+(?:la\s+)?comisi[oó]n\b.*$",
                            "",
                            sm4.group(1),
                            flags=re.IGNORECASE,
                        )
                        subs = split_subjects(hdr_subj)
                        if subs:
                            context_subjects = subs
                    continue
                # inline sanction: 'Imponer a X, una multa por importe de
                # N' — subject ends at the sanction marker (historical
                # compact form); the para text stays as the tail
                if _IMPOSE_INLINE_SUBJ_RE.search(t):
                    sm3 = _IMPOSE_INLINE_SUBJ_RE.search(t)
                    subs = split_subjects(sm3.group(1)) if sm3 else []
                    if subs:
                        context_subjects = subs
                    blocks = new_blocks(para, subs, t)
                    pub.blocks.extend(blocks)
                    current = blocks[-1]
                    _link_successor(blocks, declared_blocks)
                    continue
                # 'Imponer a X:' / 'Imponer a X, por:' / 'Imponer a X, por
                # la comisión:' subjects-only headers
                sm = re.match(
                    rf"^\s*(?:\d{{1,2}}\s*[.)]\s*)?[{_BULLETS}\s]*"
                    r"Imponer\s+a\s+(.+?)"
                    r"(?:,?\s*por\s+(?:la\s+comisi[oó]n\s*)?)?[:.]?\s*$",
                    t,
                    re.IGNORECASE,
                )
                if sm:
                    context_subjects = split_subjects(sm.group(1))
                    succ_list = bool(
                        re.search(r"declarad[ao]\s+de\s*:\s*$", t, re.I)
                    )
                    current = None
                    continue
            subs = []
            # 'Imponer a X una multa, por la comisión…' — the sanction
            # clause PRECEDES 'por la comisión': strip it from the
            # subject; the amount sits in the trailing 'por un
            # importe de … (N euros)'
            pre_multa = False
            if subj_part:
                sm2 = re.search(
                    r"Imponer\s+al?\s+(.+?)\s*,?\s*"
                    r"(?=(?:una|un|dos|tres|cuatro|cinco|la|las|los)\s+"
                    r"(?:multa|sanci[oó]n|inhabilitaci|amonestaci|"
                    r"suspensi|restitu|comiso|separaci)\b|"
                    r"por\s+la\s+comisi[oó]n\b|$)",
                    subj_part,
                    re.IGNORECASE | re.DOTALL,
                )
                if sm2:
                    subs = split_subjects(sm2.group(1))
                    pre_multa = bool(
                        re.search(
                            r"(?:una|un|la|las)\s+(?:multa|sanci[oó]n|"
                            r"inhabilitaci|amonestaci|suspensi|restitu|"
                            r"comiso|separaci)\b",
                            subj_part[sm2.end() :],
                            re.IGNORECASE,
                        )
                    )
            if subs:
                context_subjects = subs
            # pass the PRE-normalized text — 'por comisión'/'como
            # responsable' variants must reach parse_comision too
            blocks = new_blocks(para, subs, t)
            if pre_multa and blocks:
                # the fine is the 'por un importe de …' clause at the
                # end of the comisión period
                mm = re.search(
                    r"por\s+un?\s+importe\s+de\s+[^.]{3,80}?"
                    r"\(\s*\d[\d.]*\s*(?:de\s+)?euros?\s*\)|"
                    r"por\s+un?\s+importe\s+de\s+\d[\d.]*\s*"
                    r"(?:de\s+)?euros?",
                    t,
                    re.IGNORECASE,
                )
                if mm:
                    block = blocks[-1]
                    n0 = len(block.sanctions)
                    block.sanctions.extend(
                        parse_sanction_tail(
                            "una multa " + mm.group(0),
                            subs or [""],
                            para.index,
                            para.text,
                            sanction_ord + n0,
                        )
                    )
                    sanction_ord += len(block.sanctions) - n0
            pub.blocks.extend(blocks)
            current = blocks[-1]
            _link_successor(blocks, declared_blocks)
            continue
        # 'A Pescanova, S.A., por la comisión de …; una multa…' —
        # subject-first sanction items under a 'N. Resolución… acordó
        # imponer las siguientes sanciones:' list (historical form);
        # 2010–2014 variants are numbered '1. A X,…' / '2. A los
        # miembros…: don X, don Y…' / '3. Al miembro…'
        m_asi = re.match(
            rf"^(?:[{_BULLETS}\s]|\d{{1,2}}\s*[.)]\s*)*"
            r"A(?:l|l?os|l?as)?\s+(.+?)\s*,\s*"
            r"(?=por\s+la\s+comisi[oó]n\b)",
            t,
            re.IGNORECASE | re.DOTALL,
        )
        if m_asi:
            subs = split_subjects(m_asi.group(1))
            ctx = "Por " + t[m_asi.end() :].lstrip(" ,").removeprefix("por ")
            blocks = new_blocks(para, subs, ctx)
            pub.blocks.extend(blocks)
            current = blocks[-1]
            continue
        # 'Declarar la responsabilidad de X por:' — colon-scoped
        # declaration: the 'La comisión…' bullets that follow are the
        # declared infringement(s) owned by X
        mdcl = re.match(
            rf"^(?:[{_BULLETS}\s]|\d{{1,2}}\s*[.)]\s*)*"
            r"Declarar\s+la\s+responsabilidad\s+(?:de|del)\s+"
            r"(.+?)\s*por\s*:\s*[»’”]?\s*$",
            t,
            re.IGNORECASE | re.DOTALL,
        )
        if mdcl:
            declaring_name = mdcl.group(1).rstrip(".» ").strip()
            continue
        # '1. Como sucesor en la responsabilidad declarada de X por:'
        # — successor-scope opener under 'Imponer a <succ>:'; the
        # following 'La Comisión de una infracción…' block binds the
        # declared predecessor's infringement
        msuc = re.match(
            rf"^(?:[{_BULLETS}\s]|\d{{1,2}}\s*[.)]\s*)*"
            r"Como\s+sucesor[a-z]*\s+en\s+la\s+responsabilidad\s+"
            r"declarad[ao]\s+de\s+(.+?)\s*por\s*:\s*[»’”]?\s*$",
            t,
            re.IGNORECASE | re.DOTALL,
        )
        if msuc:
            succ_scope = msuc.group(1).rstrip(".» ").strip()
            succ_items = declared_blocks.get(_dkey(succ_scope), [])
            succ_idx = 0
            continue
        # '2. Como responsable de:' — the successor's OWN-responsibility
        # scope (no named predecessor): binds to the subject's own
        # declared block
        if re.match(
            rf"^(?:[{_BULLETS}\s]|\d{{1,2}}\s*[.)]\s*)*"
            r"Como\s+responsable\s+de\s*:\s*[»’”]?\s*$",
            t,
            re.IGNORECASE,
        ):
            succ_scope = context_subjects[0] if context_subjects else None
            succ_items = (
                declared_blocks.get(_dkey(succ_scope), [])
                if succ_scope else []
            )
            succ_idx = 0
            continue
        if re.match(
            rf"^(?:[{_BULLETS}\s]|\d{{1,2}}\s*[.)]\s*)*"
            r"Y\s+(?:por|de)\s+la\s+[Cc]omisi[oó]n\b",
            t,
        ):
            t = re.sub(r"^(?:Y|y)\s+(?:por|de)\s+la", "Por la", t)
        if _POR_COMISION_BULLET_RE.match(t):
            # standalone infringement+sanction bullet; inherits header subject
            blocks = new_blocks(para, context_subjects, t)
            pub.blocks.extend(blocks)
            current = blocks[-1]
            # 'Declarar la responsabilidad de X por:' scope — these
            # bullets are the declared infringement(s) of X
            if declaring_name:
                current.declared = True
                declared_blocks.setdefault(_dkey(declaring_name), []).append(current)
            # 'N. Como sucesor … de X por:' / 'Como responsable de:'
            # opened successor scope — link this block's infringement
            # to the declared predecessor (scope persists across the
            # numbered items until the next Imponer/ordinal header)
            if succ_items:
                current.declared_for = succ_items[
                    min(succ_idx, len(succ_items) - 1)
                ]
                succ_idx += 1
            continue
        # 'Bancaja, una multa por importe de un millón (…).' — a bare
        # subject-first fine under a 'como sucesor … declarada de:'
        # list: the fine lands on the successor (context_subjects),
        # the named entity is the DECLARED predecessor
        if succ_list and context_subjects:
            mbare = _BARE_SUBJ_MULTA_RE.match(t)
            if mbare:
                pred_name = mbare.group(1).strip()
                seg = mbare.group(2).strip()
                amount, amount_raw = parse_amount(seg)
                sanction_ord += 1
                if current is None:
                    # host block for the list — severity/statute come
                    # from the declared block it succeeds
                    blocks = new_blocks(para, context_subjects, "")
                    pub.blocks.extend(blocks)
                    current = blocks[-1]
                current.sanctions.append(
                    ParsedSanctionLine(
                        subject_raw=context_subjects[0],
                        sanction_raw=seg,
                        sanction_type=SanctionType.MONETARY_FINE,
                        amount=amount,
                        currency="EUR" if amount is not None else None,
                        amount_raw=amount_raw,
                        paragraph_index=para.index,
                        excerpt=t,
                        ordinal=sanction_ord,
                        declared_subject=pred_name,
                    )
                )
                continue
        if current is None:
            if (
                para.css_class == "parrafo"
                and t[:1] in _BULLETS
                and re.match(
                    r"(?i)(?:a\s+|multa|sanción|suspensión|inhabilitación|"
                    r"amonestación|restitución|comiso)",
                    t.lstrip(_BULLETS).lstrip(),
                )
            ):
                pub.parse_issues.append(
                    f"sanction-like bullet outside any impose block "
                    f"(para {para.index}): {t[:80]}"
                )
            continue
        # '– 250.000 euros (…), como sucesor en la responsabilidad
        # declarada de X.' — amount line; the fine lands on the open
        # block's subject, bound to predecessor X's declaration
        msucc = _AMOUNT_SUCC_LINE_RE.match(t)
        if msucc:
            n = parse_es_number(msucc.group(1))
            sanction_ord += 1
            current.sanctions.append(
                ParsedSanctionLine(
                    subject_raw=(
                        context_subjects[0] if context_subjects else ""
                    ),
                    sanction_raw=t.lstrip(_BULLETS).strip(),
                    sanction_type=SanctionType.MONETARY_FINE,
                    amount=n,
                    currency="EUR" if n is not None else None,
                    amount_raw=msucc.group(1) + " euros",
                    paragraph_index=para.index,
                    excerpt=t,
                    ordinal=sanction_ord,
                    declared_subject=msucc.group(2).rstrip(".» ").strip(),
                )
            )
            continue
        # standalone fine clause under an open block: 'Una multa por
        # importe de un millón (1.000.000 de euros).'
        if _BARE_MULTA_LINE_RE.match(t):
            lines = parse_sanction_tail(
                t, context_subjects, para.index, t, sanction_ord
            )
            current.sanctions.extend(lines)
            sanction_ord += len(lines)
            continue
        # subject-first bullet: '– A <subj>: <sanction>' or historical
        # '• A <subj>[, multa] por importe de N euros' (no colon)
        msubj = _SUBJECT_FIRST_RE.match(t)
        msubj2 = None if msubj else _SUBJECT_FIRST2_RE.match(t)
        if msubj or msubj2:
            if msubj:
                line_subjects = [msubj.group(1).strip()]
                tail_txt = msubj.group(2)
            elif msubj2:
                line_subjects = (
                    split_subjects(msubj2.group(1)) or [msubj2.group(1).strip()]
                )
                tail_txt = (
                    (msubj2.group(2) or "") + " " + msubj2.group(3)
                ).strip()
            else:  # pragma: no cover
                line_subjects, tail_txt = [], ""
            st, amt, amt_raw, dur = _line_sanction(tail_txt)
            for subj in line_subjects:
                sanction_ord += 1
                current.sanctions.append(
                    ParsedSanctionLine(
                        subject_raw=subj,
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
                # 'a X' inside a descriptive clause is dative, not the
                # sanction addressee ('venta de opciones … a Deutsche
                # Bank, tanto los denominados …'). Reject captures that
                # run into clause text or are implausibly long.
                if (
                    emb
                    and emb.group(1)
                    and not emb.group(1).strip().endswith(
                        ("de", "del", "para", "por")
                    )
                    and len(emb.group(2)) <= 90
                    and not re.search(
                        r"tanto\s+los|como\s+aquell|por\s+un\s+plazo|"
                        r"que\s+incluy|denominad|funcionamiento|"
                        r"naturaleza|emitidos",
                        emb.group(2),
                        re.IGNORECASE,
                    )
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
        if re.match(r"^\s*\d{1,2}\.\s*(?:Resoluci[oó]n|Orden\b|Acuerdo\b)", t):
            pub.underlying_resolutions.append(t)
            continue
        # 'Declarar que X …' — an operative declaration (obligations,
        # determinations), not a responsibility attribution: consume as
        # a documented act, never a sanction
        if re.match(
            rf"^[{_BULLETS}\s]*Declarar\s+(?:que|al|a\s+la|a\s+los|"
            r"los|las)\b",
            t, re.IGNORECASE,
        ) and not _DECLARE_RESP_RE.match(t):
            pub.underlying_resolutions.append(t)
            continue
        # lettered or bulleted conduct items under an open block:
        # 'a) La comercialización…' / '• No gestionar…' — conduct detail
        # belonging to the block; never a respondent, never an issue
        mlet = re.match(
            r"^\s*(?:([a-f])\)|[•·●\-–—])\s*(.+)$", t, re.IGNORECASE
        )
        if mlet and current is not None:
            item = mlet.group(2).strip()
            current.conduct_raw = (
                (current.conduct_raw + " " + item).strip()
                if current.conduct_raw
                else item
            )
            # lettered items often carry the real conduct dates —
            # merge them into the conduct window
            cs, ce, cp = extract_conduct_period(item)
            if cs and (current.conduct_start is None or cs < current.conduct_start):
                current.conduct_start = cs
            if ce and (current.conduct_end is None or ce > current.conduct_end):
                current.conduct_end = ce
            if cp == "day":
                current.conduct_precision = "day"
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
        # chain-head inheritance: 'art. 99.i, en relación con el art.
        # 83 ter 1., de la Ley 24/1988' — the chain's first statute
        # governs the typified article too
        if b.statute_normalized is None:
            for r in b.related:
                if r.statute_normalized:
                    b.statute_normalized = r.statute_normalized
                    if not b.statute_raw or b.statute_raw == ")":
                        b.statute_raw = r.statute_raw
                    break
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
