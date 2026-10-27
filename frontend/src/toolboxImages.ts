import { Zip, ZipPassThrough } from "fflate";

export const MAX_BATCH_BYTES = 64 * 1024 * 1024;
export function withinBatchBudget(currentBytes: number, nextBytes: number): boolean { return currentBytes + nextBytes <= MAX_BATCH_BYTES; }

export type ImageOptions = { mode: "compress" | "resize"; compression: "smart" | "strong" | "target"; targetKB: number; format: "original" | "image/jpeg" | "image/png" | "image/webp"; width: number; height: number; fit: "contain" | "cover" };
export type ImageResult = { blob: Blob; name: string; width: number; height: number; sourceWidth: number; sourceHeight: number; note: string; sourcePreview?: Blob; outputPreview?: Blob };

export async function sourceType(file: File): Promise<string> {
  const b = new Uint8Array(await file.slice(0, 12).arrayBuffer());
  if (b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) return "image/jpeg";
  if ([137, 80, 78, 71, 13, 10, 26, 10].every((v, i) => b[i] === v)) return "image/png";
  if (String.fromCharCode(...b.slice(0, 4)) === "RIFF" && String.fromCharCode(...b.slice(8, 12)) === "WEBP") return "image/webp";
  throw new Error("文件不是支持的 JPG、PNG 或 WebP 图片");
}

async function sourceDimensions(file: File, type: string): Promise<[number, number]> {
  const b = new Uint8Array(await (type === "image/jpeg" ? file : file.slice(0, 30)).arrayBuffer());
  const view = new DataView(b.buffer, b.byteOffset, b.byteLength);
  let width = 0, height = 0;
  if (type === "image/png" && b.length >= 24 && String.fromCharCode(...b.slice(12, 16)) === "IHDR") {
    width = view.getUint32(16); height = view.getUint32(20);
  } else if (type === "image/jpeg") {
    let offset = 2;
    while (offset + 4 <= b.length) {
      if (b[offset++] !== 0xff) break;
      while (b[offset] === 0xff && offset < b.length) offset++;
      const marker = b[offset++];
      if (marker === 0xd9 || marker === 0xda) break;
      if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) continue;
      if (offset + 2 > b.length) break;
      const length = view.getUint16(offset);
      if (length < 2 || offset + length > b.length) break;
      if ([0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf].includes(marker) && length >= 7) { height = view.getUint16(offset + 3); width = view.getUint16(offset + 5); break; }
      offset += length;
    }
  } else if (type === "image/webp" && b.length >= 25) {
    const chunk = String.fromCharCode(...b.slice(12, 16));
    if (chunk === "VP8X" && b.length >= 30) { width = 1 + b[24] + (b[25] << 8) + (b[26] << 16); height = 1 + b[27] + (b[28] << 8) + (b[29] << 16); }
    else if (chunk === "VP8 " && b.length >= 30 && b[23] === 0x9d && b[24] === 0x01 && b[25] === 0x2a) { width = view.getUint16(26, true) & 0x3fff; height = view.getUint16(28, true) & 0x3fff; }
    else if (chunk === "VP8L" && b[20] === 0x2f) { const bits = view.getUint32(21, true); width = (bits & 0x3fff) + 1; height = ((bits >>> 14) & 0x3fff) + 1; }
  }
  if (!width || !height) throw new Error("无法读取图片尺寸，文件可能损坏或格式不支持");
  if (width * height > 45_000_000) throw new Error("源图超过 4500 万像素");
  return [width, height];
}

export async function inspectImage(file: File): Promise<{ type: string; width: number; height: number }> {
  if (file.size > 20 * 1024 * 1024) throw new Error("文件超过 20 MiB");
  const type = await sourceType(file);
  const [width, height] = await sourceDimensions(file, type);
  return { type, width, height };
}

function encode(canvas: HTMLCanvasElement, mime: string, quality?: number): Promise<Blob> {
  return new Promise((resolve, reject) => canvas.toBlob(blob => {
    if (!blob || blob.type !== mime) reject(new Error("浏览器不支持此格式编码"));
    else resolve(blob);
  }, mime, quality));
}

