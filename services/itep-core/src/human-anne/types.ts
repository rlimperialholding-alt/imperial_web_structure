export type IncidentSeverity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type IncidentStatus =
  | "OPEN"
  | "ACKNOWLEDGED"
  | "IN_PROGRESS"
  | "RESOLVED"
  | "DISMISSED";

export interface HumanAnneIncident {
  id: string;
  taskId?: string;
  category: string;
  severity: IncidentSeverity;
  status: IncidentStatus;
  title: string;
  description: string;
  recommendedAction: string;
  source: string;
  createdAt: Date;
  acknowledgedAt?: Date;
  acknowledgedBy?: string;
  resolvedAt?: Date;
  resolvedBy?: string;
  resolution?: string;
}
