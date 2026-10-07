"""Golden-corpus integrity: frozen raw bytes, not regenerated truth.

``tests/fixtures/corpus/SHA256SUMS`` pins every fixture's raw bytes. If a
fixture is replaced, this test fails before any expectation is compared —
the expectations can never drift to bless a different document.

Expectations in ``corpus_expectations.json`` are verified snapshots of
parser output against these frozen bytes, reviewed by humans after each
adversarial round — NOT auto-regenerated inside the test run. Regenerating
them is an explicit offline action (see FINAL_REVIEW.md), never part of
the test workflow.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"


def test_fixture_bytes_match_manifest():
    sums = CORPUS / "SHA256SUMS"
    assert sums.exists(), "SHA256SUMS missing — corpus integrity unpinned"
    manifest = {}
    for line in sums.read_text(encoding="utf-8").splitlines():
        h, name = line.split(None, 1)
        manifest[name.lstrip("*")] = h
    xmls = sorted(CORPUS.glob("BOE-A-*.xml"))
    assert len(manifest) == len(xmls) == 91, (
        f"manifest={len(manifest)} xmls={len(xmls)} — a fixture was "
        "added/removed without updating SHA256SUMS"
    )
    for xml in xmls:
        actual = hashlib.sha256(xml.read_bytes()).hexdigest()
        assert actual == manifest[xml.name], (
            f"{xml.name}: frozen bytes changed ({manifest[xml.name][:12]} -> "
            f"{actual[:12]}) — regenerate SHA256SUMS only after a deliberate, "
            "reviewed fixture replacement"
        )
