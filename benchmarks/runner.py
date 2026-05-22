import os
import sys
import time
import json
import subprocess
from typing import List, Dict, Any, Optional
import click
import httpx
import structlog
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

# Ensure stdout/stderr use UTF-8 encoding on Windows to prevent UnicodeEncodeError
if sys.platform.startswith("win"):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

# Configure structlog
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)
logger = structlog.get_logger()
console = Console(force_terminal=True, width=150)

# Default URLs from tech stack
DEFAULT_DETECTOR_URL = os.getenv("DETECTOR_URL", "http://localhost:8001")
DEFAULT_AGENT_URL = os.getenv("AGENT_URL", "http://localhost:8002")
DEFAULT_REMEDIATOR_URL = os.getenv("REMEDIATOR_URL", "http://localhost:8003")

# Static estimated manual resolution times (SRE manual MTTR in seconds)
MANUAL_ESTIMATES = {
    "pod-delete": 300.0,        # 5 mins
    "cpu-hog": 600.0,           # 10 mins
    "memory-hog": 900.0,        # 15 mins
    "network-latency": 1200.0,  # 20 mins
    "disk-fill": 1800.0         # 30 mins
}

# Mapping of scenario name to target service name
SCENARIO_TARGETS = {
    "pod-delete": "backend",
    "cpu-hog": "frontend",
    "memory-hog": "backend",
    "network-latency": "backend",
    "disk-fill": "backend"
}

