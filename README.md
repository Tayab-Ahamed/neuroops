<div align="center">

<img src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=700&size=30&pause=1000&color=00D9FF&center=true&vCenter=true&width=650&lines=NeuroOps+%E2%80%94+Autonomous+AI+SRE;Detect.+Diagnose.+Remediate." alt="NeuroOps" />

<br/>

<p>
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/LangGraph-Multi--Agent-FF6B35?style=for-the-badge&logo=langchain&logoColor=white" />
  <img src="https://img.shields.io/badge/Kubernetes-Native-326CE5?style=for-the-badge&logo=kubernetes&logoColor=white" />
  <img src="https://img.shields.io/badge/OpenTelemetry-Traced-425CC7?style=for-the-badge&logo=opentelemetry&logoColor=white" />
  <img src="https://img.shields.io/badge/DORA-Elite_Performer-00C853?style=for-the-badge" />
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" />
</p>

<p>
  <img src="https://img.shields.io/badge/MTTR-< 4 minutes-success?style=flat-square" />
  <img src="https://img.shields.io/badge/Chaos_Resolved-15/15_(100%25)-brightgreen?style=flat-square" />
  <img src="https://img.shields.io/badge/False_Positives-0%25-brightgreen?style=flat-square" />
  <img src="https://img.shields.io/badge/Claude_Sonnet_4-Powered-7C3AED?style=flat-square&logo=anthropic&logoColor=white" />
</p>

**NeuroOps** is an autonomous AI SRE engine that detects, diagnoses, and remediates Kubernetes incidents end-to-end — with zero human intervention for high-confidence scenarios.

</div>

---

## 📊 Results

| Metric | Result |
|:---|:---|
| 🎯 Chaos Incidents Resolved | **15 / 15 — 100%** |
| ⚡ Average MTTR | **< 4 minutes** |
| 🏆 DORA Tier | **Elite Performer** |
| 🎪 False Positive Rate | **0%** |
| 💰 Cost vs Manual On-Call | **> 1,600× cheaper** |
| 🤖 Autonomous Resolution Rate | **50–100%** (confidence-gated) |

---

## 🧠 How It Works

```mermaid
flowchart TD
    A([🔥 Fault Injected]) --> B

    subgraph DETECT["🔍 DETECT"]
        B[Prometheus Scrapes\nGolden Signals] --> C[Isolation Forest\nAnomaly Scoring]
        C --> D{Anomaly?}
        D -- No --> B
        D -- Yes --> E[Alert Dedup\n+ Severity Triage]
    end

    E --> F

    subgraph DIAGNOSE["🧬 DIAGNOSE — LangGraph Fan-Out"]
        F[Supervisor Init\nIncident ID + OTel Trace] --> G1 & G2 & G3 & G4
        G1[🔎 Detective\nMetric Correlation]
        G2[🗺️ Topologist\nTrace Analysis]
        G3[📜 Historian\nDeploy Timeline]
        G4[📋 Log Analyser\nPod Logs]
        G1 & G2 & G3 & G4 --> H[🧠 Supervisor\nRoot Cause + Confidence]
    end

    H -- "< 0.55" --> I[👤 Escalate\nto Human]
    H -- ">= 0.65" --> J

    subgraph REMEDIATE["🔧 REMEDIATE"]
        J{Action?} -- "restart / scale" --> K[⚡ Auto-Execute]
        J -- "rollback / PR" --> L[🔔 Slack Approval\nThen Execute]
        K & L --> M[✅ Verify Resolution]
    end

    M --> N[📄 Post-Mortem\nStored]

    style DETECT fill:#1a1a2e,stroke:#00D9FF,color:#fff
    style DIAGNOSE fill:#1a1a2e,stroke:#FF6B35,color:#fff
    style REMEDIATE fill:#1a1a2e,stroke:#00C853,color:#fff
```

---

## 🏗️ Architecture

```mermaid
graph TB
    subgraph UI["🌐 Web UI :3000"]
        WEB[Orbital Command Hub\nReal-time Dashboard]
    end

    subgraph CORE["⚙️ Core Services"]
        DET["🔍 Detector :8001"]
        AGT["🧠 Agent :8002"]
        REM["🔧 Remediator :8003"]
    end

    subgraph OBS["📡 Observability"]
        PROM[Prometheus]
        JAEGER[Jaeger]
        GRAFANA[Grafana]
        OTEL[OTel Collector]
    end

    subgraph K8S["☸️ Kubernetes"]
        WORKLOADS[Target Workloads]
        CHAOS[LitmusChaos]
    end

    WEB --> AGT & DET
    DET --> PROM & OTEL
    AGT --> PROM & JAEGER & OTEL
    REM --> WORKLOADS & OTEL
    CHAOS --> WORKLOADS
    WORKLOADS --> PROM
    OTEL --> JAEGER
    PROM & JAEGER --> GRAFANA

    style UI fill:#0d1117,stroke:#00D9FF,color:#00D9FF
    style CORE fill:#0d1117,stroke:#FF6B35,color:#FF6B35
    style OBS fill:#0d1117,stroke:#7C3AED,color:#7C3AED
    style K8S fill:#0d1117,stroke:#326CE5,color:#326CE5
```

