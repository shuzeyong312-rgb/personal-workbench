import { expect, type Page } from "@playwright/test";
import type { Competitor } from "../../src/App";

export async function installApiMock(page: Page, options: { competitors: Competitor[] }) {
  const unexpected: string[] = [];
  const responses: Record<string, unknown> = {
    "GET /api/dashboard/today": { date: "2026-09-28", stats: { monitored_competitors: 0, changed_competitors: 0, change_events: 0, price_changed_competitors: 0, stock_changed_competitors: 0, sku_changed_competitors: 0, failed_collections: 0 }, items: [], collection_summary: { last_collection_at: null, success_runs: 0, failed_runs: 0, average_duration_seconds: null }, trend_7d: [] },
    "GET /api/dashboard/group-attention": { date: "2026-09-28", kpis: { monitored_product_groups: 0, changed_product_groups_today: 0, changed_competitors_today: 0 }, groups: [] },
    "GET /api/competitors/collect-batch/status": { status: "idle", outcome_code: null, total: 0, completed: 0, succeeded: 0, failed: 0, remaining: 0, verification_required: 0, current_competitor_id: null, browser_open: false, runner_active: false, items: [] },
    "GET /api/competitors": options.competitors,
    "GET /api/competitor-groups": [],
  };
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const key = `${request.method()} ${new URL(request.url()).pathname}`;
    if (!(key in responses)) { unexpected.push(key); await route.abort("blockedbyclient"); return; }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(responses[key]) });
  });
  return { unexpected, async expectNoUnexpectedApi() { expect(unexpected, `Unexpected API request:\n${unexpected.join("\n")}`).toEqual([]); } };
}
