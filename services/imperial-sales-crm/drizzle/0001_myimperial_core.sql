CREATE TABLE `projects` (
  `id` text PRIMARY KEY NOT NULL,
  `portal_code` text NOT NULL UNIQUE,
  `customer_name` text NOT NULL,
  `customer_email` text NOT NULL,
  `title` text NOT NULL,
  `status` text NOT NULL,
  `phase` text NOT NULL,
  `progress` integer NOT NULL,
  `target_completion` text NOT NULL,
  `handover_date` text,
  `created_at` text NOT NULL,
  `updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `project_members` (
  `project_id` text NOT NULL,
  `email` text NOT NULL,
  `role` text NOT NULL,
  `created_at` text NOT NULL,
  PRIMARY KEY(`project_id`, `email`),
  FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `project_members_email_idx` ON `project_members` (`email`);
--> statement-breakpoint
CREATE TABLE `project_tasks` (
  `id` text PRIMARY KEY NOT NULL,
  `project_id` text NOT NULL,
  `source` text NOT NULL,
  `title` text NOT NULL,
  `due` text NOT NULL,
  `status` text NOT NULL,
  `severity` text NOT NULL,
  `action` text NOT NULL,
  `created_at` text NOT NULL,
  `updated_at` text NOT NULL,
  FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `project_tasks_project_idx` ON `project_tasks` (`project_id`);
--> statement-breakpoint
CREATE TABLE `project_changes` (
  `id` text PRIMARY KEY NOT NULL,
  `project_id` text NOT NULL,
  `title` text NOT NULL,
  `origin` text NOT NULL,
  `scope` text NOT NULL,
  `customer_price_impact` text NOT NULL,
  `schedule_impact` text NOT NULL,
  `internal_control_status` text NOT NULL,
  `status` text NOT NULL,
  `evidence` text NOT NULL,
  `created_at` text NOT NULL,
  `updated_at` text NOT NULL,
  `customer_decision_at` text,
  `decided_by_email` text,
  FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `project_changes_project_idx` ON `project_changes` (`project_id`);
--> statement-breakpoint
CREATE TABLE `project_decisions` (
  `id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  `project_id` text NOT NULL,
  `title` text NOT NULL,
  `area` text NOT NULL,
  `due` text NOT NULL,
  `impact` text NOT NULL,
  `status` text NOT NULL,
  `response` text NOT NULL,
  `decided_at` text,
  `decided_by_email` text,
  `created_at` text NOT NULL,
  `updated_at` text NOT NULL,
  FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `project_decisions_project_idx` ON `project_decisions` (`project_id`);
--> statement-breakpoint
CREATE TABLE `project_messages` (
  `id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  `project_id` text NOT NULL,
  `author_email` text NOT NULL,
  `topic` text NOT NULL,
  `body` text NOT NULL,
  `created_at` text NOT NULL,
  FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `project_messages_project_idx` ON `project_messages` (`project_id`);
--> statement-breakpoint
CREATE TABLE `warranty_cases` (
  `id` text PRIMARY KEY NOT NULL,
  `project_id` text NOT NULL,
  `title` text NOT NULL,
  `status` text NOT NULL,
  `severity` text NOT NULL,
  `responsible_role` text NOT NULL,
  `next_deadline` text NOT NULL,
  `evidence` text NOT NULL,
  `customer_confirmed` integer NOT NULL,
  `created_at` text NOT NULL,
  `updated_at` text NOT NULL,
  FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `warranty_cases_project_idx` ON `warranty_cases` (`project_id`);
--> statement-breakpoint
CREATE TABLE `project_events` (
  `id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  `project_id` text NOT NULL,
  `actor_email` text NOT NULL,
  `action` text NOT NULL,
  `entity_type` text NOT NULL,
  `entity_id` text NOT NULL,
  `detail` text NOT NULL,
  `created_at` text NOT NULL,
  FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `project_events_project_idx` ON `project_events` (`project_id`);
