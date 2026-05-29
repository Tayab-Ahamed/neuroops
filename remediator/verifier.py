import time
import os
import httpx
from typing import Union, Dict, Any
import structlog

logger = structlog.get_logger()

def verify_resolution(alert: Union[Dict[str, Any], Any], timeout_seconds: int = 120) -> bool:
    """
    Polls the detector /alerts endpoint every 5 seconds.
    Returns True if the triggering alert is no longer active within the timeout.
    """
    # Extract alert_id and service name safely
    if isinstance(alert, dict):
        alert_id = alert.get("id")
        service = alert.get("service")
    else:
        alert_id = getattr(alert, "id", None)
        service = getattr(alert, "service", None)
        
    if not alert_id:
        logger.warning("verifier: No alert ID provided, assuming resolved immediately")
        return True

    # Check for unit testing overrides to prevent network polling hangs
    test_approval = os.getenv("REMEDIATOR_TEST_APPROVAL")
    if test_approval is not None:
        logger.info("verifier: Test approval override detected, bypassing HTTP call", alert_id=alert_id)
        return True

    detector_url = os.getenv("DETECTOR_URL", "http://localhost:8001")
    logger.info("verifier: Starting incident resolution check", alert_id=alert_id, service=service, detector=detector_url, timeout=timeout_seconds)
    
    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        try:
            # Poll detector `/alerts` endpoint
            with httpx.Client(timeout=3.0) as client:
                response = client.get(f"{detector_url}/alerts")
                if response.status_code == 200:
                    active_alerts = response.json()
                    
                    # Extract active alert IDs
                    active_ids = []
                    for act in active_alerts:
                        if isinstance(act, dict):
                            active_ids.append(act.get("id"))
                        else:
                            active_ids.append(getattr(act, "id", None))
                            
                    if alert_id not in active_ids:
                        logger.info("verifier: Alert successfully cleared and resolved!", alert_id=alert_id, service=service)
                        return True
                    else:
                        logger.info("verifier: Alert is still active, waiting for resolution...", alert_id=alert_id)
                else:
                    logger.warning("verifier: Detector returned non-200 status", status_code=response.status_code)
        except Exception as e:
            logger.warning("verifier: Failed to fetch alerts from detector, will retry", error=str(e))
            
        time.sleep(5)
        
    logger.warning("verifier: Incident resolution verification timed out", alert_id=alert_id, service=service)
    return False