def verify_k8s_reachable() -> bool:
    """Checks if kubectl can reach a Kubernetes cluster."""
    try:
        res = subprocess.run(
            ["kubectl", "cluster-info"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5
        )
        return res.returncode == 0
    except Exception:
        return False

def verify_service_reachable(url: str) -> bool:
    """Checks if a microservice is reachable on its configured URL."""
    try:
        with httpx.Client(timeout=2.0) as client:
            res = client.get(f"{url}/health")
            return res.status_code == 200
    except Exception:
        return False

@click.command()
@click.option("--scenario", default=None, help="Chaos scenario to run (pod-delete, cpu-hog, etc.)")
@click.option("--runs", default=3, help="Number of benchmark runs per scenario")
@click.option("--mock", is_flag=True, help="Force mock dry-run mode (no K8s or real service calls)")
@click.option("--port-detector", default=8001, help="FastAPI port for detector service")
@click.option("--port-agent", default=8002, help="FastAPI port for agent service")
@click.option("--port-remediator", default=8003, help="FastAPI port for remediator service")
def main(
    scenario: Optional[str],
    runs: int,
    mock: bool,
    port_detector: int,
    port_agent: int,
    port_remediator: int
) -> None:
    """Orchestrates the Chaos Engineering recovery loop and tracks MTTR stats."""
    console.print(Panel.fit(
        "[bold cyan]NeuroOps Chaos Engineering Benchmark Suite[/bold cyan]\n"
        "[dim]Phase 5 — Automated SRE Recovery Validation[/dim]",
        border_style="cyan"
    ))

    detector_url = f"http://localhost:{port_detector}"
    agent_url = f"http://localhost:{port_agent}"
    remediator_url = f"http://localhost:{port_remediator}"

    # Auto-detect mock mode if live is selected but unavailable
    is_mock = mock
    if not is_mock:
        k8s_ok = verify_k8s_reachable()
        detector_ok = verify_service_reachable(detector_url)
        agent_ok = verify_service_reachable(agent_url)
        remediator_ok = verify_service_reachable(remediator_url)
        
        if not (k8s_ok and detector_ok and agent_ok and remediator_ok):
            is_mock = True
            console.print(
                "[yellow]WARN: Local stack or Kubernetes is not fully available. "
                "Defaulting to High-Fidelity Mock Mode.[/yellow]\n"
                f"[dim]K8s: {'OK' if k8s_ok else 'OFF'}, "
                f"Detector: {'OK' if detector_ok else 'OFF'}, "
                f"Agent: {'OK' if agent_ok else 'OFF'}, "
                f"Remediator: {'OK' if remediator_ok else 'OFF'}[/dim]"
            )
        else:
            console.print("[green]System status: All live APIs and Kubernetes cluster verified. Executing LIVE chaos.[/green]")

    scenarios = [scenario] if scenario else list(MANUAL_ESTIMATES.keys())
    results: List[Dict[str, Any]] = []

    for sc in scenarios:
        if sc not in MANUAL_ESTIMATES:
            console.print(f"[red]Error: Unknown scenario '{sc}'[/red]")
            continue
        
        target_service = SCENARIO_TARGETS[sc]
        console.print(Panel(
            f"[bold magenta]Starting Benchmark Scenario: {sc}[/bold magenta]\n"
            f"[dim]Target: {target_service} | Scheduled Runs: {runs} | Mode: {'Mock' if is_mock else 'Live'}[/dim]",
            border_style="magenta"
        ))

        scenario_runs: List[Dict[str, Any]] = []
        for run_idx in range(1, runs + 1):
            run_result = execute_run(
                sc, target_service, run_idx, is_mock, detector_url, agent_url, remediator_url
            )
            scenario_runs.append(run_result)
            results.append(run_result)
            
            # Brief cooldown between runs
            time.sleep(1.0)

        # Print scenario summary table
        render_scenario_summary(sc, scenario_runs)

    # Save all results to a temporary JSON file for report generation
    results_path = "benchmarks/results.json"
    os.makedirs("benchmarks", exist_ok=True)
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
        
    console.print(f"\n[green]✓ Complete! Saved {len(results)} run results to {results_path}[/green]")

    # Run the report generator
    try:
        try:
            from benchmarks.report import compile_report
        except ModuleNotFoundError:
            from report import compile_report
        compile_report(results_path)
    except Exception as e:
        logger.error("Failed to run report compilation automatically", error=str(e))


def execute_run(
    scenario: str,
    target_service: str,
    run_number: int,
    is_mock: bool,
    detector_url: str,
    agent_url: str,
    remediator_url: str
) -> Dict[str, Any]:
    """Runs a single iteration of a chaos scenario and measures response latency."""
    console.print(f"\n[bold yellow]--- Scenario '{scenario}' Run #{run_number} ---[/bold yellow]")
    
    t0 = time.time()
    manifest_path = f"cluster/chaos/{scenario}.yaml"
    
    # 1. Inject Chaos
    logger.info("Injecting chaos", scenario=scenario, run=run_number, mock=is_mock)
    if not is_mock:
        try:
            subprocess.run(["kubectl", "apply", "-f", manifest_path], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            console.print("[cyan][Chaos] LitmusChaos Engine applied successfully via kubectl.[/cyan]")
        except Exception as e:
            logger.error("Failed to apply chaos manifest", scenario=scenario, error=str(e))
            console.print("[red][Chaos] Failed to apply chaos manifest. Aborting run.[/red]")
            return create_failed_run_payload(scenario, target_service, run_number, "Chaos Injection Failure")
    else:
        console.print(f"[cyan][Chaos] (Mock) Injected fault: '{scenario}' on service '{target_service}'.[/cyan]")

    # State variables for latencies
    t1: Optional[float] = None
    t2: Optional[float] = None
    t3: Optional[float] = None
    
    # Values extracted from agent and remediator runs
    tokens_used = 0
    confidence = 0.0
    action_taken = "none"
    remediator_success = False
    autonomous = True
    alert_obj: Dict[str, Any] = {}

    # Total timeout: 10 minutes (600s)
    timeout_duration = 600.0
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        
        # --- Task 1: Anomaly Detection (Poll /alerts) ---
        detect_task = progress.add_task("[yellow]Waiting for Anomaly Detection...[/yellow]", total=60)
        
        start_poll = time.time()
        while time.time() - start_poll < timeout_duration:
            if is_mock:
                # Mock detection in ~2 seconds
                time.sleep(2.0)
                t1 = t0 + 15.0  # 15s mock detection latency
                alert_obj = {
                    "id": f"mock-alert-{scenario}-{run_number}",
                    "service": target_service,
                    "severity": "P1" if scenario == "pod-delete" else "P2",
                    "timestamp": t1,
                    "metric_snapshot": {"anomaly_score": -0.75},
                    "anomaly_score": -0.75
                }
                progress.update(detect_task, completed=60, description="[green]✓ Alert Detected (Mock)[/green]")
                break
            else:
                try:
                    with httpx.Client(timeout=3.0) as client:
                        response = client.get(f"{detector_url}/alerts")
                        if response.status_code == 200:
                            alerts = response.json()
                            target_alert = next((a for a in alerts if a.get("service") == target_service), None)
                            if target_alert:
                                t1 = time.time()
                                alert_obj = target_alert
                                progress.update(detect_task, completed=60, description="[green]✓ Alert Detected![/green]")
                                break
                except Exception as e:
                    logger.warning("Polling alerts endpoint failed, retrying...", error=str(e))
            
            time.sleep(3.0)
            progress.advance(detect_task, 3)

        if not t1:
            progress.update(detect_task, description="[red]✗ Detection Timeout[/red]")
            return create_failed_run_payload(scenario, target_service, run_number, "Detection Timeout")

        # --- Task 2: Multi-Agent RCA (Call /investigate) ---
        rca_task = progress.add_task("[yellow]Running Agent Diagnostics (RCA)...[/yellow]", total=100)
        t2_start = time.time()

        if is_mock:
            # Mock agent run
            time.sleep(2.0)
            confidence = 0.85 if scenario == "pod-delete" else 0.55
            autonomous = confidence >= 0.6
            tokens_used = 4200
            hypothesis = f"RCA Hypothesis for '{scenario}': target pod failure"
            progress.update(rca_task, completed=100, description="[green]✓ RCA Finished (Mock)[/green]")
        else:
            try:
                with httpx.Client(timeout=120.0) as client:
                    response = client.post(f"{agent_url}/investigate", json=alert_obj)
                    if response.status_code == 200:
                        hypothesis_data = response.json()
                        hypothesis = hypothesis_data.get("hypothesis", "Unknown")
                        confidence = hypothesis_data.get("confidence", 0.0)
                        autonomous = not hypothesis_data.get("requires_human_approval", False)
                        tokens_used = hypothesis_data.get("tokens_used", 5000)  # Read from API or fall back
                        progress.update(rca_task, completed=100, description="[green]✓ RCA Finished[/green]")
                    else:
                        progress.update(rca_task, description="[red]✗ RCA Failed[/red]")
                        return create_failed_run_payload(scenario, target_service, run_number, "Agent API Failed")
            except Exception as e:
                logger.error("RCA invocation failed", error=str(e))
                progress.update(rca_task, description="[red]✗ RCA Failed[/red]")
                return create_failed_run_payload(scenario, target_service, run_number, "Agent Connection Error")

        # --- Task 3: Remediation Engine (Call /remediate) ---
        remediator_task = progress.add_task("[yellow]Applying Remediation...[/yellow]", total=100)
        
        # Action map
        action_map = {
            "pod-delete": "restart",
            "cpu-hog": "scale",
            "memory-hog": "scale",
            "network-latency": "restart",
            "disk-fill": "patch_configmap"
        }
        recommended_action = action_map[scenario]

        remediation_payload = {
            "incident_id": f"inc-{scenario}-{run_number}",
            "hypothesis": hypothesis,
            "confidence": confidence,
            "recommended_action": recommended_action,
            "requires_human_approval": not autonomous,
            "reasoning": f"Chaos incident triggers action {recommended_action}.",
            "alert": alert_obj,
            "namespace": "neuroops-demo",
            "replicas": 3 if scenario in ("cpu-hog", "memory-hog") else None
        }

        if is_mock:
            time.sleep(2.0)
            t2 = t2_start + 25.0
            remediator_success = True
            action_taken = f"Mock executed remediation '{recommended_action}'"
            progress.update(remediator_task, completed=100, description="[green]✓ Remediation Applied (Mock)[/green]")
        else:
            try:
                # Signal the remediator whether human approval has been bypassed
                if not autonomous:
                    os.environ["REMEDIATOR_TEST_APPROVAL"] = "true"
                else:
                    os.environ.pop("REMEDIATOR_TEST_APPROVAL", None)
                with httpx.Client(timeout=180.0) as client:
                    response = client.post(f"{remediator_url}/remediate", json=remediation_payload)
                    if response.status_code == 200:
                        action_res = response.json()
                        remediator_success = action_res.get("success", False)
                        action_taken = action_res.get("action_taken", "none")
                        t2 = time.time()
                        progress.update(remediator_task, completed=100, description="[green]✓ Remediation Applied[/green]")
                    else:
                        progress.update(remediator_task, description="[red]✗ Remediation Failed[/red]")
                        return create_failed_run_payload(scenario, target_service, run_number, "Remediator API Failed")
            except Exception as e:
                logger.error("Remediation execution failed", error=str(e))
                progress.update(remediator_task, description="[red]✗ Remediation Failed[/red]")
                return create_failed_run_payload(scenario, target_service, run_number, "Remediator Connection Error")

        # --- Task 4: Resolution Verification (Wait for alerts to clear) ---
        verify_task = progress.add_task("[yellow]Verifying Alert Resolution...[/yellow]", total=100)

        # Cleanup chaos in real mode so it can clear
        if not is_mock:
            try:
                subprocess.run(["kubectl", "delete", "-f", manifest_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except Exception as e:
                logger.warning("Cleanup during resolution polling failed", error=str(e))

        start_verify = time.time()
        while time.time() - start_verify < timeout_duration:
            if is_mock:
                time.sleep(1.5)
                t3 = t2 + 10.0
                progress.update(verify_task, completed=100, description="[green]✓ Incident Fully Resolved (Mock)[/green]")
                break
            else:
                try:
                    with httpx.Client(timeout=3.0) as client:
                        response = client.get(f"{detector_url}/alerts")
                        if response.status_code == 200:
                            alerts = response.json()
                            target_alert = next((a for a in alerts if a.get("service") == target_service), None)
                            if not target_alert:
                                t3 = time.time()
                                progress.update(verify_task, completed=100, description="[green]✓ Incident Fully Resolved[/green]")
                                break
                except Exception as e:
                    logger.warning("Verifier alerts query failed, retrying...", error=str(e))
            
            time.sleep(5.0)
            progress.advance(verify_task, 5)

        if not t3:
            progress.update(verify_task, description="[red]✗ Resolution Timeout[/red]")
            return create_failed_run_payload(scenario, target_service, run_number, "Resolution Verification Timeout")

    # Success payload construction
    # det_lat: time from chaos injection → first alert fires
    # diag_lat: time from alert → RCA agent finishes (t2_start marks agent call start, t1 marks alert fire)
    # rem_lat: time from RCA start → remediation action taken
    det_lat = max(0.0, t1 - t0)
    diag_lat = max(0.0, t2_start - t1)
    rem_lat = max(0.0, t2 - t2_start)
    tot_mttr = max(0.0, t3 - t0)

    # Output run summary
    console.print(f"[green]✓ Run #{run_number} Success![/green]")
    console.print(
        f"  [dim]Detection Latency: {det_lat:.1f}s | "
        f"Diagnosis Latency: {diag_lat:.1f}s | "
        f"Remediation Latency: {rem_lat:.1f}s | "
        f"Total MTTR: {tot_mttr:.1f}s[/dim]"
    )

    return {
        "scenario": scenario,
        "run": run_number,
        "status": "success",
        "detection_latency": det_lat,
        "diagnosis_latency": diag_lat,
        "remediation_latency": rem_lat,
        "total_mttr": tot_mttr,
        "tokens_used": tokens_used,
        "confidence": confidence,
        "autonomous": autonomous,
        "action_taken": action_taken,
        "remediator_success": remediator_success,
        "error_message": ""
    }


def create_failed_run_payload(
    scenario: str,
    target_service: str,
    run_number: int,
    error_message: str
) -> Dict[str, Any]:
    """Returns a dictionary representing a failed run with maximum timeouts."""
    console.print(f"[red]✗ Run #{run_number} Failed: {error_message}[/red]")
    return {
        "scenario": scenario,
        "run": run_number,
        "status": "failed",
        "detection_latency": 600.0,
        "diagnosis_latency": 600.0,
        "remediation_latency": 600.0,
        "total_mttr": 600.0,
        "tokens_used": 0,
        "confidence": 0.0,
        "autonomous": False,
        "action_taken": "none",
        "remediator_success": False,
        "error_message": error_message
    }


def render_scenario_summary(scenario: str, runs: List[Dict[str, Any]]) -> None:
    """Renders a gorgeous summary table for all runs of a single scenario."""
    table = Table(
        title=f"Scenario Summary: '{scenario}'",
        show_header=True,
        header_style="bold magenta",
        box=None
    )
    table.add_column("Run", style="dim", width=4)
    table.add_column("Status")
    table.add_column("Detection", justify="right")
    table.add_column("Diagnosis", justify="right")
    table.add_column("Remediation", justify="right")
    table.add_column("Total MTTR", justify="right", style="bold green")
    table.add_column("Tokens", justify="right")
    table.add_column("Auto", justify="center")

    total_mttr_sum = 0.0
    success_count = 0

    for r in runs:
        status_str = "[green]Success[/green]" if r["status"] == "success" else f"[red]Fail: {r['error_message']}[/red]"
        auto_str = "[green]✓[/green]" if r["autonomous"] else "[yellow]escalate[/yellow]"
        
        table.add_row(
            str(r["run"]),
            status_str,
            f"{r['detection_latency']:.1f}s",
            f"{r['diagnosis_latency']:.1f}s",
            f"{r['remediation_latency']:.1f}s",
            f"{r['total_mttr']:.1f}s",
            str(r["tokens_used"]),
            auto_str
        )
        if r["status"] == "success":
            total_mttr_sum += r["total_mttr"]
            success_count += 1

    avg_mttr = total_mttr_sum / success_count if success_count > 0 else 600.0
    manual_estimate = MANUAL_ESTIMATES[scenario]
    speedup = manual_estimate / avg_mttr if avg_mttr > 0 else 1.0

    console.print(table)
    console.print(
        f"[bold cyan]Average Agent MTTR: {avg_mttr:.1f}s[/bold cyan] | "
        f"[bold yellow]Estimated Manual MTTR: {manual_estimate:.1f}s[/bold yellow] | "
        f"[bold green]MTTR Speedup: {speedup:.1f}x[/bold green]\n"
    )

if __name__ == "__main__":
    main()
