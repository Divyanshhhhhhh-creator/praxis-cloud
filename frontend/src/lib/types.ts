/**
 * TypeScript mirror of the Praxis FastAPI contract (backend/app/domain/models.py, backend/app/main.py,
 * backend/app/agent/fintech_agent.py, backend/app/services/{policy_compiler,rbi_reporting}.py).
 * Keep 1:1 with the backend — field names, optionality and literals are identical.
 */

export type Verdict = "ALLOW" | "BLOCK" | "ESCALATE" | "SHADOW_FLAG";
export type LayerDecided = "L1_DETERMINISTIC" | "L2_GEMINI_AUDITOR" | "HITL_APPROVED" | "HITL_REJECTED";
export type DestinationMode = "original_source" | "alternate_account";
export type PolicyMode = "enforce" | "shadow";
export type GovernedTool = "issue_customer_refund" | "pay_vendor_invoice";
export type ThreatCategory =
  | "NONE"
  | "INDIRECT_PROMPT_INJECTION"
  | "LOGIC_HALLUCINATION"
  | "POLICY_MISMATCH"
  | "INVOICE_TAMPERING"
  | "HIGH_VALUE_ESCALATION";
export type DemoPdfPreset = "clean_480" | "poisoned_48000";

/** POST /v1/intercept body (InterceptRequest, extra="forbid"). */
export interface InterceptRequest {
  agent_id: string;
  idempotency_key: string;
  policy_id?: string;
  tool_name: string;
  user_prompt: string;
  untrusted_context?: string | null;
  payload: Record<string, unknown>;
  amount_inr: number;
  merchant_id: string;
  destination_mode?: DestinationMode;
  contact_changed_hours_ago?: number | null;
  attachment_base64?: string | null;
  attachment_mime?: string | null;
  /** Chaos drill: only tightens the L2 budget (0 < x ≤ 4.0). */
  timeout_override_s?: number | null;
}

export interface PolicyConfig {
  policy_id: string;
  name: string;
  mode: PolicyMode;
  max_single_txn_inr: number;
  auto_approve_threshold_inr: number;
  window_1m_inr: number;
  window_1h_inr: number;
  window_24h_inr: number;
  max_calls_per_min: number;
  rbi_cooling_period_hours: number;
  enforce_original_source_refund: boolean;
  allowed_tools: string[];
  allowed_merchants: string[];
}

export interface AuditDecision {
  audit_id: string;
  idempotency_key: string;
  agent_id: string;
  policy_id: string;
  tool_name: string;
  amount_inr: number;
  merchant_id: string;
  verdict: Verdict;
  layer_decided: LayerDecided;
  risk_score: number;
  reason: string;
  policy_citations: string[];
  payload_sha256: string;
  l1_latency_ms: number;
  l2_latency_ms: number;
  executed: boolean;
  settlement_txn_id: string | null;
  settlement_rail: string | null;
  created_at: string;
  approval_id: string | null;
  threat_category: string | null;
  invoice_extracted_total_inr: number | null;
  model_used: string | null;
}

export interface WindowUsage {
  used_1m_inr: number;
  limit_1m_inr: number;
  used_1h_inr: number;
  limit_1h_inr: number;
  used_24h_inr: number;
  limit_24h_inr: number;
  calls_1m: number;
  limit_calls_1m: number;
}

export interface MetricsSummary {
  total_requests: number;
  allowed_count: number;
  blocked_count: number;
  escalated_count: number;
  shadow_flagged_count: number;
  total_inr_settled: number;
  total_inr_protected: number;
  avg_l1_latency_ms: number;
  avg_l2_latency_ms: number;
  window_usage: WindowUsage;
}

/** GET /health */
export interface HealthStatus {
  status: string;
  service: string;
  storage_backend: string;
  payment_vault: { configured: boolean; test_mode: boolean; rail: string };
  layer2_auditor: string;
  policy_compiler: string;
  adk_agent: string;
  region: string;
}

export type ApprovalStatus = "PENDING" | "PROCESSING" | "APPROVED" | "REJECTED" | "INTEGRITY_FAILED";

