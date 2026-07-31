CREATE TABLE `crm_contract_payment_milestones` (
  `id` text PRIMARY KEY NOT NULL,
  `contract_id` text NOT NULL,
  `sequence` integer NOT NULL,
  `name` text NOT NULL,
  `due_date` text NOT NULL,
  `amount` integer NOT NULL,
  `currency` text NOT NULL,
  `status` text NOT NULL,
  `invoice_id` integer,
  `cashflow_entry_id` text NOT NULL,
  `created_by_email` text NOT NULL,
  `created_at` text NOT NULL,
  `updated_at` text NOT NULL,
  FOREIGN KEY (`contract_id`) REFERENCES `crm_contracts` (`id`) ON UPDATE no action ON DELETE cascade,
  FOREIGN KEY (`invoice_id`) REFERENCES `finance_invoice_imports` (`id`) ON UPDATE no action ON DELETE set null
);
--> statement-breakpoint
CREATE UNIQUE INDEX `crm_contract_milestone_sequence_idx`
  ON `crm_contract_payment_milestones` (`contract_id`, `sequence`);
--> statement-breakpoint
CREATE UNIQUE INDEX `crm_contract_milestone_cashflow_idx`
  ON `crm_contract_payment_milestones` (`cashflow_entry_id`);
--> statement-breakpoint
CREATE INDEX `crm_contract_milestone_due_idx`
  ON `crm_contract_payment_milestones` (`status`, `due_date`);
