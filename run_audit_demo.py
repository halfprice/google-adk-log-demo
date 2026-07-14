"""End-to-end demo: live multi-agent actions → tamper-evident audit trail →
HTTP verification endpoint.

Flow:
  1. Fresh audit trail (https://github.com/halfprice/AuditLog mock chain)
     + verification server.
  2. The audit publisher anchors the action spool on a timer (production:
     every minute; demo default: every 15s), heartbeating idle periods.
  3. The ADK incident pipeline runs live; every agent action is logged
     locally AND spooled into the signed, hash-chained trail.
  4. The anchored log is exported and POSTed to /verify → authentic.
  5. A tampered copy is POSTed → tampering pinpointed and rejected.

Usage:
    .venv/bin/python run_audit_demo.py [--interval 15] [--port 8600] [--keep-serving]
"""

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

# Must run before any research_demo import: agent.py reads DEMO_MODEL at import time.
load_dotenv(Path(__file__).resolve().parent / ".env")

# Stretch each mock RPC so the run lasts ~30s and several audit batches anchor
# live — costs zero extra LLM calls. Override with DEMO_RPC_LATENCY.
import os
os.environ.setdefault("DEMO_RPC_LATENCY", "2.0")

import audit_publisher
from audit_publisher import AUDITLOG_BIN, AGENT_IDS, DATA_DIR, AuditPublisher
from research_demo.audit_spool import SPOOL_DIR

PROJECT_DIR = Path(__file__).resolve().parent
TAMPERED = PROJECT_DIR / "tampered_log.jsonl"


def exported_path(agent: str) -> Path:
    return PROJECT_DIR / f"exported_{agent}.jsonl"


def banner(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def reset_state() -> None:
    for d in (DATA_DIR, SPOOL_DIR):
        shutil.rmtree(d, ignore_errors=True)
    for agent_id in AGENT_IDS:
        out = subprocess.run(
            [str(AUDITLOG_BIN), "--data-dir", str(DATA_DIR), "init", "--agent-id", agent_id],
            capture_output=True, text=True, check=True,
        ).stdout
        info = json.loads(out)
        print(f"  trail {info['trail_id']} created; key {info['pubkey'][:16]}… registered on chain")


def start_server(port: int) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "verify_server:app",
         "--port", str(port), "--log-level", "warning"],
        cwd=PROJECT_DIR,
    )
    for _ in range(50):
        try:
            if requests.get(f"http://127.0.0.1:{port}/health", timeout=1).ok:
                return proc
        except requests.ConnectionError:
            time.sleep(0.2)
    proc.terminate()
    raise RuntimeError("verification server did not come up")


def export_anchored_log(agent: str) -> int:
    """Concatenate one agent's anchored raw log files, in seq order."""
    storage_root = DATA_DIR / "storage" / agent
    parts = sorted(storage_root.glob("*/part-*.jsonl"),
                   key=lambda p: (int(p.parent.name), p.name))
    dest = exported_path(agent)
    with dest.open("w") as out:
        for p in parts:
            out.write(p.read_text())
    return sum(1 for _ in dest.open())


def make_tampered_copy() -> str:
    """Flip one action in agent_2's exported log — the classic insider rewrite."""
    lines = exported_path("agent_2").read_text().splitlines()
    for i, line in enumerate(lines):
        r = json.loads(line)
        detail = json.dumps(r["action"])
        if r["action"].get("action") == "tool_call" and "file_incident_report" in detail:
            old = r["action"]["args"].get("severity", "SEV1")
            r["action"]["args"]["severity"] = "SEV3"  # downgrade the incident
            lines[i] = json.dumps(r)
            what = f"seq {r['seq']}: rewrote the filed incident severity {old} → SEV3"
            break
    else:  # fallback: alter the first record's timestamp
        r = json.loads(lines[0])
        r["action"]["ts"] = "1999-01-01T00:00:00"
        lines[0] = json.dumps(r)
        what = f"seq {r['seq']}: rewrote the record timestamp"
    TAMPERED.write_text("\n".join(lines) + "\n")
    return what


