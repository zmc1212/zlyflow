// 工坊手动出片前置守卫 —— 把「一键出片」入口的自动补齐能力接到工坊的
// 「生成本镜 / 生成选中 / 生成整集」提交路径：提交前先跑同一套前置检查，
// 能自动修复的（场景匹配绑定、新建场景卡、补主视图、锁定/补生成造型）
// 经用户一次确认后自动补齐再提交，只有真正修不了的才提示手动处理。
import {
  episodeShootPrepLines,
  evaluateEpisodeShootPreflight,
  hasPaidShootPrep,
  type EpisodeShootPreflight,
} from "./episode-shoot-preflight"
import { prepareEpisodeShootAssets, type ShootPrepApi, type ShootPrepProgress } from "./episode-shoot-prep"
import type { Director2Asset, Director2Beat } from "../api"

export type WorkshopShootGuardInput = {
  projectId: string
  episodeId: string
  beats: Director2Beat[]
  assets: Director2Asset[]
  scopeBeatIds?: string[] | null
  api: ShootPrepApi
  confirm: (plan: EpisodeShootPreflight, paid: boolean) => Promise<boolean>
  onProgress?: (progress: ShootPrepProgress) => void
}

export type WorkshopShootGuardResult =
  | { status: "ready"; beats: Director2Beat[]; generated: number }
  | { status: "cancelled" }
  | { status: "blocked"; message: string; needsWorkshop?: boolean }

export async function ensureWorkshopShootReady(input: WorkshopShootGuardInput): Promise<WorkshopShootGuardResult> {
  const scope = input.scopeBeatIds && input.scopeBeatIds.length
    ? new Set(input.scopeBeatIds.map(String))
    : null
  const targetBeats = (input.beats || []).filter((beat) => !scope || scope.has(String(beat.id || "")))
  if (!targetBeats.length) return { status: "ready", beats: input.beats, generated: 0 }
  const check = evaluateEpisodeShootPreflight({ beats: targetBeats, assets: input.assets })
  if (check.ready) return { status: "ready", beats: input.beats, generated: 0 }
  if (!check.canFix) {
    return { status: "blocked", message: check.blocking.join("\n"), needsWorkshop: true }
  }
  const paid = hasPaidShootPrep(check)
  const confirmed = await input.confirm(check, paid)
  if (!confirmed) return { status: "cancelled" }
  const prepared = await prepareEpisodeShootAssets({
    projectId: input.projectId,
    episodeId: input.episodeId,
    beats: targetBeats,
    assets: input.assets,
    plan: check,
    scopeBeatIds: scope ? [...scope] : null,
    api: input.api,
    onProgress: input.onProgress,
  })
  if (!prepared.ok) {
    return { status: "blocked", message: prepared.message || "补齐出片素材失败" }
  }
  const detail = await input.api.getEpisodeDetail(input.projectId, input.episodeId)
  return { status: "ready", beats: detail.beats || input.beats, generated: prepared.generated }
}

export function workshopShootPrepConfirmLines(plan: EpisodeShootPreflight, paid: boolean): string[] {
  const lines = ["提交前将自动补齐：", ...episodeShootPrepLines(plan)]
  if (paid) lines.push("补齐素材会调用生图模型，每张约 1-3 分钟；完成后自动继续提交视频任务。")
  return lines
}
