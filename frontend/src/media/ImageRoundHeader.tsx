import { Button, Collapse, Popover } from "antd"
import { CheckCircle2, ChevronDown } from "lucide-react"
import type { ReactNode } from "react"
import "./image-results.css"

type Parameter = {
  name: string; label: string; value: string | number | boolean; unit?: string | null
  visibility?: "primary" | "advanced" | "internal"
}

export default function ImageRoundHeader({
  roundId, sequence, prompt, expanded, onExpand, language, onLanguageChange,
  references, modelName, status, statusLabel, stage, parameters, formatParameter, elapsed, onReferencePreview,
}: {
  roundId: string; sequence: number; prompt: string; expanded: boolean; onExpand: () => void
  language?: "zh" | "en"; onLanguageChange: () => void
  references: { index: number; url: string }[]
  modelName: string; status: string; statusLabel: string; stage: string
  parameters: Parameter[]; formatParameter: (parameter: Parameter) => string; elapsed: ReactNode
  onReferencePreview: (index: number, url: string) => void
}) {
  const creative = parameters.filter((parameter) => parameter.name !== "prompt" && parameter.name !== "mode" && parameter.visibility !== "internal")
  const runtime = parameters.filter((parameter) => parameter.visibility === "internal")
  const summary = creative.filter((parameter) => parameter.visibility === "primary" && typeof parameter.value !== "boolean").slice(0, 3)
  const parameterList = (items: Parameter[]) => <dl className="studio-image-parameters">{items.map((parameter) => <div key={parameter.name}>
    <dt>{parameter.label}</dt><dd>{formatParameter(parameter)}</dd>
  </div>)}</dl>

  return <header className="studio-round-header studio-image-request">
    {references.length ? <Popover trigger="click" placement="bottomLeft" arrow={false}
      content={<div className="studio-image-reference-list">{references.map((reference) => <Button key={reference.index} type="text" className="studio-image-reference-item"
        onClick={() => onReferencePreview(reference.index, reference.url)}>
        <img src={reference.url} alt="" /><span>参考图 {reference.index}</span>
      </Button>)}</div>}>
      <Button type="text" className="studio-image-reference-stack" aria-label={`查看 ${references.length} 张参考图`}>
        <img src={references[0].url} alt="" />{references.length > 1 ? <span>{references.length}</span> : null}
      </Button>
    </Popover> : null}
    <div className="studio-image-request-body">
      <div className="studio-image-prompt-row">
        <p id={`round-prompt-${roundId}`} className={`studio-image-prompt ${expanded ? "is-expanded" : ""}`}>{prompt}</p>
        <Button type="link" size="small" onClick={onExpand} aria-controls={`round-prompt-${roundId}`} aria-expanded={expanded}>{expanded ? "收起" : "展开"}</Button>
        {language ? <Button type="link" size="small" onClick={onLanguageChange} aria-label={language === "zh" ? "查看英文提示词" : "查看中文提示词"}>{language === "zh" ? "English" : "中文"}</Button> : null}
      </div>
      <div className="studio-image-meta">
        <span title={modelName}>{modelName}</span>
        {summary.map((parameter) => <span key={parameter.name} className="studio-image-meta-value" title={parameter.label}>{formatParameter(parameter)}</span>)}
        <span className="studio-image-meta-value">第 {sequence} 轮</span>
        <Popover trigger="click" placement="bottomLeft" arrow={false} content={<div className="studio-image-detail-content">
          <div className="studio-image-detail-title">创作参数</div>
          {creative.length ? parameterList(creative) : <p>此任务没有额外创作参数</p>}
          <div className="studio-image-detail-state"><span>{stage}</span>{elapsed}</div>
          {runtime.length ? <Collapse ghost size="small" items={[{ key: "runtime", label: "运行参数", children: parameterList(runtime) }]} /> : null}
        </div>}>
          <Button type="text" size="small" className="studio-image-meta-button">详细信息<ChevronDown size={12} /></Button>
        </Popover>
        <span className="studio-image-meta-status" data-status={status} title={stage}>{status === "succeeded" ? <CheckCircle2 size={13} /> : null}{statusLabel}</span>
        {elapsed}
      </div>
    </div>
  </header>
}
