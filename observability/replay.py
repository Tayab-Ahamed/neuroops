"""
observability/replay.py — Multi-Agent Incident Reasoning CLI Replay Utility

Queries Jaeger distributed tracing context to assemble and replay the full
chain of reasoning executed by Detective, Topologist, Historian, Log Analyser,
and Supervisor agents.

Falls back to the NeuroOps SQLite IncidentStore when Jaeger is unavailable.

Usage:
    # Replay from Jaeger (primary)
    python observability/replay.py --incident-id inc-abc123

    # Replay from SQLite fallback (no Jaeger required)
    python observability/replay.py --incident-id inc-abc123 --use-sqlite

    # List all available incidents
    python observability/replay.py --list

    # List incidents from a specific agent service
    python observability/replay.py --list --agent-url http://localhost:8002
"""
import click
import httpx
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box
from datetime import datetime
import sys
import os
import sqlite3
import json

# Define console for rich formatting with forced wide terminal for reliable rendering
console = Console(force_terminal=True, width=150)


# ── Jaeger helpers ─────────────────────────────────────────────────────────────

def get_tag_value(span, key):
    """Helper to extract a tag's value from a Jaeger span."""
    for tag in span.get("tags", []):
        if tag.get("key") == key:
            return tag.get("value")
    return None


