export type WorkshopH3GateKind = "need_cast" | "triptych_running" | "need_triptych" | "ready"

export type WorkshopH3GateBeat = {
  character_ids?: string[] | null
  scene_id?: string | null
  scene?: string | null
  triptych_url?: string | null
  triptych_panels?: { start?: string | null } | null
  triptych_status?: string | null
}

export function beatHasWorkshopTriptych(beat: WorkshopH3GateBeat | null | undefined): boolean {
  if (!beat) return false
  const url = String(beat.triptych_url || "").trim()
  const start = String(beat.triptych_panels?.start || "").trim()
  return Boolean(url || start)
}

export function workshopH3PromptGate(
  beat: WorkshopH3GateBeat | null | undefined,
  options: { triptychGenerating?: boolean } = {},
): WorkshopH3GateKind {
  if (!(beat?.character_ids || []).length || !String(beat?.scene_id || beat?.scene || "").trim()) {
    return "need_cast"
  }
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
  triptychRunning: "三联关键帧还在生成，完成后请先查看画面，再生成 H3 提示词",
  confirmTitle: "需要先生成三联关键帧",
  confirmContent:
    "写 H3 提示词前要先有本镜三联关键帧，模型才能按左、中、右格梳理画面。确认后先生成三联；生成完成后请查看画面，再手动点「生成 H3 提示词」。",
  confirmOk: "生成三联关键帧",
  queued: "三联关键帧已入队。完成后请查看画面，再点生成 H3 提示词",
  ready: "三联关键帧已生成，请查看画面后再点生成 H3 提示词",
  failed: "三联关键帧生成失败",
} as const
