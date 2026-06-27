// Downscale an image in the browser before upload. Large originals (phone
// photos, renders) waste bandwidth and trip the server's 10 MB cap, and the
// consumers don't need the resolution: color match samples at ~200px, and
// Claude vision resizes reference images to ~1568px on its side. A resized copy
// matches for those uses, uploads fast, and stays under the cap.
//
// Re-encodes to WebP. Degrades gracefully — returns the original file when the
// browser lacks createImageBitmap (e.g. jsdom in tests) or anything fails.

const DEFAULT_MAX_DIM = 1600;
const DEFAULT_QUALITY = 0.9;

export async function downscaleForUpload(
  file: File,
  { maxDim = DEFAULT_MAX_DIM, quality = DEFAULT_QUALITY }: { maxDim?: number; quality?: number } = {},
): Promise<File> {
  if (typeof createImageBitmap !== "function") return file;
  try {
    const bmp = await createImageBitmap(file);
    const longest = Math.max(bmp.width, bmp.height);
    if (longest <= maxDim) { bmp.close?.(); return file; }
    const scale = maxDim / longest;
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bmp.width * scale);
    canvas.height = Math.round(bmp.height * scale);
    canvas.getContext("2d")?.drawImage(bmp, 0, 0, canvas.width, canvas.height);
    bmp.close?.();
    const blob = await new Promise<Blob | null>((res) =>
      canvas.toBlob(res, "image/webp", quality));
    if (!blob) return file;
    return new File([blob], "reference.webp", { type: "image/webp" });
  } catch {
    return file;
  }
}
