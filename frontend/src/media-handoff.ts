import { restoreReferenceFiles } from "./reference-assets"

export type MediaKind = "image" | "video"

/** 一张已产出的媒体：任务 + 生成项 + 版本下标，足以在服务端定位到原始文件。 */
export type MediaHandoffSource = {
  jobId: string
  generationItemId: string
  outputIndex: number
  kind: MediaKind
}

/**
 * 工具页的 ?job=&round= 已被「重跑这个任务、恢复它上一轮的输入」占用；
 * 交接产物必须用另一组键，否则同一页面无法区分「改输入重做」和「拿这张结果继续做」。
 */
export function isMediaHandoffSource(value: unknown): value is MediaHandoffSource {
  if (!value || typeof value !== "object") return false
  const source = value as Record<string, unknown>
  return typeof source.jobId === "string" && source.jobId.trim() !== ""
    && typeof source.generationItemId === "string" && source.generationItemId.trim() !== ""
    && Number.isInteger(source.outputIndex) && (source.outputIndex as number) >= 0
    && (source.kind === "image" || source.kind === "video")
}

export function outputDownloadUrl(source: MediaHandoffSource): string {
  return `/api/jobs/${encodeURIComponent(source.jobId)}/generations/${encodeURIComponent(source.generationItemId)}/outputs/${source.outputIndex}/download`
}

/** 定位符不完整时返回 null：调用方据此收起按钮，而不是导航到一个读不出素材的页面。 */
export function mediaHandoffPath(toolPath: string, source: unknown): string | null {
  if (!isMediaHandoffSource(source)) return null
  const query = new URLSearchParams({
    sourceJob: source.jobId,
    generation: source.generationItemId,
    output: String(source.outputIndex),
    kind: source.kind,
  })
  return `${toolPath}?${query}`
}

export function readMediaHandoff(params: URLSearchParams): MediaHandoffSource | null {
  const kind = params.get("kind")
  const output = params.get("output")
  const candidate = {
    jobId: (params.get("sourceJob") ?? "").trim(),
    generationItemId: (params.get("generation") ?? "").trim(),
    outputIndex: output === null ? Number.NaN : Number(output),
    kind: kind === "image" || kind === "video" ? kind : undefined,
  }
  return isMediaHandoffSource(candidate) ? candidate : null
}

/** 把定位符换回一个可提交的 File：走同源下载路由，再由魔数嗅探确定真实类型。 */
export async function fetchHandoffFile(source: MediaHandoffSource): Promise<File> {
  const [file] = await restoreReferenceFiles([{ index: 1, url: outputDownloadUrl(source), kind: source.kind }])
  return file
}
