import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { Play, Plus } from "lucide-react"
import {
  STUDIO_TOOLS,
  TOOL_CATEGORY_LABEL,
  TOOL_CATEGORY_ORDER,
  TOOL_STATUS_LABEL,
  toolsByCategory,
  type StudioTool,
  type StudioToolCategory,
} from "./tool-registry"
import ToolDemoModal from "./ToolDemoModal"
import "./tools.css"

const FILTERS: Array<"all" | StudioToolCategory> = ["all", ...TOOL_CATEGORY_ORDER]

function ToolCardV2({ tool, onDemo }: { tool: StudioTool; onDemo: (tool: StudioTool) => void }) {
  const available = tool.status === "available"
  const body = <>
    <span className="studio-tool-card-v2-cover">
      <img src={tool.cover} alt="" loading="lazy" decoding="async" />
      <span className="studio-tool-card-v2-pill">{TOOL_STATUS_LABEL[tool.status]}</span>
      {available ? <span className="studio-tool-card-v2-cta">去使用</span> : null}
    </span>
    <span className="studio-tool-card-v2-body">
      <h2>{tool.title}</h2>
      <p>{tool.tagline}</p>
    </span>
  </>
  // 已上线的工具渲染为真链接：支持中键 / 新标签打开，行为与生成页墙卡一致。
  // 「示例」角标叠在链接外层（非嵌套交互元素），点击只弹对比示例框。
  return <>
    {available
      ? <Link to={tool.path} className="studio-tool-card-v2" aria-label={`${tool.title}：${tool.description}`}>{body}</Link>
      : <button type="button" disabled className="studio-tool-card-v2" aria-label={`${tool.title}：${tool.description}`}>{body}</button>}
    {available && tool.demo ? (
      <button
        type="button"
        className="studio-tool-card-v2-demo"
        aria-label={`查看${tool.title}功能示例`}
        onClick={() => onDemo(tool)}
      >
        <Play size={11} aria-hidden="true" />示例
      </button>
    ) : null}
  </>
}

export default function ToolsHome() {
  const [filter, setFilter] = useState<"all" | StudioToolCategory>("all")
  const [demoTool, setDemoTool] = useState<StudioTool | null>(null)
  const groups = useMemo(
    () => TOOL_CATEGORY_ORDER
      .map((category) => ({ category, tools: toolsByCategory(category) }))
      .filter((group) => group.tools.length > 0 && (filter === "all" || filter === group.category)),
    [filter],
  )
  return <div className="studio-tools-hub">
    <h1 className="studio-tools-hub-title">创作所需 一应俱全</h1>
    <nav className="studio-tools-chips" aria-label="工具分类">
      {FILTERS.map((key) => (
        <button
          key={key}
          type="button"
          className="studio-tools-chip"
          aria-pressed={filter === key}
          onClick={() => setFilter(key)}
        >
          {key === "all" ? "全部" : TOOL_CATEGORY_LABEL[key]}
        </button>
      ))}
    </nav>
    {groups.map((group) => (
      <section key={group.category} className="studio-tools-group" aria-label={TOOL_CATEGORY_LABEL[group.category]}>
        {filter === "all" ? <h2 className="studio-tools-group-title">{TOOL_CATEGORY_LABEL[group.category]}</h2> : null}
        <div className="studio-tools-grid-v2" role="list">
          {group.tools.map((tool) => <div role="listitem" key={tool.id} className="studio-tool-card-slot"><ToolCardV2 tool={tool} onDemo={setDemoTool} /></div>)}
        </div>
      </section>
    ))}
    {STUDIO_TOOLS.length > 0 ? (
      <div className="studio-tools-more"><Plus size={15} aria-hidden />更多工具陆续接入 · 敬请期待</div>
    ) : null}
    <ToolDemoModal tool={demoTool} open={demoTool !== null} onClose={() => setDemoTool(null)} />
  </div>
}
