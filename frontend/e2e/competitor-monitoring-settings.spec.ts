import { expect, test } from "@playwright/test";

import { installApiMock } from "./support/api-mock";

test("competitor monitoring settings save all values as one request", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [] });
  const settings = { item_interval_seconds: 5, continuous_collection_count: 10, batch_rest_seconds: 120, verification_cooldown_seconds: 600, auto_resume_max: 2 };
  let saved: unknown = null;
  let reads = 0;
  await page.route("**/api/settings/competitor-monitoring", route => {
    if (route.request().method() === "PUT") {
      saved = route.request().postDataJSON();
      return route.fulfill({ json: saved });
    }
    reads += 1;
    return route.fulfill({ json: settings });
  });
  await page.goto("/");
  expect(reads).toBe(0);
  await page.getByRole("button", { name: "系统设置", exact: true }).click();
  expect(reads).toBe(0);
  await page.getByRole("navigation", { name: "设置模块" }).getByRole("button", { name: /^竞品监控/ }).click();
  await expect.poll(() => reads).toBe(1);
  await page.getByLabel("单商品采集间隔").fill("6");
  await page.getByLabel("连续采集数量").fill("8");
  await page.getByLabel("批次休息时间").fill("3");
  await page.getByLabel("风控冷却时间").fill("12");
  await page.getByLabel("自动恢复次数").fill("1");
  await page.getByRole("button", { name: "保存设置", exact: true }).click();
  await expect(page.getByText("竞品监控设置已保存。", { exact: true })).toBeVisible();
  expect(saved).toEqual({ item_interval_seconds: 6, continuous_collection_count: 8, batch_rest_seconds: 180, verification_cooldown_seconds: 720, auto_resume_max: 1 });
  await mock.expectNoUnexpectedApi();
});
