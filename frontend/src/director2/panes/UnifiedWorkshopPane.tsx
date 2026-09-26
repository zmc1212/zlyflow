import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { Alert, Button, Card, Checkbox, Collapse, Drawer, Empty, Form, Image, Input, InputNumber, Modal, Select, Space, Spin, Table, Tabs, Tag, Typography, message } from "antd"
import { getEpisodeDetail, listDocuments, type Director2Document, listEpisodes, listAssets, listVideoWorkflowModes, getEpisodeProduction, generateEpisodeVideo, generateBeatSketch, generateBeatTriptych, updateEpisodeProduction, upscaleProjectVideoJob, director2ErrorDetail, type Director2Episode, type Director2EpisodeDetail, type Director2Asset, type PromptReferenceSlot } from "../api"
import { readWorkshop, writeWorkshop, planWorkshop, promptWorkshop as submitPromptWorkshop, actWorkshop, splitWorkshopGroup, mergeWorkshopGroups, type WorkshopView, type WorkshopGroup, type WorkshopJob } from "../workshop-api"
import { summarizeWorkshopBlocks } from "../workshop-references"
import { DIRECTOR2_DEFAULT_VIDEO_WORKFLOW, loadSavedVideoSettings, saveVideoSettings, optionSchemaFromMode, visibleVideoOptionFields, type Director2WorkflowMode } from "../director2-video-settings"
import { type ProductionState, materialsForUnit } from "../production"
import { ProductionSound, ProductionFilm } from "./ProductionPanes"
import { getAssetDisplayAvatar } from "./assets/shared"
import ActionPrevisPane from "./ActionPrevisPane"
import { ArrowLeft, Clapperboard, ImageIcon, RefreshCw } from "lucide-react"
import Director2VideoSettingsPopover from "./Director2VideoSettingsPopover"
import "./episode-workshop.css"
import "./unified-workshop.css"

