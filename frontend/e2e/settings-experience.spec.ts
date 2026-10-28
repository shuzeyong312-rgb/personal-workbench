import { expect, test } from "@playwright/test";
import { installApiMock } from "./support/api-mock";

test("settings visual coverage", async ({ page }, testInfo) => {
  const mock = await installApiMock(page, { competitors: [] });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await page.getByRole("button", { name: "系统设置", exact: true }).click();
  await expect(page.getByRole("heading", { name: "竞品监控分析" })).toBeVisible();
  const modules = page.getByRole("navigation", { name: "设置模块" });
  await expect(modules.getByRole("link")).toHaveCount(8);
  await expect(modules.getByRole("link", { name: /^店铺识别/ })).toHaveAttribute("href", "#settings-basic");
  await expect(modules.getByRole("link", { name: /^工作浏览器/ })).toBeVisible();
  await expect(page.getByLabel("我方店铺名称")).toHaveValue("测试店铺");
  await modules.getByRole("link", { name: "客户触达" }).click();
  await expect(page.locator("#settings-future").getByRole("button", { name: /客户触达/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#settings-future").getByRole("status")).toContainText("客户触达设置 · 尚未开放");
  await modules.getByRole("link", { name: /^店铺识别/ }).click();
  await page.screenshot({ path: testInfo.outputPath("basic-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: testInfo.outputPath("basic-narrow.png"), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("navigation", { name: "设置模块" }).getByRole("link", { name: /^采集策略/ }).click();
  await expect(page.getByLabel("单商品采集间隔")).toHaveValue("5");
  await page.screenshot({ path: testInfo.outputPath("monitoring-desktop.png") });
  await page.getByRole("radio", { name: "每日固定时间", exact: true }).check();
  await page.screenshot({ path: testInfo.outputPath("fixed-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: testInfo.outputPath("monitoring-narrow.png"), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await mock.expectNoUnexpectedApi();
});

test("drafts survive category and page changes; invalid values never submit", async ({ page }, testInfo) => {
  const mock = await installApiMock(page, { competitors: [] });
  let puts = 0;
  await page.route("**/api/settings/competitor-monitoring", async route => {
    if (route.request().method() === "GET") return route.fallback();
    puts++;
    return route.fulfill({ json: route.request().postDataJSON() });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "系统设置", exact: true }).click();
  await page.getByLabel("我方店铺名称").fill("待保存店铺");
  const categories = page.getByRole("navigation", { name: "设置模块" });
  await categories.getByRole("link", { name: /^采集策略/ }).click();
  const interval = page.getByLabel("单商品采集间隔");
  await interval.fill("");
  await page.locator("#settings-monitoring").getByRole("button", { name: "保存设置", exact: true }).click();
  await expect(interval).toBeFocused();
  await expect(page.getByRole("alert")).toContainText("数值须在范围内");
  await page.screenshot({ path: testInfo.outputPath("validation.png") });
  expect(puts).toBe(0);
  await categories.getByRole("link", { name: /^店铺识别/ }).click();
  await expect(page.getByLabel("我方店铺名称")).toHaveValue("待保存店铺");
  await categories.getByRole("link", { name: /^采集策略/ }).click();
  await expect(interval).toHaveValue("");
  for (const value of ["0", "61", "1.5"]) {
    await interval.fill(value);
    await page.locator("#settings-monitoring").getByRole("button", { name: "保存设置", exact: true }).click();
    expect(puts).toBe(0);
  }
  await interval.fill("7");
  page.once("dialog", dialog => dialog.dismiss());
  await page.getByRole("button", { name: "首页", exact: true }).click();
  await expect(interval).toBeVisible();
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "首页", exact: true }).click();
  const unload = page.waitForEvent("dialog");
  const reload = page.reload({ timeout: 2000 }).catch(() => null);
  const dialog = await unload;
  expect(dialog.type()).toBe("beforeunload");
  await dialog.dismiss();
  await reload;
  await page.getByRole("button", { name: "系统设置", exact: true }).click();
  await expect(page.getByLabel("我方店铺名称")).toHaveValue("待保存店铺");
  await categories.getByRole("link", { name: /^采集策略/ }).click();
  await expect(interval).toHaveValue("7");
  await expect(page.locator("#settings-monitoring .settings-save-state")).toContainText("未保存");
  await expect(interval).toHaveValue("7");
  await mock.expectNoUnexpectedApi();
});

test("category changes share the pending load instead of overwriting edits with a late response", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [] });
  let reads = 0;
  let release: (() => void) | undefined;
  await page.route("**/api/settings/competitor-monitoring", async route => {
    reads++;
    await new Promise<void>(resolve => { release = resolve; });
    await route.fallback();
  });
  await page.goto("/");
  await page.getByRole("button", { name: "系统设置", exact: true }).click();
  const categories = page.getByRole("navigation", { name: "设置模块" });
  await categories.getByRole("link", { name: /^采集策略/ }).click();
  await expect.poll(() => reads).toBe(1);
  await categories.getByRole("link", { name: /^店铺识别/ }).click();
  await categories.getByRole("link", { name: /^采集策略/ }).click();
  await expect(page.getByText("正在加载竞品监控设置…")).toBeVisible();
  expect(reads).toBe(1);
  release!();
  await page.getByLabel("单商品采集间隔").fill("9");
  await categories.getByRole("link", { name: /^店铺识别/ }).click();
  await categories.getByRole("link", { name: /^采集策略/ }).click();
  await expect(page.getByLabel("单商品采集间隔")).toHaveValue("9");
  expect(reads).toBe(1);
  await mock.expectNoUnexpectedApi();
});

test("keyboard focus remains visible on desktop and narrow screens", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [] });
  await page.goto("/");
  await page.getByRole("button", { name: "系统设置", exact: true }).click();
  await page.getByRole("navigation", { name: "设置模块" }).getByRole("link", { name: /^采集策略/ }).click();
  await page.getByRole("radio", { name: "每日固定时间", exact: true }).check();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await page.getByLabel("单商品采集间隔").focus();
    for (let index = 0; index < 12; index++) {
      await page.keyboard.press("Tab");
      const focus = page.locator(".settings-card input:focus");
      if (await focus.count()) {
        const field = (await focus.boundingBox())!;
        expect(field.y + field.height).toBeLessThanOrEqual(width === 390 ? 844 : 1000);
        expect(field.y).toBeGreaterThanOrEqual(0);
      }
    }
    expect(await page.locator("main").evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  }
  await mock.expectNoUnexpectedApi();
});

test("basic save keeps identity confirmation and failure recovery", async ({ page }, testInfo) => {
  const mock = await installApiMock(page, { competitors: [] });
  let stored: string | null = null;
  let puts = 0;
  let fail = true;
  await page.route("**/api/settings/own-shop-name", async route => {
    if (route.request().method() === "GET") {
      if (stored === null) return route.fallback();
      return route.fulfill({ json: { configured: true, own_shop_name: stored } });
    }
    puts++;
    if (fail) return route.fulfill({ status: 500, json: { message: "店铺保存失败，请重试" } });
    stored = route.request().postDataJSON().own_shop_name.trim();
    return route.fulfill({ json: { configured: true, own_shop_name: stored } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "系统设置", exact: true }).click();
  await page.getByLabel("我方店铺名称").fill(" 新店铺 ");
  page.once("dialog", dialog => dialog.dismiss());
  await page.locator("#settings-basic").getByRole("button", { name: "保存设置", exact: true }).click();
  expect(puts).toBe(0);
  page.once("dialog", dialog => dialog.accept());
  await page.locator("#settings-basic").getByRole("button", { name: "保存设置", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("店铺保存失败");
  await expect(page.getByLabel("我方店铺名称")).toHaveValue(" 新店铺 ");
  fail = false;
  page.once("dialog", dialog => dialog.accept());
  await page.locator("#settings-basic").getByRole("button", { name: "保存设置", exact: true }).click();
  await expect(page.getByLabel("我方店铺名称")).toHaveValue("新店铺");
  await expect(page.locator("#settings-basic .settings-save-state")).toHaveText("当前设置已保存");
  await page.screenshot({ path: testInfo.outputPath("basic-saved.png") });
  expect(puts).toBe(2);
  await mock.expectNoUnexpectedApi();
});

test("initial basic load is shared and an unconfigured shop is not reported as saved", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [] });
  let reads = 0;
  let release: (() => void) | undefined;
  await page.route("**/api/settings/own-shop-name", async route => {
    reads++;
    await new Promise<void>(resolve => { release = resolve; });
    await route.fulfill({ json: { configured: false, own_shop_name: null } });
  });
  await page.goto("/");
  await expect.poll(() => reads).toBe(1);
  await page.getByRole("button", { name: "系统设置", exact: true }).click();
  await expect(page.getByText("正在加载系统设置…")).toBeVisible();
  expect(reads).toBe(1);
  release!();
  await expect(page.locator("#settings-basic .settings-save-state")).toHaveText("尚未配置");
  await expect(page.locator("#settings-basic").getByRole("button", { name: "保存设置", exact: true })).toBeDisabled();
  await mock.expectNoUnexpectedApi();
});

test("save failure retains draft; retry shows saving then saved and keeps other category dirty", async ({ page }, testInfo) => {
  const mock = await installApiMock(page, { competitors: [] });
  let fail = true;
  let release: (() => void) | undefined;
  await page.route("**/api/settings/competitor-monitoring", async route => {
    if (route.request().method() === "GET") return route.fallback();
    if (fail) return route.fulfill({ status: 500, json: { message: "暂时无法保存，请重试。" } });
    await new Promise<void>(resolve => { release = resolve; });
    await route.fulfill({ json: route.request().postDataJSON() });
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await page.getByRole("button", { name: "系统设置", exact: true }).click();
  await page.getByLabel("我方店铺名称").fill("保留另一分类的草稿");
  const categories = page.getByRole("navigation", { name: "设置模块" });
  await categories.getByRole("link", { name: /^采集策略/ }).click();
  await page.getByLabel("单商品采集间隔").fill("6");
  await page.locator("#settings-monitoring").getByRole("button", { name: "保存设置", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("暂时无法保存");
  await expect(page.getByLabel("单商品采集间隔")).toHaveValue("6");
  await page.screenshot({ path: testInfo.outputPath("save-failure.png") });
  fail = false;
  await page.locator("#settings-monitoring").getByRole("button", { name: "保存设置", exact: true }).click();
  await expect(page.getByRole("button", { name: "保存中…" })).toBeDisabled();
  await expect(page.getByLabel("单商品采集间隔")).toBeDisabled();
  await expect(page.locator("#settings-monitoring .settings-save-state")).toContainText("正在保存");
  await page.screenshot({ path: testInfo.outputPath("saving.png") });
  await expect.poll(() => Boolean(release)).toBe(true);
  release!();
  await expect(page.getByText("竞品监控设置已保存。", { exact: true })).toBeVisible();
  await expect(page.locator("#settings-monitoring .settings-save-state").filter({ hasText: "当前设置已保存" })).toBeVisible();
  await expect(categories.getByRole("link", { name: /^店铺识别/ })).toContainText("未保存");
  await page.screenshot({ path: testInfo.outputPath("save-success.png") });
  await categories.getByRole("link", { name: /^店铺识别/ }).click();
  await expect(page.getByLabel("我方店铺名称")).toHaveValue("保留另一分类的草稿");
  await mock.expectNoUnexpectedApi();
});


test("each reset restores its saved values without changing the other draft", async ({ page }) => {
  const mock = await installApiMock(page, { competitors: [] });
  await page.goto("/");
  await page.getByRole("button", { name: "系统设置", exact: true }).click();
  await page.getByLabel("我方店铺名称").fill("店铺草稿");
  await page.getByLabel("单商品采集间隔").fill("9");
  await page.getByRole("button", { name: "撤销采集策略修改" }).click();
  await expect(page.getByLabel("单商品采集间隔")).toHaveValue("5");
  await expect(page.getByLabel("我方店铺名称")).toHaveValue("店铺草稿");
  await page.getByLabel("单商品采集间隔").fill("8");
  await page.getByRole("button", { name: "撤销店铺修改" }).click();
  await expect(page.getByLabel("我方店铺名称")).toHaveValue("测试店铺");
  await expect(page.getByLabel("单商品采集间隔")).toHaveValue("8");
  await mock.expectNoUnexpectedApi();
});
