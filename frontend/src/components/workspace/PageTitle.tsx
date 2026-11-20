import Link from "next/link";
import { MonoPill } from "./ui";

export function PageTitle({ title, subtitle, count }: { title: string; subtitle: string; count?: string }) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-[22px] font-semibold tracking-tight text-ink">{title}</h1>
        <p className="mt-1 max-w-3xl text-[13.5px] text-ink-3">{subtitle}</p>
      </div>
      <div className="flex items-center gap-2">
        {count && <MonoPill>{count}</MonoPill>}
        <Link href="/console" className="inline-flex h-9 items-center rounded-lg bg-ink px-3.5 text-[13px] font-medium text-white hover:bg-slate-800">
          Open Live Console
        </Link>
      </div>
    </div>
  );
}
