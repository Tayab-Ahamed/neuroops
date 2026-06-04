# NeuroOps — Autonomous AI SRE Engine

[![CI](https://github.com/Tayab-Ahamed/neuroops/actions/workflows/ci.yml/badge.svg)](https://github.com/Tayab-Ahamed/neuroops/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11-blue.svg)](https://python.org)
[![DORA](https://img.shields.io/badge/DORA-Elite_Performer-brightgreen.svg)](https://dora.dev)

**NeuroOps** is an autonomous AI SRE engine that detects, diagnoses, and remediates Kubernetes incidents end-to-end — with zero human intervention for high-confidence scenarios.

It combines a **LangGraph multi-agent RCA pipeline**, **dual-layer anomaly detection**, and a full **OpenTelemetry observability stack** to achieve DORA Elite Performer tier in chaos benchmarks.

---

## Results

| Metric | Value |
|---|---|
| Chaos incidents resolved | 15 / 15 (100%) |
| Average MTTR | < 4 minutes |
| DORA tier | Elite Performer |
| False positive rate | 0% |
| Cost vs manual on-call | > 1,600× cheaper |
| Autonomous resolution rate | 50–100% (confidence-gated) |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                     Web UI  (:3000)                 │
│          Orbital Command Hub  ·  Neural Activity    │
└──────────────────────┬──────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    ┌──────────┐ ┌──────────┐ ┌──────────────┐
    │ Detector │ │  Agent   │ │  Remediator  │
    │  :8001   │ │  :8002   │ │    :8003     │
    └──────────┘ └──────────┘ └──────────────┘
          │            │            │
    IsolationForest  LangGraph   kubectl / GH PR
    + Ridge Regr.   Fan-Out RCA  + Slack ChatOps
```

### Services

| Service | Port | Role |
|---|---|---|
| `detector/` | 8001 | Anomaly scoring, alert correlation, Prometheus scraping |
| `agent/` | 8002 | LangGraph multi-agent RCA, incident store, analytics APIs |
| `remediator/` | 8003 | Remediation actions, human-in-the-loop gate, post-mortems |
| `observability/` | — | CLI dashboard, trace replay, Grafana dashboards |
| `web-ui/` | — | Orbital Command Hub — real-time incident dashboard |

---

## How It Works

**1. Detect** — The Detector scrapes Prometheus every 30 seconds across an 8-dimensional feature space (latency p50/p95/p99, error rate, CPU, memory, pod restarts). An IsolationForest scores anomalies; a Ridge Regression forecaster downclasses transient spikes. Correlated alerts are grouped into single RCA requests.

**2. Diagnose** — The Agent runs a LangGraph fan-out graph with 4 parallel diagnostic agents:
- **Detective** — Prometheus metric correlation
- **Topologist** — Jaeger distributed trace analysis
- **Historian** — GitHub deployment timeline inspection
- **Log Analyser** — Pod container log scraping

A **Supervisor** fuses all findings into a `RootCauseHypothesis` with a confidence score.

**3. Remediate** — The Remediator selects the appropriate action: pod restart, deployment rollback, replica scale-out, ConfigMap patch, or GitHub PR. Confidence ≥ 0.75 executes autonomously. Below threshold, a Slack ChatOps approval gate is triggered.

---

## Quickstart

**Prerequisites:** Python 3.11, Docker, a running Kubernetes cluster (or kind/minikube)

```bash
git clone https://github.com/Tayab-Ahamed/neuroops.git
cd neuroops
```

### Run with Docker Compose

```bash
docker compose up --build
```

Services start on ports 8001, 8002, 8003. Open `web-ui/index.html` in your browser.

### Run services individually

```bash
# Terminal 1 — Detector
cd detector && pip install -r requirements.txt
uvicorn server:app --port 8001

# Terminal 2 — Agent
cd agent && pip install -r requirements.txt
uvicorn main:app --port 8002

# Terminal 3 — Remediator
cd remediator && pip install -r requirements.txt
uvicorn server:app --port 8003
```

### Environment variables

```bash
ANTHROPIC_API_KEY=sk-...      # Required for LangGraph RCA
PROMETHEUS_URL=http://...     # Default: http://localhost:9090
JAEGER_URL=http://...         # Default: http://localhost:16686
GITHUB_TOKEN=ghp_...          # Required for PR creation action
SLACK_WEBHOOK_URL=https://... # Optional: ChatOps approval gate
```

---

## APIs

### Detector (`/` port 8001)
| Endpoint | Description |
|---|---|
| `GET /health` | Service health + latest anomaly score |
| `GET /alerts` | Active alerts list |
| `GET /metrics` | Prometheus metrics endpoint |

### Agent (`/` port 8002)
| Endpoint | Description |
|---|---|
| `GET /health` | Service health + incident count |
| `GET /incidents` | All persisted incidents |
| `GET /incidents/{id}` | Single incident + full RCA trace |
| `GET /incidents/{id}/similar` | Top-K similar historical incidents |
| `GET /analytics/mttr` | p50/p95/p99 MTTR per service |
| `GET /analytics/sla` | SLA breach rate + autonomous rate |
| `GET /analytics/cost` | LLM token usage + USD cost |

### Remediator (`/` port 8003)
| Endpoint | Description |
|---|---|
| `GET /health` | Service health + action count |
| `POST /remediate` | Trigger remediation for an incident |
| `GET /metrics` | Prometheus metrics endpoint |

---

## Observability

**CLI Dashboard**
```bash
cd observability && python dashboard.py
```

**Trace Replay**
```bash
python observability/replay.py --list
python observability/replay.py --incident-id INC-001
```

**Grafana** — dashboards pre-provisioned in `observability/grafana/provisioning/`

---

## Chaos Benchmarks

Runs 5 failure scenarios × 3 iterations against a live cluster:

```bash
cd benchmarks && python runner.py --scenarios all
python report.py
```

Scenarios: `pod-delete`, `cpu-hog`, `memory-hog`, `network-latency`, `disk-fill`

---

## Project Structure

```
neuroops/
├── detector/          # Anomaly detection service
├── agent/             # LangGraph RCA + incident store
├── remediator/        # Remediation engine + post-mortems
├── observability/     # CLI tooling + Grafana dashboards
├── benchmarks/        # Chaos engineering benchmark suite
├── web-ui/            # Orbital Command Hub (HTML/CSS/JS)
├── k8s/               # Kubernetes manifests + RBAC
├── docker-compose.yml
└── pyproject.toml     # Unified tool config (black/ruff/pytest/bandit)
```

---

## License

MIT — see [LICENSE](LICENSE)
