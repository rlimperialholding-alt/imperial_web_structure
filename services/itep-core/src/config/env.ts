import { z } from "zod";

const envSchema = z.object({
  NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
  PORT: z.coerce.number().int().positive().max(65535).default(3000),
  HOST: z.string().min(1).default("0.0.0.0"),
  DATABASE_URL: z.string().min(1),
  DEFAULT_ORGANIZATION_ID: z.string().min(1).default("imperial-holding"),
  DEFAULT_ASSIGNEE_ID: z.string().min(1).default("human-anne"),
  DEFAULT_ESCALATION_PERSON_ID: z.string().min(1).default("director"),
  DEFAULT_CONTACT_EMAIL: z.string().email(),
  IDENTITY_SHARED_SECRET: z.string().min(32),
  AUTH_TOKEN_PEPPER: z.string().min(32).optional(),
  AUTH_DATA_ENCRYPTION_KEY: z.string().min(32).optional(),
  AUTH_BOOTSTRAP_TOKEN: z.string().min(32).optional(),
  AUTH_SESSION_TTL_HOURS: z.coerce.number().int().positive().max(168).default(12),
  AUTH_CHALLENGE_TTL_MINUTES: z.coerce.number().int().positive().max(30).default(5),
  AUTH_INVITATION_TTL_HOURS: z.coerce.number().int().positive().max(168).default(48),
  AUTH_COOKIE_SECURE: z.string().transform((value) => value !== "false").default("true"),
  AUTH_MAX_FAILED_LOGINS: z.coerce.number().int().min(3).max(20).default(5),
  AUTH_LOCKOUT_MINUTES: z.coerce.number().int().positive().max(1440).default(15),
  WEBHOOK_SHARED_SECRET: z.string().min(32).optional(),
  API_RATE_LIMIT_MAX: z.coerce.number().int().positive().default(300),
  API_RATE_LIMIT_WINDOW_MS: z.coerce.number().int().positive().default(60_000),
  ENFORCEMENT_INTERVAL_MS: z.coerce.number().int().positive().default(60_000),
  OUTBOX_INTERVAL_MS: z.coerce.number().int().positive().default(15_000),
  CONNECTOR_SYNC_INTERVAL_MS: z.coerce.number().int().positive().default(60_000),
  INTEGRATION_RETRY_INTERVAL_MS: z.coerce.number().int().positive().default(30_000),
  INTEGRATION_RETRY_BATCH_SIZE: z.coerce.number().int().positive().max(500).default(50),
  BILLINGO_API_BASE_URL: z.string().url().default("https://api.billingo.hu"),
  META_GRAPH_API_BASE_URL: z.string().url().default("https://graph.facebook.com"),
  META_GRAPH_API_VERSION: z.string().regex(/^v\d+\.\d+$/).default("v25.0"),
  WHATSAPP_APP_SECRET: z.string().min(32).optional(),
  WHATSAPP_VERIFY_TOKEN: z.string().min(16).optional(),
  WHATSAPP_GRAPH_API_BASE_URL: z.string().url().default("https://graph.facebook.com"),
  WHATSAPP_GRAPH_API_VERSION: z.string().regex(/^v\d+\.\d+$/).default("v25.0"),
  WHATSAPP_DATA_ENCRYPTION_KEY: z.string().min(32).optional(),
  GOOGLE_ADS_API_BASE_URL: z.string().url().default("https://googleads.googleapis.com"),
  GOOGLE_ADS_API_VERSION: z.string().regex(/^v\d+$/).default("v25"),
  GOOGLE_OAUTH_TOKEN_URL: z.string().url().default("https://oauth2.googleapis.com/token"),
  BANK_API_BASE_URL: z.string().url().default("https://bank-api.invalid"),
  CRM_API_BASE_URL: z.string().url().default("https://crm-api.invalid"),
  CRM_ACTIVITIES_PATH: z.string().min(1).default("/api/v1/activities"),
  CRM_AUTH_HEADER: z.string().min(1).default("Authorization"),
  CRM_AUTH_SCHEME: z.string().default("Bearer"),
  CRM_WORKSPACE_QUERY_PARAMETER: z.string().min(1).default("workspace"),
});

export type AppConfig = z.infer<typeof envSchema>;

export function loadConfig(
  env: NodeJS.ProcessEnv = process.env,
): AppConfig {
  const result = envSchema.safeParse(env);
  if (!result.success) {
    const details = result.error.issues
      .map((issue) => `${issue.path.join(".")}: ${issue.message}`)
      .join("; ");
    throw new Error(`Invalid application configuration: ${details}`);
  }
  return result.data;
}
