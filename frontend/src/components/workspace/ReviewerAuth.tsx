"use client";

import { useEffect, useRef, useState } from "react";
import { KeyRound, Lock, LockOpen, ShieldAlert } from "lucide-react";
import { cn } from "@/lib/format";
import {
  REVIEWER_REQUIRED_TEXT,
  getReviewerToken,
  onReviewerAuthRequested,
  requestReviewerAuth,
  setReviewerToken,
  useReviewerToken,
} from "@/lib/reviewer";

/** Inline fail-closed notice shown wherever a protected action returned 401. */
export function ReviewerRequiredBadge({ className }: { className?: string }) {
  return (
    <div role="alert" className={cn("flex flex-wrap items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-[12.5px] text-amber-900", className)}>
      <ShieldAlert className="size-4 shrink-0" aria-hidden="true" />
      <span className="font-semibold">{REVIEWER_REQUIRED_TEXT}</span>
      <button
        type="button"
        onClick={requestReviewerAuth}
        className="ml-auto rounded-md bg-amber-900 px-2 py-0.5 text-[12px] font-medium text-white hover:bg-amber-950 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-700"
      >
        Enter passcode
      </button>
    </div>
  );
}

/** Renders a protected action's error: the reviewer badge on 401, otherwise the plain red message. */
export function ActionError({ error, className }: { error: string | null; className?: string }) {
  if (!error) return null;
  if (error === REVIEWER_REQUIRED_TEXT) return <ReviewerRequiredBadge className={className} />;
  return <p role="alert" className={cn("rounded-md bg-red-50 px-3 py-2 text-[12.5px] text-red-700", className)}>{error}</p>;
}

/** Header lock button + popover: the passcode lives only in this tab's sessionStorage. */
export function ReviewerAuthButton() {
  const token = useReviewerToken();
  const unlocked = Boolean(token);
  const [open, setOpen] = useState(false);
  const [required, setRequired] = useState(false);
  const [value, setValue] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(
    () =>
      onReviewerAuthRequested(() => {
        // a stored passcode that the backend just rejected is stale: forget it so the input shows again
        if (getReviewerToken()) setReviewerToken(null);
        setRequired(true);
        setOpen(true);
      }),
    [],
  );

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
    };
  }, [open]);

  const unlock = (e: React.FormEvent) => {
    e.preventDefault();
    if (!value.trim()) return;
    setReviewerToken(value.trim());
    setValue("");
    setRequired(false);
    setOpen(false);
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => {
          setRequired(false);
          setOpen((o) => !o);
        }}
        aria-expanded={open}
        aria-haspopup="dialog"
        className={cn(
          "inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-lg border px-2.5 text-[12.5px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600",
          unlocked ? "border-emerald-200 bg-emerald-50 text-emerald-800 hover:bg-emerald-100" : "border-hairline bg-white text-ink-2 hover:bg-slate-50",
        )}
      >
        {unlocked ? <LockOpen className="size-3.5" aria-hidden="true" /> : <Lock className="size-3.5" aria-hidden="true" />}
        <span className="hidden sm:inline">{unlocked ? "Reviewer unlocked" : "Reviewer Auth"}</span>
      </button>

      {open && (
        <div role="dialog" aria-label="Treasury reviewer authentication" className="fixed right-4 top-16 z-50 w-[min(20rem,calc(100vw-2rem))] rounded-xl lg:absolute lg:right-0 lg:top-full lg:mt-2 lg:w-80 border border-hairline bg-white p-4 shadow-xl">
          <p className="flex items-center gap-2 text-[13.5px] font-semibold text-ink">
            <KeyRound className="size-4 text-indigo-600" aria-hidden="true" /> Treasury Reviewer Auth
          </p>
          {required && (
            <p className="mt-2 rounded-md bg-amber-50 px-2.5 py-1.5 text-[12px] font-medium text-amber-900 ring-1 ring-amber-200">
              {REVIEWER_REQUIRED_TEXT}
            </p>
          )}
          <p className="mt-2 text-[12px] leading-relaxed text-ink-3">
            Approve / reject, demo reset, saving or applying policies and live benchmark runs require the reviewer passcode.
            It is kept only in this tab&apos;s session storage and sent as <span className="figure">X-Reviewer-Token</span>.
          </p>
          {unlocked ? (
            <button
              type="button"
              onClick={() => {
                setReviewerToken(null);
                setOpen(false);
              }}
              className="mt-3 inline-flex h-9 w-full items-center justify-center gap-2 rounded-lg border border-hairline text-[13px] font-medium text-ink hover:bg-slate-50"
            >
              <Lock className="size-4" aria-hidden="true" /> Lock (forget passcode)
            </button>
          ) : (
            <form onSubmit={unlock} className="mt-3 flex gap-2">
              <label htmlFor="reviewer-passcode" className="sr-only">Reviewer passcode</label>
              <input
                id="reviewer-passcode"
                ref={inputRef}
                type="password"
                autoComplete="off"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder="Reviewer passcode"
                className="h-9 min-w-0 flex-1 rounded-lg border border-hairline px-3 text-[13px] text-ink focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
              />
              <button type="submit" disabled={!value.trim()} className="h-9 rounded-lg bg-ink px-3 text-[13px] font-medium text-white hover:bg-slate-800 disabled:opacity-50">
                Unlock
              </button>
            </form>
          )}
        </div>
      )}
    </div>
  );
}
