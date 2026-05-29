import json
import math
import os
import sqlite3
import threading
import time
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import structlog


logger = structlog.get_logger()


class IncidentStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("AGENT_DB_PATH", "checkpoints/agent_incidents.db")
        self._lock = threading.Lock()
        try:
            self._ensure_schema()
        except sqlite3.Error as exc:
            fallback = os.path.join(tempfile.gettempdir(), "neuroops_agent_incidents.db")
            logger.warning("Falling back to temp incident store", db_path=self.db_path, fallback=fallback, error=str(exc))
            self.db_path = fallback
            self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        directory = os.path.dirname(self.db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS incidents (
                        incident_id TEXT PRIMARY KEY,
                        service TEXT NOT NULL,
                        alert_id TEXT NOT NULL,
                        hypothesis TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        recommended_action TEXT NOT NULL,
                        requires_human_approval INTEGER NOT NULL,
                        reasoning TEXT NOT NULL,
                        tokens_used INTEGER NOT NULL,
                        remediation_result TEXT,
                        trace_json TEXT NOT NULL,
                        alert_timestamp REAL,
                        resolved_at REAL,
                        mttr_seconds REAL,
                        metric_snapshot_json TEXT,
                        created_at REAL NOT NULL
                    )
                    """
                )
                conn.commit()

    def save_incident(
        self,
        *,
        incident_id: str,
        service: str,
        alert_id: str,
        hypothesis: str,
        confidence: float,
        recommended_action: str,
        requires_human_approval: bool,
        reasoning: str,
        tokens_used: int,
        remediation_result: Optional[Dict[str, Any]],
        trace_timeline: List[Dict[str, Any]],
        alert_timestamp: Optional[float] = None,
        resolved_at: Optional[float] = None,
        mttr_seconds: Optional[float] = None,
        metric_snapshot: Optional[Dict[str, float]] = None,
    ) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO incidents (
                        incident_id, service, alert_id, hypothesis, confidence,
                        recommended_action, requires_human_approval, reasoning,
                        tokens_used, remediation_result, trace_json,
                        alert_timestamp, resolved_at, mttr_seconds,
                        metric_snapshot_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        incident_id,
                        service,
                        alert_id,
                        hypothesis,
                        confidence,
                        recommended_action,
                        1 if requires_human_approval else 0,
                        reasoning,
                        tokens_used,
                        json.dumps(remediation_result) if remediation_result is not None else None,
                        json.dumps(trace_timeline),
                        alert_timestamp,
                        resolved_at,
                        mttr_seconds,
                        json.dumps(metric_snapshot) if metric_snapshot else None,
                        time.time(),
                    ),
                )
                conn.commit()

    def get_trace(self, incident_id: str) -> Optional[List[Dict[str, Any]]]:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT trace_json FROM incidents WHERE incident_id = ?",
                    (incident_id,),
                ).fetchone()
        return json.loads(row["trace_json"]) if row else None

    def list_incidents(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT incident_id, service, alert_id, hypothesis, confidence,
                           recommended_action, requires_human_approval, reasoning,
                           tokens_used, remediation_result, created_at,
                           alert_timestamp, resolved_at, mttr_seconds
                    FROM incidents
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        incidents: List[Dict[str, Any]] = []
        for row in rows:
            incidents.append(
                {
                    "incident_id": row["incident_id"],
                    "service": row["service"],
                    "alert_id": row["alert_id"],
                    "hypothesis": row["hypothesis"],
                    "confidence": row["confidence"],
                    "recommended_action": row["recommended_action"],
                    "requires_human_approval": bool(row["requires_human_approval"]),
                    "reasoning": row["reasoning"],
                    "tokens_used": row["tokens_used"],
                    "remediation_result": json.loads(row["remediation_result"]) if row["remediation_result"] else None,
                    "created_at": row["created_at"],
                    "alert_timestamp": row["alert_timestamp"],
                    "resolved_at": row["resolved_at"],
                    "mttr_seconds": row["mttr_seconds"],
                }
            )
        return incidents

    # ── MTTR Analytics ────────────────────────────────────────────────────────

    def get_mttr_stats(self) -> Dict[str, Any]:
        """
        Computes p50, p95, p99 MTTR across all incidents that have mttr_seconds set.
        Also returns per-service breakdowns and global averages.
        """
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT service, mttr_seconds, confidence, tokens_used,
                           requires_human_approval, created_at
                    FROM incidents
                    WHERE mttr_seconds IS NOT NULL
                    ORDER BY created_at DESC
                    LIMIT 1000
                    """
                ).fetchall()

        if not rows:
            return {
                "total_incidents": 0,
                "p50_mttr_seconds": 0.0,
                "p95_mttr_seconds": 0.0,
                "p99_mttr_seconds": 0.0,
                "avg_mttr_seconds": 0.0,
                "autonomous_resolution_rate": 0.0,
                "per_service": {},
            }

        all_mttrs = sorted([row["mttr_seconds"] for row in rows])
        n = len(all_mttrs)

        def percentile(data: List[float], p: float) -> float:
            idx = max(0, math.ceil(p / 100.0 * len(data)) - 1)
            return data[idx]

        autonomous = sum(1 for r in rows if not bool(r["requires_human_approval"]))

        # Per-service breakdown
        service_mttrs: Dict[str, List[float]] = {}
        for row in rows:
            svc = row["service"]
            service_mttrs.setdefault(svc, []).append(row["mttr_seconds"])

        per_service = {}
        for svc, mttrs in service_mttrs.items():
            mttrs_sorted = sorted(mttrs)
            per_service[svc] = {
                "count": len(mttrs_sorted),
                "p50_mttr_seconds": percentile(mttrs_sorted, 50),
                "p95_mttr_seconds": percentile(mttrs_sorted, 95),
                "avg_mttr_seconds": sum(mttrs_sorted) / len(mttrs_sorted),
            }

        return {
            "total_incidents": n,
            "p50_mttr_seconds": percentile(all_mttrs, 50),
            "p95_mttr_seconds": percentile(all_mttrs, 95),
            "p99_mttr_seconds": percentile(all_mttrs, 99),
            "avg_mttr_seconds": sum(all_mttrs) / n,
            "autonomous_resolution_rate": autonomous / n if n > 0 else 0.0,
            "per_service": per_service,
        }

    def get_cost_stats(self) -> Dict[str, Any]:
        """
        Computes cumulative and per-incident LLM token usage and estimated costs.
        Based on Claude Sonnet pricing: $15.00 per 1M tokens.
        """
        TOKEN_COST_RATE = 15.0 / 1_000_000.0
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT tokens_used, created_at FROM incidents ORDER BY created_at DESC LIMIT 1000"
                ).fetchall()

        if not rows:
            return {
                "total_incidents": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "avg_tokens_per_incident": 0,
                "avg_cost_per_incident_usd": 0.0,
            }

        total_tokens = sum(r["tokens_used"] for r in rows)
        n = len(rows)
        return {
            "total_incidents": n,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_tokens * TOKEN_COST_RATE, 6),
            "avg_tokens_per_incident": total_tokens // n if n else 0,
            "avg_cost_per_incident_usd": round((total_tokens / n) * TOKEN_COST_RATE, 6) if n else 0.0,
            "token_cost_rate_per_million": 15.0,
        }

    def get_sla_status(self, sla_threshold_seconds: float = 300.0) -> Dict[str, Any]:
        """
        Checks how many incidents breached the SLA threshold (default 300s = 5 mins).
        Also calculates the autonomous resolution rate and whether the target of >= 70% is met.
        """
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT mttr_seconds, requires_human_approval
                    FROM incidents
                    WHERE mttr_seconds IS NOT NULL
                    ORDER BY created_at DESC
                    LIMIT 500
                    """
                ).fetchall()

        n = len(rows)
        if n == 0:
            return {
                "total_resolved": 0,
                "sla_breaches": 0,
                "sla_breach_rate": 0.0,
                "autonomous_resolution_rate": 0.0,
                "sla_threshold_seconds": sla_threshold_seconds,
                "target_met": False,
            }

        breaches = sum(1 for r in rows if r["mttr_seconds"] > sla_threshold_seconds)
        autonomous = sum(1 for r in rows if not bool(r["requires_human_approval"]))
        auto_rate = autonomous / n

        return {
            "total_resolved": n,
            "sla_breaches": breaches,
            "sla_breach_rate": breaches / n,
            "autonomous_resolution_rate": auto_rate,
            "sla_threshold_seconds": sla_threshold_seconds,
            "target_met": auto_rate >= 0.70,
        }

    # ── Incident Similarity Search ─────────────────────────────────────────────

    @staticmethod
    def _cosine_similarity(a: Dict[str, float], b: Dict[str, float]) -> float:
        """Computes cosine similarity between two metric snapshot dicts."""
        keys = set(a.keys()) | set(b.keys())
        if not keys:
            return 0.0
        dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
        mag_a = math.sqrt(sum(a.get(k, 0.0) ** 2 for k in keys))
        mag_b = math.sqrt(sum(b.get(k, 0.0) ** 2 for k in keys))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    def find_similar_incidents(
        self,
        metric_snapshot: Dict[str, float],
        exclude_incident_id: Optional[str] = None,
        top_k: int = 3,
    ) -> List[Tuple[float, Dict[str, Any]]]:
        """
        Finds the top-k most similar past incidents based on cosine similarity
        of their metric_snapshot feature vectors.

        Returns:
            List of (similarity_score, incident_dict) sorted descending by score.
        """
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT incident_id, service, hypothesis, confidence,
                           recommended_action, reasoning, requires_human_approval,
                           metric_snapshot_json, created_at
                    FROM incidents
                    WHERE metric_snapshot_json IS NOT NULL
                    ORDER BY created_at DESC
                    LIMIT 500
                    """
                ).fetchall()

        scored: List[Tuple[float, Dict[str, Any]]] = []
        for row in rows:
            if exclude_incident_id and row["incident_id"] == exclude_incident_id:
                continue
            try:
                snap = json.loads(row["metric_snapshot_json"])
                score = self._cosine_similarity(metric_snapshot, snap)
                scored.append((
                    score,
                    {
                        "incident_id": row["incident_id"],
                        "service": row["service"],
                        "hypothesis": row["hypothesis"],
                        "confidence": row["confidence"],
                        "recommended_action": row["recommended_action"],
                        "reasoning": row["reasoning"],
                        "requires_human_approval": bool(row["requires_human_approval"]),
                        "created_at": row["created_at"],
                        "similarity_score": round(score, 4),
                    },
                ))
            except Exception:
                continue

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]
