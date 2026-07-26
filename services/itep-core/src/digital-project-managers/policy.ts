export type DigitalActionRisk =
  | "R0" | "R1" | "R2" | "R3"
  | "R4" | "R5" | "R6" | "R7";

export type DigitalActionDecision =
  | "AUTOMATION_ALLOWED"
  | "HUMAN_REVIEW_REQUIRED"
  | "BLOCKED_AND_ESCALATED";

export function evaluateDigitalActionRisk(risk: DigitalActionRisk): {
  decision: DigitalActionDecision;
  executionAllowed: boolean;
  humanApprovalRequired: boolean;
  explanation: string;
} {
  const level = Number(risk.slice(1));
  if (level <= 3) {
    return {
      decision: "AUTOMATION_ALLOWED",
      executionAllowed: true,
      humanApprovalRequired: false,
      explanation: "Belső, visszafordítható vagy előkészítő művelet; a végrehajtás auditált.",
    };
  }
  if (level <= 5) {
    return {
      decision: "HUMAN_REVIEW_REQUIRED",
      executionAllowed: false,
      humanApprovalRequired: true,
      explanation: "Üzleti hatású művelet; végrehajtás előtt kijelölt emberi jóváhagyás szükséges.",
    };
  }
  return {
    decision: "BLOCKED_AND_ESCALATED",
    executionAllowed: false,
    humanApprovalRequired: true,
    explanation: "Szerződéses, pénzügyi, felelősségi vagy teljesítésigazolási kockázat; automatikusan tiltott és eszkalálandó.",
  };
}

