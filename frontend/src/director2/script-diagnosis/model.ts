export const DIMENSIONS = [
  { key: "duration", label: "总时长预估", hint: "对白、旁白与动作，大约需要多少时间" },
  { key: "novelty", label: "新颖度评估", hint: "找出独特设定与可以突破的套路" },
  { key: "pacing", label: "节奏把控评估", hint: "开场、冲突、转折与集尾悬念" },
  { key: "emotion", label: "情绪浓度评估", hint: "人物欲望、情绪铺垫与高潮支撑" },
  { key: "risk", label: "风险合规评估", hint: "标出内容疑点，给出调整方向" },
] as const
export type DimensionKey = typeof DIMENSIONS[number]["key"]
export type Source = { id: string; name: string; text: string }
export type Evidence = { source_id: string; block_id: string; quote: string; start: number; end: number }
export type Issue = {
  title: string; priority: "high" | "medium" | "low"; explanation: string; suggestion: string; evidence: Evidence[]
}
export type Dimension = { key: DimensionKey; conclusion: string; strengths: string[]; issues: Issue[] }
export type Duration = { min_seconds: number; max_seconds: number; basis: string }
export type Report = {
  schema_version: number; summary: string
  duration: Duration & { episodes: (Duration & { source_id: string; label: string; explicit: boolean })[] }
  dimensions: Dimension[]
  priorities: (Issue & { dimension: DimensionKey; issue_index: number })[]
}
export type DiagnosisSummary = {
  id: string; title: string; project_id: string | null; document_id: string | null
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted"
  stage: string; completed: number; total: number; model: string; error: string | null
  created_at: string; updated_at: string
}
export type Diagnosis = DiagnosisSummary & { sources: Source[]; report: Report | null }
export type Capabilities = {
  extensions: string[]; max_files: number; max_file_bytes: number; max_characters: number
  available: boolean; unavailable_reason: string | null; model: string; dimensions: Record<string, string>
}
export const PRIORITIES = {
  high: { label: "优先修改", color: "error" },
  medium: { label: "建议优化", color: "warning" },
  low: { label: "提示", color: "default" },
} as const
export const STATUS_LABELS: Record<DiagnosisSummary["status"], string> = {
  queued: "排队中", running: "诊断中", succeeded: "已完成", failed: "失败", cancelled: "已取消", interrupted: "已中断",
}
export const isActive = (task: DiagnosisSummary | null) => task?.status === "queued" || task?.status === "running"
export const characterCount = (text: string) => Array.from(text).length
export const sliceCharacters = (text: string, start: number, end?: number) => Array.from(text).slice(start, end).join("")

export function durationLabel(duration: Pick<Duration, "min_seconds" | "max_seconds">): string {
  const format = (seconds: number) => {
    const rounded = Math.round(seconds)
    if (rounded < 60) return rounded + " 秒"
    const minutes = Math.floor(rounded / 60)
    return minutes + " 分" + (rounded % 60 ? " " + (rounded % 60) + " 秒" : "钟")
  }
  return duration.min_seconds === duration.max_seconds
    ? format(duration.min_seconds)
    : format(duration.min_seconds) + " – " + format(duration.max_seconds)
}

export function citationLabel(sources: Source[], quote: Evidence): string {
  const source = sources.find(item => item.id === quote.source_id)
  const line = source ? sliceCharacters(source.text, 0, quote.start).split("\n").length : 1
  return (source?.name || quote.source_id) + " · 第 " + line + " 行"
}

export function moveItem<T>(items: T[], from: number, to: number): T[] {
  if (from < 0 || from >= items.length || to < 0 || to >= items.length || from === to) return items
  const result = [...items]
  const [item] = result.splice(from, 1)
  result.splice(to, 0, item)
  return result
}

export function reportMarkdown(task: Diagnosis): string {
  if (!task.report) return ""
  const report = task.report
  const lines = [
    "# " + task.title + " · 剧本诊断", "", report.summary, "",
    "预计总时长：" + durationLabel(report.duration), report.duration.basis, "",
    "## 优先修改", "",
  ]
  if (!report.priorities.length) lines.push("本次未发现需要优先修改的问题。", "")
  report.priorities.forEach((issue, index) => {
    lines.push(String(index + 1) + ". " + issue.title + "（" + PRIORITIES[issue.priority].label + "）", issue.suggestion, "")
  })
  report.dimensions.forEach(dimension => {
    lines.push("## " + DIMENSIONS.find(item => item.key === dimension.key)?.label, "", dimension.conclusion, "")
    dimension.strengths.forEach(strength => lines.push("- 优点：" + strength))
    dimension.issues.forEach(issue => {
      lines.push("", "### " + issue.title + "（" + PRIORITIES[issue.priority].label + "）", "", issue.explanation)
      issue.evidence.forEach(quote => {
        lines.push("", "原文依据：" + citationLabel(task.sources, quote))
        lines.push(...quote.quote.split("\n").map(line => "> " + line))
      })
      lines.push("", "修改建议：" + issue.suggestion)
    })
    if (!dimension.issues.length) lines.push("当前文本未发现有充分依据的主要问题。")
    lines.push("")
  })
  if (report.duration.episodes.length) {
    lines.push("## 分集 / 分段时长", "")
    report.duration.episodes.forEach(episode =>
      lines.push("- " + episode.label + "：" + durationLabel(episode) + "；" + episode.basis))
    lines.push("")
  }
  lines.push("新颖度为文本创作评估，未进行全网查重；风险评估为辅助审阅。", "",
    "诊断时间：" + new Date(task.created_at).toLocaleString("zh-CN"),
    "使用模型：" + task.model)
  return lines.join("\n")
}
