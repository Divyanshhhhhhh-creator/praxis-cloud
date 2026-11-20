"use client";

import { useEffect, useState } from "react";
import { Download, FlaskConical, LoaderCircle, Play, ShieldCheck, TriangleAlert } from "lucide-react";
import { errorMessage, getLatestEval, isEvalRun, runRedTeamEval } from "@/lib/api";
import { useElapsed } from "@/lib/hooks";
import { cn, formatDateTime, formatINR, formatMs } from "@/lib/format";
import type { EvalRun } from "@/lib/types";
import { Button, Card, EmptyNotice, MonoPill } from "@/components/workspace/ui";
import { DefenseDistributionChart, LatencyByCaseChart } from "@/components/workspace/evals/EvalCharts";
import { BenchmarkTable } from "@/components/workspace/evals/BenchmarkTable";
import { useToast } from "@/components/workspace/Toast";

function MetricCard({ label, value, sub, tone }: { label: string; value: string; sub: React.ReactNode; tone: "emerald" | "indigo" | "slate" }) {
  return (
    <div className="px-5 py-4">
      <p className="text-[12px] font-medium text-ink-3">{label}</p>
      <p className={cn("figure mt-1 text-[28px] font-semibold leading-tight", tone === "emerald" ? "text-emerald-700" : tone === "indigo" ? "text-indigo-700" : "text-ink")}>{value}</p>
      <div className="mt-1 text-[12px] text-ink-3">{sub}</div>
    </div>
  );
}

