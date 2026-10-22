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
  await page.goto("/");

  for (const width of [1366, 1600]) {
    await page.setViewportSize({ width, height: 1100 });
    const styles = [] as Record<string, string>[];
    const layouts = [] as { firstColumnWidth: number; checkboxLeft: number; checkboxToImage: number; imageToTitle: number; columns: { headerLeft: number; headerWidth: number; cellLeft: number; cellWidth: number }[] }[];
    for (const [label, expectedHeading] of [["竞品列表", "竞品列表"], ["我方商品", "我方商品"]]) {
      await page.getByRole("button", { name: label, exact: true }).click();
      await expect(page.getByRole("heading", { name: expectedHeading, exact: true })).toBeVisible();
      await expect(page.locator("tbody tr")).toHaveCount(10);
      await expect(page.getByRole("columnheader", { name: "操作", exact: true })).toHaveCount(0);
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
      layouts.push(await page.evaluate(() => {
        const rect = (element: Element) => element.getBoundingClientRect();
        const firstHeader = document.querySelector(".competitor-workspace thead th")!;
        const checkbox = document.querySelector(".competitor-workspace tbody input[type=checkbox]")!;
        const image = document.querySelector(".competitor-workspace tbody .product-image")!;
        const title = document.querySelector(".competitor-workspace tbody .competitor-title-link")!;
        const checkboxRect = rect(checkbox), imageRect = rect(image), titleRect = rect(title);
        return {
          firstColumnWidth: rect(firstHeader).width,
          checkboxLeft: checkboxRect.left,
          checkboxToImage: imageRect.left - checkboxRect.right,
          imageToTitle: titleRect.left - imageRect.right,
          columns: [...document.querySelectorAll(".competitor-workspace thead th")].map((header, index) => {
            const headerRect = rect(header), cellRect = rect(document.querySelectorAll(".competitor-workspace tbody tr:first-child td")[index]);
            return { headerLeft: headerRect.left, headerWidth: headerRect.width, cellLeft: cellRect.left, cellWidth: cellRect.width };
          }),
        };
      }));
      await page.screenshot({ path: testInfo.outputPath(`${width}-${label}.png`), fullPage: true });
    }
    expect(styles[1]).toEqual(styles[0]);
    expect(layouts[1]).toEqual(layouts[0]);
    expect(layouts[0].columns.every(column => Math.abs(column.headerLeft - column.cellLeft) < 0.5 && Math.abs(column.headerWidth - column.cellWidth) < 0.5)).toBe(true);
    console.info(`${width}px DOM geometry: ${JSON.stringify(layouts[0])}`);
  }

  await page.getByRole("button", { name: "我方商品 1", exact: true }).click();
  await expect(page.getByRole("heading", { name: "我方商品详情", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "返回我方商品", exact: true }).click();
  await expect(page.getByRole("heading", { name: "我方商品", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "我方商品 1", exact: true })).toBeVisible();

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
