"""A small in-process rate limiter for the endpoints that cost real money.

Two endpoints spend something per call that is not CPU: `/api/analyze` spends LLM tokens,
and `/webhook/inbound-email` sends email. Neither had any ceiling, so a loop against either
one was a bill rather than a load spike.

Deliberately in-process and deliberately not a dependency. The API runs as a single
uvicorn process on Render (see render.yaml), so a per-process counter *is* the global
counter; the moment that stops being true — a second instance, or `--workers` — this needs
to move to Redis, and the docstring on `FixedWindowLimiter` says so.
"""

import threading
import time

from fastapi import HTTPException, Request, status

# Counters for keys nobody has used in a while are dropped, so a long-running process does
# not accumulate one dict entry per IP that ever touched it.
_SWEEP_EVERY_SECONDS = 300


class FixedWindowLimiter:
    """Allow `limit` events per `window_seconds` per key.

    A fixed window, not a sliding one: it permits up to 2x the limit across a window
    boundary, which is the standard trade and entirely fine for "stop a script", which is
    all this is for. It is NOT a fairness mechanism and NOT shared between processes.
    """

    def __init__(self, limit: int, window_seconds: float):
        self._limit = limit
        self._window = window_seconds
        self._lock = threading.Lock()
        self._hits: dict[str, tuple[float, int]] = {}
        self._last_sweep = time.monotonic()

    def _sweep(self, now: float) -> None:
        """Drop windows that have already expired. Caller holds the lock."""
        if now - self._last_sweep < _SWEEP_EVERY_SECONDS:
            return
        cutoff = now - self._window
        self._hits = {
            key: entry for key, entry in self._hits.items() if entry[0] > cutoff
        }
        self._last_sweep = now

    def allow(self, key: str) -> bool:
        """Record one event for `key`. False when it is over the limit."""
        now = time.monotonic()
        with self._lock:
            self._sweep(now)
            started, count = self._hits.get(key, (now, 0))
            if now - started >= self._window:
                started, count = now, 0
            if count >= self._limit:
                return False
            self._hits[key] = (started, count + 1)
            return True

    def retry_after(self) -> int:
        return int(self._window)


def client_key(request: Request) -> str:
    """Who to count against. The signed-in user when there is one, else the peer address.

    Counting the session user first means one noisy tenant cannot exhaust the budget of
    everyone sharing an office NAT. `request.client.host` is the real client on Render
    because uvicorn runs with `--forwarded-allow-ips`, which makes it honour
    X-Forwarded-For — without that flag this would count the proxy and limit everyone at
    once, so the two settings have to stay together.
    """
    user_id = request.session.get("user_id") if "session" in request.scope else None
    if user_id:
        return f"user:{user_id}"
    peer = request.client.host if request.client else "unknown"
    return f"ip:{peer}"


def rate_limited(limiter: FixedWindowLimiter):
    """A FastAPI dependency that enforces `limiter` for the calling client."""

    def dependency(request: Request) -> None:
        if not limiter.allow(client_key(request)):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many requests. Try again shortly.",
                headers={"Retry-After": str(limiter.retry_after())},
            )

    return dependency
