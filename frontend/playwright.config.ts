import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "test-results",
  reporter: [["list"], ["html", { open: "never" }]],
  use: { baseURL: "http://127.0.0.1:5201", screenshot: "only-on-failure", trace: "retain-on-failure", video: "off" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: { command: "npm exec vite -- --host 127.0.0.1 --port 5201 --strictPort", url: "http://127.0.0.1:5201", reuseExistingServer: false, timeout: 120_000 },
});
