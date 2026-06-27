# Stretch Thu — Multi-Service Coordinator (Honors Track)

> Honors Track — for learners who have completed all core Module 10
> assignments, are On Track or Advanced, and are attending consistently.

Decompose the Module 10 Lab's monolithic backend into three downstream
microservices (NLP, KG, RAG), add a query-classifier service, and add
a coordinator service that fans out to the selected downstream(s) and
handles partial failure gracefully.

---

## Coordinator Design

The coordinator implements a **classify → fan-out → aggregate → respond** pipeline.
On every `POST /answer` request the coordinator first calls `classifier_svc` over
HTTP to obtain a ranked `routes` list.  It then launches concurrent
`httpx.AsyncClient` calls to every chosen downstream (5 s per call, 10 s for the
generation-heavy RAG service) via `call_upstream`, which enforces per-call timeouts
and emits one structured log line per call containing `service`, `status`, and
`latency_ms`.  Results are collected and aggregated: services that respond within
their timeout are listed in `responded`; any that time out or return a 5xx get
`null` in `results`.  If at least one upstream succeeded the coordinator returns
HTTP 200 with `partial: true`; if every upstream failed it returns 503.  This
design ensures a single slow or dead service never blocks the response from
healthy peers — the partial-failure contract is the core of the coordinator pattern
and the direct precursor to the multi-tool agent loop in the capstone.

## Microservice Split — Cost / Benefit

**What the split buys:** each service can be scaled, deployed, and restarted
independently.  A spike in RAG traffic (slow generative inference) no longer
starves NLP or KG queries.  Failure isolation is precise: killing `rag_svc`
leaves extraction and graph lookup fully available.  The classifier becomes a
first-class routing component rather than buried `if/else` logic, making it
trivial to swap in a zero-shot model (e.g. `facebook/bart-large-mnli`) without
touching the other services.

**What the split costs:** every request now crosses at least two HTTP boundaries
(classifier + at least one backend) instead of zero.  Shared concerns — Pydantic
models, `/healthz`, structured errors — are duplicated per service rather than
imported from a common library.  The Compose topology grows from 1 container to
5 (or 7 with the persistence tier), which increases local development overhead and
makes distributed tracing necessary for diagnosing latency.  For a small model
with tight memory budgets (≤16 GB) running multiple model-loading containers
simultaneously requires careful resource governance (memory caps in Compose) that
a single process simply doesn't need.

---

## Setup

```bash
git clone https://github.com/<your-username>/m10-s210.git
cd m10-s210
git checkout stretch-10-thu-coordinator
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Running the 5-Service Stack

```bash
docker compose up -d --build
docker compose ps          # all five services should reach status healthy
```

Verify the coordinator is live:

```bash
curl -s http://localhost:8000/healthz | python -m json.tool
# {"status": "ok"}
```

Send a question:

```bash
curl -s -X POST http://localhost:8000/answer \
  -H "Content-Type: application/json" \
  -d '{"question": "find Sichuan recipes"}' | python -m json.tool
```

Expected response shape:

```json
{
  "results": {
    "kg_svc": { "cypher": "...", "rows": [], "count": 0, "service": "kg_svc" },
    "rag_svc": { "answer": "...", "citations": [...], "confidence": 0.9, "service": "rag_svc" }
  },
  "partial": false,
  "responded": ["kg_svc", "rag_svc"]
}
```

---

## Partial-Failure Demo

Kill `rag_svc` mid-run and observe the coordinator's graceful response:

```bash
# With the stack running:
docker compose stop rag_svc

curl -s -X POST http://localhost:8000/answer \
  -H "Content-Type: application/json" \
  -d '{"question": "find Sichuan recipes"}' | python -m json.tool
```

Expected output (partial=true, rag_svc absent from responded):

```json
{
  "results": {
    "kg_svc": { "cypher": "MATCH (n) RETURN n", "rows": [], "count": 0, "service": "kg_svc" },
    "rag_svc": null
  },
  "partial": true,
  "responded": ["kg_svc"]
}
```

The coordinator returns HTTP 200 — it does not propagate the upstream 503 when at
least one peer responded successfully.

Restart `rag_svc` when done:

```bash
docker compose start rag_svc
```

---

## Observability

Every upstream call emits one structured log line on the coordinator container:

```
INFO  upstream_call service=rag_svc status=ok latency_ms=12.34
```

Every inbound request logs which upstreams were called, which responded, and total
latency:

```
INFO  coordinator answer question='find Sichuan recipes' upstreams_called=['kg_svc','rag_svc'] responded=['kg_svc','rag_svc'] partial=False latency_ms=18.21
```

View live coordinator logs:

```bash
docker compose logs -f coordinator
```

---

## Running Unit Tests

The autograder uses httpx mocks — no Docker required:

```bash
source .venv/bin/activate
pytest tests/ -v
```

---

## Submission

PR URL pasted into TalentLMS → Module 10 → Stretch Thu.

---

## License

This repository is provided for educational use only. See
[LICENSE](LICENSE) for terms.
