# NeuroOps — Phase-by-Phase Build Plan
## With Antigravity Mission Prompts

Each phase has a clear deliverable, a done checklist, and an exact prompt to paste into Antigravity's Agent Manager.

---

## Phase 0 — Project Bootstrap (Day 1, ~2 hours)

**Goal:** Get the repo skeleton, local cluster, and observability stack running.

**Deliverables:**
- Minikube cluster running with a demo app (Istio bookinfo or custom 3-service app)
- Prometheus scraping cluster metrics
- Jaeger receiving traces
- Grafana showing dashboards
- Docker Compose bringing up everything in one command

**Done when:**
- [ ] `make up` starts the full local stack without errors
- [ ] Grafana at `localhost:3000` shows Kubernetes metrics
- [ ] Jaeger at `localhost:16686` shows service traces
- [ ] At least 3 microservices running in Minikube

---

### 🤖 Antigravity Mission Prompt — Phase 0

Paste this into Antigravity Agent Manager → New Mission:

```
Mission: NeuroOps Phase 0 — Project Bootstrap

Set up a complete local Kubernetes observability stack for a project called NeuroOps. Do the following:

1. Create a Minikube-based Kubernetes cluster configuration. Write Helm values files for:
   - kube-prometheus-stack (Prometheus + Grafana + AlertManager)
   - Jaeger all-in-one (for distributed tracing)
   - OpenTelemetry Collector (config: receives OTLP from localhost:4317, exports to Jaeger)

2. Create a demo application in cluster/apps/ — 3 microservices (frontend, backend, database-stub) 
   that call each other and emit traces. Use Python FastAPI. Each service should:
   - Accept HTTP requests
   - Call the next service in the chain
   - Emit OpenTelemetry traces (use opentelemetry-instrumentation-fastapi)
   - Have a /metrics endpoint compatible with Prometheus

3. Write a docker-compose.yml that runs Prometheus, Jaeger, Grafana, and OTel Collector locally,
   with Grafana pre-configured to use Prometheus and Jaeger as datasources.

4. Write a Makefile with these targets:
   - `make cluster-up`: start Minikube + deploy all Helm charts + deploy demo apps
   - `make up`: start Docker Compose stack (Prometheus, Jaeger, Grafana, OTel Collector)
   - `make down`: tear everything down
   - `make status`: show running pods and services

5. Write a README.md with step-by-step setup instructions.

Constraints:
- All container images must be publicly available (no private registries)
- Python services must have requirements.txt
- Everything must work on macOS and Linux
- No hardcoded IPs — use service names and environment variables
```

---

## Phase 1 — Anomaly Detection Engine (Week 1, ~5 days)

**Goal:** Build the ML detection layer that watches Prometheus metrics and fires alerts when something is wrong.

**Deliverables:**
- `detector/scraper.py` — pulls Golden Signals from Prometheus every 15 seconds
- `detector/models/isolation_forest.py` — trains on baseline data, scores new windows
- `detector/alerter.py` — deduplicates, classifies severity (P1/P2/P3)
- `detector/server.py` — FastAPI server with `/alerts` and `/health` endpoints
- Unit tests with >80% coverage
- Ability to manually inject a fault and see an alert fire

**Done when:**
- [ ] Scraper collects metrics from all 3 demo services
- [ ] Model trained on 30 min of normal traffic
- [ ] Pod delete on demo service triggers P1 alert within 90 seconds
- [ ] Duplicate alerts are suppressed
- [ ] `GET /alerts` returns active alerts as JSON

---

### 🤖 Antigravity Mission Prompt — Phase 1

