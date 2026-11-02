import { useMemo, useState } from "react"
import { Button, Empty, Input, Tag } from "antd"
import { ArrowRight, Check, Search } from "lucide-react"
import type { AssistantResource } from "./api"
import ResourceCover from "./ResourceCover"
import { filterResources, resourceCategories, resourceSource, resourceSourceLabels, type ResourceKind } from "./resource-market"

export default function ResourcePicker({ kind, resources, selectedVersionId, busy, onSelect, onOpenMarket }: {
  kind: ResourceKind; resources: AssistantResource[]; selectedVersionId?: string | null
  busy: boolean; onSelect: (resource: AssistantResource) => void; onOpenMarket: () => void
}) {
  const [search, setSearch] = useState("")
  const [category, setCategory] = useState("全部")
  const categories = useMemo(() => resourceCategories(resources, kind), [resources, kind])
  const visible = filterResources(resources, kind, category, "全部", search)
  const noun = kind === "skill" ? "Skill" : "专家"

  return <div className="assistant-resource-picker">
    <Input size="small" prefix={<Search size={14} />} placeholder={`搜索${noun}名称或能力`} value={search} onChange={event => setSearch(event.target.value)} allowClear />
    <div className="assistant-resource-picker-tabs">
      {["全部", ...categories].map(name => <Button key={name} type="text" size="small" className={category === name ? "is-active" : undefined} onClick={() => setCategory(name)}>{name}</Button>)}
    </div>
    <div className="assistant-resource-picker-list">
      {visible.map(resource => {
        const selected = resource.version_id === selectedVersionId
        return <Button key={resource.id} type="text" className={`assistant-resource-picker-row${selected ? " is-selected" : ""}`} disabled={busy} onClick={() => onSelect(resource)}>
          <ResourceCover resource={resource} variant="picker" />
          <span className="assistant-resource-picker-copy">
            <span className="assistant-resource-picker-name">
              <Tag className="assistant-resource-picker-source" data-source={resourceSource(resource)}>{resourceSourceLabels[resourceSource(resource)]}</Tag>
              <span>{resource.name}</span>
            </span>
            <small>{resource.description || "自定义创作方法与专业视角"}</small>
          </span>
          {selected && <Check size={14} className="assistant-resource-picker-check" />}
        </Button>
      })}
      {!visible.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的资源" />}
    </div>
    <Button type="text" block className="assistant-resource-picker-market" onClick={onOpenMarket}>前往专家与 Skill 市场<ArrowRight size={14} /></Button>
  </div>
}
