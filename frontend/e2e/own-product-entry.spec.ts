import { expect, test, type Page } from "@playwright/test";
import { installApiMock } from "./support/api-mock";

const group = { id: 19, name: "A19", created_at: "2026-09-01T00:00:00Z" };

async function addFromDashboard(page: Page, url: string) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "竞品监控大屏" })).toBeVisible();
  await page.getByRole("button", { name: "添加监控商品" }).click();
  await page.getByLabel("1688 商品链接").fill(url);
  const request = page.waitForRequest((candidate) => candidate.method() === "POST" && candidate.url().endsWith("/api/competitors/add-batch"));
  await page.getByRole("dialog").getByRole("button", { name: "添加监控商品" }).click();
  return request;
}

test("loads competitor groups when opening the add dialog on the first Dashboard visit", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [], groups: [group] });
  let releaseFirst!: () => void;
  const firstResponseGate = new Promise<void>((resolve) => { releaseFirst = resolve; });
  let groupRequests = 0;
  let summaryRequests = 0;
  let firstResponseRoute: import("@playwright/test").Route | null = null;
  page.on("request", (request) => { if (new URL(request.url()).pathname === "/api/competitor-groups/summary") summaryRequests++; });
  await page.route("**/api/competitor-groups", async (route) => {
    groupRequests++;
    if (groupRequests === 1) {
      firstResponseRoute = route;
      await firstResponseGate;
      await route.fulfill({ json: [group] });
    } else {
      await route.fulfill({ json: [{ id: 20, name: "B20", created_at: "2026-09-01T00:00:00Z" }] });
    }
  });
  await page.goto("/");
  const firstResponse = page.waitForResponse((response) => response.request().method() === "GET" && new URL(response.url()).pathname === "/api/competitor-groups", { timeout: 5000 });
  await page.getByRole("button", { name: "添加监控商品" }).click();
  const groupSelect = page.getByLabel("竞品组", { exact: true });
  await expect(groupSelect).toBeDisabled();
  await expect(groupSelect.locator("option")).toHaveText("正在加载竞品组…");
  await page.getByLabel("1688 商品链接").fill("https://detail.1688.com/offer/1001.html");
  await expect(page.getByRole("dialog").getByRole("button", { name: "添加监控商品" })).toBeDisabled();
  await page.getByRole("button", { name: "关闭" }).click();
  await page.getByRole("button", { name: "添加监控商品" }).click();
  await expect(groupSelect).toBeEnabled();
  await expect(groupSelect.locator("option[value='20']")).toHaveText("B20");
  releaseFirst();
  await firstResponse;
  await expect(groupSelect.locator("option[value='20']")).toHaveText("B20");
  await expect(groupSelect.locator("option[value='19']")).toHaveCount(0);
  expect(groupRequests).toBe(2);
  expect(summaryRequests).toBe(0);
  await mock.expectNoUnexpectedApi();
});

test("shows a group loading error and retries the list request", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [], groups: [group] });
  let requests = 0;
  let summaryRequests = 0;
  page.on("request", (request) => { if (new URL(request.url()).pathname === "/api/competitor-groups/summary") summaryRequests++; });
  await page.route("**/api/competitor-groups", async (route) => {
    requests++;
    if (requests === 1) await route.fulfill({ status: 503, json: { message: "offline" } });
    else await route.fulfill({ json: [group] });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "添加监控商品" }).click();
  const groupSelect = page.getByLabel("竞品组", { exact: true });
  await expect(page.getByRole("alert")).toContainText("暂时无法获取竞品组");
  await expect(groupSelect).toBeDisabled();
  await expect(groupSelect.locator("option")).not.toContainText("未分组");
  await page.getByRole("button", { name: "重试加载" }).click();
  await expect(groupSelect.locator("option[value='19']")).toHaveText("A19");
  await expect(groupSelect).toBeEnabled();
  expect(requests).toBe(2);
  expect(summaryRequests).toBe(0);
  await mock.expectNoUnexpectedApi();
});

