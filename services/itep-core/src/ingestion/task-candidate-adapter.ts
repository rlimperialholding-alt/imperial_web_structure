import type { ActorContext } from "../application/ports.js";
import type { TaskApplicationService } from "../application/task-service.js";
import type { CandidateTaskCreator } from "./ports.js";
import type { TaskCandidate } from "./types.js";

export interface CandidateResolutionPolicy {
  resolveAssignee(candidate: TaskCandidate): string;
  resolveEscalationPerson(candidate: TaskCandidate): string;
  resolveContactEmail(candidate: TaskCandidate): string;
}

export class TaskApplicationCandidateCreator
  implements CandidateTaskCreator {
  constructor(
    private readonly service: TaskApplicationService,
    private readonly actor: ActorContext,
    private readonly policy: CandidateResolutionPolicy,
  ) {}

  async createFromCandidate(candidate: TaskCandidate): Promise<{ taskId: string }> {
    const assigneeId =
      candidate.assigneeId ?? this.policy.resolveAssignee(candidate);
    const escalationPersonId =
      candidate.escalationPersonId ??
      this.policy.resolveEscalationPerson(candidate);
    const contactEmail =
      candidate.contactEmail ??
      this.policy.resolveContactEmail(candidate);

    const task = await this.service.create(this.actor, {
      organizationId: candidate.organizationId,
      legalEntityId: candidate.legalEntityId,
      source: candidate.source,
      sourceExternalId: candidate.sourceExternalId,
      issuerId: candidate.issuerId,
      assigneeId,
      assigneeType: "EMPLOYEE",
      title: candidate.title,
      description: candidate.description,
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
      status: "ASSIGNED",
    });

    return { taskId: task.id };
  }
}

function defaultDueAt(): Date {
  const dueAt = new Date();
  dueAt.setUTCDate(dueAt.getUTCDate() + 2);
  return dueAt;
}
