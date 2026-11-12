import { useEffect, useRef, useState } from "react"
import { Button, Collapse, Select, Tag } from "antd"
import { ArrowUpRight, Check, FileText } from "lucide-react"
import {
  DIMENSIONS, PRIORITIES, citationLabel, durationLabel, sliceCharacters,
  type Diagnosis, type Evidence, type Issue,
} from "./model"
import { searchFilterOption } from "../../search-match"

export default function DiagnosisReport({ task }: { task: Diagnosis }) {
  const [sourceId, setSourceId] = useState(task.sources[0]?.id || "")
  const [selected, setSelected] = useState<Evidence | null>(null)
  const markRef = useRef<HTMLElement | null>(null)
  const issueRefs = useRef<Record<string, HTMLElement | null>>({})
  const report = task.report!
  const source = task.sources.find(item => item.id === sourceId) || task.sources[0]

  useEffect(() => {
    setSourceId(task.sources[0]?.id || "")
    setSelected(null)
  }, [task.id, task.sources])

  useEffect(() => {
    if (selected) markRef.current?.scrollIntoView({ block: "center", behavior: "smooth" })
  }, [selected])

  function locate(quote: Evidence) {
    setSourceId(quote.source_id)
    setSelected(quote)
  }
  function quotes(issue: Issue) {
    return issue.evidence.map((quote, index) => <Button key={index} type="text" className="sd-quote" onClick={() => locate(quote)}>
      <span className="sd-quote-copy"><span>“{quote.quote}”</span><small>{citationLabel(task.sources, quote)}</small></span>
      <ArrowUpRight size={14} />
    </Button>)
  }
  const marked = selected?.source_id === source?.id ? selected : null

  return <div className="sd-report-layout">
    <div className="sd-report-scroll">
      <section className="sd-overview">
        <div className="sd-overview-title"><Tag color="success" className="sd-tag-success">诊断完成</Tag><span>{task.sources.length} 份文件 · {report.dimensions.length} 项诊断</span></div>
        <h1>{task.title}</h1>
        <p className="sd-summary">{report.summary}</p>
        <div className="sd-duration"><span>预计总时长</span><strong>{durationLabel(report.duration)}</strong></div>
        <p className="sd-muted">{report.duration.basis}</p>
        {report.duration.episodes.length > 0 && <Collapse ghost size="small" items={[{
          key: "episodes", label: "查看分集 / 分段时长（" + report.duration.episodes.length + "）",
          children: <div className="sd-episode-times">{report.duration.episodes.map((episode, index) =>
            <div key={index}><span>{episode.label}<small>{episode.basis}</small></span><strong>{durationLabel(episode)}</strong></div>)}</div>,
        }]} />}
      </section>

      {report.priorities.length > 0 && <section className="sd-priorities">
        <h2>先从这几处改起</h2>
        {report.priorities.map((issue, index) => <Button key={index} type="text" className="sd-priority-link"
          onClick={() => issueRefs.current[issue.dimension + "-" + issue.issue_index]?.scrollIntoView({ block: "center", behavior: "smooth" })}>
          <span><Tag color={PRIORITIES[issue.priority].color} className={"sd-tag-" + issue.priority}>{PRIORITIES[issue.priority].label}</Tag>{issue.title}</span><ArrowUpRight size={15} />
        </Button>)}
      </section>}

      <nav className="sd-dimension-nav" aria-label="报告维度">
        {DIMENSIONS.map(dimension => <Button key={dimension.key} type="text" size="small"
          onClick={() => document.getElementById("sd-dimension-" + dimension.key)?.scrollIntoView({ block: "start", behavior: "smooth" })}>
          {dimension.label}
        </Button>)}
      </nav>
      {report.dimensions.map(dimension => <section key={dimension.key} className="sd-dimension" id={"sd-dimension-" + dimension.key}>
        <div className="sd-section-heading"><h2>{DIMENSIONS.find(item => item.key === dimension.key)?.label}</h2>
          <span>{dimension.issues.length ? dimension.issues.length + " 项建议" : "未见主要问题"}</span></div>
        <p>{dimension.conclusion}</p>
        {dimension.strengths.length > 0 && <ul className="sd-strengths">{dimension.strengths.map((strength, index) =>
          <li key={index}><Check size={14} /><span>{strength}</span></li>)}</ul>}
        {dimension.issues.map((issue, index) => <article className="sd-issue" key={index}
          ref={node => { issueRefs.current[dimension.key + "-" + index] = node }}>
          <h3><Tag color={PRIORITIES[issue.priority].color} className={"sd-tag-" + issue.priority}>{PRIORITIES[issue.priority].label}</Tag>{issue.title}</h3>
          <p>{issue.explanation}</p>
          <div className="sd-quotes">{quotes(issue)}</div>
          <div className="sd-suggestion"><strong>修改建议</strong><p>{issue.suggestion}</p></div>
        </article>)}
      </section>)}
      <p className="sd-report-note">新颖度为文本创作评估，未进行全网查重；风险评估为辅助审阅。</p>
      <p className="sd-report-note">使用模型：{task.model} · {new Date(task.created_at).toLocaleString("zh-CN")}</p>
    </div>
    <aside className="sd-original" aria-label="剧本原文">
      <div className="sd-original-heading"><FileText size={17} /><strong>原文对照</strong><span>提交时的剧本</span></div>
      <Select aria-label="选择原文文件" showSearch filterOption={searchFilterOption} value={source?.id} onChange={value => { setSourceId(value); setSelected(null) }}
        options={task.sources.map(item => ({ value: item.id, label: item.name }))} />
      <div className="sd-original-tip">{marked ? citationLabel(task.sources, marked) : "点击报告中的原文依据，定位到对应段落"}</div>
      <pre className="sd-original-text">{marked
        ? <>{sliceCharacters(source.text, 0, marked.start)}<mark ref={markRef}>{sliceCharacters(source.text, marked.start, marked.end)}</mark>{sliceCharacters(source.text, marked.end)}</>
        : source?.text}</pre>
    </aside>
  </div>
}
