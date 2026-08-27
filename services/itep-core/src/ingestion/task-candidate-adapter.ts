import type { ActorContext } from "../application/ports.js";
import type { TaskApplicationService } from "../application/task-service.js";
import type { CandidateTaskCreator } from "./ports.js";
import type { TaskCandidate } from "./types.js";

export interface CandidateResolutionPolicy {
  resolveAssignee(candidate: TaskCandidate): string;
  resolveEscalationPerson(candidate: TaskCandidate): string;
  resolveContactEmail(candidate: TaskCandidate): string;
}

export const SYSTEM_TECHNICAL_QUEUE = "system-technical-incidents";
export const SYSTEM_BUSINESS_REVIEW_QUEUE = "system-business-review";
const HUMAN_ANNE_IDS = new Set(["human-anne", "molnár-andrea", "molnar-andrea"]);
const TECHNICAL_MARKERS = [
  "adapter", "api", "ci/cd", "connector", "credential", "cron", "database",
  "deployment", "docker", "exception", "failure", "hiba", "gmail", "google ads",
  "idempotency", "infrastructure", "meta", "missing runtime secret", "oauth",
  "permission", "publication", "publikáció", "secret", "smtp", "systemd", "timeout",
  "webhook", "wordpress",
];

function containsTechnicalMarker(context: string): boolean {
  return TECHNICAL_MARKERS.some((marker) => {
    const escaped = marker
      .replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
      .replace(/\s+/g, "\\s+");
    return new RegExp(
      `(^|[^\\p{L}\\p{N}])${escaped}(?=$|[^\\p{L}\\p{N}])`, "iu",
    ).test(context);
  });
}

export function resolveCandidateRouting(candidate: TaskCandidate): {
  assigneeId: string; status: "DRAFT" | "ASSIGNED"; reason: string;
} {
  const context = [candidate.title, candidate.description, ...candidate.reasons]
    .join(" ").toLocaleLowerCase("hu-HU");
  if (containsTechnicalMarker(context)) {
    return { assigneeId: SYSTEM_TECHNICAL_QUEUE, status: "DRAFT", reason: "technical_incident_unassigned" };
  }
  const requested = candidate.assigneeId?.toLocaleLowerCase("hu-HU");
  const hasDirectWorkLink = /https:\/\/\S+/i.test(candidate.description);
  const hasDesiredAction = candidate.description.trim().length >= 20;
  const hasDoneCondition = candidate.acceptanceCriteria.trim().length >= 15;
  const hasAccessContext = candidate.evidenceDescription.trim().length >= 10;
  if (
    requested && HUMAN_ANNE_IDS.has(requested) && hasDirectWorkLink &&
    hasDesiredAction && hasDoneCondition && hasAccessContext && !candidate.requiresHumanReview
  ) {
    return { assigneeId: candidate.assigneeId!, status: "ASSIGNED", reason: "complete_business_task" };
  }
  return { assigneeId: SYSTEM_BUSINESS_REVIEW_QUEUE, status: "DRAFT", reason: "business_task_requires_review" };
}

export class TaskApplicationCandidateCreator
  implements CandidateTaskCreator {
  constructor(
    private readonly service: TaskApplicationService,
    private readonly actor: ActorContext,
    private readonly policy: CandidateResolutionPolicy,
  ) {}

  async createFromCandidate(candidate: TaskCandidate): Promise<{ taskId: string }> {
    const routing = resolveCandidateRouting(candidate);
    const assigneeId = routing.assigneeId || this.policy.resolveAssignee(candidate);
    const escalationPersonId =
      candidate.escalationPersonId ??
      this.policy.resolveEscalationPerson(candidate);
    const contactEmail =
      candidate.contactEmail ??
      this.policy.resolveContactEmail(candidate);

    const task = await this.service.create(this.actor, {
      organizationId: candidate.organizationId,
      source: candidate.source,
      sourceExternalId: candidate.sourceExternalId,
      issuerId: candidate.issuerId,
      assigneeId,
      assigneeType: "EMPLOYEE",
      title: candidate.title,
      description: `${candidate.description}\n\n[Routing: ${routing.reason}]`,
      priority: candidate.priority,
      dueAt: candidate.dueAt ?? defaultDueAt(),
      acceptanceCriteria: candidate.acceptanceCriteria,
      evidenceRequirement: {
        type: "OTHER",
        description: candidate.evidenceDescription,
        machineVerifiable: false,
      },
      escalationPersonId,
      contact: { email: contactEmail },
      relatedEntityIds: [candidate.sourceEventId],
      dependencies: [],
      sensitivity: candidate.sensitivity,
      status: routing.status,
    });

    return { taskId: task.id };
  }
}

function defaultDueAt(): Date {
  const dueAt = new Date();
  dueAt.setUTCDate(dueAt.getUTCDate() + 2);
  return dueAt;
}
