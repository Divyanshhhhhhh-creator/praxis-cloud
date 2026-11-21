import sys
from pathlib import Path

import httpx
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.adapters.payment_vault import PaymentVault  # noqa: E402
from app.adapters.storage import SQLiteRepository  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

TEST_TOKEN = "praxis-test-token"


class SpyVault(PaymentVault):
    """Real Razorpay vault that also counts outbound settlement attempts (no response mocking)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.calls = 0

    async def execute(self, **kw):
        self.calls += 1
        return await super().execute(**kw)


@pytest.fixture
def storage(tmp_path):
    repo = SQLiteRepository(tmp_path / "praxis_test.db")  # isolated per test; never touches praxis.db
    yield repo
    repo.close()


@pytest.fixture
def vault():
    v = SpyVault()
    if not (v.is_configured and v.is_test_mode):
        pytest.skip("Razorpay Test Mode credentials not configured in root .env")
    return v


def make_app(storage, vault, *, layer2_auditor=None, policy_compiler=None, agent_runner=None):
    """Layer 1 tests run with Layer 2 / ADK disabled (pure deterministic engine); live suites inject them."""
    # reviewer RBAC disabled here on purpose; tests/test_reviewer_auth.py covers the configured-token path
    settings = Settings(praxis_agent_token=TEST_TOKEN, praxis_db_path=storage.db_path, praxis_reviewer_token="")
    return create_app(
        settings=settings, storage=storage, vault=vault, layer2_auditor=layer2_auditor,
        policy_compiler=policy_compiler, agent_runner=agent_runner,
    )


def asgi_client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://praxis.test",
        headers={"X-Agent-Token": TEST_TOKEN}, timeout=120.0,
    )


@pytest.fixture
async def client(storage, vault):
    async with asgi_client(make_app(storage, vault)) as c:
        yield c


@pytest.fixture
def make_client(storage):
    """Factory for a client bound to a custom vault (e.g. an unreachable rail)."""
    return lambda custom_vault: asgi_client(make_app(storage, custom_vault))


# ---------------------------------------------------------------- shared LIVE Gemini fixtures
# Test-only L2 budget for SEMANTIC tests. Free-tier gemini-3.5-flash-lite latency was measured at
# 1.5–14s, so semantic tests verify verdict correctness, not free-tier speed. The production defaults
# (2.5s text / 4.0s multimodal → fail-closed ESCALATE) are pinned by
# test_production_l2_budgets_are_fail_closed_defaults and exercised by the chaos timeout tests.
SEMANTIC_TEST_BUDGET_S = 20.0


@pytest.fixture(scope="session")
def settings():
    s = Settings()
    if not s.gemini_api_key:
        pytest.skip("GEMINI_API_KEY not configured in root .env")
    return s


@pytest.fixture(scope="session")
def genai_client(settings):
    from app.services.gemini_client import get_genai_client

    return get_genai_client(settings.gemini_api_key)


@pytest.fixture(scope="session")
def rag(settings, genai_client):
    from app.services.policy_rag import PolicyRAG

    return PolicyRAG(genai_client, model=settings.embedding_model, cache_path=settings.policy_embeddings_cache_path)


@pytest.fixture(scope="session")
async def auditor(settings, genai_client, rag):
    from app.services.layer2_auditor import GeminiLayer2Auditor

    a = GeminiLayer2Auditor(
        genai_client, rag, model=settings.l2_auditor_model,
        text_timeout_s=SEMANTIC_TEST_BUDGET_S, multimodal_timeout_s=SEMANTIC_TEST_BUDGET_S,
    )
    await a.warmup()  # same warm-up the app lifespan performs at startup (once per session)
    return a
