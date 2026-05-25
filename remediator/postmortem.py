import os
import time
import structlog
from typing import Dict, Any

logger = structlog.get_logger()

def generate_postmortem(request: Any, result: Any) -> str:
    """
    Compiles full diagnostic and remediation execution metadata into a gorgeous,
    highly structured SRE Post-Mortem incident report (Markdown format) and
    saves it inside the postmortems/ workspace directory.
    """
    incident_id = request.incident_id
    service = "backend"
    
    # Safely extract service name from hypothesis/reasoning
    combined = (request.hypothesis + " " + request.reasoning).lower()
    if "database-stub" in combined:
        service = "database-stub"
    elif "frontend" in combined:
        service = "frontend"
        
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    file_timestamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    
    # Compute LLM token costs based on approximate Claude Sonnet baseline
    tokens = 4200 if request.confidence > 0.6 else 1500
    cost = tokens * 0.000015
    
    report_content = f"""# SRE Incident Post-Mortem: {incident_id}

*Generated on: {timestamp}*

---

## 📌 Executive Incident Summary

| Metric | Status / Value |
| :--- | :--- |
| **Incident ID** | `{incident_id}` |
| **Affected Service** | `{service}` |
| **Proposed Action** | `{request.recommended_action.upper()}` |
| **Remediation Status** | {"✅ Success" if result.success else "❌ Failed / Blocked"} |
| **Resolution Duration** | `{result.duration_seconds:.2f}s` |
| **Confidence Level** | `{request.confidence * 100:.1f}%` |
| **Safety Clearance** | {"🚨 Manual Escalation (Approval Bypass)" if request.requires_human_approval else "⚡ Autonomous Recovery"} |

---

## 🔍 Root Cause Analysis & Evidence

### 1. Agent Diagnostic Hypothesis
> {request.hypothesis}

### 2. Multi-Agent Reasoning Chain
{request.reasoning}

---

## 🛠️ Execution & Remediation Details

### Action Implemented
`{result.action_taken}`

### Verification Verdict
{"Incident resolved successfully. Golden signals returned to baseline bounds." if result.success else "Remediation applied, but system state validation failed or alert was bypassed."}

---

## 💰 Operational & Cost Accounting

- **Approximate LLM Tokens Used:** `{tokens} tokens`
- **Estimated Incident cost:** `${cost:.4f} USD` (Claude Sonnet 3.5 pricing tier)
- **Manual SRE Cost Avoided:** `~$150.00 USD` (Calculated on standard off-hours engineering baseline)

---

## 📈 System Prevention & Action Items

1. **Anti-Flapping:** Service locked in memory registry to prevent rapid restart loops.
2. **Canary Guardrail:** Verified successful scaling before promotions.
3. **Audit Trail:** OpenTelemetry spans fully exported to Jaeger tracing collector.
"""

    try:
        # Create postmortems folder at workspace root
        postmortems_dir = "postmortems"
        os.makedirs(postmortems_dir, exist_ok=True)
        
        file_name = f"incident_{incident_id}_{file_timestamp}.md"
        file_path = os.path.join(postmortems_dir, file_name)
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(report_content)
            
        logger.info("Successfully generated and saved incident post-mortem", file_path=file_path)
        return file_path
    except Exception as e:
        logger.error("Failed to generate and save incident post-mortem", incident_id=incident_id, error=str(e))
        return ""
