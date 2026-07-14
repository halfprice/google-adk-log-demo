"""Verification endpoint for the tamper-evident agent audit trail.

POST /verify   — body: a log file (JSONL of signed records, as exported from
                 the trail or handed over by the operator). Returns a JSON
                 report proving the log authentic against the published
                 digests (anchored manifests + chain), or pinpointing exactly
                 which records are tampered/fabricated.
GET  /audit    — full trust-nothing audit of the whole anchored trail.
GET  /trail    — current chain state (height, last seq, head blob).
GET  /health   — liveness.

Run:  .venv/bin/uvicorn verify_server:app --port 8600
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, Request, Response

PROJECT_DIR = Path(__file__).resolve().parent
AUDITLOG_BIN = Path(
    os.environ.get("AUDITLOG_BIN", PROJECT_DIR.parent / "AuditLog/target/debug/auditlog")
)
DATA_DIR = Path(os.environ.get("AUDIT_DATA_DIR", PROJECT_DIR / "audit_data"))

app = FastAPI(title="Agent audit-log verification")


def _run(args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        [str(AUDITLOG_BIN), "--data-dir", str(DATA_DIR), *args],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/verify")
async def verify(request: Request) -> Response:
    """Check an uploaded log against the published digests."""
    body = await request.body()
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".jsonl", delete=False) as f:
        f.write(body)
        tmp = f.name
    try:
        code, out, err = _run(["verify-log", "--file", tmp])
    finally:
        os.unlink(tmp)
    if not out.strip():
        return Response(
            json.dumps({"authentic": False, "error": err.strip()}),
            media_type="application/json",
            status_code=500,
        )
    # verify-log always prints a JSON report; exit code mirrors `authentic`.
    return Response(out, media_type="application/json")


@app.get("/audit")
def audit() -> Response:
    code, out, err = _run(["audit", "--json"])
    if not out.strip():
        return Response(
            json.dumps({"ok": False, "error": err.strip()}),
            media_type="application/json",
            status_code=500,
        )
    return Response(out, media_type="application/json")


@app.get("/trail")
def trail() -> dict:
    state = json.loads((DATA_DIR / "chain" / "state.json").read_text())
    return state["trails"]
