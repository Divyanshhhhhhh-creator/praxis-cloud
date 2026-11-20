"use client";

import { useEffect, useRef, useState } from "react";
import { Download, FileText, LoaderCircle, X } from "lucide-react";
import { errorMessage, getRbiIncidentReport } from "@/lib/api";
import type { RbiIncidentReport } from "@/lib/types";
import { Button } from "../ui";

export function RbiReportModal({ auditId, onClose }: { auditId: string; onClose: () => void }) {
  const [report, setReport] = useState<RbiIncidentReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let alive = true;
    getRbiIncidentReport(auditId)
      .then((r) => alive && setReport(r))
      .catch((e) => alive && setError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, [auditId]);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  const json = report ? JSON.stringify(report, null, 2) : "";
  const download = () => {
    if (!report) return;
    const url = URL.createObjectURL(new Blob([json], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${report.incident_id}_rbi_annex1.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-900/40 p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-labelledby="rbi-title" className="flex max-h-[86vh] w-full max-w-3xl flex-col rounded-xl border border-hairline bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-hairline px-5 py-4">
          <div>
            <h2 id="rbi-title" className="flex items-center gap-2 text-[15px] font-semibold text-ink">
              <FileText className="size-4 text-indigo-600" aria-hidden="true" />
              RBI Annex-1 Cyber Incident Report
            </h2>
            <p className="mt-0.5 text-[12.5px] text-ink-3">
              {report ? (
                <>
                  <span className="figure">{report.incident_id}</span> · {report.regulatory_framework.primary_circular} · deadline{" "}
                  <span className="figure">{new Date(report.regulatory_framework.reporting_deadline_utc).toLocaleString("en-IN")}</span>
                </>
              ) : (
                "GET /v1/audits/{audit_id}/rbi-incident-report"
              )}
            </p>
          </div>
          <button ref={closeRef} onClick={onClose} className="rounded-md p-1 text-ink-3 hover:bg-slate-100 hover:text-ink focus-visible:outline-2 focus-visible:outline-indigo-600" aria-label="Close report">
            <X className="size-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto bg-canvas">
          {error ? (
            <p className="p-5 text-[13px] text-red-700">{error}</p>
          ) : report ? (
            <pre className="figure whitespace-pre p-5 text-[12px] leading-relaxed text-ink-2">{json}</pre>
          ) : (
            <p className="flex items-center gap-2 p-5 text-[13px] text-ink-3">
              <LoaderCircle className="size-4 animate-spin" aria-hidden="true" /> Generating report…
            </p>
          )}
        </div>
        <div className="flex items-center justify-between gap-3 border-t border-hairline px-5 py-3">
          <p className="text-[12px] text-ink-3">6-hour CERT-In / RBI reporting readiness · SHA-256 sealed evidence</p>
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={onClose}>Close</Button>
            <Button size="sm" onClick={download} disabled={!report}>
              <Download className="size-4" aria-hidden="true" /> Download .json
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
