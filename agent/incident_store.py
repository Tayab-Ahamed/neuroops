import json
import math
import os
import sqlite3
import tempfile
import threading
import time
from typing import Any

import structlog

logger = structlog.get_logger()


class IncidentStore:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.getenv("AGENT_DB_PATH", "checkpoints/agent_incidents.db")
        self._lock = threading.Lock()
        try:
            self._ensure_schema()
        except sqlite3.Error as exc:
            fallback = os.path.join(tempfile.gettempdir(), "neuroops_agent_incidents.db")
            logger.warning(
                "Falling back to temp incident store",
                db_path=self.db_path,
                fallback=fallback,
                error=str(exc),
            )
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
                conn.execute("""
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
                        model_used TEXT,
                        created_at REAL NOT NULL
                    )
                    """)
                try:
                    conn.execute("ALTER TABLE incidents ADD COLUMN model_used TEXT")
                except sqlite3.OperationalError:
                    pass
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
        remediation_result: dict[str, Any] | None,
        trace_timeline: list[dict[str, Any]],
        alert_timestamp: float | None = None,
        resolved_at: float | None = None,
        mttr_seconds: float | None = None,
        metric_snapshot: dict[str, float] | None = None,
        model_used: str | None = None,
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
                        metric_snapshot_json, model_used, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        model_used,
                        time.time(),
                    ),
                )
                conn.commit()

    def get_trace(self, incident_id: str) -> list[dict[str, Any]] | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT trace_json FROM incidents WHERE incident_id = ?",
                    (incident_id,),
                ).fetchone()
        return json.loads(row["trace_json"]) if row else None

    def list_incidents(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT incident_id, service, alert_id, hypothesis, confidence,
                           recommended_action, requires_human_approval, reasoning,
                           tokens_used, remediation_result, created_at,
                           alert_timestamp, resolved_at, mttr_seconds, model_used
                    FROM incidents
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        incidents: list[dict[str, Any]] = []
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
                    "remediation_result": (
                        json.loads(row["remediation_result"]) if row["remediation_result"] else None
                    ),
                    "created_at": row["created_at"],
                    "alert_timestamp": row["alert_timestamp"],
                    "resolved_at": row["resolved_at"],
                    "mttr_seconds": row["mttr_seconds"],
                    "model_used": row["model_used"],
                }
            )
        return incidents

    # ── MTTR Analytics ────────────────────────────────────────────────────────

    def get_mttr_stats(self) -> dict[str, Any]:
        """
        Computes p50, p95, p99 MTTR across all incidents that have mttr_seconds set.
        Also returns per-service breakdowns and global averages.
        """
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute("""
                    SELECT service, mttr_seconds, confidence, tokens_used,
                           requires_human_approval, created_at
                    FROM incidents
                    WHERE mttr_seconds IS NOT NULL
                    ORDER BY created_at DESC
                    LIMIT 1000
                    """).fetchall()

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

        def percentile(data: list[float], p: float) -> float:
            idx = max(0, math.ceil(p / 100.0 * len(data)) - 1)
            return data[idx]

        autonomous = sum(1 for r in rows if not bool(r["requires_human_approval"]))

        # Per-service breakdown
        service_mttrs: dict[str, list[float]] = {}
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

    def get_cost_stats(self) -> dict[str, Any]:
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
            "avg_cost_per_incident_usd": (
                round((total_tokens / n) * TOKEN_COST_RATE, 6) if n else 0.0
            ),
            "token_cost_rate_per_million": 15.0,
        }

    def get_detailed_cost_stats(self) -> dict[str, Any]:
        """
        Computes detailed token costs using dynamic model routing rates.
        Haiku: $0.00025 / 1k input, $0.00125 / 1k output
        Sonnet: $0.003 / 1k input, $0.015 / 1k output
        Assumes standard split: 80% input tokens, 20% output tokens.
        """
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT model_used, tokens_used FROM incidents WHERE tokens_used IS NOT NULL"
                ).fetchall()

        total_tokens = 0
        total_cost_usd = 0.0

        haiku_calls = 0
        haiku_tokens = 0
        haiku_cost = 0.0

        sonnet_calls = 0
        sonnet_tokens = 0
        sonnet_cost = 0.0

        for row in rows:
            model = row["model_used"] or "claude-sonnet-4-6"
            tokens = row["tokens_used"]

            total_tokens += tokens
            input_tokens = tokens * 0.8
            output_tokens = tokens * 0.2

            if "haiku" in model.lower():
                haiku_calls += 1
                haiku_tokens += tokens
                cost = (input_tokens * 0.00025 / 1000.0) + (output_tokens * 0.00125 / 1000.0)
                haiku_cost += cost
                total_cost_usd += cost
            else:
                sonnet_calls += 1
                sonnet_tokens += tokens
                cost = (input_tokens * 0.003 / 1000.0) + (output_tokens * 0.015 / 1000.0)
                sonnet_cost += cost
                total_cost_usd += cost

        # Savings if all had used Sonnet:
        # Sonnet rate = tokens * (0.8 * 0.003 + 0.2 * 0.015) / 1000.0 = tokens * 0.0000054
        cost_if_all_sonnet = total_tokens * 0.0000054
        savings = cost_if_all_sonnet - total_cost_usd

        return {
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost_usd, 6),
            "model_breakdown": {
                "haiku": {
                    "calls": haiku_calls,
                    "tokens": haiku_tokens,
                    "cost_usd": round(haiku_cost, 6),
                },
                "sonnet": {
                    "calls": sonnet_calls,
                    "tokens": sonnet_tokens,
                    "cost_usd": round(sonnet_cost, 6),
                },
            },
            "estimated_savings_vs_sonnet_only_usd": round(max(0.0, savings), 6),
        }

    def get_sla_status(self, sla_threshold_seconds: float = 300.0) -> dict[str, Any]:
        """
        Checks how many incidents breached the SLA threshold (default 300s = 5 mins).
        Also calculates the autonomous resolution rate and whether the target of >= 70% is met.
        """
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute("""
                    SELECT mttr_seconds, requires_human_approval
                    FROM incidents
                    WHERE mttr_seconds IS NOT NULL
                    ORDER BY created_at DESC
                    LIMIT 500
                    """).fetchall()

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
    def _cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
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
        metric_snapshot: dict[str, float],
        exclude_incident_id: str | None = None,
        top_k: int = 3,
    ) -> list[tuple[float, dict[str, Any]]]:
        """
        Finds the top-k most similar past incidents based on cosine similarity
        of their metric_snapshot feature vectors.

        Returns:
            List of (similarity_score, incident_dict) sorted descending by score.
        """
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute("""
                    SELECT incident_id, service, hypothesis, confidence,
                           recommended_action, reasoning, requires_human_approval,
                           metric_snapshot_json, created_at
                    FROM incidents
                    WHERE metric_snapshot_json IS NOT NULL
                    ORDER BY created_at DESC
                    LIMIT 500
                    """).fetchall()

        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            if exclude_incident_id and row["incident_id"] == exclude_incident_id:
                continue
            try:
                snap = json.loads(row["metric_snapshot_json"])
                score = self._cosine_similarity(metric_snapshot, snap)
                scored.append(
                    (
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
                    )
                )
            except Exception:
                continue

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        """Retrieves the full details of a single incident, including parsed trace and metric snapshot."""
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM incidents WHERE incident_id = ?",
                    (incident_id,),
                ).fetchone()
        if not row:
            return None
        return {
            "incident_id": row["incident_id"],
            "service": row["service"],
            "alert_id": row["alert_id"],
            "hypothesis": row["hypothesis"],
            "confidence": row["confidence"],
            "recommended_action": row["recommended_action"],
            "requires_human_approval": bool(row["requires_human_approval"]),
            "reasoning": row["reasoning"],
            "tokens_used": row["tokens_used"],
            "remediation_result": (
                json.loads(row["remediation_result"]) if row["remediation_result"] else None
            ),
            "trace": json.loads(row["trace_json"]) if row["trace_json"] else [],
            "created_at": row["created_at"],
            "alert_timestamp": row["alert_timestamp"],
            "resolved_at": row["resolved_at"],
            "mttr_seconds": row["mttr_seconds"],
            "metric_snapshot": (
                json.loads(row["metric_snapshot_json"]) if row["metric_snapshot_json"] else None
            ),
            "model_used": row["model_used"],
        }

    def get_mttr_analytics(self) -> dict[str, Any]:
        """
        Group all resolved incidents by chaos scenario (parsing IDs and hypotheses)
        and calculate speedups vs baseline constants.
        """
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT incident_id, hypothesis, mttr_seconds FROM incidents WHERE mttr_seconds IS NOT NULL"
                ).fetchall()

        if not rows:
            return {
                "per_scenario": [],
                "overall_avg_mttr_seconds": 0.0,
                "p50_mttr_seconds": 0.0,
                "p95_mttr_seconds": 0.0,
                "total_incidents": 0,
            }

        baseline_constants = {
            "pod-delete": 300.0,
            "cpu-hog": 600.0,
            "memory-hog": 900.0,
            "network-latency": 1200.0,
            "disk-fill": 1800.0,
        }

        def get_scenario(inc_id: str, hyp: str) -> str:
            # First try parsing from incident_id (inc-{scenario}-{run})
            parts = inc_id.split("-")
            if len(parts) >= 3 and parts[0] == "inc":
                sc = parts[1]
                if sc in baseline_constants:
                    return sc
            h_lower = hyp.lower()
            for sc in baseline_constants:
                if sc in h_lower:
                    return sc
            # Look for friendly patterns in hypothesis
            if "pod delete" in h_lower or "delete pod" in h_lower:
                return "pod-delete"
            if "cpu" in h_lower or "cpu-hog" in h_lower:
                return "cpu-hog"
            if "memory" in h_lower or "memory-hog" in h_lower:
                return "memory-hog"
            if "network" in h_lower or "latency" in h_lower:
                return "network-latency"
            if "disk" in h_lower or "fill" in h_lower:
                return "disk-fill"
            return "unknown"

        scenarios_data = {}
        all_mttr = []

        for row in rows:
            inc_id = row["incident_id"]
            hyp = row["hypothesis"]
            mttr = row["mttr_seconds"]
            all_mttr.append(mttr)

            sc = get_scenario(inc_id, hyp)
            if sc not in scenarios_data:
                scenarios_data[sc] = []
            scenarios_data[sc].append(mttr)

        per_scenario = []
        for sc, mttrs in scenarios_data.items():
            if sc == "unknown":
                continue
            avg_agent = sum(mttrs) / len(mttrs)
            baseline = baseline_constants.get(sc, 600.0)
            speedup = baseline / avg_agent if avg_agent > 0 else 1.0
            per_scenario.append(
                {
                    "scenario": sc,
                    "avg_agent_mttr_seconds": round(avg_agent, 2),
                    "run_count": len(mttrs),
                    "baseline_mttr_seconds": baseline,
                    "speedup": round(speedup, 2),
                }
            )

        def percentile(data: list[float], p: float) -> float:
            if not data:
                return 0.0
            sorted_data = sorted(data)
            index = (len(sorted_data) - 1) * p
            lower = math.floor(index)
            upper = math.ceil(index)
            if lower == upper:
                return sorted_data[lower]
            return sorted_data[lower] * (upper - index) + sorted_data[upper] * (index - lower)

        overall_avg = sum(all_mttr) / len(all_mttr)

        return {
            "per_scenario": per_scenario,
            "overall_avg_mttr_seconds": round(overall_avg, 2),
            "p50_mttr_seconds": round(percentile(all_mttr, 0.5), 2),
            "p95_mttr_seconds": round(percentile(all_mttr, 0.95), 2),
            "total_incidents": len(all_mttr),
        }

    def get_cost_analytics(self) -> dict[str, Any]:
        """
        Query IncidentStore for model_used and tokens_used, calculating costs and savings.
        Cost rates:
          haiku - $0.00025/1k input, $0.00125/1k output
          sonnet - $0.003/1k input, $0.015/1k output
        Assumes standard split: 80% input tokens, 20% output tokens.
        """
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT model_used, tokens_used FROM incidents WHERE tokens_used IS NOT NULL"
                ).fetchall()

        if not rows:
            return {
                "total_cost_usd": 0.0,
                "total_tokens": 0,
                "incidents_counted": 0,
                "model_breakdown": {
                    "haiku": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
                    "sonnet": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
                },
                "savings_vs_all_sonnet_usd": 0.0,
                "no_data": True,
            }

        total_tokens = 0
        total_cost_usd = 0.0

        haiku_calls = 0
        haiku_input = 0
        haiku_output = 0
        haiku_cost = 0.0

        sonnet_calls = 0
        sonnet_input = 0
        sonnet_output = 0
        sonnet_cost = 0.0

        for row in rows:
            model = row["model_used"] or "claude-sonnet-4-6"
            tokens = row["tokens_used"]
            total_tokens += tokens

            input_tokens = tokens * 0.8
            output_tokens = tokens * 0.2

            if "haiku" in model.lower():
                haiku_calls += 1
                haiku_input += input_tokens
                haiku_output += output_tokens
                cost = (input_tokens * 0.00025 / 1000.0) + (output_tokens * 0.00125 / 1000.0)
                haiku_cost += cost
                total_cost_usd += cost
            else:
                sonnet_calls += 1
                sonnet_input += input_tokens
                sonnet_output += output_tokens
                cost = (input_tokens * 0.003 / 1000.0) + (output_tokens * 0.015 / 1000.0)
                sonnet_cost += cost
                total_cost_usd += cost

        # Savings if all had used Sonnet:
        cost_if_all_sonnet = ((haiku_input + sonnet_input) * 0.003 / 1000.0) + (
            (haiku_output + sonnet_output) * 0.015 / 1000.0
        )
        savings = cost_if_all_sonnet - total_cost_usd

        return {
            "total_cost_usd": round(total_cost_usd, 6),
            "total_tokens": total_tokens,
            "incidents_counted": len(rows),
            "model_breakdown": {
                "haiku": {
                    "calls": haiku_calls,
                    "input_tokens": int(haiku_input),
                    "output_tokens": int(haiku_output),
                    "cost_usd": round(haiku_cost, 6),
                },
                "sonnet": {
                    "calls": sonnet_calls,
                    "input_tokens": int(sonnet_input),
                    "output_tokens": int(sonnet_output),
                    "cost_usd": round(sonnet_cost, 6),
                },
            },
            "savings_vs_all_sonnet_usd": round(max(0.0, savings), 6),
        }

    def get_resolution_analytics(self) -> dict[str, Any]:
        """
        Group incidents by calendar day for the last 7 days.
        """
        import datetime

        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT requires_human_approval, created_at FROM incidents"
                ).fetchall()

        # Generate last 7 days (oldest first)
        today = datetime.date.today()
        dates_list = [today - datetime.timedelta(days=i) for i in range(6, -1, -1)]

        daily_map = {d: {"total": 0, "auto": 0, "human": 0} for d in dates_list}

        for row in rows:
            created_time = row["created_at"]
            try:
                inc_date = datetime.datetime.fromtimestamp(created_time).date()
                if inc_date in daily_map:
                    daily_map[inc_date]["total"] += 1
                    if row["requires_human_approval"]:
                        daily_map[inc_date]["human"] += 1
                    else:
                        daily_map[inc_date]["auto"] += 1
            except Exception:
                continue

        daily_results = []
        total_autonomous = 0
        total_incidents = 0
        days_with_data = 0

        for d in dates_list:
            stats = daily_map[d]
            rate = (stats["auto"] / stats["total"] * 100.0) if stats["total"] > 0 else 0.0
            day_label = d.strftime("%a")

            daily_results.append(
                {
                    "date": day_label,
                    "total_incidents": stats["total"],
                    "autonomous": stats["auto"],
                    "human_approved": stats["human"],
                    "rate_pct": round(rate, 1),
                }
            )

            total_autonomous += stats["auto"]
            total_incidents += stats["total"]
            if stats["total"] > 0:
                days_with_data += 1

        overall_rate = (total_autonomous / total_incidents * 100.0) if total_incidents > 0 else 0.0

        return {
            "daily": daily_results,
            "overall_rate_pct": round(overall_rate, 1),
            "target_pct": 70,
            "days_with_data": days_with_data,
        }
