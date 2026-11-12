/**
 * 剧本工作台：一集的节点派生图 + 进度关卡 + 主线任务引导。
 *
 * 定位（docs/剧本工作台分析与优化方案.md）：运营驾驶舱 —— 业务数据实时派生自
 * GET /api/projects/:id/workbench，节点上只放快捷动作（生成指令 / 出片 / 跳工坊），
 * 拖拽布局存浏览器本地，不双写业务数据。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, Button, Drawer, Modal, Progress, Skeleton, Tooltip, message } from "antd"
import {
  Background,
  BackgroundVariant,
  MarkerType,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
  type NodeChange,
  type NodeTypes,
} from "@xyflow/react"
import { Crosshair, LayoutGrid, ListChecks, RotateCcw, Wand2 } from "lucide-react"

import {
  createAsset,
  director2ErrorDetail,
  generateAssetImage,
  generateBeatH3Prompt,
  generateBeatVideo,
  getEpisodeDetail,
  getWorkbench,
  getWorkbenchOverview,
  listAssets,
  listJobs,
  listWorkbenchEpisodes,
  retryJob,
  updateAsset,
  updateEpisodeBeat,
  type Director2Workbench,
  type Director2WorkbenchEpisodeOption,
} from "../api"
import { loadProgramPreview, buildVideoJobOptions, withVideoPromptMode, DIRECTOR2_DEFAULT_VIDEO_WORKFLOW } from "../director2-video-settings"
import { beatDurationSec } from "../workshop-beat-duration"
import {
  WORKSHOP_VIDEO_TERMINAL_STATUSES,
  mapWorkshopVideoProgress,
  isActiveWorkshopJobStatus,
} from "../workshop-video-progress"
import { ensureWorkshopShootReady, workshopShootPrepConfirmLines } from "../assistant/workshop-shoot-guard"
import {
  applyLiveBeatStatus,
  attentionBeats,
  buildWorkbenchGraph,
  loadWorkbenchLayout,
  overviewEpisodeBadge,
  retryableFailedJobIds,
  saveWorkbenchLayout,
  stageChips,
  stageChipLabel,
  workbenchLayoutKey,
} from "../workbench-graph"
import type { WorkbenchBeat, WorkbenchGraphNode, WorkbenchPosition } from "../workbench-graph"
import { WbAssetNodeView, WbBeatNodeView, WbEpisodeNodeView, WbScriptNodeView } from "./workbench-nodes"
import { director2ProjectPath, director2WorkshopEpisodePath } from "../paths"
import "../workbench.css"

const NODE_TYPES: NodeTypes = {
  "wb-script": WbScriptNodeView,
  "wb-asset": WbAssetNodeView,
  "wb-beat": WbBeatNodeView,
  "wb-episode": WbEpisodeNodeView,
}

type FlowNode = Node<Record<string, unknown>>

function nextActionButtonLabel(kind: string): string {
  switch (kind) {
    case "go-script": return "去剧本"
    case "fix-assets": return "去补素材"
    case "make-prompt": return "生成指令"
    case "wait": return "生成中…"
    case "confirm": return "去确认"
    case "render": return "开始出片"
    case "compose": return "去合成"
    case "go-episode": return "继续制作"
    default: return "去处理"
  }
}

export default function WorkbenchPane({ csrfToken, projectId, episodeId }: { csrfToken: string; projectId: string; episodeId: string | null }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [positions, setPositions] = useState<Record<string, WorkbenchPosition>>({})
  const [busyBeats, setBusyBeats] = useState<Record<string, boolean>>({})
  const [inspectId, setInspectId] = useState<string | null>(null)
  const [layoutEpoch, setLayoutEpoch] = useState(0)
  const seenTerminalJobs = useRef<Set<string>>(new Set())
  // 路由不带 episodeId = 项目总览模式（全部集进度卡），点集进入单集派生图。
  const isOverview = !episodeId

  const episodesQuery = useQuery({
    queryKey: ["workbench-episodes", projectId],
    queryFn: () => listWorkbenchEpisodes(projectId),
    staleTime: 30_000,
  })
  const episodeOptions: Director2WorkbenchEpisodeOption[] = episodesQuery.data?.episodes || []
  const activeEpisodeId = episodeId && episodeOptions.some(item => item.id === episodeId)
    ? episodeId
    : episodeId || ""

  const workbenchQuery = useQuery({
    queryKey: ["workbench", projectId, activeEpisodeId],
    queryFn: () => getWorkbench(projectId, activeEpisodeId),
    enabled: !isOverview && Boolean(activeEpisodeId),
  })
  const payload: Director2Workbench | undefined = workbenchQuery.data

  const overviewQuery = useQuery({
    queryKey: ["workbench-overview", projectId],
    queryFn: () => getWorkbenchOverview(projectId),
    enabled: isOverview,
    refetchInterval: 5000,
  })
  const overview = overviewQuery.data

  const jobsQuery = useQuery({
    queryKey: ["workbench-jobs", projectId],
    queryFn: () => listJobs(projectId),
    enabled: !isOverview && Boolean(activeEpisodeId),
    refetchInterval: (query) => {
      const jobs = query.state.data || []
      return jobs.some(job => isActiveWorkshopJobStatus(job.status)) ? 1500 : 5000
    },
  })
  const jobs = jobsQuery.data || []

  // 任何 h3 提示词 / 视频任务从进行中转为终态后，刷新派生图（成片地址、提示词就绪度）。
  useEffect(() => {
    if (!payload) return
    const activeIds = new Set(jobs.filter(job => isActiveWorkshopJobStatus(job.status)).map(job => String(job.id || "")))
    let changed = false
    for (const job of jobs) {
      const id = String(job.id || "")
      if (!id || activeIds.has(id) || seenTerminalJobs.current.has(id)) continue
      seenTerminalJobs.current.add(id)
      changed = true
    }
    if (changed) void queryClient.invalidateQueries({ queryKey: ["workbench", projectId] })
  }, [jobs, payload, projectId, queryClient])

  // 布局坐标：随分集切换读取本地保存的拖拽结果。
  useEffect(() => {
    if (!activeEpisodeId) return
    setPositions(loadWorkbenchLayout(projectId, activeEpisodeId))
  }, [activeEpisodeId, projectId, layoutEpoch])

  const liveBeats = useMemo(
    () => mapWorkshopVideoProgress(jobs, activeEpisodeId).beats,
    [jobs, activeEpisodeId],
  )
  const beats = useMemo(
    () => applyLiveBeatStatus(payload?.beats || [], liveBeats),
    [payload?.beats, liveBeats],
  )

  const persistPositions = useCallback((next: Record<string, WorkbenchPosition>) => {
    if (activeEpisodeId) saveWorkbenchLayout(projectId, activeEpisodeId, next)
  }, [activeEpisodeId, projectId])

  const onNodesChange = useCallback((changes: NodeChange<FlowNode>[]) => {
    const moves = changes.filter(change => change.type === "position" && change.position)
    if (!moves.length) return
    setPositions(previous => {
      const next = { ...previous }
      for (const change of moves) {
        if (change.type === "position" && change.position) next[change.id] = { x: change.position.x, y: change.position.y }
      }
      return next
    })
  }, [])

  const onNodeDragStop = useCallback(() => {
    // 拖拽结束时以最新 positions 落盘（positions state 与拖拽同步更新）。
    setPositions(current => { persistPositions(current); return current })
  }, [persistPositions])

  const setBeatBusy = (beatId: string, busy: boolean) => setBusyBeats(previous => ({ ...previous, [beatId]: busy }))

  const refreshWorkbench = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["workbench", projectId] })
    void queryClient.invalidateQueries({ queryKey: ["workbench-jobs", projectId] })
  }, [projectId, queryClient])

  const handleGeneratePrompt = useCallback(async (beatId: string) => {
    if (!activeEpisodeId || busyBeats[beatId]) return
    setBeatBusy(beatId, true)
    try {
      const result = await generateBeatH3Prompt(csrfToken, projectId, activeEpisodeId, beatId, {})
      if (result.prompt) { message.success("生成指令已就绪"); refreshWorkbench() }
      else message.loading({ content: "正在整理本镜生成指令…", key: `wbPrompt-${beatId}`, duration: 4 })
      void queryClient.invalidateQueries({ queryKey: ["workbench-jobs", projectId] })
    } catch (error) {
      message.error(director2ErrorDetail(error, "生成指令任务创建失败"))
    } finally { setBeatBusy(beatId, false) }
  }, [activeEpisodeId, busyBeats, csrfToken, projectId, queryClient, refreshWorkbench])

  const handleRender = useCallback(async (beatId: string) => {
    if (!activeEpisodeId || busyBeats[beatId]) return
    setBeatBusy(beatId, true)
    try {
      const [detail, assets] = await Promise.all([getEpisodeDetail(projectId, activeEpisodeId), listAssets(projectId)])
      const guard = await ensureWorkshopShootReady({
        projectId,
        episodeId: activeEpisodeId,
        beats: detail.beats || [],
        assets,
        scopeBeatIds: [beatId],
        api: {
          createAsset: (pid, data) => createAsset(csrfToken, pid, data),
          updateAsset: (pid, assetId, data) => updateAsset(csrfToken, pid, assetId, data),
          updateEpisodeBeat: (pid, eid, beatId2, patch) => updateEpisodeBeat(csrfToken, pid, eid, beatId2, patch),
          generateAssetImage: (pid, assetId, data) => generateAssetImage(csrfToken, pid, assetId, data),
          getEpisodeDetail,
          listAssets,
        },
        confirm: (plan, paid) => new Promise<boolean>(resolve => {
          Modal.confirm({
            title: paid ? "补齐出片素材后自动生成？" : "自动补齐出片前置后继续？",
            content: <div>{workshopShootPrepConfirmLines(plan, paid).map(line => <p key={line} style={{ margin: "0 0 4px" }}>{line}</p>)}</div>,
            okText: paid ? "补齐并生成" : "自动补齐并生成",
            cancelText: "取消",
            centered: true,
            onOk: () => resolve(true),
            onCancel: () => resolve(false),
          })
        }),
        onProgress: item => message.loading({
          content: `正在自动补齐素材（${item.phase === "scene" ? "场景" : "造型"} ${item.index}/${item.total}）：${item.label}`,
          key: "wbPrep",
          duration: 0,
        }),
      })
      message.destroy("wbPrep")
      if (guard.status === "cancelled") return
      if (guard.status === "blocked") { message.error({ content: guard.message, duration: 10 }); return }
      const beat = beats.find(item => item.id === beatId)
      const options = withVideoPromptMode(
        buildVideoJobOptions(DIRECTOR2_DEFAULT_VIDEO_WORKFLOW, {}, { duration_per_beat: beatDurationSec(beat?.video_duration || "") }),
        loadProgramPreview(projectId),
      )
      const res = await generateBeatVideo(csrfToken, projectId, activeEpisodeId, beatId, options)
      message.success({ content: "已提交出片，可在节点上看到进度", duration: 4 })
      void queryClient.invalidateQueries({ queryKey: ["workbench-jobs", projectId] })
      if (res.job_id) seenTerminalJobs.current.delete(res.job_id)
    } catch (error) {
      message.error(director2ErrorDetail(error, "出片任务创建失败"))
    } finally { setBeatBusy(beatId, false) }
  }, [activeEpisodeId, beats, busyBeats, csrfToken, projectId, queryClient])

  // 节点图派生：图结构与布局保持纯函数；回调（快捷动作/查看详情）在这一层注入节点 data。
  const flow = useMemo(() => {
    if (!payload) return { nodes: [] as FlowNode[], edges: [] as Edge[] }
    const graph = buildWorkbenchGraph({ ...payload, beats }, positions)
    const nodes = graph.nodes.map(node => {
      if (node.type === "wb-beat") {
        const beatId = String((node.data as { beat?: WorkbenchBeat }).beat?.id || "")
        return {
          ...node,
          data: {
            ...node.data,
            busy: Boolean(busyBeats[beatId]),
            onGeneratePrompt: (id: string) => void handleGeneratePrompt(id),
            onRender: (id: string) => void handleRender(id),
            onOpenWorkshop: () => navigate(director2WorkshopEpisodePath(projectId, activeEpisodeId)),
            onInspect: (id: string) => setInspectId(id),
          },
        }
      }
      if (node.type === "wb-script") {
        return { ...node, data: { ...node.data, onGoContent: () => navigate(director2ProjectPath(projectId, "content")) } }
      }
      if (node.type === "wb-episode") {
        return { ...node, data: { ...node.data, onCompose: () => navigate(director2ProjectPath(projectId, "edit", activeEpisodeId)) } }
      }
      return { ...node }
    })
    return {
      nodes: nodes as unknown as FlowNode[],
      edges: graph.edges.map(edge => ({
        ...edge,
        markerEnd: edge.kind === "reference" ? undefined : { type: MarkerType.ArrowClosed, width: 14, height: 14 },
      })) as Edge[],
    }
  }, [payload, beats, positions, busyBeats, activeEpisodeId, handleGeneratePrompt, handleRender, navigate, projectId])

  const overviewAction = overview?.next_action
  const handleNextAction = useCallback(() => {
    const action = isOverview ? overviewAction : payload?.next_action
    if (!action) return
    if (action.kind === "go-script") { navigate(director2ProjectPath(projectId, "content")); return }
    if (action.kind === "fix-assets") { navigate(director2ProjectPath(projectId, "assets")); return }
    if (action.kind === "confirm") { navigate(director2WorkshopEpisodePath(projectId, isOverview ? String(action.episode_id || "") : activeEpisodeId)); return }
    if (action.kind === "go-episode" && action.episode_id) { navigate(director2ProjectPath(projectId, "workbench", String(action.episode_id))); return }
    if (action.kind === "compose") { navigate(director2ProjectPath(projectId, "edit", isOverview ? String(action.episode_id || "") : activeEpisodeId)); return }
    if (action.kind === "make-prompt" && action.beat_id) { void handleGeneratePrompt(action.beat_id); return }
    if (action.kind === "render" && action.beat_id) { void handleRender(action.beat_id); return }
    // wait：不需要动作
  }, [activeEpisodeId, handleGeneratePrompt, handleRender, isOverview, navigate, overviewAction, payload, projectId])

  const resetLayout = () => {
    // 先清掉本地保存的坐标再复位，否则下次 effect 又会读回旧布局。
    if (activeEpisodeId) {
      try { window.localStorage.removeItem(workbenchLayoutKey(projectId, activeEpisodeId)) } catch { /* 隐私模式忽略 */ }
    }
    setPositions({})
    setLayoutEpoch(value => value + 1)
    message.success("已恢复默认布局")
  }

  const handleRetryFailed = useCallback(async (failedBeatIds: string[]) => {
    const jobIds = retryableFailedJobIds(jobs, failedBeatIds)
    if (!jobIds.length) {
      message.info("这些镜头没有可续跑的失败任务，请直接用镜头上的「重拍」")
      return
    }
    let ok = 0
    for (const jobId of jobIds) {
      try {
        await retryJob(csrfToken, projectId, jobId)
        seenTerminalJobs.current.delete(jobId)
        ok += 1
      } catch (error) {
        message.error(director2ErrorDetail(error, "其中一个失败任务重试失败"))
      }
    }
    if (ok) {
      message.success(`已续跑 ${ok} 个失败任务（复用已完成的准备步骤）`)
      void queryClient.invalidateQueries({ queryKey: ["workbench-jobs", projectId] })
    }
  }, [csrfToken, jobs, projectId, queryClient])

  const inspectedBeat: WorkbenchBeat | null = inspectId ? beats.find(item => item.id === inspectId) || null : null
  const stages = stageChips(payload?.progress)
  const nextAction = isOverview ? overview?.next_action : payload?.next_action
  const overallPct = isOverview ? overview?.project_progress.overall_pct ?? 0 : payload?.progress.overall_pct ?? 0
  const overallLabel = isOverview ? "项目进度" : "本集进度"

  // ---- 项目总览模式：全部集进度卡 ----
  if (isOverview) {
    if (overviewQuery.isLoading) {
      return <div className="wb-pane"><div className="wb-loading"><Skeleton active paragraph={{ rows: 5 }} /></div></div>
    }
    if (overviewQuery.isError || !overview) {
      return <div className="wb-pane"><Alert type="error" showIcon title="工作台总览加载失败"
        action={<Button size="small" onClick={() => void overviewQuery.refetch()}>重试</Button>} /></div>
    }
    return <div className="wb-pane">
      <header className="wb-topbar">
        <div className="wb-topbar-main">
          <span className="wb-stage is-done" role="note"><i className="wb-stage-dot" />全部集 {overview.project_progress.episodes_total} 集</span>
          <div className="wb-overall">
            <span className="wb-overall-label">{overallLabel}</span>
            <Progress percent={overallPct} size={{ width: 132, height: 6 }} showInfo={false} />
            <span className="wb-overall-value">{overallPct}%</span>
          </div>
        </div>
        <div className="wb-topbar-side">
          {nextAction && <div className={`wb-quest is-${nextAction.kind}`}>
            <span className="wb-quest-tag">下一步</span>
            <span className="wb-quest-label">{nextAction.label}</span>
            <Button size="small" type={nextAction.kind === "wait" ? "default" : "primary"} disabled={nextAction.kind === "wait"}
              icon={nextAction.kind === "wait" ? undefined : <ListChecks size={12} />}
              onClick={handleNextAction}>{nextActionButtonLabel(nextAction.kind)}</Button>
          </div>}
        </div>
      </header>
      <div className="wb-overview-body">
        {overview.episodes.length === 0 && <div className="wb-empty">
          <LayoutGrid size={26} />
          <h2>还没有分集</h2>
          <p>先在「剧本」阶段完成拆解并同步到分镜，这里会按集展示进度。</p>
          <Button type="primary" onClick={() => navigate(director2ProjectPath(projectId, "content"))}>去剧本阶段</Button>
        </div>}
        <div className="wb-overview-grid">
          {overview.episodes.map(episode => {
            const badge = overviewEpisodeBadge(episode)
            return (
              <button key={episode.id} type="button" className="wb-ov-card" onClick={() => navigate(director2ProjectPath(projectId, "workbench", episode.id))}>
                <header className="wb-ov-head">
                  <span className="wb-ov-num">第 {episode.number} 集</span>
                  <strong className="wb-ov-title">{episode.title}</strong>
                  <span className={`wb-lamp is-${badge.tone}`}><i />{badge.label}</span>
                </header>
                <Progress percent={episode.overall_pct} size={{ width: 236, height: 6 }} showInfo={false} />
                <footer className="wb-ov-foot">
                  <span>指令 {episode.prompts_done}/{episode.beats_total}</span>
                  <span>出片 {episode.shots_done}/{episode.beats_total}</span>
                  {episode.episode_video_url ? <span className="wb-ov-cut">有整集成片</span> : null}
                </footer>
              </button>
            )
          })}
        </div>
      </div>
    </div>
  }

  if (!activeEpisodeId && episodesQuery.isSuccess) {
    return <div className="wb-pane"><div className="wb-empty">
      <LayoutGrid size={26} />
      <h2>还没有可上映射的分集</h2>
      <p>先在「剧本」阶段完成拆解并同步到分镜，工作台会把镜头串成一张节点图。</p>
      <Button type="primary" onClick={() => navigate(director2ProjectPath(projectId, "content"))}>去剧本阶段</Button>
    </div></div>
  }
  if (workbenchQuery.isLoading || (!payload && workbenchQuery.isEnabled)) {
    return <div className="wb-pane"><div className="wb-loading"><Skeleton active paragraph={{ rows: 5 }} /></div></div>
  }
  if (workbenchQuery.isError || !payload) {
    return <div className="wb-pane"><Alert type="error" showIcon title="工作台加载失败"
      description="可能是分集还没就绪，稍后重试。"
      action={<Button size="small" onClick={() => void workbenchQuery.refetch()}>重试</Button>} /></div>
  }

  return <div className="wb-pane">
    <header className="wb-topbar">
      <div className="wb-topbar-main">
        <div className="wb-stages" role="list" aria-label="本集进度关卡">
          {stages.map(stage => (
            <span key={stage.key} role="listitem" className={`wb-stage is-${stage.status}`} title={stageChipLabel(stage)}>
              <i className="wb-stage-dot" />{stageChipLabel(stage)}
            </span>
          ))}
        </div>
        <div className="wb-overall">
          <span className="wb-overall-label">{overallLabel}</span>
          <Progress percent={overallPct} size={{ width: 132, height: 6 }} showInfo={false} />
          <span className="wb-overall-value">{overallPct}%</span>
        </div>
      </div>
      <div className="wb-topbar-side">
        {nextAction && <div className={`wb-quest is-${nextAction.kind}`}>
          <span className="wb-quest-tag">下一步</span>
          <span className="wb-quest-label">{nextAction.label}</span>
          <Button size="small" type={nextAction.kind === "wait" ? "default" : "primary"} disabled={nextAction.kind === "wait"}
            icon={nextAction.kind === "wait" ? undefined : (nextAction.kind === "go-script" || nextAction.kind === "fix-assets" ? <Crosshair size={12} /> : <ListChecks size={12} />)}
            onClick={handleNextAction}>{nextActionButtonLabel(nextAction.kind)}</Button>
        </div>}
        <Tooltip title="恢复默认布局"><Button type="text" aria-label="恢复默认布局" icon={<RotateCcw size={14} />} onClick={resetLayout} /></Tooltip>
      </div>
    </header>
    <nav className="wb-episodes" aria-label="切换分集">
      <button type="button" className={`wb-episode-chip${isOverview ? " is-active" : ""}`}
        onClick={() => navigate(director2ProjectPath(projectId, "workbench"))}>
        全部集<span>{episodeOptions.length} 集</span>
      </button>
      {episodeOptions.length > 0 && episodeOptions.map(option => (
        <button key={option.id} type="button"
          className={`wb-episode-chip${option.id === activeEpisodeId ? " is-active" : ""}`}
          onClick={() => navigate(director2ProjectPath(projectId, "workbench", option.id))}>
          第 {option.number} 集<span>{option.shots_count} 镜</span>
        </button>
      ))}
    </nav>
    {(() => {
      const attention = attentionBeats(beats)
      if (!attention.length) return null
      const failedBeatIds = attention.filter(item => item.reason === "failed").map(item => item.beat.id)
      return <div className="wb-attention" role="list" aria-label="待办镜头">
        <span className="wb-attention-label"><ListChecks size={12} /> 待办镜头</span>
        {attention.map(({ beat, reason }) => (
          <button key={`${reason}-${beat.id}`} type="button" role="listitem"
            className={`wb-attention-chip is-${reason}`}
            onClick={() => setInspectId(beat.id)}>
            第 {beat.sequence} 镜 · {reason === "awaiting_refine" ? "待确认一采" : "出片失败，可重拍"}
          </button>
        ))}
        {failedBeatIds.length > 0 && <Button size="small" className="wb-attention-retry"
          icon={<Wand2 size={11} />}
          onClick={() => void handleRetryFailed(failedBeatIds)}>一键续跑失败镜头（{failedBeatIds.length}）</Button>}
      </div>
    })()}
    <div className="wb-stage-area">
      <ReactFlowProvider>
        <ReactFlow
          key={`${activeEpisodeId}:${payload.beats.length > 0 ? "ready" : "empty"}`}
          nodes={flow.nodes}
          edges={flow.edges}
          nodeTypes={NODE_TYPES}
          onNodesChange={onNodesChange}
          onNodeDragStop={onNodeDragStop}
          nodesConnectable={false}
          elementsSelectable={false}
          edgesFocusable={false}
          edgesReconnectable={false}
          zoomOnDoubleClick={false}
          deleteKeyCode={null}
          minZoom={0.1}
          maxZoom={1.5}
          fitView
          fitViewOptions={{ padding: 0.14, maxZoom: 0.9 }}
          panOnDrag
          zoomOnScroll
          preventScrolling
        >
          <Background variant={BackgroundVariant.Dots} gap={26} size={2} color="var(--wb-grid-dot)" />
        </ReactFlow>
      </ReactFlowProvider>
      {payload.beats.length === 0 && <div className="wb-stage-hint">本集还没有分镜 —— 在「剧本」阶段完成拆解后，这里会把镜头串成节点链。</div>}
    </div>
    <Drawer open={Boolean(inspectedBeat)} onClose={() => setInspectId(null)} width={420} title={inspectedBeat ? `第 ${inspectedBeat.sequence} 镜 · ${inspectedBeat.heading || inspectedBeat.title}` : "镜头详情"}
      rootClassName="wb-drawer">
      {inspectedBeat && <div className="wb-detail">
        {inspectedBeat.video_url && <video className="wb-detail-video" src={inspectedBeat.video_url} controls muted preload="metadata" />}
        <dl className="wb-detail-rows">
          {inspectedBeat.speaker && <><dt>说话人</dt><dd>{inspectedBeat.speaker}</dd></>}
          {inspectedBeat.dialogue && <><dt>台词</dt><dd>{inspectedBeat.dialogue}</dd></>}
          {inspectedBeat.text && <><dt>动作</dt><dd>{inspectedBeat.text}</dd></>}
          <dt>生成指令</dt><dd>{inspectedBeat.has_prompt ? "H3 指令已就绪" : "还没生成 H3 指令"}</dd>
          <dt>时长</dt><dd>{inspectedBeat.video_duration ? `${inspectedBeat.video_duration}s` : "自动"}</dd>
        </dl>
        <div className="wb-detail-actions">
          <Button icon={<Wand2 size={13} />} loading={Boolean(busyBeats[inspectedBeat.id])}
            onClick={() => void handleGeneratePrompt(inspectedBeat.id)}>{inspectedBeat.has_prompt ? "重新生成指令" : "生成 H3 指令"}</Button>
          <Button type="primary" loading={Boolean(busyBeats[inspectedBeat.id])} onClick={() => void handleRender(inspectedBeat.id)}>
            {inspectedBeat.has_video ? "重拍本镜" : "出片本镜"}
          </Button>
          <Button onClick={() => { setInspectId(null); navigate(director2WorkshopEpisodePath(projectId, activeEpisodeId)) }}>在工坊打开</Button>
        </div>
      </div>}
    </Drawer>
  </div>
}
