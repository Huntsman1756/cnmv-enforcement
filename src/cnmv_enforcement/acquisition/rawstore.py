"""Immutable raw artifact store.

Layout under ``data/raw/``:

    objects/<sha256>          byte-exact artifact, content-addressed
    manifest.jsonl            append-only retrieval manifest (one JSON row
                              per retrieval event)

Guarantees:

- bytes are never modified after first write (same sha256 → same object);
- every retrieval appends a manifest row — full history, no silent
  overwrites;
- same ``canonical_locator`` + different ``sha256`` is *recorded change*,
  detectable by comparing manifest rows.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from cnmv_enforcement.sources.http import FetchResult

log = logging.getLogger("cnmv_enforcement.rawstore")

MANIFEST_NAME = "manifest.jsonl"


class ManifestRow(BaseModel):
    source_id: str
    authority: str
    canonical_locator: str | None
    retrieval_url: str
    retrieved_at: datetime
    sha256: str
    content_type: str | None
    http_status: int
    document_type: str
    raw_path: str


def source_id_for(authority: str, kind: str, sha256: str) -> str:
    return f"{authority}:{kind}:{sha256[:16]}"


class RawStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.objects = root / "objects"
        self.manifest_path = root / MANIFEST_NAME
        self.objects.mkdir(parents=True, exist_ok=True)

    # -- read -----------------------------------------------------------
    def manifest(self) -> list[ManifestRow]:
        if not self.manifest_path.exists():
            return []
        rows: list[ManifestRow] = []
        for raw_line in self.manifest_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line:
                rows.append(ManifestRow.model_validate_json(line))
        return rows

    def latest_by_locator(self) -> dict[str, ManifestRow]:
        """Most recent manifest row per canonical locator."""
        out: dict[str, ManifestRow] = {}
        for row in self.manifest():
            if row.canonical_locator:
                prev = out.get(row.canonical_locator)
                if prev is None or prev.retrieved_at <= row.retrieved_at:
                    out[row.canonical_locator] = row
        return out

    def read_object(self, sha256: str) -> bytes:
        return (self.objects / sha256).read_bytes()

    def read_object_text(self, sha256: str, encoding: str = "utf-8") -> str:
        return self.read_object(sha256).decode(encoding)

    # -- write ----------------------------------------------------------
    def store(
        self,
        result: FetchResult,
        *,
        authority: str,
        document_type: str,
        canonical_locator: str | None = None,
        kind: str | None = None,
    ) -> ManifestRow:
        path = self.objects / result.sha256
        if not path.exists():
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(result.content)
            tmp.replace(path)
        rel = path.relative_to(self.root).as_posix()
        sid = source_id_for(authority, kind or document_type.lower(), result.sha256)
        row = ManifestRow(
            source_id=sid,
            authority=authority,
            canonical_locator=canonical_locator,
            retrieval_url=result.final_url,
            retrieved_at=result.retrieved_at,
            sha256=result.sha256,
            content_type=result.content_type,
            http_status=result.http_status,
            document_type=document_type,
            raw_path=rel,
        )
        with self.manifest_path.open("a", encoding="utf-8") as fh:
            fh.write(row.model_dump_json() + "\n")
        return row

    def store_bytes(
        self,
        content: bytes,
        *,
        authority: str,
        document_type: str,
        canonical_locator: str | None,
        retrieval_url: str,
        retrieved_at: datetime,
        http_status: int = 200,
        content_type: str | None = None,
        kind: str | None = None,
    ) -> ManifestRow:
        """Store bytes obtained outside the HTTP client (fixtures, tests)."""
        result = FetchResult(
            url=retrieval_url,
            final_url=retrieval_url,
            http_status=http_status,
            content_type=content_type,
            content=content,
            retrieved_at=retrieved_at,
            sha256=hashlib.sha256(content).hexdigest(),
        )
        return self.store(
            result,
            authority=authority,
            document_type=document_type,
            canonical_locator=canonical_locator,
            kind=kind,
        )


def detect_changed_locators(rows: Iterable[ManifestRow]) -> list[dict[str, str]]:
    """Canonical locators whose sha256 changed between retrievals."""
    by_loc: dict[str, set[str]] = {}
    for r in rows:
        if r.canonical_locator:
            by_loc.setdefault(r.canonical_locator, set()).add(r.sha256)
    return [
        {"canonical_locator": loc, "sha256_values": ";".join(sorted(h))}
        for loc, h in by_loc.items()
        if len(h) > 1
    ]