export default function EvalsPage() {
  const [run, setRun] = useState<EvalRun | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "empty" | "error">("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const elapsed = useElapsed(running);
  const toast = useToast();

  useEffect(() => {
    let alive = true;
    getLatestEval()
      .then((r) => {
        if (!alive) return;
        if (isEvalRun(r)) {
          setRun(r);
          setState("ready");
        } else setState("empty");
      })
      .catch((e) => {
        if (!alive) return;
        setLoadError(errorMessage(e));
        setState("error");
      });
    return () => {
      alive = false;
    };
  }, []);

  const runLive = async () => {
    setRunning(true);
    setRunError(null);
    try {
      const r = await runRedTeamEval();
      setRun(r);
      setState("ready");
      toast.show(`Benchmark ${r.run_id} complete — ${r.passed_cases}/${r.total_cases} passed in ${r.duration_s}s.`);
    } catch (e) {
      setRunError(errorMessage(e));
    } finally {
      setRunning(false);
    }
  };

  const exportJson = () => {
    if (!run) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(run, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `praxis_redteam_${run.run_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const attacks = run?.cases.filter((c) => c.kind === "attack") ?? [];
  const failClosed = attacks.filter((c) => c.actual_verdict === "ESCALATE").length;

  return (
    <div className="space-y-5">
      {/* header bar */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-[22px] font-semibold tracking-tight text-ink">
            <FlaskConical className="size-5 text-indigo-600" aria-hidden="true" />
            Red-Team Adversarial Benchmark
          </h1>
          <p className="mt-1 max-w-3xl text-[13.5px] text-ink-3">
            12 realistic FinTech & RBI attacks and controls executed through the real Praxis proxy — Layer 1 deterministic engine plus live Gemini Layer 2 —
            on an isolated ledger with dry-run settlement (no Razorpay orders).
          </p>
          {run && (
            <p className="mt-1.5 text-[12.5px] text-ink-3">
              Last run <span className="figure text-ink-2">{formatDateTime(run.timestamp)}</span> · <span className="figure">{run.run_id}</span> · {run.duration_s}s
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={runLive} disabled={running}>
            {running ? <LoaderCircle className="size-4 animate-spin" aria-hidden="true" /> : <Play className="size-4" aria-hidden="true" />}
            {running ? `Running live… ${(elapsed / 1000).toFixed(1)} s` : "Run Live 12-Case Benchmark"}
          </Button>
          <Button variant="secondary" onClick={exportJson} disabled={!run}>
            <Download className="size-4" aria-hidden="true" /> Export Benchmark JSON
          </Button>
        </div>
      </div>

      {running && (
        <p role="status" className="rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2.5 text-[13px] text-indigo-900">
          Running 7 deterministic cases instantly, then 5 live Gemini cases sequentially with 1.5 s pacing (free-tier friendly). Typically 30–90 s.
        </p>
      )}
      {runError && <p role="alert" className="rounded-lg bg-red-50 px-4 py-2.5 text-[13px] text-red-700">Benchmark failed: {runError}</p>}

      {state === "loading" ? (
        <div className="space-y-4" aria-hidden="true">
          <div className="h-28 animate-pulse rounded-xl bg-slate-100" />
          <div className="h-80 animate-pulse rounded-xl bg-slate-100" />
        </div>
      ) : state === "error" ? (
        <Card><EmptyNotice title="API offline" body={loadError ?? "Could not load GET /v1/evals/latest."} /></Card>
      ) : state === "empty" || !run ? (
        <Card><EmptyNotice title="No benchmark has been run yet" body="Press “Run Live 12-Case Benchmark” to score Praxis against live Gemini." /></Card>
      ) : (
        <>
          <Card className="grid grid-cols-2 lg:grid-cols-4">
            <MetricCard
              label="Threat Neutralization Rate"
              tone="emerald"
              value={`${run.threat_neutralization_rate_pct}%`}
              sub={<>{run.attack_cases} attacks · {run.attack_block_rate_pct}% hard-blocked{failClosed ? ` · ${failClosed} failed closed to HITL` : ""}</>}
            />
            <div className="border-l border-hairline">
              <MetricCard label="Clean Traffic Pass Rate" tone="indigo" value={`${run.clean_pass_rate_pct}%`} sub={<>{run.clean_cases} legitimate payouts · false-positive check</>} />
            </div>
            <div className="border-t border-hairline lg:border-l lg:border-t-0">
              <MetricCard label="Median Layer 1 Latency" tone="slate" value={formatMs(run.median_l1_ms)} sub="Deterministic engine + atomic ledger" />
            </div>
            <div className="border-l border-t border-hairline lg:border-t-0">
              <MetricCard label="Median Layer 2 Latency" tone="slate" value={formatMs(run.median_l2_ms)} sub={<>{run.l2_model} · live Gemini (incl. RAG)</>} />
            </div>
          </Card>

          <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-2 py-1 font-semibold ring-1 ring-inset",
                run.zero_money_leaked ? "bg-emerald-50 text-emerald-800 ring-emerald-200" : "bg-red-50 text-red-700 ring-red-200",
              )}
            >
              {run.zero_money_leaked ? <ShieldCheck className="size-3.5" aria-hidden="true" /> : <TriangleAlert className="size-3.5" aria-hidden="true" />}
              {run.zero_money_leaked ? "Zero money leaked" : `${formatINR(run.attack_money_leaked_inr)} leaked`}
            </span>
            <MonoPill>{run.passed_cases}/{run.total_cases} cases passed</MonoPill>
            <MonoPill>{formatINR(run.attack_amount_neutralized_inr, { decimals: false })} attack value neutralized</MonoPill>
            <MonoPill>benchmark_eval_budget {run.benchmark_eval_budget_s}s · prod {run.production_l2_budget_s.text}s / {run.production_l2_budget_s.multimodal}s</MonoPill>
            <MonoPill>{run.dry_run_settlement ? "dry-run settlement" : "live settlement"}</MonoPill>
          </div>

          <div className="grid gap-5 xl:grid-cols-12">
            <div className="xl:col-span-7"><LatencyByCaseChart run={run} /></div>
            <div className="xl:col-span-5"><DefenseDistributionChart run={run} /></div>
          </div>

          <BenchmarkTable cases={run.cases} />
        </>
      )}
      {toast.node}
    </div>
  );
}
