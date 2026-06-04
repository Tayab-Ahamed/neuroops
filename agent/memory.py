import os
import time
from typing import Any

import structlog

logger = structlog.get_logger()


def extract_metric_vector(metric_snapshot: dict[str, float]) -> list[float]:
    """
    Extracts the 8 Golden Signal values in a fixed order.
    1. p50_latency
    2. p95_latency
    3. p99_latency
    4. request_rate
    5. error_rate
    6. cpu_usage
    7. memory_usage
    8. pod_restarts
    """
    keys = [
        "p50_latency",
        "p95_latency",
        "p99_latency",
        "request_rate",
        "error_rate",
        "cpu_usage",
        "memory_usage",
        "pod_restarts",
    ]
    vec = []
    for k in keys:
        val = metric_snapshot.get(k)
        if val is None:
            if k == "cpu_usage":
                val = metric_snapshot.get("cpu", 0.0)
            elif k == "memory_usage":
                val = metric_snapshot.get("memory", 0.0)
            else:
                val = 0.0
        vec.append(float(val))
    return vec


class IncidentMemory:
    def __init__(self) -> None:
        self.enabled = os.getenv("MEMORY_ENABLED", "true").lower() == "true"
        self.db_path = os.getenv("MEMORY_DB_PATH", "./checkpoints/memory")
        self._collection = None

        if not self.enabled:
            logger.info("RAG Memory is disabled via MEMORY_ENABLED env var")
            return

        try:
            import chromadb

            self.client = chromadb.PersistentClient(path=self.db_path)
            # Use cosine space for similarity search
            self._collection = self.client.get_or_create_collection(
                name="incident_memory", metadata={"hnsw:space": "cosine"}
            )
            logger.info("Initialized ChromaDB persistent client", path=self.db_path)
        except Exception as exc:
            logger.error("Failed to initialize ChromaDB", error=str(exc))
            self.enabled = False

    def store(
        self,
        incident_id: str,
        hypothesis: str,
        action: str,
        outcome: str,
        metric_vector: list[float],
    ) -> None:
        if not self.enabled or self._collection is None:
            return

        try:
            timestamp = time.time()
            metadata = {
                "incident_id": incident_id,
                "hypothesis": hypothesis,
                "action": action,
                "outcome": outcome,
                "timestamp": timestamp,
            }
            self._collection.add(
                ids=[incident_id],
                embeddings=[metric_vector],
                metadatas=[metadata],
                documents=[hypothesis],
            )
            logger.info(
                "Stored incident in memory",
                incident_id=incident_id,
                action=action,
                outcome=outcome,
            )
        except Exception as exc:
            logger.error(
                "Failed to store incident in memory", incident_id=incident_id, error=str(exc)
            )

    def retrieve_similar(self, metric_vector: list[float], top_k: int = 3) -> list[dict[str, Any]]:
        if not self.enabled or self._collection is None:
            return []

        try:
            if self._collection.count() == 0:
                return []

            results = self._collection.query(
                query_embeddings=[metric_vector],
                n_results=top_k,
            )

            similar = []
            if not results or "ids" not in results or not results["ids"]:
                return []

            ids = results["ids"][0]
            distances = results.get("distances", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]

            for i in range(len(ids)):
                dist = distances[i] if i < len(distances) else 0.0
                meta = metadatas[i] if i < len(metadatas) else {}

                # cosine similarity score is 1 - distance in chroma hnsw:space cosine
                similarity_score = 1.0 - dist

                if similarity_score > 0.75:
                    similar.append(
                        {
                            "incident_id": meta.get("incident_id"),
                            "hypothesis": meta.get("hypothesis"),
                            "action": meta.get("action"),
                            "outcome": meta.get("outcome"),
                            "similarity_score": round(similarity_score, 4),
                        }
                    )

            similar.sort(key=lambda x: x["similarity_score"], reverse=True)
            return similar
        except Exception as exc:
            logger.error("Failed to retrieve similar incidents from memory", error=str(exc))
            return []
