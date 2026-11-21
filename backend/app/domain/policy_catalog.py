"""Stable policy citation codes, regulatory references and the seeded default policy."""

from __future__ import annotations

from .models import PolicyConfig

DEFAULT_POLICY_ID = "default-fintech-treasury"

# Policy citation codes
POL_ALLOWLIST = "POL-FIN-ALLOWLIST"
POL_RBI_COOLING = "POL-RBI-COOLING-12H"
POL_RBI_PA_REFUND = "POL-RBI-PA-REFUND-01"
POL_MAX_TXN = "POL-FIN-MAX-TXN"
POL_VELOCITY = "POL-FIN-VELOCITY"
POL_SLIDING_CAP = "POL-FIN-SLIDING-CAP"
POL_POLICY_NOT_FOUND = "POL-FIN-POLICY-NOT-FOUND"
POL_FAIL_CLOSED = "POL-FIN-FAIL-CLOSED"

# Regulatory circular references
RBI_CYBER_RESILIENCE_CIRCULAR = "RBI/DPSS/2026-27/475"  # 5 Nov 2026 – 12h contact-change cooling
RBI_PA_MASTER_DIRECTION = "RBI/DPSS/2025-26/141"  # PA Master Direction (refund-to-source; issued 15 Sep 2025, updated 11 Nov 2026)

POLICY_REFERENCES: dict[str, str] = {
    POL_RBI_COOLING: RBI_CYBER_RESILIENCE_CIRCULAR,
    POL_RBI_PA_REFUND: RBI_PA_MASTER_DIRECTION,
}


def default_policy() -> PolicyConfig:
    return PolicyConfig(
        policy_id=DEFAULT_POLICY_ID,
        name="Default FinTech Treasury Policy",
        mode="enforce",
        allowed_tools=["issue_customer_refund", "pay_vendor_invoice"],
        allowed_merchants=["razorpay_refunds", "razorpay_payouts", "acme_supplies", "cloud_infra_gcp"],
    )
