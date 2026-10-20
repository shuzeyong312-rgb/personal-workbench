import { expect, test } from "@playwright/test";
import { installApiMock } from "./support/api-mock";

test("preserves monitoring expansion across page navigation and opens placeholders", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [] });
  await page.goto("/");

  const monitoringToggle = page.getByRole("button", { name: "竞品监控", exact: true });
  await expect(monitoringToggle).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("navigation", { name: "主导航", exact: true }).getByRole("button", { name: "竞品监控大屏", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "首页", exact: true }).click();
  await expect(page.getByRole("heading", { name: "首页", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "进入竞品监控大屏" })).toBeVisible();
  await expect(monitoringToggle).toHaveAttribute("aria-expanded", "true");

  await monitoringToggle.click();
  await expect(monitoringToggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("navigation", { name: "主导航", exact: true }).getByRole("button", { name: "竞品监控大屏", exact: true })).toBeHidden();
  await expect(monitoringToggle).toHaveAttribute("aria-expanded", "false");

  await page.route("**/api/product-library/products?*", route => route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 20 } }));
  await page.route("**/api/product-library/manufacturers", route => route.fulfill({ json: { items: [] } }));
  await page.getByRole("button", { name: "产品库", exact: true }).click();
  await expect(page.getByRole("heading", { name: "产品库", exact: true })).toBeVisible();
  await expect(page.getByText("没有符合条件的产品")).toBeVisible();
  await expect(monitoringToggle).toHaveAttribute("aria-expanded", "false");
  for (const moduleName of ["AI智能助手", "全网比价", "自动询价", "自动上架"] as const) {
    await page.getByRole("button", { name: moduleName, exact: true }).click();
    await expect(page.getByRole("heading", { name: moduleName, exact: true })).toBeVisible();
    await expect(page.getByText(`${moduleName}模块已预留`, { exact: true })).toBeVisible();
    await expect(monitoringToggle).toHaveAttribute("aria-expanded", "false");
  }

  await page.getByRole("button", { name: "系统设置", exact: true }).click();
  await expect(page.getByRole("heading", { name: "系统设置", exact: true })).toBeVisible();
  await expect(monitoringToggle).toHaveAttribute("aria-expanded", "false");

  await monitoringToggle.click();
  await expect(monitoringToggle).toHaveAttribute("aria-expanded", "true");
  await page.getByRole("button", { name: "采集记录" }).click();
  await expect(page.getByRole("heading", { name: "采集记录", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "采集记录" })).toBeVisible();
  await expect(monitoringToggle).toHaveAttribute("aria-expanded", "true");

  await mock.expectNoUnexpectedApi();
});
