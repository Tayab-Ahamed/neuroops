.PHONY: cluster-up up down status clean chaos bench baseline

# Start Minikube, build & load demo images, deploy Helm charts and demo apps
cluster-up:
	@echo "=== Starting Minikube ==="
	minikube status >/dev/null 2>&1 || minikube start --memory=4096 --cpus=3 --driver=docker

	@echo "=== Building and Loading Demo Microservices Images ==="
	@echo "Building database-stub..."
	docker build -t neuroops-database-stub:latest ./cluster/apps/database-stub || minikube image build -t neuroops-database-stub:latest ./cluster/apps/database-stub
	minikube image load neuroops-database-stub:latest || true

	@echo "Building backend..."
	docker build -t neuroops-backend:latest ./cluster/apps/backend || minikube image build -t neuroops-backend:latest ./cluster/apps/backend
	minikube image load neuroops-backend:latest || true

	@echo "Building frontend..."
	docker build -t neuroops-frontend:latest ./cluster/apps/frontend || minikube image build -t neuroops-frontend:latest ./cluster/apps/frontend
	minikube image load neuroops-frontend:latest || true

	@echo "=== Adding Helm Repositories ==="
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
	helm repo add jaegertracing https://jaegertracing.github.io/helm-charts
	helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
	helm repo update

	@echo "=== Creating Namespace monitoring ==="
	kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -

	@echo "=== Deploying kube-prometheus-stack Helm Chart ==="
	helm upgrade --install kube-prometheus prometheus-community/kube-prometheus-stack \
		--version 65.1.1 \
		-f cluster/monitoring/prometheus-values.yaml \
		--namespace monitoring

	@echo "=== Deploying Jaeger Helm Chart ==="
	helm upgrade --install jaeger jaegertracing/jaeger \
		--version 3.3.1 \
		-f cluster/monitoring/jaeger-values.yaml \
		--namespace monitoring

	@echo "=== Deploying OpenTelemetry Collector Helm Chart ==="
	helm upgrade --install otel-collector open-telemetry/opentelemetry-collector \
		--version 0.107.0 \
		-f cluster/monitoring/otel-collector-values.yaml \
		--namespace monitoring

	@echo "=== Deploying Demo Microservices Applications ==="
	kubectl apply -f cluster/apps/manifests.yaml

	@echo "=== Bootstrap Complete! ==="
	@echo "To access the frontend service, run: minikube service frontend-service -n neuroops-demo"

# Start the local Docker Compose observability stack
up:
	@echo "=== Launching Local Observability Stack via Docker Compose ==="
	docker compose up -d
	@echo "Grafana: http://localhost:3000 (admin / admin)"
	@echo "Jaeger UI: http://localhost:16686"
	@echo "Prometheus: http://localhost:9090"

# Stop local Docker Compose stack and Minikube
down:
	@echo "=== Tearing Down Docker Compose Stack ==="
	docker compose down
	@echo "=== Stopping Minikube ==="
	minikube stop || true

# View the status of the local environments (Kubernetes + Docker Compose)
status:
	@echo "=== Docker Compose Container Status ==="
	docker compose ps
	@echo ""
	@echo "=== Kubernetes Pods (monitoring) ==="
	kubectl get pods -n monitoring
	@echo ""
	@echo "=== Kubernetes Pods (neuroops-demo) ==="
	kubectl get pods -n neuroops-demo
	@echo ""
	@echo "=== Kubernetes Services (monitoring) ==="
	kubectl get svc -n monitoring
	@echo ""
	@echo "=== Kubernetes Services (neuroops-demo) ==="
	kubectl get svc -n neuroops-demo

# Run a single chaos scenario (e.g. make chaos scenario=pod-delete)
scenario ?= pod-delete
chaos:
	@echo "=== Running Chaos Scenario: $(scenario) ==="
	python benchmarks/runner.py --scenario $(scenario)

# Run the complete chaos benchmark suite and generate SRE report
bench:
	@echo "=== Running Complete Chaos Benchmark Suite ==="
	python benchmarks/runner.py

# Collect baseline metrics and train anomaly detection models
baseline:
	@echo "=== Collecting 30 Minutes of Baseline Metrics and Training Model ==="
	python detector/baseline_collector.py --minutes 30
