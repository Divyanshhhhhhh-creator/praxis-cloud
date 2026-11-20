import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { PraxisMark } from "./LandingHeader";

/** Transition band: obsidian showcase → crisp light workspace. */
export function PortalSection() {
  return (
    <section className="relative pt-16" aria-labelledby="portal-title">
      <div aria-hidden="true" className="absolute inset-x-0 bottom-0 h-[70%] bg-linear-to-b from-obsidian via-slate-900 to-canvas" />
      <div className="relative mx-auto max-w-5xl px-5 pb-24">
        <div className="rounded-3xl border border-hairline bg-white p-8 shadow-[0_30px_80px_-30px_rgba(15,23,42,0.6)] sm:p-12">
          <div className="flex flex-col gap-8 md:flex-row md:items-center md:justify-between">
            <div className="max-w-xl">
              <p className="text-xs font-semibold tracking-[0.18em] text-indigo-600">FROM SHOWCASE TO WORKSPACE</p>
              <h2 id="portal-title" className="font-display mt-3 text-3xl font-bold tracking-[-0.02em] text-ink sm:text-4xl">
                Step inside the live Treasury Control Plane.
              </h2>
              <p className="mt-3 text-[15px] leading-relaxed text-ink-3">
                Run the real Google ADK agent, fire red-team attacks, approve held payouts and export RBI incident reports —
                all against live Gemini and Razorpay Test Mode.
              </p>
            </div>
            <Link
              href="/console"
              className="group inline-flex h-12 shrink-0 items-center gap-2 self-start rounded-xl bg-ink px-6 text-[15px] font-semibold text-white transition hover:bg-slate-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500 md:self-center"
            >
              Open Praxis Console
              <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" aria-hidden="true" />
            </Link>
          </div>
        </div>
      </div>
      <footer className="relative bg-canvas">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-3 border-t border-hairline px-5 py-6 text-sm text-ink-3 sm:flex-row">
          <span className="flex items-center gap-2">
            <PraxisMark className="size-5" />
            <span className="font-display font-semibold tracking-[0.16em] text-ink">PRAXIS</span>
            <span>· Google Startup Buildathon India 2026</span>
          </span>
          <span className="figure text-xs">asia-south1 · Razorpay Test Mode · Gemini</span>
        </div>
      </footer>
    </section>
  );
}
