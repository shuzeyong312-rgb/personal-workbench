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

test("B: preserves active selections across pages and disables inactive rows", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: competitors23 });
  await openCompetitorList(page);
  await page.getByRole("checkbox", { name: "选择 搜索目标竞品 01" }).check();
  await expect(page.getByRole("checkbox", { name: "选择 固定竞品 07" })).toBeDisabled();
  await page.getByRole("button", { name: "下一页" }).click();
  await page.getByRole("checkbox", { name: "选择 固定竞品 11" }).check();
  await expect(page.getByRole("button", { name: /采集选中（2）/ }).first()).toBeVisible();
  await page.getByRole("button", { name: "上一页" }).click();
  await expect(page.getByRole("checkbox", { name: "选择 搜索目标竞品 01" })).toBeChecked();
  await mock.expectNoUnexpectedApi();
});

test("C: selects and clears only the current page", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: competitors23 });
  await openCompetitorList(page);
  await page.getByRole("checkbox", { name: "全选当前页可采集竞品" }).check();
  await page.getByRole("button", { name: "下一页" }).click();
  await page.getByRole("checkbox", { name: "选择 固定竞品 11" }).check();
  await page.getByRole("button", { name: "上一页" }).click();
  await page.getByRole("checkbox", { name: "全选当前页可采集竞品" }).uncheck();
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
  await expect(page.getByRole("button", { name: /采集选中（0）/ }).first()).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "选择 搜索目标竞品 01" })).not.toBeChecked();
  await mock.expectNoUnexpectedApi();
});

test("fail-closed: an undeclared API is blocked and reported", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: competitors23 });
  await page.goto("/");
  await expect(page.evaluate(() => fetch("/api/not-mocked"))).rejects.toThrow("Failed to fetch");
  await expect.poll(() => mock.unexpected).toContain("GET /api/not-mocked");
  expect(mock.unexpected).toEqual(["GET /api/not-mocked"]);
});
