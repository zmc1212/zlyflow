export type WorkflowDocumentLike = {
  id: string
  filename?: string | null
  input_mode?: string | null
  status?: string | null
  shot_plan_job_id?: string | null
  analysis?: Record<string, unknown> | null
}

export type WorkflowAssetLike = {
  kind?: string | null
}

export type WorkflowEpisodeLike = {
  id?: string | null
  episode_num?: number | null
  title?: string | null
  shots_count?: number | null
}

export type WorkflowStepId = "script" | "assets" | "shots" | "workshop"
export type WorkflowStepState = "done" | "current" | "pending"

export type WorkflowStep = {
  id: WorkflowStepId
  label: string
  state: WorkflowStepState
  detail: string
  running: boolean
}

export type WorkflowActionKind =
  | "import-script"
  | "check-script"
  | "draft-assets"
  | "plan-shots"
  | "planning"
  | "sync-episodes"
  | "open-workshop"

export type WorkflowAction = {
  kind: WorkflowActionKind
  title: string
  detail: string
  button: string
  documentId?: string
  episodeId?: string
  episodeShots?: number
}

export type WorkflowAssetCounts = {
  character: number
  scene: number
  prop: number
  total: number
}

export type WorkflowProgress = {
  steps: WorkflowStep[]
  completed: number
  total: number
  document: WorkflowDocumentLike | null
  action: WorkflowAction
  assets: WorkflowAssetCounts
  plan: {
    episodeCount: number
    shotCount: number
    planning: boolean
    plannedEpisodes: number
    pipeline: boolean
  }
  workshop: {
    episodeCount: number
    shotCount: number
    episodeId: string | null
    episodeLabel: string
  }
}

const STEP_ORDER: WorkflowStepId[] = ["script", "assets", "shots", "workshop"]
const STEP_LABELS: Record<WorkflowStepId, string> = {
  script: "剧本",
  assets: "资产",
  shots: "镜头规划",
  workshop: "剧集工坊",
}

type EpisodePlan = {
  shots: unknown[]
  shots_source: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value)
}

function readEpisodePlans(document: WorkflowDocumentLike | null): EpisodePlan[] {
  const raw = document?.analysis?.episodes
  if (!Array.isArray(raw)) return []
  return raw.filter(isRecord).map((episode) => ({
    shots: Array.isArray(episode.shots) ? episode.shots : [],
    shots_source: String(episode.shots_source || "").toLowerCase(),
  }))
}

export function countWorkflowAssets(assets: WorkflowAssetLike[]): WorkflowAssetCounts {
  const counts: WorkflowAssetCounts = { character: 0, scene: 0, prop: 0, total: 0 }
  for (const asset of assets || []) {
    if (asset.kind === "character") counts.character += 1
    else if (asset.kind === "scene") counts.scene += 1
    else if (asset.kind === "prop") counts.prop += 1
  }
  counts.total = counts.character + counts.scene + counts.prop
  return counts
}

export function assetDraftPrompt(filename?: string | null): string {
  const name = String(filename || "").trim()
  return `继续下一步：请根据${name ? `剧本《${name}》` : "当前工程内容库里的剧本"}，完整梳理登场角色、场景和道具，生成可直接采纳的资产设定草稿，用于补齐资产库。`
}

function assetSummary(counts: WorkflowAssetCounts): string {
  const parts = [
    counts.character ? `${counts.character} 角色` : "",
    counts.scene ? `${counts.scene} 场景` : "",
    counts.prop ? `${counts.prop} 道具` : "",
  ].filter(Boolean)
  return parts.join(" · ") || "还没有资产设定"
}

function episodeCountLabel(count: number): string {
  return count === 1 ? "第 1 集" : `${count} 集`
}

