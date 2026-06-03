import os
import time
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Response
from graph import graph
from incident_store import IncidentStore
from pydantic import BaseModel
from state import AgentState, Alert

# Prometheus metrics instrumentation
try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    _prom_registry = CollectorRegistry()
    RCA_REQUESTS = Counter(
        "neuroops_rca_requests_total",
        "Total number of /investigate requests received",
        registry=_prom_registry,
    )
    RCA_ERRORS = Counter(
        "neuroops_rca_errors_total",
        "Total number of failed /investigate requests",
        registry=_prom_registry,
    )
    RCA_LATENCY = Histogram(
        "neuroops_rca_latency_seconds",
        "Latency of RCA graph execution in seconds",
        buckets=[1, 5, 10, 30, 60, 120, 300],
        registry=_prom_registry,
    )
    TOKENS_TOTAL = Counter(
        "neuroops_agent_tokens_total",
        "Cumulative LLM tokens consumed by the agent",
        registry=_prom_registry,
    )
    INCIDENTS_STORED = Gauge(
        "neuroops_incidents_stored_total",
        "Total number of incidents stored in SQLite",
        registry=_prom_registry,
    )
    _prom_enabled = True
except ImportError:
    _prom_enabled = False
    _prom_registry = None

logger = structlog.get_logger()

app = FastAPI(
    title="NeuroOps Multi-Agent RCA API",
    version="1.0.0",
    description=(
        "Autonomous AI SRE engine — Multi-Agent Root Cause Analysis, "
        "MTTR analytics, SLA tracking, incident similarity search, and "
        "OpenTelemetry-traced LangGraph diagnostics."
    ),
)

# Global dict to store incident trace reasoning history
incident_traces: dict[str, list[dict[str, Any]]] = {}
incident_store = IncidentStore()


class RootCauseHypothesis(BaseModel):
    incident_id: str
    hypothesis: str
    confidence: float
    recommended_action: str
    requires_human_approval: bool
    reasoning: str
    tokens_used: int = 0
    remediation_result: dict[str, Any] | None = None


@app.post("/investigate", response_model=RootCauseHypothesis)
async def investigate(alert: Alert, execute_remediation: bool = False):
    """Triggers the multi-agent LangGraph workflow to diagnose a Kubernetes incident."""
    logger.info(
        "Received alert for diagnostic investigation", alert_id=alert.id, service=alert.service
    )

    if _prom_enabled:
        RCA_REQUESTS.inc()

    import uuid

    incident_id = f"inc-{str(uuid.uuid4())[:8]}"
    t_start = time.time()

    # Initialize the input state
    initial_state: AgentState = {
        "incident_id": incident_id,
        "alert": alert,
        "detective_findings": None,
        "topologist_findings": None,
        "historian_findings": None,
        "log_findings": None,
        "hypothesis": None,
        "confidence": None,
        "recommended_action": None,
        "requires_human_approval": False,
        "reasoning": None,
        "tokens_used": 0,
        "execute_remediation": execute_remediation,
        "remediation_result": None,
    }

    try:
        # Execute LangGraph workflow synchronously with SQLite persistence config
        config = {"configurable": {"thread_id": incident_id}}
        final_state = await graph.ainvoke(initial_state, config=config)

        hypothesis = final_state.get("hypothesis") or "Unknown failure mode"
        confidence = final_state.get("confidence") or 0.0
        recommended_action = final_state.get("recommended_action") or "none"
        requires_human_approval = final_state.get("requires_human_approval") or False
        reasoning = final_state.get("reasoning") or "No detailed reasoning provided."
        tokens_used = int(final_state.get("tokens_used") or 0)
        remediation_result = final_state.get("remediation_result")

        # Save reasoning trace timeline
        trace_timeline = [
            {
                "step": 1,
                "agent": "supervisor_init",
                "action": "Initialized investigation and started OpenTelemetry root span.",
                "timestamp": alert.timestamp,
            },
            {
                "step": 2,
                "agent": "detective",
                "findings": final_state.get("detective_findings"),
                "action": "Analyzed Prometheus metric correlations across cluster service endpoints.",
            },
            {
                "step": 3,
                "agent": "topologist",
                "findings": final_state.get("topologist_findings"),
                "action": "Queried Jaeger trace dependency graphs to inspect latency bottlenecks.",
            },
            {
                "step": 4,
                "agent": "historian",
                "findings": final_state.get("historian_findings"),
                "action": "Inspected GitHub commit logs and deployment timelines.",
            },
            {
                "step": 5,
                "agent": "log_analyser",
                "findings": final_state.get("log_findings"),
                "action": "Scraped and parsed active container logs for unhandled exceptions.",
            },
            {
                "step": 6,
                "agent": "supervisor_synthesize",
                "action": "Fused multiple diagnostic findings into root cause hypothesis.",
                "hypothesis": hypothesis,
                "confidence": confidence,
                "recommended_action": recommended_action,
                "requires_human_approval": requires_human_approval,
                "reasoning": reasoning,
            },
        ]
        incident_traces[incident_id] = trace_timeline

        # Compute MTTR: alert timestamp → resolution
        t_end = time.time()
        rca_duration = t_end - t_start
        mttr_seconds = t_end - float(alert.timestamp) if alert.timestamp else rca_duration

        if _prom_enabled:
            RCA_LATENCY.observe(rca_duration)
            TOKENS_TOTAL.inc(tokens_used)

        # Persist incident with full MTTR and metric snapshot
        incident_store.save_incident(
            incident_id=incident_id,
            service=alert.service,
            alert_id=alert.id,
            hypothesis=hypothesis,
            confidence=confidence,
            recommended_action=recommended_action,
            requires_human_approval=requires_human_approval,
            reasoning=reasoning,
            tokens_used=tokens_used,
            remediation_result=remediation_result,
            trace_timeline=trace_timeline,
            alert_timestamp=float(alert.timestamp),
            resolved_at=t_end,
            mttr_seconds=mttr_seconds,
            metric_snapshot=dict(alert.metric_snapshot),
        )

        if _prom_enabled:
            INCIDENTS_STORED.set(len(incident_store.list_incidents(limit=10000)))

        logger.info(
            "Investigation completed successfully",
            incident_id=incident_id,
            hypothesis=hypothesis,
            confidence=confidence,
            mttr_seconds=round(mttr_seconds, 2),
        )

        return RootCauseHypothesis(
            incident_id=incident_id,
            hypothesis=hypothesis,
            confidence=confidence,
            recommended_action=recommended_action,
            requires_human_approval=requires_human_approval,
            reasoning=reasoning,
            tokens_used=tokens_used,
            remediation_result=remediation_result,
        )
    except Exception as e:
        if _prom_enabled:
            RCA_ERRORS.inc()
        logger.error("Failed executing RCA graph", error=str(e))
        raise HTTPException(status_code=500, detail=f"Diagnostic error: {str(e)}")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "persisted_incidents": len(incident_store.list_incidents(limit=1000)),
    }


