"use client";

import { Fragment, useState } from "react";
import { ChevronRight } from "lucide-react";
import type { EvalCaseResult } from "@/lib/types";
import { cn, formatINR, formatMs } from "@/lib/format";
import { Card, CardHeader, MonoPill, PolicyChip, VerdictPill } from "../ui";

const LAYER: Record<string, string> = {
  L1_DETERMINISTIC: "L1",
  L2_GEMINI_AUDITOR: "L2 Gemini",
  HITL_APPROVED: "HITL",
  HITL_REJECTED: "HITL",
};

function ActualPill({ c }: { c: EvalCaseResult }) {
  if (c.actual_verdict === "SKIPPED" || c.actual_verdict === "ERROR") {
    return <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[11.5px] font-semibold text-slate-700 ring-1 ring-inset ring-slate-200">{c.actual_verdict}</span>;
  }
  return <VerdictPill verdict={c.actual_verdict} />;
}

export function BenchmarkTable({ cases }: { cases: EvalCaseResult[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Card>
      <CardHeader title="12-Case Forensic Benchmark" subtitle="Click a row for the auditor's rationale, amounts and settlement evidence" />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1060px] text-left text-[13px]">
          <thead className="border-b border-hairline bg-canvas text-[12px] text-ink-3">
            <tr>
              {["", "Case", "Scenario", "Category", "Expected", "Actual", "Status", "Layer", "Latency", "Policy Citations"].map((h, i) => (
                <th key={i} scope="col" className="px-3 py-2.5 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-hairline">
            {cases.map((c) => {
              const expanded = open === c.case_id;
              const status = c.actual_verdict === "SKIPPED" ? "SKIP" : c.passed ? "PASS" : "FAIL";
              return (
                <Fragment key={c.case_id}>
                  <tr
                    tabIndex={0}
                    aria-expanded={expanded}
                    onClick={() => setOpen(expanded ? null : c.case_id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setOpen(expanded ? null : c.case_id);
                      }
                    }}
                    className={cn("cursor-pointer align-top transition-colors hover:bg-slate-50 focus-visible:bg-indigo-50/60 focus-visible:outline-none", expanded && "bg-slate-50")}
                  >
                    <td className="py-2.5 pl-3"><ChevronRight className={cn("size-4 text-ink-3 transition-transform", expanded && "rotate-90")} aria-hidden="true" /></td>
                    <td className="figure whitespace-nowrap px-3 py-2.5 font-medium text-ink">{c.case_id}</td>
                    <td className="px-3 py-2.5">
                      <div className="font-medium text-ink">{c.title}</div>
                      {c.live_gemini && <div className="text-[11.5px] text-cyan-800">live Gemini</div>}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-ink-2">{c.category}</td>
                    <td className="px-3 py-2.5"><VerdictPill verdict={c.expected_verdict} /></td>
                    <td className="px-3 py-2.5"><ActualPill c={c} /></td>
                    <td className="px-3 py-2.5">
                      <span
                        className={cn(
                          "figure rounded-md px-1.5 py-0.5 text-[11.5px] font-bold ring-1 ring-inset",
                          status === "PASS" && "bg-emerald-50 text-emerald-800 ring-emerald-200",
                          status === "FAIL" && "bg-red-50 text-red-700 ring-red-200",
                          status === "SKIP" && "bg-slate-100 text-slate-700 ring-slate-200",
                        )}
                      >
                        {status}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-ink-2">{c.actual_layer ? LAYER[c.actual_layer] : "—"}</td>
                    <td className="figure whitespace-nowrap px-3 py-2.5 text-ink-2">
                      {formatMs(c.l1_latency_ms)}
                      {c.l2_latency_ms > 0 && <span className="text-ink-3"> + {formatMs(c.l2_latency_ms)}</span>}
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex flex-wrap gap-1">
                        {c.policy_citations.length ? c.policy_citations.map((p) => <PolicyChip key={p} id={p} />) : <span className="text-ink-3">—</span>}
                      </div>
                    </td>
                  </tr>
                  {expanded && (
                    <tr className="bg-slate-50">
                      <td />
                      <td colSpan={9} className="px-3 pb-4 pt-1">
                        <div className="grid gap-4 text-[12.5px] lg:grid-cols-3">
                          <div className="lg:col-span-2">
                            <p className="text-ink-3">Scenario</p>
                            <p className="mt-0.5 text-ink-2">{c.description}</p>
                            <p className="mt-3 text-ink-3">Praxis rationale</p>
                            <p className="mt-0.5 text-ink">{c.reason || c.error || "—"}</p>
                            {c.note && <p className="mt-2 rounded-md bg-white px-2.5 py-1.5 text-ink-2 ring-1 ring-hairline">{c.note}</p>}
                          </div>
                          <dl className="space-y-1.5">
                            <div className="flex justify-between gap-3"><dt className="text-ink-3">Proposed amount</dt><dd className="figure text-ink">{formatINR(c.amount_inr)}</dd></div>
                            <div className="flex justify-between gap-3"><dt className="text-ink-3">Money moved</dt><dd className={cn("figure", c.money_moved_inr > 0 ? "text-ink" : "text-emerald-800")}>{formatINR(c.money_moved_inr)}</dd></div>
                            {c.invoice_extracted_total_inr !== null && (
                              <div className="flex justify-between gap-3"><dt className="text-ink-3">Invoice total (Gemini)</dt><dd className="figure text-ink">{formatINR(c.invoice_extracted_total_inr)}</dd></div>
                            )}
                            {c.risk_score !== null && <div className="flex justify-between gap-3"><dt className="text-ink-3">Risk score</dt><dd className="figure text-ink">{c.risk_score.toFixed(2)}</dd></div>}
                            {c.threat_category && c.threat_category !== "NONE" && (
                              <div className="flex justify-between gap-3"><dt className="text-ink-3">Threat</dt><dd className="text-ink">{c.threat_category}</dd></div>
                            )}
                            {c.settlement_txn_id && (
                              <div className="flex justify-between gap-3"><dt className="text-ink-3">Settlement</dt><dd><MonoPill>{c.settlement_txn_id}</MonoPill></dd></div>
                            )}
                            <div className="flex justify-between gap-3"><dt className="text-ink-3">Wall time</dt><dd className="figure text-ink">{formatMs(c.wall_latency_ms)}</dd></div>
                          </dl>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
