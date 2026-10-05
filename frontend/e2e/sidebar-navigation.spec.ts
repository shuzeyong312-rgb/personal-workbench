import { expect, test } from "@playwright/test";
import { installApiMock } from "./support/api-mock";

test("collapses competitor monitoring navigation and opens collection tasks placeholder", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [] });
  await page.goto("/");

  const monitoringToggle = page.getByRole("button", { name: "竞品监控" });
  await expect(monitoringToggle).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("button", { name: "竞品监控大屏" })).toBeVisible();

  await monitoringToggle.click();
  await expect(monitoringToggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("button", { name: "竞品监控大屏" })).toBeHidden();

  await monitoringToggle.click();
  await page.getByRole("button", { name: "采集任务" }).click();
  await expect(page.getByRole("heading", { name: "采集任务", exact: true })).toBeVisible();
  await expect(page.getByText("采集任务页面已预留")).toBeVisible();

  await mock.expectNoUnexpectedApi();
});
