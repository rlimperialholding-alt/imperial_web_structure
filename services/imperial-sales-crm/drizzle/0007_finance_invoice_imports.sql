CREATE TABLE `finance_invoice_imports` (
  `id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  `workspace_id` text NOT NULL,
  `source_system` text NOT NULL,
  `external_id` text NOT NULL,
  `source_url` text NOT NULL,
  `source_file_name` text NOT NULL,
  `source_sha256` text NOT NULL,
  `invoice_number` text NOT NULL,
  `invoice_type` text NOT NULL CHECK (`invoice_type` IN ('invoice', 'storno')),
  `seller_name` text NOT NULL,
  `buyer_name` text NOT NULL,
  `issue_date` text NOT NULL,
  `fulfillment_date` text NOT NULL,
  `due_date` text NOT NULL,
  `payment_method` text NOT NULL,
  `currency` text NOT NULL,
  `net_amount` integer NOT NULL,
  `tax_amount` integer NOT NULL,
  `gross_amount` integer NOT NULL,
  `description` text NOT NULL,
  `referenced_invoice_number` text,
  `customer_import_id` integer,
  `lead_id` integer,
  `project_id` text,
  `customer_match_status` text NOT NULL CHECK (`customer_match_status` IN ('matched', 'review', 'unmatched')),
  `project_match_status` text NOT NULL CHECK (`project_match_status` IN ('matched', 'review', 'unmatched')),
  `match_confidence` integer NOT NULL CHECK (`match_confidence` BETWEEN 0 AND 100),
  `payload_sha256` text NOT NULL,
  `metadata_json` text NOT NULL,
  `imported_at` text NOT NULL,
  FOREIGN KEY (`customer_import_id`) REFERENCES `crm_customer_imports`(`id`) ON UPDATE no action ON DELETE set null,
  FOREIGN KEY (`lead_id`) REFERENCES `leads`(`id`) ON UPDATE no action ON DELETE set null,
  FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE set null
);
--> statement-breakpoint
CREATE UNIQUE INDEX `finance_invoice_imports_source_idx`
  ON `finance_invoice_imports` (`workspace_id`, `source_system`, `external_id`);
--> statement-breakpoint
CREATE UNIQUE INDEX `finance_invoice_imports_number_idx`
  ON `finance_invoice_imports` (`workspace_id`, `source_system`, `invoice_number`);
--> statement-breakpoint
CREATE INDEX `finance_invoice_imports_customer_idx`
  ON `finance_invoice_imports` (`customer_import_id`, `lead_id`);
--> statement-breakpoint
CREATE INDEX `finance_invoice_imports_project_idx`
  ON `finance_invoice_imports` (`project_id`);
