import { expect, test, type Page } from "@playwright/test";
import { installApiMock } from "./support/api-mock";
import { detail } from "./fixtures/group-position";

const groups = [
  { id: 1, name: "Group A", created_at: "2026-10-01T00:00:00Z", competitor_count: 3, active_count: 3, price_min: "34.00", price_max: "40.00", changed_competitors_today: 2, last_change_at: "2026-10-14T10:00:00Z", own_product: { id: 101, offer_id: "101", title: "Portable Warmer Long Product Name That Must Stay In Its Column", shop_name: null, main_image_url: null, status: "active", is_active: true } },
  { id: 2, name: "Group B", created_at: "2026-10-01T00:00:00Z", competitor_count: 8, active_count: 8, price_min: "9.00", price_max: "20.00", changed_competitors_today: 0, last_change_at: "2026-10-13T10:00:00Z", own_product: null },
  { id: 3, name: "Group C", created_at: "2026-10-01T00:00:00Z", competitor_count: 3, active_count: 1, price_min: null, price_max: null, changed_competitors_today: 0, last_change_at: null, own_product: null },
  { id: 4, name: "Group D", created_at: "2026-10-01T00:00:00Z", competitor_count: 2, active_count: 1, price_min: "10.00", price_max: null, changed_competitors_today: 1, last_change_at: null, own_product: null },
  { id: 5, name: "Group E", created_at: "2026-10-01T00:00:00Z", competitor_count: 6, active_count: 6, price_min: "20.00", price_max: "30.00", changed_competitors_today: 1, last_change_at: "2026-10-12T10:00:00Z", own_product: null },
  { id: 6, name: "Group F", created_at: "2026-10-01T00:00:00Z", competitor_count: 4, active_count: 2, price_min: null, price_max: null, changed_competitors_today: 0, last_change_at: null, own_product: null },
];

