import type { LucideIcon } from "lucide-react"
import {
  Boxes, Clapperboard, Eraser, Film, Frame, ImagePlus, Layers, Mic, RefreshCw, Repeat2, Scissors,
  ScanFace, Settings2, Sparkles, Trash2, Video, WandSparkles,
} from "lucide-react"
import {
  IMAGE_BACKGROUND_REMOVE_WORKFLOW,
  IMAGE_ERASER_WORKFLOW,
  IMAGE_INPAINT_WORKFLOW,
  IMAGE_LAYER_SPLIT_WORKFLOW,
  IMAGE_OUTPAINT_WORKFLOW,
  photoEditWorkflowChoices,
} from "../generation/image-edit"
import { FACE_RESTORE_WORKFLOW } from "../generation/face-restore"
import { INPAINT_WORKFLOW } from "../generation/inpaint"
import { LIP_SYNC_WORKFLOW } from "../generation/lip-sync"
import { UPSCALE_ENGINE_RTX, UPSCALE_ENGINE_SEEDVR2 } from "../generation/upscale"
import { PATHS } from "../paths"
import { mediaHandoffPath, type MediaHandoffSource, type MediaKind } from "../media-handoff"

export type MediaActionId =
  | "reference" | "photo-edit" | "inpaint" | "erase" | "cutout" | "layer-split" | "outpaint" | "to-video"
  | "upscale" | "retake" | "face-restore" | "lip-sync"
  | "canvas" | "jianying" | "re-edit" | "regenerate" | "params" | "remove"

/** `bar` = 悬浮工具条图标；`more` = 「更多」下拉；两者都由本注册表决定顺序与可见性。 */
export type MediaActionSlot = "bar" | "more"

export type MediaActionMode = { id: string; name?: string; media_type?: string; available?: boolean; executor?: string }

/** 站内动作（下载以外的落地方式）由宿主提供处理器，注册表只负责决定要不要出现。 */
export type MediaActionHost = {
  reference?: boolean
  canvas?: boolean
  jianying?: boolean
  params?: boolean
  remove?: boolean
  reEdit?: boolean
  regenerate?: boolean
  createVideo?: boolean
}

export type MediaActionInput = {
  kind: MediaKind
  /** 定位符缺失（例如查看他人任务）时，所有工具页动作自动收起。 */
  source: MediaHandoffSource | null
  modes: MediaActionMode[] | null | undefined
  host?: MediaActionHost
  inspectingOtherUser?: boolean
}

export type MediaActionItem = {
  id: MediaActionId
  label: string
  icon: LucideIcon
  slot: MediaActionSlot
  /** 工具页交接链接；站内动作为 null，由宿主按 id 接线。 */
  href: string | null
  danger?: boolean
}

/** 悬浮工具条只放 5 个图标，多出来的按声明顺序降级进「更多」。 */
export const MEDIA_ACTION_BAR_LIMIT = 5

type Definition = {
  id: MediaActionId
  kind: MediaKind
  label: string
  icon: LucideIcon
  slot: MediaActionSlot
  toolPath?: string
  available?: (modes: MediaActionMode[]) => boolean
  native?: keyof MediaActionHost
  ownerOnly?: boolean
  danger?: boolean
}

/**
 * 这几个工作流在后端注册表里对创作目录隐藏（hidden_from_catalog），`/api/modes` 不返回它们，
 * 但工具首页一直按「已上线」展示；卡片动作沿用同一判定，引擎真正不可用时由工具页给出原因。
 */
const HIDDEN_TOOL_WORKFLOWS = new Set<string>([UPSCALE_ENGINE_RTX, UPSCALE_ENGINE_SEEDVR2, FACE_RESTORE_WORKFLOW, LIP_SYNC_WORKFLOW])

const toolWorkflow = (...ids: string[]) => (modes: MediaActionMode[]) => ids.some((id) => {
  const mode = modes.find((entry) => entry.id === id)
  if (mode) return mode.available !== false
  return HIDDEN_TOOL_WORKFLOWS.has(id)
})

