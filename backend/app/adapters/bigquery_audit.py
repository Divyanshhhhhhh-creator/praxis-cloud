"""BigQuery immutable audit sink (asia-south1) — POL-RBI-AUDIT-5Y.

Every persisted `AuditDecision` is mirrored to `praxis_audit.audit_decisions` via non-blocking streaming
inserts. The payment path NEVER waits on BigQuery and NEVER fails because of it: missing permissions,
quota or network errors are logged and counted, while the primary store (SQLite / Firestore) remains the
system of record for the proxy. The table is day-partitioned on `created_at` with no expiration so the
5-year RBI retention requirement is met; grant the runtime identity append-only access (dataEditor on the
dataset, no delete) to keep it immutable in practice.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from ..domain.models import AuditDecision

log = logging.getLogger("praxis.bigquery_audit")

SCHEMA: list[tuple[str, str, str]] = [
    ("audit_id", "STRING", "REQUIRED"),
    ("created_at", "TIMESTAMP", "REQUIRED"),
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("idempotency_key", "STRING", "NULLABLE"),
    ("agent_id", "STRING", "NULLABLE"),
    ("policy_id", "STRING", "NULLABLE"),
    ("tool_name", "STRING", "NULLABLE"),
    ("merchant_id", "STRING", "NULLABLE"),
    ("amount_inr", "FLOAT", "NULLABLE"),
    ("verdict", "STRING", "NULLABLE"),
    ("layer_decided", "STRING", "NULLABLE"),
    ("risk_score", "FLOAT", "NULLABLE"),
    ("reason", "STRING", "NULLABLE"),
    ("policy_citations", "STRING", "REPEATED"),
    ("payload_sha256", "STRING", "NULLABLE"),
    ("l1_latency_ms", "FLOAT", "NULLABLE"),
    ("l2_latency_ms", "FLOAT", "NULLABLE"),
    ("executed", "BOOLEAN", "NULLABLE"),
    ("settlement_txn_id", "STRING", "NULLABLE"),
    ("settlement_rail", "STRING", "NULLABLE"),
    ("approval_id", "STRING", "NULLABLE"),
    ("threat_category", "STRING", "NULLABLE"),
    ("invoice_extracted_total_inr", "FLOAT", "NULLABLE"),
    ("model_used", "STRING", "NULLABLE"),
]


def decision_to_row(d: AuditDecision) -> dict[str, Any]:
    row = d.model_dump()
    row["ingested_at"] = datetime.now(timezone.utc).isoformat()
    return {name: row.get(name) for name, _, _ in SCHEMA}


class BigQueryAuditSink:
    def __init__(
        self,
        *,
        project: Optional[str],
        dataset: str = "praxis_audit",
        table: str = "audit_decisions",
        location: str = "asia-south1",
        client: Any = None,
    ):
        self.project = project or None
        self.dataset = dataset
        self.table = table
        self.location = location
        self._client = client
        self.enabled = False
        self.written = 0
        self.failures = 0
        self.last_error: Optional[str] = None
        self._tasks: set[asyncio.Task] = set()

    @property
    def table_id(self) -> str:
        project = self.project or getattr(self._client, "project", None) or "_"
        return f"{project}.{self.dataset}.{self.table}"

    def _ensure_table_sync(self) -> None:
        from google.cloud import bigquery

        if self._client is None:
            self._client = bigquery.Client(project=self.project, location=self.location)
        ds = bigquery.Dataset(f"{self._client.project}.{self.dataset}")
        ds.location = self.location
        self._client.create_dataset(ds, exists_ok=True)
        table = bigquery.Table(self.table_id, schema=[bigquery.SchemaField(n, t, mode=m) for n, t, m in SCHEMA])
        table.time_partitioning = bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.DAY, field="created_at")
        table.description = "Praxis immutable AI-agent payment decisions (POL-RBI-AUDIT-5Y, RBI/DPSS/2026-27/475)."
        self._client.create_table(table, exists_ok=True)

    async def start(self) -> None:
        """Create dataset/table if absent. Any failure disables the sink without affecting payments."""
        try:
            await asyncio.to_thread(self._ensure_table_sync)
            self.enabled = True
            log.info("BigQuery audit sink ready: %s (%s)", self.table_id, self.location)
        except Exception as exc:
            self.enabled = False
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.warning("BigQuery audit sink disabled (%s); payments continue on the primary store.", self.last_error)

    def submit(self, decision: AuditDecision) -> None:
        """Fire-and-forget: schedule the streaming insert and return immediately."""
        if not self.enabled:
            return
        task = asyncio.create_task(self._insert(decision_to_row(decision)))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _insert(self, row: dict[str, Any]) -> None:
        row_id = f"{row['audit_id']}:{row['layer_decided']}:{row['executed']}"
        try:
            errors = await asyncio.to_thread(self._client.insert_rows_json, self.table_id, [row], row_ids=[row_id])
            if errors:
                raise RuntimeError(str(errors)[:300])
            self.written += 1
        except Exception as exc:
            self.failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.warning("BigQuery audit insert failed (payment path unaffected): %s", self.last_error)

    async def drain(self, timeout_s: float = 5.0) -> None:
        if self._tasks:
            await asyncio.wait(list(self._tasks), timeout=timeout_s)

    def status(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "table": self.table_id, "written": self.written, "failures": self.failures,
                "last_error": self.last_error}


class AuditMirroringStorage:
    """Wraps any StorageRepository: identical behaviour, plus a non-blocking BigQuery copy of every audit."""

    def __init__(self, inner: Any, sink: BigQueryAuditSink):
        self._inner = inner
        self.sink = sink

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def save_audit(self, decision: AuditDecision) -> None:
        await self._inner.save_audit(decision)  # system of record first
        self.sink.submit(decision)  # then mirror, never awaited on the payment path

    def close(self) -> None:
        self._inner.close()
