"""Audit publisher: every `interval` seconds, seal the spooled agent actions
into the tamper-evident trail (https://github.com/halfprice/AuditLog) —
sign, hash-chain, Merkle-commit,
store the manifest, and anchor it on the (mock) chain.

An interval with no actions still anchors a heartbeat, so silence is
detectable. Production cadence is 60s; the demo uses a shorter interval.

Run standalone:
    .venv/bin/python audit_publisher.py --interval 60
or use AuditPublisher as a background thread (see run_audit_demo.py).
"""

import argparse
import json
import os
import subprocess
import threading
from pathlib import Path

from research_demo import audit_spool

PROJECT_DIR = Path(__file__).resolve().parent
AUDITLOG_BIN = Path(
    os.environ.get("AUDITLOG_BIN", PROJECT_DIR.parent / "AuditLog/target/debug/auditlog")
)
DATA_DIR = Path(os.environ.get("AUDIT_DATA_DIR", PROJECT_DIR / "audit_data"))
AGENT_IDS = os.environ.get("AUDIT_AGENT_IDS", "agent_0,agent_1,agent_2").split(",")


def publish_once() -> list[dict]:
    """Rotate each agent's spool and anchor one period per trail.

    Every agent has its own chain: an agent with pending actions anchors a
    batch, an idle one anchors a heartbeat.
    """
    receipts = []
    for agent_id in AGENT_IDS:
        rotated = audit_spool.rotate(agent_id)
        cmd = [
            str(AUDITLOG_BIN),
            "--data-dir", str(DATA_DIR),
            "ingest",
            "--agent-id", agent_id,
        ]
        if rotated is not None:
            cmd += ["--spool", str(rotated)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"auditlog ingest ({agent_id}) failed: {proc.stderr.strip()}")
        receipt = json.loads(proc.stdout)
        receipt["agent_id"] = agent_id
        receipts.append(receipt)
    return receipts


class AuditPublisher(threading.Thread):
    def __init__(self, interval_secs: float):
        super().__init__(daemon=True, name="audit-publisher")
        self.interval_secs = interval_secs
        self._stop = threading.Event()
        self.receipts: list[dict] = []

    def run(self) -> None:
        while not self._stop.wait(self.interval_secs):
            self._tick()

    def _tick(self) -> None:
        try:
            receipts = publish_once()
        except Exception as e:
            print(f"  [publisher] ERROR: {e}")
            return
        self.receipts.extend(receipts)
        for r in receipts:
            if r["entry_type"] == "batch":
                print(
                    f"  [publisher] 📦 {r['agent_id']}: anchored batch h={r['height']} "
                    f"seq {r['seq_start']}..{r['seq_end']} "
                    f"({r['outcome']}) blob {r['blob_id'][:24]}…"
                )
            else:
                print(
                    f"  [publisher] 💓 {r['agent_id']}: heartbeat h={r['height']} "
                    f"({r['outcome']})"
                )

    def stop_and_flush(self) -> None:
        """Stop the timer loop and publish whatever is still spooled."""
        self._stop.set()
        self.join(timeout=5)
        self._tick()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=60.0, help="seconds between publishes")
    args = ap.parse_args()
    print(f"Publishing spool to audit trail every {args.interval:g}s (Ctrl-C to stop)")
    pub = AuditPublisher(args.interval)
    pub.run()  # foreground
