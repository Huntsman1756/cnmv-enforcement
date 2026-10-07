"""Temporal rule-version resolution.

Given a normalized statute, normalized article and the conduct window
observed in the publication text, resolve which instrument/version the
infringement was typified under. This is deterministic and conservative:

- an ambiguous instrument name ('Ley del Mercado de Valores') resolves only
  when the conduct window fits exactly one versioned instrument;
- no conduct dates → UNRESOLVED_RULE_VERSION (never guessed);
- no rule defined → NO_RULE_DEFINED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from importlib import resources

import yaml

from cnmv_enforcement.domain.enums import ConductCode, RuleResolutionStatus


@dataclass(frozen=True)
class Instrument:
    family: str
    name: str
    aliases: tuple[str, ...]
    valid_from: date
    valid_to: date | None


@dataclass(frozen=True)
class Rule:
    rule_id: str
    family: str
    article: str
    conduct_code: str


@dataclass
class RuleIndex:
    instruments: list[Instrument] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)

    def families_for(self, statute_normalized: str | None) -> list[Instrument]:
        if not statute_normalized:
            return []
        s = " ".join(statute_normalized.lower().split())
        return [
            i
            for i in self.instruments
            if any(" ".join(a.lower().split()) == s for a in i.aliases)
        ]

    def rules_for(self, family: str, article: str | None) -> list[Rule]:
        return [
            r
            for r in self.rules
            if r.family == family and r.article == article
        ]


def load_rules() -> RuleIndex:
    with (
        resources.files("cnmv_enforcement")
        .joinpath("config/legal_rules.yaml")
        .open("rb") as fh
    ):
        doc = yaml.safe_load(fh)
    idx = RuleIndex()
    for i in doc.get("instruments", []):
        idx.instruments.append(
            Instrument(
                family=i["family"],
                name=i["name"],
                aliases=tuple(i.get("aliases", [])),
                valid_from=date.fromisoformat(i["valid_from"]),
                valid_to=(
                    date.fromisoformat(i["valid_to"]) if i.get("valid_to") else None
                ),
            )
        )
    for r in doc.get("rules", []):
        idx.rules.append(
            Rule(
                rule_id=r["rule_id"],
                family=r["family"],
                article=str(r["article"]),
                conduct_code=r.get("conduct_code", "UNKNOWN"),
            )
        )
    return idx


def _covers(inst: Instrument, start: date | None, end: date | None) -> bool:
    if start is None or end is None:
        return False
    return inst.valid_from <= start and (inst.valid_to is None or end <= inst.valid_to)


def resolve_rule_version(  # noqa: PLR0911 — each status is a distinct honest outcome
    index: RuleIndex,
    statute_normalized: str | None,
    article_normalized: str | None,
    conduct_start: date | None,
    conduct_end: date | None,
) -> tuple[str | None, RuleResolutionStatus, ConductCode, str | None]:
    """→ (rule_version_id, status, conduct_code, resolved_family).

    rule_version_id names the instrument/version the typification was
    resolved under — the *version* of the applicable law, never the
    current law by default.
    """
    families = index.families_for(statute_normalized)
    if not families:
        return None, RuleResolutionStatus.NO_RULE_DEFINED, ConductCode.UNKNOWN, None
    if len(families) == 1:
        family = families[0]
    else:
        covering = [f for f in families if _covers(f, conduct_start, conduct_end)]
        if len(covering) == 1:
            family = covering[0]
        elif not covering:
            return (
                None,
                RuleResolutionStatus.UNRESOLVED_RULE_VERSION,
                ConductCode.UNKNOWN,
                None,
            )
        else:
            return (
                None,
                RuleResolutionStatus.AMBIGUOUS_VERSION,
                ConductCode.UNKNOWN,
                None,
            )
    rules = index.rules_for(family.family, article_normalized)
    if not rules and article_normalized:
        # sub-letter provisions ('282.16.c') are governed by their parent
        base = article_normalized
        while "." in base:
            base = base.rsplit(".", 1)[0]
            rules = index.rules_for(family.family, base)
            if rules:
                break
    if not rules:
        return (
            None,
            RuleResolutionStatus.NO_RULE_DEFINED,
            ConductCode.UNKNOWN,
            family.family,
        )
    code = ConductCode(rules[0].conduct_code)
    if conduct_start is None or conduct_end is None:
        return (
            rules[0].rule_id,
            RuleResolutionStatus.UNRESOLVED_RULE_VERSION,
            code,
            family.family,
        )
    if not _covers(family, conduct_start, conduct_end):
        return (
            rules[0].rule_id,
            RuleResolutionStatus.UNRESOLVED_RULE_VERSION,
            code,
            family.family,
        )
    return (
        rules[0].rule_id,
        RuleResolutionStatus.VALID_FOR_CONDUCT,
        code,
        family.family,
    )
