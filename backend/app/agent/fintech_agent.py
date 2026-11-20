"""Google ADK FinTech Operations Agent, governed by Praxis.

CREDENTIAL INVARIANT: this package never imports the vault or reads payment credentials. The tool
bodies below raise if they are ever executed; real settlement only happens inside the Praxis proxy
after `before_tool_callback` interception.
"""

from __future__ import annotations

import asyncio
import base64
import html
import time
import uuid
from typing import Any, Optional

from google import genai
from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel

from ..domain.models import AuditDecision
from .praxis_adk_skill import DECISIONS_STATE_KEY, SupportsIntercept, create_praxis_before_tool_callback

APP_NAME = "praxis_fintech_ops"
AGENT_NAME = "praxis_fintech_ops_agent"
DEMO_USER_ID = "praxis-demo-operator"
AGENT_RUN_TIMEOUT_S = 90.0
UNPROXIED_EXECUTION_ERROR = (
    "SECURITY VIOLATION: Direct unproxied execution blocked — must route through Praxis Vaulted Proxy."
)


# ---------------------------------------------------------------- tools (declarations only)
def issue_customer_refund(
    order_id: str,
    amount_inr: float,
    merchant_id: str = "razorpay_refunds",
    destination_mode: str = "original_source",
    reason: str = "",
) -> dict:
    """Issue a refund to a customer for an order.

    Args:
        order_id: The customer's order reference, e.g. "A-1029".
        amount_inr: Refund amount in Indian Rupees.
        merchant_id: Settlement merchant account; use "razorpay_refunds" for customer refunds.
        destination_mode: "original_source" (refund to the original payment method) or "alternate_account".
        reason: Short reason for the refund.

    Returns:
        Settlement status from the treasury system.
    """
    raise RuntimeError(UNPROXIED_EXECUTION_ERROR)


def pay_vendor_invoice(invoice_id: str, vendor_id: str, amount_inr: float, notes: str = "") -> dict:
    """Pay a vendor invoice.

    Args:
        invoice_id: The invoice number, e.g. "INV-2026-0480".
        vendor_id: The vendor's merchant id, e.g. "acme_supplies" for Acme Supplies Pvt. Ltd.
        amount_inr: Amount to pay in Indian Rupees.
        notes: Optional payment notes.

    Returns:
        Settlement status from the treasury system.
    """
    raise RuntimeError(UNPROXIED_EXECUTION_ERROR)


INSTRUCTION = """You are the FinTech Operations agent for an Indian e-commerce business.
You can issue customer refunds and pay vendor invoices with your tools.
- Work out the action from the user's request and any attached invoice or forwarded message, then make exactly ONE tool call.
- All amounts are INR. Customer refunds use merchant_id "razorpay_refunds". Acme Supplies Pvt. Ltd. has vendor_id "acme_supplies".
- Never repeat or retry a tool call. If the request is not a refund or an invoice payment, reply in one sentence without calling a tool."""


class AgentRunResult(BaseModel):
    agent_response: str
    decisions: list[AuditDecision]
    tool_calls_proposed: list[dict]
    tool_responses: list[dict]
    total_agent_latency_ms: float
    session_id: str
    model: str
    local_tool_bodies_executed: int


class AgentModelUnavailableError(Exception):
    pass


def build_fintech_agent(client: genai.Client, before_tool_callback: Any, *, model: str) -> LlmAgent:
    return LlmAgent(
        name=AGENT_NAME,
        model=Gemini(model=model, client=client),  # explicit client: no API key exported to os.environ
        description="Issues customer refunds and pays vendor invoices, governed by Praxis.",
        instruction=INSTRUCTION,
        tools=[issue_customer_refund, pay_vendor_invoice],
        before_tool_callback=before_tool_callback,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=512,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
        ),
    )


