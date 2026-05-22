# NeuroOps — Autonomous AI SRE Agent
## Product Requirements Document (PRD)

**Version:** 1.0  
**Last updated:** May 2026  
**Status:** Active development  

---

## 1. Problem Statement

Production Kubernetes clusters generate thousands of signals per minute — metric spikes, log anomalies, failed probes, cascading pod restarts. Human SREs context-switch constantly, diagnose incidents reactively, and repeat the same remediation steps again and again. Mean Time To Resolution (MTTR) is measured in tens of minutes.

The deeper problem: every AI SRE tool built so far is a black box. When the agent takes an action, there is no way to audit why it made that decision, which observation triggered it, or what it considered and rejected. This makes production deployment of AI agents terrifying.

**NeuroOps** solves both: it autonomously detects, diagnoses, and remediates Kubernetes incidents — and uniquely, it ships with a first-class **agent self-observability layer** that traces every reasoning step the agent takes, making it auditable, debuggable, and trustworthy.

---

## 2. Goals

### Primary goals
- Reduce MTTR by at least 4x compared to manual SRE workflows
- Autonomously resolve 70%+ of common fault classes without human intervention
- Provide full OpenTelemetry traces for every agent reasoning step alongside infra traces
- Ship a benchmarked system with real chaos experiment results

### Secondary goals
- Demonstrate production AI architecture patterns for resume/portfolio
- Serve as a reference implementation for agent observability
- Keep total cloud cost under $50/month in steady state

---

## 3. Success Metrics

| Metric | Target | How to measure |
|--------|--------|----------------|
| MTTR reduction | ≥ 4x | Compare baseline vs agent-assisted incident timelines |
| Autonomous resolution rate | ≥ 70% | % of LitmusChaos faults resolved without human approval |
| False positive rate | ≤ 10% | Anomaly alerts that were not real incidents |
| Agent trace coverage | 100% | Every agent reasoning step emits an OTel span |
| P95 detection latency | ≤ 90 seconds | Time from fault injection to first alert |

---

## 4. Scope

### In scope
- Anomaly detection on the Four Golden Signals (latency, traffic, errors, saturation)
- Multi-agent root cause analysis (RCA) using LangGraph
- Auto-remediation: pod restart, deployment rollback, horizontal scaling, config patch
- Agent self-observability via OpenTelemetry spans
- Chaos engineering integration with LitmusChaos
- Grafana dashboard showing infra traces + agent reasoning traces side by side
- Human-in-the-loop approval for destructive actions (delete, scale-down, rollback)
- GitHub PR generation for config fixes

### Out of scope (v1)
- Multi-cluster management
- Cost optimization recommendations
- Security/compliance scanning
- Slack/PagerDuty integration (planned v2)
- Fine-tuning the LLM on custom incident data

---

## 5. User Stories

**As an SRE,** I want the system to detect anomalies automatically so I am not watching dashboards 24/7.

**As an SRE,** I want to see exactly why the agent took an action so I can trust it in production.

**As an SRE,** I want the agent to handle common incidents (OOMKill, CrashLoopBackOff, high latency, disk pressure) without waking me up.

**As an engineering manager,** I want MTTR benchmarks so I can justify the system to leadership.

**As a developer,** I want the agent to open a GitHub PR with a fix suggestion instead of silently modifying production.

---

## 6. Functional Requirements

### 6.1 Detection Layer
- FR-01: Scrape Prometheus metrics every 15 seconds
- FR-02: Run Isolation Forest anomaly detection on rolling 10-minute windows
- FR-03: Alert when any Golden Signal deviates > 2σ from baseline
- FR-04: Deduplicate alerts within a 5-minute window for the same service
- FR-05: Classify alert severity: P1 (auto-remediate), P2 (suggest + wait), P3 (log only)

### 6.2 Diagnosis Layer (Multi-Agent RCA)
- FR-06: Spin up a LangGraph agent graph on every P1/P2 alert
- FR-07: Detective Agent: correlate anomaly with other service metrics in the same time window
- FR-08: Topologist Agent: query Jaeger to map the affected service's dependency graph
- FR-09: Historian Agent: query GitHub API for deployments in the last 60 minutes
- FR-10: Supervisor Agent: synthesize findings from all three agents into a root cause hypothesis
- FR-11: All agent outputs must include a confidence score (0–1) and reasoning chain

