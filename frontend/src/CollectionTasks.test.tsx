import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, expect, test } from "vitest";
import { chromium, expect as ui, type Browser, type Page } from "@playwright/test";
import { createServer, type ViteDevServer } from "vite";
import { idleBatchState } from "./App";
import { installApiMock } from "../e2e/support/api-mock";
import { competitors23 } from "../e2e/fixtures/competitors";

let server: ViteDevServer;
let browser: Browser;
beforeAll(async () => {
  server = await createServer({ root: fileURLToPath(new URL("..", import.meta.url)), server: { host: "127.0.0.1", port: 0 } });
  await server.listen();
  browser = await chromium.launch({ headless: true });
});
afterAll(async () => { await browser?.close(); await server?.close(); });
const run = (id: number) => ({ id, competitor_id: 1, ownership: "self", title: `记录 ${id}`, offer_id: "123", shop_name: "店铺", started_at: "2026-10-05T00:00:00Z", finished_at: null, status: "running", error_type: null, error_message: null, duration_seconds: null });
async function open(page: Page) {
  await page.goto(server.resolvedUrls!.local[0]);
  await page.getByRole("button", { name: "采集任务", exact: true }).click();
}

test("running polling failure is local and polling recovery clears it without retry", async () => {
  const page = await browser.newPage();
  try {
    const mock = await installApiMock(page, { competitors: [], collectionRuns: { items: [run(1)], total: 1, page: 1, page_size: 20 } });
    let fail = false;
    let completed = false;
    let reads = 0;
    await page.route("**/api/competitors/collect-batch/status", route => {
      reads++;
      return route.fulfill({ status: fail ? 503 : 200, json: { ...idleBatchState, status: completed ? "completed" : "running", total: 1, remaining: completed ? 0 : 1, completed: completed ? 1 : 0, succeeded: completed ? 1 : 0 } });
    });
    await page.clock.install();
    await open(page);
    await ui(page.getByText("采集中", { exact: true })).toBeVisible();
    await ui(page.getByText("记录 1", { exact: true })).toBeVisible();
    const initialReads = reads;
    fail = true;
    await page.clock.runFor(1500);
    await ui(page.getByText("状态刷新失败", { exact: true })).toBeVisible();
    await ui(page.getByText("记录 1", { exact: true })).toBeVisible();
    fail = false; completed = true;
    await page.clock.runFor(1500);
    await ui(page.getByText("本批次已完成", { exact: true })).toBeVisible();
    await ui(page.getByText("状态刷新失败", { exact: true })).toHaveCount(0);
    await page.clock.runFor(5000);
    await ui(page.getByText("本批次已完成", { exact: true })).toBeVisible();
    expect(reads).toBe(initialReads + 2);
    await mock.expectNoUnexpectedApi();
  } finally { await page.close(); }
}, 15000);

