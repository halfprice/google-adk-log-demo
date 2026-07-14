"""Per-agent JSONL action logging via ADK callbacks.

Every agent in the pipeline gets these callbacks attached. Each callback
appends one JSON line to logs/<agent_name>.jsonl, so at the end of a run
you have a separate, replayable action log per agent covering:

  agent_start / agent_end   - the agent's turn in the pipeline
  llm_request / llm_response - every model call (with token usage)
  tool_call / tool_result    - every tool ("RPC") invocation

All callbacks return None so they observe without altering agent behavior.
"""

import json
import os
import time
from pathlib import Path

from .audit_spool import spool_record

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def _write(agent_name: str, action: str, detail: dict) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "agent": agent_name,
        "action": action,
        **detail,
    }
    path = LOG_DIR / f"{agent_name}.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(record, default=str) + "\n")
    # Same record, second sink: the tamper-evident audit trail's spool.
    if os.environ.get("AUDIT_SPOOL", "1") != "0":
        spool_record(record)


def _truncate(text: str, limit: int = 300) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "…"


# --- agent lifecycle -------------------------------------------------------
# ADK invokes every callback with keyword arguments, so parameter names must
# match: callback_context / llm_request / llm_response / tool / args /
# tool_context / tool_response.

def log_agent_start(callback_context) -> None:
    ctx = callback_context
    _write(ctx.agent_name, "agent_start", {"invocation_id": ctx.invocation_id})


def log_agent_end(callback_context) -> None:
    ctx = callback_context
    _write(ctx.agent_name, "agent_end", {"invocation_id": ctx.invocation_id})


# --- model calls -----------------------------------------------------------

def log_llm_request(callback_context, llm_request) -> None:
    ctx = callback_context
    detail = {"model": getattr(llm_request, "model", None)}
    contents = getattr(llm_request, "contents", None) or []
    detail["history_messages"] = len(contents)
    # Record the latest text part the model is being asked to act on.
    for content in reversed(contents):
        texts = [p.text for p in (content.parts or []) if getattr(p, "text", None)]
        if texts:
            detail["latest_input"] = _truncate(" ".join(texts))
            break
    _write(ctx.agent_name, "llm_request", detail)


def log_llm_response(callback_context, llm_response) -> None:
    ctx = callback_context
    detail = {}
    content = getattr(llm_response, "content", None)
    if content and content.parts:
        texts, calls = [], []
        for part in content.parts:
            if getattr(part, "text", None):
                texts.append(part.text)
            fc = getattr(part, "function_call", None)
            if fc:
                calls.append({"tool": fc.name, "args": dict(fc.args or {})})
        if texts:
            detail["text"] = _truncate(" ".join(texts))
        if calls:
            detail["requested_tool_calls"] = calls
    usage = getattr(llm_response, "usage_metadata", None)
    if usage:
        detail["tokens"] = {
            "prompt": getattr(usage, "prompt_token_count", None),
            "response": getattr(usage, "candidates_token_count", None),
        }
    _write(ctx.agent_name, "llm_response", detail)


# --- tool ("RPC") calls ----------------------------------------------------

def log_tool_call(tool, args, tool_context) -> None:
    _write(tool_context.agent_name, "tool_call", {"tool": tool.name, "args": args})


def log_tool_result(tool, args, tool_context, tool_response) -> None:
    _write(
        tool_context.agent_name,
        "tool_result",
        {"tool": tool.name, "response": _truncate(json.dumps(tool_response, default=str), 500)},
    )


# Bundle for attaching to every LlmAgent in one line.
LOGGING_CALLBACKS = dict(
    before_agent_callback=log_agent_start,
    after_agent_callback=log_agent_end,
    before_model_callback=log_llm_request,
    after_model_callback=log_llm_response,
    before_tool_callback=log_tool_call,
    after_tool_callback=log_tool_result,
)
