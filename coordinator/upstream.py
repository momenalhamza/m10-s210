"""httpx.AsyncClient helpers — per-call timeout enforcement.

Catches a common mistake where learners set the timeout at the session
level (once across the whole AsyncClient lifecycle) instead of per
.get/.post call. The session-level timeout still applies but does not
fire per call, so slow upstreams can starve faster ones.
"""
import logging
import time

import httpx

logger = logging.getLogger(__name__)


async def call_upstream(service: str, url: str, payload: dict, timeout_s: float = 5.0):
    """Call one upstream service. Returns an UpstreamResult-shaped dict.

    Per-call timeout via `httpx.Timeout(timeout_s)` on `.post`.
    """
    start_ms = time.perf_counter() * 1000
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s)) as client:
            r = await client.post(url, json=payload)
            latency_ms = round(time.perf_counter() * 1000 - start_ms, 2)
            result = {
                "service": service,
                "status": "ok",
                "latency_ms": latency_ms,
                "payload": r.json(),
                "error": None,
            }
    except httpx.TimeoutException as exc:
        latency_ms = round(time.perf_counter() * 1000 - start_ms, 2)
        result = {
            "service": service,
            "status": "timeout",
            "latency_ms": latency_ms,
            "payload": None,
            "error": str(exc),
        }
    except Exception as exc:
        latency_ms = round(time.perf_counter() * 1000 - start_ms, 2)
        result = {
            "service": service,
            "status": "error",
            "latency_ms": latency_ms,
            "payload": None,
            "error": str(exc),
        }

    logger.info(
        "upstream_call service=%s status=%s latency_ms=%.2f",
        result["service"],
        result["status"],
        result["latency_ms"],
    )
    return result
