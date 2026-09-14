import type { Clock } from "../application/ports.js";
import type { CandidateTaskCreator } from "./ports.js";
import type { TaskCandidate } from "./types.js";

export interface IngestionReviewItem {
  id: string;
  organizationId: string;
  sourceEventId: string;
  candidate: TaskCandidate;
  status: "OPEN" | "APPROVED" | "REJECTED" | "CONVERTED";
  createdAt: Date;
  reviewedAt?: Date;
  reviewedBy?: string;
  resolution?: string;
}

export interface IngestionReviewRepository {
  getById(id: string): Promise<IngestionReviewItem | null>;
  listOpen(organizationId: string, limit: number): Promise<IngestionReviewItem[]>;
  save(item: IngestionReviewItem): Promise<void>;
}

export class IngestionReviewService {
  constructor(
    private readonly repository: IngestionReviewRepository,
    private readonly creator: CandidateTaskCreator,
    private readonly clock: Clock,
  ) {}

  listOpen(organizationId: string, limit = 100) {
    return this.repository.listOpen(organizationId, limit);
  }

  async approve(
    id: string,
    actorId: string,
    overrides: Partial<TaskCandidate> = {},
  ) {
    const item = await this.requireOpen(id);
    const candidate: TaskCandidate = {
      ...item.candidate,
      ...overrides,
      requiresHumanReview: false,
      confidence: 1,
      reasons: [
        ...item.candidate.reasons,
        `Human Anne jóváhagyta: ${actorId}`,
      ],
    };

    const created = await this.creator.createFromCandidate(candidate);
    await this.repository.save({
      ...item,
      candidate,
      status: "CONVERTED",
      reviewedAt: this.clock.now(),
      reviewedBy: actorId,
      resolution: `ITEP task created: ${created.taskId}`,
    });
    return created;
  }

  async reject(id: string, actorId: string, reason: string) {
    if (!reason.trim()) throw new Error("Rejection reason is required");
    const item = await this.requireOpen(id);
    await this.repository.save({
      ...item,
      status: "REJECTED",
      reviewedAt: this.clock.now(),
      reviewedBy: actorId,
      resolution: reason,
    });
  }

  private async requireOpen(id: string) {
    const item = await this.repository.getById(id);
    if (!item) throw new Error(`Review item not found: ${id}`);
    if (item.status !== "OPEN") {
      throw new Error("Review item is already processed");
    }
    return item;
  }
}
