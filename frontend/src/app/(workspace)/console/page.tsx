"use client";

import { useCallback, useMemo, useState } from "react";
import {
  errorMessage,
  fetchDemoPdfBase64,
  getApprovals,
  getAudits,
  getDemoPdfs,
  getHealth,
  getMetrics,
  getPolicies,
  resetDemo,
  runAdkAgent,
  runIntercept,
  upsertPolicy,
} from "@/lib/api";
import { useElapsed, usePolling } from "@/lib/hooks";
import { newIdempotencyKey } from "@/lib/format";
import { DEFAULT_POLICY_ID, REDTEAM_POLICY_ID } from "@/lib/policies";
import {
  BURST_AGENT_ID,
  COMPROMISED_AGENT_ID,
  DEFAULT_FORM,
  DEMO_PDF_FILES,
  SCENARIOS,
  type ConsoleForm,
  type Scenario,
} from "@/lib/scenarios";
import type { AuditDecision, InterceptRequest, PolicyConfig } from "@/lib/types";
import { MonoPill } from "@/components/workspace/ui";
import { KpiStrip } from "@/components/workspace/console/KpiStrip";
import { ScenarioLauncher, type CustomPdf } from "@/components/workspace/console/ScenarioLauncher";
import { VerdictInspector } from "@/components/workspace/console/VerdictInspector";
import { SpendWindows } from "@/components/workspace/console/SpendWindows";
import { AuditTable } from "@/components/workspace/console/AuditTable";
import type { RunView } from "@/components/workspace/console/types";

const FALLBACK_POLICY: PolicyConfig = {
  policy_id: DEFAULT_POLICY_ID,
  name: "Default FinTech Treasury Policy",
  mode: "enforce",
  max_single_txn_inr: 50000,
  auto_approve_threshold_inr: 5000,
  window_1m_inr: 15000,
  window_1h_inr: 50000,
  window_24h_inr: 200000,
  max_calls_per_min: 3,
  rbi_cooling_period_hours: 12,
  enforce_original_source_refund: true,
  allowed_tools: ["issue_customer_refund", "pay_vendor_invoice"],
  allowed_merchants: ["razorpay_refunds", "razorpay_payouts", "acme_supplies", "cloud_infra_gcp"],
};

function buildPayload(form: ConsoleForm, amount: number): Record<string, unknown> {
  return form.tool === "pay_vendor_invoice"
    ? { invoice_id: "INV-2026-0480", vendor_id: form.merchant, amount_inr: amount, notes: "Console vendor payout" }
    : { order_id: "CONSOLE-ORDER", amount_inr: amount, merchant_id: form.merchant, destination_mode: form.destination, reason: "console refund" };
}

