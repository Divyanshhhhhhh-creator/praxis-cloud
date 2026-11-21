"""Treasury-reviewer RBAC: when PRAXIS_REVIEWER_TOKEN is configured, every mutating governance endpoint
fails closed with 401 unless X-Reviewer-Token matches. Offline: 0 Gemini RPM, 0 Razorpay calls."""

import uuid

import pytest

from app.config import Settings
from app.domain.policy_catalog import default_policy
from app.main import REVIEWER_401_DETAIL, create_app
from tests.conftest import TEST_TOKEN, asgi_client

REVIEWER = "unit-test-reviewer-passcode"


@pytest.fixture
async def guarded(tmp_path, storage, vault):
    settings = Settings(
        _env_file=None, praxis_agent_token=TEST_TOKEN, praxis_reviewer_token=REVIEWER, gemini_api_key="",
        praxis_db_path=storage.db_path, evals_results_path=str(tmp_path / "bench.json"),
    )
    app = create_app(settings=settings, storage=storage, vault=vault, layer2_auditor=None, policy_compiler=None, agent_runner=None)
    async with asgi_client(app) as c:
        yield c


PROTECTED = [
    ("POST", "/v1/approvals/apr_missing/decide", {"decision": "REJECT", "reviewer_id": "probe"}),
    ("POST", "/v1/demo/reset", {}),
    ("POST", "/v1/evals/run", None),
    ("PUT", "/v1/policies/default-fintech-treasury", default_policy().model_dump()),
    ("POST", "/v1/policies/compile", {"instruction": "Cap hourly spend at ₹40,000", "apply": True}),
]


@pytest.mark.parametrize("method,path,body", PROTECTED, ids=[p[1] for p in PROTECTED])
async def test_mutating_endpoints_return_401_without_or_with_wrong_passcode(guarded, method, path, body):
    for headers in ({}, {"X-Reviewer-Token": "wrong-passcode"}):
        r = await guarded.request(method, path, json=body, headers=headers)
        assert r.status_code == 401, (path, headers, r.text)
        assert r.json()["detail"] == REVIEWER_401_DETAIL


async def test_correct_passcode_unlocks_reviewer_actions(guarded, vault):
    ok = {"X-Reviewer-Token": REVIEWER}
    assert (await guarded.put("/v1/policies/default-fintech-treasury", json=default_policy().model_dump(), headers=ok)).status_code == 200
    assert (await guarded.post("/v1/approvals/apr_missing/decide", json={"decision": "REJECT", "reviewer_id": "fm"}, headers=ok)).status_code == 404
    # A real HITL hold can be rejected with the passcode (budget released, no Razorpay call)
    esc = (await guarded.post("/v1/intercept", json={
        "agent_id": "agent-rbac", "idempotency_key": f"k-{uuid.uuid4().hex}", "tool_name": "issue_customer_refund",
        "user_prompt": "Refund ₹8,500", "payload": {"o": 1}, "amount_inr": 8500.0, "merchant_id": "razorpay_refunds",
    })).json()
    assert esc["verdict"] == "ESCALATE"
    no_pass = await guarded.post(f"/v1/approvals/{esc['approval_id']}/decide", json={"decision": "REJECT", "reviewer_id": "fm"})
    assert no_pass.status_code == 401
    d = await guarded.post(f"/v1/approvals/{esc['approval_id']}/decide", json={"decision": "REJECT", "reviewer_id": "fm"}, headers=ok)
    assert d.status_code == 200 and d.json()["layer_decided"] == "HITL_REJECTED"
    assert (await guarded.post("/v1/demo/reset", json={}, headers=ok)).status_code == 200
    assert vault.calls == 0


async def test_read_paths_and_compile_preview_stay_open(guarded):
    for path in ("/health", "/v1/metrics", "/v1/policies", "/v1/audits", "/v1/approvals", "/v1/evals/latest"):
        assert (await guarded.get(path)).status_code == 200, path
    # apply=false previews are never gated (503 here only because no Gemini key is configured offline)
    r = await guarded.post("/v1/policies/compile", json={"instruction": "Cap hourly spend at ₹40,000", "apply": False})
    assert r.status_code == 503
    # the agent path keeps its own X-Agent-Token auth, independent of reviewer RBAC
    assert (await guarded.post("/v1/intercept", json={}, headers={"X-Agent-Token": "bad"})).status_code == 401
