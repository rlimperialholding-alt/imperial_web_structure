import { index, integer, primaryKey, sqliteTable, text, uniqueIndex } from "drizzle-orm/sqlite-core";

export const users = sqliteTable("users", {
  email: text("email").primaryKey(),
  displayName: text("display_name").notNull(),
  role: text("role", { enum: ["admin", "sales_manager", "sales"] }).notNull(),
  createdAt: text("created_at").notNull(),
  lastSeenAt: text("last_seen_at").notNull(),
});

export const leads = sqliteTable("leads", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  name: text("name").notNull(),
  title: text("title").notNull(),
  brand: text("brand").notNull(),
  brandCode: text("brand_code").notNull(),
  location: text("location").notNull(),
  email: text("email").notNull(),
  phone: text("phone").notNull(),
  source: text("source").notNull(),
  owner: text("owner").notNull(),
  ownerInitials: text("owner_initials").notNull(),
  stage: text("stage", { enum: ["new", "contact", "consultation", "offer", "negotiation", "contract"] }).notNull(),
  value: integer("value").notNull(),
  probability: integer("probability").notNull(),
  score: integer("score").notNull(),
  quality: integer("quality").notNull(),
  temperature: text("temperature", { enum: ["hot", "warm", "cold"] }).notNull(),
  health: text("health", { enum: ["green", "yellow", "red"] }).notNull(),
  nextAction: text("next_action").notNull(),
  nextDate: text("next_date").notNull(),
  projectType: text("project_type").notNull(),
  technology: text("technology").notNull(),
  plot: integer("plot", { mode: "boolean" }).notNull(),
  financing: integer("financing", { mode: "boolean" }).notNull(),
  notes: text("notes").notNull(),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
});

export const tasks = sqliteTable("tasks", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  title: text("title").notNull(),
  leadId: integer("lead_id").references(() => leads.id, { onDelete: "set null" }),
  leadName: text("lead_name").notNull(),
  type: text("type").notNull(),
  due: text("due").notNull(),
  priority: text("priority", { enum: ["critical", "high", "normal"] }).notNull(),
  done: integer("done", { mode: "boolean" }).notNull(),
  ai: integer("ai", { mode: "boolean" }).notNull(),
  ownerEmail: text("owner_email").notNull(),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
});

export const activities = sqliteTable("activities", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  actorEmail: text("actor_email").notNull(),
  action: text("action").notNull(),
  entityType: text("entity_type").notNull(),
  entityId: integer("entity_id").notNull(),
  detail: text("detail").notNull(),
  createdAt: text("created_at").notNull(),
});

export const migrationBatches = sqliteTable("crm_migration_batches", {
  idempotencyKey: text("idempotency_key").primaryKey(),
  workspaceId: text("workspace_id").notNull(),
  sourceSystem: text("source_system").notNull(),
  payloadSha256: text("payload_sha256").notNull(),
  requestedCount: integer("requested_count").notNull(),
  storedCount: integer("stored_count").notNull(),
  status: text("status", { enum: ["processing", "completed"] }).notNull(),
  createdAt: text("created_at").notNull(),
  completedAt: text("completed_at"),
}, (table) => [
  index("crm_migration_batches_workspace_idx").on(table.workspaceId, table.createdAt),
]);

export const migrationDocuments = sqliteTable("crm_migration_documents", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  batchId: text("batch_id").notNull().references(() => migrationBatches.idempotencyKey),
  workspaceId: text("workspace_id").notNull(),
  sourceSystem: text("source_system").notNull(),
  externalId: text("external_id").notNull(),
  title: text("title").notNull(),
  fileName: text("file_name").notNull(),
  contentType: text("content_type").notNull(),
  size: integer("size").notNull(),
  sha256: text("sha256").notNull(),
  objectKey: text("object_key").notNull().unique(),
  metadataJson: text("metadata_json").notNull(),
  migratedAt: text("migrated_at").notNull(),
}, (table) => [
  uniqueIndex("crm_migration_documents_source_idx").on(
    table.workspaceId,
    table.sourceSystem,
    table.externalId,
  ),
  index("crm_migration_documents_activity_idx").on(table.workspaceId, table.id),
  index("crm_migration_documents_batch_idx").on(table.batchId),
]);

export const customerImports = sqliteTable("crm_customer_imports", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  workspaceId: text("workspace_id").notNull(),
  sourceSystem: text("source_system").notNull(),
  externalId: text("external_id").notNull(),
  sourceKind: text("source_kind", {
    enum: ["contract_customer", "web_form_lead"],
  }).notNull(),
  leadId: integer("lead_id").notNull().references(() => leads.id, {
    onDelete: "cascade",
  }),
  sourceUrl: text("source_url").notNull(),
  sourceDate: text("source_date").notNull(),
  payloadSha256: text("payload_sha256").notNull(),
  metadataJson: text("metadata_json").notNull(),
  importedAt: text("imported_at").notNull(),
}, (table) => [
  uniqueIndex("crm_customer_imports_source_idx").on(
    table.workspaceId,
    table.sourceSystem,
    table.externalId,
  ),
  index("crm_customer_imports_workspace_idx").on(table.workspaceId, table.id),
  index("crm_customer_imports_lead_idx").on(table.leadId),
]);

