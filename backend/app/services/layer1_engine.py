"""Layer 1 — Deterministic Treasury Engine.

Ordered, short-circuiting checks (enforce mode) — cheapest first, ledger last:
  1. Tool + merchant allowlists                           POL-FIN-ALLOWLIST
  2. RBI 5 Nov 2026 12h contact-change cooling guard     POL-RBI-COOLING-12H  (RBI/DPSS/2026-27/475)
  3. RBI PA refund-to-original-source rule               POL-RBI-PA-REFUND-01 (RBI/DPSS/2025-26/141)
  4. Hard single-transaction cap                         POL-FIN-MAX-TXN
  5. Atomic velocity + 1m/1h/24h sliding reservation     POL-FIN-VELOCITY / POL-FIN-SLIDING-CAP

In shadow mode every check runs, violations are collected but nothing is blocked.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from ..adapters.storage import StorageRepository
from ..domain.models import InterceptRequest, PolicyConfig, WindowUsage
from ..domain.policy_catalog import (
    POL_ALLOWLIST,
    POL_MAX_TXN,
    POL_RBI_COOLING,
    POL_RBI_PA_REFUND,
    RBI_CYBER_RESILIENCE_CIRCULAR,
    RBI_PA_MASTER_DIRECTION,
)


@dataclass
class L1Violation:
    code: str
    reason: str


@dataclass
class Layer1Result:
    violations: list[L1Violation] = field(default_factory=list)
    reservation_id: Optional[str] = None
    latency_ms: float = 0.0
    requires_deep_audit: bool = False
    window_usage: Optional[WindowUsage] = None

    @property
    def passed(self) -> bool:
        return not self.violations

    @property
    def citations(self) -> list[str]:
        return list(dict.fromkeys(v.code for v in self.violations))

    @property
    def reason(self) -> str:
        if self.passed:
            return "Layer 1 deterministic checks passed; budget atomically reserved."
        return " | ".join(v.reason for v in self.violations)


class Layer1Engine:
    def __init__(self, storage: StorageRepository):
        self.storage = storage

    async def evaluate(self, req: InterceptRequest, policy: PolicyConfig) -> Layer1Result:
        t0 = time.perf_counter()
        enforce = policy.mode == "enforce"
        result = Layer1Result(requires_deep_audit=req.amount_inr > policy.auto_approve_threshold_inr)

        def finish() -> Layer1Result:
            result.latency_ms = round((time.perf_counter() - t0) * 1000, 3)
            return result

        def flag(code: str, reason: str) -> bool:
            """Record a violation; returns True when evaluation must stop (enforce mode)."""
            result.violations.append(L1Violation(code, reason))
            return enforce

        # 1. Allowlists
        if req.tool_name not in policy.allowed_tools:
            if flag(POL_ALLOWLIST, f"Tool '{req.tool_name}' is not on the policy tool allowlist."):
                return finish()
        if req.merchant_id not in policy.allowed_merchants:
            if flag(POL_ALLOWLIST, f"Merchant '{req.merchant_id}' is not on the policy merchant allowlist."):
                return finish()

        # 2. RBI 5 Nov 2026 cyber-resilience cooling guard
        if (
            req.contact_changed_hours_ago is not None
            and req.contact_changed_hours_ago < policy.rbi_cooling_period_hours
        ):
            if flag(
                POL_RBI_COOLING,
                f"Beneficiary contact changed {req.contact_changed_hours_ago:g}h ago, inside the "
                f"{policy.rbi_cooling_period_hours:g}h mandatory cooling period ({RBI_CYBER_RESILIENCE_CIRCULAR}).",
            ):
                return finish()

        # 3. RBI PA Master Direction: refunds only to original payment source
        if (
            policy.enforce_original_source_refund
            and req.tool_name == "issue_customer_refund"
            and req.destination_mode != "original_source"
        ):
            if flag(
                POL_RBI_PA_REFUND,
                f"Refund destination '{req.destination_mode}' violates refund-to-original-source rule "
                f"({RBI_PA_MASTER_DIRECTION}, updated 11 Nov 2026).",
            ):
                return finish()

        # 4. Hard single-transaction cap
        if req.amount_inr > policy.max_single_txn_inr:
            if flag(
                POL_MAX_TXN,
                f"Amount ₹{req.amount_inr:,.2f} exceeds single-transaction cap ₹{policy.max_single_txn_inr:,.2f}.",
            ):
                return finish()

        # 5. Atomic velocity + sliding-window reservation (last: the only check that writes)
        outcome = await self.storage.reserve_budget_atomic(req.agent_id, policy, req.amount_inr, enforce=enforce)
        result.reservation_id = outcome.reservation_id
        result.window_usage = outcome.usage_before
        for v in outcome.violations:
            result.violations.append(L1Violation(v.code, v.reason))
        return finish()
