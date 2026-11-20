"use client";

import { useMemo, useState } from "react";
import { Lock, Plus, Save, ShieldCheck, TriangleAlert, X } from "lucide-react";
import { errorMessage, updatePolicy } from "@/lib/api";
import { cn, formatINR } from "@/lib/format";
import type { PolicyConfig } from "@/lib/types";
import { Button, Card } from "../ui";

const KNOWN_TOOLS = ["issue_customer_refund", "pay_vendor_invoice"];

type NumericKey =
  | "max_single_txn_inr"
  | "auto_approve_threshold_inr"
  | "window_1m_inr"
  | "window_1h_inr"
  | "window_24h_inr"
  | "max_calls_per_min";

const NUMERIC_FIELDS: { key: NumericKey; label: string; hint: string; min: number; integer?: boolean }[] = [
  { key: "max_single_txn_inr", label: "Single-transaction cap (INR)", hint: "Hard L1 block above this amount", min: 1 },
  { key: "auto_approve_threshold_inr", label: "Auto-approve threshold (INR)", hint: "Above this → Finance Manager HITL", min: 0 },
  { key: "window_1m_inr", label: "1-minute spend window (INR)", hint: "Atomic sliding cap", min: 1 },
  { key: "window_1h_inr", label: "1-hour spend window (INR)", hint: "Atomic sliding cap", min: 1 },
  { key: "window_24h_inr", label: "24-hour spend window (INR)", hint: "Atomic sliding cap", min: 1 },
  { key: "max_calls_per_min", label: "Velocity limit (calls / min)", hint: "Circuit-breaker per agent", min: 1, integer: true },
];

const inputCls =
  "figure h-9 w-full rounded-lg border border-hairline bg-white px-3 text-[13px] text-ink focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20";

function toDraft(p: PolicyConfig): Record<NumericKey, string> {
  return Object.fromEntries(NUMERIC_FIELDS.map((f) => [f.key, String(p[f.key])])) as Record<NumericKey, string>;
}

