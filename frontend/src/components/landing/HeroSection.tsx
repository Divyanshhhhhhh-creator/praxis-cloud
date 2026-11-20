"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { motion, useReducedMotion } from "framer-motion";
import { ArrowRight, Cpu, KeyRound, ShieldCheck, Sparkles } from "lucide-react";
import { getHealth, getMetrics } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { cn, formatINR, formatMs } from "@/lib/format";

const HeroVaultCanvas = dynamic(() => import("./HeroVaultCanvas"), {
  ssr: false,
  loading: () => <div className="absolute inset-0 animate-pulse rounded-full bg-indigo-500/5 blur-3xl" />,
});

function HudCard({
  label,
  icon: Icon,
  value,
  sub,
  accent,
  delay,
  className,
}: {
  label: string;
  icon: typeof ShieldCheck;
  value: string;
  sub: string;
  accent: "emerald" | "cyan" | "indigo";
  delay: number;
  className?: string;
}) {
  const reduce = useReducedMotion();
  const ring = {
    emerald: "from-emerald-400/50 shadow-[0_0_30px_-10px_rgba(16,185,129,0.8)]",
    cyan: "from-cyan-400/50 shadow-[0_0_30px_-10px_rgba(6,182,212,0.8)]",
    indigo: "from-indigo-400/50 shadow-[0_0_30px_-10px_rgba(99,102,241,0.8)]",
  }[accent];
  const iconColor = { emerald: "text-emerald-300", cyan: "text-cyan-300", indigo: "text-indigo-300" }[accent];

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={reduce ? { opacity: 1, y: 0 } : { opacity: 1, y: [0, -7, 0] }}
      transition={
        reduce
          ? { duration: 0.4, delay }
          : { opacity: { duration: 0.6, delay }, y: { duration: 6, delay, repeat: Infinity, ease: "easeInOut" } }
      }
      className={cn("rounded-2xl bg-linear-to-b to-transparent p-px", ring, className)}
    >
      <div className="rounded-[15px] border border-white/5 bg-slate-950/70 px-4 py-3.5 backdrop-blur-xl">
        <div className="flex items-center gap-2 text-[10.5px] font-semibold tracking-[0.18em] text-slate-400">
          <Icon className={cn("size-3.5", iconColor)} aria-hidden="true" />
          {label}
        </div>
        <div className="figure mt-1.5 whitespace-nowrap text-xl font-semibold text-white">{value}</div>
        <div className="mt-0.5 text-xs text-slate-400">{sub}</div>
      </div>
    </motion.div>
  );
}

export function HeroSection() {
  const metrics = usePolling(() => getMetrics(), 12_000);
  const health = usePolling(getHealth, 30_000);
  const m = metrics.data;
  const l1 = m && m.avg_l1_latency_ms > 0 ? `${formatMs(m.avg_l1_latency_ms)} avg` : "<1.2 ms";
  const auditorModel = health.data?.layer2_auditor && health.data.layer2_auditor !== "disabled" ? health.data.layer2_auditor : "gemini-3.5-flash-lite";

  const hud = [
    {
      label: "TREASURY PROTECTED",
      icon: ShieldCheck,
      value: m ? formatINR(m.total_inr_protected, { decimals: false }) : "₹0",
      sub: "0 keys exposed to agents",
      accent: "emerald" as const,
    },
    {
      label: "LAYER 1 FIREWALL",
      icon: KeyRound,
      value: l1,
      sub: m ? `Atomic caps · ${m.window_usage.calls_1m}/${m.window_usage.limit_calls_1m} calls this min` : "Atomic 1m / 1h / 24h caps armed",
      accent: "cyan" as const,
    },
    {
      label: "MULTIMODAL AUDITOR",
      icon: Cpu,
      value: auditorModel === "gemini-3.5-flash-lite" ? "Gemini 3.5 Flash-Lite" : auditorModel,
      sub: "Fail-closed active · ≤2.5 s budget",
      accent: "indigo" as const,
    },
  ];

  return (
    <section className="relative isolate overflow-hidden pt-28 sm:pt-32" aria-labelledby="hero-title">
      {/* ambient rim lighting */}
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute inset-0 bg-grid-dark [mask-image:radial-gradient(ellipse_at_center,black_30%,transparent_75%)]" />
        <div className="absolute -left-40 top-10 size-[38rem] rounded-full bg-indigo-600/25 blur-[140px]" />
        <div className="absolute right-[-10rem] top-40 size-[34rem] rounded-full bg-cyan-500/15 blur-[140px]" />
        <div className="absolute bottom-[-12rem] left-1/3 size-[30rem] rounded-full bg-emerald-500/10 blur-[140px]" />
      </div>

      <div className="mx-auto grid min-h-[92vh] max-w-7xl items-center gap-10 px-5 pb-16 lg:grid-cols-12 lg:gap-6">
        <div className="relative z-10 lg:col-span-6">
          <motion.p
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-[10.5px] font-semibold tracking-[0.16em] text-slate-300 backdrop-blur"
          >
            <Sparkles className="size-3.5 text-cyan-300" aria-hidden="true" />
            GOOGLE ADK NATIVE • GEMINI MULTIMODAL • RBI NOV 2026 READY
          </motion.p>

          <motion.h1
            id="hero-title"
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.08 }}
            className="font-display mt-6 text-[2.6rem] font-bold leading-[1.02] tracking-[-0.035em] sm:text-6xl xl:text-7xl"
          >
            <span className="text-metal">Give Your AI Agents Autonomy — </span>
            <span className="text-aurora">Not a Blank Check.</span>
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.16 }}
            className="mt-6 max-w-xl text-base leading-relaxed text-slate-300 sm:text-lg"
          >
            Praxis is a vaulted governance firewall between autonomous AI agents and live Razorpay settlement rails.
            Every refund and payout is sealed, audited by deterministic limits and Gemini, then settled — or held for a human.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.24 }}
            className="mt-9 flex flex-wrap items-center gap-3"
          >
            <Link
              href="/console"
              className="group inline-flex h-12 items-center gap-2 rounded-xl bg-linear-to-b from-indigo-400 via-indigo-500 to-indigo-700 px-6 text-[15px] font-semibold text-white shadow-[0_0_40px_-6px_rgba(99,102,241,0.95),inset_0_1px_0_rgba(255,255,255,0.35)] transition hover:brightness-110 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300"
            >
              Enter Live Console
              <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" aria-hidden="true" />
            </Link>
            <a
              href="#architecture"
              className="inline-flex h-12 items-center rounded-xl border border-white/15 bg-white/[0.05] px-6 text-[15px] font-medium text-slate-100 backdrop-blur transition hover:border-white/30 hover:bg-white/[0.09]"
            >
              Explore Architecture
            </a>
          </motion.div>
        </div>

        <div className="relative lg:col-span-6">
          <div className="relative mx-auto aspect-square w-full max-w-[640px]">
            <HeroVaultCanvas />
          </div>
          {/* HUD: anchored around the vault on large screens, stacked below on small */}
          <div className="mt-2 grid gap-3 sm:grid-cols-3 lg:mt-0 lg:block">
            <HudCard {...hud[0]} delay={0.5} className="lg:absolute lg:left-0 lg:top-[8%] lg:w-56" />
            <HudCard {...hud[1]} delay={0.7} className="lg:absolute lg:right-0 lg:top-[40%] lg:w-56" />
            <HudCard {...hud[2]} delay={0.9} className="lg:absolute lg:bottom-[6%] lg:left-[6%] lg:w-[17rem]" />
          </div>
        </div>
      </div>
    </section>
  );
}
