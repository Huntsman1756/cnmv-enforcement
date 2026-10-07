# Deployment

## Components

- **API** — read-only FastAPI over the built DuckDB (`api/app.py`), port 8765.
- **Web** — static React/Vite build (`web/dist`), served by nginx with
  `/api/*` proxied to the API.
- **Data** — `data/corpus` (frozen BOE XML corpus), `data/raw` (immutable
  raw store), `data/runtime` (duckdb, manifests, PDF status),
  `data/exports` (parquet + coverage.json).

## Local

```bash
uv sync
cnmv-enforcement build            # data/corpus -> parquet + duckdb + coverage
uvicorn cnmv_enforcement.api.app:app --port 8765
cd web && npm ci && npm run dev   # http://localhost:5174
```

## Docker

```bash
cd web && npm ci && npm run build
docker compose up --build
# web on :8080, api on :8765
```

The API image runs `cnmv-enforcement build` at build time from the corpus
in `data/corpus` — a pinned corpus yields a reproducible image.

## Scheduled jobs

| Job | Command | Purpose |
|---|---|---|
| register refresh | `cnmv-enforcement fetch` | re-enumerate register, fetch new XMLs |
| pdf status | `cnmv-enforcement pdf-status` | CNMV PDF note diffing (appeal/firmness) |
| history backfill | `cnmv-enforcement enumerate-history START END` | resumable dept-1040 scan |
| backfill fetch | `cnmv-enforcement backfill-fetch` | XMLs for sanction-like history items |
| validation | `cnmv-enforcement validate` | release gates; fails loudly |

Full-history enumeration (1961→present) is a multi-hour polite batch —
run it chunked by year; the JSONL manifest is resumable.

## TLS / exposure

The shipped `docker-compose.yml` serves plain HTTP on :8080 — it is a
single-host reference deployment. For public exposure terminate TLS in
front (reverse proxy, Caddy, or your LB) and forward `X-Forwarded-*`;
nginx already sets the security headers. The API on :8765 is read-only
and carries no auth state — restrict it to the proxy host if exposed
publicly.
