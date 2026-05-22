import os
import asyncio
import logging
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("database-stub")

app = FastAPI(title="NeuroOps Database Stub Service")

# Setup metrics
Instrumentator().instrument(app).expose(app)

# Setup tracing
service_name = os.getenv("OTEL_SERVICE_NAME", "database-stub")
resource = Resource.create(attributes={"service.name": service_name})
provider = TracerProvider(resource=resource)
otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")

logger.info(f"Initializing database-stub tracing with service name {service_name} exporting to {otlp_endpoint}")
exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
processor = BatchSpanProcessor(exporter)
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)
FastAPIInstrumentor.instrument_app(app)

tracer = trace.get_tracer(__name__)

@app.get("/query")
async def query():
    with tracer.start_as_current_span("db_query") as span:
        logger.info("Database-stub: simulating database query...")
        # Simulate query latency (50ms as designed)
        await asyncio.sleep(0.05)
        span.set_attribute("db.system", "stub-json")
        span.set_attribute("db.statement", "SELECT * FROM states WHERE project='neuroops'")
        return {
            "status": "success",
            "message": "NeuroOps database state is optimal.",
            "data": {
                "active_agents": 4,
                "remediations_completed": 42,
                "system_health": "100%"
            }
        }

@app.get("/health")
async def health():
    return {"status": "healthy"}
