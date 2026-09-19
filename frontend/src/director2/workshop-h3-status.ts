export type WorkshopH3StatusInput = {
  generating: boolean
  failed: boolean
  editing: boolean
  dirty: boolean
  savedPrompt: string
  source?: string | null
}

export function workshopH3StatusLabel(input: WorkshopH3StatusInput): string {
  if (input.generating) return "生成中"
  if (input.failed && !input.editing) return "生成失败"
  if (input.editing && input.dirty) return "未保存"
  if (!String(input.savedPrompt || "").trim()) return "未填写"
  if (input.source === "manual") return "已保存"
  return "已生成"
}

export function shouldShowWorkshopPromptLive(input: {
  generating: boolean
  failed: boolean
  editing?: boolean
  liveText: string
}): boolean {
  if (input.generating) return true
  if (input.editing) return false
  return Boolean(input.failed && String(input.liveText || "").trim())
}

export function workshopFailedLiveText(input: {
  liveText?: string
  streamText?: string
  authorEnDraft?: string
  authorZhDraft?: string
}): string {
  return String(
    input.liveText
    || input.streamText
    || input.authorEnDraft
    || input.authorZhDraft
    || "",
  )
}
