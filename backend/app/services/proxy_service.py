"""Vaulted Execution Proxy orchestrator for POST /v1/intercept.

Pipeline: idempotency → canonical SHA-256 seal → Layer 1 (atomic reservation) → Layer 2 Gemini
auditor → {BLOCK: release | ESCALATE: hold for HITL | ALLOW: vault settle → commit}
→ persist audit + idempotency cache.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from ..adapters.payment_vault import PaymentVault, SecurityIntegrityError
from ..adapters.storage import StorageRepository
from ..domain.hashing import build_execution_envelope, canonical_json, compute_payload_sha256
from ..domain.models import AuditDecision, InterceptRequest
from ..domain.policy_catalog import POL_FAIL_CLOSED, POL_POLICY_NOT_FOUND
from ..domain.policy_corpus import POL_HITL_THRESHOLD
from .layer1_engine import Layer1Engine
from .layer2_contract import Layer2Auditor, Layer2Verdict

# Outer safety net only; the auditor enforces its own 2.5s (text) / 4.0s (multimodal) budget.
L2_BACKSTOP_MARGIN_S = 3.0


class IdempotencyConflictError(Exception):
    """Same idempotency_key replayed with a different payload."""


@dataclass
class InterceptOutcome:
    decision: AuditDecision
    replayed: bool = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def scoped_idempotency_key(agent_id: str, idempotency_key: str) -> str:
    """Idempotency keys are namespaced per agent so one agent can never read another's decision."""
    return f"{agent_id}::{idempotency_key}"