function workshopEntry(episodes: WorkflowEpisodeLike[]): { episodeId: string | null; episodeNum: number; label: string; shots: number } {
  const ordered = [...episodes].sort((a, b) => Number(a.episode_num || 0) - Number(b.episode_num || 0))
  const target = ordered.find((episode) => Number(episode.shots_count || 0) > 0) || ordered[0]
  if (!target) return { episodeId: null, episodeNum: 0, label: "", shots: 0 }
  const episodeNum = Number(target.episode_num || 0)
  const title = String(target.title || "").trim()
  return {
    episodeId: target.id ? String(target.id) : null,
    episodeNum,
    label: episodeNum ? `第 ${episodeNum} 集${title ? ` · ${title}` : ""}` : title,
    shots: Number(target.shots_count || 0),
  }
}

function scriptDetail(document: WorkflowDocumentLike | null, episodes: EpisodePlan[], pipeline: boolean): string {
  if (!document) return "还没有剧本文档"
  const shots = episodes.reduce((sum, episode) => sum + episode.shots.length, 0)
  if (pipeline) return "由 AI 流程生成"
  if (!episodes.length) return "已导入，等待解析分集"
  return `${episodeCountLabel(episodes.length)} · ${shots} 个分镜`
}

function shotDetail(document: WorkflowDocumentLike | null, episodes: EpisodePlan[], planned: number, pipeline: boolean, planning: boolean): string {
  if (!document) return "等待剧本"
  if (pipeline) return "AI 流程已生成出片镜头"
  if (planning) return "正在按集规划出片镜头"
  if (!episodes.length) return "等待剧本解析出分集"
  const shots = episodes.reduce((sum, episode) => sum + episode.shots.length, 0)
  if (planned === episodes.length) return `${episodeCountLabel(episodes.length)} · ${shots} 个出片镜头`
  if (planned > 0) return `${planned}/${episodes.length} 集已规划`
  return `${episodeCountLabel(episodes.length)}待规划`
}

