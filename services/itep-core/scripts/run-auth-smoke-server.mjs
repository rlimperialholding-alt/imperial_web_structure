Object.assign(process.env, {
  NODE_ENV: "test",
  PORT: "3311",
  HOST: "127.0.0.1",
  DATABASE_URL:
    process.env.DATABASE_URL ??
    "postgresql://itep:itep-test-password@127.0.0.1:55432/itep_test?schema=public",
  DEFAULT_ORGANIZATION_ID: "imperial-holding",
  DEFAULT_ASSIGNEE_ID: "human-anne",
  DEFAULT_ESCALATION_PERSON_ID: "director",
  DEFAULT_CONTACT_EMAIL: "test@imperial.local",
  IDENTITY_SHARED_SECRET: "smoke-identity-shared-secret-00000000001",
  AUTH_TOKEN_PEPPER: "smoke-auth-token-pepper-000000000000001",
  AUTH_DATA_ENCRYPTION_KEY: "smoke-auth-data-encryption-key-00000001",
  AUTH_BOOTSTRAP_TOKEN: "smoke-auth-bootstrap-token-000000000001",
  AUTH_COOKIE_SECURE: "false",
  WHATSAPP_APP_SECRET: "smoke-whatsapp-app-secret-000000000001",
  WHATSAPP_VERIFY_TOKEN: "smoke-whatsapp-verify-token",
  WHATSAPP_DATA_ENCRYPTION_KEY: "smoke-whatsapp-data-key-000000000001",
  WHATSAPP_GRAPH_API_BASE_URL: "http://127.0.0.1:9010",
  WHATSAPP_GRAPH_API_VERSION: "v25.0",
  CONNECTOR_ACCESS_TOKEN_WHATSAPP_LIVE: "smoke-whatsapp-access-token",
});

await import("../dist/src/api/main.js");