test("empty groups permit an ungrouped add and creating a group still selects it", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [], groups: [] });
  await page.route("**/api/competitor-groups", async (route) => {
    if (route.request().method() === "POST") await route.fulfill({ json: { id: 20, name: "B20", created_at: "2026-09-01T00:00:00Z" } });
    else await route.fulfill({ json: [] });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "添加监控商品" }).click();
  const groupSelect = page.getByLabel("竞品组", { exact: true });
  await expect(groupSelect).toBeEnabled();
  await expect(groupSelect.locator("option")).toHaveText("未分组");
  await page.getByLabel("1688 商品链接").fill("https://detail.1688.com/offer/1001.html");
  const addRequest = page.waitForRequest((request) => request.method() === "POST" && new URL(request.url()).pathname === "/api/competitors/add-batch");
  await page.getByRole("dialog").getByRole("button", { name: "添加监控商品" }).click();
  expect((await addRequest).postDataJSON()).toMatchObject({ group_id: null });
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await page.getByRole("button", { name: "添加监控商品" }).click();
  await expect(groupSelect).toBeEnabled();
  await expect(groupSelect.locator("option")).toHaveText("未分组");
  await page.getByLabel("新增竞品组").fill("B20");
  await page.getByRole("button", { name: "创建", exact: true }).click();
  await expect(groupSelect.locator("option[value='20']")).toHaveText("B20");
  await expect(groupSelect).toHaveValue("20");
  await mock.expectNoUnexpectedApi();
});

test("pending add dialog keeps its original group selection until groups load", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [], groups: [group] });
  let releaseGroups!: () => void;
  const responseGate = new Promise<void>((resolve) => { releaseGroups = resolve; });
  await page.route("**/api/competitor-groups", async (route) => {
    await responseGate;
    await route.fulfill({ json: [group] });
  });
  await page.addInitScript(() => localStorage.setItem("workbench.add-submission.v1", JSON.stringify({ submission_id: "submission-pending", inputs: [{ text: "https://detail.1688.com/offer/1001.html", source_line: 1 }], group_id: 19, draft_text: "https://detail.1688.com/offer/1001.html" })));
  await page.goto("/");
  const groupsResponse = page.waitForResponse((response) => response.request().method() === "GET" && new URL(response.url()).pathname === "/api/competitor-groups");
  await page.getByRole("button", { name: "添加监控商品" }).click();
  const groupSelect = page.getByLabel("竞品组", { exact: true });
  await expect(groupSelect).toBeDisabled();
  await expect(groupSelect).toHaveValue("19");
  releaseGroups();
  await groupsResponse;
  await expect(groupSelect.locator("option[value='19']")).toHaveText("A19");
  await expect(groupSelect).toBeEnabled();
  await expect(groupSelect).toHaveValue("19");
  await mock.expectNoUnexpectedApi();
});

test("adds self from Dashboard, lists it under own products, and binds it to one group", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [], groups: [group], addProducts: { "1001": "self" }, activeMonitoredProducts: 1 });
  const collectRequest = page.waitForRequest((candidate) => candidate.method() === "POST" && candidate.url().endsWith("/api/competitors/collect-batch"));
  await page.goto("/");
  await expect(page.getByRole("button", { name: "立即采集" })).toBeVisible();
  await page.getByRole("button", { name: "立即采集" }).click();
  expect((await collectRequest).postDataJSON()).toEqual({ mode: "all_active" });
  const addRequest = await addFromDashboard(page, "https://detail.1688.com/offer/1001.html");
  expect((await addRequest).postDataJSON()).toMatchObject({ inputs: [{ text: "https://detail.1688.com/offer/1001.html", source_line: 1 }], group_id: null });
  await expect(page.locator(".toast")).toContainText("新增 1");

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
  expect((await addRequest).postDataJSON()).toMatchObject({ inputs: [{ text: "https://detail.1688.com/offer/2002.html", source_line: 1 }], group_id: null });
  await expect(page.locator(".toast")).toContainText("新增 1");

  await page.getByRole("button", { name: "竞品列表" }).click();
  await expect(page.getByRole("heading", { name: "竞品列表" })).toBeVisible();
  await expect(page.getByText("新增竞品商品", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "添加监控商品" })).not.toBeVisible();
  await page.getByRole("button", { name: "批量操作（0）" }).click();
  await expect(page.getByRole("menuitem", { name: /采集/ })).toHaveCount(0);
  await mock.expectNoUnexpectedApi();
});

test("pauses and resumes collection from the Dashboard overview", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [], batchStatus: { status: "running", outcome_code: null, total: 2, completed: 0, succeeded: 0, failed: 0, remaining: 2, verification_required: 0, current_competitor_id: null, browser_open: true, runner_active: true, auto_resume_attempt: 0, auto_resume_max: 2, cooldown_remaining_seconds: 0, resting_remaining_seconds: 0, operating_metrics_counts: { not_attempted: 0, success: 0, partial: 0, no_values: 0, failed: 0, blocked: 0 }, items: [] } });
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
