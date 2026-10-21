import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { installApiMock } from "./support/api-mock";

const evidence = resolve("../docs/qa/home-command-center");

test("desktop home fits one viewport without clipping content", async ({ page }) => {
  await installApiMock(page, { competitors: [] });
  await page.goto("/");
  for (const [width, height] of [[1920, 911], [1440, 900], [1366, 768], [1280, 720]]) {
    await page.setViewportSize({ width, height });
    const dimensions = await page.locator("main").evaluate(el => ({
      scroll: el.scrollHeight, viewport: el.clientHeight,
      sections: [...el.querySelectorAll<HTMLElement>(".workspace-home > *")].map(node => [node.className, node.offsetHeight]),
    }));
    expect(dimensions.scroll, JSON.stringify({ width, height, ...dimensions })).toBeLessThanOrEqual(dimensions.viewport);
    const sidebar = await page.locator(".workspace-sidebar").evaluate(el => ({ scroll: el.scrollHeight, viewport: el.clientHeight }));
    expect(sidebar.scroll, JSON.stringify({ width, height, sidebar })).toBeLessThanOrEqual(sidebar.viewport);
    expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight)).toBe(true);
    for (const selector of [".home-planned", ".home-settings-link", ".home-monitoring-links"]) {
      const bounds = await page.locator(selector).boundingBox();
      expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(height);
    }
    await page.screenshot({ path: resolve(evidence, `single-screen-${width}x${height}.png`) });
  }
});

test("home composition, viewport evidence and keyboard feedback", async ({ page }) => {
  mkdirSync(evidence, { recursive: true });
  const api: string[] = [];
  page.on("request", request => { if (new URL(request.url()).pathname.startsWith("/api/")) api.push(request.url()); });
  await installApiMock(page, { competitors: [] });
  await page.goto("/");
  const home = page.locator(".workspace-home");
  await expect(home.getByRole("heading", { name: "首页", exact: true })).toBeVisible();
  for (const width of process.env.HOME_BEFORE ? [1440, 390] : [1440, 1280, 761, 760, 390, 375, 320]) {
    await page.setViewportSize({ width, height: width <= 760 ? 844 : 1000 });
    await page.locator("main").evaluate(el => el.scrollTop = 0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(await home.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    if ([1440, 390].includes(width)) await page.screenshot({ path: resolve(evidence, `${process.env.HOME_BEFORE ? "before" : "after"}-${width}.png`), fullPage: true });
  }
  if (process.env.HOME_BEFORE) return;
  // App initializes monitoring in the background; HomePage must add no endpoint.
  expect([...new Set(api.map(url => new URL(url).pathname))].sort()).toEqual([
    "/api/competitors/collect-batch/status", "/api/dashboard/group-attention",
    "/api/dashboard/today", "/api/settings/own-shop-name",
  ]);
  await expect(home.getByRole("button")).toHaveCount(7);
  await expect(home.locator(".home-planned button")).toHaveCount(0);
  await page.setViewportSize({ width: 1440, height: 1000 });
  const primary = home.getByRole("button", { name: "进入竞品监控大屏" });
  await primary.focus();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  await expect(primary).toBeFocused();
  expect(await primary.evaluate(el => el.matches(":focus-visible"))).toBe(true);
  await page.screenshot({ path: resolve(evidence, "keyboard-1440.png"), fullPage: true });
  const task = home.getByRole("button", { name: "我方商品" });
  await task.hover();
  await page.screenshot({ path: resolve(evidence, "hover-1440.png"), fullPage: true });
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(await primary.evaluate(el => getComputedStyle(el).transitionDuration)).toBe("0s");
  expect(await task.locator(".home-arrow").evaluate(el => getComputedStyle(el).transform)).toBe("none");
  await primary.hover();
  await page.mouse.down();
  expect(await primary.evaluate(el => getComputedStyle(el).backgroundColor)).toBe("rgb(30, 64, 175)");
  await page.mouse.move(0, 0);
  await page.mouse.up();
  await page.setViewportSize({ width: 844, height: 390 });
  expect(await home.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
  await page.setViewportSize({ width: 390, height: 844 });
  await home.evaluate(el => {
    const text = [...el.querySelectorAll<HTMLElement>("h1,h2,h3,p,span,strong,small,button,li")];
    const sizes = text.map(node => parseFloat(getComputedStyle(node).fontSize));
    text.forEach((node, index) => node.style.fontSize = `${sizes[index] * 2}px`);
  });
  expect(await home.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
  await page.reload();
  const entries = page.locator(".workspace-home button");
  await entries.first().focus();
  for (let index = 0; index < 7; index++) {
    await expect(entries.nth(index)).toBeFocused();
    if (index < 6) await page.keyboard.press("Tab");
  }
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "系统设置", exact: true })).toBeVisible();
});
