import json
import os
import sqlite3
import threading
import time
import tempfile
from typing import Any, Dict, List, Optional


class RemediationStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("REMEDIATOR_DB_PATH", "checkpoints/remediator.db")
        self._lock = threading.Lock()
        try:
            self._ensure_schema()
        except sqlite3.Error:
            self.db_path = os.path.join(tempfile.gettempdir(), "neuroops_remediator.db")
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
                    CREATE TABLE IF NOT EXISTS remediation_actions (
                        incident_id TEXT NOT NULL,
                        service TEXT NOT NULL,
                        action_type TEXT NOT NULL,
                        success INTEGER NOT NULL,
                        action_taken TEXT NOT NULL,
                        duration_seconds REAL NOT NULL,
                        metadata_json TEXT,
                        created_at REAL NOT NULL
                    )
                    """
                )
                conn.commit()

    def record_action(
        self,
        *,
        incident_id: str,
        service: str,
        action_type: str,
        success: bool,
        action_taken: str,
        duration_seconds: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO remediation_actions (
                        incident_id, service, action_type, success, action_taken,
                        duration_seconds, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        incident_id,
                        service,
                        action_type,
                        1 if success else 0,
                        action_taken,
                        duration_seconds,
                        json.dumps(metadata) if metadata else None,
                        time.time(),
                    ),
                )
                conn.commit()

    def list_actions(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT incident_id, service, action_type, success, action_taken,
                           duration_seconds, metadata_json, created_at
                    FROM remediation_actions
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [
            {
                "incident_id": row["incident_id"],
                "service": row["service"],
                "action_type": row["action_type"],
                "success": bool(row["success"]),
                "action_taken": row["action_taken"],
                "duration_seconds": row["duration_seconds"],
                "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else None,
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def recent_success_timestamps(self, service: str, within_seconds: float) -> List[float]:
        cutoff = time.time() - within_seconds
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT created_at
                    FROM remediation_actions
                    WHERE service = ? AND success = 1 AND created_at >= ?
                    ORDER BY created_at ASC
                    """,
                    (service, cutoff),
                ).fetchall()
        return [row["created_at"] for row in rows]

    def clear(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM remediation_actions")
                conn.commit()