export async function processImage(file: File, options: ImageOptions): Promise<ImageResult> {
  const { type: originalType } = await inspectImage(file);
  let image: ImageBitmap;
  try { image = await createImageBitmap(file); } catch { throw new Error("图片解码失败或浏览器不支持此格式"); }
  const iw = image.width, ih = image.height;
  let canvas: HTMLCanvasElement | undefined;
  try {
    if (!iw || !ih || iw * ih > 45_000_000) throw new Error("源图超过 4500 万像素或无法解码");
    const w = options.mode === "resize" ? options.width : iw, h = options.mode === "resize" ? options.height : ih;
    if (options.mode === "resize" && (!Number.isInteger(w) || !Number.isInteger(h) || w < 1 || h < 1 || w > 8192 || h > 8192 || w * h > 45_000_000)) throw new Error("目标宽高须为 1–8192 的整数且不超过 4500 万像素");
    if (options.mode === "compress" && options.compression === "target" && (!Number.isInteger(options.targetKB) || options.targetKB < 20 || options.targetKB > 20000)) throw new Error("目标体积须为 20–20000 KB 的整数");
    const mime = options.format === "original" ? originalType : options.format;
    canvas = document.createElement("canvas"); canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("浏览器无法分配图片画布");
    if (options.mode === "resize" || mime === "image/jpeg") { ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, w, h); }
    const scale = options.mode === "resize" ? (options.fit === "cover" ? Math.max(w / iw, h / ih) : Math.min(w / iw, h / ih)) : 1;
    ctx.drawImage(image, (w - iw * scale) / 2, (h - ih * scale) / 2, iw * scale, ih * scale);
    let blob: Blob, note = "";
    if (options.mode === "compress" && options.compression === "target" && mime !== "image/png") {
      let low = 0.05, high = 0.95, best: Blob | undefined;
      for (let i = 0; i < 8; i++) { const q = (low + high) / 2; const candidate = await encode(canvas, mime, q); if (candidate.size <= options.targetKB * 1024) { best = candidate; low = q; } else high = q; }
      blob = best ?? await encode(canvas, mime, 0.05);
    } else blob = await encode(canvas, mime, options.mode === "resize" ? 0.9 : options.compression === "strong" ? 0.57 : 0.79);
    if (options.mode === "compress" && options.compression === "target" && blob.size > options.targetKB * 1024) note = "未达到目标体积，已显示实际大小";
    if (options.mode === "compress" && blob.size > file.size) note += " 输出不降反升，可下载原图";
    const ext = mime === "image/jpeg" ? "jpg" : mime === "image/png" ? "png" : "webp";
    const name = file.name.replace(/\.[^.]+$/, "").replace(/[\\/:*?"<>|\x00-\x1f]/g, "_").slice(0, 100) || "image";
    let sourcePreview: Blob | undefined, outputPreview: Blob | undefined;
    if (Math.max(iw * ih, w * h) > 12_000_000) {
      const preview = document.createElement("canvas");
      const renderPreview = async (source: CanvasImageSource, width: number, height: number) => {
        const scale = Math.min(1, 600 / Math.max(width, height));
        preview.width = Math.max(1, Math.round(width * scale)); preview.height = Math.max(1, Math.round(height * scale));
        const context = preview.getContext("2d"); if (!context) throw new Error("浏览器无法创建预览");
        context.drawImage(source, 0, 0, preview.width, preview.height);
        return encode(preview, "image/png");
      };
      try { sourcePreview = await renderPreview(image, iw, ih); outputPreview = await renderPreview(canvas, w, h); }
      finally { preview.width = 0; preview.height = 0; }
    }
    return { blob, name: `${name}-${options.mode === "resize" ? `${w}x${h}` : "compressed"}.${ext}`, width: w, height: h, sourceWidth: iw, sourceHeight: ih, note, sourcePreview, outputPreview };
  } finally { if (canvas) { canvas.width = 0; canvas.height = 0; } image.close(); }
}

export async function makeZip(results: ImageResult[], isCurrent: () => boolean = () => true): Promise<Blob> {
  if (results.reduce((total, result) => total + result.blob.size, 0) > MAX_BATCH_BYTES) throw new Error("批量结果超过 64 MiB，请分批处理");
  const used = new Set<string>(); const parts: BlobPart[] = [];
  const zip = new Zip((error, data) => { if (error) throw error; parts.push(data as Uint8Array<ArrayBuffer>); });
  try {
    for (const result of results) {
      const dot = result.name.lastIndexOf("."); const stem = result.name.slice(0, dot), ext = result.name.slice(dot);
      let name = result.name, n = 2; while (used.has(name.toLowerCase())) name = `${stem} (${n++})${ext}`;
      used.add(name.toLowerCase()); const entry = new ZipPassThrough(name); zip.add(entry);
      for (let offset = 0; offset < result.blob.size; offset += 256 * 1024) {
        if (!isCurrent()) throw new Error("处理结果已变化，请重新下载");
        const data = new Uint8Array(await result.blob.slice(offset, offset + 256 * 1024).arrayBuffer());
        if (!isCurrent()) throw new Error("处理结果已变化，请重新下载");
        entry.push(data, offset + data.length >= result.blob.size);
        await new Promise(resolve => setTimeout(resolve, 0));
      }
      if (!result.blob.size) entry.push(new Uint8Array(), true);
    }
    if (!isCurrent()) throw new Error("处理结果已变化，请重新下载");
    zip.end();
    return new Blob(parts, { type: "application/zip" });
  } finally { zip.terminate(); }
}
