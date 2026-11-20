import type { AuditDecision } from "@/lib/types";
import { cn, formatINR, formatMs, formatTime } from "@/lib/format";
import { Card, CardHeader, EmptyNotice, PolicyChip, VerdictPill } from "../ui";

const LAYER_SHORT: Record<AuditDecision["layer_decided"], string> = {
  L1_DETERMINISTIC: "L1",
  L2_GEMINI_AUDITOR: "L2 Gemini",
  HITL_APPROVED: "HITL ✓",
  HITL_REJECTED: "HITL ✗",
};

export function AuditTable({
  audits,
  selectedId,
  onSelect,
  error,
}: {
  audits: AuditDecision[];
  selectedId: string | null;
  onSelect: (d: AuditDecision) => void;
  error: string | null;
}) {
  return (
    <Card>
      <CardHeader title="Immutable Audit Ledger" subtitle="GET /v1/audits · newest first · click a row to inspect its forensic breakdown" />
      {error && audits.length === 0 ? (
        <EmptyNotice title="API offline" body={error} />
      ) : audits.length === 0 ? (
        <EmptyNotice title="No decisions yet" body="Pick a scenario above and run it through the firewall." />
      ) : (
        <div className="max-h-[440px] overflow-auto">
          <table className="w-full min-w-[920px] text-left text-[13px]">
            <thead className="sticky top-0 z-10 border-b border-hairline bg-canvas text-[12px] text-ink-3">
              <tr>
                {["Time", "Tool", "Amount (INR)", "Verdict", "Layer", "L1 / L2", "Razorpay ID / Citations"].map((h) => (
                  <th key={h} scope="col" className="px-4 py-2.5 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-hairline">
              {audits.map((a) => (
                <tr
                  key={a.audit_id}
                  tabIndex={0}
                  aria-selected={selectedId === a.audit_id}
                  onClick={() => onSelect(a)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelect(a);
                    }
                  }}
                  className={cn(
                    "cursor-pointer transition-colors hover:bg-slate-50 focus-visible:bg-indigo-50/60 focus-visible:outline-none",
                    selectedId === a.audit_id && "bg-indigo-50/70 hover:bg-indigo-50",
                  )}
                >
                  <td className="figure whitespace-nowrap px-4 py-2.5 text-ink-2">{formatTime(a.created_at)}</td>
                  <td className="px-4 py-2.5">
                    <div className="figure text-[12.5px] text-ink">{a.tool_name}</div>
                    <div className="truncate text-[11.5px] text-ink-3">{a.agent_id}</div>
                  </td>
                  <td className="figure whitespace-nowrap px-4 py-2.5 font-medium text-ink">{formatINR(a.amount_inr)}</td>
                  <td className="px-4 py-2.5"><VerdictPill verdict={a.verdict} /></td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-ink-2">{LAYER_SHORT[a.layer_decided]}</td>
                  <td className="figure whitespace-nowrap px-4 py-2.5 text-ink-2">
                    {formatMs(a.l1_latency_ms)} <span className="text-ink-3">/</span> {a.l2_latency_ms > 0 ? formatMs(a.l2_latency_ms) : "—"}
                  </td>
                  <td className="px-4 py-2.5">
                    {a.settlement_txn_id ? (
                      <span className="figure text-[12.5px] text-emerald-800">{a.settlement_txn_id}</span>
                    ) : a.policy_citations.length ? (
                      <div className="flex flex-wrap gap-1">
                        {a.policy_citations.slice(0, 2).map((c) => (
                          <PolicyChip key={c} id={c} />
                        ))}
                        {a.policy_citations.length > 2 && <span className="text-[11.5px] text-ink-3">+{a.policy_citations.length - 2}</span>}
                      </div>
                    ) : (
                      <span className="text-ink-3">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
