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


def _make_app(storage, vault):
    settings = Settings(praxis_agent_token=TEST_TOKEN, praxis_db_path=storage.db_path)
    return create_app(settings=settings, storage=storage, vault=vault)


@pytest.fixture
async def client(storage, vault):
    app = _make_app(storage, vault)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://praxis.test",
        headers={"X-Agent-Token": TEST_TOKEN}, timeout=30.0,
    ) as c:
        yield c


@pytest.fixture
def make_client(storage):
    """Factory for a client bound to a custom vault (e.g. an unreachable rail)."""

    def _factory(custom_vault):
        app = _make_app(storage, custom_vault)
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://praxis.test",
            headers={"X-Agent-Token": TEST_TOKEN}, timeout=30.0,
        )

    return _factory
