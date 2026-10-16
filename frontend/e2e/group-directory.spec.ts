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

function makeGroups(total: number) {
  return Array.from({ length: total }, (_, index) => {
    const source = groups[index % groups.length];
    return { ...source, id: index + 1, name: `Group ${String.fromCharCode(65 + index)}`, competitor_count: total - index, active_count: Math.min(source.active_count, total - index), last_change_at: new Date(Date.UTC(2026, 9, 15 - index)).toISOString() };
  });
}

async function openDirectory(page: Page, dataGroups = groups) {
  let currentGroups = dataGroups;
  const mock = await installApiMock(page, { competitors: [], groups: dataGroups.map(({ id, name, created_at }) => ({ id, name, created_at })) });
  await page.route("**/api/competitor-groups/summary", route => route.fulfill({ json: { groups: currentGroups, unassigned: { competitor_count: 2, active_count: 1, price_min: null, price_max: null, changed_competitors_today: 0, last_change_at: null } } }));
  await page.route("**/api/competitor-groups/*/detail?*", route => {
    const id = Number(new URL(route.request().url()).pathname.split("/").at(-2));
    return route.fulfill({ json: { ...detail, group: { ...detail.group, id, name: dataGroups.find(group => group.id === id)!.name } } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "竞品分组", exact: true }).click();
  return { mock, setGroups: (next: typeof dataGroups) => { currentGroups = next; } };
}

test("directory search, filters, stable sorting, actions, and empty state work", async ({ page }) => {
  const { mock } = await openDirectory(page);
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

test("group name opens analysis and rename and delete prompts remain available", async ({ page }) => {
  const { mock } = await openDirectory(page);
  const detailRequests: number[] = [];
  page.on("request", request => {
    const match = new URL(request.url()).pathname.match(/\/api\/competitor-groups\/(\d+)\/detail$/);
    if (match) detailRequests.push(Number(match[1]));
  });
  await page.locator('[data-group-id="3"] .group-directory-name').click();
  await expect(page.getByRole("heading", { name: "Group C 竞争分析" })).toBeVisible();
  await page.getByRole("button", { name: "返回竞品分组" }).click();
  await expect(page.locator('[data-group-id="3"]').getByRole("button", { name: "组分析" })).toHaveCount(0);
  expect(detailRequests).toEqual([3]);
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
  await openDirectory(page, makeGroups(8));
  for (const width of [1440, 1600]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect(page.locator(".group-directory-table tbody tr")).toHaveCount(8);
    await expect(page.getByRole("button", { name: "清除筛选" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`competitor-groups-${width}.png`), fullPage: true });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.locator(".group-directory-table")).toBeVisible();
  await expect(page.locator('[data-group-id="1"]').getByRole("button", { name: "查看竞品" })).toBeVisible();
  await expect(page.locator('[data-group-id="1"]').getByRole("button", { name: "组分析" })).toHaveCount(0);
  await expect(page.locator(".group-unassigned-row")).toContainText("2 个商品尚未归入竞品组");
});

test("pagination follows filtered sorting, clears to page one, and excludes unassigned", async ({ page }) => {
  const { mock } = await openDirectory(page, makeGroups(8));
  await expect(page.locator(".group-directory-table tbody tr")).toHaveCount(8);
  await expect(page.locator(".pagination-bar")).toContainText("共 8 个竞品组");
  await expect(page.locator(".pagination-bar")).toContainText("第 1 / 1 页");
  await expect(page.getByRole("button", { name: "上一页" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "下一页" })).toBeDisabled();
  await mock.expectNoUnexpectedApi();
});

test("twelve groups page after sort, filter changes and clear reset page and controls", async ({ page }) => {
  const { mock } = await openDirectory(page, makeGroups(12));
  const ids = () => page.locator(".group-directory-table tbody tr").evaluateAll(rows => rows.map(row => Number(row.getAttribute("data-group-id"))));
  await expect(page.locator(".group-directory-table tbody tr")).toHaveCount(10);
  await expect(page.locator(".pagination-bar")).toContainText("共 12 个竞品组");
  await page.getByLabel("分组排序").selectOption("count");
  await page.getByRole("button", { name: "下一页" }).click();
  expect(await ids()).toEqual([11, 12]);
  await expect(page.locator(".pagination-bar")).toContainText("第 2 / 2 页");
  await page.getByRole("textbox", { name: "搜索竞品组" }).fill("Group A");
  await expect(page.locator(".group-directory-table tbody tr")).toHaveCount(1);
  await expect(page.locator(".pagination-bar")).toContainText("共 1 个竞品组");
  await expect(page.locator(".pagination-bar")).toContainText("第 1 / 1 页");
  await page.getByRole("textbox", { name: "搜索竞品组" }).fill("Group B");
  await page.getByLabel("分组筛选").selectOption("changed");
  await expect(page.locator(".pagination-bar")).toContainText("共 0 个竞品组");
  await expect(page.getByRole("button", { name: "清除筛选" })).toBeVisible();
  await page.getByLabel("分组排序").selectOption("name");
  await page.getByRole("button", { name: "清除筛选" }).click();
  await expect(page.getByRole("textbox", { name: "搜索竞品组" })).toHaveValue("");
  await expect(page.getByLabel("分组筛选")).toHaveValue("all");
  await expect(page.getByLabel("分组排序")).toHaveValue("recent");
  await expect(page.locator(".pagination-bar")).toContainText("第 1 / 2 页");
  await expect(page.locator(".group-directory-table tbody tr")).toHaveCount(10);
  await mock.expectNoUnexpectedApi();
});

test("deleting the last group on page two reduces total pages and returns to page one", async ({ page }) => {
  const dataGroups = makeGroups(11);
  const { mock, setGroups } = await openDirectory(page, dataGroups);
  await page.getByRole("button", { name: "下一页" }).click();
  await expect(page.locator("[data-group-id='11']")).toBeVisible();
  await page.route("**/api/competitor-groups/11", async route => {
    if (route.request().method() === "DELETE") {
      setGroups(dataGroups.slice(0, 10));
      await route.fulfill({ status: 200, json: { id: 11 } });
    } else await route.continue();
  });
  const row = page.locator("[data-group-id='11']");
  await row.getByRole("button", { name: "更多" }).click();
  await page.getByRole("menuitem", { name: "删除竞品组" }).click();
  await page.getByRole("button", { name: "删除竞品组" }).click();
  await expect(page.locator(".pagination-bar")).toContainText("共 10 个竞品组");
  await expect(page.locator(".pagination-bar")).toContainText("第 1 / 1 页");
  await expect(page.locator(".group-directory-table tbody tr")).toHaveCount(10);
  await expect(page.locator(".group-unassigned-row")).toContainText("2 个商品尚未归入竞品组");
  await mock.expectNoUnexpectedApi();
});
