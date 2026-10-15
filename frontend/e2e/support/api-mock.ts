import { expect, type Page } from "@playwright/test";
import type { Competitor } from "../../src/App";

export async function installApiMock(page: Page, options: { competitors: Competitor[]; groups?: { id: number; name: string; created_at: string }[]; addProducts?: Record<string, "self" | "competitor">; activeMonitoredProducts?: number; collectionRuns?: unknown | ((url: URL) => unknown); collectionBatches?: unknown; batchDetails?: Record<string, unknown>; batchStatus?: Record<string, unknown> }) {
  const unexpected: string[] = [];
  let competitors = options.competitors;
  const groups = options.groups ?? [];
  let nextId = Math.max(0, ...competitors.map((competitor) => competitor.id)) + 1;
  let batchStatus = options.batchStatus ?? { status: "idle", outcome_code: null, batch_id: null, task_id: null, phase: null, attempts_started: 0, page_visits: 0, page_visits_unknown: 0, verification_resume_visits: 0, retry_visits: 0, retry_max: 0, retry_total: 0, retry_completed: 0, total: 0, completed: 0, succeeded: 0, failed: 0, remaining: 0, verification_required: 0, current_competitor_id: null, browser_open: false, runner_active: false, auto_resume_attempt: 0, auto_resume_max: 2, cooldown_remaining_seconds: 0, resting_remaining_seconds: 0, operating_metrics_counts: { not_attempted: 0, success: 0, partial: 0, no_values: 0, failed: 0, blocked: 0 }, items: [] };
  const responses: Record<string, unknown> = {
    "GET /api/dashboard/today": { date: "2026-09-28", stats: { monitored_competitors: 0, active_monitored_products: options.activeMonitoredProducts ?? 0, changed_competitors: 0, change_events: 0, price_changed_competitors: 0, stock_changed_competitors: 0, sku_changed_competitors: 0, failed_collections: 0 }, items: [], collection_summary: { last_collection_at: null, success_runs: 0, failed_runs: 0, average_duration_seconds: null }, trend_7d: [] },
    "GET /api/dashboard/group-attention": { date: "2026-09-28", kpis: { monitored_product_groups: 0, changed_product_groups_today: 0, changed_competitors_today: 0 }, groups: [] },
    "GET /api/settings/own-shop-name": { configured: true, own_shop_name: "测试店铺" },
    "GET /api/settings/competitor-monitoring": { item_interval_seconds: 5, continuous_collection_count: 10, batch_rest_seconds: 120, verification_cooldown_seconds: 600, auto_resume_max: 2, operating_metrics_retry_max: 0, auto_collection_enabled: true, auto_collection_strategy: "rolling_24h", auto_collection_time: "09:30", auto_collection_missed_policy: "catch_up" },
    "GET /api/competitors": competitors,
    "GET /api/collection-runs": options.collectionRuns ?? { items: [], total: 0, page: 1, page_size: 20 },
    "GET /api/collection-batches": options.collectionBatches ?? { items: [], total: 0, page: 1, page_size: 20 },
    "GET /api/competitor-groups": groups,
    "GET /api/competitor-groups/summary": { groups: [], unassigned: { competitor_count: 0, active_count: 0, price_min: null, price_max: null, changed_competitors_today: 0, last_change_at: null } },
  };
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const key = `${request.method()} ${new URL(request.url()).pathname}`;
    const requestUrl = new URL(request.url());
    if (key === "GET /api/competitors/collect-batch/status") {
      if (batchStatus.status === "stopping") batchStatus = { ...batchStatus, status: "stopped", runner_active: false, browser_open: false };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(batchStatus) });
      return;
    }
    if (request.method() === "GET" && /^\/api\/collection-batches\/[^/]+$/.test(requestUrl.pathname)) {
      const taskId = decodeURIComponent(requestUrl.pathname.split("/").at(-1)!);
      const detail = options.batchDetails?.[taskId];
      if (!detail) unexpected.push(key);
      await route.fulfill({ status: detail ? 200 : 404, contentType: "application/json", body: JSON.stringify(detail ?? { detail: "not mocked" }) });
      return;
    }
    if (key === "GET /api/collection-runs" && typeof options.collectionRuns === "function") {
      await route.fulfill({ json: options.collectionRuns(requestUrl) });
      return;
    }
    if (["POST /api/competitors/collect-batch/pause", "POST /api/competitors/collect-batch/resume", "POST /api/competitors/collect-batch/end"].includes(key)) {
      batchStatus = { ...batchStatus, status: key.endsWith("/pause") ? "paused" : key.endsWith("/end") ? "stopping" : "running" };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(batchStatus) });
      return;
    }
    if (key === "POST /api/competitors/add-batch") {
      const submission = request.postDataJSON() as { submission_id: string; inputs: { text: string; source_line: number }[]; group_id: number | null };
      const items = [];
      for (const [position, input] of submission.inputs.entries()) {
        const body = { url: input.text, group_id: submission.group_id };
      const offerId = body.url.match(/\/offer\/(\d+)\.html/i)?.[1] ?? String(nextId);
      const ownership = options.addProducts?.[offerId] ?? "competitor";
      const groupId = body.group_id ?? null;
      const added: Competitor = {
        id: nextId++, platform: "1688", offer_id: offerId, url: `https://detail.1688.com/offer/${offerId}.html`,
        group_id: groupId, group_role: ownership === "self" && groupId !== null ? "own" : "competitor", ownership,
        title: ownership === "self" ? "新增我方商品" : "新增竞品商品", shop_name: ownership === "self" ? "测试店铺" : "竞品店铺",
        main_image_url: null, status: "active", is_active: true, created_at: "2026-09-28T00:00:00Z", last_collected_at: "2026-09-28T00:00:00Z",
        latest_snapshot: { price_min: null, price_max: null, sku_count: 0 }, latest_change: null,
      };
      competitors = [...competitors, added];

        items.push({ position, source_line: input.source_line, input_text: input.text, result_code: "added", sanitized_reason: null, competitor_id: added.id, title: added.title, page_visits: 1, page_visits_unknown: 0, attempts: [] });
      }
      const input_summary = { total: items.length, candidate_total: items.length, processed: items.length, pending: 0, remaining: 0, added: items.length, business_rejected: 0, technical_failed: 0, verification_required: 0, interrupted: 0, not_executed: 0, anomaly_inputs: 0 };
      const task = { task_id: submission.submission_id, task_kind: "add_links", trigger_kind: "add_links", lifecycle_status: "terminal", outcome_code: "success", planned_products: items.length, counts: { first_pass_success: items.length }, input_summary, items, total: items.length, page: 1, page_size: 100 };
      await route.fulfill({ status: 200, json: { accepted: true, task_id: submission.submission_id, task } });
      return;
    }
    if (key === "POST /api/competitors/collect-batch") {
      const body = request.postDataJSON() as { mode?: string; competitor_ids?: number[] };
      if (body.mode !== "all_active" || body.competitor_ids) { unexpected.push(`${key} ${JSON.stringify(body)}`); }
      const activeCount = options.activeMonitoredProducts ?? competitors.filter((competitor) => competitor.is_active).length;
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "completed", outcome_code: "completed", total: activeCount, completed: activeCount, succeeded: activeCount, failed: 0, remaining: 0, verification_required: 0, current_competitor_id: null, browser_open: false, runner_active: false, auto_resume_attempt: 0, auto_resume_max: 2, cooldown_remaining_seconds: 0, resting_remaining_seconds: 0, operating_metrics_counts: { not_attempted: 0, success: activeCount, partial: 0, no_values: 0, failed: 0, blocked: 0 }, items: [] }) });
      return;
    }
    const groupMatch = requestUrl.pathname.match(/^\/api\/competitors\/(\d+)\/group$/);
    if (key === "PATCH /api/competitors/" + groupMatch?.[1] + "/group") {
      const body = request.postDataJSON() as { group_id: number | null };
      const competitorId = Number(groupMatch?.[1]);
      const current = competitors.find((competitor) => competitor.id === competitorId);
      if (!current) { await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ code: "competitor_not_found" }) }); return; }
      const updated = { ...current, group_id: body.group_id, group_role: current.ownership === "self" && body.group_id !== null ? "own" as const : "competitor" as const };
      competitors = competitors.map((competitor) => competitor.id === competitorId ? updated : competitor);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(updated) });
      return;
    }
    const detailMatch = requestUrl.pathname.match(/^\/api\/competitors\/(\d+)\/detail$/);
    if (key === "GET /api/competitors/" + detailMatch?.[1] + "/detail") {
      const current = competitors.find((competitor) => competitor.id === Number(detailMatch?.[1]));
      if (!current) { await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ code: "competitor_not_found" }) }); return; }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        range_days: Number(requestUrl.searchParams.get("days") ?? 7), competitor: current, latest_snapshot: null, latest_skus: [], latest_price_change: null,
        daily_trend: [], recent_changes: [], recent_collection_runs: [],
      }) });
      return;
    }
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
    const response = key === "GET /api/competitors"
      ? requestUrl.searchParams.get("ownership")
        ? competitors.filter((competitor) => (competitor.ownership ?? (competitor.group_role === "own" ? "self" : "competitor")) === requestUrl.searchParams.get("ownership"))
        : competitors
      : responses[key];
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(response) });
  });
  return { unexpected, async expectNoUnexpectedApi() { expect(unexpected, `Unexpected API request:\n${unexpected.join("\n")}`).toEqual([]); } };
}
