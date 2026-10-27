export const CLOUD_THUMBNAIL_WIDTH = 640

// cloud_url 只由持久化对象存储（当前为七牛云）产生，可安全追加图片处理参数；
// 处理失败时调用方回退到原图或裸视频。
export function cloudThumbnailSrc(kind: "image" | "video", cloudUrl?: string | null): string | null {
  const source = String(cloudUrl || "").trim()
  if (!/^https?:\/\//i.test(source)) return null
  const separator = source.includes("?") ? "&" : "?"
  const operation = kind === "video"
    ? `vframe/jpg/offset/1/w/${CLOUD_THUMBNAIL_WIDTH}`
    : `imageView2/2/w/${CLOUD_THUMBNAIL_WIDTH}/format/webp`
  return `${source}${separator}${operation}`
}
