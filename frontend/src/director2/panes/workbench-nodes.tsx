/**
 * 剧本工作台节点：剧本 / 资产 / 镜头 / 成片。
 * 只读派生图 —— Handle 仅用于连线渲染（不可交互，同 FeaturedProcessPage 的做法），
 * 节点内的操作按钮走既有 API，业务数据不在画布上编辑。
 */
import { memo, useState } from "react"
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react"
import { ArrowRight, Camera, Clapperboard, Film, Play, Sparkles, UserRound, Wand2 } from "lucide-react"
import { assetStatusLamp, beatStatusLamp, type WorkbenchAsset, type WorkbenchBeat } from "../workbench-graph"

export type WbScriptData = {
  number: number
  title: string
  summary: string
  beatsTotal: number
  overallPct: number
  onGoContent: () => void
}
export type WbAssetData = { asset: WorkbenchAsset }
export type WbBeatData = {
  beat: WorkbenchBeat
  busy: boolean
  onGeneratePrompt: (beatId: string) => void
  onRender: (beatId: string) => void
  onOpenWorkshop: (beatId: string) => void
  onInspect: (beatId: string) => void
}
export type WbEpisodeData = {
  number: number
  title: string
  videoUrl: string
  overallPct: number
  shotsDone: number
  beatsTotal: number
  onCompose: () => void
}

export type WbScriptNode = Node<WbScriptData, "wb-script">
export type WbAssetNode = Node<WbAssetData, "wb-asset">
export type WbBeatNode = Node<WbBeatData, "wb-beat">
export type WbEpisodeNode = Node<WbEpisodeData, "wb-episode">

/** 派生图不需要用户连线，Handle 隐藏但必须存在，否则边不渲染。 */
function WbHandles() {
  return <>
    <Handle type="target" position={Position.Left} className="wb-handle" isConnectable={false} />
    <Handle type="source" position={Position.Right} className="wb-handle" isConnectable={false} />
  </>
}

const ASSET_KIND_LABELS: Record<string, string> = { character: "角色", scene: "场景", prop: "道具" }

export const WbScriptNodeView = memo(function WbScriptNodeView({ data }: NodeProps<WbScriptNode>) {
  return <div className="wb-node wb-script" style={{ width: 236 }}>
    <WbHandles />
    <button type="button" className="wb-script-body" onClick={data.onGoContent} aria-label={`查看第 ${data.number} 集剧本`}>
      <span className="wb-script-ep">第 {data.number} 集</span>
      <strong className="wb-script-title">{data.title || "未命名一集"}</strong>
      {data.summary ? <p className="wb-script-summary">{data.summary}</p> : <p className="wb-script-summary is-empty">剧本摘要待生成</p>}
      <span className="wb-script-meta"><Clapperboard size={12} /> {data.beatsTotal} 镜 · 进度 {data.overallPct}%</span>
    </button>
  </div>
})

export const WbAssetNodeView = memo(function WbAssetNodeView({ data }: NodeProps<WbAssetNode>) {
  const asset = data.asset
  const lamp = assetStatusLamp(asset)
  const [failed, setFailed] = useState(false)
  return <div className={`wb-node wb-asset${asset.ready ? "" : " is-missing"}`} style={{ width: 236 }}>
    <WbHandles />
    <div className="wb-asset-thumb">
      {asset.image_url && !failed
        ? <img src={asset.image_url} alt={asset.name} loading="lazy" onError={() => setFailed(true)} />
        : asset.kind === "character" ? <UserRound size={18} /> : <Camera size={18} />}
    </div>
    <div className="wb-asset-copy">
      <strong title={asset.name}>{asset.name}</strong>
      <span className="wb-asset-kind">{ASSET_KIND_LABELS[asset.kind] || asset.kind}{asset.ref_beats ? ` · 引用 ${asset.ref_beats} 镜` : ""}</span>
      <span className={`wb-lamp is-${lamp.tone}`}><i />{lamp.label}</span>
    </div>
  </div>
})

export const WbBeatNodeView = memo(function WbBeatNodeView({ data }: NodeProps<WbBeatNode>) {
  const beat = data.beat
  const lamp = beatStatusLamp(beat)
  return <div className={`wb-node wb-beat is-${lamp.tone}${beat.awaiting_refine ? " is-awaiting" : ""}`} style={{ width: 268 }}>
    <WbHandles />
    <header className="wb-beat-head">
      <span className="wb-beat-seq">第 {beat.sequence} 镜</span>
      <span className="wb-beat-title" title={beat.heading || beat.title}>{beat.heading || beat.title}</span>
      <span className={`wb-lamp is-${lamp.tone}`}><i />{lamp.label}</span>
    </header>
    <button type="button" className="wb-beat-body" onClick={() => data.onInspect(beat.id)} aria-label={`查看第 ${beat.sequence} 镜详情`}>
      {beat.video_url
        ? <video className="wb-beat-video" src={beat.video_url} muted preload="metadata" />
        : <p className="wb-beat-text">{beat.text || (beat.has_prompt ? "生成指令已就绪，待出片" : "还没有生成指令")}</p>}
    </button>
    <footer className="wb-beat-actions">
      <button type="button" className={`wb-act${beat.has_prompt ? "" : " is-primary"}`} disabled={data.busy}
        onClick={() => data.onGeneratePrompt(beat.id)} aria-label={`第 ${beat.sequence} 镜生成提示词`}>
        <Wand2 size={11} />{beat.has_prompt ? "重出指令" : "生成指令"}
      </button>
      <button type="button" className="wb-act is-primary" disabled={data.busy}
        onClick={() => data.onRender(beat.id)} aria-label={`第 ${beat.sequence} 镜出片`}>
        <Film size={11} />{beat.has_video ? "重拍" : "出片"}
      </button>
      <button type="button" className="wb-act" onClick={() => data.onOpenWorkshop(beat.id)} aria-label={`第 ${beat.sequence} 镜在工坊打开`}>
        <ArrowRight size={11} />工坊
      </button>
    </footer>
  </div>
})

export const WbEpisodeNodeView = memo(function WbEpisodeNodeView({ data }: NodeProps<WbEpisodeNode>) {
  const complete = data.beatsTotal > 0 && data.shotsDone >= data.beatsTotal
  return <div className={`wb-node wb-episode${complete ? " is-complete" : ""}`} style={{ width: 256 }}>
    <WbHandles />
    <header className="wb-episode-head">
      <Sparkles size={13} />
      <strong>第 {data.number} 集 · 成片</strong>
    </header>
    {data.videoUrl
      ? <video className="wb-episode-video" src={data.videoUrl} muted preload="metadata" />
      : <div className="wb-episode-empty"><Play size={16} /><span>{complete ? "成片合成中…" : "镜头全部出片后可合成整集"}</span></div>}
    <footer className="wb-episode-foot">
      <span className="wb-episode-count">{data.shotsDone}/{data.beatsTotal} 镜</span>
      <button type="button" className="wb-act is-primary" onClick={data.onCompose} aria-label="去智能剪辑合成">
        <Sparkles size={11} />去合成
      </button>
    </footer>
  </div>
})
