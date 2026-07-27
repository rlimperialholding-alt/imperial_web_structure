-- Internal Imperial identity, company/project authorization and WhatsApp CRM messaging.

CREATE TYPE "AuthUserStatus" AS ENUM ('INVITED', 'ACTIVE', 'SUSPENDED', 'DISABLED');
CREATE TYPE "AuthJobRole" AS ENUM ('SYSTEM_ADMIN', 'EXECUTIVE', 'FINANCE', 'HR', 'SALES', 'MARKETING', 'PROJECT_MANAGER', 'ENGINEERING', 'LEGAL', 'PROCUREMENT', 'WAREHOUSE', 'SUBCONTRACTOR', 'CUSTOMER');
CREATE TYPE "WhatsAppConversationStatus" AS ENUM ('OPEN', 'PENDING', 'CLOSED', 'BLOCKED');
CREATE TYPE "WhatsAppDirection" AS ENUM ('INBOUND', 'OUTBOUND');
CREATE TYPE "WhatsAppMessageStatus" AS ENUM ('RECEIVED', 'PENDING_APPROVAL', 'APPROVED', 'SENT', 'DELIVERED', 'READ', 'FAILED', 'REJECTED');

ALTER TYPE "ConnectorKind" ADD VALUE IF NOT EXISTS 'WHATSAPP_BUSINESS';