### 6.3 Remediation Layer
- FR-12: Map root cause hypotheses to remediation actions via a decision tree
- FR-13: P1 actions execute automatically; P2 actions require human approval via CLI prompt
- FR-14: Supported actions: restart pod, rollback deployment, scale replicas, patch ConfigMap, open GitHub PR
- FR-15: Rollback uses the last known-good deployment image from deployment history
- FR-16: All actions are idempotent and re-entrant safe

### 6.4 Agent Self-Observability
- FR-17: Wrap every LangGraph node execution in an OpenTelemetry span
- FR-18: Each span must include: agent name, input summary, tool call + result, decision taken, token count, latency
- FR-19: Export spans to Jaeger via OTLP
- FR-20: Grafana dashboard must show agent trace and infra trace linked by incident ID
- FR-21: Provide a CLI command to replay any past incident's full agent reasoning trace

### 6.5 Benchmarking
- FR-22: Implement at least 5 LitmusChaos fault scenarios: pod-delete, cpu-hog, memory-hog, network-latency, disk-fill
- FR-23: Track MTTR before (manual) and after (agent) for each scenario
- FR-24: Generate a benchmark report as a markdown file

---

## 7. Non-Functional Requirements

- NFR-01: Detection → first agent action ≤ 3 minutes end-to-end
- NFR-02: Agent reasoning must not cause > 5% additional load on the cluster
- NFR-03: All LLM calls must be retried with exponential backoff on 5xx errors
- NFR-04: The system must be runnable locally on a laptop (Minikube/Kind)
- NFR-05: All credentials must be loaded from environment variables, never hardcoded
- NFR-06: Full test coverage on the anomaly detection model (unit + integration)
- NFR-07: Docker Compose must bring up the full local stack in one command

---

## 8. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     Kubernetes Cluster                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ Service A│  │ Service B│  │ Service C│  │  Chaos   │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  │ Injector │   │
│       └──────────────┴─────────────┘        └──────────┘   │
│                      │ metrics/traces                        │
└──────────────────────┼──────────────────────────────────────┘
                        │
         ┌──────────────▼──────────────┐
         │     Observability Stack      │
         │  Prometheus  │  Jaeger       │
         └──────────────┬──────────────┘
                        │
         ┌──────────────▼──────────────┐
         │     Detection Engine        │
         │  Isolation Forest + LSTM     │
         └──────────────┬──────────────┘
                        │ alert
         ┌──────────────▼──────────────┐
         │   LangGraph Agent Graph     │
         │  Detective │ Topologist │   │
         │  Historian │ Supervisor     │
         └──────────────┬──────────────┘
                        │ action + OTel spans
         ┌──────────────▼──────────────┐
         │   Remediation Engine        │
         │  K8s API │ GitHub API       │
         └──────────────┬──────────────┘
                        │
         ┌──────────────▼──────────────┐
         │  Agent Observability Layer  │
         │  OTel Collector │ Jaeger    │
         │  Grafana Dashboard          │
         └─────────────────────────────┘
```

---

## 9. Tech Stack Summary

See `TECH_STACK.md` for exact versions and install commands.

| Layer | Technology |
|-------|-----------|
| Cluster | Minikube or Kind (local), EKS/GKE (cloud) |
| Metrics | Prometheus + kube-state-metrics |
| Tracing | Jaeger + OpenTelemetry Collector |
| Dashboards | Grafana |
| ML detection | scikit-learn (Isolation Forest), PyTorch (LSTM) |
| Agent framework | LangGraph + LangChain |
| LLM | Claude claude-sonnet-4-6 (primary), GPT-4o (fallback) |
| Agent OTel | opentelemetry-sdk-python |
| Chaos | LitmusChaos |
| API layer | FastAPI |
| Container | Docker + Helm |

---

## 10. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| LLM hallucination triggers wrong remediation | Medium | High | Human-in-the-loop for P2+; confidence threshold gates |
| Isolation Forest too many false positives | Medium | Medium | Tune contamination param on baseline data; add LSTM second pass |
| LangGraph agent gets stuck in reasoning loop | Low | Medium | Max iteration limit + timeout per agent node |
| Cloud costs spike during testing | Low | Low | Use Minikube locally; set AWS billing alerts |
| LLM API rate limits during chaos tests | Medium | Low | Implement retry with backoff; cache repeated prompts |