```
Mission: NeuroOps Phase 1 — Anomaly Detection Engine

Build the anomaly detection service for NeuroOps in the detector/ directory.
Read PRD.md and ARCHITECTURE.md first for full context.

1. detector/scraper.py
   - Connect to Prometheus at PROMETHEUS_URL (env var, default: http://localhost:9090)
   - Scrape these metrics every 15 seconds for all services:
     * http_request_duration_seconds (p50, p95, p99 via quantile query)
     * http_requests_total (rate over 1m)
     * http_errors_total (rate over 1m) — error rate = errors/requests
     * container_cpu_usage_seconds_total
     * container_memory_working_set_bytes
     * kube_pod_container_status_restarts_total (delta)
   - Output: list of MetricWindow objects (service_name, timestamp, feature_vector dict)

2. detector/models/isolation_forest.py
   - IsolationForest from scikit-learn, contamination=0.05
   - fit(windows: list[MetricWindow]) — trains on baseline
   - score(window: MetricWindow) -> float — returns anomaly score (-1 to 0, lower = more anomalous)
   - predict(window: MetricWindow) -> bool — True if anomaly
   - save(path) / load(path) using joblib
   - Include a baseline_collector.py script that collects 30 min of data and trains the model

3. detector/alerter.py
   - Input: stream of MetricWindow objects + IsolationForest predictions
   - Deduplication: suppress alerts for the same service within 5 minutes
   - Severity classification:
     * P1: anomaly score < -0.5 AND (error_rate > 0.1 OR pod_restarts > 3)
     * P2: anomaly score < -0.3
     * P3: everything else
   - Output: Alert objects with fields: id, service, severity, timestamp, metric_snapshot, anomaly_score

4. detector/server.py
   - FastAPI app
   - GET /alerts — returns list of active Alert objects as JSON
   - GET /health — returns {"status": "ok", "model_loaded": bool}
   - POST /baseline/train — triggers baseline data collection + model training
   - Background task: runs scraper + alerter in a loop

5. Tests in detector/tests/:
   - test_scraper.py: mock Prometheus HTTP responses, verify correct metric extraction
   - test_model.py: inject synthetic anomaly vectors, verify detection
   - test_alerter.py: verify deduplication and severity classification logic
   - Use pytest, aim for >80% coverage

Constraints:
- Use Python 3.11+
- All config via environment variables (never hardcoded)
- Type hints on all functions
- Structured logging with structlog
- Docker-friendly: include a Dockerfile for the detector service
```

---

## Phase 2 — Multi-Agent RCA System (Week 2–3, ~8 days)

**Goal:** Build the LangGraph agent graph that diagnoses incidents when the detector fires an alert.

**Deliverables:**
- `agent/graph.py` — LangGraph graph with 4 agents wired together
- `agent/agents/` — all 4 agent implementations
- `agent/tools/` — K8s, GitHub, and Prometheus LangChain tools
- `agent/tracing.py` — OTel span wrapper
- Integration test: alert in → RCA hypothesis out, with full trace in Jaeger

**Done when:**
- [ ] Detective, Topologist, Historian run in parallel on every alert
- [ ] Supervisor produces a structured hypothesis with confidence score
- [ ] Low-confidence hypotheses are flagged for human review
- [ ] Every node execution appears as a span in Jaeger

---

### 🤖 Antigravity Mission Prompt — Phase 2

