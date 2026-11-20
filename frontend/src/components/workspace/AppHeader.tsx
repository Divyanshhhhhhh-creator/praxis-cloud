"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowUpRight } from "lucide-react";
import { getApprovals, getHealth } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { cn } from "@/lib/format";

const TABS = [
  { href: "/console", label: "Live Console" },
  { href: "/policies", label: "Policy Studio" },
  { href: "/approvals", label: "HITL Approvals", badge: true },
  { href: "/evals", label: "Red-Team Evals" },
];

function Mark() {
  return (
    <svg viewBox="0 0 24 24" className="size-[22px]" aria-hidden="true">
      <path d="M12 1.8 21 6.9v10.2L12 22.2 3 17.1V6.9z" fill="none" stroke="#0F172A" strokeWidth="2" />
      <path d="M12 6.6 16.6 9.2v5.6L12 17.4l-4.6-2.6V9.2z" fill="#4F46E5" />
    </svg>
  );
}

export function AppHeader() {
  const pathname = usePathname();
  const health = usePolling(getHealth, 10_000);
  const pending = usePolling(() => getApprovals({ status: "PENDING" }), 8_000);
  const online = health.data?.status === "ok";
  const pendingCount = pending.data?.length ?? 0;

  return (
    <header className="sticky top-0 z-40 border-b border-hairline bg-white/95 supports-[backdrop-filter]:bg-white/90 supports-[backdrop-filter]:backdrop-blur-sm">
      <div className="mx-auto flex h-14 max-w-[1440px] items-center gap-4 px-4 sm:px-6">
        {/* left: identity */}
        <div className="flex min-w-0 items-center gap-2.5">
          <Link href="/console" className="flex items-center gap-2 rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600">
            <Mark />
            <span className="text-[15px] font-semibold tracking-tight text-ink">Praxis</span>
          </Link>
          <span className="text-slate-300" aria-hidden="true">/</span>
          <span className="truncate rounded-md border border-hairline bg-canvas px-2 py-0.5 text-[13px] font-medium text-ink-2">
            Treasury Firewall
          </span>
          <span className="figure hidden rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] text-ink-3 xl:inline">
            {health.data?.region ?? "asia-south1"} • Razorpay Test
          </span>
        </div>

        {/* center: tabs */}
        <nav aria-label="Workspace" className="mx-auto hidden h-full md:block">
          <ul className="flex h-full items-stretch gap-1">
            {TABS.map((t) => {
              const active = pathname === t.href || pathname.startsWith(`${t.href}/`);
              return (
                <li key={t.href} className="flex">
                  <Link
                    href={t.href}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "relative flex items-center gap-1.5 px-3 text-[13.5px] font-medium transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-indigo-600",
                      active ? "text-ink" : "text-ink-3 hover:text-ink",
                    )}
                  >
                    {t.label}
                    {t.badge && pendingCount > 0 && (
                      <span className="figure grid h-[18px] min-w-[18px] place-items-center rounded-full bg-amber-100 px-1 text-[11px] font-semibold text-amber-800 ring-1 ring-amber-300">
                        {pendingCount}
                      </span>
                    )}
                    <span
                      aria-hidden="true"
                      className={cn("absolute inset-x-2 -bottom-px h-0.5 rounded-full", active ? "bg-ink" : "bg-transparent")}
                    />
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        {/* right: health + landing */}
        <div className="ml-auto flex items-center gap-4 md:ml-0">
          <span className="flex items-center gap-1.5 whitespace-nowrap text-[13px] text-ink-2" title={health.error ?? health.data?.service}>
            <span
              className={cn("size-2 rounded-full", online ? "bg-allow" : health.loading ? "bg-slate-300" : "bg-block")}
              aria-hidden="true"
            />
            {online ? "API Online" : health.loading ? "Checking…" : "API Offline"}
          </span>
          <Link href="/" className="hidden items-center gap-0.5 text-[13px] text-ink-3 hover:text-ink sm:inline-flex">
            Landing
            <ArrowUpRight className="size-3.5" aria-hidden="true" />
          </Link>
        </div>
      </div>

      {/* mobile tabs */}
      <nav aria-label="Workspace (mobile)" className="border-t border-hairline md:hidden">
        <ul className="flex overflow-x-auto px-2">
          {TABS.map((t) => {
            const active = pathname === t.href;
            return (
              <li key={t.href}>
                <Link
                  href={t.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex h-10 items-center gap-1.5 whitespace-nowrap border-b-2 px-3 text-[13px] font-medium",
                    active ? "border-ink text-ink" : "border-transparent text-ink-3",
                  )}
                >
                  {t.label}
                  {t.badge && pendingCount > 0 && <span className="figure text-[11px] text-amber-700">({pendingCount})</span>}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </header>
  );
}
