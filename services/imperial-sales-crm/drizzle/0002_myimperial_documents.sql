CREATE TABLE `project_documents` (
  `id` text PRIMARY KEY NOT NULL,
  `project_id` text NOT NULL,
  `name` text NOT NULL,
  `group_name` text NOT NULL,
  `status` text NOT NULL,
  `current_version` integer NOT NULL,
  `created_at` text NOT NULL,
  `updated_at` text NOT NULL,
  FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `project_documents_project_idx` ON `project_documents` (`project_id`);
--> statement-breakpoint
CREATE TABLE `project_document_versions` (
  `id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  `document_id` text NOT NULL,
  `version` integer NOT NULL,
  `object_key` text NOT NULL UNIQUE,
  `file_name` text NOT NULL,
  `content_type` text NOT NULL,
  `size` integer NOT NULL,
  `sha256` text NOT NULL,
  `uploaded_by_email` text NOT NULL,
  `uploaded_at` text NOT NULL,
  FOREIGN KEY (`document_id`) REFERENCES `project_documents`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `project_document_versions_document_version_idx` ON `project_document_versions` (`document_id`, `version`);
