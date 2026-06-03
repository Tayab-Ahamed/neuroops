import sys
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Pre-import stubs: inserted before any project module is collected.
# ---------------------------------------------------------------------------

# Mock OTLPSpanExporter to prevent synchronous gRPC network timeouts during tests.
mock_exporter_module = MagicMock()
mock_exporter_module.OTLPSpanExporter = MagicMock()
sys.modules["opentelemetry.exporter.otlp.proto.grpc.trace_exporter"] = mock_exporter_module
sys.modules["opentelemetry.exporter.otlp.proto.grpc"] = MagicMock()
sys.modules["opentelemetry.exporter.otlp"] = MagicMock()

# langchain-core 1.4.x unconditionally imports transformers.GPT2TokenizerFast
# during module load, which triggers a recursive directory scan of the entire
# Hugging Face models tree — hanging for minutes on first import.
# Stub the entire transformers namespace so the import resolves instantly.
_transformers_stub = MagicMock()
_transformers_stub.GPT2TokenizerFast = MagicMock()
sys.modules["transformers"] = _transformers_stub
sys.modules["transformers.utils"] = MagicMock()
sys.modules["transformers.utils.import_utils"] = MagicMock()
