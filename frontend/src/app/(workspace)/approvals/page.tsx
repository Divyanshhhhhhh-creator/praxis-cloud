"use client";

import { useState } from "react";
import { RefreshCw, ShieldCheck } from "lucide-react";
import { getApprovals } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { cn, formatINR } from "@/lib/format";
import type { ApprovalRow } from "@/lib/types";
import { Button, Card, EmptyNotice } from "@/components/workspace/ui";
import { PageTitle } from "@/components/workspace/PageTitle";
import { ApprovalInboxCard } from "@/components/workspace/approvals/ApprovalInboxCard";
import { useToast } from "@/components/workspace/Toast";

type Filter = "PENDING" | "APPROVED" | "REJECTED" | "ALL";
const FILTERS: { id: Filter; label: string }[] = [
  { id: "PENDING", label: "Pending" },
  { id: "APPROVED", label: "Approved" },
  { id: "REJECTED", label: "Rejected" },
  { id: "ALL", label: "All" },
];

const amountOf = (r: ApprovalRow) => r.canonical_payload.amount_paise / 100;

export default function ApprovalsPage() {
  const approvals = usePolling(() => getApprovals({ limit: 500 }), 8_000);
  const [filter, setFilter] = useState<Filter>("PENDING");
  const [refreshing, setRefreshing] = useState(false);
  const toast = useToast();
  const rows = approvals.data ?? [];

  const count = (f: Filter) => (f === "ALL" ? rows.length : rows.filter((r) => r.status === f).length);
  const visible = filter === "ALL" ? rows : rows.filter((r) => r.status === filter);
  const pending = rows.filter((r) => r.status === "PENDING");
  const heldInr = pending.reduce((s, r) => s + amountOf(r), 0);
  const settledInr = rows.filter((r) => r.status === "APPROVED").reduce((s, r) => s + amountOf(r), 0);
  const integrityFailures = rows.filter((r) => r.status === "INTEGRITY_FAILED").length;

  const refresh = async () => {
    setRefreshing(true);
    await approvals.refresh();
    setRefreshing(false);
  };

  return (
    <div className="space-y-5">
      <PageTitle
        title="HITL Approval Inbox"
        subtitle="Escalated payouts parked with their sealed SHA-256 payload and atomically held budget. Approve re-verifies the hash before Razorpay settlement; reject releases the escrow instantly."
        count={`${pending.length} pending`}
      />

      <Card className="grid grid-cols-2 lg:grid-cols-4">
        <div className="px-5 py-4">
          <p className="text-[12px] font-medium text-ink-3">Pending Count</p>
          <p className="figure mt-1 text-[22px] font-semibold text-ink">{pending.length}</p>
        </div>
        <div className="border-l border-hairline px-5 py-4">
          <p className="text-[12px] font-medium text-ink-3">Total INR Held in Escrow</p>
          <p className="figure mt-1 text-[22px] font-semibold text-amber-800">{formatINR(heldInr)}</p>
        </div>
        <div className="border-t border-hairline px-5 py-4 lg:border-l lg:border-t-0">
          <p className="text-[12px] font-medium text-ink-3">Total Approved Settled</p>
          <p className="figure mt-1 text-[22px] font-semibold text-emerald-800">{formatINR(settledInr)}</p>
        </div>
        <div className="border-l border-t border-hairline px-5 py-4 lg:border-t-0">
          <p className="text-[12px] font-medium text-ink-3">Anti-TOCTOU Integrity Status</p>
          <p className="mt-1 flex items-center gap-1.5 text-[15px] font-semibold text-ink">
            <ShieldCheck className="size-4 text-emerald-700" aria-hidden="true" /> SHA-256 Enforced
          </p>
          <p className="text-[12px] text-ink-3">{integrityFailures} integrity failure{integrityFailures === 1 ? "" : "s"} caught</p>
        </div>
      </Card>

      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-hairline">
        <nav aria-label="Approval filters" className="-mb-px flex gap-1">
          {FILTERS.map((f) => {
            const active = filter === f.id;
            const n = count(f.id);
            return (
              <button
                key={f.id}
                onClick={() => setFilter(f.id)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-1.5 border-b-2 px-3 py-2 text-[13px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-indigo-600",
                  active ? "border-ink text-ink" : "border-transparent text-ink-3 hover:text-ink",
                )}
              >
                {f.label}
                <span
                  className={cn(
                    "figure grid h-[18px] min-w-[18px] place-items-center rounded-full px-1 text-[11px] font-semibold",
                    f.id === "PENDING" && n > 0 ? "bg-amber-100 text-amber-800 ring-1 ring-amber-300" : "bg-slate-100 text-ink-3",
                  )}
                >
                  {n}
                </span>
              </button>
            );
          })}
        </nav>
        <Button variant="secondary" size="sm" onClick={refresh} disabled={refreshing} className="mb-1.5">
          <RefreshCw className={cn("size-3.5", refreshing && "animate-spin")} aria-hidden="true" /> Refresh
        </Button>
      </div>

      {approvals.error && rows.length === 0 ? (
        <Card><EmptyNotice title="API offline" body={approvals.error} /></Card>
      ) : approvals.loading && rows.length === 0 ? (
        <div className="space-y-3" aria-hidden="true">
          {[0, 1].map((i) => <div key={i} className="h-48 animate-pulse rounded-xl bg-slate-100" />)}
        </div>
      ) : visible.length === 0 ? (
        <Card>
          <EmptyNotice
            title={filter === "PENDING" ? "Inbox zero — nothing is waiting for review" : "No approvals in this view"}
            body="Escalations appear here when a payout exceeds the auto-approve threshold or Layer 2 fails closed."
            href="/console"
            cta="Open Live Console"
          />
        </Card>
      ) : (
        <div className="space-y-3">
          {visible.map((r) => (
            <ApprovalInboxCard
              key={`${r.approval_id}:${r.status}`}
              row={r}
              onDecided={(msg) => {
                if (msg) toast.show(msg);
                void approvals.refresh();
              }}
            />
          ))}
        </div>
      )}
      {toast.node}
    </div>
  );
}
