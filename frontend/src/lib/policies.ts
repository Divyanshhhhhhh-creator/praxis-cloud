/** Human labels for every policy citation the backend can emit (domain/policy_catalog.py + policy_corpus.py). */

export interface PolicyMeta {
  title: string;
  layer: "L1" | "L2" | "HITL" | "SYSTEM";
  reference?: string;
}

export const POLICY_CATALOG: Record<string, PolicyMeta> = {
  "POL-FIN-ALLOWLIST": { title: "Tool & merchant allowlist", layer: "L1" },
  "POL-RBI-COOLING-12H": { title: "12-hour contact-change cooling", layer: "L1", reference: "RBI/DPSS/2026-27/475" },
  "POL-RBI-PA-REFUND-01": { title: "Refund to original payment source", layer: "L1", reference: "RBI/DPSS/2025-26/141 (issued 15 Sep 2025, updated 11 Nov 2026)" },
  "POL-FIN-MAX-TXN": { title: "Hard single-transaction cap", layer: "L1" },
  "POL-FIN-VELOCITY": { title: "Velocity circuit-breaker", layer: "L1" },
  "POL-FIN-SLIDING-CAP": { title: "1m / 1h / 24h sliding spend cap", layer: "L1" },
  "POL-FIN-POLICY-NOT-FOUND": { title: "Unknown policy — fail closed", layer: "SYSTEM" },
  "POL-FIN-FAIL-CLOSED": { title: "Fail-closed safety net", layer: "SYSTEM" },
  "POL-RBI-AUDIT-5Y": { title: "Immutable 5-year audit & 6-hour reporting", layer: "L2", reference: "RBI/DPSS/2026-27/475" },
  "POL-FIN-INTENT-MATCH": { title: "Tool call must match user intent", layer: "L2" },
  "POL-FIN-INJECTION-DEFENSE": { title: "Indirect prompt-injection defense", layer: "L2" },
  "POL-FIN-VENDOR-VERIFY": { title: "Vendor invoice verification", layer: "L2" },
  "POL-FIN-HITL-THRESHOLD": { title: "Human-in-the-loop approval threshold", layer: "HITL" },
};

export function policyMeta(id: string): PolicyMeta {
  return POLICY_CATALOG[id] ?? { title: id, layer: "SYSTEM" };
}

export const DEFAULT_POLICY_ID = "default-fintech-treasury";
/** Wide-window lab policy so ₹48k red-team calls clear L1's ₹15k/min window and reach the L2 Gemini auditor. */
export const REDTEAM_POLICY_ID = "redteam-lab";
