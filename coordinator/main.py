"""Multi-service coordinator — Stretch Thu (Honors Track).

The coordinator exposes a single POST /answer endpoint. On each call it:
1. Calls the classifier service to identify which downstream service(s)
   should answer the question.
2. Fans out to the selected service(s) via httpx.AsyncClient with a
   per-call timeout (5 s default; 10 s for the RAG generation service).
3. Aggregates the responses and returns a single AnswerResponse.
4. If any upstream returns a 5xx or times out, the coordinator returns
   200 with `partial: true` and a per-service attribution payload —
   never a 5xx that would lose the working upstream's response.
   Exception: if ALL upstreams fail, returns 503 with structured detail.
"""
import asyncio
import logging
import os
import time

import httpx
from fastapi import FastAPI, HTTPException

from .models import AnswerRequest, AnswerResponse
from .upstream import call_upstream

logger = logging.getLogger(__name__)

app = FastAPI(title="Stretch Thu — Multi-Service Coordinator")

CLASSIFIER_URL = os.environ.get("CLASSIFIER_URL", "http://classifier_svc:8001")

_SERVICE_URLS = {
    "nlp_svc": os.environ.get("NLP_SVC_URL", "http://nlp_svc:8002") + "/extract",
    "kg_svc": os.environ.get("KG_SVC_URL", "http://kg_svc:8003") + "/kg/query",
    "rag_svc": os.environ.get("RAG_SVC_URL", "http://rag_svc:8004") + "/rag/answer",
}

_RAG_TIMEOUT_S = float(os.environ.get("RAG_TIMEOUT_S", "10.0"))
_DEFAULT_TIMEOUT_S = float(os.environ.get("DEFAULT_TIMEOUT_S", "5.0"))


@app.post("/answer", response_model=AnswerResponse)
async def answer(req: AnswerRequest) -> AnswerResponse:
    """Classify → fan out → aggregate → respond.

    Returns AnswerResponse. `partial: true` iff one or more upstreams
    failed or timed out but at least one succeeded.
    """
    request_start = time.perf_counter() * 1000

    # Step 1: ask the classifier which services should answer.
    async with httpx.AsyncClient() as client:
        clf_resp = await client.post(
            f"{CLASSIFIER_URL}/classify",
            json={"question": req.question},
        )
        clf_resp.raise_for_status()
        routes = clf_resp.json()["routes"]

    # Step 2: fan out concurrently to each selected service.
    async def _call_one(route: dict) -> dict:
        service = route["service"]
        url = _SERVICE_URLS.get(service, f"http://{service}:8000")
        timeout = _RAG_TIMEOUT_S if service == "rag_svc" else _DEFAULT_TIMEOUT_S
        return await call_upstream(service, url, {"question": req.question}, timeout_s=timeout)

    upstream_results = await asyncio.gather(*[_call_one(r) for r in routes])

    # Step 3: aggregate.
    results: dict = {}
    responded: list = []

    for r in upstream_results:
        if hasattr(r, "model_dump"):
            r = r.model_dump()
        service = r["service"]
        if r["status"] == "ok":
            results[service] = r.get("payload") or r.get("result")
            responded.append(service)
        else:
            results[service] = None

    total_latency_ms = round(time.perf_counter() * 1000 - request_start, 2)

    # All upstreams failed → 503.
    if not responded:
        logger.error(
            "coordinator all_failed question=%r upstreams=%s latency_ms=%.2f",
            req.question,
            list(results.keys()),
            total_latency_ms,
        )
        raise HTTPException(
            status_code=503,
            detail={"error": "all upstreams failed", "results": results},
        )

    partial = len(responded) < len(routes)

    logger.info(
        "coordinator answer question=%r upstreams_called=%s responded=%s partial=%s latency_ms=%.2f",
        req.question,
        list(results.keys()),
        responded,
        partial,
        total_latency_ms,
    )

    return AnswerResponse(results=results, partial=partial, responded=responded)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
