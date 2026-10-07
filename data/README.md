# data/

Runtime data directory. Contents are NOT versioned:

- `raw/` — immutable byte-exact source artifacts (objects by sha256 +
  `manifest.jsonl` retrieval log). Published as release assets.
- `corpus/` — development-time fetched corpus (regenerable via
  `cnmv-enforcement fetch`).
- `runtime/` — built DuckDB and intermediate state.
- `exports/` — generated Parquet/CSV/JSONL exports.
