"use client";

import { useRef, useState } from "react";
import { Bot, ExternalLink, LoaderCircle, Play, RotateCcw, ShieldAlert, Upload, Zap } from "lucide-react";
import { demoPdfUrl } from "@/lib/api";
import { cn } from "@/lib/format";
import { DEMO_PDF_FILES, SCENARIOS, type ConsoleForm, type PdfChoice, type RunMode, type Scenario } from "@/lib/scenarios";
import type { DemoPdf, PolicyConfig } from "@/lib/types";
import { Button, Card, VerdictPill } from "../ui";

export interface CustomPdf {
  name: string;
  base64: string;
  mime: string;
}

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const UPLOAD_MIMES = ["application/pdf", "image/png", "image/jpeg", "image/webp"];

const inputCls =
  "h-9 w-full rounded-lg border border-hairline bg-white px-3 text-[13px] text-ink placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 disabled:bg-slate-50 disabled:text-ink-3";

function Field({ id, label, hint, children, className }: { id: string; label: string; hint?: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={className}>
      <label htmlFor={id} className="text-[12px] font-medium text-ink-2">
        {label}
      </label>
      <div className="mt-1">{children}</div>
      {hint && <p className="mt-1 text-[11.5px] text-ink-3">{hint}</p>}
    </div>
  );
}