/** The sealed execution envelope (backend/app/domain/hashing.py::build_execution_envelope). */
export interface CanonicalEnvelope {
  v: number;
  tool_name: string;
  merchant_id: string;
  amount_paise: number;
  currency: "INR";
  destination_mode: DestinationMode;
  args: Record<string, unknown>;
}

/** GET /v1/approvals row (hitl_approvals + decoded JSON). */
export interface ApprovalRecord {
  approval_id: string;
  audit_id: string;
  reservation_id: string | null;
  canonical_payload_json: string;
  payload_sha256: string;
  status: ApprovalStatus;
  created_at: string;
  reviewer_id: string | null;
  decision_note: string | null;
  decided_at: string | null;
  settlement_txn_id: string | null;
  decision_audit_id: string | null;
  canonical_payload: CanonicalEnvelope;
  request: Omit<InterceptRequest, "attachment_base64">;
}

/** POST /v1/approvals/{approval_id}/decide body. */
export interface DecideRequest {
  decision: "APPROVE" | "REJECT";
  reviewer_id: string;
  note?: string;
}

/** POST /v1/agent/run body (AgentRunRequest). */
export interface AgentRunRequest {
  prompt: string;
  untrusted_context?: string | null;
  attachment_base64?: string | null;
  attachment_mime?: string | null;
  policy_id?: string;
  contact_changed_hours_ago?: number | null;
  destination_mode?: DestinationMode | null;
  simulate_timeout?: boolean;
  preset_pdf?: DemoPdfPreset | null;
}

export interface AgentToolCall {
  id: string | null;
  name: string;
  args: Record<string, unknown>;
}

export interface AgentToolResponse {
  id: string | null;
  name: string;
  response: Record<string, unknown>;
}

/** POST /v1/agent/run response (AgentRunResult). */
export interface AgentRunResult {
  agent_response: string;
  decisions: AuditDecision[];
  tool_calls_proposed: AgentToolCall[];
  tool_responses: AgentToolResponse[];
  total_agent_latency_ms: number;
  session_id: string;
  model: string;
  local_tool_bodies_executed: number;
}

/** GET /v1/demo/pdfs item. */
export interface DemoPdf {
  name: string;
  preset: DemoPdfPreset | null;
  size_bytes: number;
  sha256: string;
  mime: string;
  url: string;
}

/** POST /v1/demo/reset body + response. */
export interface DemoResetRequest {
  agent_id?: string | null;
  windows_only?: boolean;
}
export interface DemoResetResponse {
  reset: "all_demo_data" | "windows";
  policies_preserved?: boolean;
  ledger_rows: number;
  audits?: number;
  idempotency_keys?: number;
  hitl_approvals?: number;
}

/** POST /v1/policies/compile (Slice 5 Policy Studio). */
export interface CompileRequest {
  instruction: string;
  policy_id?: string;
  apply?: boolean;
}
export interface CompileResult {
  policy: PolicyConfig;
  previous_policy: PolicyConfig | null;
  changes_summary: string[];
  model_used: string;
  fallback_used: boolean;
  applied: boolean;
  latency_ms: number;
}

/** GET /v1/audits/{audit_id}/rbi-incident-report (services/rbi_reporting.py). */
export interface RbiIncidentReport {
  report_type: string;
  schema_version: string;
  incident_id: string;
  generated_at: string;
  regulatory_framework: {
    primary_circular: string;
    primary_circular_title: string;
    related_circulars: string[];
    cert_in_reporting_window_hours: number;
    reporting_deadline_utc: string;
    within_reporting_window: boolean;
  };
  reporting_entity: { system: string; environment: string; data_residency_region: string };
  incident_classification: {
    categories: string[];
    severity: "LOW" | "MEDIUM" | "HIGH";
    verdict: Verdict;
    detection_layer: LayerDecided;
    risk_score: number;
    status: string;
  };
  policy_citations: { policy_id: string; regulatory_reference: string | null }[];
  transaction: Record<string, unknown>;
  financial_impact: { amount_at_risk_inr: number; amount_lost_inr: number };
  integrity: { payload_sha256: string; hash_algorithm: string };
  description: string;
  timeline: { timestamp: string; event: string }[];
}