```
Mission: NeuroOps Phase 2 — Multi-Agent RCA System

Build the LangGraph multi-agent root cause analysis system in agent/.
Read PRD.md and ARCHITECTURE.md first. The agent graph takes an Alert as input 
and outputs a RootCauseHypothesis.

1. agent/state.py
   Define the AgentState TypedDict:
   - incident_id: str
   - alert: Alert (from detector)
   - detective_findings: dict | None
   - topologist_findings: dict | None  
   - historian_findings: dict | None
   - hypothesis: str | None
   - confidence: float | None
   - recommended_action: str | None
   - requires_human_approval: bool

2. agent/tools/k8s_tools.py
   LangChain tools wrapping the Kubernetes Python client:
   - get_pod_status(namespace, pod_name) — returns pod conditions, restart count, events
   - get_deployment_history(namespace, deployment_name) — returns rollout history
   - get_recent_events(namespace, service_name, minutes=10) — returns K8s events

3. agent/tools/github_tools.py
   LangChain tool using PyGithub:
   - get_recent_deploys(repo, minutes=60) — returns commits/releases in the last N minutes

4. agent/tools/prometheus_tools.py
   LangChain tool:
   - query_metric(promql, start, end) — returns time series as list of (timestamp, value)
   - compare_services(metric, time_window) — returns per-service breakdown

5. agent/agents/ — all agents use Claude claude-sonnet-4-6 via langchain_anthropic
   - detective.py: given the alert, queries Prometheus for correlated anomalies in other 
     services. Outputs: {"correlated_services": [], "likely_origin": str, "evidence": str}
   - topologist.py: queries Jaeger for the service dependency graph. Outputs: 
     {"upstream_services": [], "downstream_services": [], "bottleneck": str}
   - historian.py: queries GitHub for recent deployments. Outputs: 
     {"recent_deploys": [], "suspect_commit": str | None, "deploy_time": str | None}
   - supervisor.py: takes all three findings, synthesizes a hypothesis. Outputs:
     {"hypothesis": str, "confidence": float, "recommended_action": str, 
      "requires_human_approval": bool, "reasoning": str}

6. agent/tracing.py
   OTel tracer setup + traced_node() decorator as specified in ARCHITECTURE.md.
   - Init tracer with OTLP exporter to OTEL_COLLECTOR_ENDPOINT env var
   - traced_node wraps any async function, creating a child span with standard attributes

7. agent/graph.py
   LangGraph StateGraph:
   - Node: supervisor_init (creates incident_id, starts OTel root span)
   - Fan-out: detective, topologist, historian (run in parallel with asyncio)
   - Fan-in: supervisor_synthesize
   - Conditional edge: confidence < 0.6 → human_escalation node → END
   - Normal edge: supervisor_synthesize → remediator (stub for now) → END

8. agent/main.py
   - FastAPI server
   - POST /investigate: accepts Alert, runs graph, returns RootCauseHypothesis
   - GET /incidents/{incident_id}/trace: returns replay of agent reasoning steps

Constraints:
- LangGraph >= 0.2, LangChain >= 0.3
- All agents use structured output (with_structured_output)
- Max 3 LLM calls per agent node (tool calls don't count)
- Every agent node MUST use the traced_node decorator
- Handle LLM API errors with tenacity retry (max 3 attempts, exponential backoff)
```

---

## Phase 3 — Remediation Engine (Week 3, ~4 days)

**Goal:** Wire up the actions that the Supervisor agent recommends.

**Deliverables:**
- All 5 remediation actions implemented
- Human-in-the-loop CLI for P2 actions
- Verification step after each action
- End-to-end test: inject chaos → detect → diagnose → remediate → verify

**Done when:**
- [ ] `make chaos pod-delete` triggers full detect → diagnose → remediate cycle
- [ ] P1 actions execute automatically
- [ ] P2 actions pause and prompt the user
- [ ] Post-action verification confirms incident is resolved

---

### 🤖 Antigravity Mission Prompt — Phase 3

