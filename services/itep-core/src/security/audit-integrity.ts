import { createHash } from "node:crypto";

export interface AuditChainEvent {
  id: string;
  taskId: string;
  eventType: string;
  actorId: string;
  occurredAt: Date;
  sequence: bigint;
  payload: unknown;
  previousHash?: string;
  hash?: string;
}

export function calculateAuditHash(
  event: Omit<AuditChainEvent, "hash">,
): string {
  return createHash("sha256")
    .update(
      JSON.stringify({
        id: event.id,
        taskId: event.taskId,
        eventType: event.eventType,
        actorId: event.actorId,
        occurredAt: event.occurredAt.toISOString(),
        sequence: event.sequence.toString(),
        payload: event.payload,
        previousHash: event.previousHash ?? null,
      }),
    )
    .digest("hex");
}

export function verifyAuditChain(events: AuditChainEvent[]): {
  valid: boolean;
  brokenAt?: string;
} {
  const ordered = [...events].sort((a, b) =>
    a.sequence < b.sequence ? -1 : a.sequence > b.sequence ? 1 : 0,
  );

  let previousHash: string | undefined;
  for (const event of ordered) {
    if (event.previousHash !== previousHash) {
      return { valid: false, brokenAt: event.id };
    }
    const calculated = calculateAuditHash({
      ...event,
      previousHash,
    });
    if (event.hash !== calculated) {
      return { valid: false, brokenAt: event.id };
    }
    previousHash = event.hash;
  }

  return { valid: true };
}
