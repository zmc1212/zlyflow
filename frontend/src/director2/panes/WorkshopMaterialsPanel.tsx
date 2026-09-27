import { Button, Checkbox, Image, Tag, Typography } from "antd"
import { ArrowRight, ImageIcon, Plus } from "lucide-react"
import type { Director2Asset, Director2EpisodeDetail, PromptReferenceSlot } from "../api"
import type { WorkshopGroup } from "../workshop-api"
import { getAssetDisplayAvatar } from "./assets/shared"

type AssetKind = "character" | "scene" | "prop"
type Props = {
  beat: Director2EpisodeDetail["beats"][number]
  assets: Director2Asset[]
  assetRefs: PromptReferenceSlot[]
  group?: WorkshopGroup
  disabled: boolean
  onSelectAssets: (kind: AssetKind) => void
  onGroupSettings: () => void
  onWritingReferences: (urls: string[]) => void
  onGenerateSketch: () => void
  onGenerateTriptych: () => void
  onOpenPrompts: () => void
}
const categories = [
  { kind: "character", title: "本镜人物", empty: "尚未关联人物", action: "选择人物与造型" },
  { kind: "scene", title: "本镜场景", empty: "尚未关联场景", action: "选择场景" },
  { kind: "prop", title: "本镜道具", empty: "尚未关联道具", action: "选择道具" },
] as const

export default function WorkshopMaterialsPanel({ beat, assets, assetRefs, group, disabled, onSelectAssets, onGroupSettings, onWritingReferences, onGenerateSketch, onGenerateTriptych, onOpenPrompts }: Props) {
  const linkedIds = [...(beat.character_ids || []), beat.scene_id, ...(beat.prop_ids || [])]
  const writingRefs = [...assetRefs.filter(slot => slot.asset_id && linkedIds.includes(slot.asset_id)),
    ...[{ image_url: beat.sketch_url, name: "本镜草图" }, { image_url: beat.triptych_url, name: "三联关键帧" }].filter(slot => slot.image_url)]
    .filter((slot, index, all) => all.findIndex(item => item.image_url === slot.image_url) === index)
  const selected = beat.workshop_writing_refs || []
  return <div className="workshop-materials-panel" aria-label="本镜素材与参考">
    <header className="workshop-materials-intro">
      <div><Typography.Title level={5}>本镜素材</Typography.Title><Typography.Text type="secondary">先确定出镜资产，再选择写稿和视频各自使用的参考图。</Typography.Text></div>
      <Button onClick={onOpenPrompts}>去写提示词 <ArrowRight size={14} /></Button>
    </header>
    <div className="workshop-linked-assets">{categories.map(({ kind, title, empty, action }) => {
      const linked = assets.filter(asset => asset.kind === kind && (kind === "character" ? beat.character_ids?.includes(asset.id) : kind === "scene" ? beat.scene_id === asset.id : beat.prop_ids?.includes(asset.id)))
      return <section className="workshop-material-section" key={kind} aria-label={title}>
        <header className="workshop-material-section-head"><h3>{title}<span>{linked.length}</span></h3><Button icon={<Plus size={14} />} disabled={disabled} onClick={() => onSelectAssets(kind)}>{action}</Button></header>
        {linked.length ? <div className="workshop-material-gallery">{linked.map(asset => {
          const look = ((asset.extra?.identities || []) as Array<{ id: string; name?: string; image_url?: string }>).find(item => item.id === beat.character_look_ids?.[asset.id])
          const url = look?.image_url || getAssetDisplayAvatar(asset)
          return <figure className="workshop-material-tile" key={asset.id}>
            {url ? <Image src={url} alt={asset.name} /> : <div className="workshop-material-empty-image"><ImageIcon size={24} /><span>暂无图片</span></div>}
            <figcaption><strong>{asset.name}</strong>{look?.name && <span>{look.name}</span>}</figcaption>
          </figure>
        })}</div> : <div className="workshop-material-empty"><ImageIcon size={18} /><span>{empty}，可按本镜需要添加。</span></div>}
      </section>
    })}</div>
    <section className="workshop-material-section" aria-label="最终视频参考">
      <header className="workshop-material-section-head"><div><h3>最终视频参考<span>{group?.reference_slots.length || 0} 张</span></h3><p>同组共享编号；这里的图片会提交给视频模型。</p></div><Button disabled={!group || disabled} onClick={onGroupSettings}>管理本组参考</Button></header>
      {group?.reference_slots.length ? <div className="workshop-material-gallery">{group.reference_slots.map(slot => <figure className="workshop-material-tile" key={slot.token}>
        <Image src={slot.image_url || undefined} alt={slot.name} /><figcaption><Tag>{slot.token}</Tag><strong>{slot.name}</strong></figcaption>
      </figure>)}</div> : <div className="workshop-material-empty"><ImageIcon size={18} /><span>尚未配置视频参考图，可在组设置中管理。</span></div>}
    </section>
    <section className="workshop-material-section" aria-label="画面草图">
      <header className="workshop-material-section-head"><div><h3>画面草图<Tag>可选</Tag></h3><p>辅助确定构图和关键帧；出片前请检查上方的最终视频参考。</p></div></header>
      <div className="workshop-sketch-grid">{[
        { name: "本镜草图", description: "确认人物站位与画面构图", url: beat.sketch_url, action: onGenerateSketch, label: "生成本镜草图" },
        { name: "三联关键帧", description: "检查动作起幅、过程与落幅", url: beat.triptych_url, action: onGenerateTriptych, label: "生成三联关键帧" },
      ].map(item => <div className="workshop-sketch-item" key={item.name}>
        {item.url ? <Image src={item.url} alt={item.name} /> : <div className="workshop-sketch-placeholder"><ImageIcon size={26} /><span>尚未生成{item.name}</span></div>}
        <div className="workshop-sketch-caption"><div><strong>{item.name}</strong><span>{item.description}</span></div><Button disabled={disabled} onClick={item.action}>{item.url ? "重新生成" : item.label}</Button></div>
      </div>)}</div>
    </section>
    <section className="workshop-material-section" aria-label="本镜写稿参考">
      <header className="workshop-material-section-head"><div><h3>本镜写稿参考<span>已选 {selected.length} 张</span></h3><p>勾选后即时保存，仅供 AI 写提示词看图；不会自动作为视频输入。</p></div></header>
      {writingRefs.length ? <div className="workshop-material-gallery">{writingRefs.map(slot => <div className={"workshop-material-tile workshop-writing-tile" + (selected.includes(slot.image_url!) ? " is-selected" : "")} key={slot.image_url}>
        <Checkbox aria-label={`写稿参考：${slot.name}`} disabled={disabled} checked={selected.includes(slot.image_url!)} onChange={event => onWritingReferences(event.target.checked ? [...new Set([...selected, slot.image_url!])] : selected.filter(url => url !== slot.image_url))}>{selected.includes(slot.image_url!) ? "已用于写稿" : "用于写稿"}</Checkbox>
        <Image src={slot.image_url || undefined} alt={slot.name} /><div className="workshop-material-caption"><strong>{slot.name}</strong></div>
      </div>)}</div> : <div className="workshop-material-empty"><ImageIcon size={18} /><span>关联带图片的资产，或生成画面草图后，可在这里选择写稿参考。</span></div>}
    </section>
  </div>
}