@app.get("/metrics")
async def prometheus_metrics():
    """Exposes Prometheus-format metrics for scraping by Grafana / kube-prometheus."""
    if not _prom_enabled:
        return Response(content="# prometheus_client not installed", media_type="text/plain")
    return Response(
        content=generate_latest(_prom_registry),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/incidents", response_model=list[dict[str, Any]])
async def list_incidents(limit: int = 100):
    return incident_store.list_incidents(limit=limit)


@app.get("/incidents/{incident_id}/trace", response_model=list[dict[str, Any]])
async def get_incident_trace(incident_id: str):
    """Returns a step-by-step audit replay of the agent's reasoning steps for a given incident."""
    logger.info("Requesting incident trace", incident_id=incident_id)
    if incident_id in incident_traces:
        return incident_traces[incident_id]

    persisted_trace = incident_store.get_trace(incident_id)
    if persisted_trace is None:
        raise HTTPException(status_code=404, detail=f"Incident trace for {incident_id} not found.")
    return persisted_trace


@app.get("/incidents/{incident_id}/similar")
async def get_similar_incidents(incident_id: str, top_k: int = 3):
    """
    Finds the top-k most similar past incidents using cosine similarity on metric snapshot vectors.
    Returns historical precedents with their diagnoses and recommended actions.
    The Supervisor agent uses this to gain historical context during diagnosis.
    """
    import json as _json
    import sqlite3 as _sqlite3

    db_path = os.getenv("AGENT_DB_PATH", "checkpoints/agent_incidents.db")
    metric_snapshot: dict[str, float] = {}
    try:
        with _sqlite3.connect(db_path) as conn:
            conn.row_factory = _sqlite3.Row
            row = conn.execute(
                "SELECT metric_snapshot_json FROM incidents WHERE incident_id = ?",
                (incident_id,),
            ).fetchone()
        if row and row["metric_snapshot_json"]:
            metric_snapshot = _json.loads(row["metric_snapshot_json"])
    except Exception:
        pass

    if not metric_snapshot:
        raise HTTPException(
            status_code=404, detail=f"Incident '{incident_id}' not found or has no metric snapshot."
        )

    similar = incident_store.find_similar_incidents(
        metric_snapshot=metric_snapshot,
        exclude_incident_id=incident_id,
        top_k=top_k,
    )
    return {
        "incident_id": incident_id,
        "top_k": top_k,
        "similar_incidents": [item for _, item in similar],
    }


# ── Analytics Endpoints ────────────────────────────────────────────────────────


@app.get("/analytics/mttr")
async def analytics_mttr():
    """
    Returns p50, p95, p99 MTTR statistics across all resolved incidents.
    Includes per-service breakdown and autonomous resolution rate.
    """
    return incident_store.get_mttr_stats()


@app.get("/analytics/sla")
async def analytics_sla(threshold_seconds: float = 300.0):
    """
    Returns SLA breach statistics. Incidents exceeding `threshold_seconds` MTTR
    are considered SLA breaches. Target autonomous resolution rate is >= 70%.
    """
    return incident_store.get_sla_status(sla_threshold_seconds=threshold_seconds)


@app.get("/analytics/cost")
async def analytics_cost():
    """
    Returns cumulative and per-incident LLM token usage and estimated $ costs.
    Based on Claude Sonnet pricing: $15.00 per million tokens.
    """
    return incident_store.get_cost_stats()
