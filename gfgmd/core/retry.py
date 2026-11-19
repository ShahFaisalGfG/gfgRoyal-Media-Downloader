"""How long to wait before the next attempt."""

from __future__ import annotations

from gfgmd.config.defaults import DownloadDefaults

MAX_RETRY_DELAY = DownloadDefaults.MAX_RETRY_DELAY
# A site that answered "too many requests" gets at least this long to cool down.
RATE_LIMIT_DELAY = 120


def retry_delay(attempt: int, initial: int, category: str = "") -> int:
    """Seconds before attempt `attempt + 1`: doubling from `initial`, capped at five minutes."""
    delay = min(initial * (2 ** min(max(attempt, 1) - 1, 30)), MAX_RETRY_DELAY)
    if category == "rate_limited":
        delay = max(delay, RATE_LIMIT_DELAY)
    return delay
