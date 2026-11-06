import type { ReferenceSource } from "../reference-assets"

export type CompareWorkflow = { result_compare?: string; reference_labels?: string[] }
export type CompareSource = { src: string; label: string }

/**
 * 原图槽位由工作流声明的 reference_labels 决定，不按 mode id 在前端硬编码。
 * 只有逐像素对齐的编辑类工作流（去背景 / 局部重绘 / 消除笔）才值得对比。
 */
export function resolveCompareSource(
  workflow: CompareWorkflow | undefined,
  references: ReferenceSource[],
): CompareSource | undefined {
  if (workflow?.result_compare !== "overlay") return undefined
  const labels = workflow.reference_labels || []
  const slot = labels.findIndex((label) => label.startsWith("原图"))
  if (slot < 0) return undefined
  const source = references.find((item) => item.index === slot + 1 && (item.kind ?? "image") === "image")
  return source?.url ? { src: source.url, label: labels[slot] } : undefined
}

/** 叠层滑杆要求两张图构图一致；分辨率可以不同，长宽比不同则放弃叠层。 */
export function isCompareAligned(before: MediaSize, after: MediaSize): boolean {
  const ratioBefore = before.width / before.height
  const ratioAfter = after.width / after.height
  return Math.abs(ratioBefore - ratioAfter) / ratioAfter <= 0.01
}

export type MediaSize = { width: number; height: number }
