"""Slice 5 offline tests (0 Gemini RPM, 0 Razorpay calls): eval endpoints, approval enrichment,
dry-run vault integrity, and the deterministic half of the red-team suite."""

import importlib.util
import json
import sys
import uuid
from pathlib import Path

import pytest

from app.config import ROOT_DIR, Settings
from app.adapters.payment_vault import SecurityIntegrityError
from app.domain.hashing import build_execution_envelope, compute_payload_sha256
from app.main import create_app
from tests.conftest import TEST_TOKEN, asgi_client

SUITE_PATH = ROOT_DIR / "evals" / "redteam_suite.py"


def load_suite():
    spec = importlib.util.spec_from_file_location("praxis_redteam_suite_test", SUITE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def offline_settings(tmp_path: Path, **kw) -> Settings:
    return Settings(
        _env_file=None, praxis_agent_token=TEST_TOKEN, gemini_api_key="",
        praxis_db_path=str(tmp_path / "praxis.db"), evals_results_path=str(tmp_path / "bench.json"), **kw,
    )


async def test_latest_eval_reports_not_run_then_returns_saved_file(tmp_path, storage, vault):
    settings = offline_settings(tmp_path)
    app = create_app(settings=settings, storage=storage, vault=vault, layer2_auditor=None, policy_compiler=None, agent_runner=None)
    async with asgi_client(app) as c:
        assert (await c.get("/v1/evals/latest")).json() == {"status": "not_run_yet"}
        Path(settings.evals_results_path).write_text(json.dumps({"run_id": "bench_x", "passed_cases": 12}))
        assert (await c.get("/v1/evals/latest")).json()["run_id"] == "bench_x"


async def test_approvals_are_enriched_with_escalation_audit(tmp_path, storage, vault):
    app = create_app(settings=offline_settings(tmp_path), storage=storage, vault=vault, layer2_auditor=None,
                     policy_compiler=None, agent_runner=None)
    async with asgi_client(app) as c:
        d = (await c.post("/v1/intercept", json={
            "agent_id": "agent-x", "idempotency_key": f"k-{uuid.uuid4().hex}", "tool_name": "issue_customer_refund",
            "user_prompt": "Refund ₹8,500 for order C-1", "payload": {"order": "C-1"}, "amount_inr": 8500.0,
            "merchant_id": "razorpay_refunds",
        })).json()
        assert d["verdict"] == "ESCALATE"
        [row] = (await c.get("/v1/approvals", params={"status": "PENDING"})).json()
        esc = row["escalation"]
        assert esc["agent_id"] == "agent-x" and esc["merchant_id"] == "razorpay_refunds"
        assert "POL-FIN-HITL-THRESHOLD" in esc["policy_citations"] and esc["reason"]
    assert vault.calls == 0


async def test_dry_run_vault_enforces_anti_toctou_and_never_calls_razorpay():
    suite = load_suite()
    v = suite.DryRunVault()
    env = build_execution_envelope(tool_name="pay_vendor_invoice", merchant_id="acme_supplies", amount_inr=480,
                                   destination_mode="original_source", payload={"i": 1})
    sha = compute_payload_sha256(env)
    res = await v.execute(audit_id="aud_t", payload=env, expected_sha256=sha)
    assert res.settlement_txn_id.startswith("dryrun_") and res.settlement_rail == "dry_run_benchmark"
    with pytest.raises(SecurityIntegrityError):
        await v.execute(audit_id="aud_t", payload={**env, "amount_paise": 4800000}, expected_sha256=sha)


async def test_suite_deterministic_cases_pass_offline_and_skip_gemini_cases(tmp_path):
    suite = load_suite()
    report = await suite.run_benchmark(offline_settings(tmp_path), results_path=tmp_path / "bench.json")
    by_id = {c["case_id"]: c for c in report["cases"]}
    for cid in ("RT-01", "RT-02", "RT-03", "RT-04", "RT-05", "RT-07"):
        assert by_id[cid]["passed"], by_id[cid]
    assert by_id["RT-05"]["policy_citations"] == ["POL-FIN-VELOCITY"]
    assert by_id["RT-07"]["actual_verdict"] == "SHADOW_FLAG" and by_id["RT-07"]["settlement_rail"] == "dry_run_benchmark"
    assert all(by_id[c]["actual_verdict"] == "SKIPPED" for c in ("RT-06", "RT-08", "RT-09", "RT-10", "RT-11", "RT-12"))
    assert report["zero_money_leaked"] is True and report["total_cases"] == 12
    assert json.loads((tmp_path / "bench.json").read_text())["run_id"] == report["run_id"]
