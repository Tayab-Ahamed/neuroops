"""
observability/dashboard.py — Real-Time Live CLI Dashboard for NeuroOps

A rich-powered terminal dashboard that auto-refreshes every 5 seconds, showing:
- Service health grid (all 3 demo services)
- Active alerts feed
- Recent incident MTTR tracker
- Token cost analytics
- System-wide SLA status

Usage:
    python observability/dashboard.py
    python observability/dashboard.py --detector-url http://localhost:8001 \
        --agent-url http://localhost:8002 --remediator-url http://localhost:8003
"""
import time
import os
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import click
import httpx
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.align import Align
from rich.rule import Rule
from rich.spinner import Spinner
from rich.style import Style
from rich import box

console = Console()

# ── Constants ─────────────────────────────────────────────────────────────────
REFRESH_INTERVAL = 5  # seconds

SEVERITY_COLORS = {"P1": "bold red", "P2": "bold yellow", "P3": "bold cyan"}
SERVICE_ICONS = {
    "frontend": "🌐",
    "backend": "⚙️ ",
    "database-stub": "🗄️ ",
}
HEADER_ART = """\
 ███╗   ██╗███████╗██╗   ██╗██████╗  ██████╗  ██████╗ ██████╗ ███████╗
 ████╗  ██║██╔════╝██║   ██║██╔══██╗██╔═══██╗██╔═══██╗██╔══██╗██╔════╝
 ██╔██╗ ██║█████╗  ██║   ██║██████╔╝██║   ██║██║   ██║██████╔╝███████╗
 ██║╚██╗██║██╔══╝  ██║   ██║██╔══██╗██║   ██║██║   ██║██╔═══╝ ╚════██║
 ██║ ╚████║███████╗╚██████╔╝██║  ██║╚██████╔╝╚██████╔╝██║     ███████║
 ╚═╝  ╚═══╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ╚═╝     ╚══════╝"""


# ── Data Fetchers ──────────────────────────────────────────────────────────────

def safe_get(url: str, timeout: float = 3.0) -> Optional[Any]:
    """HTTP GET with timeout, returns None on any error."""
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(url)
            r.raise_for_status()
            return r.json()
    except Exception:
        return None


def fetch_health(base_url: str) -> Dict[str, Any]:
    result = safe_get(f"{base_url}/health")
    return result or {"status": "unreachable"}


def fetch_alerts(detector_url: str) -> List[Dict[str, Any]]:
    result = safe_get(f"{detector_url}/alerts")
    return result if isinstance(result, list) else []


def fetch_correlated_alerts(detector_url: str) -> List[Dict[str, Any]]:
    result = safe_get(f"{detector_url}/alerts/correlated")
    return result if isinstance(result, list) else []


def fetch_incidents(agent_url: str, limit: int = 8) -> List[Dict[str, Any]]:
    result = safe_get(f"{agent_url}/incidents?limit={limit}")
    return result if isinstance(result, list) else []


def fetch_mttr_stats(agent_url: str) -> Dict[str, Any]:
    result = safe_get(f"{agent_url}/analytics/mttr")
    return result or {}


def fetch_cost_stats(agent_url: str) -> Dict[str, Any]:
    result = safe_get(f"{agent_url}/analytics/cost")
    return result or {}


def fetch_sla_status(agent_url: str) -> Dict[str, Any]:
    result = safe_get(f"{agent_url}/analytics/sla")
    return result or {}


def fetch_actions(remediator_url: str) -> List[Dict[str, Any]]:
    result = safe_get(f"{remediator_url}/actions")
    return result if isinstance(result, list) else []


# ── Panel Builders ─────────────────────────────────────────────────────────────

def build_header() -> Panel:
    """Builds the top header banner panel."""
    now_str = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    header_text = Text(HEADER_ART, style="bold cyan")
    subtitle = Text(
        f"\n  Autonomous AI SRE Engine  ·  Live Operations Dashboard  ·  {now_str}",
        style="dim white",
        justify="center",
    )
    content = Align.center(header_text + subtitle)
    return Panel(content, border_style="cyan", padding=(0, 1))


