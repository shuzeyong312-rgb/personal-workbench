import { expect, test, type Page } from "@playwright/test";
import { competitors23 } from "./fixtures/competitors";
import { installApiMock } from "./support/api-mock";

async function openCompetitorList(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "竞品列表" }).click();
  await expect(page.getByRole("heading", { name: "竞品列表" })).toBeVisible();
  await expect(page.getByText("共 23 个竞品").first()).toBeVisible();
}

test("A: paginates 23 competitors with correct boundaries and rows", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: competitors23 });
  await openCompetitorList(page);
  await expect(page.getByText("第 1 / 3 页")).toBeVisible();
  await expect(page.getByText("搜索目标竞品 01")).toBeVisible();
  await expect(page.getByText("固定竞品 10")).toBeVisible();
  await expect(page.getByText("固定竞品 11")).not.toBeVisible();
  await expect(page.getByRole("button", { name: "上一页" })).toBeDisabled();
  await page.getByRole("button", { name: "下一页" }).click();
  await expect(page.getByText("第 2 / 3 页")).toBeVisible();
  await expect(page.getByText("固定竞品 11")).toBeVisible();
  await expect(page.getByText("固定竞品 20")).toBeVisible();
  await expect(page.getByText("固定竞品 10")).not.toBeVisible();
  await page.getByRole("button", { name: "下一页" }).click();
  await expect(page.getByText("第 3 / 3 页")).toBeVisible();
  await expect(page.getByText("固定竞品 23")).toBeVisible();
  await expect(page.getByRole("button", { name: "下一页" })).toBeDisabled();
  await mock.expectNoUnexpectedApi();
});

test("B: preserves generic selections across pages and allows inactive rows", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: competitors23 });
  await openCompetitorList(page);
  await page.getByRole("checkbox", { name: "选择 搜索目标竞品 01" }).check();
  await page.getByRole("checkbox", { name: "选择 固定竞品 07" }).check();
  await page.getByRole("button", { name: "下一页" }).click();
  await page.getByRole("checkbox", { name: "选择 固定竞品 11" }).check();
  await expect(page.getByRole("button", { name: /批量操作（3）/ }).first()).toBeVisible();
  await page.getByRole("button", { name: "上一页" }).click();
  await expect(page.getByRole("checkbox", { name: "选择 搜索目标竞品 01" })).toBeChecked();
  await mock.expectNoUnexpectedApi();
});

test("C: selects and clears only the current page", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: competitors23 });
  await openCompetitorList(page);
  await page.getByRole("checkbox", { name: "全选当前页全部商品" }).check();
  await page.getByRole("button", { name: "下一页" }).click();
  await page.getByRole("checkbox", { name: "选择 固定竞品 11" }).check();
  await page.getByRole("button", { name: "上一页" }).click();
  await page.getByRole("checkbox", { name: "全选当前页全部商品" }).uncheck();
  await page.getByRole("button", { name: "下一页" }).click();
  await expect(page.getByRole("checkbox", { name: "选择 固定竞品 11" })).toBeChecked();
  await mock.expectNoUnexpectedApi();
});

test("D: search resets to page one and clears hidden selections", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: competitors23 });
  await openCompetitorList(page);
  await page.getByRole("button", { name: "下一页" }).click();
  await page.getByRole("checkbox", { name: "选择 固定竞品 11" }).check();
  await page.getByRole("textbox", { name: "搜索商品名称 / offerId / 店铺" }).fill("搜索目标");
  await expect(page.getByText("第 1 / 1 页")).toBeVisible();
  await expect(page.getByText("共 1 个竞品").first()).toBeVisible();
  await expect(page.getByRole("button", { name: /批量操作（0）/ }).first()).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "选择 搜索目标竞品 01" })).not.toBeChecked();
  await mock.expectNoUnexpectedApi();
});

