"use client";

import { useState } from "react";
import { ArrowRight, CircleCheck, LoaderCircle, Lock, Sparkles, Wand2 } from "lucide-react";
import { actionError, compilePolicy, errorMessage, updatePolicy } from "@/lib/api";
import { ActionError } from "../ReviewerAuth";
import { useElapsed } from "@/lib/hooks";
import { cn, formatMs } from "@/lib/format";
import type { CompileResult, PolicyConfig } from "@/lib/types";
import { Button, Card, MonoPill } from "../ui";

const EXAMPLES = [
  "Tighten auto-approve to ₹2,500 and cap 1-minute spend at ₹10,000",
  "Switch to Shadow Mode and allow vendor cloud_infra_gcp",
  "Disable the 12-hour RBI cooling period and allow alternate refund accounts",
];

const FIELD_LABEL: Partial<Record<keyof PolicyConfig, string>> = {
  name: "Name",
  mode: "Mode",
  max_single_txn_inr: "Single-txn cap",
  auto_approve_threshold_inr: "Auto-approve ≤",
  window_1m_inr: "1-min window",
  window_1h_inr: "1-hour window",
  window_24h_inr: "24-hour window",
  max_calls_per_min: "Calls / min",
  rbi_cooling_period_hours: "RBI cooling (h)",
  enforce_original_source_refund: "Original-source refunds",
  allowed_tools: "Allowed tools",
  allowed_merchants: "Allowed merchants",
};

function show(v: unknown): string {
  if (Array.isArray(v)) return v.length ? v.join(", ") : "∅";
  if (typeof v === "number") return v.toLocaleString("en-IN");
  return String(v);
}

function diff(before: PolicyConfig | null, after: PolicyConfig) {
  return (Object.keys(FIELD_LABEL) as (keyof PolicyConfig)[])
    .map((k) => ({ key: k, before: before ? before[k] : undefined, after: after[k] }))
    .filter((r) => JSON.stringify(r.before) !== JSON.stringify(r.after));
}

