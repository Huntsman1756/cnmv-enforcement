"""Polite HTTP layer for official sources.

Rules: descriptive User-Agent, explicit timeouts, bounded retries with
backoff, minimum inter-request pacing per host, conditional GET support
where the server offers validators. Never hammer public infrastructure.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from cnmv_enforcement.config import USER_AGENT

log = logging.getLogger("cnmv_enforcement.http")

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=15.0)
MAX_RETRIES = 3
BACKOFF_BASE_S = 2.0
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024  # 64 MiB hard cap


@dataclass
class FetchResult:
    url: str
    final_url: str
    http_status: int
    content_type: str | None
    content: bytes
    retrieved_at: datetime
    sha256: str
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.http_status < 300


@dataclass
class FetchError:
    url: str
    error: str
    retrieved_at: datetime


class HttpClient:
    def __init__(
        self,
        user_agent: str = USER_AGENT,
        min_interval_s: float = 0.5,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate, br"},
            timeout=timeout,
            follow_redirects=True,
        )
        self.min_interval_s = min_interval_s
        self.max_retries = max_retries
        self._last_request_at = 0.0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _pace(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval_s:
            time.sleep(self.min_interval_s - elapsed)

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        accept: str | None = None,
    ) -> FetchResult:
        merged = dict(headers or {})
        if accept:
            merged["Accept"] = accept
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._pace()
            try:
                resp = self._client.get(url, headers=merged)
                self._last_request_at = time.monotonic()
                if len(resp.content) > MAX_DOWNLOAD_BYTES:
                    raise FetchSizeError(url)
                # retry on transient statuses
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    wait = BACKOFF_BASE_S * (2**attempt)
                    log.warning("%s → %s; retry in %.1fs", url, resp.status_code, wait)
                    time.sleep(wait)
                    continue
                return FetchResult(
                    url=url,
                    final_url=str(resp.url),
                    http_status=resp.status_code,
                    content_type=resp.headers.get("content-type"),
                    content=resp.content,
                    retrieved_at=datetime.now(UTC),
                    sha256=hashlib.sha256(resp.content).hexdigest(),
                    headers=dict(resp.headers),
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    wait = BACKOFF_BASE_S * (2**attempt)
                    log.warning("%s failed (%s); retry in %.1fs", url, exc, wait)
                    time.sleep(wait)
        raise HttpFetchError(url, str(last_exc))


class HttpFetchError(Exception):
    def __init__(self, url: str, detail: str) -> None:
        super().__init__(f"fetch failed for {url}: {detail}")
        self.url = url


class FetchSizeError(Exception):
    def __init__(self, url: str) -> None:
        super().__init__(f"download exceeds size cap: {url}")
