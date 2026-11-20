"""Contract between the proxy and any Layer 2 auditor implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Protocol

from ..domain.models import InterceptRequest, PolicyConfig
from .layer1_engine import Layer1Result


@dataclass
class Layer2Verdict:
    verdict: Literal["ALLOW", "BLOCK", "ESCALATE"]
    risk_score: float
    reason: str
    citations: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    threat_category: Optional[str] = None
    invoice_extracted_total_inr: Optional[float] = None
    intent_match: Optional[bool] = None
    model_used: Optional[str] = None
    retrieved_policy_ids: list[str] = field(default_factory=list)
    retrieval_mode: Optional[str] = None
    fail_closed: bool = False


class Layer2Auditor(Protocol):
    async def audit(
        self, *, req: InterceptRequest, policy: PolicyConfig, envelope: dict, payload_sha256: str, l1: Layer1Result
    ) -> Layer2Verdict: ...
