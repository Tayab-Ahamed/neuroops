import json
import os
import sqlite3
import tempfile
import threading
import time
from collections.abc import Callable
from typing import Any

import structlog

logger = structlog.get_logger()


class RemediationStore:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.getenv("REMEDIATOR_DB_PATH", "checkpoints/remediator.db")
        self._lock = threading.Lock()
        self._prepare_db_directory()
        try:
            self._ensure_schema()
        except sqlite3.Error as exc:
            fallback = os.path.join(tempfile.gettempdir(), "neuroops_remediator.db")
            logger.warning(
                "Falling back to temp remediation store",
                db_path=self.db_path,
                fallback=fallback,
                error=str(exc),
            )
            self.db_path = fallback
            self._prepare_db_directory()
            self._ensure_schema()

    def _prepare_db_directory(self) -> None:
        directory = os.path.dirname(self.db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        self._prepare_db_directory()
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _with_retry(self, operation: Callable[[], Any]) -> Any:
        attempts = 3
        for attempt in range(1, attempts + 1):
            try:
                return operation()
            except sqlite3.OperationalError as exc:
                if "database is locked" not in str(exc).lower() or attempt == attempts:
                    logger.error(
                        "SQLite operation failed",
                        db_path=self.db_path,
                        attempt=attempt,
                        error=str(exc),
                    )
                    raise
                logger.warning(
                    "SQLite database is locked; retrying operation",
                    db_path=self.db_path,
                    attempt=attempt,
                    error=str(exc),
                )
                time.sleep(0.1 * attempt)
        return None

    def _ensure_schema(self) -> None:
        with self._lock:

            def operation() -> None:
                with self._connect() as conn:
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("PRAGMA busy_timeout=30000")
                    conn.execute("""
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
                        """)
                    conn.commit()

            self._with_retry(operation)

    def record_action(
        self,
        *,
        incident_id: str,
        service: str,
        action_type: str,
        success: bool,
        action_taken: str,
        duration_seconds: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:

            def operation() -> None:
                with self._connect() as conn:
                    conn.execute("PRAGMA busy_timeout=30000")
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

            self._with_retry(operation)

    def list_actions(self, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        with self._lock:

            def operation() -> list[sqlite3.Row]:
                with self._connect() as conn:
                    conn.execute("PRAGMA busy_timeout=30000")
                    return conn.execute(
                        """
                        SELECT incident_id, service, action_type, success, action_taken,
                               duration_seconds, metadata_json, created_at
                        FROM remediation_actions
                        ORDER BY created_at DESC
                        LIMIT ? OFFSET ?
                        """,
                        (limit, offset),
                    ).fetchall()

            rows = self._with_retry(operation)
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

    def recent_success_timestamps(self, service: str, within_seconds: float) -> list[float]:
        cutoff = time.time() - within_seconds
        with self._lock:

            def operation() -> list[sqlite3.Row]:
                with self._connect() as conn:
                    conn.execute("PRAGMA busy_timeout=30000")
                    return conn.execute(
                        """
                        SELECT created_at
                        FROM remediation_actions
                        WHERE service = ? AND success = 1 AND created_at >= ?
                        ORDER BY created_at ASC
                        """,
                        (service, cutoff),
                    ).fetchall()

            rows = self._with_retry(operation)
        return [row["created_at"] for row in rows]

    def clear(self) -> None:
        with self._lock:

            def operation() -> None:
                with self._connect() as conn:
                    conn.execute("PRAGMA busy_timeout=30000")
                    conn.execute("DELETE FROM remediation_actions")
                    conn.commit()

            self._with_retry(operation)