def build_service_health_panel(
    detector_health: Dict,
    agent_health: Dict,
    remediator_health: Dict,
    alerts: List[Dict],
) -> Panel:
    """Builds the 3-service health grid."""
    alert_services = {a.get("service", "") for a in alerts}

    def service_status(health: Dict, name: str, port: int) -> Table:
        t = Table.grid(padding=(0, 1))
        t.add_column(width=3)
        t.add_column()

        status = health.get("status", "unreachable")
        if status == "unreachable":
            icon, color = "🔴", "red"
            status_label = "[bold red]OFFLINE[/bold red]"
        elif name in alert_services:
            icon, color = "🟡", "yellow"
            status_label = "[bold yellow]DEGRADED[/bold yellow]"
        else:
            icon, color = "🟢", "green"
            status_label = "[bold green]HEALTHY[/bold green]"

        t.add_row(icon, f"[bold {color}]{name.upper()}[/bold {color}]  :{port}")
        t.add_row("", f"Status: {status_label}")

        if name == "Detector":
            model_ok = health.get("model_loaded", False)
            alerts_count = health.get("active_alerts_count", 0)
            t.add_row("", f"Model: {'[green]Loaded[/green]' if model_ok else '[red]Not Loaded[/red]'}")
            t.add_row("", f"Active Alerts: [bold]{alerts_count}[/bold]")
        elif name == "Agent":
            incidents = health.get("persisted_incidents", 0)
            t.add_row("", f"Stored Incidents: [bold]{incidents}[/bold]")
        elif name == "Remediator":
            actions = health.get("actions_count", 0)
            k8s = health.get("k8s_configured", False)
            t.add_row("", f"Actions Taken: [bold]{actions}[/bold]")
            t.add_row("", f"K8s: {'[green]Connected[/green]' if k8s else '[yellow]Mocked[/yellow]'}")
        return t

    cols = Columns(
        [
            Panel(service_status(detector_health, "Detector", 8001), border_style="dim", padding=(0, 1)),
            Panel(service_status(agent_health, "Agent", 8002), border_style="dim", padding=(0, 1)),
            Panel(service_status(remediator_health, "Remediator", 8003), border_style="dim", padding=(0, 1)),
        ],
        equal=True,
    )
    return Panel(cols, title="[bold white]⚡ Service Health Grid[/bold white]", border_style="blue")


def build_alerts_panel(alerts: List[Dict], correlated: List[Dict]) -> Panel:
    """Builds the active alerts panel."""
    if not alerts:
        content = Align.center(
            Text("\n  ✅  No active alerts — all systems nominal\n", style="bold green"),
            vertical="middle",
        )
        return Panel(content, title="[bold white]🚨 Active Alerts[/bold white]", border_style="green", height=10)

    t = Table(
        show_header=True,
        header_style="bold magenta",
        border_style="dim",
        box=box.SIMPLE,
        expand=True,
    )
    t.add_column("ID", style="dim", width=14)
    t.add_column("Service", style="bold")
    t.add_column("Sev", width=4)
    t.add_column("Score", justify="right", width=8)
    t.add_column("Time", width=9)

    for a in alerts[:8]:
        sev = a.get("severity", "P3")
        color = SEVERITY_COLORS.get(sev, "white")
        score = a.get("anomaly_score", 0.0)
        ts = a.get("timestamp", 0.0)
        ts_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "?"
        icon = SERVICE_ICONS.get(a.get("service", ""), "  ")
        t.add_row(
            a.get("id", "?")[:13],
            f"{icon} {a.get('service', '?')}",
            f"[{color}]{sev}[/{color}]",
            f"[yellow]{score:.3f}[/yellow]",
            ts_str,
        )

    # Cascading failure note
    cascading = [c for c in correlated if c.get("is_cascading_failure")]
    suffix = Text("")
    if cascading:
        suffix = Text(
            f"\n  ⚠️  {len(cascading)} cascading failure group(s) detected across services!",
            style="bold yellow",
        )

    return Panel(
        Text.assemble(t.__rich_console__(console, console.options).__next__() if False else "") or t,
        title=f"[bold white]🚨 Active Alerts ({len(alerts)})[/bold white]",
        border_style="red" if any(a.get("severity") == "P1" for a in alerts) else "yellow",
    )


