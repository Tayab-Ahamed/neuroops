import os

import httpx
import structlog
from rich.console import Console
from rich.panel import Panel

logger = structlog.get_logger()
console = Console()


def send_slack_alert(
    incident_id: str, hypothesis: str, confidence: float, action: str, requires_human_approval: bool
) -> bool:
    """Sends a rich alert payload to a Slack webhook, Slack channel, or local CLI fallback log."""
    try:
        token = os.getenv("SLACK_API_TOKEN")
        channel = os.getenv("SLACK_CHANNEL_ID")
        webhook_url = os.getenv("SLACK_WEBHOOK_URL")

        safety_status = (
            "Human Approval Required" if requires_human_approval else "Autonomous Execution"
        )
        title_text = "NeuroOps Autonomous Incident Diagnosis"

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{title_text}*\n"
                        f"*Incident ID:* `{incident_id}`\n"
                        f"*Root Cause Hypothesis:* {hypothesis}\n"
                        f"*Diagnostic Confidence:* `{confidence * 100:.1f}%`\n"
                        f"*Proposed Action:* `{action.upper()}`\n"
                        f"*Safety Status:* {safety_status}"
                    ),
                },
            }
        ]

        if requires_human_approval:
            blocks.append(
                {
                    "type": "actions",
                    "block_id": f"approval_{incident_id}",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "Approve Remediation",
                                "emoji": True,
                            },
                            "style": "primary",
                            "value": "approved",
                            "action_id": "approve_btn",
                        },
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "Reject Remediation",
                                "emoji": True,
                            },
                            "style": "danger",
                            "value": "rejected",
                            "action_id": "reject_btn",
                        },
                    ],
                }
            )

        if webhook_url:
            logger.info("Sending incident alert to Slack Webhook", incident_id=incident_id)
            response = httpx.post(webhook_url, json={"blocks": blocks}, timeout=10.0)
            if not 200 <= response.status_code < 300:
                logger.warning(
                    "Slack Webhook alert returned non-2xx status",
                    incident_id=incident_id,
                    status_code=response.status_code,
                )
                return False
            return True

        if token and channel:
            logger.info(
                "Sending incident alert to Slack Channel API",
                incident_id=incident_id,
                channel=channel,
            )
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            payload = {"channel": channel, "blocks": blocks}
            response = httpx.post(
                "https://slack.com/api/chat.postMessage",
                headers=headers,
                json=payload,
                timeout=10.0,
            )
            if not 200 <= response.status_code < 300:
                logger.warning(
                    "Slack API alert returned non-2xx status",
                    incident_id=incident_id,
                    status_code=response.status_code,
                )
                return False
            response_payload = response.json()
            if not response_payload.get("ok", False):
                logger.warning(
                    "Slack API alert returned unsuccessful payload",
                    incident_id=incident_id,
                    status_code=response.status_code,
                    slack_error=response_payload.get("error"),
                )
                return False
            return True

        console.print(
            Panel(
                f"[bold yellow][ChatOps FALLBACK LOG][/bold yellow]\n\n"
                f"[bold]Incident ID:[/bold] `{incident_id}`\n"
                f"[bold]Hypothesis:[/bold] {hypothesis}\n"
                f"[bold]Confidence:[/bold] {confidence * 100:.1f}%\n"
                f"[bold]Recommended Action:[/bold] {action.upper()}\n"
                f"[bold]Requires Approval:[/bold] {requires_human_approval}\n\n"
                f"[dim]Note: Slack credentials not configured. Falling back to stdout.[/dim]",
                border_style="yellow",
                title="ChatOps Notification",
            )
        )
        return True
    except Exception as exc:
        logger.warning(
            "Failed sending Slack alert",
            incident_id=incident_id,
            error=str(exc),
            exc_info=True,
        )
        return False


def send_pagerduty_alert(incident_id: str, summary: str, severity: str = "warning") -> bool:
    """Sends a PagerDuty event when configured; failures never block remediation."""
    try:
        routing_key = os.getenv("PAGERDUTY_ROUTING_KEY")
        if not routing_key:
            return False

        payload = {
            "routing_key": routing_key,
            "event_action": "trigger",
            "dedup_key": incident_id,
            "payload": {
                "summary": summary,
                "source": "neuroops.remediator",
                "severity": severity,
            },
        }
        response = httpx.post(
            "https://events.pagerduty.com/v2/enqueue",
            json=payload,
            timeout=10.0,
        )
        if not 200 <= response.status_code < 300:
            logger.warning(
                "PagerDuty alert returned non-2xx status",
                incident_id=incident_id,
                status_code=response.status_code,
            )
            return False
        return True
    except Exception as exc:
        logger.warning(
            "Failed sending PagerDuty alert",
            incident_id=incident_id,
            error=str(exc),
            exc_info=True,
        )
        return False
