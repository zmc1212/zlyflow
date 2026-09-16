import { Button, Tag } from "antd"
import { MapPin, Package, Sparkles } from "lucide-react"

export type DirectorAssetCardKind = "character" | "scene" | "prop"

export interface DirectorAssetCardData {
  kind: DirectorAssetCardKind
  name: string
  role?: string
  age?: string
  gender?: string
  shotsCount?: number
  fixedProps?: string[]
  description?: string
  visualPrompt?: string
  sceneType?: string
  elements?: string[]
  propKind?: string
  relatedCharacter?: string
  count?: number
}

export interface DirectorAssetSummaryCardProps {
  asset: DirectorAssetCardData
  onCopyPrompt?: (prompt: string) => void
}

function getCharGradient(name: string): { background: string } {
  const gradients = [
    "linear-gradient(135deg, #6366f1 0%, #a855f7 100%)",
    "linear-gradient(135deg, #3b82f6 0%, #2dd4bf 100%)",
    "linear-gradient(135deg, #f59e0b 0%, #ef4444 100%)",
    "linear-gradient(135deg, #ec4899 0%, #8b5cf6 100%)",
    "linear-gradient(135deg, #10b981 0%, #06b6d4 100%)",
  ]
  const charCode = (name || "").charCodeAt(0) || 0
  return { background: gradients[charCode % gradients.length] }
}

function tags(values: string[], color: "orange" | "default" = "default") {
  return (
    <div className="director-asset-card-tags">
      {values.map((value) => <Tag key={value} color={color}>{value}</Tag>)}
    </div>
  )
}

function AssetPromptBlock({ prompt, onCopyPrompt }: { prompt: string; onCopyPrompt?: (value: string) => void }) {
  return (
    <div className="director-asset-card-prompt">
      <div className="director-asset-card-prompt-head">
        <span><Sparkles size={12} /> 一致性生图 Prompt</span>
        {onCopyPrompt ? <Button type="link" size="small" className="copy-link" onClick={() => onCopyPrompt(prompt)}>复制</Button> : null}
      </div>
      <p>{prompt}</p>
    </div>
  )
}

export default function DirectorAssetSummaryCard({ asset, onCopyPrompt }: DirectorAssetSummaryCardProps) {
  if (asset.kind === "character") {
    return (
      <article className="director-asset-card director-asset-card--character">
        <div className="director-asset-card-header">
          <div className="director-asset-card-avatar" style={getCharGradient(asset.name)}>{asset.name.slice(0, 1)}</div>
          <div className="director-asset-card-title-meta">
            <div className="director-asset-card-name-row">
              <h4>{asset.name}</h4>
              {asset.role ? <Tag color="blue">{asset.role}</Tag> : null}
              {asset.age ? <Tag color="cyan">{asset.age}</Tag> : null}
              {asset.gender ? <Tag color={asset.gender === "女" ? "magenta" : "geekblue"}>{asset.gender}</Tag> : null}
            </div>
            {typeof asset.shotsCount === "number" ? <span className="director-asset-card-stat">出现分镜：{asset.shotsCount} 次</span> : null}
          </div>
        </div>
        {asset.fixedProps?.length ? (
          <div className="director-asset-card-detail-row">
            <span className="director-asset-card-label"><Package size={13} /> 固定道具：</span>
            {tags(asset.fixedProps, "orange")}
          </div>
        ) : null}
        {asset.description ? <p className="director-asset-card-description">{asset.description}</p> : null}
        {asset.visualPrompt ? <AssetPromptBlock prompt={asset.visualPrompt} onCopyPrompt={onCopyPrompt} /> : null}
      </article>
    )
  }

  if (asset.kind === "scene") {
    return (
      <article className="director-asset-card director-asset-card--scene">
        <div className="director-asset-card-header">
          <div className="director-asset-card-icon director-asset-card-icon--scene"><MapPin size={20} /></div>
          <div className="director-asset-card-title-meta">
            <h4>{asset.name}</h4>
            <div className="director-asset-card-badges">
              {asset.sceneType ? <Tag color={asset.sceneType === "固定场景" || asset.sceneType === "固定场景库" ? "green" : "blue"}>{asset.sceneType}</Tag> : null}
              {typeof asset.shotsCount === "number" ? <span className="director-asset-card-stat">引用 {asset.shotsCount} 镜头</span> : null}
            </div>
          </div>
        </div>
        {asset.description ? <p className="director-asset-card-description">{asset.description}</p> : null}
        {asset.elements?.length ? (
          <div className="director-asset-card-detail-row">
            <span className="director-asset-card-label">陈设元素：</span>
            {tags(asset.elements)}
          </div>
        ) : null}
        {asset.visualPrompt ? <AssetPromptBlock prompt={asset.visualPrompt} onCopyPrompt={onCopyPrompt} /> : null}
      </article>
    )
  }

  return (
    <article className="director-asset-card director-asset-card--prop">
      <div className="director-asset-card-prop-top">
        <div className="director-asset-card-icon director-asset-card-icon--prop"><Package size={18} /></div>
        <div>
          <h4>{asset.name}</h4>
          {asset.propKind ? <Tag color={asset.propKind === "人物固定道具" ? "orange" : asset.propKind === "场景陈设道具" ? "cyan" : "blue"}>{asset.propKind}</Tag> : null}
        </div>
      </div>
      {(asset.relatedCharacter || typeof asset.count === "number") ? (
        <div className="director-asset-card-prop-bottom">
          {asset.relatedCharacter ? <div><span>关联角色/场景：</span><span>{asset.relatedCharacter}</span></div> : null}
          {typeof asset.count === "number" ? <div><span>出现频次：</span><strong>{asset.count} 次</strong></div> : null}
        </div>
      ) : null}
    </article>
  )
}
