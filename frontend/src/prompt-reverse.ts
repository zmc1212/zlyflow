import { requestJson } from "./api"

export const PROMPT_REVERSE_MAX_IMAGE_BYTES = 8 * 1024 * 1024

export type PromptReverseMediaType = "video" | "image"

export type PromptReverseResult = {
  chinese_prompt: string
  english_prompt: string
}

export function promptReverseImageError(file: File): string | null {
  if (!file.type.startsWith("image/")) return "提示词反推仅支持图片文件"
  if (file.size > PROMPT_REVERSE_MAX_IMAGE_BYTES) return "参考图超过 8MB，请压缩后再试"
  return null
}

export function normalizePromptReverseResult(data: unknown): PromptReverseResult {
  if (!data || typeof data !== "object") throw new Error("提示词反推结果格式异常，请稍后重试")
  const payload = data as Record<string, unknown>
  const chinese = String(payload.chinese_prompt ?? "").trim()
  const english = String(payload.english_prompt ?? "").trim()
  if (!chinese && !english) throw new Error("提示词反推结果为空，请重试或换一张参考图")
  return { chinese_prompt: chinese || english, english_prompt: english || chinese }
}

export async function reversePromptFromImage(
  csrfToken: string,
  file: File,
  mediaType: PromptReverseMediaType,
  hint = "",
): Promise<PromptReverseResult> {
  const form = new FormData()
  form.append("image", file)
  form.append("media_type", mediaType)
  const cleanHint = hint.trim()
  if (cleanHint) form.append("hint", cleanHint)
  const data = await requestJson<unknown>("/api/llm/reverse-prompt", {
    method: "POST",
    body: form,
    headers: { "X-CSRF-Token": csrfToken },
  })
  return normalizePromptReverseResult(data)
}

export function filesFromDataTransfer(files: FileList | File[] | null): File | null {
  const list = files ? Array.from(files) : []
  const image = list.find((file) => file.type.startsWith("image/"))
  return image ?? null
}
