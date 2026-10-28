import { expect, test } from "@playwright/test";

import { installApiMock } from "./support/api-mock";

test("competitor monitoring settings save all values as one request", async ({ page }, testInfo) => {
  const mock = await installApiMock(page, { competitors: [] });
  const settings = { item_interval_seconds: 5, continuous_collection_count: 10, batch_rest_seconds: 120, verification_cooldown_seconds: 600, auto_resume_max: 2, operating_metrics_retry_max: 0, auto_collection_enabled: true, auto_collection_strategy: "rolling_24h", auto_collection_time: "09:30", auto_collection_times: ["09:30"], auto_collection_interval_hours: 4, auto_collection_daily_limit: 3, auto_collection_missed_policy: "catch_up" };
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
  await page.getByRole("navigation", { name: "设置模块" }).getByRole("button", { name: /^采集策略/ }).click();
  await expect.poll(() => reads).toBe(1);
  await page.getByLabel("单商品采集间隔").fill("6");
  await page.getByLabel("连续采集数量").fill("8");
  await page.getByLabel("批次休息时间").fill("3");
  await page.getByLabel("风控冷却时间").fill("12");
  await page.getByLabel("自动恢复次数").fill("1");
  await page.getByLabel("经营指标补采次数").fill("1");
  await expect(page.getByLabel("自动采集时间点 1")).toBeHidden();
  await expect(page.getByRole("group", { name: "错过计划" })).toBeHidden();
  await page.getByRole("radio", { name: "每日固定时间", exact: true }).check();
  await expect(page.getByRole("radio", { name: "每日固定时间", exact: true })).toHaveValue("fixed_daily");
  await expect(page.getByLabel("自动采集时间点 1")).toBeVisible();
  await expect(page.getByRole("group", { name: "错过计划" })).toBeVisible();
  await page.getByLabel("自动采集时间点 1").fill("10:15");
  await page.getByRole("radio", { name: "跳过已错过计划", exact: true }).check();
  await page.getByRole("radio", { name: "滚动 24 小时", exact: true }).check();
  await page.getByRole("radio", { name: "滚动 24 小时", exact: true }).press("ArrowDown");
  await expect(page.getByRole("radio", { name: "每日固定时间", exact: true })).toBeChecked();
  await expect(page.getByLabel("自动采集时间点 1")).toHaveValue("10:15");
  await expect(page.getByRole("radio", { name: "跳过已错过计划", exact: true })).toBeChecked();
  await page.getByRole("radio", { name: "跳过已错过计划", exact: true }).press("ArrowUp");
  await expect(page.getByRole("radio", { name: "补采最新到期计划", exact: true })).toBeChecked();
  await expect(page.getByRole("radio", { name: "补采最新到期计划", exact: true })).toHaveValue("catch_up");
  await page.getByRole("radio", { name: "补采最新到期计划", exact: true }).press("ArrowDown");
  await expect(page.getByRole("radio", { name: "跳过已错过计划", exact: true })).toHaveValue("skip");
  await page.getByRole("switch", { name: "每日自动采集" }).uncheck();
  await expect(page.getByLabel("自动采集时间点 1")).toHaveValue("10:15");
  await expect(page.getByRole("radio", { name: "跳过已错过计划", exact: true })).toBeChecked();
  await page.getByRole("switch", { name: "每日自动采集" }).check();
  await page.getByRole("radio", { name: "每日固定时间", exact: true }).press("ArrowUp");
  await expect(page.getByRole("radio", { name: "滚动 24 小时", exact: true })).toHaveValue("rolling_24h");
  await expect(page.getByLabel("自动采集时间点 1")).toBeHidden();
  await expect(page.getByRole("group", { name: "错过计划" })).toBeHidden();
  await page.getByRole("button", { name: "保存设置", exact: true }).click();
  await expect(page.getByText("竞品监控设置已保存。", { exact: true })).toBeVisible();
  expect(saved).toEqual({ item_interval_seconds: 6, continuous_collection_count: 8, batch_rest_seconds: 180, verification_cooldown_seconds: 720, auto_resume_max: 1, operating_metrics_retry_max: 1, auto_collection_enabled: true, auto_collection_strategy: "rolling_24h", auto_collection_time: "10:15", auto_collection_times: ["10:15"], auto_collection_interval_hours: 4, auto_collection_daily_limit: 3, auto_collection_missed_policy: "skip" });
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.screenshot({ path: testInfo.outputPath("v1.2-retry-settings.png"), fullPage: true });
  await mock.expectNoUnexpectedApi();
});

