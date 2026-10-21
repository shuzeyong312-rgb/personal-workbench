import { expect, test } from "@playwright/test";
import { installApiMock } from "./support/api-mock";

test("group name modal contains keyboard focus, blocks background and restores its opener", async ({ page }) => {
  await installApiMock(page, { competitors: [] });
  await page.goto("/");
  await page.locator(".workspace-sidebar").getByRole("button", { name: "竞品分组", exact: true }).click();
  const opener = page.locator("header").getByRole("button", { name: "新增竞品组", exact: true });
  await opener.click();
  const dialog = page.getByRole("dialog", { name: "新增竞品组" });
  await expect(dialog.getByLabel("竞品组名称")).toBeFocused();
  await dialog.getByLabel("竞品组名称").fill("Keyboard group");
  await dialog.getByRole("button", { name: "关闭", exact: true }).focus();
  await page.keyboard.press("Shift+Tab");
  await expect(dialog.getByRole("button", { name: "新增竞品组", exact: true })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(dialog.getByRole("button", { name: "关闭", exact: true })).toBeFocused();
  await page.locator(".workspace-sidebar").getByRole("button", { name: "首页", exact: true }).evaluate(node => node.focus());
  expect(await dialog.evaluate(node => node.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
});

test("group name modal stays open during save and restores focus after server failure", async ({ page }) => {
  await installApiMock(page, { competitors: [] });
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/competitor-groups", async route => {
    if (route.request().method() !== "POST") return route.fallback();
    await gate;
    await route.fulfill({ status: 503, json: { message: "保存暂时失败" } });
  });
  try {
    await page.goto("/");
    await page.locator(".workspace-sidebar").getByRole("button", { name: "竞品分组", exact: true }).click();
    const opener = page.locator("header").getByRole("button", { name: "新增竞品组", exact: true });
    await opener.click();
    const dialog = page.getByRole("dialog", { name: "新增竞品组" });
    await dialog.getByLabel("竞品组名称").fill("Pending");
    await dialog.getByRole("button", { name: "新增竞品组", exact: true }).click();
    await expect(dialog.getByRole("button", { name: "保存中…" })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeVisible();
    release();
    await expect(dialog.getByRole("alert")).toContainText("保存暂时失败");
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(opener).toBeFocused();
  } finally { release(); }
});

for (const oldFailure of [false, true]) {
  test(`dashboard ignores stale ${oldFailure ? "failed" : "successful"} responses for both summary endpoints`, async ({ page }) => {
    await installApiMock(page, { competitors: [] });
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const requests = { attention: 0, today: 0 };
    const completed = { attention: false, today: false };
    for (const kind of ["attention", "today"] as const) {
      await page.route(`**/api/dashboard/${kind === "attention" ? "group-attention" : "today"}`, async route => {
        const ordinal = ++requests[kind];
        if (ordinal <= 2) await gate;
        if (ordinal <= 2 && oldFailure) await route.fulfill({ status: 503, json: { message: "旧请求失败" } });
        else if (kind === "attention") await route.fulfill({ json: { date: "2026-10-21", kpis: { monitored_product_groups: ordinal <= 2 ? 1 : 7, changed_product_groups_today: 0, changed_competitors_today: 0 }, groups: [] } });
        else await route.fulfill({ json: { date: "2026-10-21", stats: { active_monitored_products: 0, monitored_competitors: 0, changed_competitors: 0, change_events: 0, price_changed_competitors: 0, stock_changed_competitors: 0, sku_changed_competitors: 0, failed_collections: ordinal <= 2 ? 1 : 7 }, items: [], collection_summary: { last_collection_at: null, success_runs: 0, failed_runs: 0, average_duration_seconds: null }, trend_7d: [] } });
        if (ordinal <= 2) completed[kind] = true;
      });
    }
    try {
      await page.goto("/");
      await expect.poll(() => requests.attention + requests.today).toBe(4);
      await page.locator(".workspace-sidebar").getByRole("button", { name: "竞品监控大屏", exact: true }).click();
      const stats = page.getByLabel("商品组关注统计");
      await expect(stats.locator("strong")).toHaveText(["7", "0", "0", "7"]);
      release();
      await expect.poll(() => completed.attention && completed.today).toBe(true);
      await page.getByRole("button", { name: "添加监控商品", exact: true }).click();
      await page.getByRole("dialog").getByRole("button", { name: "关闭", exact: true }).click();
      await expect(stats.locator("strong")).toHaveText(["7", "0", "0", "7"]);
      await expect(page.getByText("暂时无法获取商品组关注信息。", { exact: true })).toHaveCount(0);
      await expect(page.getByText("暂时无法获取今日变化，请检查服务是否正常运行。", { exact: true })).toHaveCount(0);
    } finally { release(); }
  });
}

test("a superseded group deletion refresh is a no-op, not a false failure notice", async ({ page }) => {
  const group = { id: 1, name: "Audit group", created_at: "2026-10-21T00:00:00Z", competitor_count: 0, active_count: 0, price_min: null, price_max: null, changed_competitors_today: 0, last_change_at: null, own_product: null };
  await installApiMock(page, { competitors: [], groups: [group] });
  let deleted = false;
  await page.route("**/api/competitor-groups/summary", route => route.fulfill({ json: { groups: deleted ? [] : [group], unassigned: { competitor_count: 0, active_count: 0, price_min: null, price_max: null, changed_competitors_today: 0, last_change_at: null } } }));
  await page.route("**/api/competitor-groups/1", route => { deleted = true; return route.fulfill({ status: 204 }); });
  let hold = false;
  let held = 0;
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/dashboard/**", async route => {
    if (hold) { held++; await gate; }
    await route.fallback();
  });
  try {
    await page.goto("/");
    await page.locator(".workspace-sidebar").getByRole("button", { name: "竞品分组", exact: true }).click();
    await page.locator('[data-group-id="1"]').getByRole("button", { name: "更多" }).click();
    await page.getByRole("menuitem", { name: "删除竞品组" }).click();
    hold = true;
    await page.getByRole("dialog").getByRole("button", { name: "删除竞品组", exact: true }).click();
    await expect.poll(() => held).toBe(2);
    hold = false;
    await page.locator(".workspace-sidebar").getByRole("button", { name: "竞品监控大屏", exact: true }).click();
    await expect(page.getByRole("heading", { name: "今日需要关注的商品组" })).toBeVisible();
    release();
    await expect(page.locator(".toast")).toContainText("竞品组已删除，竞品已移至未分组。");
    await expect(page.locator(".toast")).not.toContainText("刷新失败");
  } finally { release(); }
});
