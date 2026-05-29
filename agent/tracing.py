import os
import time
from typing import Callable, Any
from functools import wraps
import structlog
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger()

# Setup OpenTelemetry tracer
OTEL_ENDPOINT = os.getenv("OTEL_COLLECTOR_ENDPOINT", "http://localhost:4317")
resource = Resource.create(attributes={"service.name": "neuroops.agent"})
provider = TracerProvider(resource=resource)

try:
    # Attempt to initialize OTLP gRPC exporter
    otlp_exporter = OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True)
    provider.add_span_processor(SimpleSpanProcessor(otlp_exporter))
    trace.set_tracer_provider(provider)
    logger.info("Successfully configured OpenTelemetry OTLP exporter", endpoint=OTEL_ENDPOINT)
except Exception as e:
    logger.warning("Failed to configure OTel OTLP exporter, falling back to Console Span Processor", error=str(e))
    # No-op trace provider fallback
    trace.set_tracer_provider(provider)

tracer = trace.get_tracer("neuroops.agent")

# Tenacity retry configuration for LLM API calls
llm_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True
)

def traced_node(agent_name: str) -> Callable:
    """Decorator to trace a LangGraph agent node's execution in an OpenTelemetry span."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(state: Any, *args, **kwargs) -> Any:
            incident_id = state.get("incident_id", "unknown")
            logger.info("Executing agent node", agent=agent_name, incident_id=incident_id)
            
            start_time = time.time()
            with tracer.start_as_current_span(f"agent.{agent_name}") as span:
                span.set_attribute("agent.name", agent_name)
                span.set_attribute("incident.id", incident_id)
                
                try:
                    result = await func(state, *args, **kwargs)
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    logger.error("Error in agent node execution", agent=agent_name, error=str(e))
                    raise e
                
                # Capture standard decision features and latency attributes
                decision = ""
                confidence = 0.0
                requires_human = False
                tool_called = ""
                tokens_used = 0
                recommended_action = ""
                
                if isinstance(result, dict):
                    # Check if keys are nested inside the agent's findings
                    findings = result.get(f"{agent_name}_findings") or result
                    if isinstance(findings, dict):
                        decision = findings.get("hypothesis") or findings.get("recommended_action") or findings.get("likely_origin") or findings.get("bottleneck") or ""
                        confidence = findings.get("confidence") or 0.0
                        requires_human = findings.get("requires_human_approval") or False
                        tool_called = findings.get("tool_called") or ""
                        tokens_used = findings.get("tokens_used") or 0
                        recommended_action = findings.get("recommended_action") or ""
                
                latency_ms = int((time.time() - start_time) * 1000)
                
                span.set_attribute("agent.decision", str(decision))
                span.set_attribute("agent.confidence", float(confidence))
                span.set_attribute("agent.requires_human_approval", bool(requires_human))
                span.set_attribute("agent.latency_ms", latency_ms)
                span.set_attribute("agent.tool_called", str(tool_called))
                span.set_attribute("agent.tokens_used", int(tokens_used))
                span.set_attribute("agent.recommended_action", str(recommended_action))
                
                logger.info("Agent node execution completed", agent=agent_name, latency_ms=latency_ms)
                return result
        return wrapper
    return decorator
