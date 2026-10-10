import { expect, test, type Page } from "@playwright/test";
import { installApiMock } from "./support/api-mock";

const group = { id: 19, name: "A19", created_at: "2026-09-01T00:00:00Z" };

async function addFromDashboard(page: Page, url: string) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "竞品监控大屏" })).toBeVisible();
  await page.getByRole("button", { name: "添加监控商品" }).click();
  await page.getByLabel("1688 商品链接").fill(url);
  const request = page.waitForRequest((candidate) => candidate.method() === "POST" && candidate.url().endsWith("/api/competitors"));
  await page.getByRole("dialog").getByRole("button", { name: "添加监控商品" }).click();
  return request;
}

test("adds self from Dashboard, lists it under own products, and binds it to one group", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [], groups: [group], addProducts: { "1001": "self" }, activeMonitoredProducts: 1 });
  const collectRequest = page.waitForRequest((candidate) => candidate.method() === "POST" && candidate.url().endsWith("/api/competitors/collect-batch"));
  await page.goto("/");
  await expect(page.getByRole("button", { name: "立即采集" })).toBeVisible();
  await page.getByRole("button", { name: "立即采集" }).click();
  expect((await collectRequest).postDataJSON()).toEqual({ mode: "all_active" });
  const addRequest = await addFromDashboard(page, "https://detail.1688.com/offer/1001.html");
  expect((await addRequest).postDataJSON()).toEqual({ url: "https://detail.1688.com/offer/1001.html", group_id: null });
  await expect(page.locator(".toast")).toContainText("已识别为我方商品");

  await page.getByRole("button", { name: "我方商品" }).click();
  await expect(page.getByRole("heading", { name: "我方商品", exact: true })).toBeVisible();
  const ownRow = page.getByRole("row").filter({ hasText: "新增我方商品" });
  await expect(ownRow).toBeVisible();
  await expect(page.getByRole("button", { name: "添加监控商品" })).not.toBeVisible();
  await page.getByRole("button", { name: "+ 绑定竞品组" }).click();
  await expect(page.getByRole("dialog", { name: "修改竞品组" })).toBeVisible();
  await page.getByRole("dialog", { name: "修改竞品组" }).getByLabel("竞品组", { exact: true }).selectOption("19");
  const groupRequest = page.waitForRequest((candidate) => candidate.method() === "PATCH" && candidate.url().endsWith("/api/competitors/1/group"));
  await page.getByRole("button", { name: "保存" }).click();
  expect((await groupRequest).postDataJSON()).toEqual({ group_id: 19 });
  await expect(ownRow).toContainText("A19");
  await page.getByRole("button", { name: "批量操作（0）" }).click();
  await expect(page.getByRole("menuitem", { name: /采集/ })).toHaveCount(0);

  await mock.expectNoUnexpectedApi();
});

test("adds competitor from Dashboard and keeps it in the competitor list", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [], groups: [group], addProducts: { "2002": "competitor" } });
  const addRequest = await addFromDashboard(page, "https://detail.1688.com/offer/2002.html");
  expect((await addRequest).postDataJSON()).toEqual({ url: "https://detail.1688.com/offer/2002.html", group_id: null });
  await expect(page.locator(".toast")).toContainText("已添加监控商品");

  await page.getByRole("button", { name: "竞品列表" }).click();
  await expect(page.getByRole("heading", { name: "竞品列表" })).toBeVisible();
  await expect(page.getByText("新增竞品商品", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "添加监控商品" })).not.toBeVisible();
  await page.getByRole("button", { name: "批量操作（0）" }).click();
  await expect(page.getByRole("menuitem", { name: /采集/ })).toHaveCount(0);
  await mock.expectNoUnexpectedApi();
});

test("pauses and resumes collection from the Dashboard overview", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [], batchStatus: { status: "running", outcome_code: null, total: 2, completed: 0, succeeded: 0, failed: 0, remaining: 2, verification_required: 0, current_competitor_id: null, browser_open: true, runner_active: true, auto_resume_attempt: 0, auto_resume_max: 2, cooldown_remaining_seconds: 0, resting_remaining_seconds: 0, items: [] } });
  await page.goto("/");
  const overview = page.locator(".collection-overview");
  await expect(overview.getByRole("button", { name: "暂停采集" })).toBeVisible();
  await overview.getByRole("button", { name: "暂停采集" }).click();
  await expect(overview.getByText("采集已暂停 · 0 / 2")).toBeVisible();
  await overview.getByRole("button", { name: "继续采集" }).click();
  await expect(overview.getByText("采集中 0 / 2")).toBeVisible();
  await overview.getByRole("button", { name: "结束采集" }).click();
  await expect(overview.getByRole("button", { name: "结束中…" })).toBeVisible();
  await expect(overview.getByText("采集已结束 · 0 / 2")).toBeVisible();
  await expect(overview.getByRole("button", { name: "暂停采集" })).toHaveCount(0);
  await mock.expectNoUnexpectedApi();
});
