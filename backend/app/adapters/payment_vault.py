"""Vaulted Razorpay Test Mode adapter.

This is the ONLY module in Praxis permitted to read RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET
and RAZORPAY_DEMO_PAYMENT_ID. Credentials come from the process environment (Secret
Manager-injected on Cloud Run) or, locally, directly from the repo-root `.env` file —
they are never exported into `os.environ` by the rest of the app, so the ADK agent
process cannot see them.
"""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
from dotenv import dotenv_values

from ..domain.hashing import compute_payload_sha256

RAZORPAY_API_BASE = "https://api.razorpay.com/v1"
SETTLEMENT_RAIL = "razorpay_test_mode"
_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"
_MIN_PAISE = 100


class SecurityIntegrityError(Exception):
    """Payload presented for execution does not match the verified SHA-256 seal (TOCTOU)."""


class SettlementError(Exception):
    """Razorpay rejected the call or was unreachable. The proxy must roll back the reservation."""

    def __init__(self, code: str, description: str, *, http_status: Optional[int] = None):
        super().__init__(f"{code}: {description}")
        self.code = code
        self.description = description
        self.http_status = http_status


@dataclass(frozen=True)
class SettlementResult:
    settlement_txn_id: str
    settlement_rail: str
    amount_paise: int
    endpoint: str
    status: Optional[str]


def _read_vault_secret(name: str) -> str:
    value = os.environ.get(name)
    if value is None and _ROOT_ENV.exists():
        value = dotenv_values(_ROOT_ENV).get(name)
    return (value or "").strip()


class PaymentVault:
    def __init__(self, *, base_url: str = RAZORPAY_API_BASE, timeout: float = 10.0):
        self._key_id = _read_vault_secret("RAZORPAY_KEY_ID")
        self._key_secret = _read_vault_secret("RAZORPAY_KEY_SECRET")
        self._demo_payment_id = _read_vault_secret("RAZORPAY_DEMO_PAYMENT_ID")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def __repr__(self) -> str:  # never leak secrets into logs / tracebacks
        return f"PaymentVault(configured={self.is_configured}, test_mode={self.is_test_mode})"

    @property
    def is_configured(self) -> bool:
        return bool(self._key_id and self._key_secret)

    @property
    def is_test_mode(self) -> bool:
        return self._key_id.startswith("rzp_test_")

    async def execute(self, *, audit_id: str, payload: dict, expected_sha256: str) -> SettlementResult:
        """Settle the exact sealed execution envelope on Razorpay Test Mode."""
        # 1. Anti-TOCTOU: re-hash what we are about to execute BEFORE any outbound I/O.
        actual = compute_payload_sha256(payload)
        if not hmac.compare_digest(actual, expected_sha256 or ""):
            raise SecurityIntegrityError(
                f"Payload hash mismatch: expected {str(expected_sha256)[:16]}…, got {actual[:16]}…. Execution refused."
            )
        if not self.is_configured:
            raise SettlementError("VAULT_NOT_CONFIGURED", "Razorpay credentials are not available to the vault.")
        if not self.is_test_mode:
            raise SettlementError("VAULT_LIVE_KEY_REFUSED", "Praxis Slice 1 only settles on Razorpay Test Mode keys.")

        tool_name = str(payload["tool_name"])
        merchant_id = str(payload["merchant_id"])
        paise = max(_MIN_PAISE, int(payload["amount_paise"]))
        notes = {
            "praxis_audit_id": audit_id,
            "tool": tool_name,
            "merchant_id": merchant_id,
            "payload_sha256": expected_sha256[:32],
        }

        if tool_name == "issue_customer_refund" and self._demo_payment_id:
            endpoint = f"/payments/{self._demo_payment_id}/refund"
            body = {"amount": paise, "speed": "normal", "receipt": f"prx_{audit_id[:16]}", "notes": notes}
            expected_prefix = "rfnd_"
        else:
            endpoint = "/orders"
            body = {"amount": paise, "currency": "INR", "receipt": f"prx_{audit_id[:16]}", "notes": notes}
            expected_prefix = "order_"

        try:
            async with httpx.AsyncClient(timeout=self._timeout, auth=(self._key_id, self._key_secret)) as client:
                resp = await client.post(f"{self._base_url}{endpoint}", json=body)
        except httpx.HTTPError as exc:
            raise SettlementError("RAZORPAY_UNREACHABLE", f"{type(exc).__name__}: {exc}") from exc

        if not resp.is_success:
            code, desc = "RAZORPAY_HTTP_ERROR", resp.text[:300]
            try:
                err = resp.json().get("error", {})
                code = err.get("code") or code
                desc = err.get("description") or desc
            except ValueError:
                pass
            raise SettlementError(code, desc, http_status=resp.status_code)

        data = resp.json()
        txn_id = str(data.get("id", ""))
        if not txn_id.startswith(expected_prefix):
            raise SettlementError("RAZORPAY_UNEXPECTED_RESPONSE", f"Expected {expected_prefix}… id, got {txn_id!r}")
        return SettlementResult(
            settlement_txn_id=txn_id,
            settlement_rail=SETTLEMENT_RAIL,
            amount_paise=int(data.get("amount", paise)),
            endpoint=f"POST /v1{endpoint}",
            status=data.get("status"),
        )
