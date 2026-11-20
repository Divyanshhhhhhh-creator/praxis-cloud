import type { MetricsSummary } from "@/lib/types";
import { cn, formatINR } from "@/lib/format";
import { Card, CardHeader } from "../ui";

function Meter({ label, used, limit, kind }: { label: string; used: number; limit: number; kind: "inr" | "calls" }) {
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;
  const state = pct >= 100 ? "cap" : pct >= 80 ? "near" : "ok";
  const fmt = (n: number) => (kind === "inr" ? formatINR(n, { decimals: false }) : `${n}`);
  return (
    <div className="px-5 py-4">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-[12.5px] font-medium text-ink-2">{label}</p>
        {state !== "ok" && (
          <span className={cn("text-[11px] font-semibold", state === "cap" ? "text-red-700" : "text-amber-800")}>
            {state === "cap" ? "At cap" : "Near cap"}
          </span>
        )}
      </div>
      <p className="figure mt-1 text-[15px] text-ink">
        {fmt(used)} <span className="text-ink-3">/ {fmt(limit)}{kind === "calls" ? " calls" : ""}</span>
      </p>
      <div
        className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-slate-100"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={limit}
        aria-valuenow={used}
      >
        <div
          className={cn("h-full rounded-full transition-[width] duration-500", state === "cap" ? "bg-block" : state === "near" ? "bg-escalate" : "bg-indigo-600")}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export function SpendWindows({ metrics }: { metrics: MetricsSummary | null }) {
  const w = metrics?.window_usage;
  return (
    <Card>
      <CardHeader
        title="Treasury Spend Windows"
        subtitle="Atomic sliding-window reservations for the default treasury policy (all agents). Held HITL budget counts until released."
      />
      {w ? (
        <div className="grid grid-cols-1 divide-y divide-hairline sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-4 lg:divide-x">
          <Meter label="1-Min Spend" used={w.used_1m_inr} limit={w.limit_1m_inr} kind="inr" />
          <Meter label="1-Hour Spend" used={w.used_1h_inr} limit={w.limit_1h_inr} kind="inr" />
          <Meter label="24-Hour Spend" used={w.used_24h_inr} limit={w.limit_24h_inr} kind="inr" />
          <Meter label="1-Min Call Velocity" used={w.calls_1m} limit={w.limit_calls_1m} kind="calls" />
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 p-5 lg:grid-cols-4" aria-hidden="true">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-14 animate-pulse rounded-lg bg-slate-100" />
          ))}
        </div>
      )}
    </Card>
  );
}
