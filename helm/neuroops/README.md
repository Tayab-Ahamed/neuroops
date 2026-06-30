# NeuroOps Helm Chart

> Autonomous AI SRE Engine — detect, diagnose, and remediate Kubernetes incidents in under 4 minutes.

## Prerequisites

| Tool | Version |
|---|---|
| Helm | ≥ 3.10 |
| Kubernetes | ≥ 1.25 |

## Installation

```bash
helm install neuroops ./helm/neuroops \
  --set anthropic.apiKey=sk-ant-... \
  --set github.token=ghp_... \
  --set global.apiKey=your-secret-key \
  --set prometheus.url=http://your-prometheus:9090 \
  --set jaeger.queryUrl=http://your-jaeger:16686
```

### Install into a dedicated namespace

```bash
helm install neuroops ./helm/neuroops \
  -n neuroops --create-namespace \
  --set anthropic.apiKey=sk-ant-... \
  --set github.token=ghp_... \
  --set global.apiKey=your-secret-key
```

### Using a values file

```bash
helm install neuroops ./helm/neuroops -f my-values.yaml
```

## Upgrading

```bash
helm upgrade neuroops ./helm/neuroops \
  --set anthropic.apiKey=sk-ant-... \
  --set github.token=ghp_...
```

## Uninstalling

```bash
helm uninstall neuroops
```

## Configuration Reference

| Key | Default | Description |
|---|---|---|
| `global.imageRegistry` | `""` | Optional image registry prefix |
| `global.imagePullPolicy` | `IfNotPresent` | Image pull policy |
| `global.apiKey` | `""` | Enables `X-API-Key` auth on all services |
| `detector.enabled` | `true` | Deploy Detector |
| `detector.replicaCount` | `1` | Detector replicas |
| `detector.service.port` | `8001` | Detector service port |
| `agent.enabled` | `true` | Deploy Agent |
| `agent.replicaCount` | `1` | Agent replicas |
| `agent.service.port` | `8002` | Agent service port |
| `remediator.enabled` | `true` | Deploy Remediator |
| `remediator.replicaCount` | `1` | Remediator replicas |
| `remediator.service.port` | `8003` | Remediator service port |
| `prometheus.url` | `http://prometheus:9090` | Prometheus endpoint |
| `jaeger.queryUrl` | `http://jaeger-query:16686` | Jaeger query endpoint |
| `otel.collectorEndpoint` | `http://otel-collector:4317` | OTel collector gRPC |
| `anthropic.apiKey` | `""` | Anthropic API key (stored in Secret) |
| `github.token` | `""` | GitHub PAT (stored in Secret) |
| `app.targetNamespace` | `default` | Namespace NeuroOps monitors |
| `app.confidenceThreshold` | `0.65` | Min confidence for autonomous action |

## Security Notes

- `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, and `NEUROOPS_API_KEY` are stored in a Kubernetes `Secret` — never in the ConfigMap.
- For production, use [Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets) or [External Secrets Operator](https://external-secrets.io/).
