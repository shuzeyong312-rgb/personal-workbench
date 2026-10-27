import { expect, test } from "@playwright/test";
import { unzipSync } from "fflate";
import { installApiMock } from "./support/api-mock";
import { readFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";

test("catalog and local image processing", async ({ page }, testInfo) => {
  await installApiMock(page, { competitors: [] });
  let items = [
    { id: 1, kind: "builtin", builtin_key: "compress", name: "图片压缩", category: "图片", description: "压缩", url: null, favorite: true },
    { id: 2, kind: "builtin", builtin_key: "resize", name: "图片尺寸修改", category: "图片", description: "尺寸", url: null, favorite: false },
    { id: 3, kind: "site", builtin_key: null, name: "iLovePDF", category: "PDF", description: "PDF", url: "https://www.ilovepdf.com/zh-cn", favorite: true },
  ];
  await page.route("**/api/toolbox/**", async route => {
    const req = route.request(), path = new URL(req.url()).pathname;
    if (req.method() === "GET") return route.fulfill({ json: items });
    if (req.method() === "POST") { items.push({ id: 4, kind: "site", builtin_key: null, favorite: false, ...req.postDataJSON() }); return route.fulfill({ status: 201, json: items.at(-1) }); }
    if (req.method() === "PATCH" && path.endsWith("/favorite")) { const id = Number(path.split("/")[4]); items = items.map(i => i.id === id ? { ...i, favorite: req.postDataJSON().favorite } : i); return route.fulfill({ json: {} }); }
    if (req.method() === "PATCH") { const id = Number(path.split("/").at(-1)); items = items.map(i => i.id === id ? { ...i, ...req.postDataJSON() } : i); return route.fulfill({ json: {} }); }
    items = items.filter(i => i.id !== Number(path.split("/").at(-1))); return route.fulfill({ status: 204 });
  });
  await page.goto("/");
  await page.locator(".workspace-sidebar").getByRole("button", { name: "常用工具箱" }).click();
  await expect(page.getByRole("link", { name: "打开网站" }).first()).toHaveAttribute("rel", "noopener noreferrer");
  await page.getByRole("button", { name: "添加网站链接" }).click();
  await page.getByLabel("网站名称").fill("测试网站"); await page.getByLabel("网址", { exact: true }).fill("https://example.com/"); await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByText("测试网站")).toBeVisible();
  const card = page.locator(".toolbox-card").filter({ hasText: "测试网站" });
  await card.getByRole("button", { name: "编辑" }).click(); await page.getByLabel("网站名称").fill("已编辑网站"); await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.locator(".toolbox-card").filter({ hasText: "已编辑网站" }).getByRole("button", { name: "收藏 已编辑网站" }).click();
  await expect(page.locator(".toolbox-card").filter({ hasText: "已编辑网站" }).first().getByRole("button", { name: "取消收藏 已编辑网站" })).toBeVisible();
  await page.reload(); await page.locator(".workspace-sidebar").getByRole("button", { name: "常用工具箱" }).click();
  await expect(page.locator(".toolbox-card").filter({ hasText: "已编辑网站" }).first().getByRole("button", { name: "取消收藏 已编辑网站" })).toBeVisible();
  page.once("dialog", dialog => dialog.accept()); await page.locator(".toolbox-card").filter({ hasText: "已编辑网站" }).first().getByRole("button", { name: "删除" }).click();
  await expect(page.getByText("已编辑网站")).toHaveCount(0);
  await page.getByRole("button", { name: "使用工具" }).first().click();
  const bytes = await page.evaluate(() => { const c = document.createElement("canvas"); c.width = 120; c.height = 60; c.getContext("2d")!.fillRect(0, 0, 120, 60); return c.toDataURL("image/png").split(",")[1]; });
  const buffer = Buffer.from(bytes, "base64");
  await page.locator('input[type="file"]').setInputFiles([{ name: "same.png", mimeType: "image/png", buffer }, { name: "same.png", mimeType: "image/png", buffer }]);
  await page.getByRole("button", { name: "图片尺寸修改", exact: true }).click();
  await page.getByRole("button", { name: "开始处理" }).click();
  await expect(page.getByText(/结果 800×800/)).toBeVisible();
  const pixel = await page.locator('img[alt="结果预览"]').evaluate(async image => { const img = image as HTMLImageElement; await img.decode(); const c = document.createElement("canvas"); c.width = img.naturalWidth; c.height = img.naturalHeight; const ctx = c.getContext("2d")!; ctx.drawImage(img, 0, 0); return Array.from(ctx.getImageData(0, 0, 1, 1).data); });
  expect(pixel).toEqual([255, 255, 255, 255]);
  const downloadPromise = page.waitForEvent("download"); await page.getByRole("button", { name: "批量 ZIP 下载" }).click();
  const path = await (await downloadPromise).path(); const files = unzipSync(new Uint8Array(await readFile(path!)));
  expect(Object.keys(files)).toHaveLength(2);
  const extractedNames = JSON.parse(execFileSync("../.venv/Scripts/python.exe", ["-c", "import json,sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); print(json.dumps(z.namelist(), ensure_ascii=False)); assert z.testzip() is None", path!], { encoding: "utf8" }));
  expect(extractedNames).toHaveLength(2);
  await page.getByLabel("适配方式").selectOption("cover"); await expect(page.getByRole("button", { name: "下载结果" })).toHaveCount(0);
  await page.getByRole("button", { name: "开始处理" }).click(); await expect(page.getByText(/结果 800×800/)).toBeVisible();
  const cropPixel = await page.locator('img[alt="结果预览"]').evaluate(async image => { const img = image as HTMLImageElement; await img.decode(); const c = document.createElement("canvas"); c.width = img.naturalWidth; c.height = img.naturalHeight; const ctx = c.getContext("2d")!; ctx.drawImage(img, 0, 0); return Array.from(ctx.getImageData(0, 0, 1, 1).data); });
  expect(cropPixel).toEqual([0, 0, 0, 255]);
  await page.locator('input[type="file"]').setInputFiles({ name: "invalid.png", mimeType: "image/png", buffer: Buffer.from("not an image") });
  await page.getByRole("button", { name: "开始处理" }).click(); await expect(page.getByText("文件不是支持的 JPG、PNG 或 WebP 图片")).toBeVisible();
  await page.getByRole("button", { name: "清空", exact: true }).click();
  await page.locator('input[type="file"]').setInputFiles([{ name: "bad.png", mimeType: "image/png", buffer: Buffer.from("invalid") }, { name: "good.png", mimeType: "image/png", buffer }]);
  await page.getByRole("button", { name: "开始处理" }).click();
  await expect(page.getByText("成功 1 张，失败 1 张")).toBeVisible();
  await expect(page.getByRole("button", { name: "批量 ZIP 下载" })).toBeVisible();
  await expect(page.getByRole("button", { name: "下载结果" })).toBeVisible();
  await page.getByRole("button", { name: "清空", exact: true }).click();
  const largeImage = await page.evaluate(() => { const c = document.createElement("canvas"); c.width = c.height = 3500; c.getContext("2d")!.fillRect(0, 0, 3500, 3500); return c.toDataURL("image/png").split(",")[1]; });
  await page.locator('input[type="file"]').setInputFiles({ name: "large.png", mimeType: "image/png", buffer: Buffer.from(largeImage, "base64") });
  await page.getByRole("button", { name: "开始处理" }).click();
  await expect(page.getByText("大图预览已缩小；下载文件保持实际尺寸。")).toBeVisible();
  expect(await page.locator('img[alt="原图预览"]').evaluate(node => (node as HTMLImageElement).naturalWidth)).toBeLessThanOrEqual(600);
  await page.getByRole("button", { name: "清空", exact: true }).click();
  const samples = await page.evaluate(() => { const c = document.createElement("canvas"); c.width = 500; c.height = 300; const ctx = c.getContext("2d")!; const data = ctx.createImageData(c.width, c.height); for (let i = 0; i < data.data.length; i += 4) { data.data[i] = (i * 17) % 251; data.data[i + 1] = (i * 31) % 253; data.data[i + 2] = (i * 43) % 255; data.data[i + 3] = i % 8 === 0 ? 0 : 255; } ctx.putImageData(data, 0, 0); return [c.toDataURL("image/png"), c.toDataURL("image/jpeg"), c.toDataURL("image/webp")].map(x => x.split(",")[1]); });
  await page.locator('input[type="file"]').setInputFiles(["png", "jpeg", "webp"].map((ext, index) => ({ name: `sample.${ext}`, mimeType: `image/${ext}`, buffer: Buffer.from(samples[index], "base64") })));
  await page.getByRole("button", { name: "图片压缩", exact: true }).click(); await page.getByRole("radio", { name: /目标文件大小/ }).check(); await page.getByLabel("目标 KB（20–20000）").fill("20");
  await page.getByRole("button", { name: "开始处理" }).click(); await expect(page.getByRole("button", { name: "开始处理" })).toBeEnabled();
  await expect(page.locator(".toolbox-row").filter({ hasText: "sample.png" })).toContainText("未达到目标体积");
  await expect(page.locator(".toolbox-row").filter({ hasText: "sample.jpeg" })).toContainText("→");
  await expect(page.locator(".toolbox-row").filter({ hasText: "sample.webp" })).toContainText("→");
  await page.getByRole("button", { name: "清空", exact: true }).click();
  const transparent = await page.evaluate(() => { const c = document.createElement("canvas"); c.width = c.height = 20; return c.toDataURL("image/png").split(",")[1]; });
  await page.locator('input[type="file"]').setInputFiles({ name: "transparent.png", mimeType: "image/png", buffer: Buffer.from(transparent, "base64") });
  await page.getByRole("radio", { name: /智能压缩/ }).check(); await page.getByLabel("输出格式").selectOption("image/jpeg"); await page.getByRole("button", { name: "开始处理" }).click();
  await expect(page.locator('img[alt="结果预览"]')).toBeVisible();
  const whitePixel = await page.locator('img[alt="结果预览"]').evaluate(async image => { const img = image as HTMLImageElement; await img.decode(); const c = document.createElement("canvas"); c.width = c.height = 20; const ctx = c.getContext("2d")!; ctx.drawImage(img, 0, 0); return Array.from(ctx.getImageData(0, 0, 1, 1).data); });
  expect(whitePixel).toEqual([255, 255, 255, 255]);
  const singleDownload = page.waitForEvent("download"); await page.getByRole("button", { name: "下载结果" }).click(); expect((await singleDownload).suggestedFilename()).toMatch(/\.jpg$/);
  await page.getByRole("button", { name: "清空", exact: true }).click(); await page.getByLabel("输出格式").selectOption("original");
  await page.locator('input[type="file"]').setInputFiles({ name: "photo.png", mimeType: "image/png", buffer });
  await page.getByRole("button", { name: "图片尺寸修改", exact: true }).click();
  await page.evaluate(() => { const original = window.createImageBitmap; window.createImageBitmap = ((...args: Parameters<typeof createImageBitmap>) => new Promise<ImageBitmap>(resolve => { (window as unknown as { releaseImage: () => void }).releaseImage = () => { void original(...args).then(resolve); }; })) as typeof createImageBitmap; });
  await page.getByRole("button", { name: "开始处理" }).click();
  await page.waitForFunction(() => !!(window as unknown as { releaseImage?: () => void }).releaseImage);
  await page.getByLabel("适配方式").selectOption("contain");
  await page.evaluate(() => (window as unknown as { releaseImage: () => void }).releaseImage());
  await expect(page.getByRole("button", { name: "开始处理" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "下载结果" })).toHaveCount(0);
  for (const width of [1440, 1024, 390]) { await page.setViewportSize({ width, height: 900 }); await page.screenshot({ path: testInfo.outputPath(`toolbox-${width}.png`), fullPage: true }); }
});