def build_incidents_panel(incidents: List[Dict]) -> Panel:
    """Builds the recent incidents table panel."""
    t = Table(
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        box=box.SIMPLE,
        expand=True,
    )
    t.add_column("Incident ID", style="dim", width=14)
    t.add_column("Service")
    t.add_column("Confidence", justify="right", width=10)
    t.add_column("Action")
    t.add_column("Human?", justify="center", width=7)
    t.add_column("Time", width=9)

    if not incidents:
        t.add_row("[dim]No incidents recorded yet[/dim]", "", "", "", "", "")
    else:
        for inc in incidents[:7]:
            conf = inc.get("confidence", 0.0)
            if conf >= 0.8:
                conf_str = f"[bold green]{conf:.0%}[/bold green]"
            elif conf >= 0.6:
                conf_str = f"[bold yellow]{conf:.0%}[/bold yellow]"
            else:
                conf_str = f"[bold red]{conf:.0%}[/bold red]"

            action = inc.get("recommended_action", "none")
            human = inc.get("requires_human_approval", False)
            human_str = "[red]YES[/red]" if human else "[green]NO[/green]"
            ts = inc.get("created_at", 0.0)
            ts_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "?"
            icon = SERVICE_ICONS.get(inc.get("service", ""), "  ")

            t.add_row(
                inc.get("incident_id", "?")[:13],
                f"{icon} {inc.get('service', '?')}",
                conf_str,
                f"[cyan]{action}[/cyan]",
                human_str,
                ts_str,
            )

    return Panel(t, title="[bold white]📋 Recent Incidents[/bold white]", border_style="blue")


def build_analytics_panel(mttr_stats: Dict, cost_stats: Dict, sla_status: Dict) -> Panel:
    """Builds the MTTR + cost analytics panel."""
    t = Table.grid(padding=(0, 2))
    t.add_column(width=28)
    t.add_column(width=28)
    t.add_column(width=28)

    # MTTR stats
    mttr_text = Text()
    mttr_text.append("⏱  MTTR Analytics\n", style="bold cyan")
    p50 = mttr_stats.get("p50_mttr_seconds", 0.0)
    p95 = mttr_stats.get("p95_mttr_seconds", 0.0)
    total = mttr_stats.get("total_incidents", 0)
    mttr_text.append(f"  p50: {p50:.1f}s\n", style="white")
    mttr_text.append(f"  p95: {p95:.1f}s\n", style="white")
    mttr_text.append(f"  Total: {total} incidents\n", style="dim")

    # Cost stats
    cost_text = Text()
    cost_text.append("💰  Token Cost Tracker\n", style="bold green")
    total_tokens = cost_stats.get("total_tokens", 0)
    total_cost = cost_stats.get("total_cost_usd", 0.0)
    avg_tokens = cost_stats.get("avg_tokens_per_incident", 0)
    cost_text.append(f"  Tokens Used: {total_tokens:,}\n", style="white")
    cost_text.append(f"  Total Cost:  ${total_cost:.4f}\n", style="white")
    cost_text.append(f"  Avg/Incident: {avg_tokens:,} tokens\n", style="dim")

    # SLA status
    sla_text = Text()
    sla_text.append("🎯  SLA Status\n", style="bold yellow")
    breaches = sla_status.get("sla_breaches", 0)
    autonomous_rate = sla_status.get("autonomous_resolution_rate", 0.0)
    target_met = sla_status.get("target_met", False)
    sla_color = "green" if target_met else "red"
    sla_text.append(f"  SLA Breaches: {breaches}\n", style="white")
    sla_text.append(f"  Auto-Resolve: {autonomous_rate:.0%}\n", style="white")
    sla_text.append(f"  Target: [bold {sla_color}]{'✓ MET' if target_met else '✗ MISSED'}[/bold {sla_color}]\n")

    t.add_row(mttr_text, cost_text, sla_text)
    return Panel(t, title="[bold white]📊 Analytics & SLA Dashboard[/bold white]", border_style="magenta")


