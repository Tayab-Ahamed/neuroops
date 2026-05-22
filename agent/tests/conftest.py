import sys
from unittest.mock import MagicMock

# Mock OTLPSpanExporter to prevent synchronous gRPC network timeouts during tests
mock_exporter_module = MagicMock()
mock_exporter_module.OTLPSpanExporter = MagicMock()

sys.modules["opentelemetry.exporter.otlp.proto.grpc.trace_exporter"] = mock_exporter_module
sys.modules["opentelemetry.exporter.otlp.proto.grpc"] = MagicMock()
sys.modules["opentelemetry.exporter.otlp"] = MagicMock()
