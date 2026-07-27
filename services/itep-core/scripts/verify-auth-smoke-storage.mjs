import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient({
  datasources: {
    db: {
      url:
        process.env.DATABASE_URL ??
        "postgresql://itep:itep-test-password@127.0.0.1:55432/itep_test?schema=public",
    },
  },
});

const [users, sessions, auditEvents, conversations, messages, webhookEvents] =
  await Promise.all([
    prisma.authUser.count(),
    prisma.authSession.count(),
    prisma.securityAuditEvent.count(),
    prisma.whatsAppConversation.count(),
    prisma.whatsAppMessage.findMany({
      select: { bodyCiphertext: true },
    }),
    prisma.whatsAppWebhookEvent.findMany({ select: { payload: true } }),
  ]);

assert(users === 2, "two smoke users");
assert(sessions >= 3, "enrollment and login sessions");
assert(auditEvents > 0, "security audit events");
assert(conversations === 1, "one smoke conversation");
assert(
  messages.length === 2 &&
    messages.every((message) => message.bodyCiphertext?.startsWith("v1.")),
  "message bodies are encrypted",
);
assert(
  webhookEvents.every(
    (event) => !JSON.stringify(event.payload).includes("Teszt bejövő üzenet"),
  ),
  "stored webhook summary excludes message content",
);

console.log(JSON.stringify({
  users,
  sessions,
  auditEvents,
  conversations,
  messages: messages.length,
  bodiesEncrypted: true,
  webhookPayloadRedacted: true,
}));
await prisma.$disconnect();

function assert(condition, label) {
  if (!condition) throw new Error(`Storage assertion failed: ${label}`);
}
