import { expect, test } from "@playwright/test";
import { installApiMock } from "./support/api-mock";

test("work browser navigation keeps settings draft and opens once", async ({ page }, testInfo) => {
  const mock = await installApiMock(page, { competitors: [] });
  let status = "idle";
  let opens = 0;
  let extensions = 0;
  await page.route("**/api/work-browser", async route => {
    if (route.request().method() === "POST") { opens++; status = "managing"; }
    await route.fulfill({ json: { status, message: "" } });
  });
  await page.route("**/api/work-browser/extensions", async route => {
    extensions++;
    await route.fulfill({ json: { status, message: "" } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "系统设置", exact: true }).click();
  await page.getByLabel("我方店铺名称").fill("未保存草稿");
  await page.getByRole("navigation", { name: "设置模块" }).getByRole("button", { name: /^工作浏览器/ }).click();
  await expect(page.getByRole("status").filter({ hasText: "空闲" })).toBeVisible();
  await expect(page.getByText("1688 官方采购助手", { exact: true })).toBeVisible();
  await expect(page.getByText("工作浏览器配置目录", { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("work-browser-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: testInfo.outputPath("work-browser-narrow.png"), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", { name: "打开工作浏览器" }).click();
  await expect(page.getByRole("status").filter({ hasText: "管理中" })).toBeVisible();
  expect(opens).toBe(1);
  await page.getByRole("button", { name: "插件管理" }).click();
  expect(extensions).toBe(1);
  await page.getByRole("button", { name: "打开工作浏览器" }).click();
  expect(opens).toBe(2);
  await page.getByRole("navigation", { name: "设置模块" }).getByRole("button", { name: /^基础设置/ }).click();
  await expect(page.getByLabel("我方店铺名称")).toHaveValue("未保存草稿");
  await mock.expectNoUnexpectedApi();
});
