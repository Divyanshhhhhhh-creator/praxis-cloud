"""Slice 1 verification: Layer 1 engine, atomic ledger, RBI guards, vault integrity, live Razorpay Test Mode."""

import asyncio
import uuid

import pytest

from app.adapters.payment_vault import PaymentVault, SecurityIntegrityError
from app.domain.hashing import build_execution_envelope, compute_payload_sha256
from app.domain.policy_catalog import default_policy

LIVE_IDS: list[str] = []


def make_req(**overrides) -> dict:
    body = {
        "agent_id": "fin-ops-agent-01",
        "idempotency_key": f"idem-{uuid.uuid4().hex}",
        "tool_name": "issue_customer_refund",
        "user_prompt": "Refund order #A-1029 for a damaged item.",
        "payload": {"order_ref": "A-1029", "customer_id": "cust_demo_01", "reason": "damaged_item"},
        "amount_inr": 500.0,
        "merchant_id": "razorpay_refunds",
    }
    body.update(overrides)
    return body


async def put_policy(client, **overrides) -> dict:
    policy = default_policy().model_dump()
    policy.update(overrides)
    r = await client.put(f"/v1/policies/{policy['policy_id']}", json=policy)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- pure domain
def test_canonical_hash_is_key_order_invariant():
    a = {"b": 1, "a": {"y": "₹", "x": [1, 2]}}
    b = {"a": {"x": [1, 2], "y": "₹"}, "b": 1}
    assert compute_payload_sha256(a) == compute_payload_sha256(b)
    assert compute_payload_sha256(a) != compute_payload_sha256({**a, "b": 2})


# ---------------------------------------------------------------- 1. live Razorpay
@pytest.mark.live
async def test_live_razorpay_refund_passes_layer1_fast(client, vault):
    r = await client.post("/v1/intercept", json=make_req())
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["verdict"] == "ALLOW" and d["executed"] is True
    assert d["layer_decided"] == "L1_DETERMINISTIC"
    assert d["settlement_rail"] == "razorpay_test_mode"
    assert d["settlement_txn_id"].startswith(("order_", "rfnd_"))
    assert d["l1_latency_ms"] < 10.0, d["l1_latency_ms"]
    assert vault.calls == 1
    LIVE_IDS.append(d["settlement_txn_id"])
    print(f"\n  [LIVE] Razorpay Test Mode ID: {d['settlement_txn_id']}  |  Layer 1 latency: {d['l1_latency_ms']} ms")

    m = (await client.get("/v1/metrics", params={"agent_id": "fin-ops-agent-01"})).json()
    assert m["allowed_count"] == 1 and m["total_inr_settled"] == 500.0
    assert m["window_usage"]["used_1m_inr"] == 500.0 and m["window_usage"]["calls_1m"] == 1


# ---------------------------------------------------------------- 2. idempotency
@pytest.mark.live
async def test_idempotent_replay_returns_identical_decision_without_second_settlement(client, vault):
    body = make_req(idempotency_key="idem-replay-001")
    first = await client.post("/v1/intercept", json=body)
    second = await client.post("/v1/intercept", json=body)
    assert first.status_code == second.status_code == 200
    a, b = first.json(), second.json()
    assert a["audit_id"] == b["audit_id"]
    assert a["settlement_txn_id"] == b["settlement_txn_id"] and a["settlement_txn_id"].startswith(("order_", "rfnd_"))
    assert first.headers["X-Praxis-Idempotent-Replay"] == "false"
    assert second.headers["X-Praxis-Idempotent-Replay"] == "true"
    assert vault.calls == 1, "Razorpay must be hit exactly once"
    print(f"\n  [IDEMPOTENCY] replayed {a['audit_id']} -> {a['settlement_txn_id']} (vault calls={vault.calls})")

    # Same key, tampered payload → 409, still no new settlement
    tampered = await client.post("/v1/intercept", json={**body, "amount_inr": 4999.0})
    assert tampered.status_code == 409
    assert vault.calls == 1


