import MaskedImageToolPage, { type MaskedImageToolConfig } from "./MaskedImageToolPage"
import { IMAGE_ERASER_WORKFLOW } from "../generation/image-edit"

export const IMAGE_ERASER_CONFIG: MaskedImageToolConfig = {
  workflow: IMAGE_ERASER_WORKFLOW,
  title: "消除笔",
  modalTitle: "消除笔",
  tagline: "涂抹要移除的内容，模型用周围环境自然填补，不留痕迹",
  editorCta: "进入消除",
  defaultTool: "brush",
  promptAria: "移除对象提示",
  promptRequired: false,
  promptPlaceholder: "可选。描述要移除的对象，例如：画面右侧的路人；不填将直接消除标记区域",
  resultNote: "标记区域将被移除并用背景自然填补，其余像素与原图完全一致。",
  loadingTip: "正在读取消除笔能力",
  successTip: "消除任务已提交，可在生成页查看进度",
  submitLabel: "应用",
}

export default function ImageEraserTool({ csrfToken }: { csrfToken: string }) {
  return <MaskedImageToolPage config={IMAGE_ERASER_CONFIG} csrfToken={csrfToken} />
}
