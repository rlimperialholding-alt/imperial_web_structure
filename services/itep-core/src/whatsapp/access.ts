import type { ActorContext } from "../application/ports.js";

export function whatsappConversationScope(actor: ActorContext) {
  if (
    actor.permissions.includes("*") ||
    actor.permissions.includes("whatsapp.read")
  ) {
    return {};
  }
  return {
    OR: [
      ...(actor.projectIds?.length
        ? [{ projectId: { in: actor.projectIds } }]
        : []),
      { assignedUserId: actor.actorId },
    ],
  };
}

export function canReadWhatsAppConversation(
  actor: ActorContext,
  conversation: { projectId: string | null; assignedUserId: string | null },
): boolean {
  if (
    actor.permissions.includes("*") ||
    actor.permissions.includes("whatsapp.read")
  ) {
    return true;
  }
  return (
    conversation.assignedUserId === actor.actorId ||
    Boolean(
      conversation.projectId &&
        actor.projectIds?.includes(conversation.projectId),
    )
  );
}
