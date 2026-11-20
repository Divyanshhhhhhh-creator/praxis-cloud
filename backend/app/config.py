"""App settings loaded from the repo-root `.env`.

Deliberately has NO Razorpay fields and does NOT export `.env` into `os.environ`:
payment credentials are read exclusively by `app/adapters/payment_vault.py`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
ROOT_ENV_FILE = ROOT_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    praxis_agent_token: str = ""
    praxis_db_path: str = str(BACKEND_DIR / "praxis.db")
    storage_backend: str = "sqlite"
    gcp_project_id: str = ""
    gcp_region: str = "asia-south1"
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
