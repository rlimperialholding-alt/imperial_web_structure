CREATE TABLE `crm_source_records` (
  `id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  `workspace_id` text NOT NULL,
  `source_system` text NOT NULL,
  `external_id` text NOT NULL,
  `source_kind` text NOT NULL,
  `record_type` text NOT NULL,
  `title` text NOT NULL,
  `source_url` text NOT NULL,
  `mime_type` text,
  `byte_size` integer,
  `parent_external_id` text,
  `source_version` text NOT NULL,
  `storage_mode` text DEFAULT 'link' NOT NULL,
  `review_status` text NOT NULL,
  `payload_sha256` text NOT NULL,
  `metadata_json` text NOT NULL,
  `first_seen_at` text NOT NULL,
  `last_seen_at` text NOT NULL,
  `updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `crm_source_records_source_idx`
  ON `crm_source_records` (`workspace_id`, `source_system`, `external_id`);
--> statement-breakpoint
CREATE INDEX `crm_source_records_type_idx`
  ON `crm_source_records` (`workspace_id`, `record_type`, `review_status`);
--> statement-breakpoint
CREATE INDEX `crm_source_records_parent_idx`
  ON `crm_source_records` (`workspace_id`, `source_system`, `parent_external_id`);
--> statement-breakpoint

CREATE TABLE `crm_business_partners` (
  `id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  `workspace_id` text NOT NULL,
  `identity_key` text NOT NULL,
  `partner_type` text NOT NULL,
  `name` text NOT NULL,
  `email` text,
  `phone` text,
  `location` text,
  `specialties` text,
  `record_status` text NOT NULL,
  `match_confidence` integer NOT NULL,
  `metadata_json` text NOT NULL,
  `created_at` text NOT NULL,
  `updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `crm_business_partners_identity_idx`
  ON `crm_business_partners` (`workspace_id`, `identity_key`);
--> statement-breakpoint
CREATE INDEX `crm_business_partners_type_idx`
  ON `crm_business_partners` (`workspace_id`, `partner_type`, `record_status`);
--> statement-breakpoint

CREATE TABLE `crm_business_partner_sources` (
  `partner_id` integer NOT NULL,
  `source_record_id` integer NOT NULL,
  `created_at` text NOT NULL,
  PRIMARY KEY (`partner_id`, `source_record_id`),
  FOREIGN KEY (`partner_id`) REFERENCES `crm_business_partners` (`id`) ON UPDATE no action ON DELETE cascade,
  FOREIGN KEY (`source_record_id`) REFERENCES `crm_source_records` (`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `crm_business_partner_sources_record_idx`
  ON `crm_business_partner_sources` (`source_record_id`);
--> statement-breakpoint

CREATE TABLE `crm_business_projects` (
  `id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  `workspace_id` text NOT NULL,
  `source_record_id` integer NOT NULL,
  `external_key` text NOT NULL,
  `title` text NOT NULL,
  `location` text,
  `project_type` text,
  `project_status` text NOT NULL,
  `customer_import_id` integer,
  `customer_match_status` text NOT NULL,
  `metadata_json` text NOT NULL,
  `created_at` text NOT NULL,
  `updated_at` text NOT NULL,
  FOREIGN KEY (`source_record_id`) REFERENCES `crm_source_records` (`id`) ON UPDATE no action ON DELETE cascade,
  FOREIGN KEY (`customer_import_id`) REFERENCES `crm_customer_imports` (`id`) ON UPDATE no action ON DELETE set null
);
--> statement-breakpoint
CREATE UNIQUE INDEX `crm_business_projects_external_idx`
  ON `crm_business_projects` (`workspace_id`, `external_key`);
--> statement-breakpoint
CREATE UNIQUE INDEX `crm_business_projects_source_idx`
  ON `crm_business_projects` (`source_record_id`);
--> statement-breakpoint
CREATE INDEX `crm_business_projects_status_idx`
  ON `crm_business_projects` (`workspace_id`, `project_status`, `customer_match_status`);
--> statement-breakpoint

CREATE TABLE `crm_import_review_items` (
  `id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  `workspace_id` text NOT NULL,
  `source_record_id` integer NOT NULL,
  `entity_type` text NOT NULL,
  `reason_code` text NOT NULL,
  `summary` text NOT NULL,
  `status` text DEFAULT 'open' NOT NULL,
  `created_at` text NOT NULL,
  `resolved_at` text,
  FOREIGN KEY (`source_record_id`) REFERENCES `crm_source_records` (`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `crm_import_review_items_source_reason_idx`
  ON `crm_import_review_items` (`source_record_id`, `entity_type`, `reason_code`);
--> statement-breakpoint
CREATE INDEX `crm_import_review_items_status_idx`
  ON `crm_import_review_items` (`workspace_id`, `status`, `entity_type`);
