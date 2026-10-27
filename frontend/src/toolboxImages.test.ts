import { describe, expect, it } from "vitest";
import { unzipSync } from "fflate";
import { makeZip, sourceType, type ImageResult } from "./toolboxImages";

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
});
