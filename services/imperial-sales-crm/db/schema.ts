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

export const customers = sqliteTable("crm_customers", {
  id: text("id").primaryKey(),
  customerType: text("customer_type", { enum: ["person", "company"] }).notNull(),
  name: text("name").notNull(),
  email: text("email").notNull(),
  phone: text("phone").notNull(),
  billingAddress: text("billing_address").notNull(),
  taxNumber: text("tax_number"),
  companyRegistrationNumber: text("company_registration_number"),
  sourceLeadId: integer("source_lead_id").references(() => leads.id, { onDelete: "set null" }),
  status: text("status", { enum: ["prospect", "active", "archived"] }).notNull(),
  createdByEmail: text("created_by_email").notNull(),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
}, (table) => [
  uniqueIndex("crm_customers_email_idx").on(table.email),
  uniqueIndex("crm_customers_source_lead_idx").on(table.sourceLeadId),
  index("crm_customers_status_idx").on(table.status, table.name),
]);

export const businessAuditEvents = sqliteTable("crm_business_audit_events", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  actorEmail: text("actor_email").notNull(),
  action: text("action").notNull(),
  entityType: text("entity_type").notNull(),
  entityId: text("entity_id").notNull(),
  detail: text("detail").notNull(),
  createdAt: text("created_at").notNull(),
}, (table) => [
  index("crm_business_audit_entity_idx").on(table.entityType, table.entityId, table.createdAt),
]);

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
  customerId: text("customer_id").references(() => customers.id, { onDelete: "set null" }),
  contractId: text("contract_id"),
  title: text("title").notNull(),
  status: text("status", { enum: ["planning", "construction", "handover", "care"] }).notNull(),
  phase: text("phase").notNull(),
  progress: integer("progress").notNull(),
  targetCompletion: text("target_completion").notNull(),
  handoverDate: text("handover_date"),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
});

export const contracts = sqliteTable("crm_contracts", {
  id: text("id").primaryKey(),
  contractNumber: text("contract_number").notNull().unique(),
  customerId: text("customer_id").notNull().references(() => customers.id, { onDelete: "restrict" }),
  leadId: integer("lead_id").references(() => leads.id, { onDelete: "set null" }),
  projectId: text("project_id").references(() => projects.id, { onDelete: "set null" }),
  title: text("title").notNull(),
  contractType: text("contract_type", { enum: ["construction", "design", "consulting", "other"] }).notNull(),
  netAmount: integer("net_amount").notNull(),
  vatRate: integer("vat_rate").notNull(),
  grossAmount: integer("gross_amount").notNull(),
  currency: text("currency").notNull(),
  status: text("status", { enum: ["draft", "review", "approved", "signed", "cancelled"] }).notNull(),
  effectiveDate: text("effective_date").notNull(),
  signedAt: text("signed_at"),
  sourceUrl: text("source_url"),
  createdByEmail: text("created_by_email").notNull(),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
}, (table) => [
  index("crm_contracts_customer_idx").on(table.customerId, table.status),
  index("crm_contracts_project_idx").on(table.projectId),
]);

export const financeInvoiceImports = sqliteTable("finance_invoice_imports", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  workspaceId: text("workspace_id").notNull(),
  sourceSystem: text("source_system").notNull(),
  externalId: text("external_id").notNull(),
  sourceUrl: text("source_url").notNull(),
  sourceFileName: text("source_file_name").notNull(),
  sourceSha256: text("source_sha256").notNull(),
  invoiceNumber: text("invoice_number").notNull(),
  invoiceType: text("invoice_type", {
    enum: ["invoice", "storno"],
  }).notNull(),
  sellerName: text("seller_name").notNull(),
  buyerName: text("buyer_name").notNull(),
  issueDate: text("issue_date").notNull(),
  fulfillmentDate: text("fulfillment_date").notNull(),
  dueDate: text("due_date").notNull(),
  paymentMethod: text("payment_method").notNull(),
  currency: text("currency").notNull(),
  netAmount: integer("net_amount").notNull(),
  taxAmount: integer("tax_amount").notNull(),
  grossAmount: integer("gross_amount").notNull(),
  description: text("description").notNull(),
  referencedInvoiceNumber: text("referenced_invoice_number"),
  customerImportId: integer("customer_import_id").references(
    () => customerImports.id,
    { onDelete: "set null" },
  ),
  leadId: integer("lead_id").references(() => leads.id, {
    onDelete: "set null",
  }),
  projectId: text("project_id").references(() => projects.id, {
    onDelete: "set null",
  }),
  customerMatchStatus: text("customer_match_status", {
    enum: ["matched", "review", "unmatched"],
  }).notNull(),
  projectMatchStatus: text("project_match_status", {
    enum: ["matched", "review", "unmatched"],
  }).notNull(),
  matchConfidence: integer("match_confidence").notNull(),
  payloadSha256: text("payload_sha256").notNull(),
  metadataJson: text("metadata_json").notNull(),
  importedAt: text("imported_at").notNull(),
}, (table) => [
  uniqueIndex("finance_invoice_imports_source_idx").on(
    table.workspaceId,
    table.sourceSystem,
    table.externalId,
  ),
  uniqueIndex("finance_invoice_imports_number_idx").on(
    table.workspaceId,
    table.sourceSystem,
    table.invoiceNumber,
  ),
  index("finance_invoice_imports_customer_idx").on(
    table.customerImportId,
    table.leadId,
  ),
  index("finance_invoice_imports_project_idx").on(table.projectId),
]);

