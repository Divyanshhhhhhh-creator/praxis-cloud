"""App settings loaded from the repo-root `.env`.

Deliberately has NO Razorpay fields and does NOT export `.env` into `os.environ`:
payment credentials are read exclusively by `app/adapters/payment_vault.py`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
ROOT_ENV_FILE = ROOT_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    praxis_agent_token: str = ""
    praxis_db_path: str = str(BACKEND_DIR / "praxis.db")
    gcp_project_id: str = ""
    gcp_region: str = "asia-south1"

    # Storage & audit backends (Slice 6). Local defaults need no GCP credentials.
    storage_backend: Literal["sqlite", "firestore"] = "sqlite"
    audit_backend: Literal["sqlite", "bigquery"] = "sqlite"  # bigquery = primary store + BigQuery mirror
    firestore_database: str = "(default)"
    bigquery_dataset: str = "praxis_audit"
    bigquery_table: str = "audit_decisions"

    # Comma-separated CORS allow-list (env ALLOWED_ORIGINS), e.g. the deployed Cloud Run frontend URL.
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()]

    # Google AI (Slice 2)
    gemini_api_key: str = ""
    layer2_enabled: bool = True
    l2_auditor_model: str = "gemini-3.5-flash-lite"
    l2_text_timeout_s: float = 2.5  # CLAUDE.md invariant 8: >2.5s → fail-closed ESCALATE
    l2_multimodal_timeout_s: float = 4.0
    l2_service_tier: str = ""  # "" = API default; e.g. "priority" (paid tiers, premium billing; benchmark first)
    policy_compiler_model: str = "gemini-3.6-flash"
    policy_compiler_fallback_model: str = "gemini-3.5-flash-lite"
    embedding_model: str = "gemini-embedding-2"
    policy_embeddings_cache_path: str = str(BACKEND_DIR / "policy_embeddings_cache.json")

    # Google ADK agent + HITL (Slice 3)
    agent_model: str = "gemini-3.5-flash-lite"
    praxis_reviewer_token: str = ""  # if set, POST /v1/approvals/{id}/decide requires X-Reviewer-Token
    demo_pdf_dir: str = str(ROOT_DIR / "evals" / "pdfs")

    # Red-team benchmark (Slice 5)
    evals_suite_path: str = str(ROOT_DIR / "evals" / "redteam_suite.py")
    evals_results_path: str = str(ROOT_DIR / "evals" / "latest_benchmark_results.json")


@lru_cache
def get_settings() -> Settings:
    return Settings()
