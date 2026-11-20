"""Slice 6 offline tests: backend factories, CORS env parsing, BigQuery fail-soft sink, /health contract.
No GCP credentials, Gemini or Razorpay calls required."""

import uuid

import pytest

from app.adapters.bigquery_audit import AuditMirroringStorage, BigQueryAuditSink, decision_to_row
from app.adapters.storage import SQLiteRepository
from app.config import Settings
from app.main import build_audit_sink, build_storage, create_app
from tests.conftest import TEST_TOKEN, asgi_client


def offline(tmp_path, **kw) -> Settings:
    return Settings(_env_file=None, praxis_agent_token=TEST_TOKEN, gemini_api_key="", praxis_db_path=str(tmp_path / "p.db"), **kw)


def test_local_defaults_are_sqlite_without_gcp(tmp_path):
    s = offline(tmp_path)
    assert (s.storage_backend, s.audit_backend) == ("sqlite", "sqlite")
    repo = build_storage(s)
    assert isinstance(repo, SQLiteRepository)
    repo.close()
    assert build_audit_sink(s) is None
    # production invariants untouched
    assert (s.l2_text_timeout_s, s.l2_multimodal_timeout_s) == (2.5, 4.0)


def test_allowed_origins_env_is_comma_separated(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://praxis-frontend-abc-el.a.run.app/, http://localhost:3000")
    s = Settings(_env_file=None)
    assert s.cors_origins == ["https://praxis-frontend-abc-el.a.run.app", "http://localhost:3000"]


class _ExplodingClient:
    project = "praxis-test"

    def create_dataset(self, *a, **k):
        raise PermissionError("bigquery.datasets.create denied")

    def insert_rows_json(self, *a, **k):
        raise PermissionError("denied")


class _RecordingClient:
    project = "praxis-test"

    def __init__(self):
        self.rows = []

    def create_dataset(self, *a, **k):
        return None

    def create_table(self, *a, **k):
        return None

    def insert_rows_json(self, table, rows, row_ids=None):
        self.rows.extend(rows)
        return []


async def _escalate(client):
    return (await client.post("/v1/intercept", json={
        "agent_id": "agent-bq", "idempotency_key": f"k-{uuid.uuid4().hex}", "tool_name": "issue_customer_refund",
        "user_prompt": "Refund ₹8,500", "payload": {"o": 1}, "amount_inr": 8500.0, "merchant_id": "razorpay_refunds",
    })).json()


async def test_bigquery_sink_failure_never_breaks_payment_path(tmp_path, vault):
    sink = BigQueryAuditSink(project="praxis-test", client=_ExplodingClient())
    await sink.start()
    assert sink.enabled is False and "denied" in sink.last_error
    storage = AuditMirroringStorage(SQLiteRepository(tmp_path / "a.db"), sink)
    app = create_app(settings=offline(tmp_path), storage=storage, vault=vault, layer2_auditor=None, policy_compiler=None, agent_runner=None)
    async with asgi_client(app) as c:
        d = await _escalate(c)
    assert d["verdict"] == "ESCALATE"  # decision still made and persisted to the primary store
    assert (await storage.get_audit(d["audit_id"])) is not None
    storage.close()


async def test_bigquery_sink_mirrors_every_audit_non_blocking(tmp_path, vault):
    client = _RecordingClient()
    sink = BigQueryAuditSink(project="praxis-test", client=client)
    await sink.start()
    assert sink.enabled and sink.table_id == "praxis-test.praxis_audit.audit_decisions"
    storage = AuditMirroringStorage(SQLiteRepository(tmp_path / "b.db"), sink)
    app = create_app(settings=offline(tmp_path), storage=storage, vault=vault, layer2_auditor=None, policy_compiler=None, agent_runner=None)
    async with asgi_client(app) as c:
        d = await _escalate(c)
    await sink.drain()
    assert sink.written == 1 and client.rows[0]["audit_id"] == d["audit_id"]
    assert client.rows[0]["policy_citations"] == d["policy_citations"] and client.rows[0]["ingested_at"]
    storage.close()


def test_decision_row_matches_schema():
    from app.adapters.bigquery_audit import SCHEMA

    names = [n for n, _, _ in SCHEMA]
    assert names[0] == "audit_id" and "payload_sha256" in names and "policy_citations" in names
    assert decision_to_row.__name__


async def test_health_reports_backends_models_and_no_secrets(tmp_path, storage, vault):
    app = create_app(settings=offline(tmp_path), storage=storage, vault=vault, layer2_auditor=None, policy_compiler=None, agent_runner=None)
    async with asgi_client(app) as c:
        h = (await c.get("/health")).json()
    assert h["storage_backend"] == "sqlite" and h["audit_backend"] == "sqlite" and h["gcp_region"] == "asia-south1"
    assert h["models"] == {
        "l2_auditor": "gemini-3.5-flash-lite", "policy_compiler": "gemini-3.6-flash",
        "policy_compiler_fallback": "gemini-3.5-flash-lite", "embedding": "gemini-embedding-2", "adk_agent": "gemini-3.5-flash-lite",
    }
    assert isinstance(h["razorpay_configured"], bool)
    blob = str(h)
    assert "rzp_" not in blob and TEST_TOKEN not in blob and "secret" not in blob.lower()


@pytest.mark.parametrize("bad", ["postgres", "FIRESTORE"])
def test_unknown_storage_backend_is_rejected(bad):
    with pytest.raises(Exception):
        Settings(_env_file=None, storage_backend=bad)
