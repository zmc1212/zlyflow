export const PLAN_GENERATION_LABEL = "生成创作方案"
export const PLAN_GENERATION_HINT = "只产出剧本、画风、分镜、人物场景和声音方案，不会生成视频或配音音频。"
export const PLAN_GENERATION_SUCCESS = "创作方案已生成。定妆、出片和配音请到对应任务区提交。"
export const PLAN_GENERATION_FAILURE = "生成创作方案失败"
export const PLAN_GENERATION_CONNECTING = "正在连接创作方案生成"

export const SCRIPT_STREAM_TITLE = "AI 导演正在创作"
export const SCRIPT_STREAM_CANCEL_LABEL = "取消生成"
export const SCRIPT_HISTORY_TITLE = "AI 导演创作记录"
export const SCRIPT_TASK_ROWS_TITLE = "生成任务"
export const SCRIPT_COMPLETION_TITLE = "创作方案已完成"
export const SCRIPT_COMPLETION_FAILED_PREFIX = "部分步骤未完成："
export const SCRIPT_NEXT_STORYBOARD = "进入分镜设计"
export const SCRIPT_NEXT_REGENERATE = "重新生成"
export const SCRIPT_ART_BLOCK_TITLE = "美术风格"
export const SCRIPT_ART_CHANGE_LABEL = "更换画风"
export const SCRIPT_ART_PICKER_TITLE = "选择美术风格"
export const SCRIPT_ART_CHANGE_HINT = "画风已更新，点击「重新生成」可按新画风重跑创作方案。"
export const SCRIPT_STREAM_WRITING_LABELS: Record<"title" | "summary" | "fullStory", string> = {
  title: "正在写：片名",
  summary: "正在写：一句话梗概",
  fullStory: "正在写：完整故事",
}
export const SCRIPT_STREAM_STATE_LABELS: Record<"done" | "cancelled" | "error", string> = {
  done: "创作完成",
  cancelled: "已取消生成",
  error: "生成失败",
}
export const SCRIPT_CLARIFY_TITLE = "AI 导演正在规划你的创意"
export const SCRIPT_CLARIFY_HINT = "回答或跳过下面的问题，剧本会按你选择的方向写。"
export const SCRIPT_CLARIFY_PROGRESS = (index: number, total: number) => `创作方向 ${index + 1}/${total}`
export const SCRIPT_CLARIFY_SKIP_ONE = "跳过这题"
export const SCRIPT_CLARIFY_SKIP_ALL = "跳过全部，直接生成"
export const SCRIPT_CLARIFY_CUSTOM = "自己写…"
export const SCRIPT_CLARIFY_CUSTOM_PLACEHOLDER = "输入你的想法"
export const SCRIPT_CLARIFY_SUBMIT = "按这个方向开拍"
export const SCRIPT_DIRECTION_LABEL = "创作方向"

export const SCRIPT_DOCUMENT_EDIT_LABEL = "编辑剧本"
export const SCRIPT_DOCUMENT_EDIT_DONE_LABEL = "完成编辑"
export const SCRIPT_DOCUMENT_NEXT_LABEL = "进入分镜设计"
export const SCRIPT_DOCUMENT_STORY_HINT = "分镜将严格按「完整故事」拆解，改完记得继续。"
export const SCRIPT_EMPTY_TITLE = "从一句创意开始"
export const SCRIPT_EMPTY_HINT = "在下方输入你的故事创意，点击发送，AI 导演会先和你确认创作方向，再逐步写出片名、梗概和完整故事。"
export const SCRIPT_PROM_BAR_HINT = "Enter 发送，Shift+Enter 换行；生成方案只整理创意，不会自动消耗定妆、视频或配音额度。"
export const SCRIPT_PROM_BAR_PLACEHOLDER = "例如：雨夜里侦探穿过霓虹暗巷，追上一个撑红伞的女人。"
export const SCRIPT_PROM_BAR_CLARIFY_PLACEHOLDER = "回答上方的问题以继续…"
export const SCRIPT_USER_BUBBLE_LABEL = "你的创意"
export const SCRIPT_IDEA_EXAMPLES = [
  "程序猿面对AI编程的冲击，从抗拒到拥抱，最后人机协作拿下年度项目",
  "不负恩情不负卿：乱世中一个镖师要在忠义与爱情之间做出抉择",
  "外卖骑手在暴雨夜送出一份改变他人生的订单",
]

export const BATCH_PROMPT_PLACEHOLDER = "输入短视频主题，例如：办公室久坐的人如何用 60 秒学会肩颈拉伸"
export const BATCH_PROMPT_HINT = "在下方输入主题并发送，会按所选工作流并行裂变多条脚本并提交文生视频。"

export type BoardBatchMode = "still" | "preview" | "final" | "custom"

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
  const base = mode === "still" ? "全部静帧" : mode === "preview" ? "全部预览" : mode === "custom" ? "全部自定义" : "全部出片"
  return count > 0 ? `${base}（${count} 镜）` : base
}

export function boardBatchConfirm(mode: BoardBatchMode, count: number, title?: string): {
  title: string
  countLabel: string
  costLabel: string
} {
  const modeLabel = mode === "still" ? "静帧" : mode === "preview" ? "预览视频" : mode === "custom" ? "自定义视频" : "终稿视频"
  const passLabel = mode === "preview" ? "预览档" : mode === "custom" ? "自定义（终稿通道）" : "终稿档"
  return {
    title: title || (mode === "still" ? "全部静帧" : mode === "preview" ? "全部预览" : mode === "custom" ? "全部自定义生成" : "全部出片"),
    countLabel: `将提交 ${count} 镜${modeLabel}。`,
    costLabel: mode === "still"
      ? `预计消耗：${count} 个 GRS 图片任务。`
      : `预计消耗：${count} 个本机 MiniMax H3 任务（${passLabel}）。`,
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
