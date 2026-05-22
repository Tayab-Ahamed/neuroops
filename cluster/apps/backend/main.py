import os
import httpx
import logging
from fastapi import FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.propagate import inject

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend")

app = FastAPI(title="NeuroOps Backend Service")

# Setup metrics
Instrumentator().instrument(app).expose(app)

# Setup tracing
service_name = os.getenv("OTEL_SERVICE_NAME", "backend")
resource = Resource.create(attributes={"service.name": service_name})
provider = TracerProvider(resource=resource)
otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")

logger.info(f"Initializing backend tracing with service name {service_name} exporting to {otlp_endpoint}")
exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
processor = BatchSpanProcessor(exporter)
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)
FastAPIInstrumentor.instrument_app(app)

tracer = trace.get_tracer(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "http://localhost:8082")

@app.get("/data")
async def data():
    with tracer.start_as_current_span("backend_data") as span:
        logger.info("Backend: handling /data request, calling database-stub...")
        # Inject tracing headers to propagate span downstream
        headers = {}
        inject(headers)
        
        async with httpx.AsyncClient() as client:
            try:
                database_endpoint = f"{DATABASE_URL}/query"
                logger.info(f"Calling database-stub at {database_endpoint} with injected headers: {headers}")
                response = await client.get(database_endpoint, headers=headers, timeout=5.0)
                if response.status_code != 200:
                    logger.error(f"Database-stub returned status code {response.status_code}")
                    raise HTTPException(status_code=502, detail="Database stub returned error status code")
                
                db_data = response.json()
                return {
                    "status": "success",
                    "processed_by": "backend",
                    "database_data": db_data
                }
            except Exception as e:
                logger.error(f"Error calling database stub: {str(e)}")
                span.record_exception(e)
                raise HTTPException(status_code=500, detail=f"Failed to communicate with database stub: {str(e)}")

@app.get("/health")
async def health():
    return {"status": "healthy"}
