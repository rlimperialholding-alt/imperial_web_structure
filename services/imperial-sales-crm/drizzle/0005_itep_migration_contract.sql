CREATE TABLE `crm_migration_batches` (
  `idempotency_key` text PRIMARY KEY NOT NULL,
  `workspace_id` text NOT NULL,
  `source_system` text NOT NULL,
  `payload_sha256` text NOT NULL,
  `requested_count` integer NOT NULL,
  `stored_count` integer NOT NULL,
  `status` text NOT NULL CHECK (`status` IN ('processing', 'completed')),
  `created_at` text NOT NULL,
  `completed_at` text
);
--> statement-breakpoint
CREATE INDEX `crm_migration_batches_workspace_idx`
  ON `crm_migration_batches` (`workspace_id`, `created_at`);
--> statement-breakpoint
CREATE TABLE `crm_migration_documents` (
  `id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  `batch_id` text NOT NULL,
  `workspace_id` text NOT NULL,
  `source_system` text NOT NULL,
  `external_id` text NOT NULL,
  `title` text NOT NULL,
  `file_name` text NOT NULL,
  `content_type` text NOT NULL,
  `size` integer NOT NULL,
  `sha256` text NOT NULL,
  `object_key` text NOT NULL,
  `metadata_json` text NOT NULL,
  `migrated_at` text NOT NULL,
  FOREIGN KEY (`batch_id`) REFERENCES `crm_migration_batches`(`idempotency_key`)
);
--> statement-breakpoint
CREATE UNIQUE INDEX `crm_migration_documents_object_key_idx`
  ON `crm_migration_documents` (`object_key`);
--> statement-breakpoint
CREATE UNIQUE INDEX `crm_migration_documents_source_idx`
  ON `crm_migration_documents` (`workspace_id`, `source_system`, `external_id`);
--> statement-breakpoint
CREATE INDEX `crm_migration_documents_activity_idx`
  ON `crm_migration_documents` (`workspace_id`, `id`);
--> statement-breakpoint
CREATE INDEX `crm_migration_documents_batch_idx`
  ON `crm_migration_documents` (`batch_id`);
