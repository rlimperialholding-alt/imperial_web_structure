CREATE TABLE `notification_preferences` (
  `project_id` text NOT NULL,
  `member_email` text NOT NULL,
  `task_notifications` integer NOT NULL,
  `decision_notifications` integer NOT NULL,
  `change_notifications` integer NOT NULL,
  `document_notifications` integer NOT NULL,
  `message_notifications` integer NOT NULL,
  `care_notifications` integer NOT NULL,
  `digest_frequency` text NOT NULL,
  `updated_at` text NOT NULL,
  PRIMARY KEY(`project_id`, `member_email`),
  FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `notification_preferences_member_idx` ON `notification_preferences` (`member_email`);
--> statement-breakpoint
CREATE TABLE `email_notifications` (
  `id` text PRIMARY KEY NOT NULL,
  `project_id` text NOT NULL,
  `recipient_email` text NOT NULL,
  `recipient_name` text NOT NULL,
  `template_key` text NOT NULL,
  `subject` text NOT NULL,
  `html_body` text,
  `text_body` text,
  `status` text NOT NULL,
  `approval_required` integer NOT NULL,
  `approved_by_email` text,
  `approved_at` text,
  `provider_message_id` text,
  `idempotency_key` text NOT NULL UNIQUE,
  `attempt_count` integer NOT NULL,
  `last_error` text,
  `related_entity_type` text NOT NULL,
  `related_entity_id` text NOT NULL,
  `created_at` text NOT NULL,
  `updated_at` text NOT NULL,
  `sent_at` text,
  FOREIGN KEY (`project_id`) REFERENCES `projects`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `email_notifications_project_idx` ON `email_notifications` (`project_id`);
--> statement-breakpoint
CREATE INDEX `email_notifications_recipient_idx` ON `email_notifications` (`recipient_email`);
--> statement-breakpoint
CREATE INDEX `email_notifications_status_idx` ON `email_notifications` (`status`);
