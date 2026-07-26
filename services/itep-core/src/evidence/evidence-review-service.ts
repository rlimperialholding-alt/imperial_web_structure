import type {
  ActorContext,
  AuditRepository,
  Clock,
  EvidenceVerifier,
  TaskRepository,
} from "../application/ports.js";
import {
  createAuditEvent,
  transitionTask,
} from "../domain/index.js";

export interface HumanAnneIncidentWriter {
  open(input: {
    taskId: string;
    category: string;
    severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
    title: string;
    description: string;
    recommendedAction: string;
    source: string;
    createdAt: Date;
  }): Promise<void>;
}

export class EvidenceReviewService {
  constructor(
    private readonly tasks: TaskRepository,
    private readonly audit: AuditRepository,
    private readonly verifier: EvidenceVerifier,
    private readonly incidents: HumanAnneIncidentWriter,
    private readonly clock: Clock,
  ) {}

  async reviewLatestEvidence(
    actor: ActorContext,
    taskId: string,
  ): Promise<{ accepted: boolean; reason: string }> {
    const task = await this.tasks.getById(taskId);
    if (!task) throw new Error(`Task not found: ${taskId}`);

    const latest = [...task.evidenceSubmissions]
      .sort((a, b) => b.submittedAt.getTime() - a.submittedAt.getTime())[0];

    if (!latest) {
      throw new Error("Task has no evidence submission");
    }

    const now = this.clock.now();
    const result = await this.verifier.verify(task, latest);

    await this.audit.append(
      createAuditEvent(
        task,
        "EVIDENCE_VERIFIED",
        actor.actorId,
        now,
        {
          evidenceId: latest.id,
          accepted: result.accepted,
          reason: result.reason,
          verifiedBy: result.verifiedBy,
        },
      ),
    );

    if (!result.accepted) {
      await this.incidents.open({
        taskId,
        category: "EVIDENCE_VERIFICATION",
        severity: task.priority === "P1" ? "CRITICAL" : "HIGH",
        title: `Bizonyíték-ellenőrzési probléma: ${task.title}`,
        description: result.reason,
        recommendedAction:
          "A Human Anne ellenőrizze a bizonyítékot és kérjen javítást vagy új feltöltést.",
        source: "digital-anne-evidence-review",
        createdAt: now,
      });
      return result;
    }

    if (
      task.evidenceRequirement.machineVerifiable &&
      task.status === "UNDER_REVIEW"
    ) {
      const closed = transitionTask(
        task,
        "CLOSED",
        actor.actorId,
        now,
      );
      await this.tasks.save(closed);
      await this.audit.append(
        createAuditEvent(
          closed,
          "TASK_AUTO_ACCEPTED",
          actor.actorId,
          now,
          {
            evidenceId: latest.id,
            verifier: result.verifiedBy,
          },
        ),
      );
    }

    return result;
  }
}
