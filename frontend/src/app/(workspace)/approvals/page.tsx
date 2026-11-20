"use client";

import { getApprovals } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { cn, formatDateTime, formatINR, humanize, shortHash } from "@/lib/format";
import type { ApprovalStatus } from "@/lib/types";
import { Card, CardHeader, EmptyNotice, MonoPill } from "@/components/workspace/ui";
import { PageTitle } from "@/components/workspace/PageTitle";

const STATUS_STYLE: Record<ApprovalStatus, string> = {
  PENDING: "bg-amber-50 text-amber-800 ring-amber-200",
  PROCESSING: "bg-sky-50 text-sky-800 ring-sky-200",
  APPROVED: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  REJECTED: "bg-slate-100 text-slate-700 ring-slate-200",
  INTEGRITY_FAILED: "bg-red-50 text-red-700 ring-red-200",
};

export default function ApprovalsPage() {
  const approvals = usePolling(() => getApprovals({ limit: 200 }), 8_000);
  const rows = approvals.data ?? [];
  const counts = rows.reduce<Record<string, number>>((acc, r) => ((acc[r.status] = (acc[r.status] ?? 0) + 1), acc), {});
  const heldInr = rows.filter((r) => r.status === "PENDING").reduce((s, r) => s + r.canonical_payload.amount_paise / 100, 0);

  return (
    <div className="space-y-5">
      <PageTitle
        title="HITL Approvals"
        subtitle="Escalated payouts parked with their sealed SHA-256 payload and atomically held budget. Release or reject inline from the Live Console; the full review queue lands in Slice 5."
        count={`${counts.PENDING ?? 0} pending · ${formatINR(heldInr, { decimals: false })} held`}
      />

      <Card>
        <div className="grid grid-cols-2 divide-x divide-hairline sm:grid-cols-5">
          {(["PENDING", "PROCESSING", "APPROVED", "REJECTED", "INTEGRITY_FAILED"] as ApprovalStatus[]).map((s) => (
            <div key={s} className="px-5 py-4">
              <p className="text-[12px] font-medium text-ink-3">{humanize(s)}</p>
              <p className="figure mt-1 text-[22px] font-semibold text-ink">{counts[s] ?? 0}</p>
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <CardHeader title="Approval ledger" subtitle="Live from GET /v1/approvals (newest first)" />
        {approvals.error && !rows.length ? (
          <EmptyNotice title="API offline" body={approvals.error} />
        ) : rows.length === 0 ? (
          <EmptyNotice title="No escalations yet" body="Run the “High-Value ₹8,500” scenario in the console to park a payout for review." href="/console" cta="Open Live Console" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-[13px]">
              <thead className="border-b border-hairline bg-canvas text-[12px] text-ink-3">
                <tr>
                  {["Created", "Status", "Tool", "Amount", "Payload SHA-256", "Reviewer", "Razorpay ID"].map((h) => (
                    <th key={h} scope="col" className="px-4 py-2.5 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {rows.map((r) => (
                  <tr key={r.approval_id}>
                    <td className="figure px-4 py-3 text-ink-2">{formatDateTime(r.created_at)}</td>
                    <td className="px-4 py-3">
                      <span className={cn("rounded-md px-2 py-0.5 text-[11.5px] font-semibold ring-1 ring-inset", STATUS_STYLE[r.status])}>{humanize(r.status)}</span>
                    </td>
                    <td className="figure px-4 py-3">{r.canonical_payload.tool_name}</td>
                    <td className="figure px-4 py-3 font-medium">{formatINR(r.canonical_payload.amount_paise / 100)}</td>
                    <td className="px-4 py-3"><MonoPill title={r.payload_sha256}>{shortHash(r.payload_sha256)}</MonoPill></td>
                    <td className="px-4 py-3 text-ink-2">{r.reviewer_id ?? "—"}</td>
                    <td className="figure px-4 py-3 text-ink-2">{r.settlement_txn_id ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