test("E: batch group assignment excludes own and refreshes the list", async ({ page }) => {
  const competitors = competitors23.map((competitor) => competitor.id === 3 ? { ...competitor, group_role: "own" as const } : competitor);
  const mock = await installApiMock(page, { competitors, groups: [{ id: 19, name: "A19", created_at: "2026-09-01T00:00:00Z" }] });
  await openCompetitorList(page);
  await page.getByRole("checkbox", { name: "选择 搜索目标竞品 01" }).check();
  await page.getByRole("checkbox", { name: "选择 固定竞品 03" }).check();
  await page.getByRole("button", { name: /批量操作（2）/ }).click();
  await page.getByRole("menuitem", { name: "设置分组（1）" }).click();
  await expect(page.getByRole("dialog")).toContainText("本次修改 1 个直接竞品");
  await expect(page.getByRole("dialog")).toContainText("1 个我方商品不会参与本次批量分组");
  await expect(page.getByRole("button", { name: "确认设置" })).toBeDisabled();
  await page.getByLabel("目标竞品组").selectOption("19");
  await expect(page.getByRole("button", { name: "确认设置" })).toBeEnabled();
  const patchRequest = page.waitForRequest((request) => request.method() === "PATCH" && request.url().endsWith("/api/competitors/group-batch"));
  await page.getByRole("button", { name: "确认设置" }).click();
  expect((await patchRequest).postDataJSON()).toEqual({ competitor_ids: [1], group_id: 19 });
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(page.getByRole("checkbox", { name: "选择 搜索目标竞品 01" })).not.toBeChecked();
  await expect(page.locator("tbody td").filter({ hasText: "A19" }).last()).toBeVisible();
  await mock.expectNoUnexpectedApi();
});

test("F: batch stop sends active selected IDs and refreshes monitoring state", async ({ page }) => {
  const competitors = competitors23.map((competitor) => competitor.id === 3 ? { ...competitor, group_role: "own" as const } : competitor);
  const mock = await installApiMock(page, { competitors });
  await openCompetitorList(page);
  await page.getByRole("checkbox", { name: "选择 搜索目标竞品 01" }).check();
  await page.getByRole("checkbox", { name: "选择 固定竞品 03" }).check();
  await page.getByRole("button", { name: /批量操作（2）/ }).click();
  await page.getByRole("menuitem", { name: "停止监控（2）" }).click();
  await expect(page.getByRole("dialog")).toContainText("停止监控 2 个商品");
  const patchRequest = page.waitForRequest((request) => request.method() === "PATCH" && request.url().endsWith("/api/competitors/monitoring-batch"));
  await page.getByRole("button", { name: "确认停止" }).click();
  expect((await patchRequest).postDataJSON()).toEqual({ competitor_ids: [1, 3], is_active: false });
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(page.locator("tr").filter({ hasText: "搜索目标竞品 01" }).getByText("已停止")).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "选择 搜索目标竞品 01" })).not.toBeChecked();
  await expect(page.getByRole("checkbox", { name: "选择 固定竞品 03" })).not.toBeChecked();
  await mock.expectNoUnexpectedApi();
});

test("G: batch delete excludes own and removes eligible competitors", async ({ page }) => {
  const competitors = competitors23.map((competitor) => competitor.id === 3 ? { ...competitor, group_role: "own" as const, group_id: 19 } : competitor);
  const mock = await installApiMock(page, { competitors });
  await openCompetitorList(page);
  await page.getByRole("checkbox", { name: "选择 搜索目标竞品 01" }).check();
  await page.getByRole("checkbox", { name: "选择 固定竞品 03" }).check();
  await page.getByRole("button", { name: /批量操作（2）/ }).click();
  await page.getByRole("menuitem", { name: "删除竞品（1）" }).click();
  await expect(page.getByRole("dialog")).toContainText("本次将永久删除 1 个直接竞品");
  await expect(page.getByRole("dialog")).toContainText("1 个我方商品不会参与批量删除");
  const deleteRequest = page.waitForRequest((request) => request.method() === "POST" && request.url().endsWith("/api/competitors/delete-batch"));
  await page.getByRole("button", { name: "永久删除 1 个竞品" }).click();
  expect((await deleteRequest).postDataJSON()).toEqual({ competitor_ids: [1] });
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(page.getByText("搜索目标竞品 01")).not.toBeVisible();
  await expect(page.getByText("固定竞品 03")).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "选择 固定竞品 03" })).not.toBeChecked();
  await mock.expectNoUnexpectedApi();
});

test("fail-closed: an undeclared API is blocked and reported", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: competitors23 });
  await page.goto("/");
  await expect(page.evaluate(() => fetch("/api/not-mocked"))).rejects.toThrow("Failed to fetch");
  await expect.poll(() => mock.unexpected).toContain("GET /api/not-mocked");
  expect(mock.unexpected).toEqual(["GET /api/not-mocked"]);
});
