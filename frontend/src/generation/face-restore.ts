import { mediaHandoffPath } from "../media-handoff"
import { PATHS } from "../paths"
import { roundReferenceSources, type ReferenceSource } from "../reference-assets"

export const FACE_RESTORE_WORKFLOW = "keep-face-restore"
export const FACE_RESTORE_LABEL = "人脸高清修复"
export type FacePoint = { x: number; y: number }
export type FaceSourceLocator = { job_id: string; generation_item_id: string; output_index: number }
type FaceOutput = { kind: string; path: string; label: string; download_url?: string | null; cloud_url?: string | null }
export type FaceRestoreJob = {
  id: string; mode: string; references: ReferenceSource[]; source?: FaceSourceLocator | null
  rounds: { id: string; mode: string; prompt: string; options: Record<string, string | number | boolean>;
    reference_count: number; references: ReferenceSource[];
    generation_items: { id: string; outputs: FaceOutput[] }[] }[]
}

export function faceRestorePath(result: { jobId?: string; generationItemId: string; outputIndex: number }): string | null {
  return mediaHandoffPath(PATHS.toolFaceRestore, {
    jobId: result.jobId ?? "", generationItemId: result.generationItemId, outputIndex: result.outputIndex, kind: "video",
  })
}

export function facePoint(value: unknown): FacePoint | null {
  try {
    const p = typeof value === "string" ? JSON.parse(value) : value
    return p && typeof p.x === "number" && typeof p.y === "number" && Number.isFinite(p.x) && Number.isFinite(p.y)
      && p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1 ? { x: p.x, y: p.y } : null
  } catch { return null }
}

export function faceVideoError(file: Pick<File, "type" | "size" | "name">): string {
  if (!file.size) return "视频不能为空文件"
  if (file.size > 500 * 1024 * 1024) return "视频不能超过 500 MB"
  return /\.(mp4|mov|webm|mkv|m4v|avi)$/i.test(file.name)
    && (!file.type || file.type === "application/octet-stream" || file.type.startsWith("video/"))
    ? "" : "请上传 MP4 / MOV / WebM 等视频文件"
}

export function selectedVideoReference(job: FaceRestoreJob, locator: FaceSourceLocator, index = 1): ReferenceSource {
  const item = job.rounds.flatMap((round) => round.generation_items).find((item) => item.id === locator.generation_item_id)
  const output = Number.isInteger(locator.output_index) && locator.output_index >= 0 ? item?.outputs[locator.output_index] : undefined
  if (!output || output.kind !== "video") throw new Error("选中的视频版本不存在，请返回成片重新选择")
  return { index, kind: "video", label: output.label,
    url: output.download_url || output.cloud_url || `/api/jobs/${encodeURIComponent(job.id)}/generations/${encodeURIComponent(item!.id)}/outputs/${locator.output_index}/download` }
}

export async function faceRestoreReferences(job: FaceRestoreJob, locator: FaceSourceLocator,
  load: (id: string) => Promise<FaceRestoreJob>): Promise<{ references: ReferenceSource[]; warning: string }> {
  const references = [selectedVideoReference(job, locator)]
  if (job.mode === FACE_RESTORE_WORKFLOW) {
    const round = job.rounds.find((r) => r.generation_items.some((item) => item.id === locator.generation_item_id))
    const original = round && roundReferenceSources(job, round).find((item) => item.index === 2)
    if (original) references.push({ ...original, kind: "video" })
  } else if ((job.mode === "seedvr2-upscale" || job.mode === "nvidia-rtx-vsr") && job.source) {
    try {
      const original = await load(job.source.job_id)
      references.push(selectedVideoReference(original, job.source, 2))
    } catch {
      return { references, warning: "未能关联高清前原片，可补充上传；当前将使用所选视频作为修脸输入。" }
    }
  }
  return { references, warning: "" }
}
