# Defect taxonomy — the 18 adversarial defects of v0.4

Permanent classification of the material defects found in the two
judgment-day rounds. Machine form: `data/review/defect_registry.yaml`.
Each defect is regression-covered by a test in
`tests/regression/test_defect_registry.py`.

| class | count | instances |
|---|---|---|
| PHANTOM_RESPONDENT | 2 | S3, S5 |
| RESPONDENT_MERGE_LOSS | 1 | S4 |
| ENTITY_NAME_SPLIT_ERROR | 1 | F2 |
| SUBJECT_TEXT_CONTAMINATION | 2 | F3, F4 |
| RESPECTIVAMENTE_ALIGNMENT_ERROR | 1 | F5 |
| COMISION_VARIANT_DROP | 1 | F6 |
| STATUTE_MISATTRIBUTION | 3 | S7, F7, F8 |
| ARTICLE_SUFFIX_LOSS | 3 | S6, F9, +golden phantom-e |
| CONDUCT_DATE_LOSS | 2 | S8, F1 |
| RESOLUTION_DATE_LOSS | 1 | S2 |
| DURATION_FIELD_LOSS | 1 | S1 |
| DUPLICATE_KEY_CORRUPTION | 1 | S9 |

18 defect instances, 12 classes. Regression coverage: 18/18
(`artifacts/review-coverage.json`, gate G16).

## Reading

- **Fan-out classes** (PHANTOM_RESPONDENT, ENTITY_NAME_SPLIT_ERROR,
  RESPECTIVAMENTE_ALIGNMENT_ERROR, DUPLICATE_KEY_CORRUPTION):
  the dataset *grew* facts that do not exist — the worst corruption
  kind for a ledger.
- **Loss classes** (ARTICLE_SUFFIX_LOSS, CONDUCT_DATE_LOSS,
  RESOLUTION_DATE_LOSS, DURATION_FIELD_LOSS, COMISION_VARIANT_DROP,
  RESPONDENT_MERGE_LOSS): real source data silently degraded.
- **Attribution classes** (STATUTE_MISATTRIBUTION,
  SUBJECT_TEXT_CONTAMINATION): real data bound to wrong identities.