def fetch_traces(jaeger_url, incident_id):
    """Fetch trace from Jaeger API based on the incident ID."""
    url = f"{jaeger_url.rstrip('/')}/api/traces"
    params = {
        "service": "neuroops.agent",
        "tag": f"incident.id:{incident_id}"
    }
    try:
        response = httpx.get(url, params=params, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        console.print(f"[bold red]Error: Failed to query Jaeger API[/bold red] - {e}")
        return None


def process_spans(data):
    """Process trace JSON to extract, sort, and clean spans."""
    if not data:
        return []
    traces = data.get("data", [])
    if not traces:
        return []

    all_spans = []
    for trace in traces:
        all_spans.extend(trace.get("spans", []))

    all_spans.sort(key=lambda s: s.get("startTime", 0))
    return all_spans


# ── SQLite fallback helpers ────────────────────────────────────────────────────

def fetch_from_sqlite(db_path: str, incident_id: str):
    """
    Fetches incident trace from the NeuroOps SQLite IncidentStore.
    Returns the stored trace_timeline list or None if not found.
    """
    if not os.path.exists(db_path):
        console.print(f"[yellow]SQLite DB not found at: {db_path}[/yellow]")
        return None, None
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT incident_id, service, hypothesis, confidence,
                       recommended_action, requires_human_approval, reasoning,
                       tokens_used, trace_json, mttr_seconds, created_at
                FROM incidents WHERE incident_id = ?
                """,
                (incident_id,),
            ).fetchone()
        if not row:
            return None, None
        trace = json.loads(row["trace_json"]) if row["trace_json"] else []
        incident_meta = dict(row)
        return trace, incident_meta
    except Exception as e:
        console.print(f"[red]SQLite query failed: {e}[/red]")
        return None, None


def list_incidents_from_api(agent_url: str):
    """Fetches the incident list from the running Agent service."""
    try:
        response = httpx.get(f"{agent_url}/incidents?limit=50", timeout=5.0)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        console.print(f"[yellow]Could not reach Agent API ({agent_url}): {e}[/yellow]")
        return None


def list_incidents_from_sqlite(db_path: str):
    """Lists all incidents from SQLite directly."""
    if not os.path.exists(db_path):
        return []
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT incident_id, service, hypothesis, confidence,
                       recommended_action, requires_human_approval,
                       tokens_used, mttr_seconds, created_at
                FROM incidents
                ORDER BY created_at DESC
                LIMIT 50
                """
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        console.print(f"[red]SQLite list failed: {e}[/red]")
        return []


# ── Renderers ──────────────────────────────────────────────────────────────────

def render_incident_list(incidents):
    """Renders a rich table of all available incidents."""
    if not incidents:
        console.print(Panel(
            "[yellow]No incidents found.[/yellow]",
            title="Incident List",
            border_style="yellow"
        ))
        return

    table = Table(
        title="Available NeuroOps Incidents (Latest First)",
        title_style="bold cyan",
        show_header=True,
        header_style="bold magenta",
        border_style="dim",
        box=box.SIMPLE,
    )
    table.add_column("Incident ID", style="dim", width=16)
    table.add_column("Service", style="bold")
    table.add_column("Confidence", justify="right", width=11)
    table.add_column("Action")
    table.add_column("MTTR", justify="right", width=10)
    table.add_column("Human?", justify="center", width=7)
    table.add_column("Tokens", justify="right", width=8)
    table.add_column("Timestamp", width=12)

    for inc in incidents:
        conf = inc.get("confidence", 0.0)
        if conf >= 0.8:
            conf_str = f"[bold green]{conf:.0%}[/bold green]"
        elif conf >= 0.6:
            conf_str = f"[bold yellow]{conf:.0%}[/bold yellow]"
        else:
            conf_str = f"[bold red]{conf:.0%}[/bold red]"

        mttr = inc.get("mttr_seconds")
        mttr_str = f"{mttr:.0f}s" if mttr else "[dim]N/A[/dim]"

        human = inc.get("requires_human_approval", False)
        human_str = "[red]YES[/red]" if human else "[green]NO[/green]"

        ts = inc.get("created_at", 0.0)
        ts_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "?"

        table.add_row(
            inc.get("incident_id", "?"),
            inc.get("service", "?"),
            conf_str,
            f"[cyan]{inc.get('recommended_action', 'none')}[/cyan]",
            mttr_str,
            human_str,
            str(inc.get("tokens_used", 0)),
            ts_str,
        )

    console.print(table)
    console.print(
        f"\n[dim]Tip: Replay any incident with: "
        f"python observability/replay.py --incident-id <INCIDENT_ID>[/dim]"
    )


def render_sqlite_replay(trace, meta):
    """Renders a stored SQLite incident trace as a formatted table."""
    table = Table(
        title=f"Agent Reasoning Replay (SQLite) — Incident: {meta['incident_id']}",
        title_style="bold cyan",
        show_header=True,
        header_style="bold magenta",
        border_style="dim",
        box=box.SIMPLE,
    )
    table.add_column("Step", width=5, style="dim")
    table.add_column("Agent / Span", style="bold green", width=22)
    table.add_column("Action / Summary", style="white")
    table.add_column("Finding Snippet", style="dim")

    for step in trace:
        step_num = str(step.get("step", "?"))
        agent = step.get("agent", "?")
        action = step.get("action", "")
        findings = step.get("findings") or {}

        # Extract a meaningful snippet from findings
        snippet = ""
        if isinstance(findings, dict):
            snippet = (
                findings.get("likely_origin")
                or findings.get("bottleneck")
                or findings.get("suspect_commit")
                or str(findings.get("error_logs", [""]))[0:60]
                or ""
            )
        if len(snippet) > 70:
            snippet = snippet[:67] + "..."

        table.add_row(step_num, agent, action, snippet)

    console.print(table)
    console.print()

    # Executive summary panel
    conf = meta.get("confidence", 0.0)
    hypothesis = meta.get("hypothesis", "N/A")
    action = meta.get("recommended_action", "none")
    requires_approval = meta.get("requires_human_approval", False)
    mttr = meta.get("mttr_seconds")
    tokens = meta.get("tokens_used", 0)

    rem_color = "green" if action != "none" else "white"
    approval_str = "[bold red]YES[/bold red]" if requires_approval else "[bold green]NO[/bold green]"
    mttr_str = f"{mttr:.1f}s" if mttr else "N/A"

    if conf >= 0.8:
        conf_str = f"[bold green]{conf:.0%}[/bold green]"
    elif conf >= 0.6:
        conf_str = f"[bold yellow]{conf:.0%}[/bold yellow]"
    else:
        conf_str = f"[bold red]{conf:.0%}[/bold red]"

    summary_text = (
        f"[bold cyan]Root Cause Hypothesis:[/bold cyan]\n{hypothesis}\n\n"
        f"[bold cyan]Confidence:[/bold cyan] {conf_str}   "
        f"[bold cyan]MTTR:[/bold cyan] {mttr_str}   "
        f"[bold cyan]Tokens:[/bold cyan] {tokens:,}\n\n"
        f"[bold cyan]Remediation Action:[/bold cyan] [bold {rem_color}]{action.upper()}[/bold {rem_color}]\n"
        f"[bold cyan]Requires Human Approval:[/bold cyan] {approval_str}"
    )

    console.print(Panel(
        summary_text,
        title="[bold green]EXECUTIVE REMEDIATION DECISION (SQLite Replay)[/bold green]",
        border_style="bright_blue",
        padding=(1, 2)
    ))


def render_replay(spans, incident_id):
    """Renders parsed Jaeger spans into a premium terminal visualization."""
    if not spans:
        console.print(Panel(
            Text(f"No agent reasoning traces found for Incident ID '{incident_id}'.\n"
                 "Please ensure the incident graph has executed and Jaeger is running.\n\n"
                 "Tip: Use --use-sqlite flag to fall back to local SQLite store.",
                 style="bold yellow"),
            title="Warning: No Jaeger Data Found",
            border_style="yellow"
        ))
        return

    # Initialize premium table
    table = Table(
        title=f"Multi-Agent Root Cause Analysis (RCA) Replay — Incident: {incident_id}",
        title_style="bold cyan",
        show_header=True,
        header_style="bold magenta",
        border_style="dim",
        box=box.SIMPLE,
    )
    table.add_column("Timestamp", style="dim")
    table.add_column("Agent / Span", style="bold green")
    table.add_column("Decision / Finding", style="white")
    table.add_column("Confidence", justify="right")
    table.add_column("Tool(s) Triggered", style="yellow")
    table.add_column("Latency", justify="right", style="cyan")
    table.add_column("LLM Tokens", justify="right", style="purple")

    supervisor_span = None

    for span in spans:
        agent_name = get_tag_value(span, "agent.name")
        if not agent_name:
            continue

        if agent_name == "supervisor_synthesize":
            supervisor_span = span

        start_time_us = span.get("startTime", 0)
        start_dt = datetime.fromtimestamp(start_time_us / 1000000.0)
        timestamp_str = start_dt.strftime("%H:%M:%S.%f")[:-3]

        decision = get_tag_value(span, "agent.decision") or "none"
        confidence_val = get_tag_value(span, "agent.confidence")
        tools = get_tag_value(span, "agent.tool_called") or "none"
        latency = get_tag_value(span, "agent.latency_ms") or 0
        tokens = get_tag_value(span, "agent.tokens_used") or 0

        confidence_str = "N/A"
        if confidence_val is not None:
            try:
                conf = float(confidence_val)
                if conf >= 0.8:
                    confidence_str = f"[bold green]{conf:.2f}[/bold green]"
                elif conf >= 0.6:
                    confidence_str = f"[bold yellow]{conf:.2f}[/bold yellow]"
                else:
                    confidence_str = f"[bold red]{conf:.2f}[/bold red]"
            except (ValueError, TypeError):
                confidence_str = str(confidence_val)

        latency_str = f"{latency}ms"
        tokens_str = f"{tokens}" if tokens > 0 else "0"

        if len(decision) > 80:
            decision_formatted = decision[:77] + "..."
        else:
            decision_formatted = decision

        table.add_row(
            timestamp_str,
            agent_name,
            decision_formatted,
            confidence_str,
            tools,
            latency_str,
            tokens_str
        )

    console.print(table)
    console.print()

    if supervisor_span:
        hypothesis = get_tag_value(supervisor_span, "agent.decision") or "No hypothesis formulated."
        remediation = get_tag_value(supervisor_span, "agent.recommended_action") or "none"
        requires_approval = get_tag_value(supervisor_span, "agent.requires_human_approval")

        rem_color = "green" if remediation != "none" else "white"
        approval_str = "[bold red]YES[/bold red]" if requires_approval else "[bold green]NO[/bold green]"

        summary_text = (
            f"[bold cyan]Root Cause Hypothesis:[/bold cyan]\n{hypothesis}\n\n"
            f"[bold cyan]Remediation Action Recommended:[/bold cyan] [bold {rem_color}]{remediation.upper()}[/bold {rem_color}]\n"
            f"[bold cyan]Requires Human Operator Approval:[/bold cyan] {approval_str}"
        )

        console.print(Panel(
            summary_text,
            title="[bold green]EXECUTIVE REMEDIATION DECISION[/bold green]",
            border_style="bright_blue",
            padding=(1, 2)
        ))
    else:
        console.print(Panel(
            "[bold yellow]Warning:[/bold yellow] Supervisor Synthesis node traces were not found in the incident dataset.\n"
            "An executive remediation decision could not be compiled.",
            title="Incident Summary Incomplete",
            border_style="yellow",
            padding=(1, 2)
        ))


# ── CLI Entry Point ────────────────────────────────────────────────────────────

@click.command()
@click.option(
    "--incident-id",
    default=None,
    help="The unique Incident ID to replay reasoning steps for."
)
@click.option(
    "--jaeger-url",
    default="http://localhost:16686",
    help="The Jaeger HTTP API endpoint base URL."
)
@click.option(
    "--agent-url",
    default="http://localhost:8002",
    help="The NeuroOps Agent API base URL (used for --list and SQLite path)."
)
@click.option(
    "--db-path",
    default=None,
    help="Path to the NeuroOps SQLite IncidentStore DB (auto-detected if not set)."
)
@click.option(
    "--use-sqlite",
    is_flag=True,
    default=False,
    help="Skip Jaeger and replay directly from the local SQLite IncidentStore."
)
@click.option(
    "--list",
    "list_mode",
    is_flag=True,
    default=False,
    help="List all available incidents (from Agent API or SQLite)."
)
def main(incident_id, jaeger_url, agent_url, db_path, use_sqlite, list_mode):
    """
    NeuroOps Multi-Agent Incident Reasoning CLI Replay Utility.

    Queries Jaeger distributed tracing context to assemble the chronologically
    sorted chain of thought executed by Detective, Topologist, Historian,
    and Supervisor agents. Falls back to SQLite when Jaeger is unavailable.
    """
    # Resolve SQLite DB path
    resolved_db = db_path or os.getenv("AGENT_DB_PATH", "checkpoints/agent_incidents.db")

    # ── List mode ──────────────────────────────────────────────────────────────
    if list_mode:
        console.print(f"[bold blue]Fetching incident list from Agent API ({agent_url})...[/bold blue]")
        incidents = list_incidents_from_api(agent_url)
        if not incidents:
            console.print(f"[yellow]Falling back to SQLite: {resolved_db}[/yellow]")
            incidents = list_incidents_from_sqlite(resolved_db)
        render_incident_list(incidents)
        return

    # ── Replay mode ────────────────────────────────────────────────────────────
    if not incident_id:
        console.print("[red]Error: --incident-id is required for replay mode.[/red]")
        console.print("[dim]Use --list to see available incidents.[/dim]")
        sys.exit(1)

    # ── SQLite replay ──────────────────────────────────────────────────────────
    if use_sqlite:
        console.print(f"[bold blue]Replaying incident '{incident_id}' from SQLite: {resolved_db}[/bold blue]")
        trace, meta = fetch_from_sqlite(resolved_db, incident_id)
        if not trace or not meta:
            console.print(f"[red]Incident '{incident_id}' not found in SQLite.[/red]")
            sys.exit(1)
        render_sqlite_replay(trace, meta)
        return

    # ── Jaeger replay (primary) ────────────────────────────────────────────────
    console.print(f"[bold blue]Connecting to Jaeger at {jaeger_url} to retrieve incident {incident_id}...[/bold blue]")
    data = fetch_traces(jaeger_url, incident_id)

    if data is None:
        # Auto-fallback to SQLite
        console.print(f"[yellow]Jaeger unavailable. Falling back to SQLite: {resolved_db}[/yellow]")
        trace, meta = fetch_from_sqlite(resolved_db, incident_id)
        if not trace or not meta:
            console.print(f"[red]Incident '{incident_id}' not found in SQLite either.[/red]")
            sys.exit(1)
        render_sqlite_replay(trace, meta)
        return

    spans = process_spans(data)

    if not spans:
        # Auto-fallback to SQLite
        console.print(f"[yellow]No Jaeger spans found. Falling back to SQLite: {resolved_db}[/yellow]")
        trace, meta = fetch_from_sqlite(resolved_db, incident_id)
        if trace and meta:
            render_sqlite_replay(trace, meta)
        else:
            render_replay([], incident_id)
        return

    render_replay(spans, incident_id)


if __name__ == "__main__":  # pragma: no cover
    main()
