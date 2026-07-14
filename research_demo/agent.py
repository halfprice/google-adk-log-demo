"""Multi-agent incident-triage pipeline.

Three specialist agents collaborate via a SequentialAgent. They hand work
to each other through shared session state: each agent writes its result
under an output_key, and the next agent's instruction reads it back with
{placeholder} syntax.

    triage_agent    -> gathers evidence with tools     -> state["findings"]
    analysis_agent  -> digs into dependencies, RCA     -> state["diagnosis"]
    report_agent    -> files the incident report (tool)

Every agent has the JSONL logging callbacks attached, so each produces its
own action log under logs/.
"""

import os

from google.adk.agents import LlmAgent, SequentialAgent

from .action_logger import LOGGING_CALLBACKS
from .tools import fetch_service_metrics, file_incident_report, search_knowledge_base

MODEL = os.environ.get("DEMO_MODEL", "gemini-2.5-flash")

triage_agent = LlmAgent(
    name="agent_0",
    model=MODEL,
    description="Gathers evidence about a reported production issue.",
    instruction=(
        "You are the on-call triage engineer. The user reports a production "
        "issue. Gather evidence:\n"
        "1. Search the knowledge base for relevant runbooks/past incidents.\n"
        "2. Fetch current metrics for the affected service.\n"
        "Then summarize the symptoms and list which dependencies look "
        "suspicious and should be investigated next. Be concise and factual."
    ),
    tools=[search_knowledge_base, fetch_service_metrics],
    output_key="findings",
    **LOGGING_CALLBACKS,
)

analysis_agent = LlmAgent(
    name="agent_1",
    model=MODEL,
    description="Determines the root cause from the triage findings.",
    instruction=(
        "You are a senior SRE doing root-cause analysis.\n\n"
        "Triage findings from the previous agent:\n{findings}\n\n"
        "Fetch metrics for each suspicious dependency named in the findings "
        "to confirm or rule it out. Then state the most likely root cause in "
        "one sentence, the evidence for it, and a recommended fix."
    ),
    tools=[fetch_service_metrics],
    output_key="diagnosis",
    **LOGGING_CALLBACKS,
)

report_agent = LlmAgent(
    name="agent_2",
    model=MODEL,
    description="Files the incident report and briefs the user.",
    instruction=(
        "You are the incident scribe.\n\n"
        "Diagnosis from the previous agent:\n{diagnosis}\n\n"
        "File an incident report with the file_incident_report tool (pick an "
        "appropriate severity). Then reply to the user with the ticket id "
        "and a 3-4 sentence plain-language summary of what happened, the "
        "root cause, and the recommended fix."
    ),
    tools=[file_incident_report],
    **LOGGING_CALLBACKS,
)

root_agent = SequentialAgent(
    name="incident_pipeline",
    description="Triage -> root-cause analysis -> incident report.",
    sub_agents=[triage_agent, analysis_agent, report_agent],
)
