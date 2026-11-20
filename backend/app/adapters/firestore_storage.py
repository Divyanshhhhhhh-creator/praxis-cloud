"""Firestore adapter (Cloud Run, asia-south1) for the `StorageRepository` port.

Atomicity model (mirrors SQLite's `BEGIN IMMEDIATE` + process lock):
  * Every budget reservation / commit / release runs inside a Firestore transaction
    (`@firestore.async_transactional`) that reads AND writes one per-(agent, policy) window document
    holding the live 24-hour reservation entries. Concurrent reservations for the same window therefore
    conflict on that document and are serialized by Firestore's transaction retry — two parallel calls can
    never both see the same headroom (no micro-slicing race), across any number of Cloud Run instances.
  * The idempotency cache and HITL approvals use transactional first-writer-wins / compare-and-set
    (PENDING -> PROCESSING) exactly like the SQLite adapter.
  * Only equality filters / single-field ordering are used, so no composite indexes need deploying.

The velocity + sliding-cap rule itself is shared with SQLite (`storage.budget_violations`).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from google.api_core import exceptions as gexc
from google.cloud import firestore
from google.cloud.firestore_v1 import FieldFilter

from ..domain.hashing import inr_to_paise
from ..domain.models import AuditDecision, MetricsSummary, PolicyConfig, WindowUsage
from ..domain.policy_catalog import DEFAULT_POLICY_ID, POL_SLIDING_CAP, default_policy
from .storage import BudgetViolation, ReservationOutcome, StorageRepository, budget_violations

C_POLICIES = "praxis_policies"
C_IDEMPOTENCY = "praxis_idempotency"
C_WINDOWS = "praxis_budget_windows"
C_LEDGER = "praxis_budget_ledger"
C_AUDITS = "praxis_audit_logs"
C_HITL = "praxis_hitl_approvals"

ACTIVE = ("RESERVED", "COMMITTED")
WINDOW_SECONDS = 86_400
MAX_WINDOW_ENTRIES = 20_000  # ~1.2 MB-safe ceiling for one window doc; beyond it we fail closed
SCAN_LIMIT = 5_000


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _doc_id(raw: str) -> str:
    """Firestore doc ids may not contain '/' and should be bounded: hash arbitrary keys."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _window_id(agent_id: str, policy_id: str) -> str:
    return _doc_id(f"{agent_id}\x1f{policy_id}")


def _live_entries(snapshot: Any, now: float) -> list[dict]:
    if snapshot is None or not snapshot.exists:
        return []
    entries = (snapshot.to_dict() or {}).get("entries") or []
    return [e for e in entries if e.get("status") in ACTIVE and float(e.get("ts", 0)) > now - WINDOW_SECONDS]


def _usage(entries: list[dict], policy: PolicyConfig, now: float) -> WindowUsage:
    p1m = sum(e["paise"] for e in entries if e["ts"] > now - 60)
    p1h = sum(e["paise"] for e in entries if e["ts"] > now - 3600)
    p24 = sum(e["paise"] for e in entries)
    return WindowUsage(
        used_1m_inr=p1m / 100,
        limit_1m_inr=policy.window_1m_inr,
        used_1h_inr=p1h / 100,
        limit_1h_inr=policy.window_1h_inr,
        used_24h_inr=p24 / 100,
        limit_24h_inr=policy.window_24h_inr,
        calls_1m=sum(1 for e in entries if e["ts"] > now - 60),
        limit_calls_1m=policy.max_calls_per_min,
    )


