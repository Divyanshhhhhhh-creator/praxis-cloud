"use client";

import { useState } from "react";
import { getPolicies } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { cn } from "@/lib/format";
import { DEFAULT_POLICY_ID } from "@/lib/policies";
import type { PolicyConfig } from "@/lib/types";
import { Card, EmptyNotice } from "@/components/workspace/ui";
import { PageTitle } from "@/components/workspace/PageTitle";
import { PolicyEditor } from "@/components/workspace/policies/PolicyEditor";
import { PolicyCompiler } from "@/components/workspace/policies/PolicyCompiler";
import { useToast } from "@/components/workspace/Toast";

export default function PoliciesPage() {
  const policies = usePolling(getPolicies, 30_000);
  const [selectedId, setSelectedId] = useState<string>(DEFAULT_POLICY_ID);
  const toast = useToast();
  const rows = policies.data ?? [];
  const selected = rows.find((p) => p.policy_id === selectedId) ?? rows[0] ?? null;

  const onChanged = (p: PolicyConfig, msg: string) => {
    setSelectedId(p.policy_id);
    toast.show(msg);
    void policies.refresh();
  };

  return (
    <div className="space-y-5">
      <PageTitle
        title="Guardrails Studio"
        subtitle="Edit the treasury policies enforced by Layer 1 and grounded into the Layer 2 auditor — or compile plain-English finance rules with Gemini 3.6 Flash. RBI regulatory floors are locked."
        count={`${rows.length} ${rows.length === 1 ? "policy" : "policies"}`}
      />

      {rows.length > 0 && (
        <nav aria-label="Policies" className="flex gap-1 overflow-x-auto border-b border-hairline">
          {rows.map((p) => {
            const active = selected?.policy_id === p.policy_id;
            return (
              <button
                key={p.policy_id}
                onClick={() => setSelectedId(p.policy_id)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "figure -mb-px flex items-center gap-2 whitespace-nowrap border-b-2 px-3 py-2 text-[12.5px] transition-colors focus-visible:outline-2 focus-visible:outline-indigo-600",
                  active ? "border-ink text-ink" : "border-transparent text-ink-3 hover:text-ink",
                )}
              >
                <span className={cn("size-1.5 rounded-full", p.mode === "shadow" ? "bg-escalate" : "bg-allow")} aria-hidden="true" />
                {p.policy_id}
              </button>
            );
          })}
        </nav>
      )}

      {!selected ? (
        <Card>
          {policies.loading ? (
            <div className="h-64 animate-pulse bg-slate-50" aria-hidden="true" />
          ) : (
            <EmptyNotice title="API offline" body={policies.error ?? "No policies returned by GET /v1/policies."} />
          )}
        </Card>
      ) : (
        <div className="grid gap-5 lg:grid-cols-12">
          <div className="lg:col-span-7">
            <PolicyEditor key={JSON.stringify(selected)} policy={selected} onSaved={onChanged} />
          </div>
          <div className="lg:col-span-5">
            <PolicyCompiler key={selected.policy_id} policy={selected} onApplied={onChanged} />
          </div>
        </div>
      )}
      {toast.node}
    </div>
  );
}
