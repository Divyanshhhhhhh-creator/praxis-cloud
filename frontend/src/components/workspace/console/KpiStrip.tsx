"use client";

import { Line, LineChart, ReferenceLine, Tooltip, YAxis } from "recharts";
import type { AuditDecision, MetricsSummary } from "@/lib/types";
import { formatINR, formatMs } from "@/lib/format";
import { Card, StatTile } from "../ui";

const L2_BUDGET_MS = 2500;

function L2Sparkline({ audits }: { audits: AuditDecision[] }) {
  const data = audits
    .filter((a) => a.l2_latency_ms > 0)
    .slice(0, 20)
    .reverse()
    .map((a, i) => ({ i, ms: Math.round(a.l2_latency_ms) }));
  if (data.length < 2) return null;
  const max = Math.max(L2_BUDGET_MS * 1.15, ...data.map((d) => d.ms));
  return (
    <div className="mt-1.5" aria-label={`Recent Layer 2 latencies, last ${data.length} audited calls`}>
      <LineChart width={150} height={34} data={data} margin={{ top: 3, right: 2, bottom: 3, left: 2 }}>
        <YAxis hide domain={[0, max]} />
        <ReferenceLine y={L2_BUDGET_MS} stroke="#D97706" strokeDasharray="3 3" strokeWidth={1} />
        <Tooltip
          cursor={{ stroke: "#CBD5E1", strokeWidth: 1 }}
          contentStyle={{ fontSize: 11, padding: "2px 6px", borderRadius: 6, borderColor: "#E2E8F0" }}
          labelFormatter={() => "Layer 2"}
          formatter={(v) => [formatMs(Number(v)), "latency"]}
        />
        <Line type="monotone" dataKey="ms" stroke="#4F46E5" strokeWidth={2} dot={false} activeDot={{ r: 4 }} isAnimationActive={false} />
      </LineChart>
    </div>
  );
}

export function KpiStrip({ metrics, audits, pendingCount, pendingHeldInr }: { metrics: MetricsSummary | null; audits: AuditDecision[]; pendingCount: number; pendingHeldInr: number }) {
  const m = metrics;
  return (
    <Card className="grid grid-cols-2 overflow-hidden lg:grid-cols-4">
      <StatTile
        label="Protected from Fraud (INR)"
        value={m ? formatINR(m.total_inr_protected) : "—"}
        sub={m ? `${m.blocked_count} blocked · ${m.escalated_count} escalated` : "Connecting…"}
      />
      <div className="border-l border-hairline">
        <StatTile
          label="Settled via Razorpay (INR)"
          value={m ? formatINR(m.total_inr_settled) : "—"}
          sub={m ? `${m.allowed_count + m.shadow_flagged_count} settlements · Test Mode` : "Connecting…"}
        />
      </div>
      <div className="border-t border-hairline px-5 py-4 lg:border-t-0 lg:border-l">
        <p className="text-[12px] font-medium text-ink-3">Avg L1 / L2 Latency</p>
        <p className="figure mt-1 whitespace-nowrap text-[17px] font-semibold leading-tight text-ink sm:text-[22px]">
          {m ? formatMs(m.avg_l1_latency_ms) : "—"}
          <span className="mx-1.5 text-ink-3">/</span>
          {m ? formatMs(m.avg_l2_latency_ms) : "—"}
        </p>
        <div className="flex flex-wrap items-center gap-x-2">
          <L2Sparkline audits={audits} />
          <span className="figure whitespace-nowrap text-[11px] text-amber-800">– – 2.5 s budget</span>
        </div>
      </div>
      <div className="border-t border-l border-hairline lg:border-t-0">
        <StatTile
          label="Pending HITL Queue"
          href="/approvals"
          value={pendingCount}
          sub={<span>{formatINR(pendingHeldInr, { decimals: false })} held · <span className="text-indigo-700">Review →</span></span>}
        />
      </div>
    </Card>
  );
}