---

## 🚀 Quickstart

**Prerequisites:** Python 3.11+, Docker, Kubernetes cluster (Minikube / kind / EKS)

```bash
git clone https://github.com/Tayab-Ahamed/neuroops.git
cd neuroops
cp .env.example .env      # fill in your API keys
```

### Docker Compose — full stack

```bash
docker compose up --build
```

Services: **:8001** Detector · **:8002** Agent · **:8003** Remediator  
Open `web-ui/index.html` for the live dashboard.

### Run services individually

```bash
# Detector
cd detector && pip install -r requirements.txt && uvicorn server:app --port 8001

# Agent
cd agent && pip install -r requirements.txt && uvicorn main:app --port 8002

# Remediator
cd remediator && pip install -r requirements.txt && uvicorn server:app --port 8003
```

---

## 🔑 Environment Variables

```bash
# LLM
ANTHROPIC_API_KEY=sk-ant-...          # Required — RCA agents
OPENAI_API_KEY=sk-...                 # Optional fallback

# Observability
PROMETHEUS_URL=http://localhost:9090
JAEGER_QUERY_URL=http://localhost:16686
OTEL_COLLECTOR_ENDPOINT=http://localhost:4317

# Kubernetes
KUBECONFIG=~/.kube/config
TARGET_NAMESPACE=neuroops-demo

# GitHub
GITHUB_TOKEN=ghp_...                  # Historian agent + PR actions
GITHUB_REPO=your-username/repo

# Tuning
CONFIDENCE_THRESHOLD=0.65             # Below → human escalation
AUTONOMOUS_CONFIDENCE_THRESHOLD=0.65  # Actions above this run autonomously
ANOMALY_CONTAMINATION=0.05

# ChatOps
SLACK_WEBHOOK_URL=https://hooks.slack.com/...   # Optional
```

---

## 📡 API Reference

### Detector — `:8001`
| Method | Endpoint | Description |
|:---:|:---|:---|
| `GET` | `/health` | Health + anomaly model status |
| `GET` | `/alerts` | Active alerts |
| `GET` | `/metrics` | Prometheus scrape endpoint |
| `POST` | `/baseline/train` | Trigger baseline training |

### Agent — `:8002`
| Method | Endpoint | Description |
|:---:|:---|:---|
| `POST` | `/investigate` | Trigger RCA for an alert |
| `GET` | `/incidents` | All persisted incidents |
| `GET` | `/incidents/{id}` | Single incident + full RCA trace |
| `GET` | `/incidents/{id}/similar` | Top-K similar incidents (RAG) |
| `GET` | `/analytics/mttr` | p50/p95/p99 MTTR per service |
| `GET` | `/analytics/sla` | SLA breach + autonomous resolution rate |
| `GET` | `/analytics/cost` | LLM token + USD cost tracking |

### Remediator — `:8003`
| Method | Endpoint | Description |
|:---:|:---|:---|
| `POST` | `/remediate` | Execute remediation action |
| `GET` | `/health` | Health + action count |
| `GET` | `/metrics` | Prometheus scrape endpoint |

---

## 📁 Project Structure

```
neuroops/
├── detector/              # Anomaly detection — Isolation Forest + Ridge Regression
├── agent/                 # LangGraph RCA — Detective, Topologist, Historian, Supervisor
├── remediator/            # Actions — restart, rollback, scale, patch, PR + approval gate
├── observability/         # OTel collector config, Grafana dashboards, CLI replay tool
├── benchmarks/            # Chaos benchmark runner + report generator
├── web-ui/                # Orbital Command Hub (real-time HTML dashboard)
├── cluster/               # Kubernetes manifests + LitmusChaos experiments
├── docker-compose.yml
├── Makefile
└── pyproject.toml
```

---

## 📜 License

MIT — see [LICENSE](LICENSE)

---

<div align="center">
<sub>Built by <a href="https://github.com/Tayab-Ahamed">Tayab Ahamed</a></sub>
</div>
