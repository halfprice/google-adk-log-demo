# google-adk-log — multi-agent demo with per-agent action logs

A local, end-to-end demo of a Google ADK multi-agent pipeline where three
agents collaborate on an incident investigation, and **every agent writes
its own JSONL action log** (LLM calls, tool/RPC calls, results) that is then
anchored to a tamper-evident audit trail.

**▶ [Security story](https://halfprice.github.io/google-adk-log-demo/demo_story2.html)** —
logs live outside the agent and their digests are anchored to a public chain, so
when an operator rewrites the raw logs to bury an incident, any third party can
prove it. &nbsp;·&nbsp;
**[System walkthrough](https://halfprice.github.io/google-adk-log-demo/demo_viz.html)** —
a 30-second replay of the whole pipeline (agents → audit trails → verification).
&nbsp;·&nbsp;
[earlier story](https://halfprice.github.io/google-adk-log-demo/demo_story.html)
(agent-only cover-up). All served from this repo via GitHub Pages.

## The pipeline

```
incident_pipeline (SequentialAgent)
├── triage_agent    — searches KB + fetches metrics   → state["findings"]
├── analysis_agent  — checks dependencies, finds RCA  → state["diagnosis"]
└── report_agent    — files the incident report, briefs the user
```

Tools (`research_demo/tools.py`) simulate backend RPCs with canned data:
the checkout service is slow because `payments-db`'s connection pool is
saturated — the agents discover this on their own.

Action logging (`research_demo/action_logger.py`) uses ADK callbacks
(`before/after_agent`, `before/after_model`, `before/after_tool`) to append
one JSON line per action to `logs/<agent_name>.jsonl`.

## Setup

Clone both repos side by side, then configure credentials:

```bash
git clone https://github.com/halfprice/google-adk-log-demo
git clone https://github.com/halfprice/AuditLog
cd google-adk-log-demo
cp .env.example .env      # then put your Gemini API key in .env
```

Auth (pick one), in `.env`:

- **AI Studio key**: set `GOOGLE_API_KEY=...` (free at https://aistudio.google.com/apikey)
- **Vertex AI**: `gcloud auth application-default login`, then uncomment the
  Vertex block in `.env`

Everything else (Rust build, Python venv, dependencies) is handled by
`./demo.sh`. Prerequisites: Python 3.10+, Rust (https://rustup.rs).

## Run

```bash
# Everything at once — builds AuditLog, sets up the venv, runs the full
# live demo (agents → per-minute anchoring → verify → tamper → caught):
./demo.sh --interval 15

# Just the agents, with per-agent JSONL action logs:
.venv/bin/python run_demo.py

# Or the interactive ADK dev UI (chat + built-in event/trace inspector):
.venv/bin/adk web
```

After a run, inspect the per-agent logs:

```bash
cat logs/analysis_agent.jsonl | python3 -m json.tool --json-lines
```

## Tamper-evident audit trail ([AuditLog](https://github.com/halfprice/AuditLog) integration)

Every agent action is also spooled into the hash-chained, Merkle-anchored
audit trail implemented in [halfprice/AuditLog](https://github.com/halfprice/AuditLog),
expected as a sibling checkout:

```bash
git clone https://github.com/halfprice/AuditLog ../AuditLog
(cd ../AuditLog && cargo build)
```
A publisher anchors the spool on a timer (production: every minute) — signed
records, batch manifest on (mock) Walrus, two-phase commit on the (mock) Sui
chain; idle periods anchor heartbeats. An HTTP endpoint verifies any log file
against the published digests.

```bash
# Full live demo: agents act → trail anchors every 15s → verify → tamper → catch
.venv/bin/python run_audit_demo.py --interval 15 [--keep-serving]

# Or run the pieces standalone:
.venv/bin/python audit_publisher.py --interval 60      # minute publisher
.venv/bin/uvicorn verify_server:app --port 8600        # verification endpoint

# Verify a log against the published digests (one trail per agent):
curl -s --data-binary @exported_agent_0.jsonl http://127.0.0.1:8600/verify | python3 -m json.tool
curl -s http://127.0.0.1:8600/audit | python3 -m json.tool   # full-trail audit
```

Pieces: `research_demo/audit_spool.py` (callback → spool),
`audit_publisher.py` (spool → `auditlog ingest`), `verify_server.py`
(`POST /verify` → `auditlog verify-log`, `GET /audit`, `GET /trail`).
A tampered, fabricated, or reordered record fails signature, hash-chain, and
Merkle-root checks against the anchored manifests and is pinpointed by seq.
