CREATE TABLE `project_invitations` (
  `id` text PRIMARY KEY NOT NULL,
  `project_id` text NOT NULL,
  `email` text NOT NULL,
  `display_name` text NOT NULL,
  `role` text NOT NULL,
  `token_hash` text NOT NULL UNIQUE,
  `status` text NOT NULL,
  `invited_by_email` text NOT NULL,
  `expires_at` text NOT NULL,
  `accepted_at` text,
  `created_at` text NOT NULL,
  `updated_at` text NOT NULL,
  FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `project_invitations_project_idx` ON `project_invitations` (`project_id`);
--> statement-breakpoint
CREATE INDEX `project_invitations_email_idx` ON `project_invitations` (`email`);
