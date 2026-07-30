import type { Clock } from "../application/ports.js";
import type {
  CandidateTaskCreator,
  IngestionReviewQueue,
  SourceEventRepository,
  TaskCandidateDeduplicator,
} from "./ports.js";
import type { SourceEvent } from "./types.js";
import { IngestionRuleEngine } from "./rules.js";

export class SourceIngestionService {
  constructor(
    private readonly events: SourceEventRepository,
    private readonly engine: IngestionRuleEngine,
    private readonly deduplicator: TaskCandidateDeduplicator,
    private readonly creator: CandidateTaskCreator,
    private readonly reviewQueue: IngestionReviewQueue,
    private readonly clock: Clock,
  ) {}

  async ingest(event: SourceEvent): Promise<{
    status: string;
    taskId?: string;
    reason: string;
  }> {
    const existing =
      (await this.events.findByFingerprint(event.fingerprint))
      ?? (await this.events.findByExternalIdentity({
        organizationId: event.organizationId,
        source: event.source,
        externalId: event.externalId,
      }));
    if (existing) {
      return {
        status: "DUPLICATE_EVENT",
        reason: "A forrásesemény már feldolgozásra került.",
      };
    }

    try {
      await this.events.create(event);
    } catch (error) {
      // A manual sync and the scheduled worker may observe the same event
      // before either transaction commits. Treat the losing unique-key race
      // exactly like the normal duplicate path, but do not hide real storage
      // failures.
      const concurrentlyCreated =
        (await this.events.findByFingerprint(event.fingerprint))
        ?? (await this.events.findByExternalIdentity({
          organizationId: event.organizationId,
          source: event.source,
          externalId: event.externalId,
        }));
      if (concurrentlyCreated) {
        return {
          status: "DUPLICATE_EVENT",
          reason: "A forráseseményt egy párhuzamos szinkron már feldolgozta.",
        };
      }
      throw error;
    }

    try {
      const decision = this.engine.evaluate(event);

      if (decision.action === "IGNORE") {
        await this.events.updateStatus(event.id, "IGNORED");
        return { status: "IGNORED", reason: decision.reason };
      }

      if (!decision.candidate) {
        throw new Error("Ingestion decision is missing task candidate");
      }

      if (decision.action === "HUMAN_REVIEW") {
        await this.reviewQueue.enqueue({
          event,
          decision,
          createdAt: this.clock.now(),
        });
        await this.events.updateStatus(event.id, "NEEDS_REVIEW");
        return {
          status: "NEEDS_REVIEW",
          reason: decision.reason,
        };
      }

      const duplicate = await this.deduplicator.findExisting(
        decision.candidate,
      );
      if (duplicate.duplicate) {
        await this.events.updateStatus(event.id, "IGNORED");
        return {
          status: "DUPLICATE_TASK",
          ...(duplicate.taskId ? { taskId: duplicate.taskId } : {}),
          reason: duplicate.reason ?? "Duplicate task",
        };
      }

      const created = await this.creator.createFromCandidate(
        decision.candidate,
      );
      await this.events.updateStatus(event.id, "TASK_CREATED");
      return {
        status: "TASK_CREATED",
        taskId: created.taskId,
        reason: decision.reason,
      };
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unknown ingestion error";
      await this.events.updateStatus(event.id, "FAILED", message);
      throw error;
    }
  }
}
