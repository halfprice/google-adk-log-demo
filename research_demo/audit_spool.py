"""Spool for the tamper-evident audit trail
(https://github.com/halfprice/AuditLog).

Every action record the agents produce is also appended here as a pending
entry. The audit publisher periodically rotates this spool and hands it to
`auditlog ingest`, which signs each action into the hash-chained,
Merkle-anchored trail.

Spool line format (what `auditlog ingest --spool` expects):
    {"claimed_time_ms": <unix ms int>, "action": {...}}

The canonical-JSON contract of the audit system covers strings/ints only,
so float values are stringified before spooling.
"""

import json
import time
from pathlib import Path

SPOOL_DIR = Path(__file__).resolve().parent.parent / "audit_spool"


def pending_path(agent: str) -> Path:
    # One spool — and downstream, one signed chain — per agent.
    return SPOOL_DIR / f"{agent}.pending.jsonl"


def _sanitize(value):
    if isinstance(value, bool) or isinstance(value, int) or value is None:
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return {str(k): _sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(v) for v in value]
    return str(value)


def spool_record(record: dict) -> None:
    SPOOL_DIR.mkdir(exist_ok=True)
    entry = {
        "claimed_time_ms": int(time.time() * 1000),
        "action": _sanitize(record),
    }
    with pending_path(record["agent"]).open("a") as f:
        f.write(json.dumps(entry) + "\n")


def rotate(agent: str) -> Path | None:
    """Atomically claim one agent's pending spool for publishing.

    Returns the rotated file path, or None if there is nothing pending.
    """
    pending = pending_path(agent)
    if not pending.exists():
        return None
    rotated = SPOOL_DIR / f"{agent}.batch-{int(time.time() * 1000)}.jsonl"
    pending.rename(rotated)
    return rotated
