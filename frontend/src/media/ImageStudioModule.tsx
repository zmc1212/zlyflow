import { Button } from "antd"
import { CheckCircle2, CircleAlert, Download, HardDrive, Maximize2, Play, RotateCcw } from "lucide-react"
import { useState } from "react"
import "./image-results.css"

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

function deliveryLabel(status: Output["delivery_status"]): string {
  if (status === "expired") return "云端文件已过期"
  if (status === "local") return "已保存到员工电脑"
  if (status === "pending") return "可下载"
  return "已存入云端"
}

type Props = {
  results: ImageResult[]
  roundCount: number
  onDownload: (result: ImageResult) => void
  onCreateVideo?: (result: ImageResult) => void
  onPreview?: (result: ImageResult) => void
  onRetryFailed?: () => void
  retrying?: boolean
  embedded?: boolean
  showHeading?: boolean
}

function ImageResultCard({ result, onDownload, onCreateVideo, onPreview }: Pick<Props, "onDownload" | "onCreateVideo" | "onPreview"> & { result: ImageResult }) {
  const [failedSrc, setFailedSrc] = useState<string>()
  const [panoramaSrc, setPanoramaSrc] = useState<string>()
  const expired = result.output.delivery_status === "expired"
  const available = Boolean(result.src) && failedSrc !== result.src && !expired
  const downloadable = !expired && Boolean(result.output.download_url || result.output.cloud_url)
  const delivery = deliveryLabel(result.output.delivery_status)
  const panorama = available && panoramaSrc === result.src
  const videoAction = onCreateVideo ? <Button type="text" className="studio-image-video-action" disabled={!available} icon={<Play size={12} />} onClick={() => onCreateVideo(result)}>生成视频</Button> : null
  return <article className="studio-image-result-card" aria-label={result.output.label}>
    <div className={`studio-image-result-media ${panorama ? "is-panorama" : ""}`}>
      {available ? <button type="button" className="studio-image-preview" onClick={() => onPreview?.(result)} disabled={!onPreview} title="预览图片" aria-label={`预览${result.output.label}`}>
        <img src={result.src} alt={result.output.label} decoding="async" onError={() => setFailedSrc(result.src)}
          onLoad={(event) => setPanoramaSrc(event.currentTarget.naturalWidth / event.currentTarget.naturalHeight >= 3 ? result.src : undefined)} />
      </button> : <div className="studio-image-unavailable" role="status">
        {expired ? <CircleAlert size={20} /> : <HardDrive size={20} />}
        <span>{expired ? delivery : "图片暂不可用"}</span>
      </div>}
      <div className="studio-image-hover-tools" role="group" aria-label={`${result.output.label}操作`}>
        {onPreview && available ? <Button type="text" className="studio-image-tool" icon={<Maximize2 size={14} />} onClick={() => onPreview(result)} title="放大预览" aria-label={`放大预览${result.output.label}`} /> : null}
        <Button type="text" className="studio-image-tool" icon={<Download size={14} />} disabled={!downloadable} onClick={() => onDownload(result)} title="下载图片" aria-label={`下载${result.output.label}`} />
        {panorama ? videoAction : null}
      </div>
      <div className="studio-image-hover-bottom">
        <span className="studio-image-delivery" data-status={result.output.delivery_status || "cloud"}>
          {expired ? <CircleAlert size={12} /> : <CheckCircle2 size={12} />}{delivery}
        </span>
        {panorama ? null : videoAction}
      </div>
    </div>
  </article>
}

export default function ImageStudioModule({
  results, roundCount, onDownload, onCreateVideo, onPreview, onRetryFailed, retrying, embedded = false, showHeading = true,
}: Props) {
  return <section className={`studio-image-results ${embedded ? "is-embedded" : "is-standalone"}`} aria-label="图片生成结果">
    {showHeading && <div className="studio-image-results-heading">
      <div><h2>图片结果</h2><p>共 {roundCount} 轮，{results.length} 张图片</p></div>
      {onRetryFailed ? <Button loading={retrying} onClick={onRetryFailed} icon={<RotateCcw size={14} />}>重试失败项</Button> : null}
    </div>}
    <div className="studio-image-result-grid">
      {results.map((result) => <ImageResultCard key={`${result.generationItemId}:${result.outputIndex}`} result={result} onDownload={onDownload} onCreateVideo={onCreateVideo} onPreview={onPreview} />)}
    </div>
  </section>
}