/** 声明顺序即展示顺序：越靠前越常用。 */
const DEFINITIONS: Definition[] = [
  { id: "reference", kind: "image", label: "用作参考图", icon: ImagePlus, slot: "bar", native: "reference" },
  { id: "photo-edit", kind: "image", label: "图片编辑", icon: WandSparkles, slot: "bar", toolPath: PATHS.toolPhotoEdit, available: (modes) => photoEditWorkflowChoices(modes).length > 0 },
  { id: "inpaint", kind: "image", label: "局部重绘", icon: Sparkles, slot: "bar", toolPath: PATHS.toolImageInpaint, available: toolWorkflow(IMAGE_INPAINT_WORKFLOW) },
  { id: "cutout", kind: "image", label: "去背景", icon: Scissors, slot: "bar", toolPath: PATHS.toolImageBgRemove, available: toolWorkflow(IMAGE_BACKGROUND_REMOVE_WORKFLOW) },
  { id: "to-video", kind: "image", label: "生成视频", icon: Film, slot: "bar", native: "createVideo" },
  { id: "erase", kind: "image", label: "消除笔", icon: Eraser, slot: "bar", toolPath: PATHS.toolImageEraser, available: toolWorkflow(IMAGE_ERASER_WORKFLOW) },
  { id: "outpaint", kind: "image", label: "扩图", icon: Frame, slot: "more", toolPath: PATHS.toolImageOutpaint, available: toolWorkflow(IMAGE_OUTPAINT_WORKFLOW) },
  { id: "layer-split", kind: "image", label: "图层分离", icon: Layers, slot: "more", toolPath: PATHS.toolImageLayerSplit, available: toolWorkflow(IMAGE_LAYER_SPLIT_WORKFLOW) },
  { id: "canvas", kind: "image", label: "加入画布", icon: Boxes, slot: "more", native: "canvas" },

  { id: "reference", kind: "video", label: "用作参考视频", icon: Video, slot: "bar", native: "reference" },
  { id: "upscale", kind: "video", label: "视频超清", icon: Sparkles, slot: "bar", toolPath: PATHS.toolVideoUpscale, available: toolWorkflow(UPSCALE_ENGINE_RTX, UPSCALE_ENGINE_SEEDVR2) },
  { id: "retake", kind: "video", label: "局部重拍", icon: Eraser, slot: "bar", toolPath: PATHS.toolPartialRetake, available: toolWorkflow(INPAINT_WORKFLOW) },
  { id: "face-restore", kind: "video", label: "人脸高清修复", icon: ScanFace, slot: "bar", toolPath: PATHS.toolFaceRestore, available: toolWorkflow(FACE_RESTORE_WORKFLOW), ownerOnly: true },
  { id: "lip-sync", kind: "video", label: "口型同步", icon: Mic, slot: "bar", toolPath: PATHS.toolLipSync, available: toolWorkflow(LIP_SYNC_WORKFLOW) },
  { id: "canvas", kind: "video", label: "加入画布", icon: Layers, slot: "more", native: "canvas" },
  { id: "jianying", kind: "video", label: "导出剪映", icon: Clapperboard, slot: "more", native: "jianying" },

  { id: "re-edit", kind: "image", label: "重新编辑", icon: Repeat2, slot: "more", native: "reEdit" },
  { id: "re-edit", kind: "video", label: "重新编辑", icon: Repeat2, slot: "more", native: "reEdit" },
  { id: "regenerate", kind: "image", label: "再次生成", icon: RefreshCw, slot: "more", native: "regenerate" },
  { id: "regenerate", kind: "video", label: "再次生成", icon: RefreshCw, slot: "more", native: "regenerate" },
  { id: "params", kind: "image", label: "查看运行参数", icon: Settings2, slot: "more", native: "params" },
  { id: "params", kind: "video", label: "查看运行参数", icon: Settings2, slot: "more", native: "params" },
  { id: "remove", kind: "image", label: "删除任务", icon: Trash2, slot: "more", native: "remove", danger: true },
  { id: "remove", kind: "video", label: "删除任务", icon: Trash2, slot: "more", native: "remove", danger: true },
]

/**
 * 结果卡片悬浮工具条与全屏预览侧栏共用的动作表。
 * 两处都从这里取，避免「预览里有、卡片上没有」这类漂移；工具页动作还要求注册表里该工作流可用。
 */
export function mediaActions(input: MediaActionInput): MediaActionItem[] {
  const modes = input.modes ?? []
  const host = input.host ?? {}
  const items: MediaActionItem[] = []
  for (const definition of DEFINITIONS) {
    if (definition.kind !== input.kind) continue
    if (definition.ownerOnly && input.inspectingOtherUser) continue
    if (definition.native) {
      if (!host[definition.native]) continue
      items.push({ id: definition.id, label: definition.label, icon: definition.icon, slot: definition.slot, href: null, danger: definition.danger })
      continue
    }
    const href = mediaHandoffPath(definition.toolPath ?? "", input.source)
    if (!href || !definition.available?.(modes)) continue
    items.push({ id: definition.id, label: definition.label, icon: definition.icon, slot: definition.slot, href, danger: definition.danger })
  }

  let barCount = 0
  return items.map((item) => {
    if (item.slot !== "bar") return item
    barCount += 1
    return barCount > MEDIA_ACTION_BAR_LIMIT ? { ...item, slot: "more" } : item
  })
}

export function mediaActionBar(items: MediaActionItem[]): MediaActionItem[] {
  return items.filter((item) => item.slot === "bar")
}

export function mediaActionMenu(items: MediaActionItem[]): MediaActionItem[] {
  return items.filter((item) => item.slot === "more")
}
