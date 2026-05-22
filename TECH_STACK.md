# NeuroOps — Tech Stack

Exact package versions and install commands for every component.

---

## Local Prerequisites (install these first)

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.11+ | `pyenv install 3.11.9` |
| Docker Desktop | Latest | https://www.docker.com/products/docker-desktop |
| Minikube | 1.33+ | `brew install minikube` |
| kubectl | 1.30+ | `brew install kubectl` |
| Helm | 3.15+ | `brew install helm` |
| make | Any | Pre-installed on macOS/Linux |

---

## Python Dependencies

### detector/requirements.txt
```
fastapi==0.115.0
uvicorn[standard]==0.30.6
prometheus-api-client==0.5.5
scikit-learn==1.5.2
torch==2.4.1
numpy==2.1.1
pandas==2.2.3
joblib==1.4.2
structlog==24.4.0
pydantic==2.9.2
pydantic-settings==2.5.2
httpx==0.27.2
pytest==8.3.3
pytest-asyncio==0.24.0
pytest-cov==5.0.0
```

### agent/requirements.txt
```
fastapi==0.115.0
uvicorn[standard]==0.30.6
langchain==0.3.7
langchain-anthropic==0.2.4
langchain-core==0.3.15
langgraph==0.2.38
openai==1.52.0
kubernetes==31.0.0
PyGithub==2.5.0
opentelemetry-sdk==1.27.0
opentelemetry-exporter-otlp==1.27.0
opentelemetry-instrumentation-fastapi==0.48b0
tenacity==9.0.0
structlog==24.4.0
pydantic==2.9.2
pydantic-settings==2.5.2
httpx==0.27.2
pytest==8.3.3
pytest-asyncio==0.24.0
pytest-cov==5.0.0
```

### remediator/requirements.txt
```
fastapi==0.115.0
uvicorn[standard]==0.30.6
kubernetes==31.0.0
PyGithub==2.5.0
rich==13.9.2
click==8.1.7
structlog==24.4.0
pydantic==2.9.2
pydantic-settings==2.5.2
httpx==0.27.2
pytest==8.3.3
pytest-asyncio==0.24.0
```

### benchmarks/requirements.txt
```
click==8.1.7
rich==13.9.2
httpx==0.27.2
pydantic==2.9.2
structlog==24.4.0
```

---

## Helm Charts

```bash
# Add repos
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add jaegertracing https://jaegertracing.github.io/helm-charts
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo add litmuschaos https://litmuschaos.github.io/litmus-helm
helm repo update

# Install versions
helm install kube-prometheus prometheus-community/kube-prometheus-stack --version 65.1.1
helm install jaeger jaegertracing/jaeger --version 3.3.1
helm install otel-collector open-telemetry/opentelemetry-collector --version 0.107.0
helm install litmus litmuschaos/litmus --version 3.14.0
```

---

## Environment Variables

Create a `.env` file at the project root (never commit this):

```bash
# LLM
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...           # fallback

# Kubernetes
KUBECONFIG=~/.kube/config
TARGET_NAMESPACE=neuroops-demo

# Prometheus
PROMETHEUS_URL=http://localhost:9090

# Jaeger
JAEGER_QUERY_URL=http://localhost:16686
JAEGER_COLLECTOR_URL=http://localhost:14268

# OpenTelemetry Collector
OTEL_COLLECTOR_ENDPOINT=http://localhost:4317

# GitHub (for historian agent + PR creation)
GITHUB_TOKEN=ghp_...
GITHUB_REPO=your-username/neuroops

# Service URLs (for inter-service comms)
DETECTOR_URL=http://localhost:8001
AGENT_URL=http://localhost:8002
REMEDIATOR_URL=http://localhost:8003

# Feature flags
HUMAN_APPROVAL_REQUIRED=true      # set false to auto-approve all P2 actions
MAX_AGENT_ITERATIONS=10
ANOMALY_CONTAMINATION=0.05
CONFIDENCE_THRESHOLD=0.6
```

---

## Docker Images Used

| Image | Tag | Used by |
|-------|-----|---------|
| prom/prometheus | v2.54.1 | Docker Compose |
| grafana/grafana | 11.2.2 | Docker Compose |
| jaegertracing/all-in-one | 1.61.0 | Docker Compose |
| otel/opentelemetry-collector-contrib | 0.111.0 | Docker Compose |
| python | 3.11-slim | All Python services |

---

## Port Map (local development)

| Service | Port |
|---------|------|
| Prometheus | 9090 |
| Grafana | 3000 |
| Jaeger UI | 16686 |
| Jaeger OTLP gRPC | 14250 |
| OTel Collector gRPC | 4317 |
| OTel Collector HTTP | 4318 |
| Detector API | 8001 |
| Agent API | 8002 |
| Remediator API | 8003 |
| Demo frontend | 8080 |
| Demo backend | 8081 |
| Demo database stub | 8082 |
