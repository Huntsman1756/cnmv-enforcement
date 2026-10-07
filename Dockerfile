FROM python:3.12-slim AS base

WORKDIR /app
RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

COPY data/corpus ./data/corpus
COPY data/corpus_historical ./data/corpus_historical
COPY data/review ./data/review
RUN .venv/bin/python -m cnmv_enforcement.cli.main build

EXPOSE 8765
CMD [".venv/bin/uvicorn", "cnmv_enforcement.api.app:app", "--host", "0.0.0.0", "--port", "8765"]
