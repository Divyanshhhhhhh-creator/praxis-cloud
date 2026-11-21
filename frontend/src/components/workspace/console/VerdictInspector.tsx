"use client";

import { ReviewerRequiredBadge } from "../ReviewerAuth";
import { REVIEWER_REQUIRED_TEXT } from "@/lib/reviewer";

import { useCallback, useState } from "react";
import {
  BadgeCheck,
  Ban,
  Check,
  ChevronDown,
  CircleCheck,
  Copy,
  FileText,
  Hourglass,
  LoaderCircle,
  MousePointerClick,
  Receipt,
  ShieldAlert,
  TriangleAlert,
} from "lucide-react";
import type { AuditDecision } from "@/lib/types";
import { cn, formatINR, formatMs, formatTime, humanize, shortHash } from "@/lib/format";
import { LAYER_LABEL, VERDICT_STYLE, verdictHeadline } from "@/lib/verdict";
import { policyMeta } from "@/lib/policies";
import { Button, Card, MonoPill, PolicyChip, VerdictPill } from "../ui";
import { ApprovalCard } from "./ApprovalCard";
import { RbiReportModal } from "./RbiReportModal";
import type { RunView } from "./types";

// ------------------------------------------------------------------ small pieces
function CopyButton({ value, label }: { value: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setDone(true);
          window.setTimeout(() => setDone(false), 1200);
        } catch {
          /* clipboard unavailable */
        }
      }}
      className="rounded p-1 text-ink-3 hover:bg-slate-100 hover:text-ink focus-visible:outline-2 focus-visible:outline-indigo-600"
      aria-label={`Copy ${label}`}
    >
      {done ? <Check className="size-3.5 text-emerald-700" /> : <Copy className="size-3.5" />}
    </button>
  );
}