CREATE TABLE "AuthOrganization" (
  "id" TEXT NOT NULL,
  "displayName" TEXT NOT NULL,
  "taxNumber" TEXT,
  "active" BOOLEAN NOT NULL DEFAULT true,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  CONSTRAINT "AuthOrganization_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "AuthUser" (
  "id" TEXT NOT NULL,
  "email" TEXT NOT NULL,
  "displayName" TEXT NOT NULL,
  "passwordHash" TEXT,
  "status" "AuthUserStatus" NOT NULL DEFAULT 'INVITED',
  "isSystemAdmin" BOOLEAN NOT NULL DEFAULT false,
  "isExecutive" BOOLEAN NOT NULL DEFAULT false,
  "mfaEnabled" BOOLEAN NOT NULL DEFAULT false,
  "mfaSecretCiphertext" TEXT,
  "failedLoginAttempts" INTEGER NOT NULL DEFAULT 0,
  "lockedUntil" TIMESTAMP(3),
  "lastLoginAt" TIMESTAMP(3),
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  CONSTRAINT "AuthUser_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "AuthMembership" (
  "id" TEXT NOT NULL,
  "userId" TEXT NOT NULL,
  "organizationId" TEXT NOT NULL,
  "jobRole" "AuthJobRole" NOT NULL,
  "projectIds" TEXT[] NOT NULL,
  "permissionGrants" TEXT[] NOT NULL,
  "permissionDenials" TEXT[] NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  CONSTRAINT "AuthMembership_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "AuthSession" (
  "id" TEXT NOT NULL,
  "userId" TEXT NOT NULL,
  "organizationId" TEXT NOT NULL,
  "tokenHash" TEXT NOT NULL,
  "csrfTokenHash" TEXT NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "lastSeenAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "expiresAt" TIMESTAMP(3) NOT NULL,
  "revokedAt" TIMESTAMP(3),
  "ipHash" TEXT,
  "userAgent" TEXT,
  CONSTRAINT "AuthSession_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "AuthChallenge" (
  "id" TEXT NOT NULL,
  "userId" TEXT NOT NULL,
  "purpose" TEXT NOT NULL,
  "tokenHash" TEXT NOT NULL,
  "metadata" JSONB,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "expiresAt" TIMESTAMP(3) NOT NULL,
  "consumedAt" TIMESTAMP(3),
  CONSTRAINT "AuthChallenge_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "AuthRecoveryCode" (
  "id" TEXT NOT NULL,
  "userId" TEXT NOT NULL,
  "codeHash" TEXT NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "usedAt" TIMESTAMP(3),
  CONSTRAINT "AuthRecoveryCode_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "AuthInvitation" (
  "id" TEXT NOT NULL,
  "userId" TEXT NOT NULL,
  "tokenHash" TEXT NOT NULL,
  "createdBy" TEXT NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "expiresAt" TIMESTAMP(3) NOT NULL,
  "acceptedAt" TIMESTAMP(3),
  "revokedAt" TIMESTAMP(3),
  CONSTRAINT "AuthInvitation_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "SecurityAuditEvent" (
  "id" TEXT NOT NULL,
  "organizationId" TEXT,
  "actorId" TEXT,
  "eventType" TEXT NOT NULL,
  "targetType" TEXT,
  "targetId" TEXT,
  "occurredAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "requestId" TEXT,
  "ipHash" TEXT,
  "metadata" JSONB NOT NULL,
  CONSTRAINT "SecurityAuditEvent_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "WhatsAppConversation" (
  "id" TEXT NOT NULL,
  "organizationId" TEXT NOT NULL,
  "connectorAccountId" TEXT NOT NULL,
  "waContactHash" TEXT NOT NULL,
  "waContactCiphertext" TEXT NOT NULL,
  "displayName" TEXT,
  "phoneMasked" TEXT NOT NULL,
  "crmCustomerId" TEXT,
  "projectId" TEXT,
  "assignedUserId" TEXT,
  "status" "WhatsAppConversationStatus" NOT NULL DEFAULT 'OPEN',
  "lastMessageAt" TIMESTAMP(3) NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  CONSTRAINT "WhatsAppConversation_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "WhatsAppMessage" (
  "id" TEXT NOT NULL,
  "conversationId" TEXT NOT NULL,
  "providerMessageId" TEXT,
  "direction" "WhatsAppDirection" NOT NULL,
  "status" "WhatsAppMessageStatus" NOT NULL,
  "messageType" TEXT NOT NULL,
  "bodyCiphertext" TEXT,
  "mediaId" TEXT,
  "replyToProviderId" TEXT,
  "requestedBy" TEXT,
  "approvedBy" TEXT,
  "approvedAt" TIMESTAMP(3),
  "rejectedBy" TEXT,
  "rejectedAt" TIMESTAMP(3),
  "rejectionReason" TEXT,
  "sentAt" TIMESTAMP(3),
  "deliveredAt" TIMESTAMP(3),
  "readAt" TIMESTAMP(3),
  "failedAt" TIMESTAMP(3),
  "errorCode" TEXT,
  "errorMessage" TEXT,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  CONSTRAINT "WhatsAppMessage_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "WhatsAppWebhookEvent" (
  "id" TEXT NOT NULL,
  "eventFingerprint" TEXT NOT NULL,
  "providerEventId" TEXT,
  "eventType" TEXT NOT NULL,
  "receivedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "processedAt" TIMESTAMP(3),
  "lastError" TEXT,
  "payload" JSONB NOT NULL,
  CONSTRAINT "WhatsAppWebhookEvent_pkey" PRIMARY KEY ("id")
);

