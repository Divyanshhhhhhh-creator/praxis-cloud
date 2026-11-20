"use client";

import { getPolicies } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { formatINR } from "@/lib/format";
import { Card, CardHeader, EmptyNotice, MonoPill } from "@/components/workspace/ui";
import { PageTitle } from "@/components/workspace/PageTitle";

export default function PoliciesPage() {
  const policies = usePolling(getPolicies, 15_000);
  const rows = policies.data ?? [];

  return (
    <div className="space-y-5">
      <PageTitle
        title="Policy Studio"
        subtitle="Treasury policies enforced by Layer 1 and grounded into the Layer 2 auditor. Plain-English compilation (gemini-3.6-flash) lands in Slice 5."
        count={`${rows.length} ${rows.length === 1 ? "policy" : "policies"}`}
      />
      <Card>
        <CardHeader title="Active policies" subtitle="Live from GET /v1/policies" />
        {policies.error && !rows.length ? (
          <EmptyNotice title="API offline" body={policies.error} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-[13px]">
              <thead className="border-b border-hairline bg-canvas text-[12px] text-ink-3">
                <tr>
                  {["Policy", "Mode", "Single txn cap", "Auto-approve ≤", "1m / 1h / 24h windows", "Velocity", "RBI cooling", "Merchants"].map((h) => (
                    <th key={h} scope="col" className="px-4 py-2.5 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {rows.map((p) => (
                  <tr key={p.policy_id} className="align-top">
                    <td className="px-4 py-3">
                      <div className="font-medium text-ink">{p.name}</div>
                      <div className="figure text-[12px] text-ink-3">{p.policy_id}</div>
                    </td>
                    <td className="px-4 py-3">
                      <MonoPill className={p.mode === "shadow" ? "border-slate-300" : "border-emerald-200 bg-emerald-50 text-emerald-800"}>{p.mode}</MonoPill>
                    </td>
                    <td className="figure px-4 py-3">{formatINR(p.max_single_txn_inr, { decimals: false })}</td>
                    <td className="figure px-4 py-3">{formatINR(p.auto_approve_threshold_inr, { decimals: false })}</td>
                    <td className="figure px-4 py-3">
                      {formatINR(p.window_1m_inr, { decimals: false })} / {formatINR(p.window_1h_inr, { decimals: false })} / {formatINR(p.window_24h_inr, { decimals: false })}
                    </td>
                    <td className="figure px-4 py-3">{p.max_calls_per_min}/min</td>
                    <td className="figure px-4 py-3">
                      {p.rbi_cooling_period_hours}h{p.enforce_original_source_refund ? " · source-only refunds" : ""}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {p.allowed_merchants.map((m) => (
                          <MonoPill key={m}>{m}</MonoPill>
                        ))}
                      </div>
                    </td>
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