async function openDirectory(page: Page) {
  const mock = await installApiMock(page, { competitors: [], groups: groups.map(({ id, name, created_at }) => ({ id, name, created_at })) });
  await page.route("**/api/competitor-groups/summary", route => route.fulfill({ json: { groups, unassigned: { competitor_count: 2, active_count: 1, price_min: null, price_max: null, changed_competitors_today: 0, last_change_at: null } } }));
  await page.route("**/api/competitor-groups/*/detail?*", route => {
    const id = Number(new URL(route.request().url()).pathname.split("/").at(-2));
    return route.fulfill({ json: { ...detail, group: { ...detail.group, id, name: groups.find(group => group.id === id)!.name } } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "竞品分组", exact: true }).click();
  return mock;
}

test("directory search, filters, stable sorting, actions, and empty state work", async ({ page }) => {
  const mock = await openDirectory(page);
  const ids = () => page.locator(".group-directory-table tbody tr").evaluateAll(rows => rows.map(row => Number(row.getAttribute("data-group-id"))));
  await expect(page.locator(".group-directory-table tbody tr")).toHaveCount(6);
  await expect(page.locator(".group-directory-summary")).toHaveText("6 个商品组 · 28 个竞品 · 22 个监控中");
  await expect(page.locator('[data-group-id="2"]')).toContainText("8/8");
  await expect(page.locator('[data-group-id="3"]')).toContainText("1/3");
  await expect(page.locator('[data-group-id="3"]')).toContainText("已停止 2 个");
  await expect(page.locator('[data-group-id="1"]')).toContainText("Portable Warmer Long Product Name");
  await expect(page.locator('[data-group-id="2"]')).toContainText("尚未绑定");
  expect(await ids()).toEqual([1, 2, 5, 3, 4, 6]);

  await page.getByRole("textbox", { name: "搜索竞品组" }).fill("portable warmer");
  await expect(page.locator(".group-directory-table tbody tr")).toHaveCount(1);
  await expect(page.locator(".group-directory-table tbody tr").first()).toHaveAttribute("data-group-id", "1");
  await page.getByRole("button", { name: "清除筛选" }).click();
  await page.getByRole("textbox", { name: "搜索竞品组" }).fill("group c");
  await expect(page.locator(".group-directory-table tbody tr")).toHaveCount(1);
  await page.getByRole("textbox", { name: "搜索竞品组" }).fill("not found");
  await expect(page.getByText("没有符合条件的竞品组")).toBeVisible();
  await page.getByRole("button", { name: "清除筛选" }).click();
  await expect(page.locator(".group-directory-table tbody tr")).toHaveCount(6);

  await page.getByLabel("分组筛选").selectOption("changed");
  expect(await ids()).toEqual([1, 5, 4]);
  await page.getByLabel("分组筛选").selectOption("incomplete");
  expect(await ids()).toEqual([3, 4, 6]);
  await page.getByLabel("分组筛选").selectOption("all");
  await page.getByLabel("分组排序").selectOption("count");
  expect(await ids()).toEqual([2, 5, 6, 1, 3, 4]);
  await page.getByLabel("分组排序").selectOption("name");
  expect(await ids()).toEqual([1, 2, 3, 4, 5, 6]);
  await page.getByLabel("分组排序").selectOption("recent");
  expect(await ids()).toEqual([1, 2, 5, 3, 4, 6]);

  await page.locator('[data-group-id="3"]').getByRole("button", { name: "查看竞品" }).click();
  await expect(page.getByRole("heading", { name: "竞品列表" })).toBeVisible();
  await expect(page.getByLabel("竞品组")).toHaveValue("3");
  await mock.expectNoUnexpectedApi();
});

test("group analysis, rename and delete prompts remain available", async ({ page }) => {
  const mock = await openDirectory(page);
  const detailRequests: number[] = [];
  page.on("request", request => {
    const match = new URL(request.url()).pathname.match(/\/api\/competitor-groups\/(\d+)\/detail$/);
    if (match) detailRequests.push(Number(match[1]));
  });
  await page.locator('[data-group-id="3"] .group-directory-name').click();
  await expect(page.getByRole("heading", { name: "Group C 竞争分析" })).toBeVisible();
  await page.getByRole("button", { name: "返回竞品分组" }).click();
  await page.locator('[data-group-id="3"]').getByRole("button", { name: "组分析" }).click();
  await expect(page.getByRole("heading", { name: "Group C 竞争分析" })).toBeVisible();
  expect(detailRequests).toEqual([3, 3]);
  await page.getByRole("button", { name: "竞品分组", exact: true }).click();
  await page.getByRole("button", { name: "新增竞品组" }).click();
  await expect(page.getByRole("dialog")).toContainText("新增竞品组");
  await page.getByRole("button", { name: "取消" }).click();
  const row = page.locator('[data-group-id="3"]');
  await row.getByRole("button", { name: "更多" }).click();
  await page.getByRole("menuitem", { name: "重命名竞品组" }).click();
  await expect(page.getByRole("dialog")).toContainText("重命名竞品组");
  await page.getByRole("button", { name: "取消" }).click();
  await row.getByRole("button", { name: "更多" }).click();
  await page.getByRole("menuitem", { name: "删除竞品组" }).click();
  await expect(page.getByRole("dialog")).toContainText("删除竞品组");
  await page.getByRole("button", { name: "取消" }).click();
  await mock.expectNoUnexpectedApi();
});

test("wide desktop screenshots and narrow layout keep the directory usable", async ({ page }, testInfo) => {
  await openDirectory(page);
  for (const width of [1440, 1600]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect(page.locator(".group-directory-table tbody tr")).toHaveCount(6);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`competitor-groups-${width}.png`), fullPage: true });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.locator(".group-directory-table")).toBeVisible();
  await expect(page.locator('[data-group-id="1"]').getByRole("button", { name: "查看竞品" })).toBeVisible();
  await expect(page.locator('[data-group-id="1"]').getByRole("button", { name: "组分析" })).toBeHidden();
  await expect(page.locator(".group-unassigned-row")).toContainText("2 个商品尚未归入竞品组");
});
