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
logger = logging.getLogger("frontend")

app = FastAPI(title="NeuroOps Frontend Service")

# Setup metrics
Instrumentator().instrument(app).expose(app)

# Setup tracing
service_name = os.getenv("OTEL_SERVICE_NAME", "frontend")
resource = Resource.create(attributes={"service.name": service_name})
provider = TracerProvider(resource=resource)
otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")

logger.info(f"Initializing frontend tracing with service name {service_name} exporting to {otlp_endpoint}")
exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
processor = BatchSpanProcessor(exporter)
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)
FastAPIInstrumentor.instrument_app(app)

tracer = trace.get_tracer(__name__)

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8081")

@app.get("/")
async def root():
    with tracer.start_as_current_span("frontend_root") as span:
        logger.info("Frontend: handling root request, calling backend...")
        # Inject tracing headers to propagate span downstream
        headers = {}
        inject(headers)
        
        async with httpx.AsyncClient() as client:
            try:
                backend_endpoint = f"{BACKEND_URL}/data"
                logger.info(f"Calling backend at {backend_endpoint} with injected headers: {headers}")
                response = await client.get(backend_endpoint, headers=headers, timeout=5.0)
                if response.status_code != 200:
                    logger.error(f"Backend returned status code {response.status_code}")
                    raise HTTPException(status_code=502, detail="Backend returned error status code")
                
                backend_data = response.json()
                return {
                    "message": "Hello from NeuroOps Frontend!",
                    "backend_response": backend_data
                }
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error calling backend: {str(e)}")
                span.record_exception(e)
                raise HTTPException(status_code=500, detail=f"Failed to communicate with backend: {str(e)}")

@app.get("/health")
async def health():
    return {"status": "healthy"}