```
Mission: NeuroOps Phase 3 — Remediation Engine

Build the remediation action engine in remediator/. It receives a RootCauseHypothesis 
from the agent and executes the recommended action. Read ARCHITECTURE.md section 7 
(Remediation Decision Tree) for the full logic.

1. remediator/actions/restart_pod.py
   - restart_pod(namespace, pod_name) -> ActionResult
   - Deletes the pod (K8s will recreate it), waits up to 60s for Ready state
   - ActionResult: {success: bool, action_taken: str, duration_seconds: float}

2. remediator/actions/rollback_deploy.py  
   - rollback_deployment(namespace, deployment_name) -> ActionResult
   - Uses K8s rollout undo, waits for rollout to complete
   - Records which revision was rolled back from/to

3. remediator/actions/scale_replicas.py
   - scale_deployment(namespace, deployment_name, replicas: int) -> ActionResult
   - Scales to requested replica count, waits for all replicas to be Ready

4. remediator/actions/patch_configmap.py
   - patch_configmap(namespace, name, patch: dict) -> ActionResult
   - Applies a strategic merge patch to the ConfigMap

5. remediator/actions/open_github_pr.py
   - open_pr(repo, title, body, branch, files: dict[str, str]) -> ActionResult
   - Creates a branch, commits files, opens a PR
   - Used when the agent generates a config fix suggestion

6. remediator/human_loop.py
   - prompt_human(hypothesis: RootCauseHypothesis, action: str) -> bool
   - Prints a rich CLI summary (use rich library) of:
     * Incident summary
     * Agent reasoning chain
     * Proposed action
     * Risk level
   - Waits for y/n input with 5-minute timeout (default: n on timeout)

7. remediator/verifier.py
   - verify_resolution(alert: Alert, timeout_seconds=120) -> bool
   - Polls the detector /alerts endpoint
   - Returns True if the triggering alert is no longer active within timeout

8. remediator/server.py
   - FastAPI server
   - POST /remediate: accepts RootCauseHypothesis, executes action, returns ActionResult
   - GET /actions: returns history of all actions taken

Constraints:
- All K8s operations use the official kubernetes Python client
- All actions must be idempotent (safe to run twice)
- Never modify resources outside the target namespace
- Always log before and after every action with structlog
- P2 detection: if hypothesis.requires_human_approval is True → call human_loop first
```

---

## Phase 4 — Agent Self-Observability Dashboard (Week 4, ~3 days)

**Goal:** Build the Grafana dashboard that shows agent reasoning traces alongside infra traces — the signature differentiator of NeuroOps.

**Deliverables:**
- Grafana dashboard JSON: agent trace + infra metrics side by side
- OTel Collector configured to receive agent spans and forward to Jaeger
- `replay.py` CLI: replay any past incident's full agent reasoning trace
- Demo recording or screenshots

**Done when:**
- [ ] Grafana shows incident timeline: metric spike → agent nodes → action taken
- [ ] Can click on any agent span and see decision + confidence + tokens used
- [ ] `python replay.py --incident-id <id>` prints the full reasoning chain

---

### 🤖 Antigravity Mission Prompt — Phase 4

```
Mission: NeuroOps Phase 4 — Agent Self-Observability Dashboard

Build the observability layer that makes NeuroOps' agent reasoning visible.
This is the signature feature — an interviewer who sees this will immediately 
understand the system is production-grade.

1. observability/collector/otel-collector-config.yaml
   Configure the OpenTelemetry Collector:
   - Receivers: otlp (grpc: 4317, http: 4318)
   - Processors: batch, memory_limiter, attributes (add "component": "neuroops-agent")
   - Exporters: jaeger (endpoint: jaeger:14250), prometheus (port 8889 for agent metrics)
   - Pipelines: traces (otlp → batch → jaeger), metrics (otlp → batch → prometheus)

2. observability/dashboards/neuroops-incident.json
   A Grafana dashboard (export as JSON) with these panels, all filtered by incident_id variable:
   - Panel 1 (stat): Incident summary — service affected, severity, duration
   - Panel 2 (time series): Golden Signals during incident (latency, error rate, CPU)
   - Panel 3 (traces): Jaeger trace panel showing the infra service call graph
   - Panel 4 (table): Agent reasoning steps — columns: agent_name, decision, confidence, latency_ms, tokens_used
   - Panel 5 (stat): Total MTTR — time from alert to resolution
   Use the Jaeger datasource for trace panels, Prometheus for metrics.

3. observability/dashboards/neuroops-overview.json
   A Grafana overview dashboard:
   - Total incidents (last 7d, last 30d)
   - MTTR trend over time (line chart)
   - Autonomous resolution rate (gauge: target 70%)
   - Top 5 most common root causes (bar chart)
   - Agent cost tracker: total LLM tokens used per day

4. observability/replay.py
   CLI tool using rich and click:
   - python replay.py --incident-id <id>
   - Fetches all OTel spans for the incident from Jaeger API
   - Renders a rich terminal table showing the full agent reasoning chain:
     * Each row: timestamp | agent_name | decision | confidence | tool_called | latency_ms
   - Also shows the final hypothesis and action taken

5. Update docker-compose.yml to include the Grafana dashboard provisioning:
   Mount the dashboard JSON files as Grafana provisioning config so they load automatically.

Constraints:
- Grafana version >= 10
- Dashboard JSON must be importable via Grafana UI (not just API)
- replay.py must work without Grafana (reads directly from Jaeger API)
```