export const projects = sqliteTable("projects", {
  id: text("id").primaryKey(),
  portalCode: text("portal_code").notNull().unique(),
  customerName: text("customer_name").notNull(),
  customerEmail: text("customer_email").notNull(),
  title: text("title").notNull(),
  status: text("status", { enum: ["planning", "construction", "handover", "care"] }).notNull(),
  phase: text("phase").notNull(),
  progress: integer("progress").notNull(),
  targetCompletion: text("target_completion").notNull(),
  handoverDate: text("handover_date"),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
});

export const projectMembers = sqliteTable("project_members", {
  projectId: text("project_id").notNull().references(() => projects.id, { onDelete: "cascade" }),
  email: text("email").notNull(),
  role: text("role", { enum: ["customer", "contact", "project_manager", "technical", "finance", "warranty"] }).notNull(),
  createdAt: text("created_at").notNull(),
}, (table) => [
  primaryKey({ columns: [table.projectId, table.email] }),
  index("project_members_email_idx").on(table.email),
]);

export const projectTasks = sqliteTable("project_tasks", {
  id: text("id").primaryKey(),
  projectId: text("project_id").notNull().references(() => projects.id, { onDelete: "cascade" }),
  source: text("source").notNull(),
  title: text("title").notNull(),
  due: text("due").notNull(),
  status: text("status", { enum: ["waiting_customer", "submitted", "completed"] }).notNull(),
  severity: text("severity", { enum: ["normal", "high"] }).notNull(),
  action: text("action").notNull(),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
}, (table) => [index("project_tasks_project_idx").on(table.projectId)]);

export const projectChanges = sqliteTable("project_changes", {
  id: text("id").primaryKey(),
  projectId: text("project_id").notNull().references(() => projects.id, { onDelete: "cascade" }),
  title: text("title").notNull(),
  origin: text("origin").notNull(),
  scope: text("scope").notNull(),
  customerPriceImpact: text("customer_price_impact").notNull(),
  scheduleImpact: text("schedule_impact").notNull(),
  internalControlStatus: text("internal_control_status", { enum: ["pending", "passed", "escalated"] }).notNull(),
  status: text("status", { enum: ["internal_review", "customer_approval", "approved", "rejected"] }).notNull(),
  evidence: text("evidence").notNull(),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
  customerDecisionAt: text("customer_decision_at"),
  decidedByEmail: text("decided_by_email"),
}, (table) => [index("project_changes_project_idx").on(table.projectId)]);

export const projectDecisions = sqliteTable("project_decisions", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  projectId: text("project_id").notNull().references(() => projects.id, { onDelete: "cascade" }),
  title: text("title").notNull(),
  area: text("area").notNull(),
  due: text("due").notNull(),
  impact: text("impact").notNull(),
  status: text("status", { enum: ["open", "approved", "question"] }).notNull(),
  response: text("response").notNull(),
  decidedAt: text("decided_at"),
  decidedByEmail: text("decided_by_email"),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
}, (table) => [index("project_decisions_project_idx").on(table.projectId)]);

export const projectMessages = sqliteTable("project_messages", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  projectId: text("project_id").notNull().references(() => projects.id, { onDelete: "cascade" }),
  authorEmail: text("author_email").notNull(),
  topic: text("topic").notNull(),
  body: text("body").notNull(),
  createdAt: text("created_at").notNull(),
}, (table) => [index("project_messages_project_idx").on(table.projectId)]);

export const warrantyCases = sqliteTable("warranty_cases", {
  id: text("id").primaryKey(),
  projectId: text("project_id").notNull().references(() => projects.id, { onDelete: "cascade" }),
  title: text("title").notNull(),
  status: text("status", { enum: ["reported", "triage", "repair", "customer_confirmation", "closed"] }).notNull(),
  severity: text("severity", { enum: ["normal", "urgent"] }).notNull(),
  responsibleRole: text("responsible_role").notNull(),
  nextDeadline: text("next_deadline").notNull(),
  evidence: text("evidence").notNull(),
  customerConfirmed: integer("customer_confirmed", { mode: "boolean" }).notNull(),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
}, (table) => [index("warranty_cases_project_idx").on(table.projectId)]);

