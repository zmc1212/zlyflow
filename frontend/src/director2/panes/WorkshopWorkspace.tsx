import { useEffect, useMemo, useRef, useState } from "react"
import { Alert, Button, Checkbox, Collapse, Dropdown, Empty, Input, Modal, Popover, Progress, Segmented, Select, Skeleton, Tooltip, message } from "antd"
import { Check, ChevronDown, FolderClosed, History, LayoutGrid, List, Mic, MoreHorizontal, PanelLeftClose, PanelLeftOpen, RefreshCw, Scissors, Search, UserRound, Video, X } from "lucide-react"
import { director2ErrorDetail, updateEpisodeBeat, type Director2Asset, type Director2Beat, type Director2EpisodeDetail } from "../api"
import { beatDurationSec } from "../workshop-beat-duration"
import { beatHasUpscaled, beatPlaybackUrl, beatUpscaleDisabledReason } from "../director2-video-settings"
import { assetKindLabel, isPromptDocument, promptDocument, promptPatch, promptReferences, promptText, workshopAssets, type PromptDocument, type WorkshopAsset, type WorkshopPromptPatch } from "../workshop-editor"
import { createWorkshopSaveQueue } from "../workshop-save-queue"
import { selectedWorkshopBeatIds, workshopBatchDeleteReason } from "../workshop-batch"
import { isAwaitingRefineStatus, isWorkshopShotRendered, workshopEpisodeBannerLabel, workshopVideoOverlayLabel, type WorkshopEpisodeVideoProgress, type WorkshopShotVideoProgress } from "../workshop-video-progress"
import { WorkshopAssetCard, WorkshopAssetThumbnail, WorkshopPromptEditor, type WorkshopPromptEditorHandle } from "./WorkshopPromptEditor"
import WorkshopPlayer from "./WorkshopPlayer"

type SaveDraft = { document: PromptDocument; patch?: WorkshopPromptPatch; error?: string; state: "pending" | "saving" | "saved" | "error" | "recovered" }
export type WorkshopWorkspaceProps = {
  csrfToken: string; projectId: string; episode: Director2EpisodeDetail; selected: Director2Beat | null; assets: Director2Asset[]; assetsState: "loading" | "ready" | "error"
  progress: Record<string, WorkshopShotVideoProgress>; episodeProgress?: WorkshopEpisodeVideoProgress | null; checked: Set<string>; generatingPrompt: boolean; upscalingId: string | null
  onSelect: (beat: Director2Beat) => void; onPatch: (id: string, patch: Partial<Director2Beat>) => void
  onCheck: (beat: Director2Beat, value: boolean) => void; onCheckAll: (value: boolean) => void
  onDetails: () => void; onDubbing: () => void; onSmartEdit: () => void; onGenerate: () => void; onPrompt: () => void; onUpscale: (beat: Director2Beat) => void; onBatchGenerate: () => void; onBatchDelete: (ids: string[]) => Promise<void>; batchGenerating: boolean; batchDeleting: boolean
  onRefine: (action: "confirm" | "skip", progress: WorkshopShotVideoProgress) => void; refineBusy: boolean
  onHistory: (beat: Director2Beat) => void; onRefreshAssets: () => void; onSaveState: (state: string, save: () => void) => void
  previewRequest?: number
  submittingVideo: boolean
  failures: Record<string, WorkshopShotVideoProgress & { error: string }>
  retryingJobId: string | null
  onRetryVideo: (progress: WorkshopShotVideoProgress) => void
  onBeforeSubmitReady: (flush: ((ids?: string[]) => Promise<void>) | null) => void
}

