"""Storage port + SQLite adapter.

`StorageRepository` is the port the services depend on; `SQLiteRepository` is the local
adapter. A Firestore adapter (Slice 6) implements the same interface, using Firestore
transactions where SQLite uses `BEGIN IMMEDIATE`.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..domain.hashing import inr_to_paise
from ..domain.models import AuditDecision, MetricsSummary, PolicyConfig, WindowUsage
from ..domain.policy_catalog import (
    DEFAULT_POLICY_ID,
    POL_SLIDING_CAP,
    POL_VELOCITY,
    default_policy,
)

ACTIVE_STATUSES = ("RESERVED", "COMMITTED")


@dataclass
class BudgetViolation:
    code: str
    reason: str


@dataclass
class ReservationOutcome:
    ok: bool
    reservation_id: Optional[str]
    violations: list[BudgetViolation] = field(default_factory=list)
    usage_before: Optional[WindowUsage] = None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StorageRepository(ABC):
    """Persistence port for the proxy. All methods are async so cloud adapters plug in cleanly."""

    # Policies
    @abstractmethod
    async def get_policy(self, policy_id: str) -> Optional[PolicyConfig]: ...
    @abstractmethod
    async def list_policies(self) -> list[PolicyConfig]: ...
    @abstractmethod
    async def upsert_policy(self, policy: PolicyConfig) -> PolicyConfig: ...

    # Idempotency
    @abstractmethod
    async def get_idempotent_decision(self, idempotency_key: str) -> Optional[AuditDecision]: ...
    @abstractmethod
    async def save_idempotent_decision(self, idempotency_key: str, decision: AuditDecision) -> AuditDecision: ...

    # Atomic budget ledger
    @abstractmethod
    async def reserve_budget_atomic(
        self, agent_id: str, policy: PolicyConfig, amount_inr: float, *, enforce: bool = True
    ) -> ReservationOutcome: ...
    @abstractmethod
    async def commit_budget_atomic(self, reservation_id: str) -> bool: ...
    @abstractmethod
    async def release_budget_atomic(self, reservation_id: str) -> bool: ...
    @abstractmethod
    async def reset_demo_windows(self, agent_id: Optional[str] = None) -> int: ...
    @abstractmethod
    async def reset_demo_data(self, agent_id: Optional[str] = None) -> dict[str, int]: ...

    # Audit log
    @abstractmethod
    async def save_audit(self, decision: AuditDecision) -> None: ...
    @abstractmethod
    async def get_audit(self, audit_id: str) -> Optional[AuditDecision]: ...
    @abstractmethod
    async def list_audits(self, limit: int = 100, agent_id: Optional[str] = None) -> list[AuditDecision]: ...

    # HITL (Slice 3)
    @abstractmethod
    async def create_pending_approval(
        self,
        *,
        audit_id: str,
        reservation_id: Optional[str],
        canonical_payload_json: str,
        payload_sha256: str,
        request_json: str,
    ) -> str: ...
    @abstractmethod
    async def list_pending_approvals(self, status: str = "PENDING") -> list[dict]: ...

    # Metrics
    @abstractmethod
    async def get_metrics(self, agent_id: Optional[str] = None, policy_id: Optional[str] = None) -> MetricsSummary: ...

    def close(self) -> None:  # pragma: no cover - optional
        pass


_SCHEMA = """
CREATE TABLE IF NOT EXISTS policies (
    policy_id   TEXT PRIMARY KEY,
    config_json TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS budget_ledger (
    reservation_id TEXT PRIMARY KEY,
    agent_id       TEXT NOT NULL,
    policy_id      TEXT NOT NULL,
    amount_paise   INTEGER NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('RESERVED','COMMITTED','RELEASED')),
    created_ts     REAL NOT NULL,
    updated_ts     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ledger_window ON budget_ledger (agent_id, policy_id, created_ts);
CREATE TABLE IF NOT EXISTS idempotency (
    idempotency_key TEXT PRIMARY KEY,
    audit_id        TEXT NOT NULL,
    decision_json   TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_logs (
    audit_id        TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    policy_id       TEXT NOT NULL,
    tool_name       TEXT NOT NULL,
    merchant_id     TEXT NOT NULL,
    amount_inr      REAL NOT NULL,
    verdict         TEXT NOT NULL,
    layer_decided   TEXT NOT NULL,
    executed        INTEGER NOT NULL,
    l1_latency_ms   REAL NOT NULL,
    l2_latency_ms   REAL NOT NULL,
    created_at      TEXT NOT NULL,
    decision_json   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_created ON audit_logs (created_at);
CREATE INDEX IF NOT EXISTS ix_audit_agent ON audit_logs (agent_id, policy_id);
CREATE TABLE IF NOT EXISTS hitl_approvals (
    approval_id            TEXT PRIMARY KEY,
    audit_id               TEXT NOT NULL,
    reservation_id         TEXT,
    canonical_payload_json TEXT NOT NULL,
    payload_sha256         TEXT NOT NULL,
    status                 TEXT NOT NULL,
    request_json           TEXT NOT NULL,
    created_at             TEXT NOT NULL
);
"""


class SQLiteRepository(StorageRepository):
    """SQLite adapter (WAL, busy_timeout=5000).

    Every ledger mutation runs inside `BEGIN IMMEDIATE` (RESERVED write lock acquired up
    front, so the read-check-insert cannot interleave with another writer) AND under a
    process-wide `threading.Lock`, so concurrent asyncio requests dispatched to worker
    threads are strictly serialized.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            self.db_path, isolation_level=None, check_same_thread=False, timeout=5.0
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(_SCHEMA)
            self._seed_default_policy()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ helpers
    def _seed_default_policy(self) -> None:
        p = default_policy()
        self._conn.execute(
            "INSERT OR IGNORE INTO policies (policy_id, config_json, updated_at) VALUES (?, ?, ?)",
            (p.policy_id, p.model_dump_json(), _utcnow_iso()),
        )

    def _write_txn(self, fn):
        """Run `fn(conn)` inside BEGIN IMMEDIATE under the process lock."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                result = fn(self._conn)
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")
            return result

    def _read(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    @staticmethod
    def _window_usage(conn: sqlite3.Connection, agent_id: Optional[str], policy: PolicyConfig, now: float) -> WindowUsage:
        sql = (
            "SELECT "
            " COALESCE(SUM(CASE WHEN created_ts > ? THEN amount_paise END), 0) AS p1m,"
            " COALESCE(SUM(CASE WHEN created_ts > ? THEN amount_paise END), 0) AS p1h,"
            " COALESCE(SUM(amount_paise), 0) AS p24h,"
            " COALESCE(SUM(CASE WHEN created_ts > ? THEN 1 ELSE 0 END), 0) AS c1m "
            "FROM budget_ledger WHERE policy_id = ? AND status IN ('RESERVED','COMMITTED') AND created_ts > ?"
        )
        params: list = [now - 60, now - 3600, now - 60, policy.policy_id, now - 86400]
        if agent_id is not None:
            sql += " AND agent_id = ?"
            params.append(agent_id)
        row = conn.execute(sql, tuple(params)).fetchone()
        return WindowUsage(
            used_1m_inr=row["p1m"] / 100,
            limit_1m_inr=policy.window_1m_inr,
            used_1h_inr=row["p1h"] / 100,
            limit_1h_inr=policy.window_1h_inr,
            used_24h_inr=row["p24h"] / 100,
            limit_24h_inr=policy.window_24h_inr,
            calls_1m=int(row["c1m"]),
            limit_calls_1m=policy.max_calls_per_min,
        )

    # ------------------------------------------------------------------ policies
    async def get_policy(self, policy_id: str) -> Optional[PolicyConfig]:
        rows = await asyncio.to_thread(self._read, "SELECT config_json FROM policies WHERE policy_id = ?", (policy_id,))
        return PolicyConfig.model_validate_json(rows[0]["config_json"]) if rows else None

    async def list_policies(self) -> list[PolicyConfig]:
        rows = await asyncio.to_thread(self._read, "SELECT config_json FROM policies ORDER BY policy_id")
        return [PolicyConfig.model_validate_json(r["config_json"]) for r in rows]

    async def upsert_policy(self, policy: PolicyConfig) -> PolicyConfig:
        def _fn(conn):
            conn.execute(
                "INSERT INTO policies (policy_id, config_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(policy_id) DO UPDATE SET config_json = excluded.config_json, updated_at = excluded.updated_at",
                (policy.policy_id, policy.model_dump_json(), _utcnow_iso()),
            )
            return policy

        return await asyncio.to_thread(self._write_txn, _fn)

    # ------------------------------------------------------------------ idempotency
    async def get_idempotent_decision(self, idempotency_key: str) -> Optional[AuditDecision]:
        rows = await asyncio.to_thread(
            self._read, "SELECT decision_json FROM idempotency WHERE idempotency_key = ?", (idempotency_key,)
        )
        return AuditDecision.model_validate_json(rows[0]["decision_json"]) if rows else None

    async def save_idempotent_decision(self, idempotency_key: str, decision: AuditDecision) -> AuditDecision:
        """First writer wins; returns the decision that is actually stored for the key."""

        def _fn(conn):
            conn.execute(
                "INSERT OR IGNORE INTO idempotency (idempotency_key, audit_id, decision_json, created_at) VALUES (?, ?, ?, ?)",
                (idempotency_key, decision.audit_id, decision.model_dump_json(), _utcnow_iso()),
            )
            row = conn.execute(
                "SELECT decision_json FROM idempotency WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            return AuditDecision.model_validate_json(row["decision_json"])

        return await asyncio.to_thread(self._write_txn, _fn)

    # ------------------------------------------------------------------ budget ledger
    def _reserve_sync(self, agent_id: str, policy: PolicyConfig, amount_inr: float, enforce: bool) -> ReservationOutcome:
        amount_paise = inr_to_paise(amount_inr)

        def _fn(conn):
            now = time.time()
            usage = self._window_usage(conn, agent_id, policy, now)
            violations: list[BudgetViolation] = []
            if usage.calls_1m + 1 > policy.max_calls_per_min:
                violations.append(
                    BudgetViolation(
                        POL_VELOCITY,
                        f"Velocity circuit-breaker: {usage.calls_1m + 1} calls in 60s exceeds "
                        f"max_calls_per_min={policy.max_calls_per_min}.",
                    )
                )
            for label, used, limit in (
                ("1m", usage.used_1m_inr, policy.window_1m_inr),
                ("1h", usage.used_1h_inr, policy.window_1h_inr),
                ("24h", usage.used_24h_inr, policy.window_24h_inr),
            ):
                used_paise = inr_to_paise(used)
                if used_paise + amount_paise > inr_to_paise(limit):
                    violations.append(
                        BudgetViolation(
                            POL_SLIDING_CAP,
                            f"Sliding {label} cap: ₹{used:,.2f} used + ₹{amount_inr:,.2f} requested "
                            f"exceeds ₹{limit:,.2f} limit.",
                        )
                    )
            if violations and enforce:
                return ReservationOutcome(ok=False, reservation_id=None, violations=violations, usage_before=usage)
            reservation_id = f"rsv_{uuid.uuid4().hex}"
            conn.execute(
                "INSERT INTO budget_ledger (reservation_id, agent_id, policy_id, amount_paise, status, created_ts, updated_ts) "
                "VALUES (?, ?, ?, ?, 'RESERVED', ?, ?)",
                (reservation_id, agent_id, policy.policy_id, amount_paise, now, now),
            )
            # In shadow mode we still reserve (to track real spend) but surface would-be violations.
            return ReservationOutcome(ok=not violations, reservation_id=reservation_id, violations=violations, usage_before=usage)

        return self._write_txn(_fn)

    async def reserve_budget_atomic(
        self, agent_id: str, policy: PolicyConfig, amount_inr: float, *, enforce: bool = True
    ) -> ReservationOutcome:
        return await asyncio.to_thread(self._reserve_sync, agent_id, policy, amount_inr, enforce)

    def _transition(self, reservation_id: str, new_status: str) -> bool:
        def _fn(conn):
            cur = conn.execute(
                "UPDATE budget_ledger SET status = ?, updated_ts = ? WHERE reservation_id = ? AND status = 'RESERVED'",
                (new_status, time.time(), reservation_id),
            )
            return cur.rowcount == 1

        return self._write_txn(_fn)

    async def commit_budget_atomic(self, reservation_id: str) -> bool:
        return await asyncio.to_thread(self._transition, reservation_id, "COMMITTED")

    async def release_budget_atomic(self, reservation_id: str) -> bool:
        return await asyncio.to_thread(self._transition, reservation_id, "RELEASED")

    async def reset_demo_windows(self, agent_id: Optional[str] = None) -> int:
        def _fn(conn):
            if agent_id is None:
                return conn.execute("DELETE FROM budget_ledger").rowcount
            return conn.execute("DELETE FROM budget_ledger WHERE agent_id = ?", (agent_id,)).rowcount

        return await asyncio.to_thread(self._write_txn, _fn)

    async def reset_demo_data(self, agent_id: Optional[str] = None) -> dict[str, int]:
        """Clears ledger, audits, idempotency cache and HITL rows. Policies are preserved."""

        def _fn(conn):
            if agent_id is None:
                return {
                    "ledger_rows": conn.execute("DELETE FROM budget_ledger").rowcount,
                    "audits": conn.execute("DELETE FROM audit_logs").rowcount,
                    "idempotency_keys": conn.execute("DELETE FROM idempotency").rowcount,
                    "hitl_approvals": conn.execute("DELETE FROM hitl_approvals").rowcount,
                }
            audit_ids = "SELECT audit_id FROM audit_logs WHERE agent_id = ?"
            return {
                "ledger_rows": conn.execute("DELETE FROM budget_ledger WHERE agent_id = ?", (agent_id,)).rowcount,
                "hitl_approvals": conn.execute(
                    f"DELETE FROM hitl_approvals WHERE audit_id IN ({audit_ids})", (agent_id,)
                ).rowcount,
                "idempotency_keys": conn.execute(
                    f"DELETE FROM idempotency WHERE audit_id IN ({audit_ids})", (agent_id,)
                ).rowcount,
                "audits": conn.execute("DELETE FROM audit_logs WHERE agent_id = ?", (agent_id,)).rowcount,
            }

        return await asyncio.to_thread(self._write_txn, _fn)

    # ------------------------------------------------------------------ audit log
    async def save_audit(self, decision: AuditDecision) -> None:
        d = decision

        def _fn(conn):
            conn.execute(
                "INSERT INTO audit_logs (audit_id, idempotency_key, agent_id, policy_id, tool_name, merchant_id, amount_inr, "
                "verdict, layer_decided, executed, l1_latency_ms, l2_latency_ms, created_at, decision_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(audit_id) DO UPDATE SET verdict = excluded.verdict, layer_decided = excluded.layer_decided, "
                "executed = excluded.executed, l2_latency_ms = excluded.l2_latency_ms, decision_json = excluded.decision_json",
                (
                    d.audit_id, d.idempotency_key, d.agent_id, d.policy_id, d.tool_name, d.merchant_id, d.amount_inr,
                    d.verdict, d.layer_decided, int(d.executed), d.l1_latency_ms, d.l2_latency_ms, d.created_at,
                    d.model_dump_json(),
                ),
            )

        await asyncio.to_thread(self._write_txn, _fn)

    async def get_audit(self, audit_id: str) -> Optional[AuditDecision]:
        rows = await asyncio.to_thread(self._read, "SELECT decision_json FROM audit_logs WHERE audit_id = ?", (audit_id,))
        return AuditDecision.model_validate_json(rows[0]["decision_json"]) if rows else None

    async def list_audits(self, limit: int = 100, agent_id: Optional[str] = None) -> list[AuditDecision]:
        if agent_id is None:
            sql, params = "SELECT decision_json FROM audit_logs ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)
        else:
            sql = "SELECT decision_json FROM audit_logs WHERE agent_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?"
            params = (agent_id, limit)
        rows = await asyncio.to_thread(self._read, sql, params)
        return [AuditDecision.model_validate_json(r["decision_json"]) for r in rows]

    # ------------------------------------------------------------------ HITL
    async def create_pending_approval(
        self,
        *,
        audit_id: str,
        reservation_id: Optional[str],
        canonical_payload_json: str,
        payload_sha256: str,
        request_json: str,
    ) -> str:
        approval_id = f"apr_{uuid.uuid4().hex}"

        def _fn(conn):
            conn.execute(
                "INSERT INTO hitl_approvals (approval_id, audit_id, reservation_id, canonical_payload_json, payload_sha256, "
                "status, request_json, created_at) VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?)",
                (approval_id, audit_id, reservation_id, canonical_payload_json, payload_sha256, request_json, _utcnow_iso()),
            )
            return approval_id

        return await asyncio.to_thread(self._write_txn, _fn)

    async def list_pending_approvals(self, status: str = "PENDING") -> list[dict]:
        rows = await asyncio.to_thread(
            self._read, "SELECT * FROM hitl_approvals WHERE status = ? ORDER BY created_at DESC", (status,)
        )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ metrics
    def _metrics_sync(self, agent_id: Optional[str], policy: PolicyConfig, policy_filter: Optional[str]) -> MetricsSummary:
        where, params = [], []
        if agent_id is not None:
            where.append("agent_id = ?")
            params.append(agent_id)
        if policy_filter is not None:
            where.append("policy_id = ?")
            params.append(policy_filter)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        sql = (
            "SELECT COUNT(*) AS total,"
            " COALESCE(SUM(verdict = 'ALLOW'), 0) AS allowed,"
            " COALESCE(SUM(verdict = 'BLOCK'), 0) AS blocked,"
            " COALESCE(SUM(verdict = 'ESCALATE'), 0) AS escalated,"
            " COALESCE(SUM(verdict = 'SHADOW_FLAG'), 0) AS shadow,"
            " COALESCE(SUM(CASE WHEN executed = 1 THEN amount_inr ELSE 0 END), 0) AS settled,"
            " COALESCE(SUM(CASE WHEN executed = 0 AND verdict IN ('BLOCK','ESCALATE') THEN amount_inr ELSE 0 END), 0) AS protected,"
            " COALESCE(AVG(l1_latency_ms), 0) AS avg_l1,"
            " COALESCE(AVG(CASE WHEN l2_latency_ms > 0 THEN l2_latency_ms END), 0) AS avg_l2 "
            f"FROM audit_logs {clause}"
        )
        with self._lock:
            row = self._conn.execute(sql, tuple(params)).fetchone()
            usage = self._window_usage(self._conn, agent_id, policy, time.time())
        return MetricsSummary(
            total_requests=int(row["total"]),
            allowed_count=int(row["allowed"]),
            blocked_count=int(row["blocked"]),
            escalated_count=int(row["escalated"]),
            shadow_flagged_count=int(row["shadow"]),
            total_inr_settled=round(float(row["settled"]), 2),
            total_inr_protected=round(float(row["protected"]), 2),
            avg_l1_latency_ms=round(float(row["avg_l1"]), 3),
            avg_l2_latency_ms=round(float(row["avg_l2"]), 3),
            window_usage=usage,
        )

    async def get_metrics(self, agent_id: Optional[str] = None, policy_id: Optional[str] = None) -> MetricsSummary:
        policy = await self.get_policy(policy_id or DEFAULT_POLICY_ID) or default_policy()
        return await asyncio.to_thread(self._metrics_sync, agent_id, policy, policy_id)