export function PolicyEditor({ policy, onSaved }: { policy: PolicyConfig; onSaved: (p: PolicyConfig, msg: string) => void }) {
  const [mode, setMode] = useState(policy.mode);
  const [nums, setNums] = useState(() => toDraft(policy));
  const [tools, setTools] = useState<string[]>(policy.allowed_tools);
  const [merchants, setMerchants] = useState<string[]>(policy.allowed_merchants);
  const [newMerchant, setNewMerchant] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const parsed = useMemo(() => {
    const out: Partial<Record<NumericKey, number>> = {};
    const errors: Partial<Record<NumericKey, string>> = {};
    for (const f of NUMERIC_FIELDS) {
      const v = Number(nums[f.key]);
      if (nums[f.key].trim() === "" || !Number.isFinite(v)) errors[f.key] = "Required";
      else if (v < f.min) errors[f.key] = `Must be ≥ ${f.min}`;
      else if (f.integer && !Number.isInteger(v)) errors[f.key] = "Whole number";
      else out[f.key] = v;
    }
    return { values: out, errors };
  }, [nums]);

  const next: PolicyConfig | null =
    Object.keys(parsed.errors).length === 0
      ? { ...policy, mode, ...(parsed.values as Record<NumericKey, number>), allowed_tools: tools, allowed_merchants: merchants }
      : null;
  const dirty = next !== null && JSON.stringify(next) !== JSON.stringify(policy);
  const unreachable = next && next.max_single_txn_inr > next.window_1m_inr;

  const save = async () => {
    if (!next) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await updatePolicy(policy.policy_id, next);
      onSaved(saved, `Saved ${saved.policy_id} — live on the next intercepted call.`);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const addMerchant = () => {
    const m = newMerchant.trim().toLowerCase().replace(/\s+/g, "_");
    if (m && !merchants.includes(m)) setMerchants([...merchants, m]);
    setNewMerchant("");
  };

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-hairline px-5 py-3.5">
        <div>
          <h2 className="text-[14px] font-semibold text-ink">Active Treasury Policy Controls</h2>
          <p className="mt-0.5 text-[12.5px] text-ink-3">
            <span className="figure">{policy.policy_id}</span> · {policy.name}
          </p>
        </div>
        <Button onClick={save} disabled={!dirty || saving}>
          <Save className="size-4" aria-hidden="true" />
          {saving ? "Saving…" : "Save Policy Changes"}
        </Button>
      </div>

      {/* enforcement mode */}
      <div className="border-b border-hairline px-5 py-4">
        <p className="text-[12px] font-medium text-ink-2">Enforcement mode</p>
        <div role="radiogroup" aria-label="Enforcement mode" className="mt-2 grid grid-cols-2 gap-2 sm:max-w-md">
          {(["enforce", "shadow"] as const).map((m) => {
            const active = mode === m;
            return (
              <button
                key={m}
                role="radio"
                aria-checked={active}
                onClick={() => setMode(m)}
                className={cn(
                  "flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-[13px] font-semibold tracking-wide transition-colors focus-visible:outline-2 focus-visible:outline-indigo-600",
                  active && m === "enforce" && "border-emerald-600 bg-emerald-50 text-emerald-800 ring-1 ring-emerald-600",
                  active && m === "shadow" && "border-amber-500 bg-amber-50 text-amber-800 ring-1 ring-amber-500",
                  !active && "border-hairline bg-white text-ink-3 hover:bg-slate-50",
                )}
              >
                <span className={cn("size-2 rounded-full", m === "enforce" ? "bg-allow" : "bg-escalate")} aria-hidden="true" />
                {m.toUpperCase()}
              </button>
            );
          })}
        </div>
        <p className="mt-2 text-[12.5px] text-ink-3">
          {mode === "shadow"
            ? "Shadow Mode logs violations as SHADOW_FLAG without blocking live settlements — ideal for zero-risk enterprise onboarding."
            : "Enforce Mode blocks violations before any rupee moves; escalations park the sealed payload for HITL review."}
        </p>
      </div>

      {/* numeric limits */}
      <div className="grid gap-x-4 gap-y-3.5 border-b border-hairline px-5 py-4 sm:grid-cols-2">
        {NUMERIC_FIELDS.map((f) => {
          const err = parsed.errors[f.key];
          return (
            <div key={f.key}>
              <label htmlFor={`pf-${f.key}`} className="text-[12px] font-medium text-ink-2">
                {f.label}
              </label>
              <input
                id={`pf-${f.key}`}
                type="number"
                inputMode="decimal"
                min={f.min}
                step={f.integer ? 1 : "any"}
                value={nums[f.key]}
                aria-invalid={!!err}
                onChange={(e) => setNums((n) => ({ ...n, [f.key]: e.target.value }))}
                className={cn(inputCls, "mt-1", err && "border-red-400 focus:border-red-500 focus:ring-red-500/20")}
              />
              <p className={cn("mt-1 text-[11.5px]", err ? "text-red-700" : "text-ink-3")}>
                {err ?? (f.integer ? f.hint : `${formatINR(Number(nums[f.key]) || 0, { decimals: false })} · ${f.hint}`)}
              </p>
            </div>
          );
        })}
        {unreachable && (
          <p className="flex items-start gap-1.5 rounded-lg bg-amber-50 px-3 py-2 text-[12px] text-amber-900 sm:col-span-2">
            <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            Payouts between {formatINR(next.window_1m_inr, { decimals: false })} and {formatINR(next.max_single_txn_inr, { decimals: false })} can never
            clear the 1-minute window, so the single-transaction cap is effectively lower.
          </p>
        )}
      </div>

      {/* allowlists */}
      <div className="space-y-4 border-b border-hairline px-5 py-4">
        <div>
          <p className="text-[12px] font-medium text-ink-2">Allowed tools</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {Array.from(new Set([...KNOWN_TOOLS, ...tools])).map((t) => {
              const on = tools.includes(t);
              return (
                <button
                  key={t}
                  aria-pressed={on}
                  onClick={() => setTools(on ? tools.filter((x) => x !== t) : [...tools, t])}
                  className={cn(
                    "figure rounded-md border px-2 py-1 text-[12px] transition-colors focus-visible:outline-2 focus-visible:outline-indigo-600",
                    on ? "border-indigo-300 bg-indigo-50 text-indigo-800" : "border-dashed border-slate-300 bg-white text-ink-3 line-through",
                  )}
                >
                  {t}
                </button>
              );
            })}
          </div>
        </div>
        <div>
          <p className="text-[12px] font-medium text-ink-2">Allowed merchants</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {merchants.map((m) => (
              <span key={m} className="figure inline-flex items-center gap-1 rounded-md border border-hairline bg-canvas py-1 pl-2 pr-1 text-[12px] text-ink-2">
                {m}
                <button onClick={() => setMerchants(merchants.filter((x) => x !== m))} className="rounded p-0.5 text-ink-3 hover:bg-slate-200 hover:text-ink" aria-label={`Remove merchant ${m}`}>
                  <X className="size-3" />
                </button>
              </span>
            ))}
            <form
              className="flex items-center gap-1"
              onSubmit={(e) => {
                e.preventDefault();
                addMerchant();
              }}
            >
              <label htmlFor="new-merchant" className="sr-only">Add merchant</label>
              <input id="new-merchant" value={newMerchant} onChange={(e) => setNewMerchant(e.target.value)} placeholder="add_merchant_id" className={cn(inputCls, "h-8 w-40")} />
              <Button type="submit" variant="secondary" size="sm" disabled={!newMerchant.trim()} aria-label="Add merchant">
                <Plus className="size-3.5" aria-hidden="true" />
              </Button>
            </form>
          </div>
        </div>
        {error && <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-[12.5px] text-red-700">{error}</p>}
      </div>

      {/* RBI regulatory floor */}
      <div className="px-5 py-4">
        <div className="rounded-xl border border-slate-300 bg-slate-50 p-4">
          <p className="flex items-center gap-2 text-[13px] font-semibold text-ink">
            <Lock className="size-4 text-ink-2" aria-hidden="true" />
            Immutable RBI Nov 2026 Regulatory Floor
            <span className="ml-auto rounded-md bg-white px-1.5 py-0.5 text-[11px] font-medium text-ink-3 ring-1 ring-hairline">Locked</span>
          </p>
          <ul className="mt-3 space-y-2.5 text-[12.5px]">
            <li className="flex items-start gap-2.5">
              <ShieldCheck className="mt-0.5 size-4 shrink-0 text-emerald-700" aria-hidden="true" />
              <span>
                <span className="figure font-medium text-ink">RBI/DPSS/2026-27/475</span>
                <span className="text-ink-2"> · 12-hour minimum cooling period after a contact change (current: </span>
                <span className="figure text-ink">{policy.rbi_cooling_period_hours}h</span>
                <span className="text-ink-2">)</span>
              </span>
            </li>
            <li className="flex items-start gap-2.5">
              <ShieldCheck className="mt-0.5 size-4 shrink-0 text-emerald-700" aria-hidden="true" />
              <span>
                <span className="figure font-medium text-ink">RBI/DPSS/2025-26/141</span>
                <span className="text-ink-2"> · Refunds only to the original payment source (</span>
                <span className="figure text-ink">{policy.enforce_original_source_refund ? "enforced" : "OFF"}</span>
                <span className="text-ink-2">)</span>
              </span>
            </li>
          </ul>
          <p className="mt-3 text-[11.5px] text-ink-3">These guardrails cannot be edited here, and the policy compiler clamps any instruction that would weaken them.</p>
        </div>
      </div>
    </Card>
  );
}