class ProxyService:
    def __init__(
        self,
        *,
        storage: StorageRepository,
        vault: PaymentVault,
        layer2_auditor: Optional[Layer2Auditor] = None,
    ):
        self.storage = storage
        self.vault = vault
        self.layer1 = Layer1Engine(storage)
        self.layer2_auditor = layer2_auditor
        self._key_locks: dict[str, list] = {}

    @staticmethod
    def _scoped_key(req: InterceptRequest) -> str:
        return scoped_idempotency_key(req.agent_id, req.idempotency_key)

    @asynccontextmanager
    async def _single_flight(self, key: str):
        entry = self._key_locks.setdefault(key, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with entry[0]:
                yield
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                self._key_locks.pop(key, None)

    async def intercept(self, req: InterceptRequest) -> InterceptOutcome:
        scoped_key = self._scoped_key(req)
        envelope = build_execution_envelope(
            tool_name=req.tool_name,
            merchant_id=req.merchant_id,
            amount_inr=req.amount_inr,
            destination_mode=req.destination_mode,
            payload=req.payload,
        )
        payload_sha256 = compute_payload_sha256(envelope)

        async with self._single_flight(scoped_key):
            cached = await self.storage.get_idempotent_decision(scoped_key)
            if cached is not None:
                if cached.payload_sha256 != payload_sha256:
                    raise IdempotencyConflictError(
                        "idempotency_key was already used with a different payload; refusing replay."
                    )
                return InterceptOutcome(decision=cached, replayed=True)
            decision = await self._evaluate_and_execute(req, envelope, payload_sha256)
            return InterceptOutcome(decision=decision)

    async def _run_layer2(self, **kw) -> Layer2Verdict:
        t0 = time.perf_counter()
        backstop = getattr(self.layer2_auditor, "max_timeout_s", 2.5) + L2_BACKSTOP_MARGIN_S
        try:
            return await asyncio.wait_for(self.layer2_auditor.audit(**kw), timeout=backstop)
        except Exception as exc:  # auditor bug / backstop timeout → fail closed
            return Layer2Verdict(
                verdict="ESCALATE", risk_score=0.65,
                reason=f"Fail-closed escalation: Layer 2 unavailable ({type(exc).__name__}); manual treasury approval required.",
                citations=[POL_FAIL_CLOSED], latency_ms=round((time.perf_counter() - t0) * 1000, 3),
                threat_category="NONE", fail_closed=True,
            )

    async def _evaluate_and_execute(self, req: InterceptRequest, envelope: dict, payload_sha256: str) -> AuditDecision:
        audit_id = f"aud_{uuid.uuid4().hex}"
        scoped_key = self._scoped_key(req)

        def decide(**kw) -> AuditDecision:
            base = dict(
                audit_id=audit_id,
                idempotency_key=req.idempotency_key,
                agent_id=req.agent_id,
                policy_id=req.policy_id,
                tool_name=req.tool_name,
                amount_inr=req.amount_inr,
                merchant_id=req.merchant_id,
                payload_sha256=payload_sha256,
                created_at=_now_iso(),
            )
            base.update(kw)
            return AuditDecision(**base)

        async def finalize(decision: AuditDecision, *, cache: bool = True) -> AuditDecision:
            await self.storage.save_audit(decision)
            if cache:
                return await self.storage.save_idempotent_decision(scoped_key, decision)
            return decision

        async def escalate(layer_decided: str, why: str) -> AuditDecision:
            approval_id = await self.storage.create_pending_approval(
                audit_id=audit_id, reservation_id=l1.reservation_id,
                canonical_payload_json=canonical_json(envelope), payload_sha256=payload_sha256,
                request_json=req.model_dump_json(exclude={"attachment_base64"}),
            )
            return await finalize(
                decide(
                    verdict="ESCALATE", layer_decided=layer_decided, risk_score=risk, reason=why,
                    policy_citations=citations, l1_latency_ms=l1.latency_ms, executed=False,
                    approval_id=approval_id, **l2_fields,
                )
            )

        policy = await self.storage.get_policy(req.policy_id)
        if policy is None:  # fail closed on unknown policy
            return await finalize(
                decide(
                    verdict="BLOCK", layer_decided="L1_DETERMINISTIC", risk_score=1.0,
                    reason=f"Unknown policy_id '{req.policy_id}'; failing closed.",
                    policy_citations=[POL_POLICY_NOT_FOUND], l1_latency_ms=0.0, executed=False,
                )
            )

        # ---- Layer 1 (deterministic, atomic reservation)
        l1 = await self.layer1.evaluate(req, policy)
        shadow = policy.mode == "shadow"
        verdict, layer, risk, reason, citations = "ALLOW", "L1_DETERMINISTIC", 0.0, l1.reason, l1.citations

        if not l1.passed:
            if not shadow:
                if l1.reservation_id:  # defensive: never leak reserved budget on a block
                    await self.storage.release_budget_atomic(l1.reservation_id)
                return await finalize(
                    decide(
                        verdict="BLOCK", layer_decided="L1_DETERMINISTIC", risk_score=1.0, reason=l1.reason,
                        policy_citations=l1.citations, l1_latency_ms=l1.latency_ms, executed=False,
                    )
                )
            verdict, risk, reason = "SHADOW_FLAG", 1.0, f"[SHADOW MODE – L1 would BLOCK] {l1.reason}"

        # ---- Layer 2 (Gemini; monotonic — may only tighten)
        l2: Optional[Layer2Verdict] = None
        l2_fields: dict = {}
        if self.layer2_auditor is not None:
            l2 = await self._run_layer2(req=req, policy=policy, envelope=envelope, payload_sha256=payload_sha256, l1=l1)
            l2_fields = dict(
                l2_latency_ms=l2.latency_ms, threat_category=l2.threat_category,
                invoice_extracted_total_inr=l2.invoice_extracted_total_inr, model_used=l2.model_used,
            )
            risk = max(risk, l2.risk_score)
            if l2.verdict == "ALLOW":
                if verdict == "ALLOW":
                    layer = "L2_GEMINI_AUDITOR"
                    reason = f"L1 passed; L2 ALLOW: {l2.reason}"
            else:
                citations = list(dict.fromkeys(citations + l2.citations))
                if shadow:
                    if l1.passed:  # L2 is the layer that raised the flag
                        layer, reason = "L2_GEMINI_AUDITOR", "L1 passed"
                    verdict = "SHADOW_FLAG"
                    reason = f"{reason} | [SHADOW MODE – L2 would {l2.verdict}] {l2.reason}"
                elif l2.verdict == "BLOCK":
                    await self.storage.release_budget_atomic(l1.reservation_id)  # zero budget leaked
                    return await finalize(
                        decide(
                            verdict="BLOCK", layer_decided="L2_GEMINI_AUDITOR", risk_score=risk, reason=l2.reason,
                            policy_citations=citations, l1_latency_ms=l1.latency_ms, executed=False, **l2_fields,
                        )
                    )
                else:  # ESCALATE → park the sealed envelope for HITL; budget stays RESERVED (held)
                    return await escalate("L2_GEMINI_AUDITOR", l2.reason)

        # ---- Deterministic HITL threshold (defense in depth: holds even if Layer 2 is disabled/unavailable)
        if not shadow and verdict == "ALLOW" and req.amount_inr > policy.auto_approve_threshold_inr:
            citations = list(dict.fromkeys(citations + [POL_HITL_THRESHOLD]))
            return await escalate(
                layer if l2 is not None else "L1_DETERMINISTIC",
                f"₹{req.amount_inr:,.2f} exceeds auto-approve threshold ₹{policy.auto_approve_threshold_inr:,.2f}; "
                "Finance Manager HITL approval required.",
            )

        # ---- Execute the sealed envelope via the vault
        try:
            settlement = await self.vault.execute(audit_id=audit_id, payload=envelope, expected_sha256=payload_sha256)
        except Exception as exc:  # SecurityIntegrityError, SettlementError, or anything unexpected
            if l1.reservation_id:
                await self.storage.release_budget_atomic(l1.reservation_id)
            code = "SECURITY_INTEGRITY" if isinstance(exc, SecurityIntegrityError) else getattr(exc, "code", type(exc).__name__)
            # Not cached under the idempotency key so the agent may safely retry the same key.
            return await finalize(
                decide(
                    verdict="BLOCK", layer_decided=layer, risk_score=risk,
                    reason=f"Fail-closed: settlement aborted ({code}): {exc}. Reserved budget released.",
                    policy_citations=list(dict.fromkeys(citations + [POL_FAIL_CLOSED])),
                    l1_latency_ms=l1.latency_ms, executed=False, **l2_fields,
                ),
                cache=False,
            )

        if l1.reservation_id:
            await self.storage.commit_budget_atomic(l1.reservation_id)

        return await finalize(
            decide(
                verdict=verdict, layer_decided=layer, risk_score=risk, reason=reason, policy_citations=citations,
                l1_latency_ms=l1.latency_ms, executed=True, settlement_txn_id=settlement.settlement_txn_id,
                settlement_rail=settlement.settlement_rail, **l2_fields,
            )
        )
