"""Resolve a CNMV register row to its canonical ``BOE-A-*`` identifier.

Strategy (proven 91/91 by prior art): the register title ends in
``(BOE de D de <month> de YYYY)``. Fetch that day's sumario, take
departamento-1040 items, match by normalized title — exact after stripping
the ``(BOE …)`` suffix; fallback token-set Jaccard ≥ 0.85 with a unique
winner (same-day resolutions share boilerplate prefixes, so prefix
matching is unsafe).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from cnmv_enforcement.config import BOE_DEPARTAMENTO_CODIGO
from cnmv_enforcement.parsing.text import normalize_key
from cnmv_enforcement.sources.boe.sumario import SumarioItem
from cnmv_enforcement.sources.cnmv.register import RegisterRow

log = logging.getLogger("cnmv_enforcement.boe.resolve")

_BOE_SUFFIX_RE = re.compile(r"\s*\(BOE[^)]*\)\s*\.?\s*$", re.IGNORECASE)
_JACCARD_MIN = 0.85


class ResolveError(Exception):
    pass


def title_key(title: str) -> str:
    t = _BOE_SUFFIX_RE.sub("", title)
    return normalize_key(t).rstrip(".")


def _token_set(t: str) -> set[str]:
    return set(t.split())


def jaccard(a: str, b: str) -> float:
    sa, sb = _token_set(a), _token_set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


@dataclass
class Resolution:
    row: RegisterRow
    boe_id: str | None
    method: str  # EXACT | JACCARD | UNRESOLVED
    score: float = 0.0


def resolve_row(row: RegisterRow, day_items: list[SumarioItem]) -> Resolution:
    key = title_key(row.title)
    cands = list(cnmv_items_like(day_items))
    # exact normalized-title match
    exact = [i for i in cands if title_key(i.titulo) == key]
    if len(exact) == 1:
        return Resolution(row, exact[0].identificador, "EXACT", 1.0)
    if len(exact) > 1:
        # shouldn't happen — same title twice in one day; take none silently
        return Resolution(row, None, "UNRESOLVED", 0.0)
    # jaccard fallback, unique winner required
    scored = sorted(
        ((jaccard(key, title_key(i.titulo)), i) for i in cands),
        key=lambda t: t[0],
        reverse=True,
    )
    if scored and scored[0][0] >= _JACCARD_MIN and (
        len(scored) == 1 or scored[0][0] > scored[1][0]
    ):
        return Resolution(
            row, scored[0][1].identificador, "JACCARD", scored[0][0]
        )
    return Resolution(row, None, "UNRESOLVED", scored[0][0] if scored else 0.0)




def cnmv_items_like(items: list[SumarioItem]) -> list[SumarioItem]:
    """Dept-1040 items only (already filtered upstream, defensive)."""
    return [i for i in items if i.departamento_codigo == BOE_DEPARTAMENTO_CODIGO]
