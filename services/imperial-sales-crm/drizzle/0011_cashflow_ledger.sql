CREATE TABLE `finance_cashflow_entries` (
  `id` text PRIMARY KEY NOT NULL,
  `source_type` text NOT NULL,
  `source_id` text,
  `direction` text NOT NULL,
  `category` text NOT NULL,
  `counterparty` text NOT NULL,
  `description` text NOT NULL,
  `project_id` text,
  `amount` integer NOT NULL,
  `currency` text NOT NULL,
  `status` text NOT NULL,
  `due_date` text NOT NULL,
  `paid_at` text,
  `created_by_email` text NOT NULL,
  `created_at` text NOT NULL,
  `updated_at` text NOT NULL,
  FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON UPDATE no action ON DELETE set null
);
--> statement-breakpoint
CREATE UNIQUE INDEX `finance_cashflow_source_idx`
  ON `finance_cashflow_entries` (`source_type`, `source_id`);
--> statement-breakpoint
CREATE INDEX `finance_cashflow_due_idx`
  ON `finance_cashflow_entries` (`status`, `due_date`);
--> statement-breakpoint
CREATE INDEX `finance_cashflow_project_idx`
  ON `finance_cashflow_entries` (`project_id`, `due_date`);
--> statement-breakpoint

INSERT OR IGNORE INTO `finance_cashflow_entries` (
  `id`, `source_type`, `source_id`, `direction`, `category`, `counterparty`,
  `description`, `project_id`, `amount`, `currency`, `status`, `due_date`,
  `paid_at`, `created_by_email`, `created_at`, `updated_at`
)
SELECT
  'CF-INV-' || fi.`id`,
  'imported_invoice',
  CAST(fi.`id` AS text),
  'outflow',
  'Szállítói számla',
  fi.`seller_name`,
  fi.`invoice_number` || ' · ' || fi.`description`,
  fi.`project_id`,
  fi.`gross_amount`,
  fi.`currency`,
  'due',
  fi.`due_date`,
  NULL,
  'migration@imperial.system',
  fi.`imported_at`,
  fi.`imported_at`
FROM `finance_invoice_imports` fi
ORDER BY fi.`id`;
