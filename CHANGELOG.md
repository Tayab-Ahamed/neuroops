# Changelog

All notable changes to NeuroOps are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html)

---

## [Unreleased]

### Added
- Helm chart for production Kubernetes deployment (`helm/neuroops/`)
- API key authentication + rate limiting on all 3 FastAPI services
- Two-way Slack app: button clicks now trigger actual remediation execution
- Predictive alerting panel in Web UI (pre-breach warnings from `/alerts/predictive`)
- Multi-cluster remediation support via `KUBECONFIG_CONTEXT` env var
- `CHANGELOG.md`, GitHub issue templates, PR template

### Fixed
- 20 broken tests in `remediator/tests/` (timeout message mismatch, bare Exception not caught, isatty guard)

---

## [1.0.0] — 2026-05-28

### Added
- LangGraph multi-agent RCA pipeline: Detective, Topologist, Historian, Log Analyser, Supervisor
- Dual-layer anomaly detection: Isolation Forest + Ridge Regression forecaster
- Alert deduplication and multi-alert correlator for cascading failure grouping
- 5 Kubernetes remediation actions: `restart_pod`, `rollback_deploy`, `scale_replicas`, `patch_configmap`, `open_github_pr`
- Confidence-gated autonomous execution (≥ 0.65 runs autonomously, < 0.55 escalates)
- Slack ChatOps approval gate with configurable timeout
- ChromaDB RAG incident memory with cosine similarity search (threshold 0.75)
- OpenTelemetry tracing on every agent node — confidence, latency, tokens captured per span
- SQLite incident store with MTTR analytics, SLA tracking, cost accounting
- Auto post-mortem generator with DORA tier classification
- Alert correlator for cascading failure detection and deduplication
- Prometheus metric scraper with 8-dimensional Golden Signal feature vector
- LitmusChaos benchmark suite: 5 chaos scenarios × 3 runs each
- Web UI — Orbital Command Hub with animated orb, glass panels, SSE live push
- CLI observability dashboard and trace replay tool
- Grafana dashboards pre-provisioned with OTel Collector config
- Docker Compose full local stack (detector + agent + remediator + Prometheus + Jaeger + Grafana)
- Anti-flapping lockout (max 2 actions per service per 10-minute window)
- Resolution verifier — polls detector `/alerts` after remediation to confirm fix worked
- PagerDuty integration in remediator chatops

### Benchmark Results (v1.0.0)
| Metric | Result |
|---|---|
| Incidents resolved | 15 / 15 (100%) |
| Average MTTR | < 4 minutes |
| MTTR speedup vs manual | **8.1×** |
| False positive rate | **0%** |
| Total AI cost (15 incidents) | **$1.39** |
| Manual SRE equivalent cost | ~$2,250 |
| Cost savings ratio | **> 1,600×** |
| DORA performance tier | **Elite Performer** |