CREATE UNIQUE INDEX "AuthUser_email_key" ON "AuthUser"("email");
CREATE INDEX "AuthUser_status_email_idx" ON "AuthUser"("status", "email");
CREATE UNIQUE INDEX "AuthMembership_userId_organizationId_key" ON "AuthMembership"("userId", "organizationId");
CREATE INDEX "AuthMembership_organizationId_jobRole_idx" ON "AuthMembership"("organizationId", "jobRole");
CREATE UNIQUE INDEX "AuthSession_tokenHash_key" ON "AuthSession"("tokenHash");
CREATE INDEX "AuthSession_userId_revokedAt_expiresAt_idx" ON "AuthSession"("userId", "revokedAt", "expiresAt");
CREATE INDEX "AuthSession_organizationId_expiresAt_idx" ON "AuthSession"("organizationId", "expiresAt");
CREATE UNIQUE INDEX "AuthChallenge_tokenHash_key" ON "AuthChallenge"("tokenHash");
CREATE INDEX "AuthChallenge_userId_purpose_expiresAt_idx" ON "AuthChallenge"("userId", "purpose", "expiresAt");
CREATE UNIQUE INDEX "AuthRecoveryCode_codeHash_key" ON "AuthRecoveryCode"("codeHash");
CREATE INDEX "AuthRecoveryCode_userId_usedAt_idx" ON "AuthRecoveryCode"("userId", "usedAt");
CREATE UNIQUE INDEX "AuthInvitation_tokenHash_key" ON "AuthInvitation"("tokenHash");
CREATE INDEX "AuthInvitation_userId_expiresAt_idx" ON "AuthInvitation"("userId", "expiresAt");
CREATE INDEX "SecurityAuditEvent_organizationId_occurredAt_idx" ON "SecurityAuditEvent"("organizationId", "occurredAt");
CREATE INDEX "SecurityAuditEvent_actorId_occurredAt_idx" ON "SecurityAuditEvent"("actorId", "occurredAt");
CREATE INDEX "SecurityAuditEvent_eventType_occurredAt_idx" ON "SecurityAuditEvent"("eventType", "occurredAt");
CREATE UNIQUE INDEX "WhatsAppConversation_organizationId_connectorAccountId_waContactHash_key" ON "WhatsAppConversation"("organizationId", "connectorAccountId", "waContactHash");
CREATE INDEX "WhatsAppConversation_organizationId_status_lastMessageAt_idx" ON "WhatsAppConversation"("organizationId", "status", "lastMessageAt");
CREATE INDEX "WhatsAppConversation_crmCustomerId_lastMessageAt_idx" ON "WhatsAppConversation"("crmCustomerId", "lastMessageAt");
CREATE INDEX "WhatsAppConversation_projectId_lastMessageAt_idx" ON "WhatsAppConversation"("projectId", "lastMessageAt");
CREATE UNIQUE INDEX "WhatsAppMessage_providerMessageId_key" ON "WhatsAppMessage"("providerMessageId");
CREATE INDEX "WhatsAppMessage_conversationId_createdAt_idx" ON "WhatsAppMessage"("conversationId", "createdAt");
CREATE INDEX "WhatsAppMessage_status_createdAt_idx" ON "WhatsAppMessage"("status", "createdAt");
CREATE UNIQUE INDEX "WhatsAppWebhookEvent_eventFingerprint_key" ON "WhatsAppWebhookEvent"("eventFingerprint");
CREATE INDEX "WhatsAppWebhookEvent_processedAt_receivedAt_idx" ON "WhatsAppWebhookEvent"("processedAt", "receivedAt");

ALTER TABLE "AuthMembership" ADD CONSTRAINT "AuthMembership_userId_fkey" FOREIGN KEY ("userId") REFERENCES "AuthUser"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "AuthMembership" ADD CONSTRAINT "AuthMembership_organizationId_fkey" FOREIGN KEY ("organizationId") REFERENCES "AuthOrganization"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "AuthSession" ADD CONSTRAINT "AuthSession_userId_fkey" FOREIGN KEY ("userId") REFERENCES "AuthUser"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "AuthChallenge" ADD CONSTRAINT "AuthChallenge_userId_fkey" FOREIGN KEY ("userId") REFERENCES "AuthUser"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "AuthRecoveryCode" ADD CONSTRAINT "AuthRecoveryCode_userId_fkey" FOREIGN KEY ("userId") REFERENCES "AuthUser"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "AuthInvitation" ADD CONSTRAINT "AuthInvitation_userId_fkey" FOREIGN KEY ("userId") REFERENCES "AuthUser"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "WhatsAppMessage" ADD CONSTRAINT "WhatsAppMessage_conversationId_fkey" FOREIGN KEY ("conversationId") REFERENCES "WhatsAppConversation"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
