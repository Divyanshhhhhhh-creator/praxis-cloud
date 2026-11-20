"""Vaulted Execution Proxy orchestrator for POST /v1/intercept.

Pipeline: idempotency → canonical SHA-256 seal → Layer 1 → (Layer 2 hook) → vault settle
→ commit/release budget → persist audit + idempotency cache.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional, Protocol

from ..adapters.payment_vault import PaymentVault, SecurityIntegrityError
from ..adapters.storage import StorageRepository
from ..domain.hashing import build_execution_envelope, canonical_json, compute_payload_sha256
from ..domain.models import AuditDecision, InterceptRequest, PolicyConfig
from ..domain.policy_catalog import POL_FAIL_CLOSED, POL_POLICY_NOT_FOUND
from .layer1_engine import Layer1Engine, Layer1Result

L2_TIMEOUT_SECONDS = 2.5


class IdempotencyConflictError(Exception):
    """Same idempotency_key replayed with a different payload."""


# ---------------------------------------------------------------- Layer 2 hook (Slice 2)
@dataclass
class Layer2Verdict:
    verdict: Literal["ALLOW", "BLOCK", "ESCALATE"]
    risk_score: float
    reason: str
    citations: list[str] = field(default_factory=list)
    latency_ms: float = 0.0


class Layer2Auditor(Protocol):
    async def audit(
        self, *, req: InterceptRequest, policy: PolicyConfig, envelope: dict, payload_sha256: str, l1: Layer1Result
    ) -> Layer2Verdict: ...


@dataclass
class InterceptOutcome:
    decision: AuditDecision
    replayed: bool = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProxyService:
    def __init__(
        self,
        *,
        storage: StorageRepository,
        vault: PaymentVault,
        layer2_auditor: Optional[Layer2Auditor] = None,
        l2_timeout_s: float = L2_TIMEOUT_SECONDS,
    ):
        self.storage = storage
        self.vault = vault
        self.layer1 = Layer1Engine(storage)
        self.layer2_auditor = layer2_auditor
        self.l2_timeout_s = l2_timeout_s
        self._key_locks: dict[str, list] = {}

    @staticmethod
    def _scoped_key(req: InterceptRequest) -> str:
        # Idempotency keys are namespaced per agent so one agent can never read another's decision.
        return f"{req.agent_id}::{req.idempotency_key}"

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
            # Step 1: idempotency
            cached = await self.storage.get_idempotent_decision(scoped_key)
            if cached is not None:
                if cached.payload_sha256 != payload_sha256:
                    raise IdempotencyConflictError(
                        "idempotency_key was already used with a different payload; refusing replay."
                    )
                return InterceptOutcome(decision=cached, replayed=True)
            decision = await self._evaluate_and_execute(req, envelope, payload_sha256)
            return InterceptOutcome(decision=decision)

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

        policy = await self.storage.get_policy(req.policy_id)
        if policy is None:  # fail closed on unknown policy
            return await finalize(
                decide(
                    verdict="BLOCK", layer_decided="L1_DETERMINISTIC", risk_score=1.0,
                    reason=f"Unknown policy_id '{req.policy_id}'; failing closed.",
                    policy_citations=[POL_POLICY_NOT_FOUND], l1_latency_ms=0.0, executed=False,
                )
            )

        # Step 3: Layer 1
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
            verdict, risk, reason = "SHADOW_FLAG", 1.0, f"[SHADOW MODE – would BLOCK] {l1.reason}"

        # Step 4: Layer 2 hook (monotonic: may only tighten; fail-closed to ESCALATE)
        l2_latency = 0.0
        if self.layer2_auditor is not None:
            t0 = time.perf_counter()
            try:
                l2 = await asyncio.wait_for(
                    self.layer2_auditor.audit(
                        req=req, policy=policy, envelope=envelope, payload_sha256=payload_sha256, l1=l1
                    ),
                    timeout=self.l2_timeout_s,
                )
            except Exception as exc:  # timeout, API error, malformed output → fail closed
                l2 = Layer2Verdict("ESCALATE", 0.5, f"Layer 2 unavailable ({type(exc).__name__}); fail-closed to HITL.",
                                   [POL_FAIL_CLOSED])
            l2_latency = round(l2.latency_ms or (time.perf_counter() - t0) * 1000, 3)
            if l2.verdict != "ALLOW":
                citations = list(dict.fromkeys(citations + l2.citations))
                risk = max(risk, l2.risk_score)
                if shadow:
                    verdict, reason = "SHADOW_FLAG", f"{reason} | [SHADOW MODE – L2 {l2.verdict}] {l2.reason}"
                elif l2.verdict == "BLOCK":
                    if l1.reservation_id:
                        await self.storage.release_budget_atomic(l1.reservation_id)
                    return await finalize(
                        decide(
                            verdict="BLOCK", layer_decided="L2_GEMINI_AUDITOR", risk_score=risk, reason=l2.reason,
                            policy_citations=citations, l1_latency_ms=l1.latency_ms, l2_latency_ms=l2_latency,
                            executed=False,
                        )
                    )
                else:  # ESCALATE → park sealed payload for HITL; budget stays RESERVED (held)
                    decision = decide(
                        verdict="ESCALATE", layer_decided="L2_GEMINI_AUDITOR", risk_score=risk, reason=l2.reason,
                        policy_citations=citations, l1_latency_ms=l1.latency_ms, l2_latency_ms=l2_latency,
                        executed=False,
                    )
                    await self.storage.create_pending_approval(
                        audit_id=audit_id, reservation_id=l1.reservation_id,
                        canonical_payload_json=canonical_json(envelope), payload_sha256=payload_sha256,
                        request_json=req.model_dump_json(exclude={"attachment_base64"}),
                    )
                    return await finalize(decision)
            else:
                risk = max(risk, l2.risk_score)

        # Step 5: execute the sealed envelope via the vault
        try:
            settlement = await self.vault.execute(audit_id=audit_id, payload=envelope, expected_sha256=payload_sha256)
        except Exception as exc:  # SecurityIntegrityError, SettlementError, or anything unexpected
            if l1.reservation_id:
                await self.storage.release_budget_atomic(l1.reservation_id)
            code = getattr(exc, "code", type(exc).__name__)
            if isinstance(exc, SecurityIntegrityError):
                code = "SECURITY_INTEGRITY"
            # Not cached under the idempotency key so the agent may safely retry the same key.
            return await finalize(
                decide(
                    verdict="BLOCK", layer_decided="L1_DETERMINISTIC", risk_score=risk,
                    reason=f"Fail-closed: settlement aborted ({code}): {exc}. Reserved budget released.",
                    policy_citations=list(dict.fromkeys(citations + [POL_FAIL_CLOSED])),
                    l1_latency_ms=l1.latency_ms, l2_latency_ms=l2_latency, executed=False,
                ),
                cache=False,
            )

        if l1.reservation_id:
            await self.storage.commit_budget_atomic(l1.reservation_id)

        # Step 6: persist
        return await finalize(
            decide(
                verdict=verdict, layer_decided=layer, risk_score=risk, reason=reason, policy_citations=citations,
                l1_latency_ms=l1.latency_ms, l2_latency_ms=l2_latency, executed=True,
                settlement_txn_id=settlement.settlement_txn_id, settlement_rail=settlement.settlement_rail,
            )
        )
