import click
import httpx
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from datetime import datetime
import sys

# Define console for rich formatting with forced wide terminal for reliable rendering
console = Console(force_terminal=True, width=150)

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
        sys.exit(1)

def process_spans(data):
    """Process trace JSON to extract, sort, and clean spans."""
    traces = data.get("data", [])
    if not traces:
        return []
    
    # Collect all spans across all traces found (usually one main trace per incident)
    all_spans = []
    for trace in traces:
        all_spans.extend(trace.get("spans", []))
    
    # Sort chronologically by startTime (microseconds)
    all_spans.sort(key=lambda s: s.get("startTime", 0))
    return all_spans

def render_replay(spans, incident_id):
    """Renders the parsed spans into a premium terminal visualization."""
    if not spans:
        console.print(Panel(
            Text(f"No agent reasoning traces found for Incident ID '{incident_id}'.\n"
                 "Please ensure the incident graph has executed and Jaeger is running.",
                 style="bold yellow"),
            title="Warning: No Data Found",
            border_style="yellow"
        ))
        return

    # Initialize premium table
    table = Table(
        title=f"Multi-Agent Root Cause Analysis (RCA) Replay - Incident: {incident_id}",
        title_style="bold cyan",
        show_header=True,
        header_style="bold magenta",
        border_style="dim"
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
        # Check if span contains agent name attribute
        agent_name = get_tag_value(span, "agent.name")
        if not agent_name:
            continue
        
        # If supervisor synthesize, keep reference for final panel
        if agent_name == "supervisor_synthesize":
            supervisor_span = span

        # Parse basic fields
        start_time_us = span.get("startTime", 0)
        start_dt = datetime.fromtimestamp(start_time_us / 1000000.0)
        timestamp_str = start_dt.strftime("%H:%M:%S.%f")[:-3]

        decision = get_tag_value(span, "agent.decision") or "none"
        confidence_val = get_tag_value(span, "agent.confidence")
        tools = get_tag_value(span, "agent.tool_called") or "none"
        latency = get_tag_value(span, "agent.latency_ms") or 0
        tokens = get_tag_value(span, "agent.tokens_used") or 0

        # Color-code confidence
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

        # Format decision string nicely (truncating if too long, or keeping readable)
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

    # Print the timeline table
    console.print(table)
    console.print()

    # Renders the final executive summary card at the bottom
    if supervisor_span:
        hypothesis = get_tag_value(supervisor_span, "agent.decision") or "No hypothesis formulated."
        remediation = get_tag_value(supervisor_span, "agent.recommended_action") or "none"
        requires_approval = get_tag_value(supervisor_span, "agent.requires_human_approval")
        
        # Color coding for remediation action
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

@click.command()
@click.option(
    "--incident-id",
    required=True,
    help="The unique Incident ID to replay reasoning steps for."
)
@click.option(
    "--jaeger-url",
    default="http://localhost:16686",
    help="The Jaeger HTTP API endpoint base URL."
)
def main(incident_id, jaeger_url):
    """NeuroOps Multi-Agent Incident Reasoning CLI Replay Utility.
    
    Queries Jaeger distributed tracing context to assemble the chronologically
    sorted chain of thought executed by Detective, Topologist, Historian,
    and Supervisor agents.
    """
    console.print(f"[bold blue]Connecting to Jaeger at {jaeger_url} to retrieve incident {incident_id}...[/bold blue]")
    data = fetch_traces(jaeger_url, incident_id)
    spans = process_spans(data)
    render_replay(spans, incident_id)

if __name__ == "__main__":  # pragma: no cover
    main()
