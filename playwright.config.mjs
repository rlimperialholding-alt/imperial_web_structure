import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 4 : 1,
  timeout: 60_000,
  expect: {
    timeout: 10_000
  },
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }]
  ],
  use: {
    baseURL: process.env.PREVIEW_BASE_URL || "http://127.0.0.1:8080",
    browserName: "chromium",
    colorScheme: "light",
    locale: "hu-HU",
    reducedMotion: "reduce",
    serviceWorkers: "block",
    trace: "retain-on-failure"
  },
  outputDir: "test-results"
});
