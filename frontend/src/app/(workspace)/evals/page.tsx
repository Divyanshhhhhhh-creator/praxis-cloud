"use client";

import { getMetrics } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { formatINR, formatMs } from "@/lib/format";
import { SCENARIOS } from "@/lib/scenarios";
import { Card, CardHeader, StatTile, VerdictPill } from "@/components/workspace/ui";
import { PageTitle } from "@/components/workspace/PageTitle";

export default function EvalsPage() {
  const metrics = usePolling(() => getMetrics(), 10_000);
  const m = metrics.data;

  return (
    <div className="space-y-5">
      <PageTitle
        title="Red-Team Evals"
        subtitle="The 12-case adversarial FinTech benchmark (prompt injection, hallucinated amounts, RBI guards, velocity, fail-closed chaos) runs here in Slice 5. Live firewall totals below."
        count={m ? `${m.total_requests} decisions logged` : undefined}
      />

      <Card className="grid grid-cols-2 divide-hairline lg:grid-cols-5 lg:divide-x">
        <StatTile label="Allowed" value={m?.allowed_count ?? "—"} />
        <StatTile label="Blocked" value={m?.blocked_count ?? "—"} />
        <StatTile label="Escalated" value={m?.escalated_count ?? "—"} />
        <StatTile label="Protected (INR)" value={m ? formatINR(m.total_inr_protected, { decimals: false }) : "—"} />
        <StatTile label="Avg L1 / L2" value={m ? `${formatMs(m.avg_l1_latency_ms)} / ${formatMs(m.avg_l2_latency_ms)}` : "—"} />
      </Card>

      <Card>
        <CardHeader title="Attack scenarios available in the Live Console" subtitle="Each runs against live Gemini and Razorpay Test Mode" />
        <ul className="divide-y divide-hairline">
          {SCENARIOS.map((s) => (
            <li key={s.id} className="flex flex-col gap-1 px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-[13.5px] font-medium text-ink">{s.title}</p>
                <p className="text-[12.5px] text-ink-3">{s.blurb}</p>
              </div>
              <div className="flex items-center gap-2">
                <VerdictPill verdict={s.expect} />
                <span className="figure text-[12px] text-ink-3">{s.expectDetail}</span>
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