export const contractPaymentMilestones = sqliteTable("crm_contract_payment_milestones", {
  id: text("id").primaryKey(),
  contractId: text("contract_id").notNull().references(() => contracts.id, { onDelete: "cascade" }),
  sequence: integer("sequence").notNull(),
  name: text("name").notNull(),
  dueDate: text("due_date").notNull(),
  amount: integer("amount").notNull(),
  currency: text("currency").notNull(),
  status: text("status", { enum: ["planned", "invoiced", "paid", "cancelled"] }).notNull(),
  invoiceId: integer("invoice_id").references(() => financeInvoiceImports.id, { onDelete: "set null" }),
  cashflowEntryId: text("cashflow_entry_id").notNull(),
  createdByEmail: text("created_by_email").notNull(),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
}, (table) => [
  uniqueIndex("crm_contract_milestone_sequence_idx").on(table.contractId, table.sequence),
  uniqueIndex("crm_contract_milestone_cashflow_idx").on(table.cashflowEntryId),
  index("crm_contract_milestone_due_idx").on(table.status, table.dueDate),
]);

export const cashflowEntries = sqliteTable("finance_cashflow_entries", {
  id: text("id").primaryKey(),
  sourceType: text("source_type", {
    enum: ["imported_invoice", "manual", "contract_schedule", "bank"],
  }).notNull(),
  sourceId: text("source_id"),
  direction: text("direction", { enum: ["inflow", "outflow"] }).notNull(),
  category: text("category").notNull(),
  counterparty: text("counterparty").notNull(),
  description: text("description").notNull(),
  projectId: text("project_id").references(() => projects.id, { onDelete: "set null" }),
  amount: integer("amount").notNull(),
  currency: text("currency").notNull(),
  status: text("status", { enum: ["planned", "due", "paid", "cancelled"] }).notNull(),
  dueDate: text("due_date").notNull(),
  paidAt: text("paid_at"),
  createdByEmail: text("created_by_email").notNull(),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
}, (table) => [
  uniqueIndex("finance_cashflow_source_idx").on(table.sourceType, table.sourceId),
  index("finance_cashflow_due_idx").on(table.status, table.dueDate),
  index("finance_cashflow_project_idx").on(table.projectId, table.dueDate),
]);

export const sourceRecords = sqliteTable("crm_source_records", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  workspaceId: text("workspace_id").notNull(),
  sourceSystem: text("source_system").notNull(),
  externalId: text("external_id").notNull(),
  sourceKind: text("source_kind", {
    enum: ["drive_file", "drive_folder", "gmail_message", "spreadsheet_row"],
  }).notNull(),
  recordType: text("record_type", {
    enum: [
      "customer_source",
      "lead_source",
      "project",
      "contract",
      "project_document",
      "invoice_source",
      "partner_source",
      "restricted_source",
      "other",
    ],
  }).notNull(),
  title: text("title").notNull(),
  sourceUrl: text("source_url").notNull(),
  mimeType: text("mime_type"),
  byteSize: integer("byte_size"),
  parentExternalId: text("parent_external_id"),
  sourceVersion: text("source_version").notNull(),
  storageMode: text("storage_mode", { enum: ["link"] }).notNull(),
  reviewStatus: text("review_status", {
    enum: ["verified", "review", "excluded"],
  }).notNull(),
  payloadSha256: text("payload_sha256").notNull(),
  metadataJson: text("metadata_json").notNull(),
  firstSeenAt: text("first_seen_at").notNull(),
  lastSeenAt: text("last_seen_at").notNull(),
  updatedAt: text("updated_at").notNull(),
}, (table) => [
  uniqueIndex("crm_source_records_source_idx").on(
    table.workspaceId,
    table.sourceSystem,
    table.externalId,
  ),
  index("crm_source_records_type_idx").on(
    table.workspaceId,
    table.recordType,
    table.reviewStatus,
  ),
  index("crm_source_records_parent_idx").on(
    table.workspaceId,
    table.sourceSystem,
    table.parentExternalId,
  ),
]);

