import { expect, test } from "@playwright/test";
import { installApiMock } from "./support/api-mock";

test("group and collection pages show loading, then real empty states", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [], groups: [{ id: 1, name: "A19", created_at: "2026-10-01T00:00:00Z" }] });
  let releaseGroups!: () => void;
  const groupGate = new Promise<void>(resolve => { releaseGroups = resolve; });
  await page.route("**/api/competitor-groups/summary", async route => {
    await groupGate;
    await route.fulfill({ json: { groups: [{ id: 1, name: "A19", created_at: "2026-10-01T00:00:00Z", competitor_count: 0, active_count: 0, price_min: null, price_max: null, changed_competitors_today: 0, last_change_at: null, own_product: null }], unassigned: { competitor_count: 0, active_count: 0, price_min: null, price_max: null, changed_competitors_today: 0, last_change_at: null } } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "竞品分组", exact: true }).click();
  await expect(page.getByText("正在加载竞品组…", { exact: true })).toBeVisible();
  releaseGroups();
  await expect(page.locator(".group-directory-card")).toHaveCount(1);

  let releaseHistory!: () => void;
  const historyGate = new Promise<void>(resolve => { releaseHistory = resolve; });
  await page.route("**/api/collection-batches?*", async route => {
    await historyGate;
    await route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 20 } });
  });
  await page.getByRole("button", { name: "采集记录", exact: true }).click();
  await expect(page.getByText("正在加载采集记录…", { exact: true })).toBeVisible();
  releaseHistory();
  await expect(page.getByText("暂无符合条件的采集记录，可清除筛选后重试。", { exact: true })).toBeVisible();
  await mock.expectNoUnexpectedApi();
});

test("competitor groups recover from an API error to the actionable empty state", async ({ page }) => {
  let fail = true;
  const mock = await installApiMock(page, { competitors: [] });
  await page.route("**/api/competitor-groups/summary", route => fail
    ? route.fulfill({ status: 503, json: { detail: "controlled failure" } })
    : route.fulfill({ json: { groups: [], unassigned: { competitor_count: 0, active_count: 0, price_min: null, price_max: null, changed_competitors_today: 0, last_change_at: null } } }));
  await page.goto("/");
  await page.getByRole("button", { name: "竞品分组", exact: true }).click();
  await expect(page.getByText("加载失败", { exact: true })).toBeVisible();
  await expect(page.getByText("暂时无法获取竞品组，请检查服务是否正常运行。", { exact: true })).toBeVisible();
  fail = false;
  await page.getByRole("button", { name: "重试", exact: true }).click();
  await expect(page.getByText("还没有竞品组", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "新增竞品组" }).last()).toBeVisible();
  await mock.expectNoUnexpectedApi();
});