export function PolicyCompiler({
  policy,
  onApplied,
}: {
  policy: PolicyConfig;
  onApplied: (p: PolicyConfig, msg: string) => void;
}) {
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState<"compile" | "apply" | null>(null);
  const [result, setResult] = useState<CompileResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const elapsed = useElapsed(busy === "compile");

  const compile = async () => {
    setBusy("compile");
    setError(null);
    setResult(null);
    try {
      setResult(await compilePolicy(instruction.trim(), policy.policy_id, false));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  // Apply EXACTLY what was previewed (no second LLM pass that could differ from what the reviewer saw).
  const apply = async () => {
    if (!result) return;
    setBusy("apply");
    setError(null);
    try {
      const saved = await updatePolicy(result.policy.policy_id, result.policy);
      onApplied(saved, `Compiled policy applied live to ${saved.policy_id}.`);
      setResult(null);
      setInstruction("");
    } catch (e) {
      setError(actionError(e));
    } finally {
      setBusy(null);
    }
  };

  const changes = result ? diff(result.previous_policy, result.policy) : [];
  // Deterministic clamps ("RBI floor enforced: …") and the model's own refusals both count as RBI-floor notices.
  const isFloorNote = (s: string) => /RBI/i.test(s) && /(floor|cannot|refus|kept|not be relaxed)/i.test(s);
  const floorNotes = result?.changes_summary.filter(isFloorNote) ?? [];
  const otherNotes = result?.changes_summary.filter((s) => !isFloorNote(s)) ?? [];

  return (
    <Card>
      <div className="border-b border-hairline px-5 py-3.5">
        <h2 className="flex items-center gap-2 text-[14px] font-semibold text-ink">
          <Wand2 className="size-4 text-indigo-600" aria-hidden="true" />
          Plain-English Policy Compiler
        </h2>
        <p className="mt-0.5 text-[12.5px] text-ink-3">
          gemini-3.6-flash compiles a finance rule into a validated policy for <span className="figure">{policy.policy_id}</span>. Preview first, then apply.
        </p>
      </div>

      <div className="space-y-3 px-5 py-4">
        <label htmlFor="compile-instruction" className="text-[12px] font-medium text-ink-2">
          Treasury instruction
        </label>
        <textarea
          id="compile-instruction"
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          rows={3}
          maxLength={4000}
          placeholder="e.g. Cap hourly spend at ₹40,000 and only allow razorpay_refunds"
          className="w-full rounded-lg border border-hairline bg-white px-3 py-2 text-[13px] leading-relaxed text-ink placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
        />
        <div className="flex flex-col gap-1.5">
          {EXAMPLES.map((ex, i) => (
            <button
              key={ex}
              onClick={() => setInstruction(ex)}
              className={cn(
                "rounded-lg border px-3 py-2 text-left text-[12.5px] transition-colors focus-visible:outline-2 focus-visible:outline-indigo-600",
                i === 2 ? "border-red-200 bg-red-50/40 text-red-900 hover:bg-red-50" : "border-hairline bg-canvas text-ink-2 hover:bg-slate-100",
              )}
            >
              {i === 2 && <Lock className="mr-1.5 inline size-3.5 align-[-2px]" aria-hidden="true" />}“{ex}”
            </button>
          ))}
        </div>
        <Button onClick={compile} disabled={!instruction.trim() || busy !== null} className="w-full">
          {busy === "compile" ? <LoaderCircle className="size-4 animate-spin" aria-hidden="true" /> : <Sparkles className="size-4" aria-hidden="true" />}
          {busy === "compile" ? `Compiling with Gemini… ${(elapsed / 1000).toFixed(1)} s` : "Compile Preview (Gemini 3.6 Flash)"}
        </Button>
        <ActionError error={error} />
      </div>

      {result && (
        <div className="border-t border-hairline">
          <div className="flex flex-wrap items-center gap-1.5 px-5 pt-4">
            <MonoPill className="border-indigo-200 bg-indigo-50 text-indigo-800">{result.model_used}</MonoPill>
            {result.fallback_used && <MonoPill className="border-amber-200 bg-amber-50 text-amber-800">fallback after 429/5xx</MonoPill>}
            <MonoPill>{formatMs(result.latency_ms)}</MonoPill>
            <MonoPill>preview · not applied</MonoPill>
          </div>

          {floorNotes.length > 0 && (
            <div className="mx-5 mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3">
              <p className="flex items-center gap-1.5 text-[12.5px] font-semibold text-amber-900">
                <Lock className="size-3.5" aria-hidden="true" /> Praxis refused to weaken RBI mandates
              </p>
              <ul className="mt-1.5 space-y-1 text-[12px] text-amber-900">
                {floorNotes.map((n) => (
                  <li key={n}>• {n}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="px-5 pt-3">
            <p className="text-[12px] font-semibold uppercase tracking-[0.06em] text-ink-3">Changes summary</p>
            <ul className="mt-1.5 space-y-1 text-[12.5px] text-ink-2">
              {otherNotes.length ? otherNotes.map((n) => <li key={n}>• {n}</li>) : <li className="text-ink-3">No field changes requested.</li>}
            </ul>
          </div>

          <div className="px-5 py-3">
            <p className="text-[12px] font-semibold uppercase tracking-[0.06em] text-ink-3">Before → After</p>
            {changes.length ? (
              <table className="mt-1.5 w-full text-left text-[12.5px]">
                <tbody className="divide-y divide-hairline">
                  {changes.map((c) => (
                    <tr key={c.key}>
                      <th scope="row" className="py-1.5 pr-3 font-medium text-ink-2">{FIELD_LABEL[c.key]}</th>
                      <td className="figure py-1.5 text-red-700 line-through decoration-red-300">{show(c.before)}</td>
                      <td className="px-2 text-ink-3"><ArrowRight className="size-3.5" aria-hidden="true" /></td>
                      <td className="figure py-1.5 font-medium text-emerald-800">{show(c.after)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="mt-1.5 text-[12.5px] text-ink-3">The compiled policy is identical to the current one.</p>
            )}
          </div>

          <div className="flex gap-2 border-t border-hairline px-5 py-3.5">
            <Button variant="success" onClick={apply} disabled={busy !== null || changes.length === 0} className="flex-1">
              {busy === "apply" ? <LoaderCircle className="size-4 animate-spin" aria-hidden="true" /> : <CircleCheck className="size-4" aria-hidden="true" />}
              Apply Compiled Policy Live
            </Button>
            <Button variant="secondary" onClick={() => setResult(null)} disabled={busy !== null}>
              Discard
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
