"use client";

import { useState } from "react";
import { BadgeCheck, ChevronDown, CircleCheck, CircleX, LoaderCircle, ShieldAlert } from "lucide-react";
import { ApiError, decideApproval, errorMessage } from "@/lib/api";
import { cn, formatDateTime, formatINR, humanize } from "@/lib/format";
import type { ApprovalRow, ApprovalStatus } from "@/lib/types";
import { Button, MonoPill, PolicyChip } from "../ui";

export const STATUS_STYLE: Record<ApprovalStatus, string> = {
  PENDING: "bg-amber-50 text-amber-800 ring-amber-200",
  PROCESSING: "bg-sky-50 text-sky-800 ring-sky-200",
  APPROVED: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  REJECTED: "bg-slate-100 text-slate-700 ring-slate-200",
  INTEGRITY_FAILED: "bg-red-50 text-red-700 ring-red-200",
};

const fieldCls =
  "h-9 w-full rounded-lg border border-hairline bg-white px-3 text-[13px] text-ink placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20";

export function ApprovalInboxCard({ row, onDecided }: { row: ApprovalRow; onDecided: (msg: string) => void }) {
  const [reviewer, setReviewer] = useState("finance-manager-01");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"APPROVE" | "REJECT" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const amount = row.canonical_payload.amount_paise / 100;
  const esc = row.escalation;
  const agent = esc?.agent_id ?? row.request.agent_id;

  const decide = async (choice: "APPROVE" | "REJECT") => {
    setBusy(choice);
    setError(null);
    try {
      const d = await decideApproval(row.approval_id, choice, reviewer.trim() || "finance-manager-01", note);
      onDecided(
        choice === "APPROVE"
          ? `Approved ${formatINR(amount)} — settled on Razorpay as ${d.settlement_txn_id}.`
          : `Rejected ${formatINR(amount)} — held budget released to ₹0.`,
      );
    } catch (e) {
      const conflict = e instanceof ApiError && e.status === 409;
      setError(conflict ? `409 Conflict — ${e.message} The inbox has been refreshed.` : errorMessage(e));
      if (conflict) onDecided("");
    } finally {
      setBusy(null);
    }
  };

  return (
    <article className="rounded-xl border border-hairline bg-white" aria-labelledby={`apr-${row.approval_id}`}>
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn("rounded-md px-2 py-0.5 text-[11.5px] font-semibold ring-1 ring-inset", STATUS_STYLE[row.status])}>{humanize(row.status)}</span>
            <span id={`apr-${row.approval_id}`} className="figure text-[12px] text-ink-3">{row.approval_id}</span>
            <span className="text-[12px] text-ink-3">· {formatDateTime(row.created_at)}</span>
          </div>
          <p className="mt-2 text-[13px] text-ink-2">
            <span className="figure text-ink">{row.canonical_payload.tool_name}</span> → <span className="figure text-ink">{row.canonical_payload.merchant_id}</span>
            <span className="text-ink-3"> · agent </span>
            <span className="figure">{agent}</span>
          </p>
        </div>
        <p className="figure text-[22px] font-semibold tabular-nums text-ink">{formatINR(amount)}</p>
      </div>

      {esc && (
        <div className="px-5 pt-3">
          <p className="text-[12.5px] leading-relaxed text-ink-2">
            <span className="font-medium text-ink">Escalation reason: </span>
            {esc.reason}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {esc.policy_citations.map((c) => (
              <PolicyChip key={c} id={c} />
            ))}
            <MonoPill>risk {esc.risk_score.toFixed(2)}</MonoPill>
            {esc.model_used && <MonoPill>{esc.model_used}</MonoPill>}
          </div>
        </div>
      )}

      <details className="group mx-5 mt-3 rounded-lg border border-hairline bg-canvas">
        <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-[12px] [&::-webkit-details-marker]:hidden">
          <BadgeCheck className="size-3.5 shrink-0 text-emerald-700" aria-hidden="true" />
          <span className="font-medium text-ink-2">Sealed Payload Hash — Verified Before Settlement</span>
          <span className="figure min-w-0 flex-1 truncate text-ink-3" title={row.payload_sha256}>{row.payload_sha256}</span>
          <ChevronDown className="size-3.5 shrink-0 text-ink-3 transition-transform group-open:rotate-180" aria-hidden="true" />
        </summary>
        <pre className="figure max-h-56 overflow-auto border-t border-hairline px-3 py-2 text-[11.5px] leading-relaxed text-ink-2">
          {JSON.stringify(row.canonical_payload, null, 2)}
        </pre>
      </details>

      <div className="mt-4 border-t border-hairline px-5 py-3.5">
        {row.status === "PENDING" ? (
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-3">
              <div>
                <label htmlFor={`rev-${row.approval_id}`} className="text-[12px] font-medium text-ink-2">Reviewer ID</label>
                <input id={`rev-${row.approval_id}`} value={reviewer} onChange={(e) => setReviewer(e.target.value)} maxLength={128} className={cn(fieldCls, "figure mt-1")} />
              </div>
              <div className="sm:col-span-2">
                <label htmlFor={`note-${row.approval_id}`} className="text-[12px] font-medium text-ink-2">Reviewer note (optional)</label>
                <input id={`note-${row.approval_id}`} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} placeholder="e.g. Verified with customer on call" className={cn(fieldCls, "mt-1")} />
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="success" onClick={() => decide("APPROVE")} disabled={busy !== null}>
                {busy === "APPROVE" ? <LoaderCircle className="size-4 animate-spin" aria-hidden="true" /> : <CircleCheck className="size-4" aria-hidden="true" />}
                Approve & Settle on Razorpay
              </Button>
              <Button variant="danger" onClick={() => decide("REJECT")} disabled={busy !== null}>
                {busy === "REJECT" ? <LoaderCircle className="size-4 animate-spin" aria-hidden="true" /> : <CircleX className="size-4" aria-hidden="true" />}
                Reject & Release Budget
              </Button>
            </div>
          </div>
        ) : row.status === "APPROVED" ? (
          <dl className="grid gap-3 text-[12.5px] sm:grid-cols-3">
            <div>
              <dt className="text-ink-3">Razorpay settlement</dt>
              <dd className="figure mt-0.5 font-semibold text-emerald-800">{row.settlement_txn_id ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-ink-3">Reviewer</dt>
              <dd className="figure mt-0.5 text-ink">{row.reviewer_id ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-ink-3">Decided</dt>
              <dd className="figure mt-0.5 text-ink">{formatDateTime(row.decided_at)}</dd>
            </div>
            {row.decision_note && <p className="text-ink-2 sm:col-span-3">“{row.decision_note}”</p>}
          </dl>
        ) : row.status === "REJECTED" ? (
          <div className="flex flex-wrap items-center gap-3 text-[12.5px]">
            <span className="rounded-md bg-slate-100 px-2 py-0.5 font-semibold text-slate-700 ring-1 ring-inset ring-slate-200">Budget Released (₹0 Settled)</span>
            <span className="text-ink-2">by <span className="figure">{row.reviewer_id ?? "—"}</span> · {formatDateTime(row.decided_at)}</span>
            {row.decision_note && <span className="text-ink-3">“{row.decision_note}”</span>}
          </div>
        ) : row.status === "INTEGRITY_FAILED" ? (
          <p className="flex items-center gap-2 text-[12.5px] text-red-700">
            <ShieldAlert className="size-4" aria-hidden="true" />
            Anti-TOCTOU integrity failure: stored payload no longer matched its seal — settlement refused, budget released.
          </p>
        ) : (
          <p className="text-[12.5px] text-ink-3">Settlement in progress…</p>
        )}
        {error && <p role="alert" className="mt-3 rounded-md bg-red-50 px-3 py-2 text-[12.5px] text-red-700">{error}</p>}
      </div>
    </article>
  );
}
