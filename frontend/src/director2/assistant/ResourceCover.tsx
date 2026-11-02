import { Button, Tag } from "antd"
import { Star } from "lucide-react"
import type { AssistantResource } from "./api"
import { resourceCover, resourceSource, resourceSourceLabels } from "./resource-market"

export default function ResourceCover({ resource, variant = "card", favorite, onToggleFavorite }: {
  resource: AssistantResource; variant?: "card" | "thumb" | "picker"
  favorite?: boolean; onToggleFavorite?: () => void
}) {
  const source = resourceSource(resource)
  return <div className={`assistant-resource-cover is-${variant}`}>
    <img src={resourceCover(resource.category)} alt="" loading={variant === "card" ? "lazy" : "eager"} draggable={false} />
    <span className="assistant-cover-scrim" aria-hidden="true" />
    {variant === "card" && <>
      <Tag className="assistant-cover-source" data-source={source}>{resourceSourceLabels[source]}</Tag>
      {onToggleFavorite && <Button
        className="assistant-cover-star" type="text" size="small"
        data-favorite={favorite ? "true" : undefined}
        aria-label={favorite ? "取消收藏" : "收藏资源"}
        icon={<Star size={13} fill={favorite ? "currentColor" : "none"} />}
        onClick={event => { event.stopPropagation(); onToggleFavorite() }}
      />}
      <div className="assistant-cover-caption">
        <span>{resource.resource_type === "skill" ? "Skill" : "Expert"} · {resource.category}</span>
        <strong>{resource.name}</strong>
      </div>
    </>}
  </div>
}
