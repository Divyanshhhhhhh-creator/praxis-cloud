---
name: praxis-adk-governance
description: Govern any Google ADK agent's payment tools with the Praxis Vaulted Proxy (deterministic treasury limits, RBI Nov 2026 guards, Gemini semantic/PDF audit, HITL approval) via ADK's native before_tool_callback. Use when an ADK agent can move money (refunds, vendor payouts) and must never hold payment credentials.
---

# Praxis ADK Governance Skill

> "Give your AI agents autonomy, not a blank check."

Praxis plugs into Google ADK's native `before_tool_callback`. Every call to a governed
financial tool (`issue_customer_refund`, `pay_vendor_invoice`) is:

1. Converted into a strict `InterceptRequest` and sealed with a canonical SHA-256 hash.
2. Evaluated by **Layer 1**: allowlists, RBI 12-hour contact-change cooling (`RBI/DPSS/2026-27/475`),
   RBI refund-to-original-source (`POL-RBI-PA-REFUND-01`), hard caps, and atomic 1m/1h/24h spend
   windows and velocity limits.
3. Evaluated by **Layer 2**: a grounded `gemini-3.5-flash-lite` auditor that checks intent match,
   prompt injection and invoice PDFs. It has no tools of its own, can only tighten a decision, and
   fails closed to ESCALATE.
4. Settled on Razorpay Test Mode **by the proxy's vault only**, escalated to a Finance Manager
   (HITL), or blocked.

The callback **always returns a dict** for governed tools, so ADK never runs the local tool body.
The agent process never sees `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET`.

## Use it in 3 lines

```python
from app.agent.praxis_adk_skill import create_praxis_before_tool_callback, PraxisHttpProxy

praxis = PraxisHttpProxy("https://praxis-proxy-xyz.a.run.app", agent_token=os.environ["PRAXIS_AGENT_TOKEN"])
agent = LlmAgent(name="ops", model="gemini-3.5-flash-lite", tools=[issue_customer_refund, pay_vendor_invoice],
                 before_tool_callback=create_praxis_before_tool_callback(praxis))
```

If the agent runs in the same process as the proxy, pass the in-process `ProxyService` instead of
`PraxisHttpProxy`. Any object that has `async intercept(InterceptRequest)` works.

## Trusted session state (set by your app, never by the LLM)

| key | purpose |
|---|---|
| `original_user_prompt` | the human's verbatim request, used as the intent baseline for Layer 2 |
| `untrusted_context` | email or ticket text; treated as data only and sandboxed in XML |
| `attachment_base64`, `attachment_mime` | invoice PDF or image for the multimodal audit |
| `policy_id`, `agent_id` | which treasury policy and ledger to apply |
| `contact_changed_hours_ago` | feeds the RBI 12-hour cooling guard |
| `destination_mode` | `original_source` or `alternate_account`; the most restrictive of this and the tool args wins |
| `timeout_override_s` | chaos drill; can only shorten the Layer 2 budget |

## What the agent receives back

| status | meaning |
|---|---|
| `SETTLED` | ALLOW: real `settlement_txn_id` (`order_…` / `rfnd_…`) on `razorpay_test_mode` |
| `BLOCKED_BY_PRAXIS` | BLOCK, with `reason` and `policy_citations` |
| `PAUSED_FOR_HITL_APPROVAL` | ESCALATE: `approval_id`; a human releases it via `POST /v1/approvals/{id}/decide` |

Every decision is also appended to `tool_context.state["praxis_decisions"]` for UI traces.

## Guarantees

- **Idempotent:** the key is derived from the run ID, tool and args, so a retried call settles at most once.
- **Fail-closed:** a malformed call or an unreachable proxy returns `BLOCKED_BY_PRAXIS`, never a fall-through.
- **Free-tier friendly:** `skip_summarization=True` ends the turn on the Praxis result (one model call per action).
