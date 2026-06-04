from unittest.mock import MagicMock, patch

# Ensure agent directory is in path for imports
from memory import IncidentMemory, extract_metric_vector


def test_extract_metric_vector():
    snapshot = {
        "p50_latency": 0.05,
        "p95_latency": 0.12,
        "p99_latency": 0.25,
        "request_rate": 100.0,
        "error_rate": 0.02,
        "cpu_usage": 0.65,
        "memory_usage": 0.8,
        "pod_restarts": 0.0,
    }
    vec = extract_metric_vector(snapshot)
    assert len(vec) == 8
    assert vec[0] == 0.05
    assert vec[4] == 0.02
    assert vec[5] == 0.65

    # Test fallback mapping
    snapshot_fallback = {
        "cpu": 0.75,
        "memory": 0.85,
    }
    vec_fallback = extract_metric_vector(snapshot_fallback)
    assert len(vec_fallback) == 8
    assert vec_fallback[5] == 0.75  # cpu mapping
    assert vec_fallback[6] == 0.85  # memory mapping
    assert vec_fallback[0] == 0.0  # p50 default


@patch("chromadb.PersistentClient")
def test_incident_memory_store(mock_client_class):
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_client_class.return_value = mock_client

    memory = IncidentMemory()
    assert memory.enabled is True

    # Test store
    metric_vector = [0.1] * 8
    memory.store(
        incident_id="inc-123",
        hypothesis="Memory Leak",
        action="restart",
        outcome="resolved",
        metric_vector=metric_vector,
    )

    mock_collection.add.assert_called_once()
    args, kwargs = mock_collection.add.call_args
    assert kwargs["ids"] == ["inc-123"]
    assert kwargs["embeddings"] == [metric_vector]
    assert kwargs["metadatas"][0]["incident_id"] == "inc-123"
    assert kwargs["metadatas"][0]["hypothesis"] == "Memory Leak"


@patch("chromadb.PersistentClient")
def test_incident_memory_retrieve_similar(mock_client_class):
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_client_class.return_value = mock_client

    # Mock collection.query result
    # We want: similarity score = 1.0 - dist. So if dist = 0.1, similarity = 0.9 (> 0.75, should keep)
    # If dist = 0.3, similarity = 0.7 (< 0.75, should filter out)
    mock_collection.count.return_value = 2
    mock_collection.query.return_value = {
        "ids": [["inc-1", "inc-2"]],
        "distances": [[0.1, 0.3]],
        "metadatas": [
            [
                {"incident_id": "inc-1", "hypothesis": "H1", "action": "A1", "outcome": "O1"},
                {"incident_id": "inc-2", "hypothesis": "H2", "action": "A2", "outcome": "O2"},
            ]
        ],
        "documents": [["H1", "H2"]],
    }

    memory = IncidentMemory()
    metric_vector = [0.1] * 8
    similar = memory.retrieve_similar(metric_vector, top_k=2)

    assert len(similar) == 1  # Only inc-1 has similarity score > 0.75 (0.9)
    assert similar[0]["incident_id"] == "inc-1"
    assert similar[0]["similarity_score"] == 0.9
