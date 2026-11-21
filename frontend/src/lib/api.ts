/** Typed client for the live Praxis FastAPI backend (backend/app/main.py). */

import type {
  AgentRunRequest,
  AgentRunResult,
  ApprovalRow,
  ApprovalStatus,
  AuditDecision,
  CompileRequest,
  CompileResult,
  DecideRequest,
  DemoPdf,
  DemoResetRequest,
  DemoResetResponse,
  EvalRun,
  HealthStatus,
  InterceptRequest,
  LatestEval,
  MetricsSummary,
  PolicyConfig,
  RbiIncidentReport,
} from "./types";
import { REVIEWER_REQUIRED_TEXT, getReviewerToken, requestReviewerAuth } from "./reviewer";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");
const AGENT_TOKEN = process.env.NEXT_PUBLIC_AGENT_TOKEN ?? "";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT";
  json?: unknown;
  query?: Record<string, string | number | undefined | null>;
  agentAuth?: boolean;
  /** Mutating governance call: attach the session-only reviewer passcode as X-Reviewer-Token. */
  reviewerAuth?: boolean;
  timeoutMs?: number;
}

function detailToMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        const item = d as { loc?: unknown[]; msg?: string };
        return `${(item.loc ?? []).join(".")}: ${item.msg ?? "invalid"}`;
      })
      .join("; ");
  }
  return JSON.stringify(detail);
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const url = new URL(`${API_URL}${path}`);
  for (const [k, v] of Object.entries(opts.query ?? {})) {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  }
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.json !== undefined) headers["Content-Type"] = "application/json";
  if (opts.agentAuth) headers["X-Agent-Token"] = AGENT_TOKEN;
  if (opts.reviewerAuth) {
    const reviewer = getReviewerToken();
    if (reviewer) headers["X-Reviewer-Token"] = reviewer;
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), opts.timeoutMs ?? 15_000);
  let res: Response;
  try {
    res = await fetch(url, {
      method: opts.method ?? "GET",
      headers,
      body: opts.json !== undefined ? JSON.stringify(opts.json) : undefined,
      signal: controller.signal,
      cache: "no-store",
    });
  } catch (err) {
    const aborted = err instanceof DOMException && err.name === "AbortError";
    throw new ApiError(0, aborted ? "Request timed out" : `Praxis API unreachable at ${API_URL}`);
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (body.detail !== undefined) message = detailToMessage(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message);
  }
  return (await res.json()) as T;
}

// ------------------------------------------------------------------ reads
export const getHealth = () => request<HealthStatus>("/health", { timeoutMs: 4_000 });

export const getMetrics = (params: { agent_id?: string; policy_id?: string } = {}) =>
  request<MetricsSummary>("/v1/metrics", { query: params });

export const getAudits = (params: { limit?: number; agent_id?: string } = {}) =>
  request<AuditDecision[]>("/v1/audits", { query: params });

export const getPolicies = () => request<PolicyConfig[]>("/v1/policies");

export const getApprovals = (params: { status?: ApprovalStatus; limit?: number } = {}) =>
  request<ApprovalRow[]>("/v1/approvals", { query: params });

export const getDemoPdfs = () => request<DemoPdf[]>("/v1/demo/pdfs");

export const demoPdfUrl = (name: string) => `${API_URL}/v1/demo/pdfs/${encodeURIComponent(name)}`;

export const getRbiIncidentReport = (auditId: string) =>
  request<RbiIncidentReport>(`/v1/audits/${encodeURIComponent(auditId)}/rbi-incident-report`);

// ------------------------------------------------------------------ writes
/** POST /v1/intercept — the "compromised agent" path; requires X-Agent-Token. */
export const runIntercept = (payload: InterceptRequest) =>
  request<AuditDecision>("/v1/intercept", { method: "POST", json: payload, agentAuth: true, timeoutMs: 60_000 });

/** POST /v1/agent/run — real Google ADK LlmAgent governed by before_tool_callback. */
export const runAdkAgent = (payload: AgentRunRequest) =>
  request<AgentRunResult>("/v1/agent/run", { method: "POST", json: payload, timeoutMs: 150_000 });

export const decideApproval = (
  approvalId: string,
  decision: DecideRequest["decision"],
  reviewerId: string,
  note = "",
) =>
  request<AuditDecision>(`/v1/approvals/${encodeURIComponent(approvalId)}/decide`, {
    method: "POST",
    json: { decision, reviewer_id: reviewerId, note } satisfies DecideRequest,
    reviewerAuth: true,
    timeoutMs: 60_000,
  });

export const resetDemo = (body: DemoResetRequest = {}) =>
  request<DemoResetResponse>("/v1/demo/reset", { method: "POST", json: body, reviewerAuth: true });

export const upsertPolicy = (policy: PolicyConfig) =>
  request<PolicyConfig>(`/v1/policies/${encodeURIComponent(policy.policy_id)}`, { method: "PUT", json: policy, reviewerAuth: true });

/** PUT /v1/policies/{policy_id} */
export const updatePolicy = (policyId: string, config: PolicyConfig) =>
  request<PolicyConfig>(`/v1/policies/${encodeURIComponent(policyId)}`, { method: "PUT", json: config, reviewerAuth: true });

/** POST /v1/policies/compile — gemini-3.6-flash (falls back to flash-lite); apply=false previews only. */
export const compilePolicy = (instruction: string, policyId: string, apply = false) =>
  request<CompileResult>("/v1/policies/compile", {
    method: "POST",
    json: { instruction, policy_id: policyId, apply } satisfies CompileRequest,
    reviewerAuth: apply,
    timeoutMs: 120_000,
  });

/** GET /v1/evals/latest — last persisted 12-case benchmark (or {status:"not_run_yet"}). */
export const getLatestEval = () => request<LatestEval>("/v1/evals/latest");

/** POST /v1/evals/run — runs the live 12-case red-team suite (~1–2 min on the free tier). */
export const runRedTeamEval = () => request<EvalRun>("/v1/evals/run", { method: "POST", timeoutMs: 300_000, reviewerAuth: true });

export const isEvalRun = (x: LatestEval | null | undefined): x is EvalRun => !!x && "run_id" in x;

// ------------------------------------------------------------------ helpers
/** Fetch a demo invoice PDF and return its base64 (for the /v1/intercept attachment path). */
export async function fetchDemoPdfBase64(name: string): Promise<string> {
  const res = await fetch(demoPdfUrl(name), { cache: "no-store" });
  if (!res.ok) throw new ApiError(res.status, `Could not load ${name}`);
  return arrayBufferToBase64(await res.arrayBuffer());
}

export function arrayBufferToBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.status ? `${err.status} · ${err.message}` : err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

/** True when a protected governance endpoint rejected the call for a missing / wrong reviewer passcode. */
export function isReviewerAuthError(err: unknown): boolean {
  return err instanceof ApiError && err.status === 401;
}

/** Error text for a protected reviewer action; on 401 it also opens the header's Reviewer Auth prompt. */
export function actionError(err: unknown): string {
  if (isReviewerAuthError(err)) {
    requestReviewerAuth();
    return REVIEWER_REQUIRED_TEXT;
  }
  return errorMessage(err);
}
