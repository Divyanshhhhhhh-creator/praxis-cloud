/** Small shared primitives for the enterprise workspace (Stripe / Linear / Vercel style). */

import Link from "next/link";
import { cn } from "@/lib/format";
import { VERDICT_STYLE } from "@/lib/verdict";
import { policyMeta } from "@/lib/policies";
import type { Verdict } from "@/lib/types";

export function Card({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("rounded-xl border border-hairline bg-white", className)} {...rest}>
      {children}
    </div>
  );
}

export function CardHeader({ title, subtitle, right, className }: { title: React.ReactNode; subtitle?: React.ReactNode; right?: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-start justify-between gap-4 border-b border-hairline px-5 py-3.5", className)}>
      <div className="min-w-0">
        <h2 className="text-[14px] font-semibold text-ink">{title}</h2>
        {subtitle && <p className="mt-0.5 text-[12.5px] text-ink-3">{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

export function VerdictPill({ verdict, className }: { verdict: Verdict; className?: string }) {
  const s = VERDICT_STYLE[verdict];
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11.5px] font-semibold ring-1 ring-inset", s.pill, className)}>
      <span className={cn("size-1.5 rounded-full", s.dot)} aria-hidden="true" />
      {s.label}
    </span>
  );
}

export function MonoPill({ children, className, title }: { children: React.ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={cn("figure inline-flex items-center gap-1 rounded-md border border-hairline bg-canvas px-1.5 py-0.5 text-[11.5px] text-ink-2", className)}>
      {children}
    </span>
  );
}

export function PolicyChip({ id }: { id: string }) {
  const meta = policyMeta(id);
  return (
    <span
      title={`${meta.title}${meta.reference ? ` · ${meta.reference}` : ""}`}
      className="figure inline-flex items-center gap-1.5 rounded-md border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-[11.5px] font-medium text-indigo-800"
    >
      {id}
    </span>
  );
}

export function Button({
  variant = "primary",
  size = "md",
  className,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger" | "success"; size?: "sm" | "md" }) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 disabled:cursor-not-allowed disabled:opacity-55",
        size === "md" ? "h-10 px-4 text-[14px]" : "h-8 px-3 text-[13px]",
        variant === "primary" && "bg-ink text-white hover:bg-slate-800",
        variant === "secondary" && "border border-hairline bg-white text-ink hover:bg-slate-50",
        variant === "ghost" && "text-ink-2 hover:bg-slate-100",
        variant === "danger" && "border border-red-200 bg-white text-red-700 hover:bg-red-50",
        variant === "success" && "bg-emerald-700 text-white hover:bg-emerald-800",
        className,
      )}
      {...rest}
    />
  );
}

export function EmptyNotice({ title, body, href, cta }: { title: string; body: string; href?: string; cta?: string }) {
  return (
    <div className="grid place-items-center px-6 py-14 text-center">
      <p className="text-[14px] font-semibold text-ink">{title}</p>
      <p className="mt-1 max-w-md text-[13px] text-ink-3">{body}</p>
      {href && cta && (
        <Link href={href} className="mt-4 inline-flex h-9 items-center rounded-lg bg-ink px-3.5 text-[13px] font-medium text-white hover:bg-slate-800">
          {cta}
        </Link>
      )}
    </div>
  );
}

export function StatTile({ label, value, sub, href }: { label: string; value: React.ReactNode; sub?: React.ReactNode; href?: string }) {
  const body = (
    <>
      <p className="text-[12px] font-medium text-ink-3">{label}</p>
      <p className="figure mt-1 text-[22px] font-semibold leading-tight text-ink">{value}</p>
      {sub && <div className="mt-1 text-[12px] text-ink-3">{sub}</div>}
    </>
  );
  return href ? (
    <Link href={href} className="block px-5 py-4 transition-colors hover:bg-slate-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-indigo-600">
      {body}
    </Link>
  ) : (
    <div className="px-5 py-4">{body}</div>
  );
}
