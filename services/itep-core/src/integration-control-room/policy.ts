import type {
  ConnectorOperationalSnapshot,
  IncidentSeverity,
} from "./domain.js";

export interface IntegrationPolicy {
  degradedFailureThreshold: number;
  failedFailureThreshold: number;
  deadLetterIncidentThreshold: number;
  stalledMinutes: number;
  retryBaseDelaySeconds: number;
  retryMaxDelaySeconds: number;
}

export const defaultIntegrationPolicy: IntegrationPolicy = {
  degradedFailureThreshold: 2,
  failedFailureThreshold: 5,
  deadLetterIncidentThreshold: 3,
  stalledMinutes: 30,
  retryBaseDelaySeconds: 30,
  retryMaxDelaySeconds: 3600,
};

export function calculateRetryDelaySeconds(
  attempt: number,
  policy: IntegrationPolicy = defaultIntegrationPolicy,
): number {
  const exponential = policy.retryBaseDelaySeconds * 2 ** Math.max(0, attempt - 1);
  return Math.min(exponential, policy.retryMaxDelaySeconds);
}

export function deriveOperationalStatus(
  snapshot: ConnectorOperationalSnapshot,
  policy: IntegrationPolicy = defaultIntegrationPolicy,
): ConnectorOperationalSnapshot["status"] {
  if (snapshot.reauthRequired) return "REAUTH_REQUIRED";
  if (
    snapshot.rateLimitedUntil &&
    snapshot.rateLimitedUntil.getTime() > Date.now()
  ) {
    return "RATE_LIMITED";
  }
  if (snapshot.consecutiveFailures >= policy.failedFailureThreshold) {
    return "FAILED";
  }
  if (snapshot.consecutiveFailures >= policy.degradedFailureThreshold) {
    return "DEGRADED";
  }
  return snapshot.status === "DISCONNECTED" ? "DISCONNECTED" : "HEALTHY";
}

export function incidentSeverityFor(
  snapshot: ConnectorOperationalSnapshot,
): IncidentSeverity {
  if (snapshot.status === "FAILED" || snapshot.reauthRequired) return "CRITICAL";
  if (snapshot.deadLetterCount >= 3) return "HIGH";
  if (snapshot.status === "DEGRADED" || snapshot.status === "RATE_LIMITED") {
    return "MEDIUM";
  }
  return "LOW";
}
