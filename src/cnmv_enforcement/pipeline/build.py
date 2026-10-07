"""Deterministic corpus build: corpus XMLs → parse → assemble → tables.

Every input is an immutable bytes artifact; ordering is stable; the same
inputs always produce the same dataset.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from cnmv_enforcement.domain.bundle import CaseBundle
from cnmv_enforcement.parsing.assemble import assemble_case
from cnmv_enforcement.parsing.boe_publication import (
    ParsedPublication,
    parse_publication_xml,
)


@dataclass
class BuildResult:
    bundles: list[CaseBundle] = field(default_factory=list)
    publications: list[ParsedPublication] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    built_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def build_corpus(
    corpus_dir: Path,
    *,
    register_snapshot: dict | None = None,
    observed_at: datetime | None = None,
) -> BuildResult:
    """Parse every ``BOE-A-*.xml`` in corpus_dir and assemble CaseBundles.

    ``index.json`` (written by fetch) supplies register metadata per doc;
    files are processed in sorted order for determinism.
    """
    obs = observed_at or datetime.now(UTC)
    index: dict[str, dict] = {}
    index_path = corpus_dir / "index.json"
    if index_path.exists():
        for item in json.loads(index_path.read_text(encoding="utf-8")):
            index[item["boe_id"]] = item

    result = BuildResult(built_at=obs)
    for xml_path in sorted(corpus_dir.glob("BOE-A-*.xml")):
        boe_id = xml_path.stem
        meta = index.get(boe_id, {})
        try:
            pub = parse_publication_xml(xml_path.read_bytes())
        except Exception as exc:  # hard parse failure — recorded, not silent
            result.issues.append(
                {"boe_id": boe_id, "kind": "PARSE_FAILED", "detail": str(exc)}
            )
            continue
        result.publications.append(pub)
        for issue in pub.parse_issues:
            result.issues.append(
                {"boe_id": boe_id, "kind": "PARSE_ISSUE", "detail": issue}
            )
        if not pub.blocks:
            result.issues.append(
                {"boe_id": boe_id, "kind": "NO_INFRINGEMENTS_PARSED", "detail": ""}
            )
        register_date = meta.get("register_entry_date")
        bundle = assemble_case(
            pub,
            document_id=f"boe-xml:{boe_id}",
            observed_at=obs,
            register_entry_date=(
                date.fromisoformat(register_date) if register_date else None
            ),
            fallback_key=meta.get("title", ""),
        )
        result.bundles.append(bundle)
    return result
