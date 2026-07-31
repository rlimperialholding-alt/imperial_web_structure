CREATE TABLE `crm_customers` (
  `id` text PRIMARY KEY NOT NULL,
  `customer_type` text NOT NULL,
  `name` text NOT NULL,
  `email` text NOT NULL,
  `phone` text NOT NULL,
  `billing_address` text NOT NULL,
  `tax_number` text,
  `company_registration_number` text,
  `source_lead_id` integer,
  `status` text NOT NULL,
  `created_by_email` text NOT NULL,
  `created_at` text NOT NULL,
  `updated_at` text NOT NULL,
  FOREIGN KEY (`source_lead_id`) REFERENCES `leads` (`id`) ON UPDATE no action ON DELETE set null
);
--> statement-breakpoint
CREATE UNIQUE INDEX `crm_customers_email_idx` ON `crm_customers` (`email`);
--> statement-breakpoint
CREATE UNIQUE INDEX `crm_customers_source_lead_idx` ON `crm_customers` (`source_lead_id`);
--> statement-breakpoint
CREATE INDEX `crm_customers_status_idx` ON `crm_customers` (`status`, `name`);
--> statement-breakpoint

ALTER TABLE `projects` ADD `customer_id` text REFERENCES `crm_customers` (`id`) ON DELETE set null;
--> statement-breakpoint
ALTER TABLE `projects` ADD `contract_id` text;
--> statement-breakpoint

CREATE TABLE `crm_contracts` (
  `id` text PRIMARY KEY NOT NULL,
  `contract_number` text NOT NULL UNIQUE,
  `customer_id` text NOT NULL,
  `lead_id` integer,
  `project_id` text,
  `title` text NOT NULL,
  `contract_type` text NOT NULL,
  `net_amount` integer NOT NULL,
  `vat_rate` integer NOT NULL,
  `gross_amount` integer NOT NULL,
  `currency` text NOT NULL,
  `status` text NOT NULL,
  `effective_date` text NOT NULL,
  `signed_at` text,
  `source_url` text,
  `created_by_email` text NOT NULL,
  `created_at` text NOT NULL,
  `updated_at` text NOT NULL,
  FOREIGN KEY (`customer_id`) REFERENCES `crm_customers` (`id`) ON UPDATE no action ON DELETE restrict,
  FOREIGN KEY (`lead_id`) REFERENCES `leads` (`id`) ON UPDATE no action ON DELETE set null,
  FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON UPDATE no action ON DELETE set null
);
--> statement-breakpoint
CREATE INDEX `crm_contracts_customer_idx` ON `crm_contracts` (`customer_id`, `status`);
--> statement-breakpoint
CREATE INDEX `crm_contracts_project_idx` ON `crm_contracts` (`project_id`);
--> statement-breakpoint

CREATE TABLE `crm_business_audit_events` (
  `id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  `actor_email` text NOT NULL,
  `action` text NOT NULL,
  `entity_type` text NOT NULL,
  `entity_id` text NOT NULL,
  `detail` text NOT NULL,
  `created_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `crm_business_audit_entity_idx`
  ON `crm_business_audit_events` (`entity_type`, `entity_id`, `created_at`);
