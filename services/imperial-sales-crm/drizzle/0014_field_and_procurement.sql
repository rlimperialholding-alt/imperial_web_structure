CREATE TABLE `project_site_logs` (
  `id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  `project_id` text NOT NULL,
  `log_date` text NOT NULL,
  `weather` text NOT NULL,
  `workforce` integer NOT NULL,
  `summary` text NOT NULL,
  `blockers` text NOT NULL,
  `created_by_email` text NOT NULL,
  `created_at` text NOT NULL,
  FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `project_site_logs_date_idx` ON `project_site_logs` (`project_id`, `log_date`);
--> statement-breakpoint
CREATE TABLE `procurement_requests` (
  `id` text PRIMARY KEY NOT NULL,
  `project_id` text NOT NULL,
  `title` text NOT NULL,
  `category` text NOT NULL,
  `quantity` integer NOT NULL,
  `unit` text NOT NULL,
  `required_by` text NOT NULL,
  `budget_amount` integer NOT NULL,
  `currency` text NOT NULL,
  `supplier_partner_id` integer,
  `status` text NOT NULL,
  `created_by_email` text NOT NULL,
  `created_at` text NOT NULL,
  `updated_at` text NOT NULL,
  FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON UPDATE no action ON DELETE cascade,
  FOREIGN KEY (`supplier_partner_id`) REFERENCES `crm_business_partners` (`id`) ON UPDATE no action ON DELETE set null
);
--> statement-breakpoint
CREATE INDEX `procurement_requests_project_idx` ON `procurement_requests` (`project_id`, `status`, `required_by`);
--> statement-breakpoint
CREATE INDEX `procurement_requests_supplier_idx` ON `procurement_requests` (`supplier_partner_id`);