export function buildWorkflowProgress(input: {
  documents: WorkflowDocumentLike[]
  assets: WorkflowAssetLike[]
  episodes: WorkflowEpisodeLike[]
}): WorkflowProgress {
  const documents = input.documents || []
  const assets = countWorkflowAssets(input.assets || [])
  const workshopEpisodes = input.episodes || []
  const document = documents[0] || null
  const episodes = readEpisodePlans(document)
  const pipeline = String(document?.input_mode || "").toLowerCase() === "ai_pipeline"
  const planning = !!document && !pipeline && (!!document.shot_plan_job_id || String(document.status || "").toLowerCase() === "planning")
  const plannedEpisodes = episodes.filter((episode) => episode.shots_source === "llm").length
  const shotCount = episodes.reduce((sum, episode) => sum + episode.shots.length, 0)
  const workshopShotCount = workshopEpisodes.reduce((sum, episode) => sum + Number(episode.shots_count || 0), 0)
  const workshopTarget = workshopEntry(workshopEpisodes)

  const scriptDone = !!document && (pipeline || episodes.length > 0)
  const assetsDone = assets.total > 0
  const shotsDone = !!document && (pipeline || (episodes.length > 0 && plannedEpisodes === episodes.length))
  const workshopDone = workshopEpisodes.length > 0

  const done: Record<WorkflowStepId, boolean> = { script: scriptDone, assets: assetsDone, shots: shotsDone, workshop: workshopDone }
  const details: Record<WorkflowStepId, string> = {
    script: scriptDetail(document, episodes, pipeline),
    assets: assetSummary(assets),
    shots: shotDetail(document, episodes, plannedEpisodes, pipeline, planning),
    workshop: workshopDone ? `${episodeCountLabel(workshopEpisodes.length)} · ${workshopShotCount} 个分镜` : "还没有同步分集",
  }
  let currentAssigned = false
  const steps: WorkflowStep[] = STEP_ORDER.map((id) => {
    const isDone = done[id]
    const isCurrent = !isDone && !currentAssigned
    if (isCurrent) currentAssigned = true
    return {
      id,
      label: STEP_LABELS[id],
      state: isDone ? "done" : isCurrent ? "current" : "pending",
      detail: details[id],
      running: id === "shots" && planning,
    }
  })

  let action: WorkflowAction
  if (!document) {
    action = {
      kind: "import-script",
      title: "先准备剧本",
      detail: "导入剧本文档，或直接描述创意让助手写第一集，采纳后会写入内容库。",
      button: "去导入剧本",
    }
  } else if (!scriptDone) {
    action = {
      kind: "check-script",
      title: "剧本还没有解析出分集",
      detail: "文档已写入内容库，但没有可用的分集镜头。到内容库检查剧本格式，必要时重新导入。",
      button: "去内容库检查",
    }
  } else if (!assetsDone) {
    action = {
      kind: "draft-assets",
      title: "补齐资产设定",
      detail: "按剧本提取角色、场景和道具，生成可一键采纳的资产草稿。",
      button: "生成资产设定",
    }
  } else if (planning) {
    action = {
      kind: "planning",
      title: "正在规划出片镜头",
      detail: "按集生成中，完成后这里会自动更新，无需停留在本页等待。",
      button: "规划中",
      documentId: document.id,
    }
  } else if (!shotsDone) {
    action = {
      kind: "plan-shots",
      title: "规划出片镜头",
      detail: plannedEpisodes > 0
        ? `还有 ${episodes.length - plannedEpisodes} 集沿用剧本切镜，继续规划会消耗模型额度。`
        : `把剧本切镜改写成可出片的镜头清单${episodes.length > 1 ? `（共 ${episodes.length} 集）` : ""}，会消耗模型额度。`,
      button: plannedEpisodes > 0 ? "继续规划剩余分集" : "规划出片镜头",
      documentId: document.id,
    }
  } else if (!workshopDone) {
    action = episodes.length
      ? {
          kind: "sync-episodes",
          title: "同步到剧集工坊",
          detail: `出片镜头已就绪，把 ${episodeCountLabel(episodes.length)}同步到剧集工坊后即可逐镜出片。`,
          button: "同步到剧集工坊",
          documentId: document.id,
        }
      : {
          kind: "check-script",
          title: "没有可同步的分集",
          detail: "剧本已由 AI 流程处理，但内容库里没有可同步的分集镜头，请到内容库检查。",
          button: "去内容库检查",
        }
  } else {
    const shootable = !!workshopTarget.episodeId && workshopTarget.shots > 0
    action = {
      kind: "open-workshop",
      title: "分段提交逐镜任务",
      detail: workshopTarget.episodeId
        ? shootable
          ? `${workshopTarget.label}已就绪，为 ${workshopTarget.shots} 个镜头分别提交独立任务，可逐个查看和重做；整集出片请到剧集工坊手动操作。`
          : `${workshopTarget.label}还没有分镜，进入工坊补充分镜后再出片。`
        : "剧本、资产、镜头和剧集都已就绪，去剧集工坊生成 H3 提示词与视频。",
      button: shootable
        ? `分段提交 ${workshopTarget.shots} 个镜头`
        : workshopTarget.episodeId
          ? (workshopTarget.episodeNum ? `进入第 ${workshopTarget.episodeNum} 集出片` : "进入本集出片")
          : "去剧集工坊出片",
      episodeId: workshopTarget.episodeId || undefined,
      episodeShots: workshopTarget.episodeId ? workshopTarget.shots : undefined,
    }
  }

  return {
    steps,
    completed: STEP_ORDER.filter((id) => done[id]).length,
    total: STEP_ORDER.length,
    document,
    action,
    assets,
    plan: { episodeCount: episodes.length, shotCount, planning, plannedEpisodes, pipeline },
    workshop: { episodeCount: workshopEpisodes.length, shotCount: workshopShotCount, episodeId: workshopTarget.episodeId, episodeLabel: workshopTarget.label },
  }
}
