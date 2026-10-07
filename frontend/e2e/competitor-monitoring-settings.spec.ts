import { expect, test } from "@playwright/test";

import { installApiMock } from "./support/api-mock";

test("competitor monitoring settings save all values as one request", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [] });
  const settings = { item_interval_seconds: 5, continuous_collection_count: 10, batch_rest_seconds: 120, verification_cooldown_seconds: 600, auto_resume_max: 2, auto_collection_enabled: true, auto_collection_strategy: "rolling_24h", auto_collection_time: "09:30", auto_collection_missed_policy: "catch_up" };
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
  await expect(page.getByLabel("自动采集时间")).toBeHidden();
  await expect(page.getByRole("group", { name: "错过计划" })).toBeHidden();
  await page.getByRole("radio", { name: "每日固定时间", exact: true }).check();
  await expect(page.getByRole("radio", { name: "每日固定时间", exact: true })).toHaveValue("fixed_daily");
  await expect(page.getByLabel("自动采集时间")).toBeVisible();
  await expect(page.getByRole("group", { name: "错过计划" })).toBeVisible();
  await page.getByLabel("自动采集时间").fill("10:15");
  await page.getByRole("radio", { name: "本次跳过", exact: true }).check();
  await page.getByRole("radio", { name: "滚动 24 小时", exact: true }).check();
  await page.getByRole("radio", { name: "滚动 24 小时", exact: true }).press("ArrowDown");
  await expect(page.getByRole("radio", { name: "每日固定时间", exact: true })).toBeChecked();
  await expect(page.getByLabel("自动采集时间")).toHaveValue("10:15");
  await expect(page.getByRole("radio", { name: "本次跳过", exact: true })).toBeChecked();
  await page.getByRole("radio", { name: "本次跳过", exact: true }).press("ArrowUp");
  await expect(page.getByRole("radio", { name: "下次启动时补采", exact: true })).toBeChecked();
  await expect(page.getByRole("radio", { name: "下次启动时补采", exact: true })).toHaveValue("catch_up");
  await page.getByRole("radio", { name: "下次启动时补采", exact: true }).press("ArrowDown");
  await expect(page.getByRole("radio", { name: "本次跳过", exact: true })).toHaveValue("skip");
  await page.getByRole("switch", { name: "每日自动采集" }).uncheck();
  await expect(page.getByLabel("自动采集时间")).toHaveValue("10:15");
  await expect(page.getByRole("radio", { name: "本次跳过", exact: true })).toBeChecked();
  await page.getByRole("switch", { name: "每日自动采集" }).check();
  await page.getByRole("radio", { name: "每日固定时间", exact: true }).press("ArrowUp");
  await expect(page.getByRole("radio", { name: "滚动 24 小时", exact: true })).toHaveValue("rolling_24h");
  await expect(page.getByLabel("自动采集时间")).toBeHidden();
  await expect(page.getByRole("group", { name: "错过计划" })).toBeHidden();
  await page.getByRole("button", { name: "保存设置", exact: true }).click();
  await expect(page.getByText("竞品监控设置已保存。", { exact: true })).toBeVisible();
  expect(saved).toEqual({ item_interval_seconds: 6, continuous_collection_count: 8, batch_rest_seconds: 180, verification_cooldown_seconds: 720, auto_resume_max: 1, auto_collection_enabled: true, auto_collection_strategy: "rolling_24h", auto_collection_time: "10:15", auto_collection_missed_policy: "skip" });
  await mock.expectNoUnexpectedApi();
});