def show_verdict(report: dict) -> None:
    if report.get("authentic"):
        print(f"  ✅ AUTHENTIC — {report.get('agent_id', '?')}: "
              f"{report['records_provided']} records checked against "
              f"{len(report['batches'])} anchored batch(es)")
        for b in report["batches"]:
            print(f"     h={b['height']} seq {b['batch_seq_start']}..{b['batch_seq_end']} "
                  f"[{b['mode']}] — {sum(c['ok'] for c in b['checks'])}/{len(b['checks'])} checks passed")
    else:
        print("  ❌ NOT AUTHENTIC")
        for p in report.get("problems", []):
            print(f"     ✘ {p}")
        for b in report.get("batches", []):
            for c in b["checks"]:
                if not c["ok"]:
                    print(f"     ✘ batch h={b['height']}: {c['name']}: {c['detail']}")
        if "error" in report:
            print(f"     ✘ {report['error']}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=15.0,
                    help="publish interval in seconds (production: 60)")
    ap.add_argument("--port", type=int, default=8600)
    ap.add_argument("--keep-serving", action="store_true",
                    help="leave the verification server running at the end")
    args = ap.parse_args()

    if not AUDITLOG_BIN.exists():
        sys.exit(
            f"auditlog binary not found at {AUDITLOG_BIN} — clone "
            "https://github.com/halfprice/AuditLog next to this repo and run `cargo build`"
        )

    banner("1. Setup: fresh audit trail + verification endpoint")
    reset_state()
    server = start_server(args.port)
    print(f"  verification endpoint: http://127.0.0.1:{args.port}  (/verify, /audit, /trail)")

    publisher = AuditPublisher(args.interval)
    publisher.start()
    print(f"  publisher: anchoring the action spool every {args.interval:g}s "
          f"(production cadence: every minute)")

    try:
        banner("2. Live run: agents act; every action is logged AND spooled to the trail")
        import run_demo  # loads .env, checks credentials
        for attempt in range(1, 4):
            try:
                await run_demo.main()
                break
            except Exception as e:
                if attempt == 3:
                    raise
                print(f"\n  pipeline attempt {attempt} failed ({type(e).__name__}: "
                      f"{str(e)[:120]}) — retrying in 30s; the trail keeps anchoring meanwhile")
                await asyncio.sleep(30)

        banner("3. Sealing the trails")
        publisher.stop_and_flush()
        # One idle tick → heartbeats, so silence after the run is also anchored.
        publisher._tick()
        batches = [r for r in publisher.receipts if r["entry_type"] == "batch"]
        heartbeats = [r for r in publisher.receipts if r["entry_type"] == "heartbeat"]
        print(f"  anchored across {len(AGENT_IDS)} trails: {len(batches)} batch(es), "
              f"{len(heartbeats)} heartbeat(s)")

        for agent_id in AGENT_IDS:
            n = export_anchored_log(agent_id)
            print(f"  exported {n} signed records → {exported_path(agent_id).name}")

        banner("4. Verify each agent's log via POST /verify")
        for agent_id in AGENT_IDS:
            report = requests.post(f"http://127.0.0.1:{args.port}/verify",
                                   data=exported_path(agent_id).read_bytes(),
                                   timeout=30).json()
            show_verdict(report)

        banner("5. Tamper with the log, verify again")
        what = make_tampered_copy()
        print(f"  tampered copy: {what}")
        report = requests.post(f"http://127.0.0.1:{args.port}/verify",
                               data=TAMPERED.read_bytes(), timeout=30).json()
        show_verdict(report)

        banner("6. Full-trail audit (GET /audit)")
        audit = requests.get(f"http://127.0.0.1:{args.port}/audit", timeout=30).json()
        for t in audit["trails"]:
            print(f"  trail {t['trail_id']}: {len(t['entries'])} anchored entries, "
                  f"{'ALL CHECKS PASS ✅' if audit['ok'] else 'FAILURES FOUND ❌'}")

        exported_names = ", ".join(exported_path(a).name for a in AGENT_IDS)
        print(f"\nArtifacts: {exported_names}, {TAMPERED.name}, audit_data/, logs/")
        print("Verify any log yourself:")
        print(f"  curl -s --data-binary @exported_agent_0.jsonl http://127.0.0.1:{args.port}/verify | python3 -m json.tool")
    finally:
        if args.keep_serving:
            print(f"\nVerification server left running on port {args.port} (Ctrl-C to stop it).")
            server.wait()
        else:
            server.terminate()


if __name__ == "__main__":
    asyncio.run(main())
