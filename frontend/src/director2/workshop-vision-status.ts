export type WorkshopVisionStatusSource = {
  vision_status?: string | null
  vision_model?: string | null
  vision_image_count?: number | string | null
}

export function workshopVisionStatusLine(source: WorkshopVisionStatusSource | null | undefined): string {
  const status = String(source?.vision_status || "").trim()
  const model = String(source?.vision_model || "").trim()
  const count = Number(source?.vision_image_count || 0)
  const imageCount = Number.isFinite(count) && count > 0 ? Math.floor(count) : 0
  if (status === "used") {
    const bits = ["已看图"]
    if (model) bits.push(model)
    if (imageCount) bits.push(`${imageCount} 张`)
    return bits.join(" · ")
  }
  if (status === "failed_text_fallback" || (status === "unavailable" && imageCount > 0)) {
    return "未看图，已用纯文本"
  }
  return ""
}

export function workshopPromptAsideLine(
  source: WorkshopVisionStatusSource | null | undefined,
  options?: { failed?: boolean },
): string {
  const bits = [workshopVisionStatusLine(source)]
  if (options?.failed) bits.push("写稿未通过校验")
  return bits.filter(Boolean).join(" · ")
}
