"""Off-path Plain-English Treasury Policy Compiler (`gemini-3.6-flash`, falls back to flash-lite on 429/5xx/timeout)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Literal, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from ..adapters.storage import StorageRepository
from ..domain.models import PolicyConfig
from .gemini_client import is_retryable_model_error

log = logging.getLogger("praxis.policy_compiler")

KNOWN_TOOLS = ("issue_customer_refund", "pay_vendor_invoice")
RBI_MIN_COOLING_HOURS = 12.0


class CompileRequest(BaseModel):
    instruction: str = Field(min_length=3, max_length=4000)
    policy_id: str = "default-fintech-treasury"
    apply: bool = False


class CompiledPolicyDraft(BaseModel):
    """Schema handed to Gemini (no numeric constraints; validated into PolicyConfig afterwards)."""

    name: str
    mode: Literal["enforce", "shadow"]
    max_single_txn_inr: float
    auto_approve_threshold_inr: float
    window_1m_inr: float
    window_1h_inr: float
    window_24h_inr: float
    max_calls_per_min: int
    rbi_cooling_period_hours: float
    enforce_original_source_refund: bool
    allowed_tools: list[str]
    allowed_merchants: list[str]
    changes_summary: list[str]


class CompileResult(BaseModel):
    policy: PolicyConfig
    previous_policy: Optional[PolicyConfig]
    changes_summary: list[str]
    model_used: str
    fallback_used: bool
    applied: bool
    latency_ms: float


class PolicyCompileError(Exception):
    pass


SYSTEM_INSTRUCTION = f"""You compile a finance manager's plain-English treasury rule into an updated Praxis policy.
Start from <current_policy> and change ONLY what the instruction asks; keep every other field identical.
All amounts are INR. Known tools: {", ".join(KNOWN_TOOLS)}.
"cap hourly spend" -> window_1h_inr; "per minute" -> window_1m_inr; "daily" -> window_24h_inr; "auto-approve up to X" -> auto_approve_threshold_inr.
RBI regulatory floors you must never relax: rbi_cooling_period_hours >= {RBI_MIN_COOLING_HOURS:g}, enforce_original_source_refund = true.
changes_summary: one short human-readable line per changed field, e.g. "Hourly spend cap: ₹50,000 → ₹40,000"."""


class PolicyCompiler:
    def __init__(
        self,
        client: genai.Client,
        storage: StorageRepository,
        *,
        model: str = "gemini-3.6-flash",
        fallback_model: str = "gemini-3.5-flash-lite",
        timeout_s: float = 30.0,
    ):
        self.client = client
        self.storage = storage
        self.model = model
        self.fallback_model = fallback_model
        self.timeout_s = timeout_s
        self._config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=CompiledPolicyDraft,
            temperature=0.0,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
        )

    async def _generate(self, model: str, prompt: str) -> CompiledPolicyDraft:
        resp = await asyncio.wait_for(
            self.client.aio.models.generate_content(model=model, contents=prompt, config=self._config),
            timeout=self.timeout_s,
        )
        if isinstance(resp.parsed, CompiledPolicyDraft):
            return resp.parsed
        return CompiledPolicyDraft.model_validate_json(resp.text or "")

    async def compile(self, req: CompileRequest) -> CompileResult:
        t0 = time.perf_counter()
        current = await self.storage.get_policy(req.policy_id)
        if current is None:
            raise PolicyCompileError(f"Unknown policy_id '{req.policy_id}'.")
        prompt = (
            f"<current_policy>\n{current.model_dump_json(indent=1)}\n</current_policy>\n\n"
            f"<instruction>\n{req.instruction}\n</instruction>"
        )

        model_used, fallback_used = self.model, False
        try:
            draft = await self._generate(self.model, prompt)
        except Exception as exc:
            if not (is_retryable_model_error(exc) or isinstance(exc, asyncio.TimeoutError)):
                raise PolicyCompileError(f"Policy compiler failed: {type(exc).__name__}: {exc}") from exc
            log.warning("%s unavailable (%s); falling back to %s", self.model, type(exc).__name__, self.fallback_model)
            model_used, fallback_used = self.fallback_model, True
            draft = await self._generate(self.fallback_model, prompt)

        data = draft.model_dump()
        summary = list(data.pop("changes_summary"))
        # Deterministic regulatory floors — the LLM cannot compile away RBI guards.
        if data["rbi_cooling_period_hours"] < RBI_MIN_COOLING_HOURS:
            data["rbi_cooling_period_hours"] = RBI_MIN_COOLING_HOURS
            summary.append(f"RBI floor enforced: cooling period kept at {RBI_MIN_COOLING_HOURS:g}h (RBI/DPSS/2026-27/475).")
        if not data["enforce_original_source_refund"]:
            data["enforce_original_source_refund"] = True
            summary.append("RBI floor enforced: refund-to-original-source kept ON (POL-RBI-PA-REFUND-01).")
        try:
            policy = PolicyConfig(policy_id=req.policy_id, **data)
        except ValidationError as exc:
            raise PolicyCompileError(f"Compiled policy failed validation: {exc.errors()[:3]}") from exc

        if req.apply:
            await self.storage.upsert_policy(policy)
        return CompileResult(
            policy=policy,
            previous_policy=current,
            changes_summary=summary,
            model_used=model_used,
            fallback_used=fallback_used,
            applied=req.apply,
            latency_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
