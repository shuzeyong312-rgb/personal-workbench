import { describe, expect, it, vi } from "vitest";
import { unzipSync } from "fflate";
import { MAX_BATCH_BYTES, inspectImage, makeZip, processImage, sourceType, withinBatchBudget, type ImageResult } from "./toolboxImages";

describe("toolbox image files", () => {
  it("checks bytes rather than trusting a file type", async () => {
    const fake = new File([new Uint8Array([1, 2, 3])], "photo.png", { type: "image/png" });
    await expect(sourceType(fake)).rejects.toThrow();
  });
  it("preserves both same-named results in an extractable ZIP", async () => {
    const result = { name: "图片.jpg", blob: new Blob(["one"]) } as ImageResult;
    const zip = await makeZip([result, { ...result, blob: new Blob(["two"]) }]);
    const files = unzipSync(new Uint8Array(await zip.arrayBuffer()));
    expect(Object.keys(files)).toEqual(["图片.jpg", "图片 (2).jpg"]);
    expect(new TextDecoder().decode(files["图片 (2).jpg"])).toBe("two");
  });
  it("rejects an oversized PNG before invoking the browser decoder", async () => {
    const header = new Uint8Array(24); header.set([137,80,78,71,13,10,26,10,0,0,0,13,73,72,68,82]);
    new DataView(header.buffer).setUint32(16, 10000); new DataView(header.buffer).setUint32(20, 10000);
    const decode = vi.fn(); vi.stubGlobal("createImageBitmap", decode);
    try {
      await expect(processImage(new File([header], "huge.png"), { mode: "compress", compression: "smart", targetKB: 200, format: "original", width: 800, height: 800, fit: "contain" })).rejects.toThrow(/4500/);
      expect(decode).not.toHaveBeenCalled();
    } finally { vi.unstubAllGlobals(); }
  });
  it("reads JPEG and WebP dimensions before decoding", async () => {
    const jpeg = new Uint8Array([0xff,0xd8,0xff,0xc0,0,11,8,0x1b,0x58,0x1b,0x58,1,1,0,0]);
    await expect(inspectImage(new File([jpeg], "large.jpg"))).rejects.toThrow(/4500/);
    const webp = new Uint8Array(30); webp.set([82,73,70,70], 0); webp.set([87,69,66,80,86,80,56,88], 8);
    webp.set([0x0f,0x27,0,0x0f,0x27,0], 24);
    await expect(inspectImage(new File([webp], "large.webp"))).rejects.toThrow(/4500/);
  });
  it("rejects over-budget ZIPs before reading data and cancels stale work", async () => {
    expect(withinBatchBudget(MAX_BATCH_BYTES - 1, 1)).toBe(true);
    expect(withinBatchBudget(MAX_BATCH_BYTES - 1, 2)).toBe(false);
    const read = vi.fn(); const huge = { name: "big.png", blob: { size: MAX_BATCH_BYTES + 1, arrayBuffer: read } } as unknown as ImageResult;
    await expect(makeZip([huge])).rejects.toThrow(/64 MiB/); expect(read).not.toHaveBeenCalled();
    const result = { name: "image.png", blob: new Blob(["data"]) } as ImageResult;
    await expect(makeZip([result], () => false)).rejects.toThrow(/变化/);
  });
  it("yields between bounded ZIP chunks without reading a whole output blob", async () => {
    const blob = new Blob([new Uint8Array(700_000)]); const fullRead = vi.spyOn(blob, "arrayBuffer");
    const result = { name: "large.png", blob } as ImageResult;
    let yielded = false; setTimeout(() => { yielded = true; }, 0);
    const zip = await makeZip([result]);
    expect(yielded).toBe(true); expect(fullRead).not.toHaveBeenCalled();
    expect(unzipSync(new Uint8Array(await zip.arrayBuffer()))["large.png"].length).toBe(700_000);
  });
});