test("batch details are collapsed by default and expand in Backend order", async () => {
  const page = await browser.newPage();
  try {
    const mock = await installApiMock(page, { competitors: competitors23, collectionRuns: { items: [run(1)], total: 1, page: 1, page_size: 20 } });
    await page.route("**/api/competitors/collect-batch/status", route => route.fulfill({ json: {
      ...idleBatchState, status: "completed", total: 3, completed: 3, succeeded: 1, failed: 1, remaining: 0, verification_required: 1,
      items: [
        { competitor_id: 3, status: "success", outcome: "active", error_code: null, message: null },
        { competitor_id: 2, status: "failed", outcome: null, error_code: "collection_timeout", message: "商品页面加载超时" },
        { competitor_id: 1, status: "verification_required", outcome: null, error_code: "1688_verification_required", message: "需要完成验证" },
      ],
    } }));
    await open(page);
    await ui(page.getByRole("heading", { name: "本批次明细" })).toBeVisible();
    await ui(page.getByText("固定竞品 03", { exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "查看本批次明细" }).click();
    const rows = page.locator(".collection-batch-items li");
    await ui(rows).toHaveCount(3);
    expect(await rows.allTextContents()).toEqual([
      expect.stringContaining("固定竞品 03"),
      expect.stringContaining("固定竞品 02"),
      expect.stringContaining("搜索目标竞品 01"),
    ]);
    await ui(page.getByText("采集成功 · 在售", { exact: true })).toBeVisible();
    await ui(page.getByText("collection_timeout", { exact: true })).toBeVisible();
    await ui(page.getByText("1688_verification_required", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "收起本批次明细" }).click();
    await ui(page.getByText("固定竞品 03", { exact: true })).toHaveCount(0);
    await mock.expectNoUnexpectedApi();
  } finally { await page.close(); }
});

test("running shows a compact progress notice", async () => {
  const page = await browser.newPage();
  try {
    const mock = await installApiMock(page, { competitors: competitors23 });
    await page.route("**/api/competitors/collect-batch/status", route => route.fulfill({ json: { ...idleBatchState, status: "running", total: 2, completed: 1, succeeded: 1, remaining: 1, current_competitor_id: 1 } }));
    await open(page);
    await ui(page.getByText("正在处理当前商品。", { exact: true })).toBeVisible();
    await mock.expectNoUnexpectedApi();
  } finally { await page.close(); }
});

test("history empty page preserves Backend total and page, returns to previous without slicing", async () => {
  const page = await browser.newPage();
  try {
    const mock = await installApiMock(page, { competitors: [] });
    const queries: string[] = [];
    await page.route("**/api/collection-runs?*", route => {
      const url = new URL(route.request().url());
      queries.push(url.search);
      const requestedPage = Number(url.searchParams.get("page"));
      return route.fulfill({ json: { items: requestedPage === 2 ? [] : Array.from({ length: 20 }, (_, i) => run(i + 1)), total: requestedPage === 2 ? 21 : 41, page: requestedPage, page_size: 20 } });
    });
    await open(page);
    const bar = page.locator(".pagination-bar");
    await ui(bar).toContainText("共 41 条");
    await ui(page.locator(".collection-runs-table tbody tr")).toHaveCount(20);
    await bar.getByRole("button", { name: "下一页" }).click();
    await ui(page.getByText("当前页无记录", { exact: true })).toBeVisible();
    await ui(page.getByText("暂无采集记录", { exact: true })).toHaveCount(0);
    await ui(bar).toContainText("共 21 条");
    await ui(bar).toContainText("第 2 / 2 页");
    await ui(bar.locator('[aria-current="page"]')).toHaveText("2");
    await ui(bar.getByRole("button", { name: "下一页" })).toBeDisabled();
    await bar.getByRole("button", { name: "上一页" }).click();
    await ui(page.locator(".collection-runs-table tbody tr")).toHaveCount(20);
    expect(queries.slice(-2)).toEqual(["?status=all&ownership=all&page=2", "?status=all&ownership=all&page=1"]);
    await mock.expectNoUnexpectedApi();
  } finally { await page.close(); }
});

test.each(["status", "history"])("%s failure and retry leave the other source independent", async source => {
  const page = await browser.newPage();
  try {
    const mock = await installApiMock(page, { competitors: [] });
    let fail = true;
    let statusReads = 0;
    let historyReads = 0;
    await page.route("**/api/competitors/collect-batch/status", route => {
      statusReads++;
      return route.fulfill({ status: source === "status" && fail ? 503 : 200, json: { ...idleBatchState, status: "completed" } });
    });
    await page.route("**/api/collection-runs?*", route => {
      historyReads++;
      return route.fulfill({ status: source === "history" && fail ? 503 : 200, json: { items: [run(1)], total: 1, page: 1, page_size: 20 } });
    });
    await open(page);
    await ui(page.getByText(source === "status" ? "状态刷新失败" : "采集记录加载失败", { exact: true })).toBeVisible();
    await ui(page.getByText(source === "status" ? "记录 1" : "本批次已完成", { exact: true })).toBeVisible();
    const previousStatus = statusReads;
    const previousHistory = historyReads;
    fail = false;
    await page.getByRole("button", { name: "重试", exact: true }).click();
    await ui(page.getByText("本批次已完成", { exact: true })).toBeVisible();
    await ui(page.getByText("记录 1", { exact: true })).toBeVisible();
    expect(statusReads).toBe(previousStatus + (source === "status" ? 1 : 0));
    expect(historyReads).toBe(previousHistory + (source === "history" ? 1 : 0));
    await mock.expectNoUnexpectedApi();
  } finally { await page.close(); }
});

test("history filters reset page and stale responses cannot replace the newest query", async () => {
  const page = await browser.newPage();
  try {
    const mock = await installApiMock(page, { competitors: [] });
    const queries: URLSearchParams[] = [];
    let releaseOld: (() => void) | undefined;
    let oldFinished: Promise<void> | undefined;
    await page.route("**/api/collection-runs?*", async route => {
      const params = new URL(route.request().url()).searchParams;
      queries.push(params);
      if (params.get("search") === "old") {
        await new Promise<void>(resolve => { releaseOld = resolve; });
        oldFinished = route.fulfill({ json: { items: [run(999)], total: 1, page: 1, page_size: 20 } });
        await oldFinished;
        return;
      }
      await route.fulfill({ json: { items: [run(1)], total: 41, page: Number(params.get("page")), page_size: 20 } });
    });
    await open(page);
    const next = page.getByRole("button", { name: "下一页", exact: true });
    const assertQuery = (expected: Record<string, string>) => expect(Object.fromEntries(queries.at(-1)!)).toEqual(expected);
    await ui(next).toBeEnabled();
    await next.click();
    await ui(page.getByText("第 2 / 3 页", { exact: true })).toBeVisible();
    await page.getByLabel("搜索采集记录").fill("目标");
    await page.getByRole("button", { name: "搜索", exact: true }).click();
    await ui(page.getByText("第 1 / 3 页", { exact: true })).toBeVisible();
    assertQuery({ search: "目标", status: "all", ownership: "all", page: "1" });
    await next.click();
    await ui(page.getByText("第 2 / 3 页", { exact: true })).toBeVisible();
    await page.getByLabel("采集记录状态").selectOption("failed");
    await ui(page.getByText("第 1 / 3 页", { exact: true })).toBeVisible();
    assertQuery({ search: "目标", status: "failed", ownership: "all", page: "1" });
    await next.click();
    await ui(page.getByText("第 2 / 3 页", { exact: true })).toBeVisible();
    await page.getByLabel("采集记录身份").selectOption("self");
    await ui(page.getByText("第 1 / 3 页", { exact: true })).toBeVisible();
    assertQuery({ search: "目标", status: "failed", ownership: "self", page: "1" });
    await next.click();
    await ui(page.getByText("第 2 / 3 页", { exact: true })).toBeVisible();
    assertQuery({ search: "目标", status: "failed", ownership: "self", page: "2" });
    await page.getByLabel("搜索采集记录").fill("old");
    await page.getByRole("button", { name: "搜索", exact: true }).click();
    await ui.poll(() => !!releaseOld).toBe(true);
    await page.getByLabel("搜索采集记录").fill("new");
    await page.getByRole("button", { name: "搜索", exact: true }).click();
    await ui(page.getByText("记录 1", { exact: true })).toBeVisible();
    releaseOld!();
    await ui.poll(() => !!oldFinished).toBe(true);
    await oldFinished;
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await ui(page.getByText("记录 999", { exact: true })).toHaveCount(0);
    await ui(page.getByText("记录 1", { exact: true })).toBeVisible();
    await mock.expectNoUnexpectedApi();
  } finally { await page.close(); }
});

test.each(["own-products", "competitors"])("%s uses the shared pagination contract and local ten-row pages", async source => {
  const page = await browser.newPage();
  try {
    const self = source === "own-products";
    const products = competitors23.map(product => ({ ...product, ownership: self ? "self" as const : "competitor" as const }));
    const mock = await installApiMock(page, { competitors: products });
    await page.goto(server.resolvedUrls!.local[0]);
    await page.getByRole("button", { name: self ? "我方商品" : "竞品列表", exact: true }).click();
    const bar = page.locator(".pagination-bar");
    await ui(bar).toContainText(self ? "共 23 个我方商品" : "共 23 个竞品");
    await ui(bar.locator('[aria-current="page"]')).toHaveText("1");
    await ui(bar.getByRole("button", { name: "上一页" })).toBeDisabled();
    await bar.getByRole("button", { name: "下一页" }).click();
    await ui(bar).toContainText("第 2 / 3 页");
    await ui(page.getByRole("row").filter({ hasText: "固定竞品 11" })).toBeVisible();
    await ui(page.getByRole("row").filter({ hasText: "固定竞品 10" })).toHaveCount(0);
    await mock.expectNoUnexpectedApi();
  } finally { await page.close(); }
});
