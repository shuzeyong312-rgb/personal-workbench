import { expect, test } from "@playwright/test";
import { installApiMock } from "./support/api-mock";

const product = { id: 42, version: 1, model: "FAN-42", name: "便携风扇", manufacturer_name: "测试厂家", parameters: null, selling_points: null, wholesale_price: null, price_note: null, created_at: "2026-01-01", updated_at: "2026-01-01" };

test("search uses the product API, supports click navigation and keyboard dismissal", async ({ page }) => {
  await installApiMock(page, { competitors: [] });
  const queries: string[] = [];
  await page.route("**/api/product-library/**", async route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/products")) { queries.push(url.searchParams.get("q") || ""); await route.fulfill({ json: { items: url.searchParams.get("q")?.includes("FAN") ? [product] : [], total: 1 } }); }
    else if (url.pathname.endsWith("/manufacturers")) await route.fulfill({ json: { items: [] } });
    else await route.fulfill({ status: 404 });
  });
  await page.goto("/");
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog", { name: "全局搜索" });
  await dialog.getByRole("textbox").fill("FAN-42");
  await expect(dialog.getByRole("button", { name: /便携风扇/ })).toBeVisible();
  await page.screenshot({ path: "test-results/workspace-search-desktop.png" });
  await page.keyboard.press("Enter");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: /便携风扇/ }).click();
  await expect(page.locator('main[data-page="product-library"]')).toBeVisible();
  await expect.poll(() => queries.filter(q => q === "FAN-42").length).toBeGreaterThanOrEqual(2);
  await page.keyboard.press("Control+k"); await page.keyboard.press("Escape"); await expect(dialog).toBeHidden();
});

test("terminal tasks are deduplicated and read state survives reload and clearing", async ({ page }) => {
  const terminal = { status: "completed", task_id: "task-a", work_kind: "collect_products", lifecycle_status: "terminal", batch_outcome_code: "partial_failure", total: 3, completed: 3, succeeded: 2, failed: 1, remaining: 0, runner_active: false, browser_open: false, items: [] };
  await installApiMock(page, { competitors: [], batchStatus: terminal });
  await page.goto("/");
  const bell = page.getByRole("button", { name: /任务通知/ });
  await expect(bell).toHaveAttribute("aria-label", "任务通知，1 条未读");
  await bell.click();
  await expect(page.getByText("竞品采集部分完成")).toHaveCount(1);
  await page.getByRole("button", { name: "标记已读" }).click();
  await page.reload();
  await expect(bell).toHaveAttribute("aria-label", "任务通知，0 条未读");
  await bell.click(); await page.getByRole("button", { name: "清理已读" }).click();
  await page.reload(); await bell.click(); await expect(page.getByText("暂无任务通知")).toBeVisible();
});

test("rapid searches ignore stale responses and failures are visible", async ({ page }) => {
  await installApiMock(page, { competitors: [] });
  await page.route("**/api/product-library/products?*", async route => {
    const q = new URL(route.request().url()).searchParams.get("q");
    if (q === "slow") { await new Promise(resolve => setTimeout(resolve, 900)); await route.fulfill({ json: { items: [{ ...product, name: "过期商品" }], total: 1 } }).catch(() => {}); }
    else if (q === "error") await route.fulfill({ status: 500 });
    else await route.fulfill({ json: { items: [product], total: 1 } });
  });
  await page.goto("/"); await page.keyboard.press("Control+k");
  const input = page.getByRole("textbox", { name: "搜索页面、功能或商品" });
  await input.fill("slow"); await page.waitForTimeout(350); await input.fill("fast");
  await expect(page.getByRole("button", { name: /便携风扇/ })).toBeVisible();
  await page.waitForTimeout(700); await expect(page.getByText("过期商品")).toHaveCount(0);
  await input.fill("error"); await expect(page.getByRole("alert")).toContainText("商品搜索失败");
});

