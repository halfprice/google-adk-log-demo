"""Mock tools that simulate RPCs to backend services.

Each tool sleeps briefly to mimic network latency and returns canned data,
so the demo runs fully offline (only the LLM calls leave your machine).
The data is rigged so there is a real root cause to discover: the
checkout-service is slow because payments-db's connection pool is saturated.
"""

import os
import time

# Simulated latency per "RPC", in seconds. Raising it stretches the demo's
# wall-clock (so more audit batches anchor mid-run) at zero extra LLM calls.
_RPC_LATENCY = float(os.environ.get("DEMO_RPC_LATENCY", "0.2"))

_KNOWLEDGE_BASE = {
    "checkout": [
        {
            "doc_id": "runbook-042",
            "title": "Checkout service runbook",
            "snippet": (
                "checkout-service depends on payments-db and inventory-api. "
                "High p99 latency is most often caused by a downstream "
                "dependency. Check dependency metrics before restarting."
            ),
        },
        {
            "doc_id": "postmortem-117",
            "title": "2026-03-11 checkout latency incident",
            "snippet": (
                "Previous incident: payments-db connection pool exhaustion "
                "caused checkout p99 to exceed 4s. Fix was raising pool size "
                "and adding connection recycling."
            ),
        },
    ],
    "payments": [
        {
            "doc_id": "runbook-019",
            "title": "Payments DB operations guide",
            "snippet": (
                "payments-db runs with a default pool of 50 connections. "
                "Saturation shows up as pool_wait_ms > 500."
            ),
        },
    ],
}

_SERVICE_METRICS = {
    "checkout-service": {
        "p50_latency_ms": 180,
        "p99_latency_ms": 4300,
        "error_rate_pct": 3.8,
        "requests_per_sec": 220,
        "status": "DEGRADED",
        "dependencies": ["payments-db", "inventory-api"],
    },
    "payments-db": {
        "p50_latency_ms": 2100,
        "p99_latency_ms": 5800,
        "connection_pool_in_use": 50,
        "connection_pool_size": 50,
        "pool_wait_ms": 1450,
        "status": "SATURATED",
        "dependencies": [],
    },
    "inventory-api": {
        "p50_latency_ms": 35,
        "p99_latency_ms": 90,
        "error_rate_pct": 0.1,
        "status": "HEALTHY",
        "dependencies": [],
    },
}


def search_knowledge_base(query: str) -> dict:
    """Search the internal knowledge base for runbooks and past incidents.

    Args:
        query: Free-text search query, e.g. a service name or symptom.

    Returns:
        A dict with a list of matching documents (doc_id, title, snippet).
    """
    time.sleep(_RPC_LATENCY)
    query_lower = query.lower()
    results = []
    for keyword, docs in _KNOWLEDGE_BASE.items():
        if keyword in query_lower:
            results.extend(docs)
    if not results:
        # Fall back to the checkout docs so the demo never dead-ends.
        results = _KNOWLEDGE_BASE["checkout"]
    return {"query": query, "results": results}


def fetch_service_metrics(service_name: str) -> dict:
    """Fetch current metrics for a service via the monitoring RPC.

    Args:
        service_name: One of: checkout-service, payments-db, inventory-api.

    Returns:
        A dict of current metrics for the service, including its
        dependencies, or an error if the service is unknown.
    """
    time.sleep(_RPC_LATENCY)
    metrics = _SERVICE_METRICS.get(service_name.strip().lower())
    if metrics is None:
        return {
            "error": f"unknown service '{service_name}'",
            "known_services": sorted(_SERVICE_METRICS),
        }
    return {"service": service_name, "metrics": metrics}


def file_incident_report(title: str, severity: str, root_cause: str, summary: str) -> dict:
    """File an incident report in the (simulated) ticketing system.

    Args:
        title: Short incident title.
        severity: One of: SEV1, SEV2, SEV3.
        root_cause: One-sentence root cause.
        summary: Longer description of findings and recommended fix.

    Returns:
        A dict with the created ticket id and status.
    """
    time.sleep(_RPC_LATENCY)
    return {
        "ticket_id": "INC-20260714-001",
        "status": "FILED",
        "title": title,
        "severity": severity,
        "root_cause": root_cause,
        "summary": summary,
    }
