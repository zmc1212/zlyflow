import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState, startTransition } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { Alert, Button, Card, Checkbox, Collapse, Drawer, Dropdown, Empty, Form, Image, Input, InputNumber, Modal, Select, Space, Spin, Switch, Table, Tabs, Tag, Tooltip, Typography, message } from "antd"
import { getEpisodeDetail, listDocuments, type Director2Document, listEpisodes, listAssets, listVideoWorkflowModes, getEpisodeProduction, generateEpisodeVideo, generateBeatSketch, generateBeatTriptych, updateEpisodeProduction, upscaleProjectVideoJob, director2ErrorDetail, type Director2Episode, type Director2EpisodeDetail, type Director2Asset, type PromptReferenceSlot } from "../api"
import { readWorkshop, readWorkshopJobs, writeWorkshop, planWorkshop, promptWorkshop as submitPromptWorkshop, actWorkshop, splitWorkshopGroup, mergeWorkshopGroups, type WorkshopView, type WorkshopGroup, type WorkshopJob } from "../workshop-api"
import { summarizeWorkshopBlocks } from "../workshop-references"
import { DIRECTOR2_DEFAULT_VIDEO_WORKFLOW, loadSavedVideoSettings, saveVideoSettings, optionSchemaFromMode, visibleVideoOptionFields, type Director2WorkflowMode } from "../director2-video-settings"
import { type ProductionState, materialsForUnit } from "../production"
import { H3ConfirmationPanel, H3_CONFIRM_MODE } from "../../components/H3ConfirmationPanel"
import { ProductionSound, ProductionFilm } from "./ProductionPanes"
import { getAssetDisplayAvatar } from "./assets/shared"
import ActionPrevisPane from "./ActionPrevisPane"
import WorkshopMaterialsPanel from "./WorkshopMaterialsPanel"
import { ArrowLeft, ChevronLeft, ChevronRight, ChevronDown, Clapperboard, ImageIcon, RefreshCw, Search, Maximize2, Minimize2 } from "lucide-react"
import Director2VideoSettingsPopover from "./Director2VideoSettingsPopover"
import WorkshopPromptCandidates, { workshopPendingCandidateIds, workshopCanRegenerate } from "./WorkshopPromptCandidates"
import { workshopNextAction, workshopVideoBlockReason } from "../workshop-ui-state"
import "./episode-workshop.css"
import "./unified-workshop.css"

