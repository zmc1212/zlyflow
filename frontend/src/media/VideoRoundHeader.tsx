import { Button, Collapse, Dropdown, Popover } from "antd"
import { AudioLines, CheckCircle2, ChevronDown, Clapperboard, FileVideo, Mic } from "lucide-react"
import { useId, type ReactNode } from "react"
import { videoDeliveryLabel, videoResultKey, videoVersions, type VideoResult } from "./video-result-model"
import type { ReferenceKind, ReferenceSource } from "../reference-assets"
import "./video-results.css"

type Parameter = {
  name: string; label: string; value: string | number | boolean; unit?: string | null
  visibility?: "primary" | "advanced" | "internal"
}

/**
 * 参考素材缩略图：非图片类型只给图标，避免通用「音频或视频」槽位被当成图片渲染出碎图。
 * media 是音频与视频共用的槽位（如人声/伴奏分离），接口不下发具体类型，故用中性图标。
 */
function referencePreview(reference: ReferenceSource, size: number) {
  if (reference.kind === "video") return <FileVideo size={size} />
  if (reference.kind === "audio") return <Mic size={size} />
  if (reference.kind === "media") return <AudioLines size={size} />
  return <img src={reference.url} alt="" loading="lazy" />
}

export default function VideoRoundHeader({
  roundId, sequence, prompt, expanded, onExpand, language, onLanguageChange,
  references, modelName, status, statusLabel, stage, parameters, formatParameter, elapsed,
  results, selected, onSelect, detailsOpen, runtimeExpanded, onDetailsChange, onReferencePreview,
}: {
  roundId: string; sequence: number; prompt: string; expanded: boolean; onExpand: () => void
  language?: "zh" | "en"; onLanguageChange: () => void
  references: ReferenceSource[]
  modelName: string; status: string; statusLabel: string; stage: string
  parameters: Parameter[]; formatParameter: (parameter: Parameter) => string; elapsed: ReactNode
  results: VideoResult[]; selected?: VideoResult; onSelect: (key: string) => void
  detailsOpen: boolean; runtimeExpanded: boolean
  onDetailsChange: (open: boolean, runtime: boolean) => void
  onReferencePreview: (index: number, url: string, kind: ReferenceKind, label?: string | null) => void
}) {
  const versionMenuId = useId()
  // The model name already identifies the workflow, so its raw id is not repeated.
  const creative = parameters.filter((parameter) => parameter.name !== "prompt" && parameter.name !== "mode" && parameter.visibility !== "internal")
  const runtime = parameters.filter((parameter) => parameter.visibility === "internal")
  const summary = creative.filter((parameter) => parameter.visibility === "primary" && typeof parameter.value !== "boolean").slice(0, 2)
  const versions = videoVersions(results)
  const selectedKey = selected ? videoResultKey(selected) : undefined
  const selectedIndex = versions.findIndex((version) => version.key === selectedKey)
  const parameterList = (items: Parameter[]) => <dl className="studio-video-parameters">{items.map((parameter) => (
    <div key={parameter.name}><dt>{parameter.label}</dt><dd>{formatParameter(parameter)}</dd></div>
  ))}</dl>

  return <header className="studio-round-header studio-video-request">
    {references.length ? <Popover trigger="click" placement="bottomLeft" arrow={false}
      classNames={{ root: "studio-video-reference-popover" }}
      content={<div className="studio-video-reference-list">{references.map((reference) => (
        <Button key={reference.index} type="text" className="studio-video-reference-item"
          onClick={() => onReferencePreview(reference.index, reference.url, reference.kind || "image", reference.label)}>
          {referencePreview(reference, 24)}<span>{reference.label || `参考图 ${reference.index}`}</span>
        </Button>
      ))}</div>}>
      <Button type="text" className="studio-video-reference-stack" aria-label={`查看 ${references.length} 份参考素材`}>
        {references.slice(0, 5).map((reference, index) => <span key={reference.index} className="studio-video-reference-mini">
          {referencePreview(reference, 18)}
          {index === Math.min(4, references.length - 1) ? <span className="studio-video-reference-count">{references.length}</span> : null}
        </span>)}
      </Button>
    </Popover> : <div className="studio-video-request-icon"><Clapperboard size={19} /></div>}
    <div className="studio-video-request-body">
      <div className="studio-video-prompt-row">
        <p id={`round-prompt-${roundId}`} className={`studio-video-prompt ${expanded ? "is-expanded" : ""}`}>{prompt}</p>
        <Button type="link" size="small" onClick={onExpand} aria-controls={`round-prompt-${roundId}`} aria-expanded={expanded}>{expanded ? "收起" : "展开"}</Button>
        {language ? <Button type="link" size="small" onClick={onLanguageChange} aria-label={language === "zh" ? "查看英文提示词" : "查看中文提示词"}>{language === "zh" ? "English" : "中文"}</Button> : null}
      </div>
      <div className="studio-video-meta">
        <span className="studio-video-model" title={modelName}>{modelName}</span>
        {summary.map((parameter) => <span key={parameter.name} className="studio-video-meta-value" title={parameter.label}>{formatParameter(parameter)}</span>)}
        <span className="studio-video-meta-value">第 {sequence} 轮</span>
        <span className="studio-video-meta-status" data-status={status} title={stage}>{statusLabel}{status === "succeeded" ? <CheckCircle2 size={13} /> : null}</span>
        {versions.length > 1 ? <Dropdown trigger={["click"]} placement="bottomLeft"
          onOpenChange={(open) => { if (open) requestAnimationFrame(() => document.getElementById(versionMenuId)?.focus({ preventScroll: true })) }}
          menu={{ id: versionMenuId, selectable: true, selectedKeys: selectedKey ? [selectedKey] : [],
            items: versions.map((version) => ({ key: version.key,
              label: <span className="studio-video-version-option"><span>{version.label}</span>{version.detail ? <small>{version.detail}</small> : null}</span>,
            })), onClick: ({ key }) => onSelect(key) }}>
          <Button type="text" size="small" className="studio-video-meta-button" aria-label={`切换视频版本，当前第 ${selectedIndex + 1} 个，共 ${versions.length} 个`}>
            版本 {selectedIndex + 1}/{versions.length}<ChevronDown size={12} />
          </Button>
        </Dropdown> : null}
        <Popover trigger="click" placement="bottomLeft" arrow={false} open={detailsOpen}
          onOpenChange={(open) => onDetailsChange(open, false)} classNames={{ root: "studio-video-details-popover" }}
          content={<div className="studio-video-detail-content">
            <div className="studio-video-detail-title">创作参数</div>
            {creative.length ? parameterList(creative) : <p className="studio-video-detail-note">此任务没有额外创作参数</p>}
            <div className="studio-video-detail-state"><span>{stage}</span>{elapsed}{selected ? <span>{videoDeliveryLabel(selected)}</span> : null}</div>
            {runtime.length ? <Collapse ghost size="small" activeKey={runtimeExpanded ? ["runtime"] : []}
              onChange={(keys) => onDetailsChange(true, keys.includes("runtime"))}
              items={[{ key: "runtime", label: "运行参数", children: parameterList(runtime) }]} /> : null}
          </div>}>
          <Button type="text" size="small" className="studio-video-meta-button" aria-expanded={detailsOpen}>详细信息<ChevronDown size={12} /></Button>
        </Popover>
      </div>
    </div>
  </header>
}
