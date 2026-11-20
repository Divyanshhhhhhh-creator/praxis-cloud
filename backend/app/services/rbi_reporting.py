"""RBI Annex-1 / CERT-In 6-hour cyber incident report builder for blocked threats."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..domain.models import AuditDecision
from ..domain.policy_catalog import (
    POL_ALLOWLIST,
    POL_MAX_TXN,
    POL_RBI_COOLING,
    POL_RBI_PA_REFUND,
    POL_SLIDING_CAP,
    POL_VELOCITY,
    POLICY_REFERENCES,
    RBI_CYBER_RESILIENCE_CIRCULAR,
    RBI_PA_MASTER_DIRECTION,
)

REPORTING_WINDOW_HOURS = 6

_CATEGORY = {
    POL_RBI_COOLING: ("Account takeover indicator – payout after recent beneficiary contact change", "HIGH"),
    POL_RBI_PA_REFUND: ("Refund diversion attempt – refund to non-original payment source", "HIGH"),
    POL_ALLOWLIST: ("Unauthorised tool / counterparty invocation by autonomous agent", "MEDIUM"),
    POL_VELOCITY: ("Anomalous transaction velocity – possible automated drain", "MEDIUM"),
    POL_SLIDING_CAP: ("Cumulative spend limit breach – possible micro-slicing", "MEDIUM"),
    POL_MAX_TXN: ("Single-transaction limit breach", "MEDIUM"),
}
_SEVERITY_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


class NotReportableError(Exception):
    pass


def build_rbi_incident_report(decision: AuditDecision, *, gcp_region: str = "asia-south1") -> dict:
    if decision.verdict == "ALLOW":
        raise NotReportableError("Audit was ALLOWed; no cyber incident to report.")

    detected_at = datetime.fromisoformat(decision.created_at)
    generated_at = datetime.now(timezone.utc)
    deadline = detected_at + timedelta(hours=REPORTING_WINDOW_HOURS)

    categories, severity = [], "LOW"
    for code in decision.policy_citations:
        if code in _CATEGORY:
            label, sev = _CATEGORY[code]
            categories.append(label)
            if _SEVERITY_RANK[sev] > _SEVERITY_RANK[severity]:
                severity = sev
    if not categories:
        categories.append("Policy violation by autonomous agent")

    contained = not decision.executed
    return {
        "report_type": "RBI Annex-1 Cyber Incident Report (CERT-In 6-hour reporting readiness)",
        "schema_version": "praxis.rbi.annex1.v1",
        "incident_id": f"PRX-INC-{decision.audit_id.removeprefix('aud_')[:12].upper()}",
        "generated_at": generated_at.isoformat(),
        "regulatory_framework": {
            "primary_circular": RBI_CYBER_RESILIENCE_CIRCULAR,
            "primary_circular_title": "RBI Cyber Resilience & Digital Payment Security Controls (5 Nov 2026)",
            "related_circulars": [RBI_PA_MASTER_DIRECTION],
            "cert_in_reporting_window_hours": REPORTING_WINDOW_HOURS,
            "reporting_deadline_utc": deadline.isoformat(),
            "within_reporting_window": generated_at <= deadline,
        },
        "reporting_entity": {
            "system": "Praxis AI Agent Governance Firewall",
            "environment": "razorpay_test_mode",
            "data_residency_region": gcp_region,
        },
        "incident_classification": {
            "categories": categories,
            "severity": severity,
            "verdict": decision.verdict,
            "detection_layer": decision.layer_decided,
            "risk_score": decision.risk_score,
            "status": "CONTAINED – blocked pre-settlement" if contained else "EXECUTED – flagged post-settlement",
        },
        "policy_citations": [
            {"policy_id": code, "regulatory_reference": POLICY_REFERENCES.get(code)}
            for code in decision.policy_citations
        ],
        "transaction": {
            "audit_id": decision.audit_id,
            "idempotency_key": decision.idempotency_key,
            "agent_id": decision.agent_id,
            "policy_id": decision.policy_id,
            "tool_name": decision.tool_name,
            "merchant_id": decision.merchant_id,
            "amount_inr": decision.amount_inr,
            "currency": "INR",
            "executed": decision.executed,
            "settlement_txn_id": decision.settlement_txn_id,
            "settlement_rail": decision.settlement_rail,
        },
        "financial_impact": {
            "amount_at_risk_inr": decision.amount_inr,
            "amount_lost_inr": 0.0 if contained else decision.amount_inr,
        },
        "integrity": {
            "payload_sha256": decision.payload_sha256,
            "hash_algorithm": "SHA-256 over canonical JSON (sorted keys, compact separators, UTF-8)",
        },
        "description": decision.reason,
        "timeline": [
            {"timestamp": decision.created_at, "event": "Agent tool call intercepted by Praxis proxy; payload sealed (SHA-256)."},
            {
                "timestamp": decision.created_at,
                "event": f"{decision.layer_decided} returned {decision.verdict}: {', '.join(decision.policy_citations) or 'n/a'}.",
            },
            {
                "timestamp": decision.created_at,
                "event": "Settlement suppressed; zero funds moved; reserved budget released."
                if contained
                else f"Settlement executed ({decision.settlement_txn_id}) under shadow mode.",
            },
            {"timestamp": generated_at.isoformat(), "event": "RBI Annex-1 incident report generated."},
            {"timestamp": deadline.isoformat(), "event": "CERT-In / RBI 6-hour reporting deadline."},
        ],
    }
