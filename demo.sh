#!/usr/bin/env bash
# One-shot demo runner: builds the audit-trail binary, sets up the Python
# environment, checks credentials, and runs the full live demo
# (agents → per-minute anchoring → verification endpoint → tamper detection).
#
# Usage:
#   ./demo.sh                 # full demo, publish every 15s
#   ./demo.sh --interval 60   # production cadence
#   ./demo.sh --keep-serving  # leave the verify endpoint running afterward
set -euo pipefail
cd "$(dirname "$0")"

# Audit trail implementation: https://github.com/halfprice/AuditLog
AUDITLOG_DIR="${AUDITLOG_DIR:-../AuditLog}"
BIN="$AUDITLOG_DIR/target/debug/auditlog"

echo "==> [1/4] Building the audit-trail binary (cargo build in $AUDITLOG_DIR)"
command -v cargo >/dev/null || { echo "ERROR: cargo not found — install Rust (https://rustup.rs)"; exit 1; }
[ -d "$AUDITLOG_DIR" ] || { echo "ERROR: $AUDITLOG_DIR not found — run: git clone https://github.com/halfprice/AuditLog $AUDITLOG_DIR"; exit 1; }
(cd "$AUDITLOG_DIR" && cargo build --quiet)
[ -x "$BIN" ] || { echo "ERROR: build did not produce $BIN"; exit 1; }

echo "==> [2/4] Setting up the Python environment"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --quiet -r requirements.txt

echo "==> [3/4] Checking Gemini credentials in .env"
if ! grep -qE '^GOOGLE_API_KEY=.+' .env 2>/dev/null && ! grep -qE '^GOOGLE_GENAI_USE_VERTEXAI=(TRUE|1)' .env 2>/dev/null; then
    echo "ERROR: no credentials. Put GOOGLE_API_KEY=<key> in .env"
    echo "       (free key: https://aistudio.google.com/apikey)"
    exit 1
fi

echo "==> [4/4] Running the demo"
exec .venv/bin/python run_audit_demo.py "$@"
