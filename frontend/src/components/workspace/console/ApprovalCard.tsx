"use client";

import { useState } from "react";
import Link from "next/link";
import { CircleCheck, CircleX, Hourglass, LoaderCircle } from "lucide-react";
import { decideApproval, errorMessage } from "@/lib/api";
import { formatINR } from "@/lib/format";
import { CONSOLE_REVIEWER_ID } from "@/lib/scenarios";
import type { AuditDecision } from "@/lib/types";
import { Button } from "../ui";

export function ApprovalCard({
  decision,
  isPending,
  onDecided,
}: {
  decision: AuditDecision;
  /** null = unknown yet (queue still loading) */
  isPending: boolean | null;
  onDecided: (next: AuditDecision) => void;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"APPROVE" | "REJECT" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const decide = async (choice: "APPROVE" | "REJECT") => {
    if (!decision.approval_id) return;
    setBusy(choice);
    setError(null);
    try {
      onDecided(await decideApproval(decision.approval_id, choice, CONSOLE_REVIEWER_ID, note));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="rounded-xl border border-amber-200 bg-amber-50/50" aria-labelledby="approval-title">
      <div className="flex items-center gap-2 border-b border-amber-200 px-4 py-3">
        <Hourglass className="size-4 text-amber-700" aria-hidden="true" />
        <h3 id="approval-title" className="text-[13.5px] font-semibold text-ink">Treasury Approval Required</h3>
        <span className="ml-auto text-[12px] text-ink-3">Finance Manager · 1-click release</span>
      </div>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-2.5 px-4 py-3.5 text-[12.5px] sm:grid-cols-3">
        <div>
          <dt className="text-ink-3">Held budget</dt>
          <dd className="figure mt-0.5 text-[15px] font-semibold text-ink">{formatINR(decision.amount_inr)}</dd>
        </div>
        <div className="min-w-0">
          <dt className="text-ink-3">approval_id</dt>
          <dd className="figure mt-0.5 truncate text-ink-2" title={decision.approval_id ?? ""}>{decision.approval_id}</dd>
        </div>
        <div className="min-w-0">
          <dt className="text-ink-3">Sealed payload_sha256</dt>
          <dd className="figure mt-0.5 truncate text-ink-2" title={decision.payload_sha256}>{decision.payload_sha256}</dd>
        </div>
      </dl>
      {isPending === false ? (
        <p className="border-t border-amber-200 px-4 py-3 text-[12.5px] text-ink-2">
          This approval has already been decided. See <Link className="text-indigo-700 underline" href="/approvals">HITL Approvals</Link> for the outcome.
        </p>
      ) : (
        <div className="border-t border-amber-200 px-4 py-3.5">
          <label htmlFor="review-note" className="text-[12px] font-medium text-ink-2">Reviewer note (optional)</label>
          <input
            id="review-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={1000}
            placeholder="e.g. Verified with customer on call"
            className="mt-1 h-9 w-full rounded-lg border border-hairline bg-white px-3 text-[13px] text-ink placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
          />
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="success" onClick={() => decide("APPROVE")} disabled={busy !== null}>
              {busy === "APPROVE" ? <LoaderCircle className="size-4 animate-spin" aria-hidden="true" /> : <CircleCheck className="size-4" aria-hidden="true" />}
              Approve & Settle on Razorpay
            </Button>
            <Button variant="danger" onClick={() => decide("REJECT")} disabled={busy !== null}>
              {busy === "REJECT" ? <LoaderCircle className="size-4 animate-spin" aria-hidden="true" /> : <CircleX className="size-4" aria-hidden="true" />}
              Reject & Release Budget
            </Button>
          </div>
          <p className="mt-2 text-[11.5px] text-ink-3">
            Approve re-verifies the sealed SHA-256 before settlement; a second decision returns 409. Reviewer: <span className="figure">{CONSOLE_REVIEWER_ID}</span>
          </p>
          {error && <p role="alert" className="mt-2 rounded-md bg-red-50 px-3 py-2 text-[12.5px] text-red-700">{error}</p>}
        </div>
      )}
    </section>
  );
}