export const businessPartners = sqliteTable("crm_business_partners", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  workspaceId: text("workspace_id").notNull(),
  identityKey: text("identity_key").notNull(),
  partnerType: text("partner_type", {
    enum: ["subcontractor", "supplier", "designer", "architect", "b2b_partner"],
  }).notNull(),
  name: text("name").notNull(),
  email: text("email"),
  phone: text("phone"),
  location: text("location"),
  specialties: text("specialties"),
  recordStatus: text("record_status", {
    enum: ["verified", "prospect", "review", "excluded"],
  }).notNull(),
  matchConfidence: integer("match_confidence").notNull(),
  metadataJson: text("metadata_json").notNull(),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
}, (table) => [
  uniqueIndex("crm_business_partners_identity_idx").on(
    table.workspaceId,
    table.identityKey,
  ),
  index("crm_business_partners_type_idx").on(
    table.workspaceId,
    table.partnerType,
    table.recordStatus,
  ),
]);

export const businessPartnerSources = sqliteTable("crm_business_partner_sources", {
  partnerId: integer("partner_id").notNull().references(
    () => businessPartners.id,
    { onDelete: "cascade" },
  ),
  sourceRecordId: integer("source_record_id").notNull().references(
    () => sourceRecords.id,
    { onDelete: "cascade" },
  ),
  createdAt: text("created_at").notNull(),
}, (table) => [
  primaryKey({ columns: [table.partnerId, table.sourceRecordId] }),
  uniqueIndex("crm_business_partner_sources_record_idx").on(
    table.sourceRecordId,
  ),
]);

export const businessProjects = sqliteTable("crm_business_projects", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  workspaceId: text("workspace_id").notNull(),
  sourceRecordId: integer("source_record_id").notNull().references(
    () => sourceRecords.id,
    { onDelete: "cascade" },
  ),
  externalKey: text("external_key").notNull(),
  title: text("title").notNull(),
  location: text("location"),
  projectType: text("project_type"),
  projectStatus: text("project_status", {
    enum: ["active", "planning", "on_hold", "completed", "archived", "review"],
  }).notNull(),
  customerImportId: integer("customer_import_id").references(
    () => customerImports.id,
    { onDelete: "set null" },
  ),
  customerMatchStatus: text("customer_match_status", {
    enum: ["matched", "review", "unmatched"],
  }).notNull(),
  metadataJson: text("metadata_json").notNull(),
  createdAt: text("created_at").notNull(),
  updatedAt: text("updated_at").notNull(),
}, (table) => [
  uniqueIndex("crm_business_projects_external_idx").on(
    table.workspaceId,
    table.externalKey,
  ),
  uniqueIndex("crm_business_projects_source_idx").on(table.sourceRecordId),
  index("crm_business_projects_status_idx").on(
    table.workspaceId,
    table.projectStatus,
    table.customerMatchStatus,
  ),
]);

export const importReviewItems = sqliteTable("crm_import_review_items", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  workspaceId: text("workspace_id").notNull(),
  sourceRecordId: integer("source_record_id").notNull().references(
    () => sourceRecords.id,
    { onDelete: "cascade" },
  ),
  entityType: text("entity_type").notNull(),
  reasonCode: text("reason_code").notNull(),
  summary: text("summary").notNull(),
  status: text("status", { enum: ["open", "resolved", "dismissed"] }).notNull(),
  createdAt: text("created_at").notNull(),
  resolvedAt: text("resolved_at"),
}, (table) => [
  uniqueIndex("crm_import_review_items_source_reason_idx").on(
    table.sourceRecordId,
    table.entityType,
    table.reasonCode,
  ),
  index("crm_import_review_items_status_idx").on(
    table.workspaceId,
    table.status,
    table.entityType,
  ),
]);

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
