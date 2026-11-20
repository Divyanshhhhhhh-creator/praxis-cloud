import type { AgentRunResult, AuditDecision } from "@/lib/types";

export type RunSource = "adk" | "intercept" | "burst" | "ledger" | "hitl";

/** Everything the Forensic Verdict Inspector renders for one run / selected audit. */
export interface RunView {
  source: RunSource;
  scenario?: string;
  decision: AuditDecision | null;
  agent?: AgentRunResult;
  burst?: AuditDecision[];
  /** The ESCALATE decision a HITL approve/reject resolved. */
  escalatedFrom?: AuditDecision;
}
