ALTER TABLE `project_tasks` ADD `assigned_to_email` text;
--> statement-breakpoint
ALTER TABLE `project_tasks` ADD `created_by_email` text;
--> statement-breakpoint
CREATE TABLE `project_comments` (
  `id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  `project_id` text NOT NULL,
  `entity_type` text NOT NULL,
  `entity_id` text NOT NULL,
  `author_email` text NOT NULL,
  `body` text NOT NULL,
  `mentions_json` text NOT NULL,
  `created_at` text NOT NULL,
  FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `project_comments_entity_idx`
  ON `project_comments` (`project_id`, `entity_type`, `entity_id`);
--> statement-breakpoint
CREATE INDEX `project_comments_created_idx`
  ON `project_comments` (`project_id`, `created_at`);
