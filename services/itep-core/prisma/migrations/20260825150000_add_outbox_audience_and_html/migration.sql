ALTER TABLE "NotificationOutbox"
    ADD COLUMN "audience" TEXT,
    ADD COLUMN "htmlBody" TEXT;

UPDATE "NotificationOutbox"
SET "audience" = 'external'
WHERE "audience" IS NULL;

ALTER TABLE "NotificationOutbox"
    ALTER COLUMN "audience" SET NOT NULL,
    ALTER COLUMN "audience" SET DEFAULT 'external';

ALTER TABLE "NotificationOutbox"
    ADD CONSTRAINT "NotificationOutbox_audience_check"
    CHECK ("audience" IN ('external', 'internal'));