export const projectEvents = sqliteTable("project_events", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  projectId: text("project_id").notNull().references(() => projects.id, { onDelete: "cascade" }),
  actorEmail: text("actor_email").notNull(),
  action: text("action").notNull(),
  entityType: text("entity_type").notNull(),
  entityId: text("entity_id").notNull(),
  detail: text("detail").notNull(),
  createdAt: text("created_at").notNull(),
}, (table) => [index("project_events_project_idx").on(table.projectId)]);

export const projectDocuments = sqliteTable("project_documents", {
  id: text("id").primaryKey(),
  projectId: text("project_id").notNull().references(() => projects.id, { onDelete: "cascade" }),
  name: text("name").notNull(),
  group: text("group_name").notNull(),
  status: text("status", { enum: ["draft", "approval", "verified"] }).notNull(),
  currentVersion: integer("current_version").notNull(),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
}, (table) => [index("project_documents_project_idx").on(table.projectId)]);

export const projectDocumentVersions = sqliteTable("project_document_versions", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  documentId: text("document_id").notNull().references(() => projectDocuments.id, { onDelete: "cascade" }),
  version: integer("version").notNull(),
  objectKey: text("object_key").notNull().unique(),
  fileName: text("file_name").notNull(),
  contentType: text("content_type").notNull(),
  size: integer("size").notNull(),
  sha256: text("sha256").notNull(),
  uploadedByEmail: text("uploaded_by_email").notNull(),
  uploadedAt: text("uploaded_at").notNull(),
}, (table) => [
  uniqueIndex("project_document_versions_document_version_idx").on(table.documentId, table.version),
]);

export const projectInvitations = sqliteTable("project_invitations", {
  id: text("id").primaryKey(),
  projectId: text("project_id").notNull().references(() => projects.id, { onDelete: "cascade" }),
  email: text("email").notNull(),
  displayName: text("display_name").notNull(),
  role: text("role", { enum: ["customer", "contact", "project_manager", "technical", "finance", "warranty"] }).notNull(),
  tokenHash: text("token_hash").notNull().unique(),
  status: text("status", { enum: ["pending", "accepted", "revoked", "expired"] }).notNull(),
  invitedByEmail: text("invited_by_email").notNull(),
  expiresAt: text("expires_at").notNull(),
  acceptedAt: text("accepted_at"),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
}, (table) => [
  index("project_invitations_project_idx").on(table.projectId),
  index("project_invitations_email_idx").on(table.email),
]);

export const notificationPreferences = sqliteTable("notification_preferences", {
  projectId: text("project_id").notNull().references(() => projects.id, { onDelete: "cascade" }),
  memberEmail: text("member_email").notNull(),
  taskNotifications: integer("task_notifications", { mode: "boolean" }).notNull(),
  decisionNotifications: integer("decision_notifications", { mode: "boolean" }).notNull(),
  changeNotifications: integer("change_notifications", { mode: "boolean" }).notNull(),
  documentNotifications: integer("document_notifications", { mode: "boolean" }).notNull(),
  messageNotifications: integer("message_notifications", { mode: "boolean" }).notNull(),
  careNotifications: integer("care_notifications", { mode: "boolean" }).notNull(),
  digestFrequency: text("digest_frequency", { enum: ["immediate", "daily", "weekly", "off"] }).notNull(),
  updatedAt: text("updated_at").notNull(),
}, (table) => [
  primaryKey({ columns: [table.projectId, table.memberEmail] }),
  index("notification_preferences_member_idx").on(table.memberEmail),
]);

export const emailNotifications = sqliteTable("email_notifications", {
  id: text("id").primaryKey(),
  projectId: text("project_id").notNull().references(() => projects.id, { onDelete: "cascade" }),
  recipientEmail: text("recipient_email").notNull(),
  recipientName: text("recipient_name").notNull(),
  templateKey: text("template_key", { enum: ["invitation", "task", "decision", "change", "document", "message", "care"] }).notNull(),
  subject: text("subject").notNull(),
  htmlBody: text("html_body"),
  textBody: text("text_body"),
  status: text("status", { enum: ["draft", "approved", "sending", "sent", "failed", "cancelled"] }).notNull(),
  approvalRequired: integer("approval_required", { mode: "boolean" }).notNull(),
  approvedByEmail: text("approved_by_email"),
  approvedAt: text("approved_at"),
  providerMessageId: text("provider_message_id"),
  idempotencyKey: text("idempotency_key").notNull().unique(),
  attemptCount: integer("attempt_count").notNull(),
  lastError: text("last_error"),
  relatedEntityType: text("related_entity_type").notNull(),
  relatedEntityId: text("related_entity_id").notNull(),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
  sentAt: text("sent_at"),
}, (table) => [
  index("email_notifications_project_idx").on(table.projectId),
  index("email_notifications_recipient_idx").on(table.recipientEmail),
  index("email_notifications_status_idx").on(table.status),
]);
