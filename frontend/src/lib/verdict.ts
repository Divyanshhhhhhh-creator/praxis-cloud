import type { AuditDecision, Verdict } from "./types";

/** Pill styling: -50 fill, -700 text (AA), semantic dot colour from the spec. */
export const VERDICT_STYLE: Record<Verdict, { label: string; pill: string; dot: string; banner: string; text: string }> = {
  ALLOW: {
    label: "ALLOW",
    pill: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    dot: "bg-allow",
    banner: "bg-emerald-50 border-emerald-200",
    text: "text-emerald-700",
  },
  BLOCK: {
    label: "BLOCK",
    pill: "bg-red-50 text-red-700 ring-red-200",
    dot: "bg-block",
    banner: "bg-red-50 border-red-200",
    text: "text-red-700",
  },
  ESCALATE: {
    label: "ESCALATE",
    pill: "bg-amber-50 text-amber-800 ring-amber-200",
    dot: "bg-escalate",
    banner: "bg-amber-50 border-amber-200",
    text: "text-amber-800",
  },
  SHADOW_FLAG: {
    label: "SHADOW FLAG",
    pill: "bg-slate-100 text-slate-700 ring-slate-200",
    dot: "bg-shadowflag",
    banner: "bg-slate-50 border-slate-200",
    text: "text-slate-700",
  },
};

export function verdictHeadline(d: AuditDecision, formatInr: (n: number) => string): string {
  if (d.layer_decided === "HITL_APPROVED") return "APPROVED BY FINANCE & SETTLED";
  if (d.layer_decided === "HITL_REJECTED") return `REJECTED — ${formatInr(d.amount_inr)} RELEASED`;
  switch (d.verdict) {
    case "ALLOW":
      return d.executed ? "ALLOWED & SETTLED" : "ALLOWED";
    case "BLOCK":
      return `BLOCKED — ${formatInr(d.amount_inr)} PROTECTED`;
    case "ESCALATE":
      return "ESCALATED — HITL HOLD";
    case "SHADOW_FLAG":
      return "SHADOW FLAGGED";
  }
}

export const LAYER_LABEL: Record<AuditDecision["layer_decided"], string> = {
  L1_DETERMINISTIC: "Layer 1 · Deterministic",
  L2_GEMINI_AUDITOR: "Layer 2 · Gemini Auditor",
  HITL_APPROVED: "HITL · Approved",
  HITL_REJECTED: "HITL · Rejected",
};