test("fixed daily and interval controls validate and save the complete settings", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [] });
  const settings = { item_interval_seconds: 5, continuous_collection_count: 10, batch_rest_seconds: 120, verification_cooldown_seconds: 600, auto_resume_max: 2, operating_metrics_retry_max: 0, auto_collection_enabled: true, auto_collection_strategy: "rolling_24h", auto_collection_time: "09:30", auto_collection_times: ["09:30"], auto_collection_interval_hours: 4, auto_collection_daily_limit: 3, auto_collection_missed_policy: "catch_up" };
  const saves: Record<string, unknown>[] = [];
  await page.route("**/api/settings/competitor-monitoring", route => {
    if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      saves.push(body);
      return route.fulfill({ json: body });
    }
    return route.fulfill({ json: settings });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "系统设置", exact: true }).click();
  await page.getByRole("navigation", { name: "设置模块" }).getByRole("button", { name: /^采集策略/ }).click();
  await page.getByRole("radio", { name: "每日固定时间", exact: true }).check();
  await expect(page.getByLabel("自动采集时间点 1")).toHaveValue("09:30");
  await page.getByRole("button", { name: "新增时间点" }).click();
  await page.getByRole("button", { name: "新增时间点" }).click();
  await expect(page.getByLabel("自动采集时间点 3")).toBeVisible();
  await page.getByRole("button", { name: "删除时间点 3" }).click();
  await page.getByLabel("自动采集时间点 1").fill("08:30");
  await page.getByLabel("自动采集时间点 2").fill("08:30");
  await page.getByRole("button", { name: "保存设置", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("不重复");
  expect(saves).toHaveLength(0);
  await page.getByLabel("自动采集时间点 2").fill("12:30");
  await page.getByRole("button", { name: "保存设置", exact: true }).click();
  await expect(page.getByText("竞品监控设置已保存。", { exact: true })).toBeVisible();
  expect(saves[0]).toMatchObject({ auto_collection_strategy: "fixed_daily", auto_collection_time: "08:30", auto_collection_times: ["08:30", "12:30"] });

  await page.getByRole("radio", { name: "每日固定间隔", exact: true }).check();
  await expect(page.getByLabel("每日开始时间")).toHaveValue("08:30");
  await expect(page.getByLabel("固定间隔小时数")).toHaveValue("4");
  await expect(page.getByRole("group", { name: "错过计划" })).toBeVisible();
  await page.getByLabel("每日开始时间").fill("21:00");
  await page.getByLabel("每日最多采集次数").fill("3");
  await page.getByRole("button", { name: "保存设置", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("同一天");
  expect(saves).toHaveLength(1);
  await page.getByLabel("每日最多采集次数").fill("1");
  await page.getByRole("button", { name: "保存设置", exact: true }).click();
  await expect(page.getByText("竞品监控设置已保存。", { exact: true })).toBeVisible();
  expect(saves[1]).toMatchObject({ auto_collection_strategy: "fixed_interval", auto_collection_time: "21:00", auto_collection_interval_hours: 4, auto_collection_daily_limit: 1, auto_collection_times: ["08:30", "12:30"] });
  await expect(page.getByLabel("自动采集时间点 1")).toBeHidden();
  await expect(page.getByLabel("每日开始时间")).toBeVisible();
  await mock.expectNoUnexpectedApi();
});
