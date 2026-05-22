# NeuroOps — Architecture Document

---

## 1. Guiding Principles

- **Observable by default.** Every component — including the AI agents — emits structured traces and metrics. Nothing is a black box.
- **Fail safe, not fail silent.** If the agent is uncertain (confidence < 0.6), it escalates to human review rather than acting.
- **Minimal blast radius.** Destructive actions (rollback, scale-down) always require human approval. Read-only diagnosis is fully autonomous.
- **Runnable locally.** The full stack runs on a laptop with Minikube. No hard cloud dependency.

---

## 2. Component Map

```
neuroops/
├── cluster/                  # Kubernetes manifests and Helm charts
│   ├── apps/                 # Demo microservices (bookinfo or custom)
│   ├── monitoring/           # Prometheus, Jaeger, Grafana Helm values
│   └── chaos/                # LitmusChaos experiment definitions
│
├── detector/                 # Anomaly detection service
│   ├── models/               # Isolation Forest + LSTM training + inference
│   ├── scraper.py            # Prometheus metric scraper
│   ├── alerter.py            # Alert deduplication + severity classification
│   └── server.py             # FastAPI server exposing /alerts endpoint
│
├── agent/                    # LangGraph multi-agent system
│   ├── graph.py              # LangGraph graph definition (nodes + edges)
│   ├── agents/
│   │   ├── detective.py      # Metric correlation agent
│   │   ├── topologist.py     # Service dependency + Jaeger agent
│   │   ├── historian.py      # GitHub deploy history agent
│   │   └── supervisor.py     # Synthesis + decision agent
│   ├── tools/                # LangChain tools (K8s API, GitHub API, Prometheus)
│   └── tracing.py            # OTel span wrapper for every agent node
│
├── remediator/               # Remediation action engine
│   ├── actions/
│   │   ├── restart_pod.py
│   │   ├── rollback_deploy.py
│   │   ├── scale_replicas.py
│   │   ├── patch_configmap.py
│   │   └── open_github_pr.py
│   └── human_loop.py         # CLI approval flow for P2 actions
│
├── observability/            # Agent self-observability layer
│   ├── collector/            # OTel Collector config
│   ├── dashboards/           # Grafana dashboard JSON
│   └── replay.py             # CLI tool to replay incident agent traces
│
├── benchmarks/               # Chaos experiment runner + MTTR tracker
│   ├── runner.py             # Orchestrates inject → detect → remediate cycle
│   └── report.py             # Generates benchmark markdown report
│
├── docker-compose.yml        # Local stack: Prometheus, Jaeger, Grafana, OTel Collector
├── Makefile                  # Common commands (make up, make chaos, make bench)
└── README.md
```

---

## 3. Data Flow — Incident Lifecycle

```
1. INJECT
   LitmusChaos injects fault into cluster
   (pod-delete / cpu-hog / memory-hog / network-latency / disk-fill)
         │
         ▼
2. DETECT  [~15s polling interval]
   Prometheus scrapes Golden Signals from all services
   Scraper feeds rolling 10-min window to Isolation Forest
   If anomaly score > threshold → create Alert object
   Alert deduplicator checks: is this the same alert within 5 min?
   → No: classify severity (P1/P2/P3), emit to alert queue
         │
         ▼
3. DIAGNOSE  [LangGraph graph spins up]
   Supervisor Agent creates incident ID, starts OTel trace
   ┌─────────────────────────────────────────────────────┐
   │ Parallel execution (LangGraph fan-out):              │
   │  Detective Agent  → queries Prometheus for corr.    │
   │  Topologist Agent → queries Jaeger for dep. graph   │
   │  Historian Agent  → queries GitHub API for deploys  │
   └────────────────────┬────────────────────────────────┘
                        │ results
   Supervisor Agent synthesizes → root cause hypothesis + confidence
   If confidence < 0.6 → escalate to human
         │
         ▼
4. REMEDIATE
   Supervisor maps hypothesis → remediation action
   P1 (confidence ≥ 0.8, non-destructive): execute automatically
   P2 (confidence ≥ 0.6, or destructive):  prompt human via CLI
   Action executes → verify cluster state → confirm resolution
         │
         ▼
5. OBSERVE (running throughout)
   Every agent node wrapped in OTel span:
     - span.set_attribute("agent.name", ...)
     - span.set_attribute("agent.input_tokens", ...)
     - span.set_attribute("agent.decision", ...)
     - span.set_attribute("agent.tool_called", ...)
   Spans exported to Jaeger via OTLP
   Grafana shows infra trace + agent reasoning trace linked by incident_id
```

---

## 4. Agent Graph Design (LangGraph)

```python
# Conceptual graph structure
START
  └─► supervisor_init          # create incident, start OTel trace
        ├─► detective           # parallel fan-out
        ├─► topologist          # parallel fan-out
        └─► historian           # parallel fan-out
              └─► supervisor_synthesize   # fan-in, generate hypothesis
                    ├─► [confidence < 0.6] human_escalation  ──► END
                    └─► [confidence ≥ 0.6] remediator
                          └─► verifier    # confirm fix worked
                                └─► END
```

