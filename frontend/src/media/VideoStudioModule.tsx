import { HardDrive, LoaderCircle, Maximize2 } from "lucide-react"
import { useEffect, useMemo, useState, type CSSProperties } from "react"
import { mediaAspectVars, parseMediaAspect, type MediaAspectSize } from "../lib/utils"

type Output = {
  kind: "image" | "video"; path: string; label: string
  delivery_status?: "pending" | "local" | "cloud" | "expired"
  download_url?: string | null
}

export type VideoResult = {
  generationItemId: string
  outputIndex: number
  output: Output
  src?: string
}

function VideoResultCard({
  result, pendingSave, onSave, onPreview, aspectRatio,
}: {
  result: VideoResult
  pendingSave?: string
  onSave: (result: VideoResult) => void
  onPreview?: (result: VideoResult) => void
  aspectRatio?: string
}) {
  const hint = useMemo(() => parseMediaAspect(aspectRatio), [aspectRatio])
  const [measured, setMeasured] = useState<MediaAspectSize>()
  const aspect = measured || hint
  const orientation = aspect && aspect.height > aspect.width ? "portrait" : "landscape"

  useEffect(() => {
    setMeasured(undefined)
  }, [result.src])

  return (
    <article className={`studio-video-result-card overflow-hidden rounded-xl border border-white/[0.1] bg-[#202127] is-${orientation}`}>
      <div className="studio-video-result-media group relative bg-[#17181e]" style={mediaAspectVars(aspect) as CSSProperties}>
        {result.src ? onPreview ? (
          <button type="button" onClick={() => onPreview(result)} title="预览视频" className="h-full w-full cursor-zoom-in">
            <video
              className="h-full w-full object-contain"
              muted
              playsInline
              preload="metadata"
              src={result.src}
              onLoadedMetadata={(event) => {
                const { videoWidth, videoHeight } = event.currentTarget
                if (videoWidth > 0 && videoHeight > 0) setMeasured({ width: videoWidth, height: videoHeight })
              }}
            />
          </button>
        ) : (
          <video
            className="h-full w-full object-contain"
            controls
            playsInline
            preload="metadata"
            src={result.src}
            onLoadedMetadata={(event) => {
              const { videoWidth, videoHeight } = event.currentTarget
              if (videoWidth > 0 && videoHeight > 0) setMeasured({ width: videoWidth, height: videoHeight })
            }}
          />
        ) : <div className="grid h-full place-items-center text-[#777781]"><HardDrive size={20} /></div>}
        {result.src && onPreview ? <span className="pointer-events-none absolute inset-0 grid place-items-center bg-black/0 text-white opacity-0 transition group-hover:bg-black/25 group-hover:opacity-100"><Maximize2 size={20} /></span> : null}
      </div>
      <div className="flex min-h-11 items-center justify-between gap-3 px-3 py-2">
        <div className="min-w-0">
          <p className="truncate text-xs text-[#c7c7ce]">{result.output.label}</p>
          <p className={`mt-0.5 text-[10px] ${result.output.delivery_status === "local" ? "text-emerald-300" : "text-amber-200"}`}>
            {result.output.delivery_status === "local" ? "已保存到员工电脑" : "等待保存到本机"}
          </p>
        </div>
        {result.output.delivery_status !== "local" && result.output.download_url ? (
          <button type="button" disabled={pendingSave === result.output.path} onClick={() => onSave(result)} className="flex h-8 shrink-0 items-center gap-1.5 rounded-md bg-[#7047f6] px-2.5 text-xs text-white disabled:opacity-45">
            {pendingSave === result.output.path ? <LoaderCircle className="animate-spin" size={13} /> : <HardDrive size={13} />}保存
          </button>
        ) : null}
      </div>
    </article>
  )
}

export default function VideoStudioModule({
  results, roundCount, pendingSave, onSave, onPreview, embedded = false, showHeading = true, aspectRatio,
}: {
  results: VideoResult[]
  roundCount: number
  pendingSave?: string
  onSave: (result: VideoResult) => void
  onPreview?: (result: VideoResult) => void
  embedded?: boolean
  showHeading?: boolean
  aspectRatio?: string
}) {
  return (
    <section className={embedded ? "studio-video-results min-w-0" : "studio-video-results relative z-10 mx-auto mt-8 max-w-[1080px]"} aria-label="视频生成结果">
      {showHeading && <div className="mb-3"><h2 className="text-sm font-medium text-[#dedee5]">视频结果</h2><p className="mt-1 text-xs text-[#85858f]">共 {roundCount} 轮</p></div>}
      <div className={`studio-video-result-grid ${results.length === 1 ? "is-single" : ""}`}>
        {results.map((result) => (
          <VideoResultCard
            key={`${result.generationItemId}:${result.outputIndex}`}
            result={result}
            pendingSave={pendingSave}
            onSave={onSave}
            onPreview={onPreview}
            aspectRatio={aspectRatio}
          />
        ))}
      </div>
    </section>
  )
}