# ---------------------------------------------------------------- 3. velocity
@pytest.mark.live
async def test_velocity_circuit_breaker_blocks_fourth_call(client, vault):
    verdicts = []
    for _ in range(4):
        r = await client.post("/v1/intercept", json=make_req(amount_inr=100.0))
        verdicts.append(r.json())
    assert [d["verdict"] for d in verdicts] == ["ALLOW", "ALLOW", "ALLOW", "BLOCK"]
    assert "POL-FIN-VELOCITY" in verdicts[3]["policy_citations"]
    assert verdicts[3]["executed"] is False and verdicts[3]["settlement_txn_id"] is None
    assert vault.calls == 3


# ---------------------------------------------------------------- 4. concurrency
@pytest.mark.live
async def test_concurrent_micro_slicing_cannot_race_the_window(client, vault):
    await put_policy(client, max_calls_per_min=20)
    results = await asyncio.gather(
        *[client.post("/v1/intercept", json=make_req(amount_inr=4000.0, tool_name="pay_vendor_invoice",
                                                     merchant_id="acme_supplies")) for _ in range(10)]
    )
    decisions = [r.json() for r in results]
    allowed = [d for d in decisions if d["verdict"] == "ALLOW"]
    blocked = [d for d in decisions if d["verdict"] == "BLOCK"]
    assert len(allowed) <= 3 and sum(d["amount_inr"] for d in allowed) <= 15000.0
    assert len(allowed) == 3 and len(blocked) == 7
    assert all(d["executed"] and d["settlement_txn_id"].startswith("order_") for d in allowed)
    assert all("POL-FIN-SLIDING-CAP" in d["policy_citations"] for d in blocked)
    assert vault.calls == 3
    m = (await client.get("/v1/metrics", params={"agent_id": "fin-ops-agent-01"})).json()
    assert m["window_usage"]["used_1m_inr"] == 12000.0
    print(f"\n  [CONCURRENCY] 10 parallel x ₹4,000 → {len(allowed)} ALLOW (₹12,000), {len(blocked)} BLOCK")


async def test_ledger_reservation_is_atomic_under_thread_contention(storage):
    policy = default_policy().model_copy(update={"max_calls_per_min": 1000})
    outcomes = await asyncio.gather(
        *[storage.reserve_budget_atomic("agent-x", policy, 4000.0) for _ in range(50)]
    )
    assert sum(o.ok for o in outcomes) == 3  # 3 × ₹4,000 = ₹12,000 ≤ ₹15,000


# ---------------------------------------------------------------- 5. RBI guards + Annex-1
async def test_rbi_cooling_guard_and_pa_refund_rule_block_and_report(client, vault):
    r1 = await client.post("/v1/intercept", json=make_req(contact_changed_hours_ago=2.0))
    d1 = r1.json()
    assert d1["verdict"] == "BLOCK" and d1["policy_citations"] == ["POL-RBI-COOLING-12H"]
    assert "RBI/DPSS/2026-27/475" in d1["reason"]

    r2 = await client.post("/v1/intercept", json=make_req(destination_mode="alternate_account"))
    d2 = r2.json()
    assert d2["verdict"] == "BLOCK" and d2["policy_citations"] == ["POL-RBI-PA-REFUND-01"]

    # 13h since contact change → outside cooling period → passes the guard (not blocked by it)
    ok = await client.post("/v1/intercept", json=make_req(contact_changed_hours_ago=13.0, amount_inr=1.0))
    assert "POL-RBI-COOLING-12H" not in ok.json()["policy_citations"]
    assert vault.calls == 1  # only the compliant call reached Razorpay

    rep = await client.get(f"/v1/audits/{d1['audit_id']}/rbi-incident-report")
    assert rep.status_code == 200
    report = rep.json()
    assert report["regulatory_framework"]["primary_circular"] == "RBI/DPSS/2026-27/475"
    assert report["regulatory_framework"]["cert_in_reporting_window_hours"] == 6
    assert report["integrity"]["payload_sha256"] == d1["payload_sha256"]
    assert report["policy_citations"][0] == {"policy_id": "POL-RBI-COOLING-12H",
                                             "regulatory_reference": "RBI/DPSS/2026-27/475"}
    assert report["incident_classification"]["severity"] == "HIGH"
    assert report["financial_impact"]["amount_lost_inr"] == 0.0
    assert len(report["timeline"]) >= 4

    # ALLOWed audits are not reportable incidents
    assert (await client.get(f"/v1/audits/{ok.json()['audit_id']}/rbi-incident-report")).status_code == 409
    audits = (await client.get("/v1/audits")).json()
    assert [a["audit_id"] for a in audits] == [ok.json()["audit_id"], d2["audit_id"], d1["audit_id"]]