function RiskMeter({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(1, score)) * 100;
  const tone = score >= 0.75 ? "bg-block" : score >= 0.35 ? "bg-escalate" : "bg-allow";
  return (
    <div className="min-w-[150px]">
      <div className="flex items-baseline justify-between text-[11.5px]">
        <span className="text-ink-3">Risk score</span>
        <span className="figure font-semibold text-ink">{score.toFixed(2)}</span>
      </div>
      <div className="relative mt-1 h-1.5 rounded-full bg-slate-200" role="meter" aria-label="Risk score" aria-valuemin={0} aria-valuemax={1} aria-valuenow={score}>
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${pct}%` }} />
        {[35, 75].map((t) => (
          <span key={t} className="absolute top-[-2px] h-[10px] w-px bg-slate-500" style={{ left: `${t}%` }} aria-hidden="true" />
        ))}
      </div>
      <div className="figure mt-0.5 flex justify-between text-[10px] text-ink-3" aria-hidden="true">
        <span>0</span>
        <span className="ml-[22%]">.35</span>
        <span className="ml-[30%]">.75</span>
        <span>1</span>
      </div>
    </div>
  );
}

function Section({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn("px-5 py-4", className)}>
      <h3 className="text-[12px] font-semibold uppercase tracking-[0.06em] text-ink-3">{title}</h3>
      <div className="mt-2.5">{children}</div>
    </section>
  );
}

function Accordion({ title, children, defaultOpen = false }: { title: React.ReactNode; children: React.ReactNode; defaultOpen?: boolean }) {
  return (
    <details className="group border-t border-hairline" open={defaultOpen}>
      <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-3 text-[13px] font-medium text-ink hover:bg-slate-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-indigo-600 [&::-webkit-details-marker]:hidden">
        {title}
        <ChevronDown className="size-4 text-ink-3 transition-transform group-open:rotate-180" aria-hidden="true" />
      </summary>
      <div className="px-5 pb-4">{children}</div>
    </details>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="figure max-h-64 overflow-auto rounded-lg border border-hairline bg-canvas p-3 text-[11.5px] leading-relaxed text-ink-2">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

// ------------------------------------------------------------------ verdict header
function VerdictHeader({ d }: { d: AuditDecision }) {
  const s = VERDICT_STYLE[d.verdict];
  const Icon = d.verdict === "ALLOW" ? CircleCheck : d.verdict === "BLOCK" ? Ban : d.verdict === "ESCALATE" ? Hourglass : ShieldAlert;
  return (
    <div className={cn("border-b px-5 py-4", s.banner)}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <VerdictPill verdict={d.verdict} />
            <span className="text-[12px] text-ink-3">{LAYER_LABEL[d.layer_decided]}</span>
          </div>
          <p className={cn("mt-2 flex items-center gap-2 text-[19px] font-semibold tracking-tight", s.text)}>
            <Icon className="size-5 shrink-0" aria-hidden="true" />
            <span className="figure">{verdictHeadline(d, (n) => formatINR(n))}</span>
          </p>
          <p className="mt-1 text-[12.5px] text-ink-2">
            <span className="figure">{d.tool_name}</span> · {formatINR(d.amount_inr)} → <span className="figure">{d.merchant_id}</span> · {formatTime(d.created_at)}
          </p>
        </div>
        <RiskMeter score={d.risk_score} />
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        <MonoPill title="Layer 1 deterministic latency">L1 {formatMs(d.l1_latency_ms)}</MonoPill>
        <MonoPill title="Layer 2 Gemini latency (incl. Policy RAG)">L2 {d.l2_latency_ms > 0 ? formatMs(d.l2_latency_ms) : "—"}</MonoPill>
        {d.model_used && <MonoPill>{d.model_used}</MonoPill>}
        {d.threat_category && d.threat_category !== "NONE" && (
          <MonoPill className="border-red-200 bg-red-50 text-red-800">{humanize(d.threat_category)}</MonoPill>
        )}
        <MonoPill>{d.agent_id}</MonoPill>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ contextual panels
function SettlementReceipt({ d }: { d: AuditDecision }) {
  return (
    <section className="rounded-xl border border-emerald-200 bg-white" aria-labelledby="receipt-title">
      <div className="flex items-center gap-2 border-b border-emerald-100 bg-emerald-50/60 px-4 py-2.5">
        <Receipt className="size-4 text-emerald-700" aria-hidden="true" />
        <h3 id="receipt-title" className="text-[13.5px] font-semibold text-ink">Razorpay Test Settlement Receipt</h3>
        <span className="ml-auto inline-flex items-center gap-1 rounded-md bg-emerald-700 px-1.5 py-0.5 text-[11px] font-semibold text-white">
          <BadgeCheck className="size-3" aria-hidden="true" /> Verified SHA-256
        </span>
      </div>
      <dl className="grid gap-3 px-4 py-3.5 text-[12.5px] sm:grid-cols-2">
        <div className="sm:col-span-2">
          <dt className="text-ink-3">settlement_txn_id</dt>
          <dd className="mt-0.5 flex items-center gap-1">
            <span className="figure text-[17px] font-semibold text-ink">{d.settlement_txn_id}</span>
            {d.settlement_txn_id && <CopyButton value={d.settlement_txn_id} label="Razorpay ID" />}
          </dd>
        </div>
        <div>
          <dt className="text-ink-3">Rail</dt>
          <dd className="figure mt-0.5 text-ink">{d.settlement_rail}</dd>
        </div>
        <div>
          <dt className="text-ink-3">Amount settled</dt>
          <dd className="figure mt-0.5 text-ink">{formatINR(d.amount_inr)}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-ink-3">Executed payload_sha256 (== sealed at intake)</dt>
          <dd className="figure mt-0.5 break-all text-ink-2">{d.payload_sha256}</dd>
        </div>
      </dl>
    </section>
  );
}

function BlockPanel({ d, onExport }: { d: AuditDecision; onExport: () => void }) {
  const rejected = d.layer_decided === "HITL_REJECTED";
  return (
    <section className="flex flex-col gap-3 rounded-xl border border-red-200 bg-white p-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p className="text-[13.5px] font-semibold text-ink">{rejected ? "Held budget returned to the treasury" : "Zero funds moved — settlement suppressed"}</p>
        <p className="mt-0.5 text-[12.5px] text-ink-3">
          {rejected ? (
            <>Reservation released atomically; {formatINR(d.amount_inr)} is back in the 1m / 1h / 24h windows.</>
          ) : (
            <>Reserved budget released atomically. Evidence is sealed for the 6-hour RBI / CERT-In window.</>
          )}
        </p>
      </div>
      <Button variant="secondary" onClick={onExport} className="shrink-0">
        <FileText className="size-4" aria-hidden="true" /> Export RBI Annex-1 Report (JSON)
      </Button>
    </section>
  );
}

function InvoiceDiff({ d }: { d: AuditDecision }) {
  if (d.invoice_extracted_total_inr === null) return null;
  const mismatch = Math.abs(d.invoice_extracted_total_inr - d.amount_inr) > Math.max(1, d.amount_inr * 0.01);
  return (
    <Section title="Invoice Discrepancy Check">
      <div className="grid grid-cols-2 overflow-hidden rounded-lg border border-hairline">
        <div className="px-4 py-3">
          <p className="text-[12px] text-ink-3">Invoice extracted total (Gemini)</p>
          <p className="figure mt-0.5 text-[17px] font-semibold text-ink">{formatINR(d.invoice_extracted_total_inr)}</p>
        </div>
        <div className={cn("border-l border-hairline px-4 py-3", mismatch && "bg-red-50")}>
          <p className="text-[12px] text-ink-3">Agent proposed amount</p>
          <p className={cn("figure mt-0.5 text-[17px] font-semibold", mismatch ? "text-red-700" : "text-ink")}>{formatINR(d.amount_inr)}</p>
        </div>
      </div>
      <p className={cn("mt-2 flex items-center gap-1.5 text-[12.5px]", mismatch ? "text-red-700" : "text-emerald-700")}>
        {mismatch ? <TriangleAlert className="size-3.5" aria-hidden="true" /> : <CircleCheck className="size-3.5" aria-hidden="true" />}
        {mismatch
          ? `Mismatch: proposed amount is ${(d.amount_inr / Math.max(d.invoice_extracted_total_inr, 0.01)).toFixed(0)}× the visible invoice total.`
          : "Proposed amount matches the visible invoice total."}
      </p>
    </Section>
  );
}

function BurstBreakdown({ burst }: { burst: AuditDecision[] }) {
  return (
    <Section title={`Velocity burst · ${burst.length} rapid calls`}>
      <ol className="overflow-hidden rounded-lg border border-hairline text-[12.5px]">
        {burst.map((b, i) => (
          <li key={b.audit_id} className={cn("flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2", i > 0 && "border-t border-hairline")}>
            <span className="figure w-12 text-ink-3">Call #{i + 1}</span>
            <VerdictPill verdict={b.verdict} />
            <span className="text-ink-2">{b.layer_decided === "L1_DETERMINISTIC" ? "L1" : b.layer_decided === "L2_GEMINI_AUDITOR" ? "L2" : "HITL"}</span>
            <span className="figure text-ink-3">L1 {formatMs(b.l1_latency_ms)}</span>
            <span className="ml-auto flex flex-wrap gap-1">
              {b.settlement_txn_id ? (
                <span className="figure text-emerald-800">{b.settlement_txn_id}</span>
              ) : (
                b.policy_citations.map((c) => <PolicyChip key={c} id={c} />)
              )}
            </span>
          </li>
        ))}
      </ol>
    </Section>
  );
}

// ------------------------------------------------------------------ main inspector
export function VerdictInspector({
  view,
  running,
  runningLabel,
  elapsedMs,
  error,
  burstProgress,
  approvalPending,
  onDecided,
}: {
  view: RunView | null;
  running: boolean;
  runningLabel: string;
  elapsedMs: number;
  error: string | null;
  burstProgress: AuditDecision[];
  approvalPending: (approvalId: string) => boolean | null;
  onDecided: (next: AuditDecision) => void;
}) {
  const [reportFor, setReportFor] = useState<string | null>(null);
  const closeReport = useCallback(() => setReportFor(null), []); // stable: polling re-renders must not re-run modal effects
  const d = view?.decision ?? null;

  return (
    <Card className="flex min-h-[640px] flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-hairline px-5 py-3.5">
        <div>
          <h2 className="text-[14px] font-semibold text-ink">Forensic Verdict Inspector</h2>
          <p className="mt-0.5 text-[12.5px] text-ink-3">
            {running ? "Evaluating live through Praxis…" : view ? `Source: ${view.source === "adk" ? "Google ADK agent" : view.source === "ledger" ? "audit ledger" : view.source === "burst" ? "velocity burst" : view.source === "hitl" ? "HITL decision" : "compromised agent"}${view.scenario ? ` · ${view.scenario}` : ""}` : "Live L1 + L2 decision trace"}
          </p>
        </div>
        {running && (
          <span className="figure inline-flex items-center gap-1.5 rounded-md bg-indigo-50 px-2 py-1 text-[12px] font-medium text-indigo-800">
            <LoaderCircle className="size-3.5 animate-spin" aria-hidden="true" />
            {(elapsedMs / 1000).toFixed(2)} s
          </span>
        )}
      </div>

      <div aria-live="polite" className="flex flex-1 flex-col">
        {running ? (
          <div className="space-y-4 p-5">
            <p className="text-[13px] text-ink-2">{runningLabel}</p>
            {burstProgress.length > 0 && <BurstBreakdown burst={burstProgress} />}
            <div className="space-y-3" aria-hidden="true">
              <div className="h-24 animate-pulse rounded-xl bg-slate-100" />
              <div className="h-16 animate-pulse rounded-xl bg-slate-100" />
              <div className="h-32 animate-pulse rounded-xl bg-slate-100" />
            </div>
          </div>
        ) : error === REVIEWER_REQUIRED_TEXT ? (
          <div className="p-5">
            <ReviewerRequiredBadge />
          </div>
        ) : error ? (
          <div className="p-5">
            <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4">
              <p className="text-[13.5px] font-semibold text-red-800">Request failed</p>
              <p className="figure mt-1 break-words text-[12.5px] text-red-700">{error}</p>
              <p className="mt-2 text-[12px] text-ink-3">Praxis fails closed — nothing was settled by this failed request.</p>
            </div>
          </div>
        ) : !view ? (
          <div className="grid flex-1 place-items-center p-8 text-center">
            <div className="max-w-sm">
              <div className="mx-auto grid size-11 place-items-center rounded-xl border border-hairline bg-canvas">
                <MousePointerClick className="size-5 text-indigo-600" aria-hidden="true" />
              </div>
              <p className="mt-4 text-[14px] font-semibold text-ink">No verdict yet</p>
              <ol className="mt-2 space-y-1 text-left text-[13px] text-ink-3">
                <li>1. Pick a scenario preset on the left (e.g. <span className="text-ink-2">Poisoned PDF</span>).</li>
                <li>2. Press <span className="text-ink-2">Run Through Praxis Firewall</span>.</li>
                <li>3. Inspect the verdict, citations, receipt or approval here.</li>
              </ol>
              <p className="mt-3 text-[12px] text-ink-3">Or click any row in the audit ledger below.</p>
            </div>
          </div>
        ) : !d ? (
          <div className="p-5">
            <div className="rounded-xl border border-hairline bg-canvas p-4">
              <p className="text-[13.5px] font-semibold text-ink">The agent did not propose a governed tool call</p>
              <p className="mt-1 text-[13px] text-ink-2">{view.agent?.agent_response}</p>
            </div>
          </div>
        ) : (
          <div className="flex flex-1 flex-col">
            <VerdictHeader d={d} />
            {view.escalatedFrom && (
              <p className="border-b border-hairline bg-canvas px-5 py-2 text-[12px] text-ink-3">
                Resolved from escalation <span className="figure text-ink-2">{view.escalatedFrom.audit_id}</span> · approval{" "}
                <span className="figure text-ink-2">{d.approval_id}</span>
              </p>
            )}

            <div className="space-y-0 divide-y divide-hairline">
              <div className="px-5 py-4">
                {d.executed && d.settlement_txn_id ? (
                  <SettlementReceipt d={d} />
                ) : d.verdict === "ESCALATE" && d.approval_id ? (
                  <ApprovalCard key={d.approval_id} decision={d} isPending={approvalPending(d.approval_id)} onDecided={onDecided} />
                ) : d.verdict === "BLOCK" ? (
                  <BlockPanel d={d} onExport={() => setReportFor(d.audit_id)} />
                ) : null}
                <p className="mt-3 text-[13px] leading-relaxed text-ink-2">{d.reason}</p>
              </div>

              <Section title="Policy citations">
                {d.policy_citations.length ? (
                  <ul className="space-y-1.5">
                    {d.policy_citations.map((c) => {
                      const meta = policyMeta(c);
                      return (
                        <li key={c} className="flex flex-wrap items-center gap-2 text-[12.5px]">
                          <PolicyChip id={c} />
                          <span className="text-ink-2">{meta.title}</span>
                          {meta.reference && <span className="figure text-[11.5px] text-ink-3">{meta.reference}</span>}
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <p className="text-[12.5px] text-ink-3">No violations — all deterministic and semantic checks passed.</p>
                )}
              </Section>

              <InvoiceDiff d={d} />
              {view.burst && view.burst.length > 0 && <BurstBreakdown burst={view.burst} />}
            </div>

            <div className="mt-auto">
              {view.agent && (
                <Accordion
                  defaultOpen
                  title={
                    <span className="flex items-center gap-2">
                      ADK Execution Trace
                      <span className="rounded-md bg-emerald-50 px-1.5 py-0.5 text-[11px] font-semibold text-emerald-800 ring-1 ring-inset ring-emerald-200">
                        Local Tool Body Executions: {view.agent.local_tool_bodies_executed}
                        {view.agent.local_tool_bodies_executed === 0 ? " (Vaulted Isolation Verified)" : ""}
                      </span>
                    </span>
                  }
                >
                  <div className="space-y-3 text-[12.5px]">
                    <p className="text-ink-2">
                      <span className="text-ink-3">Agent response:</span> {view.agent.agent_response}
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      <MonoPill>model {view.agent.model}</MonoPill>
                      <MonoPill>total {formatMs(view.agent.total_agent_latency_ms)}</MonoPill>
                      <MonoPill title={view.agent.session_id}>session {shortHash(view.agent.session_id, 12, 4)}</MonoPill>
                    </div>
                    <div>
                      <p className="mb-1 text-ink-3">Proposed tool call(s) — intercepted by before_tool_callback</p>
                      <JsonBlock value={view.agent.tool_calls_proposed} />
                    </div>
                    <div>
                      <p className="mb-1 text-ink-3">Praxis response returned to the agent</p>
                      <JsonBlock value={view.agent.tool_responses} />
                    </div>
                  </div>
                </Accordion>
              )}
              <Accordion title="Cryptographic seal & identifiers">
                <dl className="grid gap-2.5 text-[12.5px]">
                  {(
                    [
                      ["payload_sha256 (canonical envelope)", d.payload_sha256],
                      ["audit_id", d.audit_id],
                      ["idempotency_key", d.idempotency_key],
                      ["policy_id", d.policy_id],
                      ["created_at", d.created_at],
                    ] as const
                  ).map(([k, v]) => (
                    <div key={k}>
                      <dt className="text-ink-3">{k}</dt>
                      <dd className="mt-0.5 flex items-start gap-1">
                        <span className="figure break-all text-ink-2">{v}</span>
                        <CopyButton value={v} label={k} />
                      </dd>
                    </div>
                  ))}
                </dl>
              </Accordion>
            </div>
          </div>
        )}
      </div>
      {reportFor && <RbiReportModal auditId={reportFor} onClose={closeReport} />}
    </Card>
  );
}
