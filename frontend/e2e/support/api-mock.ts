import { expect, type Page } from "@playwright/test";
import type { Competitor } from "../../src/App";

export async function installApiMock(page: Page, options: { competitors: Competitor[]; groups?: { id: number; name: string; created_at: string }[] }) {
  const unexpected: string[] = [];
  let competitors = options.competitors;
  const groups = options.groups ?? [];
  const responses: Record<string, unknown> = {
    "GET /api/dashboard/today": { date: "2026-09-28", stats: { monitored_competitors: 0, changed_competitors: 0, change_events: 0, price_changed_competitors: 0, stock_changed_competitors: 0, sku_changed_competitors: 0, failed_collections: 0 }, items: [], collection_summary: { last_collection_at: null, success_runs: 0, failed_runs: 0, average_duration_seconds: null }, trend_7d: [] },
    "GET /api/dashboard/group-attention": { date: "2026-09-28", kpis: { monitored_product_groups: 0, changed_product_groups_today: 0, changed_competitors_today: 0 }, groups: [] },
    "GET /api/competitors/collect-batch/status": { status: "idle", outcome_code: null, total: 0, completed: 0, succeeded: 0, failed: 0, remaining: 0, verification_required: 0, current_competitor_id: null, browser_open: false, runner_active: false, auto_resume_attempt: 0, auto_resume_max: 2, cooldown_remaining_seconds: 0, items: [] },
    "GET /api/competitors": competitors,
    "GET /api/competitor-groups": groups,
    "GET /api/competitor-groups/summary": { groups: [], unassigned: { competitor_count: 0, active_count: 0, price_min: null, price_max: null, changed_competitors_today: 0, last_change_at: null } },
  };
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const key = `${request.method()} ${new URL(request.url()).pathname}`;
    if (key === "PATCH /api/competitors/group-batch") {
      const body = request.postDataJSON() as { competitor_ids: number[]; group_id: number | null };
      competitors = competitors.map((competitor) => body.competitor_ids.includes(competitor.id) ? { ...competitor, group_id: body.group_id } : competitor);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ updated_count: body.competitor_ids.length, competitor_ids: body.competitor_ids, group_id: body.group_id }) });
      return;
    }
    if (key === "PATCH /api/competitors/monitoring-batch") {
      const body = request.postDataJSON() as { competitor_ids: number[]; is_active: boolean };
      const updatedIds = competitors.filter((competitor) => body.competitor_ids.includes(competitor.id) && competitor.is_active !== body.is_active).map((competitor) => competitor.id);
      competitors = competitors.map((competitor) => updatedIds.includes(competitor.id) ? { ...competitor, is_active: body.is_active } : competitor);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ updated_count: updatedIds.length, competitor_ids: updatedIds, is_active: body.is_active }) });
      return;
    }
    if (key === "POST /api/competitors/delete-batch") {
      const body = request.postDataJSON() as { competitor_ids: number[] };
      competitors = competitors.filter((competitor) => !body.competitor_ids.includes(competitor.id));
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ deleted_count: body.competitor_ids.length, competitor_ids: body.competitor_ids }) });
      return;
    }
    if (!(key in responses)) { unexpected.push(key); await route.abort("blockedbyclient"); return; }
    const response = key === "GET /api/competitors" ? competitors : responses[key];
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(response) });
  });
  return { unexpected, async expectNoUnexpectedApi() { expect(unexpected, `Unexpected API request:\n${unexpected.join("\n")}`).toEqual([]); } };
}
