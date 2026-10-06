import { expect, test } from "@playwright/test";

import { competitors23 } from "./fixtures/competitors";
import { installApiMock } from "./support/api-mock";

test("collection tasks shows current state, history, and sends the status filter", async ({ page }) => {
  const mock = await installApiMock(page, {
    competitors: competitors23,
    collectionRuns: {
      items: [{ id: 1, competitor_id: 1, ownership: "competitor", title: "搜索目标竞品 01", offer_id: "offer-01", shop_name: "测试店铺", started_at: "2026-10-05T00:00:00Z", finished_at: "2026-10-05T00:00:04Z", status: "failed", error_type: "collection_timeout", error_message: "商品页面加载超时", duration_seconds: 4 }],
      total: 1, page: 1, page_size: 20,
    },
  });
  await page.goto("/");
  await page.getByRole("button", { name: "采集任务" }).click();
  await expect(page.getByRole("heading", { name: "采集任务" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "当前批量采集" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "采集记录" })).toBeVisible();
  await expect(page.getByText("商品页面加载超时")).toBeVisible();
  const request = page.waitForRequest((candidate) => candidate.url().includes("/api/collection-runs?") && new URL(candidate.url()).searchParams.get("status") === "failed");
  await page.getByLabel("采集记录状态").selectOption("failed");
  await request;
  await mock.expectNoUnexpectedApi();
});

test("an empty history page retains pagination and can return to the previous Backend page", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [] });
  const requestedPages: number[] = [];
  await page.route("**/api/collection-runs?*", route => {
    const requestedPage = Number(new URL(route.request().url()).searchParams.get("page"));
    requestedPages.push(requestedPage);
    return route.fulfill({ json: { items: [], total: requestedPage === 1 ? 41 : 21, page: requestedPage, page_size: 20 } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "采集任务", exact: true }).click();
  await expect(page.getByText("第 1 / 3 页", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "下一页" }).click();
  await expect(page.getByText("当前页无记录", { exact: true })).toBeVisible();
  await expect(page.getByText("共 21 条", { exact: true })).toBeVisible();
  await expect(page.getByText("第 2 / 2 页", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "下一页" })).toBeDisabled();
  await page.getByRole("button", { name: "上一页" }).click();
  await expect(page.getByText("第 1 / 3 页", { exact: true })).toBeVisible();
  expect(requestedPages.slice(-2)).toEqual([2, 1]);
  await mock.expectNoUnexpectedApi();
});

test("collection tasks separates current batch states from collapsed details", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: competitors23 });
  const base = { outcome_code: null, total: 3, completed: 1, succeeded: 1, failed: 0, remaining: 2, verification_required: 0, current_competitor_id: 1, browser_open: true, runner_active: true, auto_resume_attempt: 1, auto_resume_max: 2, cooldown_remaining_seconds: 30, resting_remaining_seconds: 20, items: [] };
  let state = { ...base, status: "running" };
  await page.route("**/api/competitors/collect-batch/status", route => route.fulfill({ json: state }));
  const check = async (status: typeof state.status, label: string) => {
    state = { ...base, status };
    await page.goto("/");
    await page.getByRole("button", { name: "采集任务", exact: true }).click();
    await expect(page.getByText(label, { exact: true })).toBeVisible();
  };
  await check("running", "采集中");
  await expect(page.getByRole("progressbar")).toBeVisible();
  await check("resting", "计划内主动休息");
  await expect(page.getByText("这是计划内主动休息。", { exact: true })).toBeVisible();
  await check("cooling_down", "风控冷却中");
  await expect(page.getByText("冷却剩余：30 秒 · 自动恢复 1 / 2", { exact: true })).toBeVisible();
  await expect(page.getByText("这是计划内主动休息。", { exact: true })).toHaveCount(0);
  await check("verification_required", "需要人工验证");
  await expect(page.getByText("请在已打开的浏览器中完成 1688 人工验证。", { exact: true })).toBeVisible();
  await check("completed", "本批次已完成");
  await expect(page.getByRole("button", { name: "查看本批次明细" })).toBeVisible();
  state = { ...base, status: "completed", completed: 3, remaining: 0, verification_required: 1, failed: 1, items: [
    { competitor_id: 2, status: "failed", outcome: null, error_code: "collection_timeout", message: "商品页面加载超时" },
    { competitor_id: 1, status: "verification_required", outcome: null, error_code: "1688_verification_required", message: "需要完成验证" },
  ] };
  await page.reload();
  await page.getByRole("button", { name: "采集任务", exact: true }).click();
  await expect(page.getByText("固定竞品 02", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "查看本批次明细" }).click();
  await expect(page.locator(".collection-batch-items li")).toHaveCount(2);
  await expect(page.getByText("商品页面加载超时", { exact: true })).toBeVisible();
  await mock.expectNoUnexpectedApi();
});
