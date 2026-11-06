import { Button, Dropdown, Tooltip } from "antd"
import {
  CheckCircle2, CircleAlert, Download, FileImage, HardDrive, Maximize2, MoreHorizontal, RotateCcw,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { useState } from "react"
import type { CompareSource } from "./image-compare"
import { mediaActionMenu, mediaActionBar, type MediaActionItem } from "./media-actions"
import type { MediaHandoffSource } from "../media-handoff"
import "./image-results.css"

type Output = {
  kind: "image" | "video"; path: string; label: string
  delivery_status?: "pending" | "local" | "cloud" | "expired"
  download_url?: string | null
  cloud_url?: string | null
}

export type ImageResult = {
  jobId?: string
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

/** 注册表存的是图标组件，渲染时才知道要实例化哪一个。 */
function ActionIcon({ icon: Icon, size }: { icon: LucideIcon; size: number }) {
  return <Icon size={size} />
}

type Props = {
  results: ImageResult[]
  roundCount: number
  compare?: CompareSource
  onDownload: (result: ImageResult) => void
  onPreview?: (result: ImageResult) => void
  /** 卡片按每张结果自己的定位符取动作，注册表仍由宿主持有。 */
  resolveActions?: (source: MediaHandoffSource) => MediaActionItem[]
  onAction?: (action: MediaActionItem, result: ImageResult) => void
  onRetryFailed?: () => void
  retrying?: boolean
  embedded?: boolean
  showHeading?: boolean
}

function ImageResultCard({ result, compare, onDownload, onPreview, resolveActions, onAction }: Pick<Props, "compare" | "onDownload" | "onPreview" | "resolveActions" | "onAction"> & { result: ImageResult }) {
  const [failedSrc, setFailedSrc] = useState<string>()
  const [panoramaSrc, setPanoramaSrc] = useState<string>()
  const [showOriginal, setShowOriginal] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const expired = result.output.delivery_status === "expired"
  const available = Boolean(result.src) && failedSrc !== result.src && !expired
  const comparing = available && showOriginal ? compare : undefined
  const shownSrc = comparing ? comparing.src : result.src
  const downloadable = !expired && Boolean(result.output.download_url || result.output.cloud_url)
  const delivery = deliveryLabel(result.output.delivery_status)
  const panorama = available && panoramaSrc === result.src
  const registry = result.jobId
    ? (resolveActions?.({ jobId: result.jobId, generationItemId: result.generationItemId, outputIndex: result.outputIndex, kind: "image" }) ?? [])
    : []
  const bar = available ? mediaActionBar(registry) : []
  const menu = mediaActionMenu(registry)
  // 运行参数与删除不依赖图片本身能不能预览，其余动作在没有结果时按住。
  const alwaysEnabled = (item: MediaActionItem) => item.id === "params" || item.id === "remove"
  return <article className="studio-image-result-card" aria-label={result.output.label}>
    <div className={`studio-image-result-media ${panorama ? "is-panorama" : ""}`}>
      {available ? <button type="button" className="studio-image-preview" onClick={() => onPreview?.(result)} disabled={!onPreview} title="预览图片" aria-label={`预览${result.output.label}`}>
        <img src={shownSrc} alt={comparing ? comparing.label : result.output.label} decoding="async"
          onError={() => { if (!comparing) setFailedSrc(result.src) }}
          onLoad={(event) => { if (comparing) return; setPanoramaSrc(event.currentTarget.naturalWidth / event.currentTarget.naturalHeight >= 3 ? result.src : undefined) }} />
      </button> : <div className="studio-image-unavailable" role="status">
        {expired ? <CircleAlert size={20} /> : <HardDrive size={20} />}
        <span>{expired ? delivery : "图片暂不可用"}</span>
      </div>}
      {comparing ? <span className="studio-image-compare-flag">{comparing.label}</span> : null}
      <div className="studio-image-hover-tools" role="group" aria-label={`${result.output.label}操作`}>
        {onPreview && available ? <Button type="text" className="studio-image-tool" icon={<Maximize2 size={14} />} onClick={() => onPreview(result)} title="放大预览" aria-label={`放大预览${result.output.label}`} /> : null}
        {available && compare ? <Button type="text" className={`studio-image-tool${comparing ? " is-active" : ""}`} aria-pressed={showOriginal} icon={<FileImage size={14} />} onClick={() => setShowOriginal((current) => !current)} title={comparing ? "返回结果图" : "对比原图"} aria-label={comparing ? "返回结果图" : `对比${compare.label}`} /> : null}
        <Button type="text" className="studio-image-tool" icon={<Download size={14} />} disabled={!downloadable} onClick={() => onDownload(result)} title="下载图片" aria-label={`下载${result.output.label}`} />
        {menu.length ? <Dropdown trigger={["click"]} placement="bottomRight" open={menuOpen} onOpenChange={setMenuOpen}
          classNames={{ root: "studio-image-more-popup" }}
          menu={{
            items: menu.map((item) => ({ key: item.id, label: item.label, icon: <ActionIcon icon={item.icon} size={15} />, disabled: !alwaysEnabled(item) && !available, danger: item.danger })),
            onClick: ({ key }) => {
              setMenuOpen(false)
              const item = menu.find((action) => action.id === key)
              if (item) onAction?.(item, result)
            },
          }}>
          <Button type="text" className="studio-image-tool" icon={<MoreHorizontal size={16} />} aria-label={`更多${result.output.label}操作`} aria-expanded={menuOpen} />
        </Dropdown> : null}
      </div>
      <div className="studio-image-hover-bottom">
        <span className="studio-image-delivery" data-status={result.output.delivery_status || "cloud"}>
          {expired ? <CircleAlert size={12} /> : <CheckCircle2 size={12} />}{delivery}
        </span>
        {bar.length ? <div className="studio-image-hover-actions" role="group" aria-label={`${result.output.label}快捷操作`}>
          {bar.map((item) => <Tooltip key={item.id} title={item.label}>
            <Button type="text" className="studio-image-tool" icon={<ActionIcon icon={item.icon} size={14} />} aria-label={`${item.label}${result.output.label}`} onClick={() => onAction?.(item, result)} />
          </Tooltip>)}
        </div> : null}
      </div>
    </div>
  </article>
}

export default function ImageStudioModule({
  results, roundCount, compare, onDownload, onPreview, resolveActions, onAction, onRetryFailed, retrying, embedded = false, showHeading = true,
}: Props) {
  return <section className={`studio-image-results ${embedded ? "is-embedded" : "is-standalone"}`} aria-label="图片生成结果">
    {showHeading && <div className="studio-image-results-heading">
      <div><h2>图片结果</h2><p>共 {roundCount} 轮，{results.length} 张图片</p></div>
      {onRetryFailed ? <Button loading={retrying} onClick={onRetryFailed} icon={<RotateCcw size={14} />}>重试失败项</Button> : null}
    </div>}
    <div className="studio-image-result-grid">
      {results.map((result) => <ImageResultCard key={`${result.generationItemId}:${result.outputIndex}`} result={result} compare={compare} onDownload={onDownload} onPreview={onPreview} resolveActions={resolveActions} onAction={onAction} />)}
    </div>
  </section>
}