export function ScenarioLauncher({
  form,
  onChange,
  activeScenario,
  onPickScenario,
  onRun,
  onBurst,
  onReset,
  running,
  elapsedMs,
  policies,
  pdfs,
  customPdf,
  onCustomPdf,
  resetFeedback,
}: {
  form: ConsoleForm;
  onChange: (patch: Partial<ConsoleForm>) => void;
  activeScenario: string | null;
  onPickScenario: (s: Scenario) => void;
  onRun: () => void;
  onBurst: () => void;
  onReset: () => void;
  running: boolean;
  elapsedMs: number;
  policies: PolicyConfig[];
  pdfs: DemoPdf[];
  customPdf: CustomPdf | null;
  onCustomPdf: (pdf: CustomPdf | null) => void;
  resetFeedback: string | null;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const adk = form.mode === "adk";
  const presetPdfName = form.pdf === "clean_480" || form.pdf === "poisoned_48000" ? DEMO_PDF_FILES[form.pdf] : null;
  const presetAvailable = !presetPdfName || pdfs.length === 0 || pdfs.some((p) => p.name === presetPdfName);
  const policyIds = Array.from(new Set([...policies.map((p) => p.policy_id), form.policyId]));

  const onFile = (file: File | undefined) => {
    setUploadError(null);
    if (!file) return;
    if (!UPLOAD_MIMES.includes(file.type)) return setUploadError("Use a PDF, PNG, JPEG or WebP file.");
    if (file.size > MAX_UPLOAD_BYTES) return setUploadError("File exceeds 10 MB.");
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result ?? "");
      onCustomPdf({ name: file.name, mime: file.type, base64: result.slice(result.indexOf(",") + 1) });
      onChange({ pdf: "custom" });
    };
    reader.onerror = () => setUploadError("Could not read file.");
    reader.readAsDataURL(file);
  };

  const modes: { id: RunMode; label: string; route: string; icon: typeof Bot; desc: string }[] = [
    { id: "adk", label: "Google ADK Agent", route: "/v1/agent/run", icon: Bot, desc: "A real LlmAgent decides the tool call; before_tool_callback routes it through Praxis." },
    { id: "intercept", label: "Compromised Agent", route: "/v1/intercept", icon: ShieldAlert, desc: "You play the hijacked agent and submit the exact tool call straight to the proxy." },
  ];

  return (
    <Card className="flex flex-col">
      <div className="border-b border-hairline px-5 py-3.5">
        <h2 className="text-[14px] font-semibold text-ink">Agent & Attack Simulator</h2>
        <p className="mt-0.5 text-[12.5px] text-ink-3">Live Gemini + Razorpay Test Mode · every run is audited</p>
      </div>

      {/* mode switch */}
      <div className="px-5 pt-4">
        <div role="radiogroup" aria-label="Execution mode" className="grid grid-cols-2 gap-1 rounded-lg border border-hairline bg-canvas p-1">
          {modes.map((m) => (
            <button
              key={m.id}
              role="radio"
              aria-checked={form.mode === m.id}
              onClick={() => onChange({ mode: m.id })}
              className={cn(
                "flex flex-col items-start rounded-md px-3 py-2 text-left transition-colors focus-visible:outline-2 focus-visible:outline-indigo-600",
                form.mode === m.id ? "bg-white shadow-sm ring-1 ring-hairline" : "hover:bg-white/60",
              )}
            >
              <span className="flex items-center gap-1.5 text-[13px] font-semibold text-ink">
                <m.icon className={cn("size-4", m.id === "adk" ? "text-indigo-600" : "text-red-600")} aria-hidden="true" />
                {m.label}
              </span>
              <span className="figure text-[11px] text-ink-3">{m.route}</span>
            </button>
          ))}
        </div>
        <p className="mt-2 text-[12px] text-ink-3">{modes.find((m) => m.id === form.mode)?.desc}</p>
      </div>

      {/* presets */}
      <div className="px-5 pt-4">
        <p className="text-[12px] font-medium text-ink-2">Scenario presets</p>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {SCENARIOS.map((s) => (
            <button
              key={s.id}
              onClick={() => onPickScenario(s)}
              disabled={running}
              aria-pressed={activeScenario === s.id}
              className={cn(
                "group rounded-lg border px-3 py-2.5 text-left transition-colors focus-visible:outline-2 focus-visible:outline-indigo-600 disabled:opacity-60",
                activeScenario === s.id ? "border-indigo-500 bg-indigo-50/60 ring-1 ring-indigo-500" : "border-hairline bg-white hover:border-slate-300 hover:bg-slate-50",
              )}
            >
              <span className="flex items-center justify-between gap-2">
                <span className="text-[13px] font-semibold text-ink">{s.title}</span>
                {s.action === "velocity-burst" && <Zap className="size-3.5 text-amber-600" aria-hidden="true" />}
              </span>
              <span className="mt-1 flex items-center gap-1.5">
                <VerdictPill verdict={s.expect} className="px-1.5 py-0 text-[10.5px]" />
                <span className="figure truncate text-[11px] text-ink-3">{s.expectDetail}</span>
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* form */}
      <form
        className="mt-4 grid grid-cols-2 gap-3 border-t border-hairline px-5 py-4"
        onSubmit={(e) => {
          e.preventDefault();
          onRun();
        }}
      >
        <Field id="prompt" label="User prompt (trusted intent)" className="col-span-2">
          <textarea
            id="prompt"
            value={form.prompt}
            onChange={(e) => onChange({ prompt: e.target.value })}
            rows={3}
            required
            placeholder="e.g. Refund ₹500 to customer cust_demo_01 for order A-1029 to their original card."
            className={cn(inputCls, "h-auto py-2 leading-relaxed")}
          />
        </Field>

        <Field id="tool" label="Tool" hint={adk ? "Chosen by the ADK agent" : undefined}>
          <select id="tool" value={form.tool} disabled={adk} onChange={(e) => onChange({ tool: e.target.value as ConsoleForm["tool"] })} className={inputCls}>
            <option value="issue_customer_refund">issue_customer_refund</option>
            <option value="pay_vendor_invoice">pay_vendor_invoice</option>
          </select>
        </Field>
        <Field id="amount" label="Amount (INR)" hint={adk ? "Chosen by the ADK agent" : undefined}>
          <input id="amount" type="number" min={1} step="0.01" inputMode="decimal" value={form.amount} disabled={adk} onChange={(e) => onChange({ amount: e.target.value })} className={cn(inputCls, "figure")} />
        </Field>
        <Field id="merchant" label="Merchant ID">
          <input id="merchant" value={form.merchant} disabled={adk} onChange={(e) => onChange({ merchant: e.target.value })} className={cn(inputCls, "figure")} />
        </Field>
        <Field id="destination" label="Destination mode">
          <select id="destination" value={form.destination} onChange={(e) => onChange({ destination: e.target.value as ConsoleForm["destination"] })} className={cn(inputCls, "figure")}>
            <option value="original_source">original_source</option>
            <option value="alternate_account">alternate_account</option>
          </select>
        </Field>
        <Field id="contact" label="Contact changed (hours ago)">
          <input id="contact" type="number" min={0} step="0.5" placeholder="optional" value={form.contactHours} onChange={(e) => onChange({ contactHours: e.target.value })} className={cn(inputCls, "figure")} />
        </Field>
        <Field id="policy" label="Treasury policy">
          <select id="policy" value={form.policyId} onChange={(e) => onChange({ policyId: e.target.value })} className={cn(inputCls, "figure")}>
            {policyIds.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </Field>

        <Field id="pdf" label="Invoice attachment" className="col-span-2">
          <div className="flex gap-2">
            <select
              id="pdf"
              value={form.pdf}
              onChange={(e) => {
                const v = e.target.value as PdfChoice;
                if (v === "custom" && !customPdf) fileRef.current?.click();
                onChange({ pdf: v });
              }}
              className={inputCls}
            >
              <option value="none">None</option>
              <option value="clean_480">Clean ₹480 PDF (invoice_clean_480.pdf)</option>
              <option value="poisoned_48000">Poisoned ₹48k PDF (invoice_poisoned_480_to_48000.pdf)</option>
              <option value="custom">{customPdf ? `Custom: ${customPdf.name}` : "Custom file upload…"}</option>
            </select>
            <Button type="button" variant="secondary" size="md" className="shrink-0 px-3" onClick={() => fileRef.current?.click()} aria-label="Upload a custom invoice file">
              <Upload className="size-4" aria-hidden="true" />
            </Button>
            <input ref={fileRef} type="file" accept={UPLOAD_MIMES.join(",")} className="sr-only" tabIndex={-1} onChange={(e) => onFile(e.target.files?.[0])} />
          </div>
          {presetPdfName && (
            <a href={demoPdfUrl(presetPdfName)} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-[11.5px] text-indigo-700 hover:underline">
              Preview {presetPdfName} <ExternalLink className="size-3" aria-hidden="true" />
            </a>
          )}
          {!presetAvailable && <p className="mt-1 text-[11.5px] text-red-700">This preset PDF is not served by the backend.</p>}
          {uploadError && <p className="mt-1 text-[11.5px] text-red-700">{uploadError}</p>}
        </Field>

        <Field id="untrusted" label="Untrusted email / ticket (sandboxed data)" className="col-span-2">
          <textarea id="untrusted" value={form.untrusted} onChange={(e) => onChange({ untrusted: e.target.value })} rows={2} placeholder="optional" className={cn(inputCls, "h-auto py-2")} />
        </Field>

        <label className="col-span-2 flex items-start gap-2.5 rounded-lg border border-hairline bg-canvas px-3 py-2.5">
          <input type="checkbox" checked={form.simulateTimeout} onChange={(e) => onChange({ simulateTimeout: e.target.checked })} className="mt-0.5 size-4 accent-indigo-600" />
          <span>
            <span className="text-[13px] font-medium text-ink">Simulate L2 Timeout (Fail-Closed)</span>
            <span className="figure block text-[11.5px] text-ink-3">timeout_override_s = 0.001 → must ESCALATE, never ALLOW</span>
          </span>
        </label>

        <div className="col-span-2 flex flex-wrap items-center gap-2 pt-1">
          {activeScenario === "velocity-burst" ? (
            <Button type="button" onClick={onBurst} disabled={running} className="flex-1">
              {running ? <LoaderCircle className="size-4 animate-spin" aria-hidden="true" /> : <Zap className="size-4" aria-hidden="true" />}
              {running ? `Firing burst… ${(elapsedMs / 1000).toFixed(2)} s` : "Fire 4× Velocity Burst"}
            </Button>
          ) : (
            <Button type="submit" disabled={running || !form.prompt.trim()} className="flex-1">
              {running ? <LoaderCircle className="size-4 animate-spin" aria-hidden="true" /> : <Play className="size-4" aria-hidden="true" />}
              {running ? `Evaluating… ${(elapsedMs / 1000).toFixed(2)} s` : "Run Through Praxis Firewall"}
            </Button>
          )}
          <Button
            type="button"
            variant={confirmReset ? "danger" : "secondary"}
            disabled={running}
            onClick={() => {
              if (!confirmReset) {
                setConfirmReset(true);
                window.setTimeout(() => setConfirmReset(false), 3500);
                return;
              }
              setConfirmReset(false);
              onReset();
            }}
          >
            <RotateCcw className="size-4" aria-hidden="true" />
            {confirmReset ? "Confirm reset" : "Reset Demo State"}
          </Button>
        </div>
        {resetFeedback && (
          <p role="status" className="col-span-2 text-[12px] text-emerald-700">
            {resetFeedback}
          </p>
        )}
      </form>
    </Card>
  );
}
