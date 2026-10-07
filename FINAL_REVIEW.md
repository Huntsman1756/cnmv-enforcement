# FINAL REVIEW — cnmv-enforcement

Scope review performed against the merged corpus (91 register-snapshot
publications + 70 historical-backfill publications, 2018-2021 slice).

## Dual adversarial review (judgment-day, round 1)

Two blind judges inspected the frozen target. Judge A returned 9 SEVERE
findings, all verified against source XML and fixed (see commit
`fix(parser): judge A round`).

| # | Defect | Fix |
|---|--------|-----|
| S1 | `duration_raw` parsed but dropped at assembly | passed to `Sanction` |
| S2 | `sanctioning_resolution_date` NULL in 89/91 docs | broadened resolution regex → 85/91 dated |
| S3 | paren-split `, a la fecha` → phantom subject, doubled fine | paren masking in `split_subjects` |
| S4 | `X y Y` merged subjects → merged respondents, under-counted fines | multi-word ` y ` split (entity names like 'Riva y García' protected) |
| S5 | dative `a X` in descriptive clause → garbage respondent | length + clause-marker guards |
| S6 | lettered articles lost letters (`282.16. a)`, `93. p)`, `b) y c)`) | space-dot-letter + letter-list emission |
| S7 | `Reglamento (UE) número` not normalized → related provisions inherited typifying statute | connector added |
| S8 | cross-month day lists / `8 y 9 junio` dropped dates | `_CROSS_MONTH_RE`, `_DAY_NODE_RE`, wider statute window |
| S9 | `respondents` table duplicate PK rows | dedup by `respondent_id` |

## Dual adversarial review — scoped re-judgment (round 2)

Judge B's scoped re-judgment over the fix delta returned 9 further SEVERE
findings — 2 of them regressions introduced by round-1 fixes (entity `y`
names; a `separación` lookahead gap). All were verified against the real
parse before fixing (commit `fix(parser): judge B round 2`).

| # | Defect | Fix |
|---|--------|-----|
| F1 | `entre el D1 de M1 y el D2 de M2` cross-month form — start date lost | `el` allowed after conjunctions |
| F2 | `Banco Financiero y de Ahorro` entity name split (round-1 regression) | `y` split requires uppercase start + no comma |
| F3 | `separación` absent from subject-first lookahead | added |
| F4 | `Imponer a X, por la comisión:` leaked boilerplate into subjects | header tail strip |
| F5 | `respectivamente` → cross-product (400k vs 200k) | positional pairing |
| F6 | `por la comisión por parte de…` unparsed (untyped block) | mid-clause without comma |
| F7 | `del mismo texto legal` forced block statute on all segment articles | per-chunk statute |
| F8 | `(en la actualidad, …RDL)` polluted typifying statute | masked before normalize |
| F9 | `letra o)`, `83 ter 1`, `107 quáter 3.c`, `99 z ter` letter loss | token/word-suffix grammar (conjunction-safe) |

Plus `al carecer`/`al presentar` conduct boundary, `Resolución de fecha`
w/o Consejo, and a phantom-`e` regression caught by goldens (`282.6.e`
→ `282.6`). Judge-B verdict on round-1 delta: UNSOUND — corrected.

## Verified dataset state (post-fix)

```
cases            160   (91 register + 69 historical sanction publications)
respondents      276   (deduped by strong normalized identity)
infringements    260
sanctions        390
events           521
evidence         2219
documents        160
case_status      88    (from CNMV-PDF status observations)
parse_issues     1     (the revocation doc — recorded, not a defect)
```

- `pytest`: 100 pass (91-doc golden corpus, regenerated to verified-correct
  values).
- `cnmv-enforcement validate`: all gates green.
- `mypy`/`ruff`: clean.

## Scope honesty

- Register coverage = the live snapshot only; register absence is never
  claimed as non-enforcement.
- Historical coverage = BOE dept 1040 items 2018-01→2021-10 matching
  sanction-title markers; older/deeper history requires longer
  `enumerate-history` runs (resumable manifest).
- PDF status notes are *observations* (`observed_*`), never legal truth;
  "no appeal observed" is never rendered as "no appeal".
- Respondent names are reproduced as-published; anonymized parties stay
  anonymized.

## Known residual limitations (judge-W class, documented not hidden)

- Some `subject_raw` values retain procedural prefixes (evidence is raw;
  `normalized_name` strips roles for identity).
- `respectivamente` multi-role attributions attach to the last subject.
- 6 register docs lack `sanctioning_resolution_date` (different wording;
  honest absence).
- `UNRESOLVED_RULE_VERSION` (~30%) marks rule-versions not yet in the
  catalog — stated, never guessed.
- `events` from PDF notes carry no respondent linkage (publication-level
  observations).