class FirestoreRepository(StorageRepository):
    def __init__(self, *, project: Optional[str] = None, database: Optional[str] = None, client: Any = None):
        self._db = client or firestore.AsyncClient(project=project or None, database=database or None)
        self._ready_lock = asyncio.Lock()
        self._ready = False

    def close(self) -> None:
        try:
            self._db.close()
        except Exception:  # pragma: no cover - best effort
            pass

    # ------------------------------------------------------------------ helpers
    def _col(self, name: str):
        return self._db.collection(name)

    async def _ensure_ready(self) -> None:
        if self._ready:
            return
        async with self._ready_lock:
            if self._ready:
                return
            p = default_policy()
            try:
                await self._col(C_POLICIES).document(p.policy_id).create(
                    {"config": p.model_dump(), "updated_at": _utcnow_iso()}
                )
            except gexc.AlreadyExists:
                pass
            self._ready = True

    async def _delete_where(self, collection: str, field: Optional[str] = None, value: Any = None) -> int:
        query = self._col(collection)
        if field is not None:
            query = query.where(filter=FieldFilter(field, "==", value))
        deleted = 0
        batch = self._db.batch()
        async for snap in query.stream():
            batch.delete(snap.reference)
            deleted += 1
            if deleted % 400 == 0:
                await batch.commit()
                batch = self._db.batch()
        if deleted % 400:
            await batch.commit()
        return deleted

    # ------------------------------------------------------------------ policies
    async def get_policy(self, policy_id: str) -> Optional[PolicyConfig]:
        await self._ensure_ready()
        snap = await self._col(C_POLICIES).document(policy_id).get()
        return PolicyConfig.model_validate(snap.to_dict()["config"]) if snap.exists else None

    async def list_policies(self) -> list[PolicyConfig]:
        await self._ensure_ready()
        out = [PolicyConfig.model_validate(s.to_dict()["config"]) async for s in self._col(C_POLICIES).stream()]
        return sorted(out, key=lambda p: p.policy_id)

    async def upsert_policy(self, policy: PolicyConfig) -> PolicyConfig:
        await self._ensure_ready()
        await self._col(C_POLICIES).document(policy.policy_id).set({"config": policy.model_dump(), "updated_at": _utcnow_iso()})
        return policy

    # ------------------------------------------------------------------ idempotency
    async def get_idempotent_decision(self, idempotency_key: str) -> Optional[AuditDecision]:
        snap = await self._col(C_IDEMPOTENCY).document(_doc_id(idempotency_key)).get()
        return AuditDecision.model_validate_json(snap.to_dict()["decision_json"]) if snap.exists else None

    async def save_idempotent_decision(self, idempotency_key: str, decision: AuditDecision) -> AuditDecision:
        ref = self._col(C_IDEMPOTENCY).document(_doc_id(idempotency_key))

        @firestore.async_transactional
        async def txn(transaction):
            snap = await ref.get(transaction=transaction)
            if snap.exists:  # first writer wins
                return AuditDecision.model_validate_json(snap.to_dict()["decision_json"])
            transaction.set(ref, {
                "idempotency_key": idempotency_key, "agent_id": decision.agent_id, "audit_id": decision.audit_id,
                "decision_json": decision.model_dump_json(), "created_at": _utcnow_iso(),
            })
            return decision

        return await txn(self._db.transaction())

    async def update_idempotent_decision(self, idempotency_key: str, decision: AuditDecision) -> None:
        await self._col(C_IDEMPOTENCY).document(_doc_id(idempotency_key)).set(
            {"audit_id": decision.audit_id, "decision_json": decision.model_dump_json()}, merge=True
        )

    # ------------------------------------------------------------------ budget ledger (transactional)
    async def reserve_budget_atomic(
        self, agent_id: str, policy: PolicyConfig, amount_inr: float, *, enforce: bool = True
    ) -> ReservationOutcome:
        window_ref = self._col(C_WINDOWS).document(_window_id(agent_id, policy.policy_id))
        reservation_id = f"rsv_{uuid.uuid4().hex}"
        amount_paise = inr_to_paise(amount_inr)

        @firestore.async_transactional
        async def txn(transaction):
            now = time.time()
            snap = await window_ref.get(transaction=transaction)  # read → this txn conflicts with any concurrent writer
            entries = _live_entries(snap, now)
            usage = _usage(entries, policy, now)
            violations = budget_violations(usage, policy, amount_inr)
            if len(entries) >= MAX_WINDOW_ENTRIES:  # document-size guard: fail closed, never insert
                violations.append(BudgetViolation(POL_SLIDING_CAP, "Ledger window saturated; failing closed."))
                return ReservationOutcome(ok=False, reservation_id=None, violations=violations, usage_before=usage)
            if violations and enforce:
                return ReservationOutcome(ok=False, reservation_id=None, violations=violations, usage_before=usage)
            entries.append({"rid": reservation_id, "paise": amount_paise, "ts": now, "status": "RESERVED"})
            transaction.set(window_ref, {"agent_id": agent_id, "policy_id": policy.policy_id, "entries": entries, "updated_ts": now})
            transaction.set(self._col(C_LEDGER).document(reservation_id), {
                "agent_id": agent_id, "policy_id": policy.policy_id, "amount_paise": amount_paise,
                "status": "RESERVED", "created_ts": now, "updated_ts": now,
            })
            return ReservationOutcome(ok=not violations, reservation_id=reservation_id, violations=violations, usage_before=usage)

        return await txn(self._db.transaction())

    async def _transition(self, reservation_id: str, new_status: str) -> bool:
        ledger_ref = self._col(C_LEDGER).document(reservation_id)

        @firestore.async_transactional
        async def txn(transaction):
            ledger = await ledger_ref.get(transaction=transaction)
            if not ledger.exists or ledger.get("status") != "RESERVED":
                return False
            window_ref = self._col(C_WINDOWS).document(_window_id(ledger.get("agent_id"), ledger.get("policy_id")))
            window = await window_ref.get(transaction=transaction)
            now = time.time()
            entries = _live_entries(window, now)
            if new_status == "RELEASED":
                entries = [e for e in entries if e["rid"] != reservation_id]
            else:
                for e in entries:
                    if e["rid"] == reservation_id:
                        e["status"] = new_status
            transaction.set(window_ref, {"entries": entries, "updated_ts": now}, merge=True)
            transaction.update(ledger_ref, {"status": new_status, "updated_ts": now})
            return True

        return await txn(self._db.transaction())

    async def commit_budget_atomic(self, reservation_id: str) -> bool:
        return await self._transition(reservation_id, "COMMITTED")

    async def release_budget_atomic(self, reservation_id: str) -> bool:
        return await self._transition(reservation_id, "RELEASED")

    async def reset_demo_windows(self, agent_id: Optional[str] = None) -> int:
        field = "agent_id" if agent_id is not None else None
        await self._delete_where(C_WINDOWS, field, agent_id)
        return await self._delete_where(C_LEDGER, field, agent_id)

    async def reset_demo_data(self, agent_id: Optional[str] = None) -> dict[str, int]:
        field = "agent_id" if agent_id is not None else None
        return {
            "ledger_rows": await self.reset_demo_windows(agent_id),
            "hitl_approvals": await self._delete_where(C_HITL, field, agent_id),
            "idempotency_keys": await self._delete_where(C_IDEMPOTENCY, field, agent_id),
            "audits": await self._delete_where(C_AUDITS, field, agent_id),
        }

    # ------------------------------------------------------------------ audit log
    async def save_audit(self, decision: AuditDecision) -> None:
        d = decision
        await self._col(C_AUDITS).document(d.audit_id).set({
            "audit_id": d.audit_id, "agent_id": d.agent_id, "policy_id": d.policy_id, "verdict": d.verdict,
            "layer_decided": d.layer_decided, "executed": d.executed, "amount_inr": d.amount_inr,
            "l1_latency_ms": d.l1_latency_ms, "l2_latency_ms": d.l2_latency_ms, "created_at": d.created_at,
            "decision_json": d.model_dump_json(),
        })

    async def get_audit(self, audit_id: str) -> Optional[AuditDecision]:
        snap = await self._col(C_AUDITS).document(audit_id).get()
        return AuditDecision.model_validate_json(snap.to_dict()["decision_json"]) if snap.exists else None

    async def list_audits(self, limit: int = 100, agent_id: Optional[str] = None) -> list[AuditDecision]:
        if agent_id is None:
            query = self._col(C_AUDITS).order_by("created_at", direction=firestore.Query.DESCENDING).limit(limit)
            return [AuditDecision.model_validate_json(s.to_dict()["decision_json"]) async for s in query.stream()]
        query = self._col(C_AUDITS).where(filter=FieldFilter("agent_id", "==", agent_id)).limit(SCAN_LIMIT)
        rows = [s.to_dict() async for s in query.stream()]
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        return [AuditDecision.model_validate_json(r["decision_json"]) for r in rows[:limit]]

    # ------------------------------------------------------------------ HITL
    async def create_pending_approval(
        self, *, audit_id: str, reservation_id: Optional[str], canonical_payload_json: str, payload_sha256: str, request_json: str,
    ) -> str:
        approval_id = f"apr_{uuid.uuid4().hex}"
        try:
            agent_id = json.loads(request_json).get("agent_id")
        except ValueError:
            agent_id = None
        await self._col(C_HITL).document(approval_id).create({
            "approval_id": approval_id, "audit_id": audit_id, "reservation_id": reservation_id,
            "canonical_payload_json": canonical_payload_json, "payload_sha256": payload_sha256, "status": "PENDING",
            "request_json": request_json, "created_at": _utcnow_iso(), "agent_id": agent_id,
            "reviewer_id": None, "decision_note": None, "decided_at": None, "settlement_txn_id": None, "decision_audit_id": None,
        })
        return approval_id

    @staticmethod
    def _approval_row(raw: dict) -> dict:
        row = {k: v for k, v in raw.items() if k != "agent_id"}
        return row

    async def list_approvals(self, status: Optional[str] = None, limit: int = 200) -> list[dict]:
        query = self._col(C_HITL)
        if status is not None:
            query = query.where(filter=FieldFilter("status", "==", status))
        rows = [self._approval_row(s.to_dict()) async for s in query.limit(SCAN_LIMIT).stream()]
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        out = []
        for item in rows[:limit]:
            item["canonical_payload"] = json.loads(item["canonical_payload_json"])
            item["request"] = json.loads(item.pop("request_json"))
            out.append(item)
        return out

    async def get_approval(self, approval_id: str) -> Optional[dict]:
        snap = await self._col(C_HITL).document(approval_id).get()
        return self._approval_row(snap.to_dict()) if snap.exists else None

    async def claim_approval(self, approval_id: str, reviewer_id: str) -> bool:
        ref = self._col(C_HITL).document(approval_id)

        @firestore.async_transactional
        async def txn(transaction):
            snap = await ref.get(transaction=transaction)
            if not snap.exists or snap.get("status") != "PENDING":
                return False
            transaction.update(ref, {"status": "PROCESSING", "reviewer_id": reviewer_id})
            return True

        return await txn(self._db.transaction())

    async def finalize_approval(
        self, approval_id: str, *, status: str, reviewer_id: str, note: str = "",
        settlement_txn_id: Optional[str] = None, decision_audit_id: Optional[str] = None,
    ) -> None:
        ref = self._col(C_HITL).document(approval_id)

        @firestore.async_transactional
        async def txn(transaction):
            snap = await ref.get(transaction=transaction)
            if snap.exists and snap.get("status") == "PROCESSING":
                transaction.update(ref, {
                    "status": status, "reviewer_id": reviewer_id, "decision_note": note, "decided_at": _utcnow_iso(),
                    "settlement_txn_id": settlement_txn_id, "decision_audit_id": decision_audit_id,
                })

        await txn(self._db.transaction())

    async def unclaim_approval(self, approval_id: str) -> None:
        ref = self._col(C_HITL).document(approval_id)

        @firestore.async_transactional
        async def txn(transaction):
            snap = await ref.get(transaction=transaction)
            if snap.exists and snap.get("status") == "PROCESSING":
                transaction.update(ref, {"status": "PENDING", "reviewer_id": None})

        await txn(self._db.transaction())

    # ------------------------------------------------------------------ metrics
    async def _window_usage(self, agent_id: Optional[str], policy: PolicyConfig) -> WindowUsage:
        now = time.time()
        if agent_id is not None:
            snap = await self._col(C_WINDOWS).document(_window_id(agent_id, policy.policy_id)).get()
            return _usage(_live_entries(snap, now), policy, now)
        entries: list[dict] = []
        query = self._col(C_WINDOWS).where(filter=FieldFilter("policy_id", "==", policy.policy_id))
        async for snap in query.stream():
            entries.extend(_live_entries(snap, now))
        return _usage(entries, policy, now)

    async def get_metrics(self, agent_id: Optional[str] = None, policy_id: Optional[str] = None) -> MetricsSummary:
        policy = await self.get_policy(policy_id or DEFAULT_POLICY_ID) or default_policy()
        query = self._col(C_AUDITS)
        if agent_id is not None:
            query = query.where(filter=FieldFilter("agent_id", "==", agent_id))
        if policy_id is not None:
            query = query.where(filter=FieldFilter("policy_id", "==", policy_id))
        rows = [s.to_dict() async for s in query.stream()]
        l2 = [r["l2_latency_ms"] for r in rows if r.get("l2_latency_ms", 0) > 0]
        return MetricsSummary(
            total_requests=len(rows),
            allowed_count=sum(r["verdict"] == "ALLOW" for r in rows),
            blocked_count=sum(r["verdict"] == "BLOCK" for r in rows),
            escalated_count=sum(r["verdict"] == "ESCALATE" for r in rows),
            shadow_flagged_count=sum(r["verdict"] == "SHADOW_FLAG" for r in rows),
            total_inr_settled=round(sum(r["amount_inr"] for r in rows if r["executed"]), 2),
            total_inr_protected=round(sum(r["amount_inr"] for r in rows if not r["executed"] and r["verdict"] in ("BLOCK", "ESCALATE")), 2),
            avg_l1_latency_ms=round(sum(r["l1_latency_ms"] for r in rows) / len(rows), 3) if rows else 0.0,
            avg_l2_latency_ms=round(sum(l2) / len(l2), 3) if l2 else 0.0,
            window_usage=await self._window_usage(agent_id, policy),
        )
