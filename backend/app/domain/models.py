"""Strict API-first Pydantic v2 schemas for the Praxis Vaulted Execution Proxy."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .hashing import canonical_json

Verdict = Literal["ALLOW", "BLOCK", "ESCALATE", "SHADOW_FLAG"]
LayerDecided = Literal["L1_DETERMINISTIC", "L2_GEMINI_AUDITOR", "HITL_APPROVED", "HITL_REJECTED"]
DestinationMode = Literal["original_source", "alternate_account"]


class InterceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    agent_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=128)
    policy_id: str = Field(default="default-fintech-treasury", min_length=1, max_length=128)
    tool_name: str = Field(min_length=1, max_length=128)
    user_prompt: str
    untrusted_context: Optional[str] = None
    payload: dict
    amount_inr: float = Field(gt=0, allow_inf_nan=False)
    merchant_id: str = Field(min_length=1, max_length=128)
    destination_mode: DestinationMode = "original_source"
    contact_changed_hours_ago: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    attachment_base64: Optional[str] = None
    attachment_mime: Optional[str] = None

    @field_validator("payload")
    @classmethod
    def _payload_must_be_canonicalizable(cls, v: dict) -> dict:
        try:
            canonical_json(v)
        except (TypeError, ValueError) as exc:  # NaN/Infinity or non-JSON types
            raise ValueError(f"payload is not canonical-JSON serializable: {exc}") from exc
        return v


class PolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(min_length=1, max_length=128)
    name: str
    mode: Literal["enforce", "shadow"] = "enforce"
    max_single_txn_inr: float = Field(default=50000.0, gt=0)
    auto_approve_threshold_inr: float = Field(default=5000.0, ge=0)
    window_1m_inr: float = Field(default=15000.0, gt=0)
    window_1h_inr: float = Field(default=50000.0, gt=0)
    window_24h_inr: float = Field(default=200000.0, gt=0)
    max_calls_per_min: int = Field(default=3, ge=1)
    rbi_cooling_period_hours: float = Field(default=12.0, ge=0)
    enforce_original_source_refund: bool = True
    allowed_tools: list[str]
    allowed_merchants: list[str]


class AuditDecision(BaseModel):
    audit_id: str
    idempotency_key: str
    agent_id: str
    policy_id: str
    tool_name: str
    amount_inr: float
    merchant_id: str
    verdict: Verdict
    layer_decided: LayerDecided
    risk_score: float
    reason: str
    policy_citations: list[str]
    payload_sha256: str
    l1_latency_ms: float
    l2_latency_ms: float = 0.0
    executed: bool
    settlement_txn_id: Optional[str] = None
    settlement_rail: Optional[str] = None
    created_at: str
    approval_id: Optional[str] = None
    threat_category: Optional[str] = None
    invoice_extracted_total_inr: Optional[float] = None
    model_used: Optional[str] = None


class WindowUsage(BaseModel):
    used_1m_inr: float
    limit_1m_inr: float
    used_1h_inr: float
    limit_1h_inr: float
    used_24h_inr: float
    limit_24h_inr: float
    calls_1m: int
    limit_calls_1m: int


class MetricsSummary(BaseModel):
    total_requests: int
    allowed_count: int
    blocked_count: int
    escalated_count: int
    shadow_flagged_count: int
    total_inr_settled: float
    total_inr_protected: float
    avg_l1_latency_ms: float
    avg_l2_latency_ms: float
    window_usage: WindowUsage