export default function ConsolePage() {
  const firstScenario = SCENARIOS[0];
  const [form, setForm] = useState<ConsoleForm>(() => ({ ...DEFAULT_FORM, ...firstScenario.form }));
  const [activeScenario, setActiveScenario] = useState<string | null>(firstScenario.id);
  const [customPdf, setCustomPdf] = useState<CustomPdf | null>(null);
  const [view, setView] = useState<RunView | null>(null);
  const [running, setRunning] = useState(false);
  const [runningLabel, setRunningLabel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [burstProgress, setBurstProgress] = useState<AuditDecision[]>([]);
  const [resetFeedback, setResetFeedback] = useState<string | null>(null);
  const elapsed = useElapsed(running);

  const metrics = usePolling(() => getMetrics(), 10_000);
  const audits = usePolling(() => getAudits({ limit: 50 }), 10_000);
  const pending = usePolling(() => getApprovals({ status: "PENDING" }), 8_000);
  const policies = usePolling(getPolicies, 30_000);
  const pdfs = usePolling(getDemoPdfs, 0);
  const health = usePolling(getHealth, 30_000);

  const { refresh: refreshMetrics } = metrics;
  const { refresh: refreshAudits } = audits;
  const { refresh: refreshPending } = pending;
  const { refresh: refreshPolicies } = policies;
  const refreshAll = useCallback(
    () => Promise.all([refreshMetrics(), refreshAudits(), refreshPending(), refreshPolicies()]).then(() => undefined),
    [refreshMetrics, refreshAudits, refreshPending, refreshPolicies],
  );

  const pendingIds = useMemo(() => new Set((pending.data ?? []).map((p) => p.approval_id)), [pending.data]);
  const pendingHeld = useMemo(() => (pending.data ?? []).reduce((s, p) => s + p.canonical_payload.amount_paise / 100, 0), [pending.data]);
  const approvalPending = useCallback((id: string) => (pending.data ? pendingIds.has(id) : null), [pending.data, pendingIds]);

  const scenarioTitle = activeScenario ? SCENARIOS.find((s) => s.id === activeScenario)?.title : undefined;

  const ensurePolicy = useCallback(
    async (policyId: string) => {
      const known = policies.data ?? [];
      if (policyId !== REDTEAM_POLICY_ID || known.some((p) => p.policy_id === REDTEAM_POLICY_ID)) return;
      const base = known.find((p) => p.policy_id === DEFAULT_POLICY_ID) ?? FALLBACK_POLICY;
      await upsertPolicy({
        ...base,
        policy_id: REDTEAM_POLICY_ID,
        name: "Red-Team Lab (wide windows → Layer 2 decides)",
        window_1m_inr: 100000,
        window_1h_inr: 200000,
        window_24h_inr: 500000,
        max_calls_per_min: 10,
      });
    },
    [policies.data],
  );

  const pickScenario = (s: Scenario) => {
    setActiveScenario(s.id);
    setError(null);
    setForm({
      ...DEFAULT_FORM,
      ...s.form,
      ...(s.action === "velocity-burst"
        ? { prompt: "Refund ₹500 for a duplicate charge (fired 4× back-to-back by velocity-burst-agent).", amount: "500" }
        : {}),
    });
  };

  const changeForm = (patch: Partial<ConsoleForm>) => {
    setForm((f) => ({ ...f, ...patch }));
    if (activeScenario !== "velocity-burst" || "mode" in patch) setActiveScenario(null);
  };

  const run = async () => {
    const amount = Number(form.amount);
    const contact = form.contactHours.trim() === "" ? null : Number(form.contactHours);
    if (form.mode === "intercept" && !(amount > 0)) return setError("Amount must be greater than ₹0.");
    if (contact !== null && !(contact >= 0)) return setError("Contact-changed hours must be ≥ 0.");

    setRunning(true);
    setError(null);
    setBurstProgress([]);
    try {
      await ensurePolicy(form.policyId);
      const preset = form.pdf === "clean_480" || form.pdf === "poisoned_48000" ? form.pdf : null;

      if (form.mode === "adk") {
        setRunningLabel("Google ADK LlmAgent is reasoning on the prompt → before_tool_callback → Praxis Layer 1 + Layer 2…");
        const res = await runAdkAgent({
          prompt: form.prompt,
          untrusted_context: form.untrusted.trim() || null,
          policy_id: form.policyId,
          contact_changed_hours_ago: contact,
          destination_mode: form.destination,
          simulate_timeout: form.simulateTimeout,
          preset_pdf: preset,
          ...(form.pdf === "custom" && customPdf ? { attachment_base64: customPdf.base64, attachment_mime: customPdf.mime } : {}),
        });
        await refreshAll();
        setView({ source: "adk", scenario: scenarioTitle, decision: res.decisions.at(-1) ?? null, agent: res });
      } else {
        setRunningLabel("Sealing payload (SHA-256) → Layer 1 deterministic engine → Layer 2 Gemini auditor…");
        let attachment: { attachment_base64: string; attachment_mime: string } | Record<string, never> = {};
        if (preset) attachment = { attachment_base64: await fetchDemoPdfBase64(DEMO_PDF_FILES[preset]), attachment_mime: "application/pdf" };
        else if (form.pdf === "custom" && customPdf) attachment = { attachment_base64: customPdf.base64, attachment_mime: customPdf.mime };

        const req: InterceptRequest = {
          agent_id: COMPROMISED_AGENT_ID,
          idempotency_key: newIdempotencyKey("console"),
          policy_id: form.policyId,
          tool_name: form.tool,
          user_prompt: form.prompt,
          untrusted_context: form.untrusted.trim() || null,
          payload: buildPayload(form, amount),
          amount_inr: amount,
          merchant_id: form.merchant,
          destination_mode: form.destination,
          contact_changed_hours_ago: contact,
          timeout_override_s: form.simulateTimeout ? 0.001 : null,
          ...attachment,
        };
        const decision = await runIntercept(req);
        await refreshAll();
        setView({ source: "intercept", scenario: scenarioTitle, decision });
      }
    } catch (e) {
      setView(null);
      setError(errorMessage(e));
    } finally {
      setRunning(false);
    }
  };

  const runBurst = async () => {
    setRunning(true);
    setError(null);
    setBurstProgress([]);
    const results: AuditDecision[] = [];
    try {
      for (let i = 1; i <= 4; i++) {
        setRunningLabel(`Velocity burst: firing call ${i} of 4 from ${BURST_AGENT_ID} (₹500 each, back-to-back)…`);
        const d = await runIntercept({
          agent_id: BURST_AGENT_ID,
          idempotency_key: newIdempotencyKey(`burst${i}`),
          policy_id: DEFAULT_POLICY_ID,
          tool_name: "issue_customer_refund",
          user_prompt: `Refund ₹500 to customer cust_burst_0${i} for order V-90${i} (duplicate charge) to the original card.`,
          payload: { order_id: `V-90${i}`, amount_inr: 500, merchant_id: "razorpay_refunds", destination_mode: "original_source" },
          amount_inr: 500,
          merchant_id: "razorpay_refunds",
          destination_mode: "original_source",
        });
        results.push(d);
        setBurstProgress([...results]);
      }
      await refreshAll();
      setView({ source: "burst", scenario: "Velocity Burst (4× calls)", decision: results[results.length - 1], burst: results });
    } catch (e) {
      setView(results.length ? { source: "burst", scenario: "Velocity Burst (partial)", decision: results[results.length - 1], burst: results } : null);
      setError(results.length ? null : errorMessage(e));
    } finally {
      setRunning(false);
    }
  };

  const onDecided = (next: AuditDecision) => {
    setView((v) => ({ source: "hitl", scenario: v?.scenario, decision: next, agent: v?.agent, escalatedFrom: v?.decision ?? undefined }));
    void refreshAll();
  };

  const onReset = async () => {
    setError(null);
    try {
      const r = await resetDemo();
      setView(null);
      setResetFeedback(`Demo state cleared: ${r.audits ?? 0} audits, ${r.ledger_rows} ledger rows, ${r.hitl_approvals ?? 0} approvals. Policies preserved.`);
      window.setTimeout(() => setResetFeedback(null), 5000);
      await refreshAll();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight text-ink">Live Interception Console</h1>
          <p className="mt-1 text-[13.5px] text-ink-3">
            Fire real agent tool calls through the Praxis firewall and inspect every deterministic and semantic decision.
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <MonoPill>L2 {health.data?.layer2_auditor ?? "—"}</MonoPill>
          <MonoPill>ADK {health.data?.adk_agent ?? "—"}</MonoPill>
          <MonoPill>{health.data?.payment_vault.test_mode ? "Razorpay Test Mode" : "Razorpay —"}</MonoPill>
        </div>
      </div>

      <KpiStrip metrics={metrics.data} audits={audits.data ?? []} pendingCount={pending.data?.length ?? 0} pendingHeldInr={pendingHeld} />

      <div className="grid gap-5 lg:grid-cols-12">
        <div className="lg:col-span-5">
          <ScenarioLauncher
            form={form}
            onChange={changeForm}
            activeScenario={activeScenario}
            onPickScenario={pickScenario}
            onRun={run}
            onBurst={runBurst}
            onReset={onReset}
            running={running}
            elapsedMs={elapsed}
            policies={policies.data ?? []}
            pdfs={pdfs.data ?? []}
            customPdf={customPdf}
            onCustomPdf={setCustomPdf}
            resetFeedback={resetFeedback}
          />
        </div>
        <div className="lg:col-span-7">
          <VerdictInspector
            view={view}
            running={running}
            runningLabel={runningLabel}
            elapsedMs={elapsed}
            error={error}
            burstProgress={burstProgress}
            approvalPending={approvalPending}
            onDecided={onDecided}
          />
        </div>
      </div>

      <SpendWindows metrics={metrics.data} />

      <AuditTable
        audits={audits.data ?? []}
        selectedId={view?.decision?.audit_id ?? null}
        error={audits.error}
        onSelect={(d) => {
          setError(null);
          setView({ source: "ledger", decision: d });
          window.scrollTo({ top: 0, behavior: "smooth" });
        }}
      />
    </div>
  );
}
