# CLAUDE.md — Praxis Cloud (Google Startup Buildathon India 2026)

## Mission
Build **Praxis**, an institutional FinTech Treasury & AI Agent Governance Firewall sitting between autonomous AI agents (Google ADK) and Razorpay Test Mode payment/settlement rails.
Tagline: "Give Your AI Agents Autonomy, Not a Blank Check."

## Verified Google AI Models (Tested Live on Active Key)
- Hot-Path Semantic & Multimodal PDF Auditor: `gemini-3.5-flash-lite` (`google-genai` SDK, `thinking_level="minimal"`, strict Pydantic `response_schema`).
- Off-Path Plain-English Finance Policy Compiler & Deep Escalation Analyst: `gemini-3.6-flash` (with automatic fallback to `gemini-3.5-flash-lite` on any 429/503).
- Policy RAG Grounding Embeddings: `gemini-embedding-2` (3072 dims, cites exact Policy IDs like `POL-RBI-PA-REFUND-01`).

## Non-Negotiable Engineering & Security Invariants
1. **ZERO FAKE AI OR PAYMENTS:** Every Layer 2 audit, Policy RAG lookup, and Policy Compile MUST call the real Gemini API (`google-genai`). Every approved payout/refund MUST call the real Razorpay Test Mode API (`https://api.razorpay.com/v1/...`) returning genuine Razorpay IDs (`rfnd_...` or `order_...`). Do NOT use Stripe anywhere.
2. **NATIVE GOOGLE ADK HOOK:** Use `google-adk` `LlmAgent` with `before_tool_callback(tool, args, tool_context)`. Returning a `dict` skips local tool execution and returns the Praxis Vaulted Proxy response directly to the agent.
3. **VAULTED CREDENTIAL ISOLATION:** `backend/app/agent/` MUST NEVER read or import `RAZORPAY_KEY_ID` or `RAZORPAY_KEY_SECRET`. Only `backend/app/adapters/payment_vault.py` inside the Proxy accesses Razorpay credentials (`.env` locally, Secret Manager on Cloud Run).
4. **NO TOCTOU:** Canonical JSON payload is SHA-256 hashed at proxy intake. Approved and HITL-released transactions execute ONLY the exact verified payload hash.
5. **ATOMIC SLIDING WINDOWS:** Enforce `1m`, `1h`, and `24h` cumulative INR spend caps + velocity circuit-breakers atomically (`BEGIN IMMEDIATE` in SQLite locally; Firestore Transaction on Cloud Run). Atomically release reserved budget if Layer 2 blocks or downstream fails.
6. **IDEMPOTENCY:** Deduplicate every write call by `idempotency_key`.
7. **XML SANDBOXING + MONOTONICITY:** Wrap untrusted inputs (emails, PDFs) in `<untrusted_data>...</untrusted_data>`. Layer 2 Gemini has zero tools and can only tighten decisions (never override a Layer 1 `BLOCK`).
8. **FAIL-CLOSED DEFAULT:** Any Layer 2 timeout (>2.5s), API error, or ambiguous risk (`0.35 <= risk < 0.75`) MUST route to `ESCALATE` (HITL)—never `ALLOW`.
9. **RBI NOV 5 & NOV 11, 2026 COMPLIANCE GUARDS:**
   - Include `POL-RBI-PA-REFUND-01` (refunds must route strictly to original payment source — RBI PA Master Direction updated 11 Nov 2026) in Layer 1 and Policy RAG.
   - Include Layer 1 deterministic `12-hour contact-change cooling guard` (`RBI/DPSS/2026-27/475`, 5 Nov 2026).
   - Provide `Export RBI Annex-1 Incident Report (JSON)` endpoint for blocked threats (6-hour reporting readiness).
   - Deploy Cloud Run, Firestore, and BigQuery strictly in `asia-south1` (Mumbai).

## Clean Architecture Layout
- `backend/app/domain/` — Pure Pydantic models, canonical SHA-256 hashing, policy schemas, invariants.
- `backend/app/services/` — Layer 1 Deterministic Treasury Engine, Layer 2 Grounded Gemini Auditor, Policy Compiler, HITL Manager.
- `backend/app/adapters/` — Payment Vault (Razorpay Test Mode via httpx Basic Auth), Storage (SQLite / Firestore), Audit Sink (SQLite / BigQuery).
- `backend/app/agent/` — Google ADK FinTech Operations Agent (`issue_customer_refund`, `pay_vendor_invoice`) + `before_tool_callback`.
- `frontend/` — Next.js 15 App Router, TypeScript, Tailwind CSS, shadcn/ui, Recharts. Mercury / Stripe Radar FinTech aesthetic, WCAG AA contrast, zero clutter.
- `evals/` — 12-case adversarial FinTech benchmark + PDF invoice generators.

## Verification Rule
After every slice, ALWAYS run `pytest` (backend) or `npm run build` (frontend) and prove live endpoints work before finishing.