---

## Phase 5 — Chaos Benchmarks & Polish (Week 4–5, ~3 days)

**Goal:** Run real chaos experiments, measure MTTR, generate the benchmark report you'll put in your resume.

**Deliverables:**
- 5 LitmusChaos experiment definitions
- Automated benchmark runner
- Benchmark report: MTTR before vs after, autonomous resolution rate, false positive rate

**Done when:**
- [ ] All 5 chaos scenarios run cleanly
- [ ] Benchmark report generated as `benchmarks/REPORT.md`
- [ ] At least 3 scenarios show ≥ 4x MTTR improvement
- [ ] False positive rate < 10%

---

### 🤖 Antigravity Mission Prompt — Phase 5

```
Mission: NeuroOps Phase 5 — Chaos Benchmarks

Build the chaos engineering benchmark suite for NeuroOps.

1. cluster/chaos/ — LitmusChaos ChaosExperiment YAMLs for 5 scenarios:
   - pod-delete: delete the backend pod every 30 seconds for 2 minutes
   - cpu-hog: stress CPU to 90% on the frontend pod for 3 minutes
   - memory-hog: consume 80% of memory on backend pod for 3 minutes
   - network-latency: inject 500ms latency on backend→database calls for 5 minutes
   - disk-fill: fill disk to 85% on a node for 3 minutes

2. benchmarks/runner.py
   For each scenario:
   a. Record start time (t0)
   b. Apply LitmusChaos experiment via kubectl
   c. Poll detector /alerts until a P1/P2 alert fires — record detection time (t1)
   d. Poll remediator /actions until an action is taken — record action time (t2)
   e. Poll verifier until alert clears — record resolution time (t3)
   f. Metrics: detection_latency = t1-t0, diagnosis_latency = t2-t1, 
      resolution_latency = t3-t2, total_mttr = t3-t0
   g. Record whether action was autonomous or human-approved
   h. Run each scenario 3 times and average the results

3. benchmarks/report.py
   Generate benchmarks/REPORT.md:
   - Executive summary: overall MTTR improvement, autonomous resolution rate
   - Per-scenario table: baseline MTTR (estimated manual) vs agent MTTR
   - False positive rate: alerts that fired but no real incident
   - Agent cost: total LLM tokens and estimated $ cost per incident
   - Charts: render ASCII bar charts with rich (no external image dependencies)

4. Makefile additions:
   - `make chaos scenario=pod-delete`: run a single chaos scenario
   - `make bench`: run all 5 scenarios and generate report
   - `make baseline`: collect 30 min of baseline metrics for model training

Constraints:
- LitmusChaos must be installed via Helm in the cluster
- Each scenario must clean up after itself (ChaosResult TTL)
- Report must be standalone markdown (no external image URLs)
- Benchmark runner must handle timeouts gracefully (skip scenario if > 10 min)
```

---

## Timeline Summary

| Week | Phase | Key milestone |
|------|-------|---------------|
| 1 (Days 1–2) | Phase 0 | `make up` works, Grafana shows live data |
| 1 (Days 3–7) | Phase 1 | Anomaly fires within 90s of pod delete |
| 2–3 | Phase 2 | Full LangGraph RCA with Jaeger agent traces |
| 3 | Phase 3 | End-to-end: inject → detect → diagnose → fix |
| 4 | Phase 4 | Grafana shows agent + infra side by side |
| 4–5 | Phase 5 | Benchmark report with MTTR numbers |
