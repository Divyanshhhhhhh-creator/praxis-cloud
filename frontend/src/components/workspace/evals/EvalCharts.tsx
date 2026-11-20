"use client";

import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { EvalCaseResult, EvalRun } from "@/lib/types";
import { formatMs } from "@/lib/format";
import { Card, CardHeader } from "../ui";

// Validated categorical pair (dataviz validator: CVD ΔE 16.4, normal ΔE 21.4, contrast ≥ 3:1)
const L1_COLOR = "#4F46E5";
const L2_COLOR = "#0891B2";
const AXIS = { fontSize: 11, fill: "#64748B" };

function decisionMs(c: EvalCaseResult) {
  return Math.max(0.001, c.l1_latency_ms + c.l2_latency_ms);
}

interface LatencyDatum {
  id: string;
  title: string;
  layer: "L1" | "L2";
  ms: number;
  l1: number;
  l2: number;
}

function LatencyTooltip({ active, payload }: { active?: boolean; payload?: { payload: LatencyDatum }[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-lg border border-hairline bg-white px-3 py-2 text-[12px] shadow-md">
      <p className="font-semibold text-ink">
        <span className="figure">{d.id}</span> · {d.title}
      </p>
      <p className="mt-0.5 text-ink-2">
        {d.layer === "L1" ? "L1 Deterministic" : "L2 Gemini Multimodal"} · <span className="figure">{formatMs(d.ms)}</span>
      </p>
      <p className="figure text-ink-3">
        L1 {formatMs(d.l1)} · L2 {d.l2 > 0 ? formatMs(d.l2) : "—"}
      </p>
    </div>
  );
}

export function LatencyByCaseChart({ run }: { run: EvalRun }) {
  const data: LatencyDatum[] = run.cases
    .filter((c) => c.actual_verdict !== "SKIPPED" && c.actual_verdict !== "ERROR")
    .map((c) => ({
      id: c.case_id,
      title: c.title,
      layer: c.actual_layer === "L2_GEMINI_AUDITOR" ? "L2" : "L1",
      ms: decisionMs(c),
      l1: c.l1_latency_ms,
      l2: c.l2_latency_ms,
    }));
  return (
    <Card>
      <CardHeader
        title="Decision Latency by Case"
        subtitle="Milliseconds per decided call · log scale (L1 is ~10,000× faster than a Gemini round-trip)"
        right={
          <div className="flex items-center gap-3 text-[12px] text-ink-2" aria-label="Legend">
            <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm" style={{ background: L1_COLOR }} />L1 Deterministic</span>
            <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm" style={{ background: L2_COLOR }} />L2 Gemini Multimodal</span>
          </div>
        }
      />
      <div className="h-[340px] px-2 py-3">
        <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 640, height: 320 }}>
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 84, bottom: 4, left: 8 }} barCategoryGap={4}>
            <CartesianGrid horizontal={false} stroke="#EEF2F6" />
            <XAxis type="number" scale="log" domain={[0.001, "auto"]} allowDataOverflow tick={AXIS} tickFormatter={(v) => formatMs(Number(v))} axisLine={false} tickLine={false} />
            <YAxis type="category" dataKey="id" width={52} tick={{ ...AXIS, fontFamily: "var(--font-mono)" }} axisLine={false} tickLine={false} />
            <Tooltip content={<LatencyTooltip />} cursor={{ fill: "#F1F5F9" }} />
            <Bar dataKey="ms" radius={[0, 4, 4, 0]} isAnimationActive={false} maxBarSize={18}>
              {data.map((d) => (
                <Cell key={d.id} fill={d.layer === "L1" ? L1_COLOR : L2_COLOR} />
              ))}
              <LabelList dataKey="ms" position="right" formatter={(v) => formatMs(Number(v))} style={{ fontSize: 11, fill: "#334155", fontFamily: "var(--font-mono)" }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

export function DefenseDistributionChart({ run }: { run: EvalRun }) {
  const data = run.defense_distribution;
  const total = data.reduce((s, d) => s + d.count, 0);
  return (
    <Card>
      <CardHeader title="Defense Layer Distribution" subtitle={`Where each of the ${total} decided cases was resolved`} />
      <div className="h-[340px] px-2 py-3">
        <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 420, height: 320 }}>
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 40, bottom: 4, left: 8 }} barCategoryGap={10}>
            <CartesianGrid horizontal={false} stroke="#EEF2F6" />
            <XAxis type="number" allowDecimals={false} tick={AXIS} axisLine={false} tickLine={false} domain={[0, "dataMax"]} />
            <YAxis type="category" dataKey="bucket" width={170} tick={AXIS} axisLine={false} tickLine={false} />
            <Tooltip
              cursor={{ fill: "#F1F5F9" }}
              contentStyle={{ fontSize: 12, borderRadius: 8, borderColor: "#E2E8F0" }}
              formatter={(v) => [`${v} case${Number(v) === 1 ? "" : "s"}`, "Resolved"]}
            />
            <Bar dataKey="count" fill={L1_COLOR} radius={[0, 4, 4, 0]} isAnimationActive={false} maxBarSize={22}>
              <LabelList dataKey="count" position="right" style={{ fontSize: 12, fill: "#0F172A", fontFamily: "var(--font-mono)", fontWeight: 600 }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
