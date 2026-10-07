"""CNMV public sanctions register — observed snapshot collector.

The register is a server-rendered paginated table (5 rows/page,
``?page=N`` 0-indexed, ``Página X de Y`` pager). There is no public list
API and no declared total ⇒ enumeration status is
``COMPLETE_OBSERVED_SNAPSHOT``, never ``VERIFIED_REPRODUCIBLE_ENUMERATION``.

Structural integrity rules (fail loudly, never silently truncate):

- every page must render the table;
- every row must carry a ``verdocumento`` document link;
- the walked pages must equal ``pager_total``;
- total rows = ``(last_page_index × rows_per_page) + rows_on_last_page``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from cnmv_enforcement.config import CNMV_REGISTER_URL
from cnmv_enforcement.parsing.dates import parse_long_es, parse_slash_es
from cnmv_enforcement.parsing.text import collapse_ws
from cnmv_enforcement.sources.http import FetchResult, HttpClient

log = logging.getLogger("cnmv_enforcement.cnmv.register")

_PAGER_RE = re.compile(r"Página\s+(\d+)\s+de\s+(\d+)")
_TABLE_ID = "ctl00_ContentPrincipal_grdRegSanciones"
ROWS_PER_PAGE = 5
_BOE_DATE_RE = re.compile(
    r"\(BOE\s+(?:de[l]?\s+)?(\d{1,2}\s+de\s+\w+\s+de\s+\d{4})\s*\)",
    re.IGNORECASE,
)


class RegisterIntegrityError(Exception):
    pass


@dataclass
class RegisterRow:
    register_entry_date: date | None
    title: str
    document_url: str
    boe_date: date | None = None
    page_index: int = 0


@dataclass
class RegisterSnapshot:
    rows: list[RegisterRow] = field(default_factory=list)
    declared_pages: int = 0
    observed_at_pages: list[FetchResult] = field(default_factory=list)


def parse_register_page(html: str, page_index: int) -> tuple[list[RegisterRow], int]:
    """Parse one register page → (rows, declared_total_pages)."""
    tree = HTMLParser(html)
    table = tree.css_first(f"#{_TABLE_ID}")
    if table is None:
        raise RegisterIntegrityError(
            f"page {page_index}: register table #{_TABLE_ID} not found"
        )
    declared = 0
    m = _PAGER_RE.search(tree.text())
    if m:
        declared = int(m.group(2))
    rows: list[RegisterRow] = []
    for tr in table.css("tr"):
        tds = tr.css("td")
        if len(tds) < 2:
            continue
        link = tr.css_first("a[href*='verdocumento']")
        if link is None:
            raise RegisterIntegrityError(
                f"page {page_index}: row without verdocumento link"
            )
        entry_date_txt = collapse_ws(tds[0].text())
        title = collapse_ws(tds[1].text())
        boe_m = _BOE_DATE_RE.search(title)
        boe_date = None
        if boe_m:
            boe_date = parse_long_es(boe_m.group(1))
        rows.append(
            RegisterRow(
                register_entry_date=parse_slash_es(entry_date_txt),
                title=title,
                document_url=link.attributes.get("href", ""),
                boe_date=boe_date,
                page_index=page_index,
            )
        )
    return rows, declared


def collect_register(client: HttpClient) -> RegisterSnapshot:
    """Walk all pages of the register and return the observed snapshot."""
    snap = RegisterSnapshot()
    first = client.get(f"{CNMV_REGISTER_URL}?lang=es&page=0")
    snap.observed_at_pages.append(first)
    rows, declared = parse_register_page(first.content.decode("utf-8"), 0)
    snap.rows.extend(rows)
    snap.declared_pages = declared
    if declared <= 0:
        raise RegisterIntegrityError("pager 'Página X de N' not found on page 0")
    for page in range(1, declared):
        res = client.get(f"{CNMV_REGISTER_URL}?lang=es&page={page}")
        snap.observed_at_pages.append(res)
        page_rows, _page_declared = parse_register_page(
            res.content.decode("utf-8"), page
        )
        if not page_rows:
            raise RegisterIntegrityError(f"page {page}: zero rows")
        snap.rows.extend(page_rows)
    # integrity: every full page must have ROWS_PER_PAGE rows; the last page
    # may be partial but non-empty. A missing row means a truncated walk.
    by_page: dict[int, int] = {}
    for r in snap.rows:
        by_page[r.page_index] = by_page.get(r.page_index, 0) + 1
    for page in range(declared):
        count = by_page.get(page, 0)
        if page < declared - 1 and count != ROWS_PER_PAGE:
            raise RegisterIntegrityError(
                f"page {page}: {count} rows, expected {ROWS_PER_PAGE}"
            )
        if count == 0:
            raise RegisterIntegrityError(f"page {page}: zero rows")
    derived_total = (declared - 1) * ROWS_PER_PAGE + by_page[declared - 1]
    if len(snap.rows) != derived_total:
        raise RegisterIntegrityError(
            f"row count {len(snap.rows)} != derived total {derived_total}"
        )
    log.info("register snapshot: %d rows across %d pages", len(snap.rows), declared)
    return snap
