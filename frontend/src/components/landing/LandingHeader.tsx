"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { getHealth } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { cn } from "@/lib/format";

const LINKS = [
  { href: "#architecture", label: "Architecture" },
  { href: "#compliance", label: "Compliance" },
  { href: "#security", label: "Security" },
];

export function PraxisMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={cn("size-6", className)} aria-hidden="true">
      <defs>
        <linearGradient id="praxis-mark" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#818cf8" />
          <stop offset="0.55" stopColor="#22d3ee" />
          <stop offset="1" stopColor="#34d399" />
        </linearGradient>
      </defs>
      <path d="M12 1.8 21 6.9v10.2L12 22.2 3 17.1V6.9z" fill="none" stroke="url(#praxis-mark)" strokeWidth="1.8" />
      <path d="M12 6.6 16.6 9.2v5.6L12 17.4l-4.6-2.6V9.2z" fill="url(#praxis-mark)" opacity="0.9" />
    </svg>
  );
}

export function LandingHeader() {
  const health = usePolling(getHealth, 15_000);
  const online = health.data?.status === "ok";

  return (
    <header className="fixed inset-x-0 top-4 z-50 px-4">
      <nav
        aria-label="Primary"
        className="mx-auto flex h-14 max-w-6xl items-center justify-between rounded-2xl border border-white/10 bg-white/[0.04] px-4 shadow-[0_8px_40px_-12px_rgba(0,0,0,0.8)] backdrop-blur-xl sm:px-5"
      >
        <Link href="/" className="flex items-center gap-2.5 rounded-md focus-visible:outline-2 focus-visible:outline-cyan-400">
          <PraxisMark />
          <span className="font-display text-[15px] font-bold tracking-[0.22em] text-white">PRAXIS</span>
        </Link>

        <ul className="hidden items-center gap-8 md:flex">
          {LINKS.map((l) => (
            <li key={l.href}>
              <a href={l.href} className="text-sm text-slate-300 transition-colors hover:text-white">
                {l.label}
              </a>
            </li>
          ))}
        </ul>

        <div className="flex items-center gap-3 sm:gap-4">
          <span className="hidden items-center gap-2 text-xs text-slate-400 sm:flex" title={health.error ?? "Live backend"}>
            <span className="relative flex size-2">
              {online && <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-60" />}
              <span className={cn("relative inline-flex size-2 rounded-full", online ? "bg-emerald-400" : health.loading ? "bg-slate-500" : "bg-red-500")} />
            </span>
            <span className="figure">{online ? "API live" : health.loading ? "Connecting" : "API offline"}</span>
          </span>
          <Link
            href="/console"
            className="group inline-flex h-9 items-center gap-1.5 rounded-xl bg-linear-to-b from-indigo-500 to-indigo-600 px-3.5 text-sm font-medium text-white shadow-[0_0_24px_-4px_rgba(99,102,241,0.9),inset_0_1px_0_rgba(255,255,255,0.25)] transition hover:from-indigo-400 hover:to-indigo-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300"
          >
            Launch Console
            <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
          </Link>
        </div>
      </nav>
    </header>
  );
}
