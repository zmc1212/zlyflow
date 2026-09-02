export const PLAN_GENERATION_LABEL = "生成创作方案"
export const PLAN_GENERATION_HINT = "只产出剧本、画风、分镜、人物场景和声音方案，不会生成视频或配音音频。"
export const PLAN_GENERATION_SUCCESS = "创作方案已生成。定妆、出片和配音请到对应任务区提交。"
export const PLAN_GENERATION_FAILURE = "生成创作方案失败"
export const PLAN_GENERATION_CONNECTING = "正在连接创作方案生成"

export type BoardBatchMode = "still" | "preview" | "final"

export function plateBatchLabel(kind: "character" | "location", count: number): string {
  const base = kind === "location" ? "全部场景" : "全部定妆"
  return count > 0 ? `${base}（${count}）` : base
}

export function approveBatchLabel(kind: "location" | "prop" | "character", count: number): string {
  const base = kind === "location" ? "批准全部场景" : kind === "prop" ? "批准全部道具" : "批准全部定妆"
  return count > 0 ? `${base}（${count}）` : base
}

export function approveBatchConfirm(kind: "location" | "prop" | "character", count: number): {
  title: string
  countLabel: string
  costLabel: string
} {
  const noun = kind === "location" ? "场景母版" : kind === "prop" ? "道具转面" : "角色定妆"
  return {
    title: kind === "location" ? "批准全部场景" : kind === "prop" ? "批准全部道具" : "批准全部定妆",
    countLabel: `将批准 ${count} 个已生成成功的${noun}候选，每个取当前最新一版。`,
    costLabel: "不消耗算力；已批准或尚无成功候选的项会跳过。",
  }
}

export function plateBatchConfirm(kind: "character" | "location", total: number, pending: number): {
  title: string
  countLabel: string
  costLabel: string
} {
  const sceneOnly = kind === "location"
  const skip = Math.max(0, total - pending)
  return {
    title: sceneOnly ? "全部场景定妆" : "全部定妆",
    countLabel: `将为 ${total} 个${sceneOnly ? "场景" : "角色"}提交定妆图。`,
    costLabel: skip
      ? `已有定妆图的 ${skip} 个会跳过，预计提交 ${pending} 个 GRS 图片任务。`
      : `预计消耗：${total} 个 GRS 图片任务。`,
  }
}

export function boardBatchLabel(mode: BoardBatchMode, count: number): string {
  const base = mode === "still" ? "全部静帧" : mode === "preview" ? "全部预览" : "全部出片"
  return count > 0 ? `${base}（${count} 镜）` : base
}

export function boardBatchConfirm(mode: BoardBatchMode, count: number, title?: string): {
  title: string
  countLabel: string
  costLabel: string
} {
  const modeLabel = mode === "still" ? "静帧" : mode === "preview" ? "预览视频" : "终稿视频"
  return {
    title: title || (mode === "still" ? "全部静帧" : mode === "preview" ? "全部预览" : "全部出片"),
    countLabel: `将提交 ${count} 镜${modeLabel}。`,
    costLabel: mode === "still"
      ? `预计消耗：${count} 个 GRS 图片任务。`
      : `预计消耗：${count} 个本机 MiniMax H3 任务（${mode === "preview" ? "预览档" : "终稿档"}）。`,
  }
}

export function ttsBatchLabel(count: number): string {
  return count > 0 ? `生成全部配音（${count} 条）` : "生成全部配音"
}

export function ttsBatchConfirm(count: number): {
  title: string
  countLabel: string
  costLabel: string
} {
  return {
    title: "生成全部配音",
    countLabel: `将为 ${count} 条对白生成配音。`,
    costLabel: `预计消耗：${count} 次 TTS 调用；已有音频的镜头会重新生成。`,
  }
}

export function muxBatchLabel(count: number): string {
  return count > 0 ? `导出成片（${count} 镜）` : "导出成片"
}

export function muxBatchConfirm(count: number): {
  title: string
  countLabel: string
  costLabel: string
} {
  return {
    title: "导出成片",
    countLabel: `将把 ${count} 镜合成为一条成片。`,
    costLabel: "预计消耗：本机 ffmpeg 合成，不会再提交出片任务。失败、中断或停止的镜头不会进入成片。",
  }
}
