import { expect, test } from "@playwright/test";
import { makeCompetitor } from "./fixtures/competitors";
import { installApiMock } from "./support/api-mock";

const competitors = Array.from({ length: 23 }, (_, index) => makeCompetitor(index + 1, {
  title: `对照商品 ${index + 1}`,
  group_id: index % 2 ? 19 : null,
  status: index === 2 ? "offline" : index === 4 ? "unknown" : "active",
  is_active: index !== 6,
  last_collected_at: index % 3 ? "2026-10-19T08:30:00Z" : null,
}));
const ownProducts = competitors.map((product, index) => ({
  ...product,
  id: product.id + 100,
  offer_id: `own-${product.offer_id}`,
  ownership: "self" as const,
  title: `我方商品 ${index + 1}`,
}));

test("own products share competitor list presentation and preserve own-product controls", async ({ page }, testInfo) => {
  const mock = await installApiMock(page, {
    competitors: [...competitors, ...ownProducts],
    groups: [{ id: 19, name: "A19", created_at: "2026-09-01T00:00:00Z" }],
  });
  await page.setViewportSize({ width: 1600, height: 1100 });
  await page.goto("/");

  const styles = [] as Record<string, string>[];
  for (const [label, expectedHeading] of [["竞品列表", "竞品列表"], ["我方商品", "我方商品"]]) {
    await page.getByRole("button", { name: label, exact: true }).click();
    await expect(page.getByRole("heading", { name: expectedHeading, exact: true })).toBeVisible();
    await expect(page.locator("tbody tr")).toHaveCount(10);
    styles.push(await page.evaluate(() => {
      const read = (selector: string, property: string) => getComputedStyle(document.querySelector(selector)!).getPropertyValue(property);
      return {
        heading: read(".page-header h1", "font-size"),
        workspaceBorder: read(".competitor-workspace", "border-color"),
        filterHeight: read(".filter-field input", "height"),
        filterSurface: read(".filter-field input", "background-color"),
        tableHeader: read(".competitor-workspace th", "background-color"),
        tableText: read(".competitor-workspace td", "font-size"),
        statusShape: read(".status-badge", "border-radius"),
        pageButton: read(".pagination-bar button", "border-radius"),
      };
    }));
    await page.screenshot({ path: testInfo.outputPath(`${label}.png`), fullPage: true });
  }
  expect(styles[1]).toEqual(styles[0]);

  await page.getByRole("textbox", { name: "搜索商品名称 / offerId / 店铺" }).fill("我方商品 13");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await expect(page.locator("tbody tr")).toContainText("我方商品 13");
  await page.getByRole("button", { name: "重置", exact: true }).click();
  await page.getByLabel("商品状态", { exact: true }).selectOption("offline");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await page.getByRole("button", { name: "重置", exact: true }).click();
  await page.getByLabel("竞品组", { exact: true }).selectOption("19");
  await expect(page.locator("tbody tr")).toHaveCount(10);
  await page.getByRole("button", { name: "重置", exact: true }).click();
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(page.getByText("第 2 / 3 页")).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(10);

  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("我方商品-窄屏.png"), fullPage: true });
  await mock.expectNoUnexpectedApi();
});
