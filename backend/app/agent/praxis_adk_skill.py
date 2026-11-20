"""Praxis governance as a reusable Google ADK skill.

    from app.agent.praxis_adk_skill import create_praxis_before_tool_callback
    agent = LlmAgent(..., before_tool_callback=create_praxis_before_tool_callback(proxy))

Every governed write tool call is intercepted by ADK's native `before_tool_callback`, sealed and
evaluated by the Praxis Vaulted Proxy (L1 deterministic + L2 Gemini), and the callback ALWAYS
returns a dict — so ADK never executes the local tool body. Payment credentials live only in the
proxy's vault; nothing in this package can see them.

`proxy_service` is duck-typed: anything with `async intercept(InterceptRequest)` works — the in-process
`ProxyService`, or `PraxisHttpProxy` below for agents running in a different process/service.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Awaitable, Callable, Iterable, Optional, Protocol

import httpx

from ..domain.models import AuditDecision, InterceptRequest

log = logging.getLogger("praxis.adk_skill")

GOVERNED_TOOLS: frozenset[str] = frozenset({"issue_customer_refund", "pay_vendor_invoice"})
DECISIONS_STATE_KEY = "praxis_decisions"

# Trusted session metadata the host application places in ADK session state (never LLM-authored).
STATE_KEYS = (
    "original_user_prompt",
    "untrusted_context",
    "attachment_base64",
    "attachment_mime",
    "policy_id",
    "contact_changed_hours_ago",
    "destination_mode",
    "timeout_override_s",
    "agent_id",
)


class SupportsIntercept(Protocol):
    async def intercept(self, req: InterceptRequest) -> Any: ...


class PraxisHttpProxy:
    """Remote adapter: routes intercepts to a deployed Praxis proxy over HTTPS with the agent token."""

    def __init__(self, base_url: str, agent_token: str, *, timeout_s: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self._headers = {"X-Agent-Token": agent_token}
        self.timeout_s = timeout_s

    async def intercept(self, req: InterceptRequest) -> AuditDecision:
        async with httpx.AsyncClient(timeout=self.timeout_s, headers=self._headers) as client:
            resp = await client.post(f"{self.base_url}/v1/intercept", json=req.model_dump(mode="json"))
            resp.raise_for_status()
            return AuditDecision.model_validate(resp.json())


def _tool_name(tool: Any) -> str:
    return getattr(tool, "name", None) or getattr(tool, "__name__", "") or str(tool)


def _amount(args: dict) -> float:
    try:
        return float(args.get("amount_inr"))
    except (TypeError, ValueError):
        return -1.0  # forces a schema rejection → fail-closed response below


def _merchant(tool_name: str, args: dict) -> str:
    if tool_name == "pay_vendor_invoice":
        return str(args.get("vendor_id") or "")
    return str(args.get("merchant_id") or "razorpay_refunds")


def _destination(args: dict, state_value: Optional[str]) -> str:
    # Most restrictive wins: if EITHER the LLM's proposal or the trusted session says alternate, treat it as alternate.
    modes = {str(args.get("destination_mode") or "original_source"), str(state_value or "original_source")}
    return "alternate_account" if "alternate_account" in modes else "original_source"


def deterministic_idempotency_key(run_id: str, tool_name: str, args: dict) -> str:
    """Same tool + same args within one agent run ⇒ same key ⇒ the proxy settles at most once."""
    material = json.dumps({"run": run_id, "tool": tool_name, "args": args}, sort_keys=True, default=str)
    return "adk-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:40]


def decision_to_tool_response(d: AuditDecision) -> dict:
    """The dict ADK hands back to the LLM as the tool's result."""
    common = {"verdict": d.verdict, "audit_id": d.audit_id, "amount_inr": d.amount_inr, "payload_sha256": d.payload_sha256}
    if d.verdict in ("ALLOW", "SHADOW_FLAG") and d.executed:
        return {"status": "SETTLED", **common, "settlement_txn_id": d.settlement_txn_id,
                "settlement_rail": d.settlement_rail}
    if d.verdict == "ESCALATE":
        return {"status": "PAUSED_FOR_HITL_APPROVAL", **common, "approval_id": d.approval_id, "reason": d.reason}
    return {"status": "BLOCKED_BY_PRAXIS", **common, "reason": d.reason, "policy_citations": d.policy_citations}


def create_praxis_before_tool_callback(
    proxy_service: SupportsIntercept,
    default_policy_id: str = "default-fintech-treasury",
    *,
    governed_tools: Iterable[str] = GOVERNED_TOOLS,
    default_agent_id: str = "praxis_fintech_ops_agent",
    skip_summarization: bool = True,
) -> Callable[..., Awaitable[Optional[dict]]]:
    """Factory for ADK's `before_tool_callback(tool, args, tool_context)`.

    skip_summarization=True ends the turn on the Praxis result (no second LLM call), which halves
    model RPM per governed action — important on the Gemini free tier.
    """
    governed = frozenset(governed_tools)

    async def before_tool_callback(tool: Any, args: dict[str, Any], tool_context: Any) -> Optional[dict]:
        name = _tool_name(tool)
        if name not in governed:
            return None  # non-financial tools run normally

        state = tool_context.state
        meta = {k: state.get(k) for k in STATE_KEYS}
        run_id = str(getattr(tool_context, "invocation_id", "") or state.get("praxis_run_id") or "")
        clean_args = {k: v for k, v in dict(args).items() if v is not None}
        try:
            req = InterceptRequest(
                agent_id=meta["agent_id"] or default_agent_id,
                idempotency_key=deterministic_idempotency_key(run_id, name, clean_args),
                policy_id=meta["policy_id"] or default_policy_id,
                tool_name=name,
                user_prompt=meta["original_user_prompt"] or "",
                untrusted_context=meta["untrusted_context"],
                payload=clean_args,
                amount_inr=_amount(clean_args),
                merchant_id=_merchant(name, clean_args),
                destination_mode=_destination(clean_args, meta["destination_mode"]),
                contact_changed_hours_ago=meta["contact_changed_hours_ago"],
                attachment_base64=meta["attachment_base64"],
                attachment_mime=meta["attachment_mime"],
                timeout_override_s=meta["timeout_override_s"],
            )
            outcome = await proxy_service.intercept(req)
            decision: AuditDecision = getattr(outcome, "decision", outcome)
        except Exception as exc:  # malformed tool args, proxy unreachable, idempotency conflict … → fail closed
            log.warning("Praxis intercept failed for %s: %s", name, exc)
            response = {
                "status": "BLOCKED_BY_PRAXIS", "verdict": "BLOCK", "audit_id": None,
                "reason": f"Fail-closed: Praxis could not evaluate this call ({type(exc).__name__}).",
                "policy_citations": ["POL-FIN-FAIL-CLOSED"],
            }
        else:
            state[DECISIONS_STATE_KEY] = list(state.get(DECISIONS_STATE_KEY) or []) + [decision.model_dump(mode="json")]
            response = decision_to_tool_response(decision)

        if skip_summarization:
            tool_context.actions.skip_summarization = True
        return response  # ALWAYS a dict for governed tools → ADK never runs the local tool body

    return before_tool_callback
