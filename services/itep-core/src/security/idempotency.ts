export interface IdempotencyRecord {
  key: string;
  scope: string;
  requestHash: string;
  responseStatus?: number;
  responseBody?: unknown;
  createdAt: Date;
  expiresAt: Date;
  completedAt?: Date;
}

export interface IdempotencyRepository {
  get(scope: string, key: string): Promise<IdempotencyRecord | null>;
  create(record: IdempotencyRecord): Promise<void>;
  complete(input: {
    scope: string;
    key: string;
    responseStatus: number;
    responseBody: unknown;
    completedAt: Date;
  }): Promise<void>;
}

export class IdempotencyService {
  constructor(
    private readonly repository: IdempotencyRepository,
    private readonly now: () => Date,
    private readonly ttlMs = 24 * 60 * 60 * 1000,
  ) {}

  async begin(input: {
    scope: string;
    key: string;
    requestHash: string;
  }): Promise<
    | { mode: "NEW" }
    | { mode: "REPLAY"; status: number; body: unknown }
  > {
    const existing = await this.repository.get(input.scope, input.key);
    if (existing) {
      if (existing.requestHash !== input.requestHash) {
        throw new Error("Idempotency key reused with different request");
      }
      if (
        existing.completedAt &&
        existing.responseStatus !== undefined
      ) {
        return {
          mode: "REPLAY",
          status: existing.responseStatus,
          body: existing.responseBody,
        };
      }
      throw new Error("Idempotent operation is already in progress");
    }

    const now = this.now();
    await this.repository.create({
      key: input.key,
      scope: input.scope,
      requestHash: input.requestHash,
      createdAt: now,
      expiresAt: new Date(now.getTime() + this.ttlMs),
    });

    return { mode: "NEW" };
  }

  async complete(input: {
    scope: string;
    key: string;
    responseStatus: number;
    responseBody: unknown;
  }) {
    await this.repository.complete({
      ...input,
      completedAt: this.now(),
    });
  }
}
