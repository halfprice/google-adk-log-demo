"""Run the multi-agent incident-triage demo end-to-end.

Usage:
    .venv/bin/python run_demo.py

Streams every action (agent handoffs, tool calls, tool results, agent
replies) to the console as it happens, then prints where each agent's
JSONL action log was written.
"""

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent
LOG_DIR = PROJECT_DIR / "logs"

load_dotenv(PROJECT_DIR / ".env")

if not (
    os.environ.get("GOOGLE_API_KEY")
    or os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").upper() in ("TRUE", "1")
):
    sys.exit(
        "No Gemini credentials found.\n"
        "Either put GOOGLE_API_KEY=<your key> in .env (get one at "
        "https://aistudio.google.com/apikey),\n"
        "or set GOOGLE_GENAI_USE_VERTEXAI=TRUE and GOOGLE_CLOUD_PROJECT/"
        "GOOGLE_CLOUD_LOCATION after `gcloud auth application-default login`."
    )

from google.adk.runners import InMemoryRunner  # noqa: E402  (needs env loaded first)
from google.genai import types  # noqa: E402

from research_demo.agent import root_agent  # noqa: E402

USER_QUERY = (
    "Users are reporting that checkout is extremely slow, some requests are "
    "timing out. Please investigate checkout-service and file an incident."
)


def show(label: str, body: str = "", indent: int = 2) -> None:
    pad = " " * indent
    print(f"{pad}{label}" + (f" {body}" if body else ""))


async def main() -> None:
    # Start each run with fresh per-agent logs.
    if LOG_DIR.exists():
        shutil.rmtree(LOG_DIR)

    runner = InMemoryRunner(agent=root_agent, app_name="research_demo")
    session = await runner.session_service.create_session(
        app_name="research_demo", user_id="demo-user"
    )

    print("=" * 72)
    print("USER:", USER_QUERY)
    print("=" * 72)

    current_author = None
    async for event in runner.run_async(
        user_id="demo-user",
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=USER_QUERY)]),
    ):
        if event.author != current_author:
            current_author = event.author
            print(f"\n--- [{current_author}] " + "-" * (50 - len(current_author or "")))

        for call in event.get_function_calls():
            show("🔧 tool_call:", f"{call.name}({json.dumps(dict(call.args or {}))})")
        for resp in event.get_function_responses():
            brief = json.dumps(resp.response, default=str)
            show("↩  tool_result:", brief[:160] + ("…" if len(brief) > 160 else ""))
        if event.content and event.content.parts:
            text = " ".join(
                p.text for p in event.content.parts if getattr(p, "text", None)
            ).strip()
            if text:
                show("💬", text if event.is_final_response() else text[:300])

    print("\n" + "=" * 72)
    print("Per-agent action logs (JSONL):")
    for log_file in sorted(LOG_DIR.glob("*.jsonl")):
        lines = log_file.read_text().splitlines()
        actions = [json.loads(l)["action"] for l in lines]
        print(f"  {log_file.relative_to(PROJECT_DIR)}  ({len(lines)} actions: {', '.join(actions)})")
    print("\nInspect one with e.g.:  cat logs/triage_agent.jsonl | python3 -m json.tool --json-lines")


if __name__ == "__main__":
    asyncio.run(main())