export default function WorkshopWorkspace(props: WorkshopWorkspaceProps) {
  const { episode, selected: beat } = props
  const assets = useMemo(() => workshopAssets(props.assets), [props.assets])
  const storageKey = (id: string) => `zly:workshop:prompt:${props.projectId}:${episode.id}:${id}`
  const [drafts, setDrafts] = useState<Record<string, SaveDraft>>(() => {
    const recovered: Record<string, SaveDraft> = {}
    episode.beats.forEach(beat => {
      try {
        const stored = JSON.parse(localStorage.getItem(storageKey(beat.id)) || "null")
        if (isPromptDocument(stored?.document) && promptText(stored.document) !== String(beat.video_prompt_zh || "")) recovered[beat.id] = { document: stored.document, state: "recovered" }
      } catch { /* Keep the remote text available when a local recovery record is damaged. */ }
    })
    return recovered
  })
  const draftsRef = useRef(drafts)
  const callbacks = useRef(props)
  callbacks.current = props
  const mounted = useRef(true)
  const editor = useRef<WorkshopPromptEditorHandle>(null)
  const [editorRevision, setEditorRevision] = useState(0)
  const [collapsed, setCollapsed] = useState(false)
  const [batch, setBatch] = useState(false)
  const [batchModal, batchModalContext] = Modal.useModal()
  const [preview, setPreview] = useState(false)
  useEffect(() => { if (props.previewRequest) setPreview(true) }, [props.previewRequest])
  const [openReference, setOpenReference] = useState<string | null>(null)
  const queue = useRef<ReturnType<typeof createWorkshopSaveQueue<SaveDraft>> | null>(null)
  const updateDraft = (id: string, value: SaveDraft | null) => {
    const next = { ...draftsRef.current }
    if (value) next[id] = value; else delete next[id]
    draftsRef.current = next
    if (mounted.current) setDrafts(next)
  }
  if (!queue.current) queue.current = createWorkshopSaveQueue<SaveDraft>(async (id, draft) => {
    if (!draft.patch) throw new Error(draft.error || "请先修复资产引用")
    const response = await updateEpisodeBeat(props.csrfToken, props.projectId, episode.id, id, draft.patch)
    if (draftsRef.current[id]?.document === draft.document && mounted.current) callbacks.current.onPatch(id, response.beat)
  }, (id, state, error) => {
    const current = draftsRef.current[id]
    if (!current) return
    if (state === "saved") {
      try { localStorage.removeItem(storageKey(id)) } catch { /* Saving to the server already succeeded. */ }
      updateDraft(id, null)
    } else updateDraft(id, { ...current, state, ...(state === "error" ? { error: director2ErrorDetail(error, "保存失败，请重试") } : {}) })
  })
  const save = (force = false) => {
    if (!beat) return
    const current = draftsRef.current[beat.id]
    if (!current || current.state === "recovered" && !force) return
    if (current.state === "recovered") {
      try { const draft = { ...current, patch: promptPatch(current.document, assets), state: "pending" as const }; updateDraft(beat.id, draft); queue.current!.enqueue(beat.id, draft) }
      catch (error) { updateDraft(beat.id, { ...current, state: "error", error: director2ErrorDetail(error, "引用无效") }); return }
    }
    void queue.current!.flush(beat.id).catch(() => {})
  }
  useEffect(() => {
    mounted.current = true
    callbacks.current.onBeforeSubmitReady(async ids => {
      const wanted = ids || callbacks.current.episode.beats.map(item => item.id)
      for (const id of wanted) {
        const draft = draftsRef.current[id]
        if (draft?.state === "recovered") throw new Error("请先保存本地恢复稿，或选择使用服务器版本，再生成视频")
        if (draft && !draft.patch) throw new Error(draft.error || "请先修复资产引用")
        await queue.current!.flush(id)
      }
    })
    const unload = (event: BeforeUnloadEvent) => { if (queue.current?.pending()) { event.preventDefault(); event.returnValue = "" } }
    window.addEventListener("beforeunload", unload)
    return () => { mounted.current = false; callbacks.current.onBeforeSubmitReady(null); window.removeEventListener("beforeunload", unload); void queue.current?.flushAll() }
  }, [])
  const currentDraft = beat ? drafts[beat.id] : undefined
  const document = useMemo(() => beat ? currentDraft?.document || promptDocument(beat, assets) : null, [beat, currentDraft?.document, assets])
  const references = useMemo(() => document ? promptReferences(document, assets) : [], [document, assets])
  const saveState = currentDraft?.state === "error" ? "保存失败" : currentDraft?.state === "recovered" ? "本地待恢复" : currentDraft ? "保存中" : "已保存"
  useEffect(() => { props.onSaveState(saveState, () => save(true)) }, [saveState, beat?.id, assets])
  const changed = (doc: PromptDocument) => {
    if (!beat) return
    let patch: WorkshopPromptPatch | undefined
    let error: string | undefined
    try { patch = promptPatch(doc, assets) } catch (reason) { error = director2ErrorDetail(reason, "资产引用无效") }
    const draft: SaveDraft = { document: doc, patch, error, state: error ? "error" : "pending" }
    updateDraft(beat.id, draft)
    try { localStorage.setItem(storageKey(beat.id), JSON.stringify({ document: doc })) } catch { /* The editor still keeps the unsaved document in memory. */ }
    if (patch) props.onPatch(beat.id, { ...patch, h3_prompt: null, h3_prompt_source: "", timestamped_zh_prompt: "" })
    queue.current!.enqueue(beat.id, draft)
  }
  const insert = (asset: WorkshopAsset) => { if (!props.generatingPrompt) editor.current?.insert(asset); setOpenReference(null) }
  const selectId = (id: string) => { const target = episode.beats.find(b => b.id === id); if (target) props.onSelect(target) }
  const selectedIds = selectedWorkshopBeatIds(episode.beats, props.checked)
  const selectedSet = new Set(selectedIds)
  const selectionBusy = props.generatingPrompt || props.batchGenerating || selectedIds.some(id => !!props.progress[id])
  const deleteReason = workshopBatchDeleteReason(episode.beats.length, selectedIds.length, selectionBusy || props.batchDeleting)
  const toggleBatch = () => { props.onCheckAll(false); setBatch(value => !value) }
  const requestBatchDelete = () => {
    if (deleteReason) return
    const ids = [...selectedIds]
    batchModal.confirm({
      title: `删除所选 ${ids.length} 个片段？`,
      content: "片段正文及编辑内容将被移除，原剧本、资产、云端媒体和历史任务保留。已有整集合成需要重新合成。",
      okText: "删除片段", cancelText: "取消", okButtonProps: { danger: true }, autoFocusButton: "cancel",
      onOk: async () => {
        try {
          await queue.current!.flushAll()
          await props.onBatchDelete(ids)
          ids.forEach(id => { try { localStorage.removeItem(storageKey(id)) } catch { /* optional local draft */ } updateDraft(id, null) })
        } catch (error) { message.error(director2ErrorDetail(error, "删除片段失败，请重试")); throw error }
      },
    })
  }
  const progress = beat ? props.progress[beat.id] : undefined
  const failure = beat ? props.failures[beat.id] : undefined
  const submitting = props.submittingVideo || props.batchGenerating
  const awaiting = isAwaitingRefineStatus(progress?.status)
  const shotRendered = isWorkshopShotRendered(progress)
  const shotQueued = progress?.shotStage === "queued"
  const playbackBeats = useMemo(() => episode.beats.map(beat => {
    const status = props.progress[beat.id]
    const url = status?.shotUrl || (status && status.scope !== "upscale" ? status.previewUrl || "" : "")
    return url ? { ...beat, upscaled_video_url: null, video_url: url } : beat
  }), [episode.beats, props.progress])
  const activeBeat = useMemo(() => playbackBeats.find(item => item.id === beat?.id) || beat, [playbackBeats, beat])
  return <div className={"ws-workspace" + (collapsed ? " is-asset-collapsed" : "")}>
    {!collapsed && <WorkshopAssetLibrary assets={assets} episode={episode.number} beats={episode.beats} loading={props.assetsState === "loading"} error={props.assetsState === "error"} onRetry={props.onRefreshAssets} onInsert={insert} onCollapse={() => setCollapsed(true)}/>}
    <section className="ws-workbench">
      {props.episodeProgress && <div className="ws-episode-progress" role="status" aria-live="polite"><Progress percent={props.episodeProgress.progress} size="small" showInfo={false} status="active"/><span className="ws-episode-progress-label">{workshopEpisodeBannerLabel(props.episodeProgress)}</span></div>}
      <div className="ws-workbench-upper">
        <section className="ws-script-panel" aria-label="片段正文编辑区">
          {beat && document ? <>
            <header className="ws-script-header"><div className="ws-clip-heading">{collapsed && <Tooltip title="展开资产库"><Button type="text" size="small" icon={<PanelLeftOpen size={16}/>} aria-label="展开资产库" onClick={() => setCollapsed(false)}/></Tooltip>}<h2>片段 {String(episode.beats.findIndex(b => b.id === beat.id) + 1).padStart(2, "0")}</h2><Dropdown trigger={["click"]} menu={{ items: [{ key: "generate-prompt", label: props.generatingPrompt ? "正在更新提示词" : "生成 / 更新提示词", disabled: props.generatingPrompt, onClick: props.onPrompt }, { key: "details", label: "高级制作详情", onClick: props.onDetails }, { type: "divider" }, ...assets.map(asset => ({ key: asset.key, label: <span className="ws-reference-choice"><WorkshopAssetThumbnail asset={asset}/><span>{asset.title}</span></span>, disabled: props.generatingPrompt, onClick: () => insert(asset) }))] }}><Button type="text" size="small" className="ws-quiet-action">引用资产及工具</Button></Dropdown></div>
              <div className="ws-reference-assets" aria-label="本片段引用资产">{references.map(asset => <Popover key={asset.key} open={openReference === asset.key} onOpenChange={open => setOpenReference(open ? asset.key : null)} trigger="click" placement="bottomLeft" arrow={false} content={<WorkshopAssetCard asset={asset} onInsert={() => insert(asset)}/>}><Tooltip title={asset.title}><Button type="text" className="ws-reference-tile" aria-label={"查看引用资产 " + asset.title}><WorkshopAssetThumbnail asset={asset}/></Button></Tooltip></Popover>)}</div>
            </header>
            <div className="ws-script-document" key={beat.id + ":" + editorRevision}>
              {currentDraft?.state === "recovered" && <Alert type="warning" showIcon title="有尚未同步的本地修改" description="当前展示本地草稿；保存后会更新当前片段。" action={<><Button size="small" onClick={() => save(true)}>保存此稿</Button><Button size="small" onClick={() => { localStorage.removeItem(storageKey(beat.id)); updateDraft(beat.id, null); setEditorRevision(v => v + 1) }}>使用服务器版本</Button></>}/>}
              {currentDraft?.error && <Alert type="error" showIcon title={currentDraft.error} action={<Button size="small" onClick={() => save(true)}>重试保存</Button>}/>}
              {props.assetsState === "loading" ? <Skeleton active paragraph={{ rows: 6 }}/> : <WorkshopPromptEditor ref={editor} document={document} assets={assets} label={"片段 " + String(episode.beats.findIndex(b => b.id === beat.id) + 1).padStart(2, "0") + " 正文"} disabled={props.generatingPrompt} onChange={changed} onSave={save}/>}
            </div>
            <footer className="ws-document-footer"><Button type="text" size="small" onClick={props.onDetails}>高级制作详情<ChevronDown size={12}/></Button>{props.generatingPrompt && <span>正在更新提示词…</span>}</footer>
          </> : <Empty description="本集尚未规划片段"/>}
        </section>
        <aside className="ws-preview-panel" aria-label="片段视频预览">{beat && <div className="ws-preview-center">
          <WorkshopPlayer beats={playbackBeats} selectedId={beat.id} onSelect={selectId} onExpand={() => setPreview(true)} active={!preview}/>
          <div className="ws-preview-meta"><span>片段 {String(episode.beats.findIndex(b => b.id === beat.id) + 1).padStart(2, "0")}</span><span>{beatDurationSec(beat.video_duration)}s · {awaiting ? "待确认二采" : beatHasUpscaled(activeBeat) ? "已出片 · 超清" : beatPlaybackUrl(activeBeat) ? "已出片" : progress ? "生成中" : "待制作"}</span></div>
          {progress && !awaiting && <div className="ws-video-progress" role="status">{shotRendered ? <Check size={13} aria-hidden/> : !shotQueued && <Progress percent={progress.progress} size="small" showInfo={false}/>}<span>{workshopVideoOverlayLabel(progress.status, progress.progress, progress)}</span></div>}
          {failure && !progress && <Alert type="error" showIcon title="视频生成中断" description={<>{failure.error}<br/>重试会继续本次提交；修改正文后请重新生成。</>} action={<Button size="small" loading={props.retryingJobId === failure.jobId} disabled={Boolean(props.retryingJobId) || submitting} onClick={() => props.onRetryVideo(failure)}>重试当前步骤</Button>}/>}
          {awaiting && progress && <div className="ws-refine-actions"><p>一采预览已生成</p><Button size="small" loading={props.refineBusy} onClick={() => props.onRefine("confirm", progress)}>确认二采</Button><Button size="small" disabled={props.refineBusy} onClick={() => props.onRefine("skip", progress)}>保留一采</Button></div>}
          <div className="ws-preview-actions"><Button type="text" size="small" onClick={() => props.onHistory(beat)}>历史版本</Button><Button type="text" size="small" icon={<RefreshCw size={13}/>} loading={props.submittingVideo || Boolean(progress) && progress?.scope !== "upscale"} disabled={props.generatingPrompt || submitting || Boolean(progress)} onClick={props.onGenerate}>{beatPlaybackUrl(activeBeat) ? "重拍片段" : "生成片段"}</Button><Dropdown trigger={["click"]} menu={{ items: [{ key: "upscale", label: "智能超清", disabled: Boolean(beatUpscaleDisabledReason(beat, progress)) || props.upscalingId === beat.id, title: beatUpscaleDisabledReason(beat, progress), onClick: () => props.onUpscale(beat) }, { key: "download", label: "下载当前视频", disabled: !beatPlaybackUrl(activeBeat), onClick: () => { const a = window.document.createElement("a"); a.href = beatPlaybackUrl(activeBeat); a.download = "片段-" + beat.sequence + ".mp4"; a.target = "_blank"; a.rel = "noopener"; a.click() } }, { key: "details", label: "高级制作详情", onClick: props.onDetails }] }}><Button type="text" size="small" aria-label="片段更多操作" icon={<MoreHorizontal size={14}/>}/></Dropdown></div>
        </div>}</aside>
      </div>
      <section className="ws-filmstrip" aria-label="本集视频片段">
        <div className="ws-filmstrip-toolbar" role="toolbar" aria-label="片段批量操作">
          <Button type="text" size="small" className={"ws-batch-toggle" + (batch ? " is-active" : "")} aria-label={batch ? "退出批量" : "批量"} aria-pressed={batch} icon={<List size={12}/>} onClick={toggleBatch}>批量{batch && <X size={12}/>}</Button>
          {batch && <>
            <Checkbox className="ws-check-all" aria-label="全选" checked={selectedIds.length === episode.beats.length && !!episode.beats.length} indeterminate={selectedIds.length > 0 && selectedIds.length < episode.beats.length} onChange={event => props.onCheckAll(event.target.checked)}><span>全选</span><span className="ws-selected-count" aria-live="polite">· 已选 {selectedIds.length} 个</span></Checkbox>
            <div className="ws-batch-actions"><Button className="ws-batch-generate" size="small" disabled={!selectedIds.length || selectionBusy || props.batchDeleting} loading={props.batchGenerating} onClick={props.onBatchGenerate}>批量生成</Button><Tooltip title={deleteReason || undefined}><span className="ws-batch-delete-wrap"><Button className="ws-batch-delete" size="small" disabled={!!deleteReason} loading={props.batchDeleting} onClick={requestBatchDelete}>批量删除</Button></span></Tooltip></div>
          </>}
          <div className="ws-filmstrip-tools"><Button type="text" size="small" icon={<Mic size={13}/>} onClick={props.onDubbing}>配音</Button><Button type="text" size="small" icon={<Scissors size={13}/>} onClick={props.onSmartEdit}>智能剪辑</Button></div>
        </div>
        <div className="ws-filmstrip-items">{episode.beats.map((item, index) => {
          const checked = selectedSet.has(item.id)
          const highlighted = batch ? checked : item.id === beat?.id
          const playback = playbackBeats[index] || item
          const shotProgress = props.progress[item.id]
          const thumbUrl = beatPlaybackUrl(playback)
          return <div className="ws-filmstrip-entry" key={item.id}>
            <Button type="text" className={"ws-filmstrip-item" + (highlighted ? " is-selected" : "")} aria-label={"选择片段" + (index + 1)} aria-pressed={highlighted} onClick={() => batch ? props.onCheck(item, !checked) : props.onSelect(item)}>
              <span className="ws-filmstrip-thumb">{thumbUrl ? <video src={thumbUrl + "#t=0.01"} preload="metadata" muted playsInline/> : item.sketch_url || item.render_url ? <img src={item.render_url || item.sketch_url || ""} alt=""/> : <span className="ws-empty-thumb"><Video size={19}/></span>}{shotProgress && !isWorkshopShotRendered(shotProgress) ? <span className="ws-thumb-progress">{isAwaitingRefineStatus(shotProgress.status) ? "待确认" : shotProgress.shotStage === "queued" ? "排队" : shotProgress.progress + "%"}</span> : thumbUrl ? <span className="ws-ready-dot" aria-label="已出片"/> : null}</span>
              <span className="ws-filmstrip-label">片段 {String(index + 1).padStart(2, "0")}<i>·</i>{beatDurationSec(item.video_duration)}s</span>
            </Button>
            {batch ? <Checkbox className="ws-batch-check" checked={checked} aria-label={"勾选片段" + (index + 1)} onChange={event => props.onCheck(item, event.target.checked)}/> : <Tooltip title="历史记录"><Button type="text" size="small" className="ws-clip-history" icon={<History size={11}/>} aria-label={"片段" + (index + 1) + " 历史记录"} onClick={() => { props.onSelect(item); props.onHistory(item) }}/></Tooltip>}
          </div>
        })}</div>
      </section>
    </section>
    {batchModalContext}
    <Modal open={preview} onCancel={() => setPreview(false)} title={"第 " + episode.number + " 集 · " + episode.title} footer={null} width={1000} centered destroyOnHidden className="ws-preview-modal">{beat && <WorkshopPlayer beats={playbackBeats} selectedId={beat.id} onSelect={selectId}/>}</Modal>
  </div>
}

