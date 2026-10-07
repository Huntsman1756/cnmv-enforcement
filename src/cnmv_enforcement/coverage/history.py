"""Historical coverage matrix — per-period enumeration/accounting.

The artifact is a pure projection of the frozen enumeration manifests +
the built dataset: every number is derivable and auditable. It answers
"for period P: what was enumerated, downloaded, classified, parsed and
reviewed — and what limits are declared", never "coverage is complete".
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class PeriodCoverage:
    period: str  # '2015' or '2021-10-02..2021-11-17'
    enumeration_method: str = "boe_sumario_dept1040"
    enumeration_status: str = "ENUMERATED"
    days_enumerated: int = 0
    enumeration_errors: int = 0
    documents_enumerated: int = 0
    sanction_like_items: int = 0
    documents_downloaded: int = 0
    documents_failed: int = 0
    sanction_publications: int = 0
    subsequent_events: int = 0
    corrections: int = 0
    other_documents: int = 0
    cases: int = 0
    respondents: int = 0
    sanctions: int = 0
    infringements: int = 0
    review_items: int = 0
    inconclusive_items: int = 0
    identifier_manifest_sha256: str = ""
    coverage_status: str = "UNVERIFIED"
    limitations: list[str] = field(default_factory=list)


def _classify(title: str, sanction_like: bool) -> str:
    tl = title.lower()
    if "rectificaci" in tl or "corrección de errores" in tl:
        return "CORRECTION"
    if sanction_like:
        return "SANCTION_PUBLICATION"
    return "OTHER"


def build_history_matrix(
    manifests: dict[str, Path],
    downloaded_ids: dict[str, set[str]],
) -> list[PeriodCoverage]:
    """manifests: period → JSONL path; downloaded_ids: period → the
    BOE ids present in the corpus dir for that period."""
    out: list[PeriodCoverage] = []
    for period, path in sorted(manifests.items()):
        pc = PeriodCoverage(period=period)
        ids: list[str] = []
        seen_err = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            pc.days_enumerated += 1
            if "error" in d:
                seen_err += 1
            for it in d.get("items", []):
                bid = it["boe_id"]
                ids.append(bid)
                pc.documents_enumerated += 1
                kind = _classify(
                    it.get("title", ""), bool(it.get("sanction_like"))
                )
                if kind == "SANCTION_PUBLICATION":
                    pc.sanction_publications += 1
                    pc.sanction_like_items += 1
                elif kind == "CORRECTION":
                    pc.corrections += 1
                else:
                    pc.other_documents += 1
        pc.enumeration_errors = seen_err
        dl = downloaded_ids.get(period, set())
        pc.documents_downloaded = sum(1 for i in ids if i in dl)
        # failures = sanction-like ids enumerated but not downloaded
        got = {i for i in ids if i in dl}
        pc.documents_failed = sum(
            1
            for line in path.read_text(encoding="utf-8").splitlines()
            for it in json.loads(line).get("items", [])
            if it.get("sanction_like") and it["boe_id"] not in got
        )
        pc.identifier_manifest_sha256 = hashlib.sha256(
            ("\n".join(sorted(ids))).encode()
        ).hexdigest()
        pc.coverage_status = (
            "REPRODUCIBLY_ENUMERATED"
            if pc.sanction_publications == 0 or pc.documents_failed == 0
            else "PARTIAL"
        )
        out.append(pc)
    return out


def matrix_json(periods: list[PeriodCoverage]) -> str:
    return json.dumps([asdict(p) for p in periods], indent=1, ensure_ascii=False)
