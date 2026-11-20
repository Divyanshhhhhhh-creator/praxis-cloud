"""1-click Human-in-the-Loop approval release & rejection.

Guarantees:
  * Exactly-once: an atomic PENDING -> PROCESSING claim means two concurrent APPROVE clicks can never both
    settle. Anything not PENDING returns a conflict (HTTP 409).
  * Anti-TOCTOU: the stored canonical payload is re-hashed and compared with the SHA-256 sealed at intake,
    and the vault re-verifies it again, before any money moves. Only the exact verified payload executes.
  * Budget integrity: APPROVE commits the held reservation; REJECT (or an integrity failure) releases it to ₹0.
"""

from __future__ import annotations

import hmac
import json
import uuid
from datetime import datetime, timezone
from typing import Literal

from ..adapters.payment_vault import PaymentVault, SecurityIntegrityError
from ..adapters.storage import StorageRepository
from ..domain.hashing import compute_payload_sha256
from ..domain.models import AuditDecision
from .proxy_service import scoped_idempotency_key


class ApprovalNotFoundError(Exception):
    pass


class ApprovalConflictError(Exception):
    pass


class ApprovalIntegrityError(Exception):
    pass


class ApprovalSettlementError(Exception):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class HitlService:
    def __init__(self, *, storage: StorageRepository, vault: PaymentVault):
        self.storage = storage
        self.vault = vault

    async def decide_approval(
        self, approval_id: str, decision: Literal["APPROVE", "REJECT"], reviewer_id: str, note: str = ""
    ) -> AuditDecision:
        approval = await self.storage.get_approval(approval_id)
        if approval is None:
            raise ApprovalNotFoundError(f"Approval '{approval_id}' not found.")
        if approval["status"] != "PENDING":
            raise ApprovalConflictError(
                f"Approval '{approval_id}' is already {approval['status']}; refusing double decision."
            )
        if not await self.storage.claim_approval(approval_id, reviewer_id):
            raise ApprovalConflictError(f"Approval '{approval_id}' was decided concurrently; refusing double decision.")

        original = await self.storage.get_audit(approval["audit_id"])
        if original is None:  # should be impossible; fail closed
            await self._release_and_finalize(approval, "REJECTED", reviewer_id, "orphaned approval (no audit)")
            raise ApprovalIntegrityError("Escalated audit record missing; approval rejected fail-closed.")

        if decision == "REJECT":
            return await self._reject(approval, original, reviewer_id, note)
        return await self._approve(approval, original, reviewer_id, note)

    # ------------------------------------------------------------------ helpers
    def _derive(self, original: AuditDecision, **kw) -> AuditDecision:
        base = original.model_dump()
        base.update(
            audit_id=f"aud_{uuid.uuid4().hex}",
            created_at=_now_iso(),
            settlement_txn_id=None,
            settlement_rail=None,
        )
        base.update(kw)
        return AuditDecision(**base)

    async def _persist(self, decision: AuditDecision) -> None:
        await self.storage.save_audit(decision)
        # Agent retries with the original idempotency key now observe the human's final decision.
        await self.storage.update_idempotent_decision(
            scoped_idempotency_key(decision.agent_id, decision.idempotency_key), decision
        )

    async def _release_and_finalize(self, approval: dict, status: str, reviewer_id: str, note: str, audit_id=None):
        if approval.get("reservation_id"):
            await self.storage.release_budget_atomic(approval["reservation_id"])
        await self.storage.finalize_approval(
            approval["approval_id"], status=status, reviewer_id=reviewer_id, note=note, decision_audit_id=audit_id
        )

    async def _reject(self, approval: dict, original: AuditDecision, reviewer_id: str, note: str) -> AuditDecision:
        decision = self._derive(
            original,
            verdict="BLOCK",
            layer_decided="HITL_REJECTED",
            executed=False,
            approval_id=approval["approval_id"],
            reason=f"Rejected by {reviewer_id} via HITL (escalated audit {original.audit_id}). "
                   f"Held budget released to ₹0.{(' Note: ' + note) if note else ''}",
        )
        await self._release_and_finalize(approval, "REJECTED", reviewer_id, note, decision.audit_id)
        await self._persist(decision)
        return decision

    async def _approve(self, approval: dict, original: AuditDecision, reviewer_id: str, note: str) -> AuditDecision:
        expected = approval["payload_sha256"]
        payload = json.loads(approval["canonical_payload_json"])
        if not hmac.compare_digest(compute_payload_sha256(payload), expected) or expected != original.payload_sha256:
            await self._fail_integrity(approval, original, reviewer_id)
        decision_audit_id = f"aud_{uuid.uuid4().hex}"
        try:
            settlement = await self.vault.execute(audit_id=decision_audit_id, payload=payload, expected_sha256=expected)
        except SecurityIntegrityError:
            await self._fail_integrity(approval, original, reviewer_id)
        except Exception as exc:
            # Razorpay down / rejected: nothing moved, so the approval goes back to PENDING (budget still held).
            await self.storage.unclaim_approval(approval["approval_id"])
            raise ApprovalSettlementError(
                f"Settlement failed ({getattr(exc, 'code', type(exc).__name__)}): {exc}. Approval left PENDING."
            ) from exc

        # Money has moved: from here on, never un-claim.
        if approval.get("reservation_id"):
            await self.storage.commit_budget_atomic(approval["reservation_id"])
        decision = self._derive(
            original,
            audit_id=decision_audit_id,
            verdict="ALLOW",
            layer_decided="HITL_APPROVED",
            executed=True,
            approval_id=approval["approval_id"],
            settlement_txn_id=settlement.settlement_txn_id,
            settlement_rail=settlement.settlement_rail,
            reason=f"Approved by {reviewer_id} via HITL (escalated audit {original.audit_id}); sealed payload "
                   f"SHA-256 re-verified before settlement.{(' Note: ' + note) if note else ''}",
        )
        await self.storage.finalize_approval(
            approval["approval_id"], status="APPROVED", reviewer_id=reviewer_id, note=note,
            settlement_txn_id=settlement.settlement_txn_id, decision_audit_id=decision.audit_id,
        )
        await self._persist(decision)
        return decision

    async def _fail_integrity(self, approval: dict, original: AuditDecision, reviewer_id: str):
        decision = self._derive(
            original,
            verdict="BLOCK",
            layer_decided="HITL_REJECTED",
            executed=False,
            approval_id=approval["approval_id"],
            risk_score=1.0,
            policy_citations=list(dict.fromkeys(original.policy_citations + ["POL-RBI-AUDIT-5Y"])),
            reason="Anti-TOCTOU integrity failure: stored payload no longer matches its sealed SHA-256. "
                   "Settlement refused, held budget released.",
        )
        await self._release_and_finalize(approval, "INTEGRITY_FAILED", reviewer_id, "payload hash mismatch",
                                         decision.audit_id)
        await self._persist(decision)
        raise ApprovalIntegrityError(decision.reason)
