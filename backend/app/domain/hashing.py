"""Canonical JSON serialization + SHA-256 payload fingerprinting (anti-TOCTOU)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

ENVELOPE_VERSION = 1


def canonical_json(payload: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8 preserved, NaN/Infinity rejected."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def compute_payload_sha256(payload: dict) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def inr_to_paise(amount_inr: float) -> int:
    return int(round(float(amount_inr) * 100))


def build_execution_envelope(
    *,
    tool_name: str,
    merchant_id: str,
    amount_inr: float,
    destination_mode: str,
    payload: dict,
) -> dict:
    """The exact object that gets hashed at intake and executed by the vault.

    Binding tool, merchant, amount (integer paise) and destination into the hashed
    envelope means nothing that moves money can change between verification and
    settlement without breaking the SHA-256 seal.
    """
    return {
        "v": ENVELOPE_VERSION,
        "tool_name": tool_name,
        "merchant_id": merchant_id,
        "amount_paise": inr_to_paise(amount_inr),
        "currency": "INR",
        "destination_mode": destination_mode,
        "args": payload,
    }