type Props = { csrfToken: string; projectId: string; episodeId?: string | null; onDetailModeChange?: (value: boolean) => void; projectExtra?: unknown; projectSettings?: unknown }
const UnifiedWorkshopPane = forwardRef<{ fetchEpisodes: () => Promise<void> | void }, Props>(function UnifiedWorkshopPane({ csrfToken, projectId, episodeId, onDetailModeChange }, ref) {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [documents, setDocuments] = useState<Director2Document[]>([])
  const [episodes, setEpisodes] = useState<Director2Episode[]>([])
  const [detail, setDetail] = useState<Director2EpisodeDetail | null>(null)
  const [view, setView] = useState<WorkshopView | null>(null)
  const [production, setProduction] = useState<ProductionState | null>(null)
  const [assets, setAssets] = useState<Director2Asset[]>([])
  const [modes, setModes] = useState<Director2WorkflowMode[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [planning, setPlanning] = useState(false)
  const [script, setScript] = useState(false)
  const [workflow, setWorkflow] = useState(DIRECTOR2_DEFAULT_VIDEO_WORKFLOW)
  const [aspect, setAspect] = useState("16:9")
  const [maximum, setMaximum] = useState(3)
  const [target, setTarget] = useState<number | null>(null)
  const [targetDuration, setTargetDuration] = useState<number | null>(null)
  const [reuse, setReuse] = useState(false)
  const [inspector, setInspector] = useState(["h3", "prompt", "prompts"].includes(params.get("tab") || "") ? "material" : "text")
  const [draft, setDraft] = useState("")
  const [revisionTarget, setRevisionTarget] = useState<string | null>(null)
  const [revisionNote, setRevisionNote] = useState("")
  const [groupDraft, setGroupDraft] = useState<WorkshopGroup | null>(null)
  const [candidateGroups, setCandidateGroups] = useState<WorkshopGroup[] | null>(null)
  const [candidateEdits, setCandidateEdits] = useState<Record<string, Record<string, unknown>>>({})
  const [previewJob, setPreviewJob] = useState<string | null>(null)
  const [takeId, setTakeId] = useState("")
  const [assetPicker, setAssetPicker] = useState<"character" | "scene" | "prop" | null>(null)
  const [videoOptions, setVideoOptions] = useState<Record<string, unknown>>(() => loadSavedVideoSettings(projectId) || {})
  const requestSequence = useRef(0)
  const lastEditor = useRef({ id: "", saved: "" })
  const editReferences = useRef<string | undefined>(undefined)
  const groupReferences = useRef<string | undefined>(undefined)
  const plan = view?.plan
  const beat = detail?.beats.find(b => b.id === params.get("source")) || detail?.beats[0]
  const group = plan?.groups.find(g => beat && g.beat_ids.includes(beat.id))
  const currentGroupNumber = plan && group ? plan.groups.indexOf(group) + 1 : 0
  const activeTab = ["shots", "dubbing", "compose"].includes(params.get("tab") || "") ? params.get("tab")! : "shots"
  const mode = modes.find(m => m.id === (plan?.workflow_id || workflow))
  const groupWriting = mode?.prompt_profile === "director_segments"
  const saved = beat ? plan?.shot_prompts[beat.id]?.h3_prompt || "" : ""
  const dirty = draft !== saved
  const revision = plan?.revision ?? view?.legacy_plan?.revision ?? 0
  const planningMode = modes.find(m => m.id === workflow)
  const missingReferenceGroups = plan?.groups.filter(g => g.reference_issues?.length || g.reference_slots.length < (mode?.min_references || 0)) || []
  const planningJob = view?.jobs.find(j => j.id === previewJob) || view?.jobs.find(j => j.kind === "workshop_planning" && j.status === "completed")
  const runningJobs = view?.jobs.filter(j => ["queued", "running"].includes(j.status)) || []
  const candidates = view?.jobs.filter(j => j.kind === "workshop_prompt" && beat && j.payload.candidates[beat.id]) || []
  const pendingPromptIds = new Set(view?.jobs.filter(j => j.kind === "workshop_prompt" && j.status === "completed").flatMap(j =>
    Object.keys(j.payload.candidates || {}).filter(id => !(plan?.applied_candidates?.[j.id] || j.payload.applied_ids || []).includes(id) && detail?.beats.some(b => b.id === id))
  ) || [])

  const loadEpisodes = useCallback(async () => { setEpisodes(await listEpisodes(projectId)) }, [projectId])
  useImperativeHandle(ref, () => ({ fetchEpisodes: loadEpisodes }), [loadEpisodes])
  const load = useCallback(async () => {
    if (!episodeId) return
    const seq = ++requestSequence.current
    try {
      const [next, work, state] = await Promise.all([getEpisodeDetail(projectId, episodeId), readWorkshop(projectId, episodeId), getEpisodeProduction(projectId, episodeId, "director")])
      if (seq !== requestSequence.current) return
      setDetail(next); setView(work); setProduction(state); setError("")
    } catch (err) { if (seq === requestSequence.current) setError(director2ErrorDetail(err, "读取工坊失败")) }
  }, [episodeId, projectId])
  useEffect(() => {
    void loadEpisodes().catch(err => setError(director2ErrorDetail(err, "读取分集失败")))
    void Promise.all([listAssets(projectId), listVideoWorkflowModes(), listDocuments(projectId)]).then(([a, m, docs]) => { setDocuments(docs); setAssets(a); setModes(m.modes.filter(w => w.prompt_profile === "director_segments" || w.prompt_profile === "full_reference")) }).catch(err => setError(director2ErrorDetail(err, "读取制作配置失败")))
  }, [loadEpisodes, projectId])
  useEffect(() => {
    setDetail(null); setView(null); setProduction(null); setTakeId(""); onDetailModeChange?.(Boolean(episodeId))
    void load(); const timer = setInterval(() => void load(), 4000)
    return () => { clearInterval(timer); requestSequence.current++ }
  }, [load, episodeId])
  useEffect(() => {
    const previous = lastEditor.current
    setDraft(value => previous.id !== beat?.id || value === previous.saved ? saved : value)
    if (previous.id !== beat?.id) setTakeId("")
    lastEditor.current = { id: beat?.id || "", saved }
  }, [beat?.id, saved])
  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = "" }
    window.addEventListener("beforeunload", warn)
    return () => window.removeEventListener("beforeunload", warn)
  }, [dirty])
  useEffect(() => {
    if (params.get("mode") || ["plan", "script"].includes(params.get("tab") || "")) {
      const next = new URLSearchParams(params); next.delete("mode"); next.set("tab", "shots"); setParams(next, { replace: true })
    }
  }, [params, setParams])
  useEffect(() => {
    const id = params.get("source")
    if (!id || !detail || !view || detail.beats.some(b => b.id === id)) return
    const legacy = view.legacy_plan?.parts?.flatMap(p => p.segments || []).filter(s => s.id === id) || []
    if (legacy.length === 1 && legacy[0].source_beat_ids?.length === 1 && detail.beats.some(b => b.id === legacy[0].source_beat_ids![0])) {
      const next = new URLSearchParams(params); next.set("source",legacy[0].source_beat_ids[0]); next.set("tab","shots"); setParams(next,{replace:true}); setInspector("material")
    }
  }, [detail, view, params, setParams])
  async function perform(action: () => Promise<unknown>, success?: string) {
    setBusy(true)
    try { await action(); if (success) message.success(success) }
    catch (err) { message.error(director2ErrorDetail(err, "操作未完成")) }
    finally { await load(); setBusy(false) }
  }
  function selectBeat(id: string) {
    const change = () => { const next = new URLSearchParams(params); next.set("source", id); next.set("tab", "shots"); setParams(next) }
    if (dirty) Modal.confirm({ title: "本镜提示词尚未保存", content: "切换后将放弃当前未保存修改。", okText: "放弃修改并切换", onOk: change })
    else change()
  }
  async function generate(ids?: string[]) {
    const result = await generateEpisodeVideo(csrfToken, projectId, episodeId!, { ...videoOptions, beat_ids: ids, expected_revision: revision, expected_reference_fingerprint: plan?.reference_fingerprint, workflow: plan?.workflow_id, aspect_ratio: plan?.aspect_ratio })
    message.info(`已按镜头组提交 ${result.submitted || 0} 个视频任务，跳过 ${result.skipped || 0} 组${result.blocked?.length ? `；${summarizeWorkshopBlocks(result.blocked)}` : ""}`)
  }
  function groupDuration(ids: string[]) {
    return ids.reduce((seconds, id) => seconds + Number(detail?.beats.find(item => item.id === id)?.video_duration || 0), 0)
  }
  const write = (data: Record<string, unknown>) => writeWorkshop(csrfToken, projectId, episodeId!, { expected_revision: revision, expected_reference_fingerprint: plan?.reference_fingerprint, ...data })
  const editDraft = (value: string) => { if (!dirty) editReferences.current = plan?.reference_fingerprint; setDraft(value) }
  const openGroup = (value: WorkshopGroup) => { groupReferences.current = plan?.reference_fingerprint; setGroupDraft(structuredClone(value)) }
  const promptWorkshop = (csrf: string, project: string, episode: string, data: Record<string, unknown>) => submitPromptWorkshop(csrf, project, episode, {...data, expected_reference_fingerprint: plan?.reference_fingerprint})
  const jobAction = (job: WorkshopJob, action: string, more: Record<string, unknown> = {}) => actWorkshop(csrfToken, projectId, episodeId!, job.id, { action, expected_revision: revision, expected_reference_fingerprint: plan?.reference_fingerprint, ...more })
  const assetRefs: PromptReferenceSlot[] = assets.flatMap(a => {
    const looks = (a.extra?.identities || []) as Array<{ id: string; name?: string; image_url?: string }>
    const images = looks.filter(l => l.image_url).map(l => ({ url: l.image_url!, look: l.id, label: l.name || l.id }))
    if (!images.length && getAssetDisplayAvatar(a)) images.push({ url: getAssetDisplayAvatar(a), look: "", label: "" })
    return images.map(item => ({ asset_id: a.id, name: `${a.name}${item.label ? ` · ${item.label}` : ""}`, image_url: item.url, look_id: item.look, kind: a.kind, index: 0, token: "" }))
  })
  const acceptedEpisodes = documents.flatMap(d => d.analysis?.script_development && Array.isArray(d.analysis.episodes) ? (d.analysis.episodes as Array<{episode_num: number}>).map(e => ({doc:d.id,number:e.episode_num})) : [])
  const linkedEpisode = (episode: Director2Episode) => { try { const data = JSON.parse(episode.data_json || "{}"); return acceptedEpisodes.some(e => e.doc === data.source_document_id && e.number === episode.episode_num) } catch { return false } }
  if (!episodeId) return <div className="d2-episode-workshop workshop-container"><div className="xiaji-workshop">
    <header className="xiaji-workshop-hero"><span className="xiaji-ingest-hero-icon"><Clapperboard size={20} /></span><div className="hero-text-col"><h1>剧集工坊</h1><p>从采纳剧本开始，依次规划镜头、准备素材和生成视频。</p></div><Space><Button icon={<RefreshCw size={14} />} onClick={() => void loadEpisodes()}>刷新</Button><Button type="primary" onClick={() => navigate(`/director/projects/${projectId}/content`)}>去内容库</Button></Space></header>
    <div className="xiaji-workshop-stats"><span>总集数 <strong>{episodes.length}</strong></span><span>内容库已采纳 <strong>{acceptedEpisodes.length}</strong></span><span>历史／未关联 <strong>{episodes.filter(e => !linkedEpisode(e)).length}</strong></span></div>
    {error && <Alert type="error" message={error} />}
    <div className="xiaji-episode-grid">{episodes.map(e => <div key={e.id} className="xiaji-episode-card" role="button" tabIndex={0} onKeyDown={event => { if (event.key === "Enter") navigate(`/director/projects/${projectId}/workshop/${e.id}?tab=shots`) }} onClick={() => navigate(`/director/projects/${projectId}/workshop/${e.id}?tab=shots`)}>
      <div className="card-head"><strong className="card-title">第 {e.episode_num} 集 · {e.title}</strong><Tag>{linkedEpisode(e) ? "已关联剧本" : "历史／未关联"}</Tag></div>
      <p className="card-summary">{e.script_text?.replace(/[#\n-]/g, " ").slice(0, 85) || "采纳剧本后开始本集制作"}</p><div className="card-footer"><em className="card-meta">{e.shots_count || 0} 个镜头</em><span className="card-actions">进入本集 →</span></div>
    </div>)}</div>{!episodes.length && <Empty description="先在内容库采纳剧本，工坊将自动建立分集" />}
  </div></div>
  if (!detail || !view) return <div className="unified-content">{error ? <Alert type="error" message={error} action={<Button onClick={() => void load()}>重试</Button>} /> : <Spin />}</div>
  const materials = beat && production ? materialsForUnit(production, beat.id) : []
  const take = materials.find(m => m.id === takeId) || materials.find(m => production?.adopted[beat?.id || ""] === m.id) || materials[0]
  const range = beat && take?.ranges?.[beat.id]
  const groupEditor = (groups: WorkshopGroup[], onChange: (next: WorkshopGroup[]) => void) => groups.map((g, i) => <Card key={g.id} size="small" title={`镜头组 ${i + 1}`}>
    <Space wrap>{g.beat_ids.map((id, n) => <Space key={id}><Tag>镜头 {(planningJob?.payload.candidate?.beats || detail.beats).findIndex(b => b.id === id) + 1}</Tag>{n < g.beat_ids.length - 1 && <Button size="small" onClick={() => onChange(splitWorkshopGroup(groups, g.id, n + 1))}>在此拆组</Button>}</Space>)}{i < groups.length - 1 && <Button size="small" onClick={() => { const next = mergeWorkshopGroups(groups, i); if (next === groups) message.warning("两组公共设定或参考编号不同，请先统一组设置"); else onChange(next) }}>合并下一组</Button>}</Space>
  </Card>)
  return <div className="d2-episode-workshop workshop-container in-episode-detail unified-workshop">
    <div className="xiaji-episode-head"><div className="xiaji-episode-head-main"><div className="xiaji-episode-head-title"><Button icon={<ArrowLeft size={15} />} onClick={() => navigate(`/director/projects/${projectId}/workshop`)}>返回分集</Button><h2>第 {detail.number} 集 · {detail.title}</h2><Tag>{detail.beats.length} 镜 · {plan?.groups.length || 0} 组</Tag></div></div><Space><Button onClick={() => setScript(true)}>查看采纳剧本</Button><Button onClick={() => void load()}>刷新</Button></Space></div>
    <Typography.Text type="secondary">来源版本 {view.source.revision} · {plan?.target_duration_seconds ? `目标 ${plan.target_duration_seconds} 秒 · ` : ""}{plan?.aspect_ratio || aspect} · {plan ? `已确认规划 ${plan.planning_revision}` : "待确认镜头规划"}</Typography.Text>
    {error && <Alert type="error" message={error} />}
    {view.source_changed && <Alert type="warning" showIcon message="内容库有新采纳稿，请调整镜头规划；现有视频和手工稿已保留" />}
    {view.source.unlinked && <Alert type="warning" message="本集未关联当前文档分集，历史剧本和素材保留。规划将使用本集现存剧本。" />}
    <Tabs className="episode-tabs" activeKey={activeTab} onChange={key => { const next = new URLSearchParams(params); next.set("tab", key); setParams(next) }} items={[
      { key: "shots", label: "镜头", children: <>
        <Space wrap className="unified-actions"><Button type="primary" onClick={() => { setWorkflow(plan?.workflow_id || workflow); setAspect(plan?.aspect_ratio || aspect); setMaximum(plan?.max_shots_per_group || 3); setTargetDuration(plan?.target_duration_seconds || null); setReuse(Boolean(detail.beats.length)); setPlanning(true) }}>{plan ? "调整规划" : "规划镜头"}</Button>
          <Button disabled={!plan || busy || view.source_changed} onClick={() => void perform(() => promptWorkshop(csrfToken, projectId, episodeId, { expected_revision: revision }), "正在生成本集 H3 候选稿")}>批量生成本集提示词</Button><Button type="primary" disabled={!group || busy || view.source_changed} onClick={() => void perform(() => generate(group!.beat_ids))}>批量生成当前镜头组视频{currentGroupNumber ? `（第 ${currentGroupNumber} 组）` : ""}</Button><Button disabled={!plan || busy || view.source_changed} onClick={() => Modal.confirm({ title: `按 ${plan!.groups.length} 个镜头组批量生成本集视频？`, content: "每个镜头组分别提交一个视频任务，不会把整集镜头合成一条超长视频。已采用的组会跳过。", okText: "按组提交", cancelText: "取消", onOk: () => perform(() => generate()) })}>按组批量生成本集</Button>
        <Director2VideoSettingsPopover triggerLabel="更多视频设置" workflowId={plan?.workflow_id || workflow} workflows={modes} fields={visibleVideoOptionFields(mode).filter(f => !["duration", "video_duration"].includes(f.name))} values={{...Object.fromEntries(Object.entries(videoOptions).map(([key, value]) => [key, String(value)])),aspect_ratio:plan?.aspect_ratio || aspect}} onWorkflowChange={id => { setWorkflow(id); setMaximum(Math.min(maximum,modes.find(m => m.id === id)?.max_segments || 1)); setReuse(Boolean(detail.beats.length)); setPlanning(true) }} onChange={(name, value) => { if(name === "aspect_ratio") {setAspect(value); setWorkflow(plan?.workflow_id || workflow); setReuse(Boolean(detail.beats.length)); setPlanning(true); return} const next = {...videoOptions,[name]:optionSchemaFromMode(mode)[name]?.type === "boolean" ? value === "true" : optionSchemaFromMode(mode)[name]?.type === "integer" || optionSchemaFromMode(mode)[name]?.type === "number" ? Number(value) : value}; setVideoOptions(next); saveVideoSettings(projectId,Object.fromEntries(Object.entries(next).map(([key,v]) => [key,String(v)]))) }} /></Space>
        <Collapse items={[{key:"job-history",label:`任务进度与失败记录（${view.jobs.filter(j => ["running", "queued", "failed"].includes(j.status) || Object.keys(j.payload.failures || {}).length).length}）`,children:<Space direction="vertical" style={{width:"100%"}}>{view.jobs.filter(j => ["running", "queued", "failed"].includes(j.status) || Object.keys(j.payload.failures || {}).length).map(j => <Alert key={j.id} type={j.status === "failed" ? "error" : "info"} showIcon message={j.error || j.payload.message} action={<Space>{["running", "queued"].includes(j.status) ? <Button disabled={busy} onClick={() => void perform(() => jobAction(j, "cancel"))}>取消</Button> : <Button disabled={busy} onClick={() => void perform(() => jobAction(j, "retry"))}>重试失败部分</Button>}</Space>} />)}</Space>}]} />
        {pendingPromptIds.size > 0 && <Alert type="info" showIcon message={`已生成 ${pendingPromptIds.size} 镜 H3 候选稿，待检查采纳`} description="生成完成后需采纳候选稿，才会写入本镜提示词并用于生成视频。" action={<Button onClick={() => { selectBeat([...pendingPromptIds][0]); setInspector("material") }}>查看待采纳提示词</Button>} />}
        {missingReferenceGroups.length > 0 && <Alert type="warning" showIcon message={`${missingReferenceGroups.length} 组参考素材尚未就绪`} description={<><Typography.Paragraph>人物／道具设定图自动关联，补图后会自动更新；提示词需按最新参考重新生成并采纳。</Typography.Paragraph>{missingReferenceGroups.map(g => <Typography.Paragraph key={g.id}>第 {(plan?.groups.indexOf(g) || 0) + 1} 组：{g.reference_issues?.join("；") || "请补齐视频参考图"}</Typography.Paragraph>)}</>} action={<Space><Button onClick={() => navigate(`/director/projects/${projectId}/assets`)}>去资产库补图</Button><Button onClick={() => openGroup(missingReferenceGroups[0])}>检查组参考</Button></Space>} />}
        {runningJobs.map(j => <Typography.Paragraph key={j.id} type="secondary">{j.payload.message}</Typography.Paragraph>)}<div className="unified-shot-layout xiaji-shots-split"><aside className="unified-shot-list xiaji-shots-grid-pane">{(plan?.groups || [{ id: "legacy", beat_ids: detail.beats.map(b => b.id), common_prompt: "", reference_slots: [] }]).map((g, i) => <section key={g.id}>
          <Space wrap><Typography.Text strong>{plan ? `镜头组 ${i + 1}` : "历史镜头"}</Typography.Text>{plan && <Typography.Text type="secondary">{g.beat_ids.length} 镜 · 约 {groupDuration(g.beat_ids)} 秒</Typography.Text>}{plan && <Button size="small" onClick={() => openGroup(g)}>组设置</Button>}</Space>
          <div className="xiaji-shot-tiles">{g.beat_ids.map(id => { const b = detail.beats.find(item => item.id === id); const thumbnail = b?.sketch_url || b?.triptych_url; return b && <div key={id} className={`xiaji-shot-tile${beat?.id === id ? " is-selected" : ""}`}><div className="xiaji-shot-tile-head"><strong>镜头 {b.sequence}</strong><span>{b.video_duration}s</span></div><button className="xiaji-shot-tile-body" onClick={() => selectBeat(id)}><div className="xiaji-shot-tile-media">{thumbnail ? <img src={thumbnail} alt={b.heading} /> : <ImageIcon size={24} />}</div><div className="tile-caption">{b.heading || b.action}</div></button><Tag>{production?.adopted[id] ? "已采用视频" : pendingPromptIds.has(id) ? "候选待采纳" : plan?.shot_prompts[id] ? b.h3_prompt_reference_state === "current" ? "提示词就绪" : "提示词待检查" : "待写词"}</Tag></div> })}</div>
          {plan && <Space wrap><Button size="small" disabled={busy || view.source_changed} onClick={() => void perform(() => promptWorkshop(csrfToken, projectId, episodeId, { expected_revision: revision, beat_ids: g.beat_ids }), "正在生成本组候选")}>本组写词</Button><Button size="small" disabled={busy || view.source_changed} onClick={() => void perform(() => generate(g.beat_ids))}>批量生成本组视频</Button></Space>}
        </section>)}</aside><section className="unified-shot-detail xiaji-shots-detail" aria-label="镜头检视器">{beat ? <Tabs className="xiaji-inspector-tabs" activeKey={inspector} onChange={setInspector} items={[
          { key: "text", label: "镜头内容", children: <Space direction="vertical" style={{ width: "100%" }}><Typography.Title level={4}>镜头 {beat.sequence} · {beat.heading}</Typography.Title><Typography.Paragraph>{beat.action}</Typography.Paragraph><Typography.Paragraph>对白：{beat.dialogue || "无"}</Typography.Paragraph><Typography.Text type="secondary">剧情和对白来自采纳剧本；改故事请回内容库。</Typography.Text><Form layout="vertical" key={`${beat.id}-${plan?.planning_revision}`} onFinish={values => void perform(() => write({ beat_id: beat.id, shot_updates: values }), "拍摄设置已保存")} initialValues={{ camera: beat.camera, video_duration: Number(beat.video_duration) }}><Form.Item name="camera" label="景别与运镜"><Input.TextArea rows={3} disabled={!plan} /></Form.Item><Form.Item name="video_duration" label="镜头时长（秒）"><InputNumber min={1} disabled={!plan} /></Form.Item><Button htmlType="submit" disabled={!plan || busy}>保存拍摄设置</Button></Form></Space> },
          { key: "material", label: "素材组", children: <>
            {!plan && <Alert type="info" message="先确认镜头规划，可选择保留当前镜头。历史稿件在下方完整保留。" />}
            <div className="unified-material h3-material-content"><div className="h3-material-left">
              {(["character", "scene", "prop"] as const).map(kind => <div className="h3-ref-block" key={kind}><div className="h3-ref-block-head"><span className="h3-ref-label">{kind === "character" ? "本镜人物" : kind === "scene" ? "本镜场景" : "本镜道具"}</span><Button type="text" size="small" disabled={!plan || busy} onClick={() => setAssetPicker(kind)}>选择</Button></div>
                <div className="h3-ref-grid">{assets.filter(a => a.kind === kind && (kind === "character" ? beat.character_ids?.includes(a.id) : kind === "scene" ? beat.scene_id === a.id : beat.prop_ids?.includes(a.id))).map(a => {
                  const look = ((a.extra?.identities || []) as Array<{id:string;name?:string;image_url?:string}>).find(l => l.id === beat.character_look_ids?.[a.id]); const url = look?.image_url || getAssetDisplayAvatar(a);
                  return <div className="h3-ref-img-cell" key={a.id}>{url ? <Image src={url} alt={a.name} /> : <div className="workshop-photo-empty"><ImageIcon size={22} /></div>}<div className="h3-ref-info"><span className="h3-ref-name">{a.name}</span>{look?.name && <span>{look.name}</span>}</div></div>
                })}</div>
              </div>)}
              <div className="h3-ref-block"><div className="h3-ref-block-head"><span className="h3-ref-label">最终视频参考</span>{group && <Button type="text" size="small" onClick={() => openGroup(group)}>组设置</Button>}</div><div className="h3-ref-grid">{group?.reference_slots.map(slot => <div className="h3-ref-img-cell" key={slot.token}><Image src={slot.image_url || undefined} alt={slot.name} /><div className="h3-ref-info"><span className="h3-ref-seq">{slot.token}</span><span className="h3-ref-name">{slot.name}</span></div></div>)}</div><Typography.Text type="secondary">同组共享编号，写稿参考不会自动提交。</Typography.Text></div>
              <div className="h3-ref-block"><div className="h3-ref-block-head"><span className="h3-ref-label">本镜写稿参考</span></div><div className="h3-ref-grid">{[...assetRefs.filter(s => s.asset_id && [...(beat.character_ids || []), beat.scene_id, ...(beat.prop_ids || [])].includes(s.asset_id)), ...[{image_url:beat.sketch_url,name:"本镜草图"},{image_url:beat.triptych_url,name:"本镜三联图"}].filter(s => s.image_url)].map((slot, i) => <div className="h3-ref-img-cell" key={`${slot.image_url}-${i}`}><Image src={slot.image_url || undefined} alt={slot.name} /><Checkbox disabled={!plan || busy} checked={beat.workshop_writing_refs?.includes(slot.image_url!)} onChange={event => void perform(() => write({beat_id:beat.id,writing_reference_urls:event.target.checked ? [...(beat.workshop_writing_refs || []), slot.image_url] : (beat.workshop_writing_refs || []).filter(url => url !== slot.image_url)}))}>{slot.name}</Checkbox></div>)}</div></div>
              <Collapse items={[{ key: "prepare", label: "参考准备（可选）", children: <Space direction="vertical"><Button disabled={busy || !plan} onClick={() => void perform(() => generateBeatSketch(csrfToken, projectId, episodeId, beat.id), "草图任务已提交")}>生成本镜草图</Button>{beat.sketch_url && <Image width={140} src={beat.sketch_url} />}<Button disabled={busy || !plan} onClick={() => void perform(() => generateBeatTriptych(csrfToken, projectId, episodeId, beat.id), "三联图任务已提交")}>生成三联关键帧</Button>{beat.triptych_url && <Image width={180} src={beat.triptych_url} />}<Collapse items={[{ key: "action", label: "动作预演", children: <ActionPrevisPane projectId={projectId} episodeId={episodeId} beatId={beat.id} csrfToken={csrfToken} /> }]} /></Space> }]} />
</div><div className="h3-prompt-panel"><div className="h3-prompt-head"><Typography.Title level={5}>本镜 H3 提示词</Typography.Title><Space wrap><Button type="primary" disabled={busy || !plan || view.source_changed} onClick={() => void perform(() => promptWorkshop(csrfToken, projectId, episodeId, { expected_revision: revision, beat_ids: groupWriting ? group?.beat_ids : [beat.id] }), groupWriting ? "正在统筹生成整组候选稿" : "正在生成本镜候选稿")}>{groupWriting ? `生成本组提示词（${group?.beat_ids.length || 0} 镜）` : saved ? "重新生成候选" : "生成 H3 提示词"}</Button>{groupWriting && <Button disabled={busy || dirty || view.source_changed || !group?.beat_ids.every(id => plan?.shot_prompts[id])} onClick={() => { setRevisionTarget(beat.id); setRevisionNote("") }}>返修本镜</Button>}<Button disabled={busy || !plan || !dirty} onClick={() => void perform(() => write({ beat_id: beat.id, h3_prompt: draft, expected_reference_fingerprint: editReferences.current }), "已保存本镜提示词")}>保存修改</Button><Button disabled={!saved} onClick={() => void navigator.clipboard.writeText(`${group?.common_prompt ? `主体定义：${group.common_prompt}\n\n` : ""}${saved}`).then(() => message.success("已复制有效提示词"))}>复制完整提示词</Button></Space>
              </div>{candidates.map(j => {
                const wholeGroup = groupWriting && j.payload.prompt_scope === "group"
                const ids = wholeGroup ? group?.beat_ids || [] : [beat.id]
                const applied = plan?.applied_candidates?.[j.id] || j.payload.applied_ids || []
                const legacy = groupWriting && !j.payload.prompt_scope
                const adopted = ids.length > 0 && ids.every(id => applied.includes(id))
                return <Collapse key={`${j.id}-${beat.id}-${adopted}`} defaultActiveKey={adopted ? [] : [j.id]} items={[{ key: j.id, label: `${adopted ? "已采纳" : "待采纳"} · ${wholeGroup ? `整组候选（${ids.length} 镜）` : j.payload.prompt_scope === "shot_revision" ? "本镜返修候选" : "本镜候选"}`, children: <>
                  {legacy && <Alert type="info" message="旧逐镜候选仅供参考，请重新生成整组候选" />}
                  <Button disabled={busy || dirty || j.status !== "completed" || legacy || !ids.length || ids.some(id => !j.payload.candidates[id] || applied.includes(id))} onClick={() => void perform(() => jobAction(j, "apply", { beat_ids: ids }), wholeGroup ? "已采用整组候选" : "已采用本镜候选")}>{ids.every(id => applied.includes(id)) ? "已采用候选" : wholeGroup ? "采用整组候选" : "采用本镜候选"}</Button>
                  {ids.map(id => <Card key={id} size="small" title={`镜头 ${detail.beats.find(b => b.id === id)?.sequence || id}`}><Typography.Paragraph style={{ whiteSpace: "pre-wrap", maxHeight: 240, overflowY: "auto" }}>{j.payload.candidates[id]?.h3_prompt || "本组候选不完整，请重新生成"}</Typography.Paragraph></Card>)}
                </> }]} />
              })}
              <Input.TextArea className="h3-prompt-editor" aria-label="本镜 H3 提示词" placeholder={pendingPromptIds.has(beat.id) ? "本镜候选稿已生成，请在上方检查并采纳。" : "暂无已采纳提示词，请先生成并采纳候选稿。"} value={draft} onChange={e => editDraft(e.target.value)} rows={16} disabled={!plan} style={{ marginTop: 12 }} />
              {dirty && <Typography.Paragraph type="warning">有未保存修改，复制和提交仍使用已保存版本。</Typography.Paragraph>}{beat.h3_prompt_reference_state === "stale" && <Alert type="warning" message="镜头或参考设定已变化，请检查正文后保存或生成新候选" />}
              <Button disabled={busy || !saved || dirty || view.source_changed || beat.h3_prompt_reference_state !== "current"} style={{ marginTop: 12 }} onClick={() => void perform(() => generate([beat.id]))}>生成本镜视频</Button>
            </div></div>
            {view.legacy_prompts[beat.id]?.length ? <Collapse items={[{ key: "history", label: `历史稿件（${view.legacy_prompts[beat.id].length}）`, children: view.legacy_prompts[beat.id].map((p, i) => <Card key={i} title={p.source}><Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{p.common_prompt}{"\n"}{p.h3_prompt}</Typography.Paragraph><Button disabled={!plan} onClick={() => editDraft(p.h3_prompt)}>放入编辑器检查</Button></Card>) }]} /> : null}
            {Boolean(plan?.shot_prompts[beat.id]?.history?.length) && <Collapse items={[{key:"prompt-versions",label:"本镜提示词历史版本",children:plan?.shot_prompts[beat.id]?.history?.map((record,i) => <Card key={i} size="small" title={`历史稿 ${i+1}`}><Typography.Paragraph style={{whiteSpace:"pre-wrap"}}>{record.h3_prompt}</Typography.Paragraph><Button disabled={dirty} onClick={() => editDraft(record.h3_prompt)}>放入编辑器检查</Button></Card>)}]} />}
          </> },
          { key: "video", label: "视频", children: take && production ? <Space direction="vertical" style={{ width: "100%" }}><Select aria-label="视频版本" value={take.id} style={{ minWidth: 260 }} onChange={setTakeId} options={materials.map((m, i) => ({ value: m.id, label: `${production.adopted[beat.id] === m.id ? "已采用" : "候选"} · 版本 ${materials.length - i}` }))} /><video className="production-video" key={`${take.url}-${beat.id}`} src={take.url} controls onLoadedMetadata={e => { if (range) e.currentTarget.currentTime = range.start }} onTimeUpdate={e => { if (range && e.currentTarget.currentTime > range.end) e.currentTarget.pause() }} /><Typography.Text>{range ? `本镜区间 ${range.start.toFixed(2)}–${range.end.toFixed(2)} 秒` : "历史素材尚无可靠区间"}</Typography.Text><Space><Button type="primary" disabled={busy || production.adopted[beat.id] === take.id} onClick={() => void perform(() => updateEpisodeProduction(csrfToken, projectId, episodeId, "adopt", { expected_revision: production.revision, mode: production.active_mode, material_id: take.id }), "已采用视频")}>采用此版（覆盖 {take.unit_ids.length} 镜）</Button><Button disabled={busy || !take.job_id} onClick={() => void perform(() => upscaleProjectVideoJob(csrfToken, projectId, take.job_id, { scale: 2 }), "已提交超分")}>2× 超分</Button></Space></Space> : <Empty description="生成视频后，在这里预览和采用 Take" /> },
        ]} /> : <Empty description="采纳剧本后，点击规划镜头开始制作" />}</section></div>
      </> },
      { key: "dubbing", label: "声音", children: production && <ProductionSound state={production} csrfToken={csrfToken} projectId={projectId} episodeId={episodeId} onRefresh={load} /> },
      { key: "compose", label: "合成", children: production && <ProductionFilm state={production} csrfToken={csrfToken} projectId={projectId} episodeId={episodeId} onRefresh={load} onJob={() => void load()} jobActive={false} /> },
    ]} />
    <Modal title={assetPicker === "character" ? "选择本镜人物与造型" : assetPicker === "scene" ? "选择本镜场景" : "选择本镜道具"} open={Boolean(assetPicker)} onCancel={() => setAssetPicker(null)} footer={<Button onClick={() => setAssetPicker(null)}>完成</Button>} width={820}>
      <div className="workshop-asset-gallery">{assets.filter(a => a.kind === assetPicker).map(a => {
        const checked = assetPicker === "character" ? beat?.character_ids?.includes(a.id) : assetPicker === "scene" ? beat?.scene_id === a.id : beat?.prop_ids?.includes(a.id);
        const selectedIds = assetPicker === "character" ? beat?.character_ids || [] : beat?.prop_ids || [];
        return <div className={`workshop-asset-photo${checked ? " is-selected" : ""}`} key={a.id}>
          {getAssetDisplayAvatar(a) ? <Image src={getAssetDisplayAvatar(a)} alt={a.name} /> : <div className="workshop-photo-empty"><ImageIcon size={28} /></div>}
          <Checkbox checked={Boolean(checked)} disabled={busy} onChange={event => void perform(() => write({beat_id:beat!.id,shot_updates:assetPicker === "scene" ? {scene_id:event.target.checked ? a.id : ""} : {[assetPicker === "character" ? "character_ids" : "prop_ids"]:event.target.checked ? [...selectedIds,a.id] : selectedIds.filter(id => id !== a.id)}}))}>{a.name}</Checkbox>
          {checked && assetPicker === "character" && <div className="h3-ref-grid">{((a.extra?.identities || []) as Array<{id:string;name?:string;image_url?:string}>).map(look => <div className="h3-ref-img-cell" key={look.id}>{look.image_url && <Image src={look.image_url} alt={look.name} />}<Checkbox disabled={busy} checked={beat?.character_look_ids?.[a.id] === look.id} onChange={event => void perform(() => write({beat_id:beat!.id,shot_updates:{character_look_ids:{...beat?.character_look_ids,[a.id]:event.target.checked ? look.id : ""}}}))}>{look.name || "默认造型"}</Checkbox></div>)}</div>}
        </div>
      })}</div>{!assets.some(a => a.kind === assetPicker) && <Empty description="资产库暂无此类素材"><Button onClick={() => navigate(`/director/projects/${projectId}/assets`)}>去资产库</Button></Empty>}
    </Modal>
    <Drawer title="已采纳剧本" open={script} onClose={() => setScript(false)} width={720}><Button onClick={() => navigate(`/director/projects/${projectId}/content${view.source.document_id ? `?doc=${view.source.document_id}` : ""}`)}>到内容库修改剧本</Button><Typography.Paragraph style={{ whiteSpace: "pre-wrap", marginTop: 20 }}>{view.source.text}</Typography.Paragraph><Collapse items={[{key:"history",label:`历史规划与素材（${view.history?.length || 0} 次）`,children:<Space direction="vertical" style={{width:"100%"}}>{view.history?.map((h,i) => <Collapse key={i} items={[{key:String(i),label:`历史版本 ${i+1} · ${h.beats.length} 镜`,children:<pre style={{whiteSpace:"pre-wrap"}}>{JSON.stringify(h,null,2)}</pre>}]} />)}{view.historical_media?.map(m => <a key={m.id} href={m.url} target="_blank" rel="noreferrer">{m.title || "历史视频"} · {m.id}</a>)}</Space>}]} /></Drawer>
    <Modal title="返修本镜提示词" open={Boolean(revisionTarget)} onCancel={() => setRevisionTarget(null)} okText="生成本镜返修候选" confirmLoading={busy} okButtonProps={{ disabled: !revisionNote.trim() || dirty || view.source_changed }} onOk={() => void perform(async () => {
      await promptWorkshop(csrfToken, projectId, episodeId, { expected_revision: revision, beat_ids: [revisionTarget], prompt_scope: "shot_revision", revision_note: revisionNote.trim() }); setRevisionTarget(null)
    }, "正在结合整组上下文返修本镜")}>
      <Alert type="info" message="只返修当前镜头，其他镜头保持不变" description="会参考整组已采纳提示词保持前后衔接。修改镜头数量、时长或组公共设定，请回到整组调整。" />
      <Form layout="vertical"><Form.Item label="本镜修改意见"><Input.TextArea value={revisionNote} onChange={e => setRevisionNote(e.target.value)} maxLength={4000} showCount rows={4} /></Form.Item></Form>
    </Modal>
    <Modal title="规划镜头与分组" open={planning} onCancel={() => setPlanning(false)} footer={null} width={900}>
      <Alert type="info" message="先确认镜头数量、剧情分配和分组；这里不会生成视频提示词。" />
      <Form layout="vertical"><Form.Item label="规划方式"><Select value={reuse} onChange={setReuse} options={[{ value: false, label: "从采纳剧本重新规划（先预览）" }, { value: true, label: "保留当前镜头，只建立或调整分组" }]} /></Form.Item><Form.Item label="视频工作流"><Select value={workflow} onChange={id => { setWorkflow(id); setMaximum(Math.min(maximum, modes.find(m => m.id === id)?.max_segments || 1)) }} options={modes.map(m => ({ value: m.id, label: m.name }))} /></Form.Item><Space wrap><Form.Item label="画幅"><Select style={{ width: 140 }} value={aspect} onChange={setAspect} options={(optionSchemaFromMode(planningMode).aspect_ratio?.enum || ["16:9", "9:16"]).map(v => ({ value: String(v), label: String(v) }))} /></Form.Item><Form.Item label="目标时长（秒，留空自动）"><InputNumber min={1} max={7200} value={targetDuration} onChange={setTargetDuration} disabled={reuse} /></Form.Item><Form.Item label="目标镜头数（留空自动）"><InputNumber min={1} value={target} onChange={setTarget} disabled={reuse} /></Form.Item><Form.Item label="每组最多镜头数"><InputNumber min={1} max={planningMode?.max_segments || 1} value={maximum} onChange={v => setMaximum(v || 1)} /></Form.Item></Space></Form>
      <Button type="primary" loading={busy} onClick={() => void perform(async () => { const job = await planWorkshop(csrfToken, projectId, episodeId, { expected_revision: revision, workflow_id: workflow, aspect_ratio: aspect, max_shots_per_group: maximum, target_shot_count: target, target_duration_seconds: targetDuration, reuse_existing: reuse }); setPreviewJob(job.job_id); setCandidateGroups(null); setCandidateEdits({}) }, "正在准备镜头候选")}>生成规划候选</Button>
      {planningJob?.payload.candidate && <Space direction="vertical" style={{ width: "100%", marginTop: 16 }}><Alert message={planningJob.payload.count_note} description={`保留 ${planningJob.payload.candidate.beats.filter(b => detail.beats.some(old => old.id === b.id)).length} 镜；新增 ${planningJob.payload.candidate.beats.filter(b => !detail.beats.some(old => old.id === b.id)).length} 镜；删除 ${detail.beats.filter(b => !planningJob.payload.candidate!.beats.some(next => next.id === b.id)).length} 镜。历史结果保留。`} type="info" /><Table size="small" pagination={false} rowKey="id" dataSource={planningJob.payload.candidate.beats} columns={[{ title: "镜号", dataIndex: "sequence" }, { title: "镜头", dataIndex: "heading" }, { title: "动作", dataIndex: "action" }, { title: "对白", dataIndex: "dialogue" }, { title: "拍摄意图", render: (_, b) => <Input.TextArea aria-label={`候选镜头 ${b.sequence} 运镜`} value={String(candidateEdits[b.id]?.camera ?? b.camera ?? "")} onChange={e => setCandidateEdits({...candidateEdits,[b.id]:{...candidateEdits[b.id],camera:e.target.value}})} /> }, { title: "时长", render: (_, b) => <InputNumber aria-label={`候选镜头 ${b.sequence} 时长`} min={1} value={Number(candidateEdits[b.id]?.video_duration ?? b.video_duration)} onChange={v => setCandidateEdits({...candidateEdits,[b.id]:{...candidateEdits[b.id],video_duration:v}})} /> }]} />{groupEditor(candidateGroups || planningJob.payload.candidate.plan.groups, setCandidateGroups)}<Button type="primary" disabled={busy} onClick={() => void perform(async () => { await jobAction(planningJob, "apply", { groups: candidateGroups || planningJob.payload.candidate!.plan.groups, shot_updates: candidateEdits }); setPlanning(false) }, "已确认镜头规划")}>确认采用本次规划</Button></Space>}
      {plan && <Collapse style={{ marginTop: 16 }} items={[{ key: "groups", label: "仅调整当前分组（不调用 AI）", children: <>{groupEditor(plan.groups, groups => void perform(() => write({ groups }), "已调整分组"))}</> }]} />}
    </Modal>
    <Modal title="组公共设定与参考图" open={Boolean(groupDraft)} onCancel={() => setGroupDraft(null)} confirmLoading={busy} onOk={() => groupDraft && void perform(async () => { await write({ expected_reference_fingerprint: groupReferences.current, groups: plan!.groups.map(g => g.id === groupDraft.id ? groupDraft : g) }); setGroupDraft(null) }, "组设定已保存，相关提示词将重新检查")} width={720}>
      {groupDraft && <Alert type={groupDraft.reference_issues?.length ? "warning" : "info"} showIcon message={groupDraft.reference_policy === "auto" ? "参考图自动关联人物／道具及所选造型，资产补图后自动更新" : "当前参考图为手动选择，顺序保留；资产换图会自动更新"} description={groupDraft.reference_issues?.join("；")} action={groupDraft.reference_policy !== "auto" && <Button disabled={busy} onClick={() => void perform(async () => { await write({auto_reference_group_ids:[groupDraft.id]}); setGroupDraft(null) }, "已恢复自动关联参考图")}>恢复自动关联</Button>} />}
      {groupDraft && <Form layout="vertical"><Alert type="info" message={`本次修改影响同组 ${groupDraft.beat_ids.length} 个镜头`} /><Form.Item label="公共主体与声音设定"><Input.TextArea rows={5} value={groupDraft.common_prompt} onChange={e => setGroupDraft({ ...groupDraft, common_prompt: e.target.value })} /></Form.Item><Form.Item label="时间码模式"><Select value={groupDraft.timecode_mode || "per_shot"} onChange={v => setGroupDraft({ ...groupDraft, timecode_mode: v })} options={[{ value: "per_shot", label: "每镜从零（默认）" }, { value: "cumulative", label: "组内累计时间码" }]} /></Form.Item><Form.Item label={`最终视频参考（最多 ${mode?.max_references || 0} 张，按选择顺序编号）`}><Select mode="multiple" value={groupDraft.reference_slots.map(s => s.image_url)} maxCount={mode?.max_references || 0} options={[...assetRefs, ...groupDraft.reference_slots.filter(s => !assetRefs.some(a => a.image_url === s.image_url))].map(s => ({ value: s.image_url, label: s.name }))} onChange={urls => setGroupDraft({ ...groupDraft, reference_slots: urls.map((url, i) => ({ ...(assetRefs.find(s => s.image_url === url) || groupDraft.reference_slots.find(s => s.image_url === url))!, index: i + 1, token: `<Picture ${i + 1}>` })) })} /></Form.Item><Button onClick={() => navigate(`/director/projects/${projectId}/assets`)}>到资产库准备图片与造型</Button></Form>}
    </Modal>
  </div>
})
export default UnifiedWorkshopPane
