/**
 * 生成页「开始生成」按钮的禁用原因。
 *
 * 按钮在缺少必填素材时保持禁用，但必须告诉用户缺什么；
 * 这里的文案同时用于按钮 tooltip、行内提示和 Ctrl/⌘ + Enter 的反馈。
 */

export type ReferenceMode = "none" | "keyframes" | "collection" | "fixed"

export type ReferenceRequirementInput = {
  referenceMode: ReferenceMode
  minReferences: number
  maxReferences: number
  /** 当前参考素材总数（图片 + 音频 + 视频）。 */
  referenceCount: number
  /** 当前参考图片数量。 */
  imageCount: number
  hasAudioReference: boolean
  hasVideoReference: boolean
  referenceLabels?: string[]
  acceptsAudioReference?: boolean
  acceptsVideoReference?: boolean
}

export type SubmitRequirementInput = ReferenceRequirementInput & {
  loading?: boolean
  available?: boolean
  unavailableReason?: string | null
  prompt: string
  defaultPrompt?: string | null
  motionVideoError?: string
  optionError?: string
  pending?: boolean
  optimizing?: boolean
  inspectingOtherUser?: boolean
}

const labelAt = (labels: string[] | undefined, index: number, fallback: string) =>
  (labels?.[index] || fallback).replace(/[（(]\s*(?:可选|必填)\s*[）)]\s*$/, "").trim()

/**
 * 只返回参考素材不足时的提示；素材满足要求时返回空字符串。
 * 图片类工作流给出还差几张，动作/音频类工作流直接说要补哪一份素材。
 */
export function referenceRequirementHint(input: ReferenceRequirementInput): string {
  if (input.referenceMode === "none") return ""
  const gap = input.minReferences - input.referenceCount
  if (gap <= 0) return ""

  if (input.acceptsVideoReference) {
    if (input.imageCount === 0 && !input.hasVideoReference) {
      return `先上传${labelAt(input.referenceLabels, 0, "角色形象图")}和${labelAt(input.referenceLabels, 1, "动作参考视频")}，才能开始生成`
    }
    if (input.imageCount === 0) return `先上传${labelAt(input.referenceLabels, 0, "角色形象图")}，才能开始生成`
    if (!input.hasVideoReference) return `先上传${labelAt(input.referenceLabels, 1, "动作参考视频")}，才能开始生成`
  }

  if (input.acceptsAudioReference) {
    if (input.imageCount === 0) return `先上传${labelAt(input.referenceLabels, 0, "人物形象图")}，才能开始生成`
    if (!input.hasAudioReference) return `先上传${labelAt(input.referenceLabels, 1, "口播音频（5 秒以内）")}，才能开始生成`
  }

  if (input.referenceMode === "keyframes") return "首帧为必填，上传后即可开始生成"

  if (input.referenceMode === "fixed") {
    return `还需要 ${gap} 份${labelAt(input.referenceLabels, input.referenceCount, "参考图")}，才能开始生成`
  }

  return `还需上传 ${gap} 张参考图（至少 ${input.minReferences} 张），才能开始生成`
}

/** 按钮被禁用时的唯一原因；为空表示可以提交。 */
export function submitBlockReason(input: SubmitRequirementInput): string {
  if (input.inspectingOtherUser) return "当前为他人任务，无法提交"
  if (input.loading) return "工作流正在加载"
  if (input.available === false) return input.unavailableReason?.trim() || "当前工作流暂不可用"
  if (input.optimizing) return "正在润色提示词…"
  if (input.pending) return "正在提交…"

  const referenceHint = referenceRequirementHint(input)
  if (referenceHint) return referenceHint

  if (!input.prompt.trim() && !(input.defaultPrompt ?? "").trim()) return "写一句创作提示词后即可开始生成"

  if (input.referenceCount > input.maxReferences) {
    return input.acceptsVideoReference
      ? `参考素材最多 ${input.maxReferences} 份，请先移除多余素材`
      : `参考图最多 ${input.maxReferences} 张，请先移除多余图片`
  }

  if (input.motionVideoError) return input.motionVideoError
  if (input.optionError) return input.optionError
  return ""
}
