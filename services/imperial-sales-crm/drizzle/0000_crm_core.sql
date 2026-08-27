CREATE TABLE `users` (
  `email` text PRIMARY KEY NOT NULL,
  `display_name` text NOT NULL,
  `role` text NOT NULL,
  `created_at` text NOT NULL,
  `last_seen_at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `leads` (
  `id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  `name` text NOT NULL, `title` text NOT NULL, `brand` text NOT NULL, `brand_code` text NOT NULL,
  `location` text NOT NULL, `email` text NOT NULL, `phone` text NOT NULL, `source` text NOT NULL,
  `owner` text NOT NULL, `owner_initials` text NOT NULL, `stage` text NOT NULL, `value` integer NOT NULL,
  `probability` integer NOT NULL, `score` integer NOT NULL, `quality` integer NOT NULL, `temperature` text NOT NULL,
  `health` text NOT NULL, `next_action` text NOT NULL, `next_date` text NOT NULL, `project_type` text NOT NULL,
  `technology` text NOT NULL, `plot` integer NOT NULL, `financing` integer NOT NULL, `notes` text NOT NULL,
  `created_at` text NOT NULL, `updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `tasks` (
  `id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  `title` text NOT NULL,
  `lead_id` integer,
  `lead_name` text NOT NULL,
  `type` text NOT NULL,
  `due` text NOT NULL,
  `priority` text NOT NULL,
  `done` integer NOT NULL,
  `ai` integer NOT NULL,
  `owner_email` text NOT NULL,
  `created_at` text NOT NULL,
  `updated_at` text NOT NULL,
  FOREIGN KEY (`lead_id`) REFERENCES `leads`(`id`) ON UPDATE no action ON DELETE set null
);
--> statement-breakpoint
CREATE TABLE `activities` (
  `id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  `actor_email` text NOT NULL,
  `action` text NOT NULL,
  `entity_type` text NOT NULL,
  `entity_id` integer NOT NULL,
  `detail` text NOT NULL,
  `created_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `leads_stage_idx` ON `leads` (`stage`);
--> statement-breakpoint
CREATE INDEX `tasks_done_idx` ON `tasks` (`done`);
