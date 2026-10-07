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
    corpus_dir: Path | list[Path],
    *,
    register_snapshot: dict | None = None,
    observed_at: datetime | None = None,
) -> BuildResult:
    """Parse every ``BOE-A-*.xml`` in the corpus dir(s) and assemble
    CaseBundles. Multiple dirs = multiple corpora (register snapshot +
    historical backfill); the corpus label lands on each publication for
    coverage accounting.
    """
    obs = observed_at or datetime.now(UTC)
    dirs = [corpus_dir] if isinstance(corpus_dir, Path) else list(corpus_dir)
    index: dict[str, dict] = {}
    xml_paths: list[Path] = []
    for d in dirs:
        index_path = d / "index.json"
        if index_path.exists():
            for item in json.loads(index_path.read_text(encoding="utf-8")):
                index[item["boe_id"]] = item
        xml_paths.extend(sorted(d.glob("BOE-A-*.xml")))
    xml_paths.sort(key=lambda p: (p.parent.name, p.name))

    result = BuildResult(built_at=obs)
    seen: set[str] = set()
    for xml_path in xml_paths:
        boe_id = xml_path.stem
        meta = index.get(boe_id, {})
        if boe_id in seen:
            result.issues.append(
                {
                    "boe_id": boe_id,
                    "kind": "DUPLICATE_CORPUS_ENTRY",
                    "detail": f"skipped second copy in {xml_path.parent}",
                }
            )
            continue
        seen.add(boe_id)
        try:
            raw = xml_path.read_bytes()
            pub = parse_publication_xml(raw)
            import hashlib

            pub.raw_sha256 = hashlib.sha256(raw).hexdigest()
        except Exception as exc:  # hard parse failure — recorded, not silent
            result.issues.append(
                {"boe_id": boe_id, "kind": "PARSE_FAILED", "detail": str(exc)}
            )
            continue
        result.publications.append(pub)
        pub.corpus = {
            "corpus": "register_snapshot",
            "corpus_h1_dev": "h1_2015_2017_dev",
            "corpus_h2_dev": "h2_2010_2014_dev",
            "corpus_h1_holdout": "h1_2015_2017_holdout",
        }.get(xml_path.parent.name, "historical_backfill")
        if pub.document_kind != "SANCTION_PUBLICATION":
            result.issues.append(
                {
                    "boe_id": boe_id,
                    "kind": "SUBSEQUENT_EVENT_DOC",
                    "detail": "revocation/correction document — not a case",
                }
            )
            continue
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
