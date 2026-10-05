import { expect, test } from "@playwright/test";
import { installApiMock } from "./support/api-mock";

test("uses consistent module navigation, collapses monitoring, and opens placeholders", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [] });
  await page.goto("/");

  const monitoringToggle = page.getByRole("button", { name: "竞品监控" });
  await expect(monitoringToggle).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("button", { name: "竞品监控大屏" })).toBeVisible();

  await monitoringToggle.click();
  await expect(monitoringToggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("button", { name: "竞品监控大屏" })).toBeHidden();

  await page.getByRole("button", { name: "首页", exact: true }).click();
  await expect(page.getByRole("heading", { name: "首页", exact: true })).toBeVisible();
  await expect(page.getByText("首页模块已预留")).toBeVisible();

  for (const moduleName of ["全网比价", "自动询价", "自动上架"] as const) {
    await page.getByRole("button", { name: moduleName, exact: true }).click();
    await expect(page.getByRole("heading", { name: moduleName, exact: true })).toBeVisible();
    await expect(page.getByText(`${moduleName}模块已预留`)).toBeVisible();
  }

  await monitoringToggle.click();
  await page.getByRole("button", { name: "采集任务" }).click();
  await expect(page.getByRole("heading", { name: "采集任务", exact: true })).toBeVisible();
  await expect(page.getByText("采集任务模块已预留")).toBeVisible();

  await mock.expectNoUnexpectedApi();
});