def build_footer(refresh_count: int) -> Panel:
    """Builds the bottom status bar."""
    now_str = datetime.now().strftime("%H:%M:%S")
    parts = Text.assemble(
        ("  NeuroOps Live Dashboard  ", "bold cyan"),
        (f"│  Last refresh: {now_str}  ", "dim"),
        (f"│  Refresh #{refresh_count}  ", "dim"),
        (f"│  Interval: {REFRESH_INTERVAL}s  ", "dim"),
        ("│  Press Ctrl+C to exit  ", "dim"),
    )
    return Panel(parts, border_style="dim", padding=(0, 0))


# ── Main Dashboard Loop ────────────────────────────────────────────────────────

def make_layout(
    detector_url: str,
    agent_url: str,
    remediator_url: str,
    refresh_count: int,
) -> Layout:
    """Fetches all data and assembles the full dashboard layout."""
    # Parallel data fetching
    detector_health = fetch_health(detector_url)
    agent_health = fetch_health(agent_url)
    remediator_health = fetch_health(remediator_url)
    alerts = fetch_alerts(detector_url)
    correlated = fetch_correlated_alerts(detector_url)
    incidents = fetch_incidents(agent_url)
    mttr_stats = fetch_mttr_stats(agent_url)
    cost_stats = fetch_cost_stats(agent_url)
    sla_status = fetch_sla_status(agent_url)

    layout = Layout()
    layout.split_column(
        Layout(build_header(), name="header", size=11),
        Layout(name="body"),
        Layout(build_footer(refresh_count), name="footer", size=3),
    )
    layout["body"].split_column(
        Layout(
            build_service_health_panel(detector_health, agent_health, remediator_health, alerts),
            name="health",
            size=10,
        ),
        Layout(name="middle"),
        Layout(build_analytics_panel(mttr_stats, cost_stats, sla_status), name="analytics", size=9),
    )
    layout["middle"].split_row(
        Layout(build_alerts_panel(alerts, correlated), name="alerts"),
        Layout(build_incidents_panel(incidents), name="incidents"),
    )
    return layout


@click.command()
@click.option("--detector-url", default="http://localhost:8001", help="Detector service URL")
@click.option("--agent-url", default="http://localhost:8002", help="Agent service URL")
@click.option("--remediator-url", default="http://localhost:8003", help="Remediator service URL")
@click.option("--refresh", default=REFRESH_INTERVAL, help="Refresh interval in seconds")
def main(detector_url: str, agent_url: str, remediator_url: str, refresh: int) -> None:
    """
    NeuroOps Real-Time Live CLI Operations Dashboard.

    Displays live service health, active alerts, recent incidents, MTTR analytics,
    and token cost metrics. Auto-refreshes every N seconds (default: 5).
    """
    global REFRESH_INTERVAL
    REFRESH_INTERVAL = refresh

    console.print(
        Panel.fit(
            "[bold cyan]Starting NeuroOps Live Dashboard...[/bold cyan]\n"
            f"[dim]Connecting to: Detector={detector_url}  Agent={agent_url}  Remediator={remediator_url}[/dim]",
            border_style="cyan",
        )
    )

    refresh_count = 0
    try:
        with Live(
            make_layout(detector_url, agent_url, remediator_url, refresh_count),
            refresh_per_second=1,
            screen=True,
        ) as live:
            while True:
                time.sleep(refresh)
                refresh_count += 1
                live.update(
                    make_layout(detector_url, agent_url, remediator_url, refresh_count)
                )
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Dashboard stopped by user.[/bold yellow]")


if __name__ == "__main__":  # pragma: no cover
    main()
