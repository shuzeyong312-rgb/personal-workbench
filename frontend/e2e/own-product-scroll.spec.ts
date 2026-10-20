import { expect, test } from "@playwright/test";
import { makeCompetitor } from "./fixtures/competitors";
import { installApiMock } from "./support/api-mock";

test("own products scroll to the last row without shrinking the table", async ({ page }) => {
  const products = Array.from({ length: 10 }, (_, index) => makeCompetitor(index + 1, { ownership: "self" }));
  const mock = await installApiMock(page, { competitors: products });
  await page.setViewportSize({ width: 1920, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "我方商品", exact: true }).click();
  await expect(page.locator("tbody tr")).toHaveCount(10);
  const main = page.locator("main");
  expect(await main.evaluate(el => el.scrollHeight > el.clientHeight)).toBe(true);
  await main.hover();
  await page.mouse.wheel(0, 1800);
  await expect.poll(() => main.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
  await expect(page.getByRole("checkbox", { name: `选择 ${products[9].title}`, exact: true })).toBeInViewport();
  await expect(page.getByRole("button", { name: "下一页", exact: true })).toBeInViewport();
  await mock.expectNoUnexpectedApi();
});