Each node is an async function. The supervisor uses structured output (JSON) to pass findings between nodes. Every node is wrapped by `tracing.traced_node()` which creates a child OTel span.

---

## 5. Agent Self-Observability — The Key Differentiator

### The problem this solves
Most LangGraph agents are black boxes. When an agent makes a wrong decision, you have no way to know which observation led it there, what the model's reasoning was, or how long each step took.

### How it works
Every agent node execution is wrapped with an OpenTelemetry span:

```python
# tracing.py
from opentelemetry import trace

tracer = trace.get_tracer("neuroops.agent")

def traced_node(agent_name: str):
    def decorator(fn):
        async def wrapper(state: AgentState, *args, **kwargs):
            with tracer.start_as_current_span(f"agent.{agent_name}") as span:
                span.set_attribute("agent.name", agent_name)
                span.set_attribute("incident.id", state["incident_id"])
                
                result = await fn(state, *args, **kwargs)
                
                span.set_attribute("agent.decision", result.get("decision", ""))
                span.set_attribute("agent.confidence", result.get("confidence", 0))
                span.set_attribute("agent.input_tokens", result.get("usage", {}).get("input_tokens", 0))
                span.set_attribute("agent.latency_ms", span.end_time - span.start_time)
                return result
        return wrapper
    return decorator
```

### What you see in Grafana
A single incident dashboard view shows:
- Top panel: infra metrics (latency spike, error rate) — from Prometheus
- Middle panel: service trace (which service called which) — from Jaeger
- Bottom panel: agent reasoning trace (which agent ran, what it decided, how long it took) — from Jaeger via OTLP

All three are correlated by `incident_id` tag.

---

## 6. Anomaly Detection Design

### Model choice: why Isolation Forest + LSTM?

**Isolation Forest** (phase 2): fast, unsupervised, excellent at point anomalies in high-dimensional metric data. No labeled training data required — critical for a new cluster.

**LSTM** (phase 2 optional enhancement): catches temporal anomalies that Isolation Forest misses — gradual degradation patterns, slow memory leaks, hourly traffic patterns.

### Feature vector per scrape window
```
[
  service_name (encoded),
  p50_latency, p95_latency, p99_latency,
  error_rate,
  request_rate,
  cpu_usage_pct,
  memory_usage_pct,
  pod_restart_count_delta,
  ready_replicas / desired_replicas
]
```

### Threshold tuning
Run the cluster under normal load for 30 minutes before enabling alerts. The Isolation Forest `contamination` parameter defaults to 0.05 (5% of samples expected to be anomalous). Adjust if false positive rate is too high.

---

## 7. Remediation Decision Tree

```
Root cause hypothesis
├── "OOMKill / memory pressure"
│   └── Scale replicas UP → if persists → open PR increasing memory limit
├── "CrashLoopBackOff"
│   ├── Recent deploy in last 60 min? → Rollback deployment
│   └── No recent deploy → Restart pod + collect logs → open GitHub issue
├── "High CPU saturation"
│   └── Scale replicas UP → if persists → escalate to human
├── "High latency (upstream dependency)"
│   └── Restart dependency pod → if persists → escalate
├── "Disk pressure on node"
│   └── Identify large logs → patch log rotation ConfigMap
└── "Unknown / confidence < 0.6"
    └── Escalate to human with full context summary
```

---

## 8. Local Setup Architecture (Docker Compose)

```yaml
# Services in docker-compose.yml
services:
  prometheus:    # Scrapes cluster (via remote_write from Minikube)
  jaeger:        # Receives traces from cluster + OTel Collector
  grafana:       # Dashboards; depends on prometheus + jaeger
  otel-collector: # Receives agent spans, forwards to Jaeger
  detector:      # NeuroOps detection service
  agent:         # NeuroOps agent service
  remediator:    # NeuroOps remediation service
```

All services communicate on a shared Docker network. Minikube exposes the cluster's Prometheus remote_write endpoint to the host.

---

## 9. Key Design Decisions & Rationale

| Decision | Chosen | Rejected | Why |
|----------|--------|----------|-----|
| Agent framework | LangGraph | AutoGen, CrewAI | LangGraph gives explicit graph control; easier to trace |
| Anomaly detection | Isolation Forest | Simple thresholds | No labeled data needed; handles multivariate anomalies |
| LLM | Claude claude-sonnet-4-6 | GPT-4o only | Better at structured JSON output; strong tool use |
| Tracing | OpenTelemetry | Custom logging | OTel is the standard; works with existing Jaeger setup |
| Local cluster | Minikube | k3d, Kind | Best Prometheus integration; widest tutorial support |
| Human-in-loop | CLI prompt | Web UI | Simpler to build; same signal for demos |