# ---------------------------------------------------------------- 6. allowlist + shadow
@pytest.mark.live
async def test_unapproved_merchant_blocks_in_enforce_and_flags_in_shadow(client, vault):
    r = await client.post("/v1/intercept", json=make_req(merchant_id="shady_offshore_ltd"))
    d = r.json()
    assert d["verdict"] == "BLOCK" and d["policy_citations"] == ["POL-FIN-ALLOWLIST"] and d["executed"] is False
    m = (await client.get("/v1/metrics", params={"agent_id": "fin-ops-agent-01"})).json()
    assert m["window_usage"]["used_1m_inr"] == 0.0 and m["window_usage"]["calls_1m"] == 0  # leaked ₹0
    assert m["total_inr_protected"] == 500.0
    assert vault.calls == 0

    await put_policy(client, mode="shadow")
    s = (await client.post("/v1/intercept", json=make_req(merchant_id="shady_offshore_ltd"))).json()
    assert s["verdict"] == "SHADOW_FLAG" and "POL-FIN-ALLOWLIST" in s["policy_citations"]
    assert s["executed"] is True and s["settlement_txn_id"].startswith("order_")
    assert vault.calls == 1
    print(f"\n  [SHADOW] flagged + settled live: {s['settlement_txn_id']}")


# ---------------------------------------------------------------- 7. TOCTOU + fail-closed
async def test_vault_refuses_mismatched_hash_before_any_network_io():
    # Unresolvable host: if the vault attempted I/O we'd get SettlementError, not SecurityIntegrityError.
    v = PaymentVault(base_url="https://razorpay-toctou.invalid/v1")
    envelope = build_execution_envelope(tool_name="pay_vendor_invoice", merchant_id="acme_supplies",
                                        amount_inr=500.0, destination_mode="original_source", payload={"inv": "INV-9"})
    sealed = compute_payload_sha256(envelope)
    with pytest.raises(SecurityIntegrityError):
        await v.execute(audit_id="aud_toctou", payload=envelope, expected_sha256="0" * 64)
    envelope["amount_paise"] = 9_999_900  # attacker swaps amount after verification
    with pytest.raises(SecurityIntegrityError):
        await v.execute(audit_id="aud_toctou", payload=envelope, expected_sha256=sealed)


async def test_settlement_failure_fails_closed_and_releases_budget(make_client):
    async with make_client(PaymentVault(base_url="https://razorpay-down.invalid/v1")) as c:
        d = (await c.post("/v1/intercept", json=make_req())).json()
        assert d["verdict"] == "BLOCK" and d["executed"] is False
        assert "POL-FIN-FAIL-CLOSED" in d["policy_citations"]
        m = (await c.get("/v1/metrics")).json()
        assert m["window_usage"]["used_1m_inr"] == 0.0 and m["window_usage"]["calls_1m"] == 0


# ---------------------------------------------------------------- API hygiene
async def test_intercept_requires_agent_token_and_reset_preserves_policies(client):
    assert (await client.post("/v1/intercept", json=make_req(), headers={"X-Agent-Token": "wrong"})).status_code == 401
    await client.post("/v1/intercept", json=make_req(merchant_id="nope"))
    reset = (await client.post("/v1/demo/reset")).json()
    assert reset["audits"] == 1 and reset["policies_preserved"] is True
    assert (await client.get("/v1/audits")).json() == []
    assert [p["policy_id"] for p in (await client.get("/v1/policies")).json()] == ["default-fintech-treasury"]
    assert (await client.get("/health")).json()["payment_vault"]["test_mode"] is True
