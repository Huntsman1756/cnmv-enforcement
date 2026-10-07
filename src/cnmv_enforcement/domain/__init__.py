"""Domain model for the cnmv-enforcement ledger.

Non-negotiable invariants encoded here:

- FACT != INFERENCE. Unsupported fields stay ``None`` or ``UNKNOWN``.
- OBSERVED != TRUE_FOR_ALL_TIME. Every fact carries provenance.
- REGISTER ABSENCE != NO SANCTION.
- RESOLUTION DATE != OFFENCE DATE != PUBLICATION DATE.
- NO APPEAL OBSERVED != NO APPEAL.
- CASE STATUS != RESPONDENT STATUS != SANCTION STATUS.
- NO EVIDENCE = NO CLAIM.
"""
