import { Download, HardDrive, LoaderCircle, Play, RotateCcw } from "lucide-react"

type Output = {
  kind: "image" | "video"; path: string; label: string
  delivery_status?: "pending" | "local" | "cloud" | "expired"
  download_url?: string | null
  cloud_url?: string | null
}

export type ImageResult = {
  generationItemId: string
  outputIndex: number
  output: Output
  src?: string
}

function deliveryLabel(status: Output["delivery_status"]): { text: string; tone: string } {
  if (status === "expired") return { text: "云端文件已过期", tone: "text-amber-200" }
  if (status === "local") return { text: "已保存到员工电脑", tone: "text-emerald-300" }
  if (status === "pending") return { text: "可下载", tone: "text-amber-200" }
  return { text: "已存入云端", tone: "text-emerald-300" }
}

export default function ImageStudioModule({
  results, roundCount, onDownload, onCreateVideo, onPreview, onRetryFailed, retrying, embedded = false, showHeading = true,
}: {
  results: ImageResult[]
  roundCount: number
  onDownload: (result: ImageResult) => void
  onCreateVideo?: (result: ImageResult) => void
  onPreview?: (result: ImageResult) => void
  onRetryFailed?: () => void
  retrying?: boolean
  embedded?: boolean
  showHeading?: boolean
}) {
  return <section className={`studio-image-results ${embedded ? "min-w-0" : "relative z-10 mx-auto mt-8 max-w-[1080px]"}`} aria-label="图片生成结果">
    {showHeading && <div className="studio-image-results-heading mb-3 flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="text-sm font-medium text-[#dedee5]">图片结果</h2><p className="mt-1 text-xs text-[#85858f]">共 {roundCount} 轮，生成结果已存入云端存储</p></div>
      {onRetryFailed ? <button type="button" disabled={retrying} onClick={onRetryFailed} className="flex h-9 items-center gap-2 rounded-lg border border-amber-300/25 bg-amber-300/[0.06] px-3 text-xs text-amber-200 disabled:opacity-45">{retrying ? <LoaderCircle className="animate-spin" size={14} /> : <RotateCcw size={14} />}重试失败项</button> : null}
    </div>}
    <div className={`studio-image-result-grid grid gap-4 ${results.length === 1 ? "grid-cols-1" : "sm:grid-cols-2"}`}>
      {results.map((result) => {
        const downloadable = Boolean(result.output.download_url || result.output.cloud_url)
        const delivery = deliveryLabel(result.output.delivery_status)
        return <article key={`${result.generationItemId}:${result.outputIndex}`} className="studio-image-result-card overflow-hidden rounded-xl border border-white/[0.1]">
          <div className={`studio-image-result-media ${embedded ? "h-[min(68vh,680px)]" : "aspect-square"}`}>{result.src ? <button type="button" onClick={() => onPreview?.(result)} disabled={!onPreview} title="预览图片" className="h-full w-full cursor-zoom-in disabled:cursor-default"><img src={result.src} alt={result.output.label} className="h-full w-full object-contain" /></button> : <div className="grid h-full place-items-center text-[#777781]"><HardDrive size={20} /></div>}</div>
          <div className="studio-image-result-footer flex min-h-14 flex-wrap items-center justify-between gap-2 px-3 py-2.5">
            <div className="min-w-0"><p className="truncate text-xs text-[#d4d4da]">{result.output.label}</p><p className={`mt-0.5 text-[10px] ${delivery.tone}`}>{delivery.text}</p></div>
            <div className="flex items-center gap-2">
              <button type="button" disabled={!downloadable} onClick={() => onDownload(result)} className="studio-image-action-secondary flex h-8 items-center gap-1.5 rounded-md border border-white/10 px-2.5 text-xs disabled:opacity-45"><Download size={13} />下载</button>
              {onCreateVideo ? <button type="button" onClick={() => onCreateVideo(result)} className="studio-image-action-primary flex h-8 items-center gap-1.5 rounded-md bg-[#7047f6] px-2.5 text-xs text-white disabled:opacity-45"><Play size={13} />生成视频</button> : null}
            </div>
          </div>
        </article>
      })}
    </div>
  </section>
}
