import MaskedImageToolPage, { type MaskedImageToolConfig } from "./MaskedImageToolPage"
import { IMAGE_INPAINT_WORKFLOW } from "../generation/image-edit"

export const IMAGE_INPAINT_CONFIG: MaskedImageToolConfig = {
  workflow: IMAGE_INPAINT_WORKFLOW,
  title: "图片局部重绘",
  modalTitle: "局部重绘",
  tagline: "涂抹画面区域，一句话把选区变成新内容，其余画面保持不变",
  editorCta: "进入重绘",
  defaultTool: "brush",
  promptAria: "重绘内容描述",
  promptRequired: false,
  promptPlaceholder: "描述想要重新绘制的内容，不填将基于原图生成",
  resultNote: "只有标记的区域会被重绘，标记区域外的像素与原图完全一致。",
  loadingTip: "正在读取图片局部重绘能力",
  successTip: "局部重绘任务已提交，可在生成页查看进度",
  submitLabel: "应用",
}

export default function ImageInpaintTool({ csrfToken }: { csrfToken: string }) {
  return <MaskedImageToolPage config={IMAGE_INPAINT_CONFIG} csrfToken={csrfToken} />
}