test("search respects unsaved settings when navigation is cancelled", async ({ page }) => {
  await installApiMock(page, { competitors: [] });
  await page.goto("/"); await page.getByRole("button", { name: "系统设置", exact: true }).click();
  await page.getByLabel("我方店铺名称").fill("未保存的店铺");
  page.once("dialog", dialog => dialog.dismiss());
  await page.keyboard.press("Control+k");
  await page.getByRole("dialog", { name: "全局搜索" }).getByRole("button", { name: "竞品分组 页面" }).click();
  await expect(page.locator('main[data-page="settings"]')).toBeVisible();
  await expect(page.getByLabel("我方店铺名称")).toHaveValue("未保存的店铺");
});

test("compact layout remains usable at a narrow viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installApiMock(page, { competitors: [] });
  await page.goto("/");
  await page.getByRole("button", { name: /搜索页面、功能或商品/ }).click();
  const dialog = page.getByRole("dialog", { name: "全局搜索" });
  await expect(dialog).toBeVisible();
  await page.screenshot({ path: "test-results/workspace-search-mobile.png" });
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: /任务通知/ }).click();
  await expect(page.getByLabel("任务通知中心")).toBeVisible();
  await page.screenshot({ path: "test-results/workspace-notifications-mobile.png" });
});


test("add-links notification uses real terminal input counts", async ({ page }) => {
  const batchStatus = { status: "completed", task_id: "task-add", work_kind: "add_links", lifecycle_status: "terminal", batch_outcome_code: "partial_failure", runner_active: false, browser_open: false, input_progress: { total: 3, processed: 3, added: 1, business_rejected: 1, technical_failed: 1, not_executed: 0, remaining: 0 }, items: [] };
  await installApiMock(page, { competitors: [], batchStatus });
  await page.goto("/"); await page.getByRole("button", { name: /任务通知/ }).click();
  await expect(page.getByText("添加监控商品部分完成")).toBeVisible();
  await expect(page.getByText(/新增 1 · 业务拒绝 1 · 技术失败 1/)).toBeVisible();
});

test("running tasks do not notify until the polled terminal state", async ({ page }) => {
  await installApiMock(page, { competitors: [] });
  let finished = false;
  const running = { status: "running", task_id: "task-running", work_kind: "collect_products", lifecycle_status: "running", batch_outcome_code: null, total: 2, completed: 1, succeeded: 1, failed: 0, remaining: 1, runner_active: true, browser_open: false, items: [] };
  await page.route("**/api/competitors/collect-batch/status", route => route.fulfill({ json: finished ? { ...running, status: "completed", lifecycle_status: "terminal", batch_outcome_code: "success", completed: 2, succeeded: 2, remaining: 0, runner_active: false } : running }));
  await page.goto("/");
  const bell = page.getByRole("button", { name: /任务通知/ });
  await expect(bell).toHaveAttribute("aria-label", "任务通知，0 条未读");
  finished = true;
  await expect(bell).toHaveAttribute("aria-label", "任务通知，1 条未读", { timeout: 6000 });
  await bell.click(); await expect(page.getByText("竞品采集已完成")).toBeVisible();
});

test("add-links terminal state keeps polling until the runner exits on a non-dashboard page", async ({ page }) => {
  await installApiMock(page, { competitors: [] });
  let runnerActive = true;
  const terminal = { status: "completed", task_id: "task-transition", work_kind: "add_links", lifecycle_status: "terminal", batch_outcome_code: "success", browser_open: false, input_progress: { total: 1, processed: 1, added: 1, business_rejected: 0, technical_failed: 0, not_executed: 0, remaining: 0, anomaly_inputs: 0 }, items: [] };
  await page.route("**/api/competitors/collect-batch/status", route => route.fulfill({ json: { ...terminal, runner_active: runnerActive } }));
  await page.goto("/");
  const bell = page.getByRole("button", { name: /任务通知/ });
  await expect(bell).toHaveAttribute("aria-label", "任务通知，0 条未读");
  await page.waitForTimeout(500);
  runnerActive = false;
  await expect(bell).toHaveAttribute("aria-label", "任务通知，1 条未读", { timeout: 6000 });
  await bell.click();
  await expect(page.getByText("添加监控商品已完成")).toHaveCount(1);
  await page.reload();
  await expect(bell).toHaveAttribute("aria-label", "任务通知，1 条未读");
  await bell.click();
  await expect(page.getByText("添加监控商品已完成")).toHaveCount(1);
});
