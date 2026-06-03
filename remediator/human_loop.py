import os
import sys
import time
from typing import Any

import structlog
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

logger = structlog.get_logger()
console = Console()


def input_with_timeout(prompt: str, timeout: int = 300) -> str:
    """
    Prompts the user for input with a strict timeout in seconds.
    Supports Windows natively via msvcrt, and fallback to select/sys.stdin on Unix.
    """
    if not sys.stdin.isatty():
        logger.info("Non-interactive TTY environment detected, bypassing human input")
        return "n"

    try:
        import msvcrt

        # Windows console input with timeout
        sys.stdout.write(prompt)
        sys.stdout.flush()
        start = time.time()
        chars = []

        while time.time() - start < timeout:
            if msvcrt.kbhit():
                char = msvcrt.getch()
                if char in (b"\r", b"\n"):
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    break
                elif char == b"\b":  # Backspace
                    if chars:
                        chars.pop()
                        sys.stdout.write("\b \b")
                        sys.stdout.flush()
                else:
                    try:
                        decoded = char.decode("utf-8")
                        chars.append(decoded)
                        sys.stdout.write(decoded)
                        sys.stdout.flush()
                    except UnicodeDecodeError:
                        pass
            time.sleep(0.05)
        else:
            sys.stdout.write("\n")
            sys.stdout.flush()
            logger.info("Windows CLI approval prompt timed out")
            return "n"

        return "".join(chars).strip()

    except ImportError:
        # Unix console input with timeout
        import select

        sys.stdout.write(prompt)
        sys.stdout.flush()
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if ready:
            return sys.stdin.readline().strip()
        else:
            sys.stdout.write("\n")
            sys.stdout.flush()
            logger.info("Unix CLI approval prompt timed out")
            return "n"


def prompt_human(hypothesis: dict[str, Any] | Any, action: str) -> bool:
    """
    Prints a premium visual CLI report summarizing the incident details,
    the agent's diagnosis reasoning chain, the proposed remediation action,
    and prompts the operator for approval.
    """
    # Check for unit testing overrides to prevent hanging in test suite execution
    test_approval = os.getenv("REMEDIATOR_TEST_APPROVAL")
    if test_approval is not None:
        logger.info("Test approval override detected", value=test_approval)
        return test_approval.lower() == "true"

    # Extract fields from dict or Pydantic model safely
    def get_val(obj, key, default=""):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    incident_id = get_val(hypothesis, "incident_id", "unknown")
    hyp_text = get_val(hypothesis, "hypothesis", "N/A")
    confidence = get_val(hypothesis, "confidence", 0.0)
    reasoning = get_val(hypothesis, "reasoning", "No reasoning provided.")

    # 1. Classify Risk Level
    action_lower = action.lower()
    if "rollback" in action_lower:
        risk_level = "HIGH"
        risk_color = "red"
        risk_desc = (
            "Reverts deployment image & configurations to a prior revision. High potential impact."
        )
    elif action_lower in ("restart", "scale", "patch_configmap", "scale_replicas"):
        risk_level = "MEDIUM"
        risk_color = "yellow"
        risk_desc = (
            "Modifies active resource replica scales or restarts active container instances."
        )
    elif action_lower in ("open_github_pr", "open_pr"):
        risk_level = "LOW"
        risk_color = "green"
        risk_desc = "Opens a config adjustment Pull Request on GitHub. Safe and non-destructive."
    else:
        risk_level = "LOW"
        risk_color = "green"
        risk_desc = "No immediate destructive actions proposed."

    # 2. Render Incident Panel
    console.print()
    title_text = Text(
        f"🚨 NEUROOPS INCIDENT RESOLUTION PANEL [{incident_id}] 🚨",
        style="bold white on red",
        justify="center",
    )
    console.print(Panel(title_text, border_style="red"))

    # Summary Table
    table = Table(show_header=False, expand=True, border_style="dim")
    table.add_column("Key", style="bold cyan", width=25)
    table.add_column("Value", style="white")

    table.add_row("Root Cause Hypothesis", hyp_text)
    table.add_row("Agent Confidence", f"{confidence * 100:.1f}%")
    table.add_row("Proposed Action", f"[bold green]{action.upper()}[/bold green]")
    table.add_row("Risk Severity", f"[bold {risk_color}]{risk_level} RISK[/bold {risk_color}]")
    table.add_row("Risk Implications", f"[italic dim]{risk_desc}[/italic dim]")

    console.print(
        Panel(table, title="[bold white]Incident Overview[/bold white]", border_style=risk_color)
    )

    # Agent Reasoning Panel
    reason_panel = Panel(
        Text(reasoning, style="white"),
        title="[bold white]Agent Diagnosis Reasoning Chain[/bold white]",
        border_style="cyan",
    )
    console.print(reason_panel)

    # 3. Prompt for Operator input
    prompt_str = "\n👉 Approve this remediation action? [y/n] (Timeout 5m, default 'n'): "
    ans = input_with_timeout(prompt_str, timeout=300)

    approved = ans.lower() in ("y", "yes")

    if approved:
        console.print(
            "[bold green]✔ Remediation action approved. Launching recovery...[/bold green]\n"
        )
        logger.info("Remediation approved by operator", incident_id=incident_id, action=action)
    else:
        console.print("[bold red]✘ Remediation action rejected or timed out.[/bold red]\n")
        logger.info("Remediation rejected by operator", incident_id=incident_id, action=action)

    return approved