function WorkshopAssetLibrary({ assets, episode, beats, loading, error, onRetry, onInsert, onCollapse }: { assets: WorkshopAsset[]; episode: number; beats: Director2Beat[]; loading: boolean; error: boolean; onRetry: () => void; onInsert: (asset: WorkshopAsset) => void; onCollapse: () => void }) {
  const [query, setQuery] = useState("")
  const [layout, setLayout] = useState("list")
  const [kind, setKind] = useState("all")
  const [grouped, setGrouped] = useState(true)
  const [scope, setScope] = useState("episode")
  const [openGroups, setOpenGroups] = useState<string[]>(["character", "scene", "prop", "all"])
  const [openAsset, setOpenAsset] = useState<string | null>(null)
  const [viewing, setViewing] = useState<WorkshopAsset | null>(null)
  const linkedIds = new Set(beats.flatMap(beat => [...(beat.character_ids || []), ...(beat.prop_ids || []), ...(beat.scene_id ? [beat.scene_id] : [])]))
  const linkedNames = new Set(beats.flatMap(beat => [...(beat.characters || []), ...(beat.props || []), ...(beat.scene ? [beat.scene] : [])]))
  const filtered = assets.filter(asset => (scope === "project" || linkedIds.has(asset.id) || linkedNames.has(asset.name)) && (asset.name + asset.variant).includes(query) && (kind === "all" || kind === asset.kind))
  const groups = (grouped ? ["character", "scene", "prop"] : ["all"]).flatMap(group => {
    const items = filtered.filter(a => group === "all" || a.kind === group)
    return items.length ? [{ key: group, label: group === "all" ? "全部资产" : assetKindLabel(group), children: <div className="ws-asset-items">{items.map(asset => <div className="ws-asset-row-wrapper" key={asset.key}><Popover open={openAsset === asset.key} onOpenChange={open => setOpenAsset(open ? asset.key : null)} trigger="click" arrow={false} placement="rightTop" content={<WorkshopAssetCard asset={asset} onInsert={() => { onInsert(asset); setOpenAsset(null) }}/>}><Button type="text" className="ws-asset-row" aria-label={"资产 " + asset.title}><WorkshopAssetThumbnail asset={asset}/><span>{asset.name}{asset.variant && <span className="ws-asset-variant"> · {asset.variant}</span>}</span></Button></Popover><Dropdown trigger={["click"]} menu={{ items: [{ key: "view", label: "查看资产", onClick: () => setViewing(asset) }, { key: "insert", label: "引用到光标位置", onClick: () => onInsert(asset) }] }}><Button type="text" size="small" className="ws-asset-more" icon={<MoreHorizontal size={14}/>} aria-label={asset.title + " 更多操作"}/></Dropdown></div>)}</div> }] : []
  })
  return <aside className="ws-asset-library" aria-label="本集资产库"><div className="ws-library-title"><h3>资产库</h3><Segmented size="small" value={layout} onChange={setLayout} options={[{ value: "list", icon: <List size={13}/>, label: <span className="ws-sr-only">列表视图</span> }, { value: "grid", icon: <LayoutGrid size={13}/>, label: <span className="ws-sr-only">宫格视图</span> }]}/><Button type="text" size="small" icon={<PanelLeftClose size={14}/>} aria-label="收起资产库" onClick={onCollapse}/></div><div className="ws-library-filters"><Input aria-label="搜索资产库" prefix={<Search size={12}/>} placeholder="搜索" value={query} onChange={event => setQuery(event.target.value)} allowClear variant="filled"/><Select className="ws-asset-scope" aria-label="资产库范围" variant="borderless" value={scope} onChange={setScope} options={[{ value: "episode", label: "第 " + episode + " 集" }, { value: "project", label: "全部资产" }]}/><Dropdown trigger={["click"]} menu={{ selectable: true, selectedKeys: [grouped ? "type" : "none"], items: [{ key: "type", label: "按类型分组", onClick: () => setGrouped(true) }, { key: "none", label: "不分组", onClick: () => setGrouped(false) }] }}><Button type="text" size="small">分组<ChevronDown size={10}/></Button></Dropdown><Dropdown trigger={["click"]} menu={{ selectable: true, selectedKeys: [kind], items: ["all", "character", "scene", "prop"].map(kind => ({ key: kind, label: kind === "all" ? "全部" : assetKindLabel(kind), onClick: () => setKind(kind) })) }}><Button type="text" size="small">{kind === "all" ? "标签" : assetKindLabel(kind)}<ChevronDown size={10}/></Button></Dropdown></div><div className={"ws-library-contents " + layout}>{loading ? <Skeleton active paragraph={{ rows: 8 }}/> : error ? <Alert type="error" showIcon title="资产加载失败" action={<Button size="small" onClick={onRetry}>重试</Button>}/> : filtered.length ? <Collapse ghost activeKey={openGroups} onChange={keys => setOpenGroups(typeof keys === "string" ? [keys] : keys)} expandIcon={() => <FolderClosed size={13}/>} items={groups}/> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={scope === "episode" ? "本集没有匹配的资产" : "没有找到相关资产"}>{scope === "episode" && <Button size="small" onClick={() => setScope("project")}>查看全部资产</Button>}</Empty>}</div><Modal title={viewing?.title} open={!!viewing} onCancel={() => setViewing(null)} footer={null} width={400} centered>{viewing && <WorkshopAssetCard asset={viewing} onInsert={() => { onInsert(viewing); setViewing(null) }}/>}</Modal></aside>
}
