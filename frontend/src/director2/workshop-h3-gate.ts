export type WorkshopH3GateKind = "need_cast" | "triptych_running" | "need_triptych" | "ready"

export type WorkshopH3GateBeat = {
  character_ids?: string[] | null
  scene_id?: string | null
  scene?: string | null
  triptych_url?: string | null
  triptych_panels?: { start?: string | null } | null
  triptych_status?: string | null
}

export function beatsMissingH3Prompt<T extends { h3_prompt?: string | null }>(beats: T[]): T[] {
  return (beats || []).filter((beat) => !String(beat.h3_prompt || "").trim())
}

export function beatHasWorkshopTriptych(beat: WorkshopH3GateBeat | null | undefined): boolean {
  if (!beat) return false
  const url = String(beat.triptych_url || "").trim()
  const start = String(beat.triptych_panels?.start || "").trim()
  return Boolean(url || start)
}

export function workshopH3PromptGate(
  beat: WorkshopH3GateBeat | null | undefined,
  options: { triptychGenerating?: boolean; requireTriptych?: boolean } = {},
): WorkshopH3GateKind {
  if (!(beat?.character_ids || []).length || !String(beat?.scene_id || beat?.scene || "").trim()) {
    return "need_cast"
  }
  if (!options.requireTriptych) return "ready"
  const status = String(beat?.triptych_status || "").trim().toLowerCase()
  if (
    options.triptychGenerating
    || ["queued", "preparing", "running", "storing"].includes(status)
  ) {
    return "triptych_running"
  }
  if (!beatHasWorkshopTriptych(beat)) return "need_triptych"
  return "ready"
}

export function workshopH3GenerateLabel(input: { generating?: boolean; hasPrompt?: boolean } = {}): string {
  if (input.generating) return "生成中"
  return input.hasPrompt ? "重新生成" : "生成 H3 提示词"
}

export const WORKSHOP_H3_TRIPTYCH_GATE = {
  needCast: "请先绑定出场角色和场景，再生成三联关键帧",
  triptychRunning: "关键帧正在生成，完成后可直接生成视频",
  confirmTitle: "需要先生成三联关键帧",
  confirmContent:
    "关键帧规划是可选能力，用于预先控制构图和动作。普通视频生成会直接使用已有资产参考图。",
  confirmOk: "生成三联关键帧",
  queued: "关键帧已入队，生成后可直接用于视频制作",
  ready: "关键帧已就绪，可直接生成视频",
  failed: "三联关键帧生成失败",
} as const