type Props = { csrfToken: string; projectId: string; episodeId?: string | null; onDetailModeChange?: (value: boolean) => void; projectExtra?: unknown; projectSettings?: unknown }
const UnifiedWorkshopPane = forwardRef<{ fetchEpisodes: () => Promise<void> | void }, Props>(function UnifiedWorkshopPane({ csrfToken, projectId, episodeId, onDetailModeChange }, ref) {
  const navigate = useNavigate()
  const [modal, modalContextHolder] = Modal.useModal()
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
  const [authorSettingsOpen, setAuthorSettingsOpen] = useState(false)
  const [taskDrawerOpen, setTaskDrawerOpen] = useState(false)
  const [referenceIssuesOpen, setReferenceIssuesOpen] = useState(false)
  const [candidateDrawerOpen, setCandidateDrawerOpen] = useState(false)
  const [shotSearch, setShotSearch] = useState("")
  const [focusEditor, setFocusEditor] = useState(false)
  const [workflow, setWorkflow] = useState(DIRECTOR2_DEFAULT_VIDEO_WORKFLOW)
  const [aspect, setAspect] = useState("16:9")
  const [maximum, setMaximum] = useState(3)
  const [target, setTarget] = useState<number | null>(null)
  const [targetDuration, setTargetDuration] = useState<number | null>(null)
  const [reuse, setReuse] = useState(false)
  const [inspector, setInspector] = useState("material")
  const [draft, setDraft] = useState("")
  const [previsDirty, setPrevisDirty] = useState(false)
  const [revisionTarget, setRevisionTarget] = useState<string | null>(null)
  const [revisionNote, setRevisionNote] = useState("")
  const [authorChoice, setAuthorChoice] = useState<{ profile_id?: string; model?: string; reasoning_effort?: string }>({})
  const [reviewEnabled, setReviewEnabled] = useState(false)
  const [reviewAuthor, setReviewAuthor] = useState<{ profile_id?: string; model?: string; reasoning_effort?: string }>({})
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
  const chosenAuthor = { ...view?.writing_author, ...authorChoice }
  const chosenReviewer = { ...view?.writing_author, ...reviewAuthor }
  const beat = detail?.beats.find(b => b.id === params.get("source")) || detail?.beats[0]
  const group = plan?.groups.find(g => beat && g.beat_ids.includes(beat.id))
  const currentGroupNumber = plan && group ? plan.groups.indexOf(group) + 1 : 0
  const activeTab = ["shots", "dubbing", "compose"].includes(params.get("tab") || "") ? params.get("tab")! : "shots"
  const mode = modes.find(m => m.id === (plan?.workflow_id || workflow))
  const groupWriting = mode?.prompt_profile === "director_segments"
  const saved = beat ? plan?.shot_prompts?.[beat.id]?.h3_prompt || "" : ""
  const dirty = draft !== saved
  const revision = plan?.revision ?? view?.legacy_plan?.revision ?? 0
  const planningMode = modes.find(m => m.id === workflow)
  const missingReferenceGroups = plan?.groups.filter(g => g.reference_issues?.length || g.reference_slots.length < (mode?.min_references || 0)) || []
  const planningJob = view?.jobs.find(j => j.id === previewJob) || view?.jobs.find(j => j.kind === "workshop_planning" && j.status === "completed")
  const runningJobs = view?.jobs.filter(j => ["queued", "running"].includes(j.status)) || []
  const trackedJobs = view?.jobs.filter(job => ["running", "queued", "failed"].includes(job.status) || Object.keys(job.payload?.failures || {}).length) || []
  const failedJobCount = trackedJobs.filter(job => job.status === "failed" || Object.keys(job.payload?.failures || {}).length).length
  const pendingPromptIds = workshopPendingCandidateIds(view?.jobs || [], plan, groupWriting, Boolean(view?.source_changed))

  const loadEpisodes = useCallback(async () => { setEpisodes(await listEpisodes(projectId)) }, [projectId])
  useImperativeHandle(ref, () => ({ fetchEpisodes: loadEpisodes }), [loadEpisodes])
  const load = useCallback(async (fetchHistory = false) => {
    if (!episodeId) return
    const seq = ++requestSequence.current
    try {
      const [next, work, state] = await Promise.all([getEpisodeDetail(projectId, episodeId), readWorkshop(projectId, episodeId, fetchHistory || script), getEpisodeProduction(projectId, episodeId, "director")])
      if (seq !== requestSequence.current) return
      startTransition(() => {
        const detailSig = (d: any) => d ? JSON.stringify({
          status: d.status,
          beats: d.beats?.map((b: any) => `${b.id}:${b.sketch_url}:${b.triptych_url}:${b.video_duration}:${b.camera}:${b.h3_prompt_reference_state}`)
        }) : ""
        
        const viewSig = (w: any) => w ? JSON.stringify({
          jobs: w.jobs,
          source_changed: w.source_changed,
          planRev: w.plan?.planning_revision,
          legacyRev: w.legacy_plan?.revision,
          historyCount: w.history?.length
        }) : ""
        
        const prodSig = (p: any) => p ? JSON.stringify(p) : ""
        
        setDetail(prev => detailSig(prev) === detailSig(next) ? prev : next)
        setView(prev => viewSig(prev) === viewSig(work) ? prev : work)
        setProduction(prev => prodSig(prev) === prodSig(state) ? prev : state)
        setError("")
      })
    } catch (err) { if (seq === requestSequence.current) setError(director2ErrorDetail(err, "读取工坊失败")) }
  }, [episodeId, projectId, script])
  useEffect(() => {
    void loadEpisodes().catch(err => setError(director2ErrorDetail(err, "读取分集失败")))
    void Promise.all([listAssets(projectId), listVideoWorkflowModes(), listDocuments(projectId)]).then(([a, m, docs]) => { setDocuments(docs); setAssets(a); setModes(m.modes.filter(w => w.prompt_profile === "director_segments" || w.prompt_profile === "full_reference")) }).catch(err => setError(director2ErrorDetail(err, "读取制作配置失败")))
  }, [loadEpisodes, projectId])
  useEffect(() => {
    startTransition(() => { setDetail(null); setView(null); setProduction(null); setTakeId(""); onDetailModeChange?.(Boolean(episodeId)) })
    void load(); 
    let lastJobsStr = ""
    const timer = setInterval(async () => {
      if (document.hidden || !projectId || !episodeId) return
      try {
        const res = await readWorkshopJobs(projectId, episodeId)
        const currentStr = JSON.stringify(res.jobs.map(j => j.status))
        if (lastJobsStr && currentStr !== lastJobsStr) {
          void load()
        }
        lastJobsStr = currentStr
        setView(prev => prev ? {...prev, jobs: res.jobs} : prev)
      } catch (e) {}
    }, 4000)
    return () => { clearInterval(timer); requestSequence.current++ }
  }, [load, episodeId])
  useEffect(() => {
    const previous = lastEditor.current
    setDraft(value => previous.id !== beat?.id || value === previous.saved ? saved : value)
    if (previous.id !== beat?.id) setTakeId("")
    lastEditor.current = { id: beat?.id || "", saved }
  }, [beat?.id, saved])
  useEffect(() => {
    if (!dirty && !previsDirty) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = "" }
    window.addEventListener("beforeunload", warn)
    return () => window.removeEventListener("beforeunload", warn)
  }, [dirty, previsDirty])
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
  function confirmNavigation(change: () => void) {
    if (dirty || previsDirty) modal.confirm({ title: dirty ? "本镜提示词尚未保存" : "本镜动作预演尚未提交或保存", content: "离开当前镜头会放弃未保存的提示词或动作预演输入。可取消并继续编辑。", okText: "放弃修改并离开", cancelText: "继续编辑", onOk: change })
    else change()
  }
  function selectBeat(id: string) {
    if (id === beat?.id) return
    confirmNavigation(() => { const next = new URLSearchParams(params); next.set("source", id); next.set("tab", "shots"); setParams(next) })
  }
  async function generate(ids?: string[]) {
    if (dirty) throw new Error("请先保存当前提示词修改，再生成视频。")
    const result = await generateEpisodeVideo(csrfToken, projectId, episodeId!, { ...videoOptions, beat_ids: ids, expected_revision: revision, expected_reference_fingerprint: plan?.reference_fingerprint, workflow: plan?.workflow_id, aspect_ratio: plan?.aspect_ratio })
    message.info(`已按镜头组提交 ${result.submitted || 0} 个视频任务，跳过 ${result.skipped || 0} 组${result.blocked?.length ? `；${summarizeWorkshopBlocks(result.blocked)}` : ""}`)
  }
  function groupDuration(ids: string[]) {
    return ids.reduce((seconds, id) => seconds + Number(detail?.beats.find(item => item.id === id)?.video_duration || 0), 0)
  }
  const write = (data: Record<string, unknown>) => writeWorkshop(csrfToken, projectId, episodeId!, { expected_revision: revision, expected_reference_fingerprint: plan?.reference_fingerprint, ...data })
  const editDraft = (value: string) => { if (!dirty) editReferences.current = plan?.reference_fingerprint; setDraft(value) }
  const openGroup = (value: WorkshopGroup) => { groupReferences.current = plan?.reference_fingerprint; setGroupDraft(structuredClone(value)) }
  const promptWorkshop = async (csrf: string, project: string, episode: string, data: Record<string, unknown>) => {
    if (dirty) throw new Error("请先保存当前提示词修改，再生成候选。")
    return submitPromptWorkshop(csrf, project, episode, {...data, expected_reference_fingerprint: plan?.reference_fingerprint, ...(groupWriting ? { writing_author: chosenAuthor, review_enabled: reviewEnabled && data.prompt_scope !== "shot_revision", review_author: chosenReviewer } : {})})
  }
  const jobAction = (job: WorkshopJob, action: string, more: Record<string, unknown> = {}) => actWorkshop(csrfToken, projectId, episodeId!, job.id, { action, expected_revision: revision, expected_reference_fingerprint: plan?.reference_fingerprint, ...more })
  const applyCandidate = (job: WorkshopJob, ids: string[], wholeGroup: boolean, version: "original" | "reviewed" = "original") => void perform(async () => {
    await jobAction(job, "apply", { beat_ids: ids, version, switch_version: ids.every(id => plan?.shot_prompts[id]?.authoring_job_id === job.id) })
    setCandidateDrawerOpen(false)
  }, `已采用${version === "reviewed" ? "审校稿" : "原稿"}（${wholeGroup ? "整组" : "本镜"}）`)
  const reviewJob = (job: WorkshopJob, ids: string[]) => void perform(() => jobAction(job, "review", { beat_ids: ids, review_author: chosenReviewer }), "已提交独立审校，原稿保留")
  const regenerateJob = (job: WorkshopJob) => void perform(async () => {
    if (dirty) throw new Error("请先保存当前提示词修改，再创建新候选。")
    await jobAction(job, "regenerate", { writing_author: chosenAuthor })
  }, "已按当前写稿方式创建新任务，旧记录保留")
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
    {error && <Alert type="error" title={error} />}
    <div className="xiaji-episode-grid">{episodes.map(e => <div key={e.id} className="xiaji-episode-card" role="button" tabIndex={0} onKeyDown={event => { if (event.key === "Enter") navigate(`/director/projects/${projectId}/workshop/${e.id}?tab=shots`) }} onClick={() => navigate(`/director/projects/${projectId}/workshop/${e.id}?tab=shots`)}>
      <div className="card-head"><strong className="card-title">第 {e.episode_num} 集 · {e.title}</strong><Tag>{linkedEpisode(e) ? "已关联剧本" : "历史／未关联"}</Tag></div>
      <p className="card-summary">{e.script_text?.replace(/[#\n-]/g, " ").slice(0, 85) || "采纳剧本后开始本集制作"}</p><div className="card-footer"><em className="card-meta">{e.shots_count || 0} 个镜头</em><span className="card-actions">进入本集 →</span></div>
    </div>)}</div>{!episodes.length && <Empty description="先在内容库采纳剧本，工坊将自动建立分集" />}
  </div></div>
  if (!detail || !view) return <div className="unified-content">{error ? <Alert type="error" title={error} action={<Button onClick={() => void load()}>重试</Button>} /> : <Spin />}</div>
  const materials = beat && production ? materialsForUnit(production, beat.id) : []
  const take = materials.find(m => m.id === takeId) || materials.find(m => production?.adopted[beat?.id || ""] === m.id) || materials[0]
  const range = beat && take?.ranges?.[beat.id]
  const beatIndex = detail.beats.findIndex(item => item.id === beat?.id)
  const generationIds = group?.beat_ids || (beat ? [beat.id] : [])
  const generationShots = detail.beats.filter(item => generationIds.includes(item.id))
  const referenceBlocked = Boolean(group && (group.reference_issues?.length || group.reference_slots.length < (mode?.min_references || 0)))
  const videoBlockReason = workshopVideoBlockReason({ hasPlan: Boolean(plan), busy, dirty, sourceChanged: view.source_changed, referencesMissing: referenceBlocked, shots: generationShots, prompts: plan?.shot_prompts || {} })
  const nextAction = workshopNextAction({ hasPlan: Boolean(plan) && !view.source_changed, dirty, pending: Boolean(beat && pendingPromptIds.has(beat.id)), hasPrompt: Boolean(saved), videoBlocked: Boolean(videoBlockReason) })
  const videoLabel = plan?.workflow_id === H3_CONFIRM_MODE ? "生成一采预览" : generationIds.length > 1 ? "生成本组视频（" + generationIds.length + " 镜）" : "生成本镜视频"
  const writeLabel = groupWriting ? "生成本组提示词（" + (group?.beat_ids.length || 0) + " 镜）" : "生成本镜提示词"
  const openPlanning = () => { setWorkflow(plan?.workflow_id || workflow); setAspect(plan?.aspect_ratio || aspect); setMaximum(plan?.max_shots_per_group || 3); setTargetDuration(plan?.target_duration_seconds || null); setReuse(Boolean(detail.beats.length)); setPlanning(true) }
  const saveCurrentPrompt = () => void perform(() => write({ beat_id: beat!.id, h3_prompt: draft, expected_reference_fingerprint: editReferences.current }), "已保存本镜提示词")
  const writeCurrentPrompt = () => void perform(() => promptWorkshop(csrfToken, projectId, episodeId, { expected_revision: revision, beat_ids: groupWriting ? group?.beat_ids : [beat!.id] }), groupWriting ? "正在统筹生成整组候选稿" : "正在生成本镜候选稿")
  const showPending = () => {
    const id = [...pendingPromptIds][0]
    if (!id) return
    const change = () => { const next = new URLSearchParams(params); next.set("source", id); next.set("tab", "shots"); setParams(next); setInspector("prompt"); setCandidateDrawerOpen(true) }
    if (id !== beat?.id) confirmNavigation(change); else change()
  }
  const groupEditor = (groups: WorkshopGroup[], onChange: (next: WorkshopGroup[]) => void) => groups.map((g, i) => <Card key={g.id} size="small" title={`镜头组 ${i + 1}`}>
    <Space wrap>{g.beat_ids.map((id, n) => <Space key={id}><Tag>镜头 {(planningJob?.payload.candidate?.beats || detail.beats).findIndex(b => b.id === id) + 1}</Tag>{n < g.beat_ids.length - 1 && <Button size="small" onClick={() => onChange(splitWorkshopGroup(groups, g.id, n + 1))}>在此拆组</Button>}</Space>)}{i < groups.length - 1 && <Button size="small" onClick={() => { const next = mergeWorkshopGroups(groups, i); if (next === groups) message.warning("两组公共设定或参考编号不同，请先统一组设置"); else onChange(next) }}>合并下一组</Button>}</Space>
  </Card>)
  return <div className={"d2-episode-workshop workshop-container in-episode-detail unified-workshop" + (focusEditor ? " is-focused" : "")}>
    {modalContextHolder}
    <header className="xiaji-episode-head workshop-episode-header">
      <Button icon={<ArrowLeft size={15} />} onClick={() => confirmNavigation(() => navigate("/director/projects/" + projectId + "/workshop"))}>返回分集</Button>
      <div className="workshop-episode-title">
        <div className="workshop-title-line"><h2>第 {detail.number} 集 · {detail.title}</h2><Tag>{detail.beats.length} 镜 · {plan?.groups.length || 0} 组</Tag></div>
        <Typography.Text type="secondary">来源版本 {view.source.revision} · {plan?.target_duration_seconds ? `目标 ${plan.target_duration_seconds} 秒 · ` : ""}{plan?.aspect_ratio || aspect} · {plan ? `已确认规划 ${plan.planning_revision}` : "待确认镜头规划"}</Typography.Text>
      </div>
      <Space size={8}><Director2VideoSettingsPopover triggerLabel="更多视频设置" workflowId={plan?.workflow_id || workflow} workflows={modes} fields={visibleVideoOptionFields(mode).filter(f => !["duration", "video_duration"].includes(f.name))} values={{...Object.fromEntries(Object.entries(videoOptions).map(([key, value]) => [key, String(value)])),aspect_ratio:plan?.aspect_ratio || aspect}} onWorkflowChange={id => { setWorkflow(id); setMaximum(Math.min(maximum,modes.find(m => m.id === id)?.max_segments || 1)); setReuse(Boolean(detail.beats.length)); setPlanning(true) }} onChange={(name, value) => { if(name === "aspect_ratio") {setAspect(value); setWorkflow(plan?.workflow_id || workflow); setReuse(Boolean(detail.beats.length)); setPlanning(true); return} const next = {...videoOptions,[name]:optionSchemaFromMode(mode)[name]?.type === "boolean" ? value === "true" : optionSchemaFromMode(mode)[name]?.type === "integer" || optionSchemaFromMode(mode)[name]?.type === "number" ? Number(value) : value}; setVideoOptions(next); saveVideoSettings(projectId,Object.fromEntries(Object.entries(next).map(([key,v]) => [key,String(v)]))) }} /><Dropdown trigger={["click"]} menu={{ items: [
        { key: "plan", label: plan ? "调整镜头规划" : "规划镜头", disabled: busy || dirty, onClick: openPlanning },
        { key: "script", label: "查看采纳剧本", onClick: () => { setScript(true); void load(true); } },
        { key: "refresh", label: "刷新本集", onClick: () => void load() },
        { type: "divider" },
        { key: "episode-prompts", label: "整集：批量生成提示词", disabled: !plan || busy || dirty || view.source_changed, onClick: () => void perform(() => promptWorkshop(csrfToken, projectId, episodeId, { expected_revision: revision }), "正在生成本集 H3 候选稿") },
        { key: "episode-videos", label: "整集：按镜头组批量生成视频", disabled: !plan || busy || dirty || view.source_changed, onClick: () => modal.confirm({ title: "按 " + plan!.groups.length + " 个镜头组批量生成本集视频？", content: "每组分别提交一个视频任务；已采用的组会跳过，不会合成一条超长视频。", okText: "按组提交", cancelText: "取消", onOk: () => perform(() => generate()) }) },
      ] }}><Button>分集操作 <ChevronDown size={14} /></Button></Dropdown></Space>
    </header>
    {error && <Alert type="error" title={error} />}
    {view.source_changed && <Alert type="warning" showIcon title="内容库有新采纳稿，请调整镜头规划；现有视频和手工稿已保留" />}
    {view.source.unlinked && <Alert type="warning" title="本集未关联当前文档分集，历史剧本和素材保留。规划将使用本集现存剧本。" />}
    <Tabs className="episode-tabs" tabBarExtraContent={activeTab === "shots" ? <div className="workshop-episode-tools">
      {pendingPromptIds.size > 0 && <Button type="link" onClick={showPending}>{pendingPromptIds.size} 镜候选待审阅</Button>}
      {missingReferenceGroups.length > 0 && <Button type="text" onClick={() => setReferenceIssuesOpen(true)}>{missingReferenceGroups.length} 组素材待补齐</Button>}
      <Button type="text" onClick={() => setTaskDrawerOpen(true)}>任务记录{runningJobs.length ? " · " + runningJobs.length + " 进行中" : ""}{failedJobCount ? " · " + failedJobCount + " 条失败" : ""}</Button>
    </div> : undefined} activeKey={activeTab} onChange={key => { const next = new URLSearchParams(params); next.set("tab", key); setParams(next) }} items={[
      { key: "shots", label: "镜头", children: <div className="workshop-shots-workspace">
        <div className="unified-shot-layout xiaji-shots-split"><aside className="unified-shot-list xiaji-shots-grid-pane" aria-label="镜头导航">
          <div className="workshop-shot-search"><Input aria-label="搜索镜头" placeholder="搜索镜号、剧情或对白" prefix={<Search size={15} />} allowClear value={shotSearch} onChange={event => setShotSearch(event.target.value)} /><span>{detail.beats.length} 个镜头 · 选择后在右侧继续制作</span></div>
          <div className="workshop-shot-navigation">{(plan?.groups || [{ id: "legacy", beat_ids: detail.beats.map(b => b.id), common_prompt: "", reference_slots: [] }]).map((g, i) => {
            const matching = g.beat_ids.map(id => detail.beats.find(b => b.id === id)).filter(b => b && (!shotSearch.trim() || [b.sequence, "镜头 " + b.sequence, b.heading, b.action, b.dialogue].join(" ").toLocaleLowerCase().includes(shotSearch.trim().toLocaleLowerCase())))
            if (!matching.length) return null
            return <section key={g.id} className={group?.id === g.id ? "is-current-group" : undefined}>
              <div className="workshop-group-label"><strong>{plan ? "第 " + (i + 1) + " 组" : "历史镜头"}</strong><span>{g.beat_ids.length} 镜 · {groupDuration(g.beat_ids)} 秒</span></div>
              {matching.map(b => b && <button type="button" key={b.id} aria-pressed={beat?.id === b.id} aria-label={"选择镜头 " + b.sequence + "：" + (b.heading || b.action)} className={"workshop-shot-row" + (beat?.id === b.id ? " is-selected" : "")} onClick={() => selectBeat(b.id)}>
                <span className="workshop-shot-thumbnail">{b.sketch_url || b.triptych_url ? <img src={b.sketch_url || b.triptych_url || undefined} alt="" loading="lazy" /> : <span>{String(b.sequence).padStart(2, "0")}</span>}</span>
                <span className="workshop-shot-row-copy"><span className="workshop-shot-row-title"><strong>镜头 {b.sequence}</strong><span>{b.video_duration}s</span></span><span className="workshop-shot-row-description">{b.heading || b.action || "暂无镜头描述"}</span><span className={"workshop-shot-status" + (pendingPromptIds.has(b.id) ? " is-pending" : "")}>{pendingPromptIds.has(b.id) ? "新候选待审阅" : production?.adopted[b.id] ? "已采用视频" : plan?.shot_prompts?.[b.id] ? b.h3_prompt_reference_state === "current" ? "提示词就绪" : "提示词待检查" : "待写提示词"}</span></span>
              </button>)}
            </section>
          })}{shotSearch.trim() && !detail.beats.some(b => [b.sequence, "镜头 " + b.sequence, b.heading, b.action, b.dialogue].join(" ").toLocaleLowerCase().includes(shotSearch.trim().toLocaleLowerCase())) && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的镜头"><Button onClick={() => setShotSearch("")}>清除搜索</Button></Empty>}</div>
        </aside><section className="unified-shot-detail xiaji-shots-detail" aria-label="镜头检视器">{beat && <header className="workshop-current-shot"><div><strong>镜头 {beat.sequence}<span className="workshop-shot-position"> / {detail.beats.length}</span></strong><span>{group ? "第 " + currentGroupNumber + " 组 · " + group.beat_ids.length + " 镜共 " + groupDuration(group.beat_ids) + " 秒" : "尚未分组"}</span></div><Space size={4}>{group && <Button type="text" size="small" onClick={() => openGroup(group)}>组设定</Button>}<Tooltip title="上一个镜头"><Button aria-label="上一个镜头" icon={<ChevronLeft size={16} />} disabled={beatIndex <= 0} onClick={() => selectBeat(detail.beats[beatIndex - 1].id)} /></Tooltip><Tooltip title="下一个镜头"><Button aria-label="下一个镜头" icon={<ChevronRight size={16} />} disabled={beatIndex >= detail.beats.length - 1} onClick={() => selectBeat(detail.beats[beatIndex + 1].id)} /></Tooltip><Tooltip title={focusEditor ? "退出专注模式" : "专注当前镜头"}><Button aria-label={focusEditor ? "退出专注模式" : "专注当前镜头"} aria-pressed={focusEditor} icon={focusEditor ? <Minimize2 size={15} /> : <Maximize2 size={15} />} onClick={() => setFocusEditor(value => !value)} /></Tooltip></Space></header>}{beat ? <Tabs className="xiaji-inspector-tabs" activeKey={inspector} onChange={setInspector} items={[
          { key: "text", label: "镜头内容", children: <div className="workshop-inspector-scroll workshop-shot-content">
            <section><Typography.Title level={4}>镜头 {beat.sequence}</Typography.Title><Typography.Paragraph className="workshop-shot-heading">{beat.heading}</Typography.Paragraph></section>
            <section><Typography.Title level={5}>剧情</Typography.Title><Typography.Paragraph>{beat.action || "暂无剧情描述"}</Typography.Paragraph></section>
            <section><Typography.Title level={5}>对白</Typography.Title><Typography.Paragraph>{beat.dialogue || "无"}</Typography.Paragraph><Typography.Text type="secondary">剧情和对白来自采纳剧本；改故事请回内容库。</Typography.Text></section>
            <section><Typography.Title level={5}>拍摄设置</Typography.Title><Form layout="vertical" key={`${beat.id}-${plan?.planning_revision}`} onFinish={values => void perform(() => write({ beat_id: beat.id, shot_updates: values }), "拍摄设置已保存")} initialValues={{ camera: beat.camera, video_duration: Number(beat.video_duration) }}><Form.Item name="camera" label="景别与运镜"><Input.TextArea rows={3} disabled={!plan} /></Form.Item><Form.Item name="video_duration" label="镜头时长（秒）"><InputNumber min={1} disabled={!plan} /></Form.Item><Button htmlType="submit" disabled={!plan || busy}>保存拍摄设置</Button></Form></section>
          </div> },
          { key: "material", label: "素材", children: <div className="workshop-inspector-scroll workshop-materials-scroll">
            {!plan && <Alert type="info" showIcon title="先确认镜头规划，再关联素材。" action={<Button onClick={openPlanning}>规划镜头</Button>} />}
            <WorkshopMaterialsPanel beat={beat} assets={assets} assetRefs={assetRefs} group={group} disabled={!plan || busy}
              onSelectAssets={setAssetPicker} onGroupSettings={() => { if (group) openGroup(group) }}
              onWritingReferences={urls => void perform(() => write({ beat_id: beat.id, writing_reference_urls: urls }))}
              onGenerateSketch={() => void perform(() => generateBeatSketch(csrfToken, projectId, episodeId, beat.id), "草图任务已提交")}
              onGenerateTriptych={() => void perform(() => generateBeatTriptych(csrfToken, projectId, episodeId, beat.id), "三联图任务已提交")}
              onOpenPrompts={() => setInspector("prompt")} />
          </div> },
          { key: "prompt", label: dirty ? "提示词 · 未保存" : "提示词", children: <div className="workshop-prompt-workspace">
            {!plan && <Alert type="info" title="先确认镜头规划，可选择保留当前镜头。历史稿件在下方完整保留。" />}
            <div className="workshop-prompt-layout">
              <div className="h3-prompt-panel">
                <header className="h3-prompt-head">
                  <div className="workshop-prompt-title"><div><Typography.Text strong>正式提示词</Typography.Text><span className="workshop-editor-context">{dirty ? "未保存修改" : pendingPromptIds.has(beat.id) ? "有新候选，审阅采纳后才替换正文" : saved ? "已保存 · 可编辑本镜正文" : "先生成候选，审阅后采纳"}</span></div><Button onClick={() => setInspector("material")}>查看素材 · {group?.reference_slots.length || 0} 张视频参考</Button></div>
                </header>
                <div className="workshop-prompt-body">
                  <Input.TextArea id="workshop-h3-editor" className="h3-prompt-editor" aria-label="本镜 H3 提示词" placeholder={pendingPromptIds.has(beat.id) ? "本镜候选稿已生成，请在上方检查并采纳。" : "暂无已采纳提示词，请先生成并采纳候选稿。"} value={draft} onChange={event => editDraft(event.target.value)} rows={10} disabled={!plan} />
                  {beat.h3_prompt_reference_state === "stale" && <Alert type="warning" showIcon title="镜头或参考设定已变化，请检查正文后保存或生成新候选" />}
                  {plan?.shot_prompts[beat.id]?.authoring_version && <Typography.Text type="secondary">采纳来源：{plan.shot_prompts[beat.id].authoring_version === "reviewed" ? "审校稿" : "原稿"} · {plan.shot_prompts[beat.id].authoring_job_id}</Typography.Text>}
                  <WorkshopPromptCandidates display="history" jobs={view.jobs} beatId={beat.id} beats={detail.beats} group={group} groupWriting={groupWriting} plan={plan || null} sourceChanged={view.source_changed} busy={busy} dirty={dirty} onRegenerate={regenerateJob} onReview={reviewJob} onApply={applyCandidate} />
            {view.legacy_prompts[beat.id]?.length ? <Collapse items={[{ key: "history", label: `历史稿件（${view.legacy_prompts[beat.id].length}）`, children: view.legacy_prompts[beat.id].map((p, i) => <Card key={i} title={p.source}><Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{p.common_prompt}{"\n"}{p.h3_prompt}</Typography.Paragraph><Button disabled={!plan} onClick={() => editDraft(p.h3_prompt)}>放入编辑器检查</Button></Card>) }]} /> : null}
            {Boolean(plan?.shot_prompts?.[beat.id]?.history?.length) && <Collapse items={[{key:"prompt-versions",label:"本镜提示词历史版本",children:plan?.shot_prompts?.[beat.id]?.history?.map((record,i) => <Card key={i} size="small" title={`历史稿 ${i+1}`}><Typography.Paragraph style={{whiteSpace:"pre-wrap"}}>{record.h3_prompt}</Typography.Paragraph><Button disabled={dirty} onClick={() => editDraft(record.h3_prompt)}>放入编辑器检查</Button></Card>)}]} />}

                </div>
                <footer className="workshop-prompt-footer workshop-workflow-footer">
                  <span className="workshop-next-step" role="status">{videoBlockReason || (generationIds.length > 1 ? "视频按第 " + currentGroupNumber + " 组（" + generationIds.length + " 镜）一起提交；返修仅改当前镜头。" : "使用已保存的提示词生成当前镜头视频。")}</span>
                  <div className="workshop-footer-actions"><Dropdown trigger={["click"]} menu={{ items: [
                    { key: "write", label: writeLabel, disabled: busy || !plan || dirty || view.source_changed, onClick: writeCurrentPrompt },
                    ...(groupWriting ? [{ key: "revise", label: "只返修镜头 " + beat.sequence, disabled: busy || dirty || view.source_changed || !group?.beat_ids.every(id => plan?.shot_prompts?.[id]), onClick: () => { setRevisionTarget(beat.id); setRevisionNote("") } }] : []),
                    { key: "copy", label: "复制完整提示词（已保存版）", disabled: !saved, onClick: () => void navigator.clipboard.writeText((group?.common_prompt ? "主体定义：" + group.common_prompt + "\n\n" : "") + saved).then(() => message.success("已复制有效提示词")) },
                    { key: "author", label: "写稿设置 · " + (chosenAuthor.model || "未配置"), onClick: () => setAuthorSettingsOpen(true) },
                  ] }}><Button>提示词操作 <ChevronDown size={14} /></Button></Dropdown><Space size={8}>
                    {nextAction !== "generate" && <Tooltip title={videoBlockReason || undefined}><Button disabled={Boolean(videoBlockReason)} onClick={() => void perform(() => generate(generationIds))}>{videoLabel}</Button></Tooltip>}
                    <Button type="primary" disabled={busy || (dirty && nextAction !== "save") || (nextAction === "save" && !plan)} onClick={() => {
                      if (nextAction === "plan") openPlanning()
                      else if (nextAction === "save") saveCurrentPrompt()
                      else if (nextAction === "review") setCandidateDrawerOpen(true)
                      else if (nextAction === "write" || (nextAction === "check" && !referenceBlocked)) writeCurrentPrompt()
                      else if (nextAction === "check") setInspector("material")
                      else void perform(() => generate(generationIds))
                    }}>{nextAction === "plan" ? view.source_changed ? "更新镜头规划" : "规划镜头" : nextAction === "save" ? "保存修改" : nextAction === "review" ? "审阅候选并采纳" : nextAction === "write" ? writeLabel : nextAction === "check" ? referenceBlocked ? "检查素材与参考" : writeLabel : videoLabel}</Button>
                  </Space></div>
                </footer>
              </div>
            </div>
          </div> },
          { key: "previs", label: "动作预演", children: <div className="workshop-inspector-scroll workshop-previs-scroll">
            <ActionPrevisPane key={`${projectId}:${episodeId}:${beat.id}`} projectId={projectId} episodeId={episodeId} beatId={beat.id} csrfToken={csrfToken} onDirtyChange={setPrevisDirty} />
          </div> },
          { key: "video", label: "视频版本", children: <div className="workshop-inspector-scroll">{take && production ? <Space orientation="vertical" size={16} style={{ width: "100%" }}><Select aria-label="视频版本" value={take.id} style={{ minWidth: 260 }} onChange={setTakeId} options={materials.map((m, i) => ({ value: m.id, label: `${production.adopted[beat.id] === m.id ? "已采用" : "候选"} · 版本 ${materials.length - i}` }))} /><video className="production-video" key={`${take.url}-${beat.id}`} src={take.url} controls onLoadedMetadata={e => { if (range) e.currentTarget.currentTime = range.start }} onTimeUpdate={e => { if (range && e.currentTarget.currentTime > range.end) e.currentTarget.pause() }} /><Typography.Text>{range ? `本镜区间 ${range.start.toFixed(2)}–${range.end.toFixed(2)} 秒` : "历史素材尚无可靠区间"}</Typography.Text><Space><Button type="primary" disabled={busy || production.adopted[beat.id] === take.id} onClick={() => void perform(() => updateEpisodeProduction(csrfToken, projectId, episodeId, "adopt", { expected_revision: production.revision, mode: production.active_mode, material_id: take.id }), "已采用视频")}>采用此版（覆盖 {take.unit_ids.length} 镜）</Button><Button disabled={busy || !take.job_id} onClick={() => void perform(() => upscaleProjectVideoJob(csrfToken, projectId, take.job_id, { scale: 2 }), "已提交超分")}>2× 超分</Button></Space>{take.workflow_id === H3_CONFIRM_MODE && take.job_id && <H3ConfirmationPanel endpoint={`/api/projects/${projectId}/jobs/${take.job_id}/refine`} csrfToken={csrfToken} />}</Space> : <Empty description="生成视频后，在这里预览和采用 Take" />}</div> },
        ]} /> : <Empty description="采纳剧本后，点击规划镜头开始制作" />}</section></div>
      </div> },
      { key: "dubbing", label: "声音", children: production && <ProductionSound state={production} csrfToken={csrfToken} projectId={projectId} episodeId={episodeId} onRefresh={load} /> },
      { key: "compose", label: "合成", children: production && <ProductionFilm state={production} csrfToken={csrfToken} projectId={projectId} episodeId={episodeId} onRefresh={load} onJob={() => void load()} jobActive={false} /> },
    ]} />
    {beat && <Drawer rootClassName="unified-workshop-drawer workshop-candidate-drawer" title={"审阅候选 · 镜头 " + beat.sequence + " / 第 " + currentGroupNumber + " 组"} size={720} open={candidateDrawerOpen} onClose={() => setCandidateDrawerOpen(false)}>
      <Alert type="info" showIcon title="先检查候选，再决定是否替换正式稿" description={dirty ? "当前正文有未保存修改，采纳已禁用。请关闭审阅面板并先保存。" : "整组候选会一起更新本组正文和公共设定；单镜返修只替换当前镜头。关闭面板不会采纳。"} />
      <WorkshopPromptCandidates display="all" jobs={view.jobs} beatId={beat.id} beats={detail.beats} group={group} groupWriting={groupWriting} plan={plan || null} sourceChanged={view.source_changed} busy={busy} dirty={dirty} onRegenerate={regenerateJob} onReview={reviewJob} onApply={applyCandidate} />
    </Drawer>}
    <Drawer rootClassName="unified-workshop-drawer" title="写稿设置" open={authorSettingsOpen} onClose={() => setAuthorSettingsOpen(false)} size={480}><Form layout="vertical">
          <Alert type="info" showIcon title="不会因附图静默更换作者。模型 ID 来自已配置的 API，不能把桌面模型名当成 API 可用性证明。" />
          <div className="workshop-author-fields">
            <Form.Item label="写稿供应商"><Select aria-label="写稿供应商" style={{ width: 200 }} value={chosenAuthor.profile_id} disabled={busy} options={(view.writing_profiles || []).map(p => ({ value: p.profile_id, label: `${p.profile_id} · ${p.model || "未配置"}` }))} onChange={id => setAuthorChoice(view.writing_profiles?.find(p => p.profile_id === id) || { profile_id: id })} /></Form.Item>
            <Form.Item label="API 模型 ID"><Input aria-label="写稿模型 ID" value={chosenAuthor.model || ""} disabled={busy} onChange={e => setAuthorChoice(p => ({ ...p, model: e.target.value }))} /></Form.Item>
            <Form.Item label="推理设置（模型支持时）"><Select aria-label="写稿推理设置" style={{ width: 160 }} value={chosenAuthor.reasoning_effort || "low"} disabled={busy} options={["auto", "none", "low", "medium", "high", "xhigh"].map(value => ({ value, label: value }))} onChange={reasoning_effort => setAuthorChoice(p => ({ ...p, reasoning_effort }))} /></Form.Item>
            <Form.Item label="图片处理"><Typography.Text>作者直接读取实际参考图，需要支持视觉的模型。</Typography.Text></Form.Item>
            <Form.Item label="二次审校"><Switch aria-label="二次审校" checked={reviewEnabled} onChange={setReviewEnabled} /></Form.Item>
            {reviewEnabled && <>
              <Alert type="info" title="每组第一稿生成后额外调用一次审校模型。原稿保留，需要明确选择采用版本。" />
              <Form.Item label="审校供应商"><Select aria-label="审校供应商" style={{ width: 200 }} value={chosenReviewer.profile_id} options={(view.writing_profiles || []).map(p => ({ value: p.profile_id, label: `${p.profile_id} · ${p.model || "未配置"}` }))} onChange={id => setReviewAuthor(view.writing_profiles?.find(p => p.profile_id === id) || { profile_id: id })} /></Form.Item>
              <Form.Item label="审校模型 ID"><Input aria-label="审校模型 ID" value={chosenReviewer.model || ""} onChange={e => setReviewAuthor(p => ({ ...p, model: e.target.value }))} /></Form.Item>
              <Form.Item label="审校推理设置"><Select aria-label="审校推理设置" value={chosenReviewer.reasoning_effort || "low"} options={["auto", "none", "low", "medium", "high", "xhigh"].map(value => ({ value, label: value }))} onChange={reasoning_effort => setReviewAuthor(p => ({ ...p, reasoning_effort }))} /></Form.Item>
            </>}
          </div>
        </Form></Drawer>
    <Drawer rootClassName="unified-workshop-drawer" title={`任务进度与失败记录（${trackedJobs.length}）`} open={taskDrawerOpen} onClose={() => setTaskDrawerOpen(false)} size={520}>
      <div className="workshop-task-records">{trackedJobs.map(job => <Alert key={job.id} type={job.status === "failed" || Object.keys(job.payload?.failures || {}).length ? "error" : "info"} showIcon title={job.error || job.payload?.message || "任务处理中"} description={<Space orientation="vertical">
        <Typography.Text>任务 {job.id.slice(-8)} · {job.status === "failed" ? "失败" : job.status === "queued" ? "排队中" : job.status === "running" ? "进行中" : "含失败记录"}</Typography.Text>
        {["running", "queued"].includes(job.status) ? <Button disabled={busy} onClick={() => void perform(() => jobAction(job, "cancel"))}>取消</Button> : <Space wrap>
        <Button disabled={busy} onClick={() => void perform(() => jobAction(job, "retry"))}>{job.kind === "workshop_prompt" ? "按原输入重试" : "重试失败部分"}</Button>
        {groupWriting && workshopCanRegenerate(job) && <Button disabled={busy || dirty || view.source_changed || !plan} onClick={() => regenerateJob(job)}>按新方式重新生成</Button>}
      </Space>}</Space>} />)}{!trackedJobs.length && <Empty description="暂无运行中任务或失败记录" />}</div>
    </Drawer>
    <Drawer rootClassName="unified-workshop-drawer" title="参考素材待完善" open={referenceIssuesOpen} onClose={() => setReferenceIssuesOpen(false)} size={480}>
      <div className="workshop-task-records"><Typography.Paragraph>人物／道具设定图自动关联，补图后会自动更新；提示词需按最新参考重新生成并采纳。</Typography.Paragraph>{missingReferenceGroups.map(item => <Alert key={item.id} type="warning" showIcon title={`第 ${(plan?.groups.indexOf(item) || 0) + 1} 组`} description={item.reference_issues?.join("；") || "请补齐视频参考图"} action={<Button onClick={() => openGroup(item)}>检查组参考</Button>} />)}<Button onClick={() => navigate(`/director/projects/${projectId}/assets`)}>去资产库补图</Button></div>
    </Drawer>
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
    {script && <Drawer destroyOnClose title="已采纳剧本" open={script} onClose={() => setScript(false)} size={720}><Button onClick={() => navigate(`/director/projects/${projectId}/content${view.source.document_id ? `?doc=${view.source.document_id}` : ""}`)}>到内容库修改剧本</Button><Typography.Paragraph style={{ whiteSpace: "pre-wrap", marginTop: 20 }}>{view.source.text}</Typography.Paragraph><Collapse items={[{key:"history",label:`历史规划与素材（${view.history?.length || 0} 次）`,children:<Space orientation="vertical" style={{width:"100%"}}>{view.history?.map((h,i) => <Collapse key={i} items={[{key:String(i),label:`历史版本 ${i+1} · ${h.beats.length} 镜`,children:<pre style={{whiteSpace:"pre-wrap"}}>{JSON.stringify(h,null,2)}</pre>}]} />)}{view.historical_media?.map(m => <a key={m.id} href={m.url} target="_blank" rel="noreferrer">{m.title || "历史视频"} · {m.id}</a>)}</Space>}]} /></Drawer>}
    <Modal title="返修本镜提示词" open={Boolean(revisionTarget)} onCancel={() => setRevisionTarget(null)} okText="生成本镜返修候选" confirmLoading={busy} okButtonProps={{ disabled: !revisionNote.trim() || dirty || view.source_changed }} onOk={() => void perform(async () => {
      await promptWorkshop(csrfToken, projectId, episodeId, { expected_revision: revision, beat_ids: [revisionTarget], prompt_scope: "shot_revision", revision_note: revisionNote.trim() }); setRevisionTarget(null)
    }, "正在结合整组上下文返修本镜")}>
      <Alert type="info" title="只返修当前镜头，其他镜头保持不变" description="会参考整组已采纳提示词保持前后衔接。修改镜头数量、时长或组公共设定，请回到整组调整。" />
      <Form layout="vertical"><Form.Item label="本镜修改意见"><Input.TextArea value={revisionNote} onChange={e => setRevisionNote(e.target.value)} maxLength={4000} showCount rows={4} /></Form.Item></Form>
    </Modal>
    <Modal title="规划镜头与分组" open={planning} onCancel={() => setPlanning(false)} footer={null} width={900}>
      <Alert type="info" title="先确认镜头数量、剧情分配和分组；这里不会生成视频提示词。" />
      <Form layout="vertical"><Form.Item label="规划方式"><Select value={reuse} onChange={setReuse} options={[{ value: false, label: "从采纳剧本重新规划（先预览）" }, { value: true, label: "保留当前镜头，只建立或调整分组" }]} /></Form.Item><Form.Item label="视频工作流"><Select value={workflow} onChange={id => { setWorkflow(id); setMaximum(Math.min(maximum, modes.find(m => m.id === id)?.max_segments || 1)) }} options={modes.map(m => ({ value: m.id, label: m.name }))} /></Form.Item><Space wrap><Form.Item label="画幅"><Select style={{ width: 140 }} value={aspect} onChange={setAspect} options={(optionSchemaFromMode(planningMode).aspect_ratio?.enum || ["16:9", "9:16"]).map(v => ({ value: String(v), label: String(v) }))} /></Form.Item><Form.Item label="目标时长（秒，留空自动）"><InputNumber min={1} max={7200} value={targetDuration} onChange={setTargetDuration} disabled={reuse} /></Form.Item><Form.Item label="目标镜头数（留空自动）"><InputNumber min={1} value={target} onChange={setTarget} disabled={reuse} /></Form.Item><Form.Item label="每组最多镜头数"><InputNumber min={1} max={planningMode?.max_segments || 1} value={maximum} onChange={v => setMaximum(v || 1)} /></Form.Item></Space></Form>
      <Button type="primary" loading={busy} onClick={() => void perform(async () => { const job = await planWorkshop(csrfToken, projectId, episodeId, { expected_revision: revision, workflow_id: workflow, aspect_ratio: aspect, max_shots_per_group: maximum, target_shot_count: target, target_duration_seconds: targetDuration, reuse_existing: reuse }); setPreviewJob(job.job_id); setCandidateGroups(null); setCandidateEdits({}) }, "正在准备镜头候选")}>生成规划候选</Button>
      {planningJob?.payload?.candidate && <Space orientation="vertical" style={{ width: "100%", marginTop: 16 }}><Alert title={planningJob.payload?.count_note} description={`保留 ${planningJob.payload?.candidate.beats.filter(b => detail.beats.some(old => old.id === b.id)).length} 镜；新增 ${planningJob.payload?.candidate.beats.filter(b => !detail.beats.some(old => old.id === b.id)).length} 镜；删除 ${detail.beats.filter(b => !planningJob.payload?.candidate!.beats.some(next => next.id === b.id)).length} 镜。历史结果保留。`} type="info" /><Table size="small" pagination={false} rowKey="id" dataSource={planningJob.payload?.candidate.beats} columns={[{ title: "镜号", dataIndex: "sequence" }, { title: "镜头", dataIndex: "heading" }, { title: "动作", dataIndex: "action" }, { title: "对白", dataIndex: "dialogue" }, { title: "拍摄意图", render: (_, b) => <Input.TextArea aria-label={`候选镜头 ${b.sequence} 运镜`} value={String(candidateEdits[b.id]?.camera ?? b.camera ?? "")} onChange={e => setCandidateEdits({...candidateEdits,[b.id]:{...candidateEdits[b.id],camera:e.target.value}})} /> }, { title: "时长", render: (_, b) => <InputNumber aria-label={`候选镜头 ${b.sequence} 时长`} min={1} value={Number(candidateEdits[b.id]?.video_duration ?? b.video_duration)} onChange={v => setCandidateEdits({...candidateEdits,[b.id]:{...candidateEdits[b.id],video_duration:v}})} /> }]} />{groupEditor(candidateGroups || planningJob.payload?.candidate.plan.groups, setCandidateGroups)}<Button type="primary" disabled={busy} onClick={() => void perform(async () => { await jobAction(planningJob, "apply", { groups: candidateGroups || planningJob.payload?.candidate!.plan.groups, shot_updates: candidateEdits }); setPlanning(false) }, "已确认镜头规划")}>确认采用本次规划</Button></Space>}
      {plan && <Collapse style={{ marginTop: 16 }} items={[{ key: "groups", label: "仅调整当前分组（不调用 AI）", children: <>{groupEditor(plan.groups, groups => void perform(() => write({ groups }), "已调整分组"))}</> }]} />}
    </Modal>
    <Modal title="组公共设定与参考图" open={Boolean(groupDraft)} onCancel={() => setGroupDraft(null)} confirmLoading={busy} onOk={() => groupDraft && void perform(async () => { await write({ expected_reference_fingerprint: groupReferences.current, groups: plan!.groups.map(g => g.id === groupDraft.id ? groupDraft : g) }); setGroupDraft(null) }, "组设定已保存，相关提示词将重新检查")} width={720}>
      {groupDraft && <Alert type={groupDraft.reference_issues?.length ? "warning" : "info"} showIcon title={groupDraft.reference_policy === "auto" ? "参考图自动关联人物／道具及所选造型，资产补图后自动更新" : "当前参考图为手动选择，顺序保留；资产换图会自动更新"} description={groupDraft.reference_issues?.join("；")} action={groupDraft.reference_policy !== "auto" && <Button disabled={busy} onClick={() => void perform(async () => { await write({auto_reference_group_ids:[groupDraft.id]}); setGroupDraft(null) }, "已恢复自动关联参考图")}>恢复自动关联</Button>} />}
      {groupDraft && <Form layout="vertical"><Alert type="info" title={`本次修改影响同组 ${groupDraft.beat_ids.length} 个镜头`} /><Form.Item label="公共主体与声音设定"><Input.TextArea rows={5} value={groupDraft.common_prompt} onChange={e => setGroupDraft({ ...groupDraft, common_prompt: e.target.value })} /></Form.Item><Form.Item label="时间码模式"><Select value={groupDraft.timecode_mode || "per_shot"} onChange={v => setGroupDraft({ ...groupDraft, timecode_mode: v })} options={[{ value: "per_shot", label: "每镜从零（默认）" }, { value: "cumulative", label: "组内累计时间码" }]} /></Form.Item><Form.Item label={`最终视频参考（最多 ${mode?.max_references || 0} 张，按选择顺序编号）`}><Select mode="multiple" value={groupDraft.reference_slots.map(s => s.image_url)} maxCount={mode?.max_references || 0} options={[...assetRefs, ...groupDraft.reference_slots.filter(s => !assetRefs.some(a => a.image_url === s.image_url))].map(s => ({ value: s.image_url, label: s.name }))} onChange={urls => setGroupDraft({ ...groupDraft, reference_slots: urls.map((url, i) => ({ ...(assetRefs.find(s => s.image_url === url) || groupDraft.reference_slots.find(s => s.image_url === url))!, index: i + 1, token: `<Picture ${i + 1}>` })) })} /></Form.Item><Button onClick={() => navigate(`/director/projects/${projectId}/assets`)}>到资产库准备图片与造型</Button></Form>}
    </Modal>
  </div>
})
export default UnifiedWorkshopPane