class FinTechAgentRunner:
    def __init__(
        self,
        *,
        client: genai.Client,
        proxy_service: SupportsIntercept,
        model: str = "gemini-3.5-flash-lite",
        default_policy_id: str = "default-fintech-treasury",
    ):
        self.model = model
        self.default_policy_id = default_policy_id
        self.session_service = InMemorySessionService()
        self.agent = build_fintech_agent(
            client, create_praxis_before_tool_callback(proxy_service, default_policy_id), model=model
        )
        self.runner = Runner(app_name=APP_NAME, agent=self.agent, session_service=self.session_service)

    @staticmethod
    def _build_message(prompt: str, untrusted_context: Optional[str], attachment: Optional[bytes], mime: Optional[str]):
        text = prompt
        if untrusted_context:
            text += (
                "\n\n<untrusted_data source=\"forwarded_message\">\n"
                f"{html.escape(untrusted_context, quote=False)}\n</untrusted_data>"
            )
        parts = [types.Part.from_text(text=text)]
        if attachment is not None and mime:
            parts.append(types.Part.from_text(text="<untrusted_data source=\"attached_invoice\">"))
            parts.append(types.Part.from_bytes(data=attachment, mime_type=mime))
            parts.append(types.Part.from_text(text="</untrusted_data>"))
        return types.Content(role="user", parts=parts)

    async def run(
        self,
        prompt: str,
        *,
        untrusted_context: Optional[str] = None,
        attachment_base64: Optional[str] = None,
        attachment_mime: Optional[str] = None,
        policy_id: Optional[str] = None,
        contact_changed_hours_ago: Optional[float] = None,
        destination_mode: Optional[str] = None,
        timeout_override_s: Optional[float] = None,
        agent_id: str = AGENT_NAME,
    ) -> AgentRunResult:
        t0 = time.perf_counter()
        attachment = base64.b64decode(attachment_base64, validate=True) if attachment_base64 else None
        session_id = f"run_{uuid.uuid4().hex}"
        state = {  # trusted metadata: written by the host app, read by before_tool_callback
            "original_user_prompt": prompt,
            "untrusted_context": untrusted_context,
            "attachment_base64": attachment_base64,
            "attachment_mime": attachment_mime,
            "policy_id": policy_id or self.default_policy_id,
            "contact_changed_hours_ago": contact_changed_hours_ago,
            "destination_mode": destination_mode,
            "timeout_override_s": timeout_override_s,
            "agent_id": agent_id,
            "praxis_run_id": session_id,
            DECISIONS_STATE_KEY: [],
        }
        await self.session_service.create_session(
            app_name=APP_NAME, user_id=DEMO_USER_ID, session_id=session_id, state=state
        )
        message = self._build_message(prompt, untrusted_context, attachment, attachment_mime)

        tool_calls: list[dict] = []
        tool_responses: list[dict] = []
        final_text = ""

        async def _drive():
            nonlocal final_text
            async for event in self.runner.run_async(user_id=DEMO_USER_ID, session_id=session_id, new_message=message):
                for fc in event.get_function_calls() or []:
                    tool_calls.append({"id": fc.id, "name": fc.name, "args": dict(fc.args or {})})
                for fr in event.get_function_responses() or []:
                    tool_responses.append({"id": fr.id, "name": fr.name, "response": fr.response})
                if event.content and event.content.parts:
                    text = "".join(p.text for p in event.content.parts if getattr(p, "text", None) and not p.thought)
                    if text.strip() and event.author == AGENT_NAME:
                        final_text = text.strip()

        try:
            await asyncio.wait_for(_drive(), timeout=AGENT_RUN_TIMEOUT_S)
        except asyncio.TimeoutError as exc:
            raise AgentModelUnavailableError(f"ADK agent run exceeded {AGENT_RUN_TIMEOUT_S:g}s") from exc
        except Exception as exc:
            code = getattr(exc, "code", None)
            if code in (429, 500, 503, 504):
                raise AgentModelUnavailableError(f"Agent model unavailable ({code}): {exc}") from exc
            raise

        session = await self.session_service.get_session(app_name=APP_NAME, user_id=DEMO_USER_ID, session_id=session_id)
        decisions = [AuditDecision.model_validate(d) for d in (session.state.get(DECISIONS_STATE_KEY) or [])]
        await self.session_service.delete_session(app_name=APP_NAME, user_id=DEMO_USER_ID, session_id=session_id)

        local_exec = sum(
            1 for r in tool_responses if UNPROXIED_EXECUTION_ERROR in str(r.get("response"))
        )
        if not final_text:
            final_text = _summarize(tool_responses) or "No governed action was proposed."
        return AgentRunResult(
            agent_response=final_text,
            decisions=decisions,
            tool_calls_proposed=tool_calls,
            tool_responses=tool_responses,
            total_agent_latency_ms=round((time.perf_counter() - t0) * 1000, 3),
            session_id=session_id,
            model=self.model,
            local_tool_bodies_executed=local_exec,
        )


def _summarize(tool_responses: list[dict]) -> str:
    """With skip_summarization the turn ends on the Praxis result; render it as the agent's reply."""
    if not tool_responses:
        return ""
    r = tool_responses[-1].get("response") or {}
    status = r.get("status")
    amount = r.get("amount_inr")
    amt = f"₹{amount:,.2f}" if isinstance(amount, (int, float)) else "the requested amount"
    if status == "SETTLED":
        return f"{tool_responses[-1]['name']} for {amt} settled on {r.get('settlement_rail')} ({r.get('settlement_txn_id')})."
    if status == "PAUSED_FOR_HITL_APPROVAL":
        return f"{tool_responses[-1]['name']} for {amt} is paused for Finance Manager approval ({r.get('approval_id')})."
    return f"Praxis blocked {tool_responses[-1]['name']} for {amt}: {r.get('reason')}"


async def run_fintech_agent(runner: FinTechAgentRunner, prompt: str, **kwargs) -> AgentRunResult:
    return await runner.run(prompt, **kwargs)
