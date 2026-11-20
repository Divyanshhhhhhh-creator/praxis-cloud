"use client";

import { useCallback, useEffect, useState } from "react";
import { CircleCheck, X } from "lucide-react";

export function useToast() {
  const [message, setMessage] = useState<string | null>(null);
  const show = useCallback((m: string) => setMessage(m), []);
  useEffect(() => {
    if (!message) return;
    const id = window.setTimeout(() => setMessage(null), 4500);
    return () => window.clearTimeout(id);
  }, [message]);
  const node = message ? (
    <div role="status" className="fixed bottom-5 right-5 z-50 flex max-w-sm items-start gap-2.5 rounded-xl border border-hairline bg-white px-4 py-3 text-[13px] text-ink shadow-lg">
      <CircleCheck className="mt-0.5 size-4 shrink-0 text-emerald-700" aria-hidden="true" />
      <span className="flex-1">{message}</span>
      <button onClick={() => setMessage(null)} className="rounded p-0.5 text-ink-3 hover:bg-slate-100" aria-label="Dismiss notification">
        <X className="size-3.5" />
      </button>
    </div>
  ) : null;
  return { show, node };
}
