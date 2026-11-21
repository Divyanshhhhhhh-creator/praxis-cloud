"use client";

import { motion, useReducedMotion } from "framer-motion";
import { Bot, Gauge, ScanEye, Vault } from "lucide-react";
import { cn } from "@/lib/format";

const STAGES = [
  {
    n: "01",
    title: "Google ADK Agent",
    icon: Bot,
    accent: "text-indigo-300",
    glow: "shadow-[0_0_50px_-14px_rgba(99,102,241,0.9)]",
    points: ["Native before_tool_callback", "Zero Razorpay keys in process", "Local tool body raises if called"],
  },
  {
    n: "02",
    title: "Layer 1 Deterministic Engine",
    icon: Gauge,
    accent: "text-cyan-300",
    glow: "shadow-[0_0_50px_-14px_rgba(6,182,212,0.9)]",
    points: ["<1 ms local checks · ~50 ms Firestore Tx", "Atomic 1m / 1h / 24h spend caps", "RBI 12-hr cooling & original-source guards"],
  },
  {
    n: "03",
    title: "Layer 2 Grounded Gemini Auditor",
    icon: ScanEye,
    accent: "text-violet-300",
    glow: "shadow-[0_0_50px_-14px_rgba(139,92,246,0.9)]",
    points: ["gemini-3.5-flash-lite multimodal PDF", "gemini-embedding-2 Policy RAG", "Monotonic: can only tighten"],
  },
  {
    n: "04",
    title: "Vaulted Razorpay Rail & HITL",
    icon: Vault,
    accent: "text-emerald-300",
    glow: "shadow-[0_0_50px_-14px_rgba(16,185,129,0.9)]",
    points: ["SHA-256 anti-TOCTOU execution", "Live order_… / rfnd_… settlement", "1-click Finance Manager hold"],
  },
];

export function PipelineSection() {
  const reduce = useReducedMotion();
  return (
    <section id="architecture" className="relative scroll-mt-24 py-28" aria-labelledby="architecture-title">
      <div className="mx-auto max-w-7xl px-5">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.6 }}
          className="max-w-3xl"
        >
          <p className="text-xs font-semibold tracking-[0.2em] text-cyan-300">THE INTERCEPTION PIPELINE</p>
          <h2 id="architecture-title" className="font-display mt-4 text-4xl font-bold tracking-[-0.03em] text-metal sm:text-5xl">
            Every tool call crosses four checkpoints before a single rupee moves.
          </h2>
          <p className="mt-5 text-lg text-slate-400">
            The agent proposes. Praxis seals the payload, evaluates it in sub-millisecond deterministic code, grounds a Gemini
            audit in your treasury policy — and only then lets the vault touch Razorpay.
          </p>
        </motion.div>

        <div className="relative mt-16">
          {/* rail + travelling data packet (desktop) */}
          <div aria-hidden="true" className="absolute left-[6%] right-[6%] top-[52px] hidden h-px bg-linear-to-r from-indigo-500/0 via-slate-500/50 to-emerald-500/0 lg:block">
            {!reduce && (
              <motion.span
                className="absolute -top-[5px] size-[11px] rounded-full bg-cyan-300 shadow-[0_0_18px_4px_rgba(34,211,238,0.85)]"
                initial={{ left: "0%", opacity: 0 }}
                whileInView={{ left: ["0%", "100%"], opacity: [0, 1, 1, 0] }}
                viewport={{ once: false }}
                transition={{ duration: 3.4, ease: "easeInOut", repeat: Infinity, repeatDelay: 0.6 }}
              />
            )}
          </div>

          <ol className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {STAGES.map((s, i) => (
              <motion.li
                key={s.n}
                initial={{ opacity: 0, y: 30 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-60px" }}
                transition={{ duration: 0.55, delay: i * 0.12 }}
                className="relative"
              >
                <div className={cn("relative mx-auto grid size-[104px] place-items-center rounded-3xl border border-white/10 bg-linear-to-b from-slate-800/80 to-slate-950", s.glow)}>
                  <div className="absolute inset-px rounded-[23px] bg-linear-to-b from-white/10 to-transparent opacity-40" aria-hidden="true" />
                  <s.icon className={cn("relative size-9", s.accent)} aria-hidden="true" />
                </div>
                <div className="mt-6 rounded-2xl border border-white/[0.07] bg-white/[0.03] p-5 backdrop-blur-sm">
                  <div className="figure text-xs text-slate-500">{s.n}</div>
                  <h3 className="font-display mt-1 text-lg font-semibold text-white">{s.title}</h3>
                  <ul className="mt-3 space-y-1.5">
                    {s.points.map((p) => (
                      <li key={p} className="flex gap-2 text-sm text-slate-400">
                        <span className={cn("mt-2 size-1 shrink-0 rounded-full bg-current", s.accent)} aria-hidden="true" />
                        <span>{p}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </motion.li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
