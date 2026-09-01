CREATE TABLE `crm_customer_imports` (
  `id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  `workspace_id` text NOT NULL,
  `source_system` text NOT NULL,
  `external_id` text NOT NULL,
  `source_kind` text NOT NULL CHECK (`source_kind` IN ('contract_customer', 'web_form_lead')),
  `lead_id` integer NOT NULL,
  `source_url` text NOT NULL,
  `source_date` text NOT NULL,
  `payload_sha256` text NOT NULL,
  `metadata_json` text NOT NULL,
  `imported_at` text NOT NULL,
  FOREIGN KEY (`lead_id`) REFERENCES `leads`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `crm_customer_imports_source_idx`
  ON `crm_customer_imports` (`workspace_id`, `source_system`, `external_id`);
--> statement-breakpoint
CREATE INDEX `crm_customer_imports_workspace_idx`
  ON `crm_customer_imports` (`workspace_id`, `id`);
--> statement-breakpoint
CREATE INDEX `crm_customer_imports_lead_idx`
  ON `crm_customer_imports` (`lead_id`);
