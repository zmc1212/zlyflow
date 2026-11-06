export type WorkshopH3GateKind = "need_cast" | "ready"

export type WorkshopH3GateBeat = {
  character_ids?: string[] | null
  scene_id?: string | null
  scene?: string | null
}

export function beatsMissingH3Prompt<T extends { h3_prompt?: string | null }>(beats: T[]): T[] {
  return (beats || []).filter((beat) => !String(beat.h3_prompt || "").trim())
}

export function workshopH3PromptGate(beat: WorkshopH3GateBeat | null | undefined): WorkshopH3GateKind {
  if (!(beat?.character_ids || []).length || !String(beat?.scene_id || beat?.scene || "").trim()) {
    return "need_cast"
  }
  return "ready"
}

export function workshopH3GenerateLabel(input: { generating?: boolean; hasPrompt?: boolean } = {}): string {
  if (input.generating) return "生成中"
  return input.hasPrompt ? "重新生成" : "生成 H3 提示词"
}
