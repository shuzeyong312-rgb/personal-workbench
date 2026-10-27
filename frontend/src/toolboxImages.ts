import { zipSync } from "fflate";

export type ImageOptions = { mode: "compress" | "resize"; compression: "smart" | "strong" | "target"; targetKB: number; format: "original" | "image/jpeg" | "image/png" | "image/webp"; width: number; height: number; fit: "contain" | "cover" };
export type ImageResult = { blob: Blob; name: string; width: number; height: number; sourceWidth: number; sourceHeight: number; note: string };

export async function sourceType(file: File): Promise<string> {
  const b = new Uint8Array(await file.slice(0, 12).arrayBuffer());
  if (b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) return "image/jpeg";
  if ([137, 80, 78, 71, 13, 10, 26, 10].every((v, i) => b[i] === v)) return "image/png";
  if (String.fromCharCode(...b.slice(0, 4)) === "RIFF" && String.fromCharCode(...b.slice(8, 12)) === "WEBP") return "image/webp";
  throw new Error("文件不是支持的 JPG、PNG 或 WebP 图片");
}

function encode(canvas: HTMLCanvasElement, mime: string, quality?: number): Promise<Blob> {
  return new Promise((resolve, reject) => canvas.toBlob(blob => {
    if (!blob || blob.type !== mime) reject(new Error("浏览器不支持此格式编码"));
    else resolve(blob);
  }, mime, quality));
}

export async function processImage(file: File, options: ImageOptions): Promise<ImageResult> {
  if (file.size > 20 * 1024 * 1024) throw new Error("文件超过 20 MiB");
  const originalType = await sourceType(file);
  let image: ImageBitmap;
  try { image = await createImageBitmap(file); } catch { throw new Error("图片解码失败或浏览器不支持此格式"); }
  const iw = image.width, ih = image.height;
  try {
    if (!iw || !ih || iw * ih > 45_000_000) throw new Error("源图超过 4500 万像素或无法解码");
    const w = options.mode === "resize" ? options.width : iw, h = options.mode === "resize" ? options.height : ih;
    if (options.mode === "resize" && (!Number.isInteger(w) || !Number.isInteger(h) || w < 1 || h < 1 || w > 8192 || h > 8192 || w * h > 45_000_000)) throw new Error("目标宽高须为 1–8192 的整数且不超过 4500 万像素");
    if (options.mode === "compress" && options.compression === "target" && (!Number.isInteger(options.targetKB) || options.targetKB < 20 || options.targetKB > 20000)) throw new Error("目标体积须为 20–20000 KB 的整数");
    const mime = options.format === "original" ? originalType : options.format;
    const canvas = document.createElement("canvas"); canvas.width = w; canvas.height = h;
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
    return { blob, name: `${name}-${options.mode === "resize" ? `${w}x${h}` : "compressed"}.${ext}`, width: w, height: h, sourceWidth: iw, sourceHeight: ih, note };
  } finally { image.close(); }
}

export async function makeZip(results: ImageResult[]): Promise<Blob> {
  const used = new Set<string>(); const entries: Record<string, Uint8Array> = {};
  for (const result of results) {
    const dot = result.name.lastIndexOf("."); const stem = result.name.slice(0, dot), ext = result.name.slice(dot);
    let name = result.name, n = 2; while (used.has(name.toLowerCase())) name = `${stem} (${n++})${ext}`;
    used.add(name.toLowerCase()); entries[name] = new Uint8Array(await result.blob.arrayBuffer());
  }
  return new Blob([zipSync(entries)], { type: "application/zip" });
}
