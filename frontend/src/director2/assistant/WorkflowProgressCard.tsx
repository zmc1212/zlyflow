import { useCallback, useEffect, useRef, useState, type ReactNode } from "react"
import { Button, Modal, Spin, Steps, Tooltip, message } from "antd"
import { ArrowRight, RefreshCw, Route, Video } from "lucide-react"
import { createAsset, director2ErrorDetail, enqueueDocumentShotPlan, generateAssetImage, generateBeatH3Prompt, generateBeatVideo, getEpisodeDetail, listAssets, listDocuments, listEpisodes, listJobs, listVideoWorkflowModes, transferEpisodesFromDoc, updateAsset, updateEpisodeBeat } from "../api"
import { beatHasVideo, loadSavedVideoSettings, refineForceWarning } from "../director2-video-settings"
import { projectVideoResolution } from "../project-video-resolution"
import { beatDurationSec } from "../workshop-beat-duration"
import { episodeShootOptions, episodeShotTaskConfirmLines, resolveEpisodeShootPlan } from "./episode-shoot"
import { episodeShootPrepLines, episodeShootPrepSummary, evaluateEpisodeShootPreflight, hasPaidShootPrep, type EpisodeShootPreflight } from "./episode-shoot-preflight"
import { formatShootPrepElapsed, prepareEpisodeShootAssets, type ShootPrepProgress } from "./episode-shoot-prep"
import { activeEpisodeVideoJobs, ensureEpisodeShotPrompts, submitEpisodeShotTasks, type ShotPromptPrepProgress, type ShotTaskProgress } from "./episode-shot-tasks"
import { assetDraftPrompt, buildWorkflowProgress, type WorkflowAction, type WorkflowProgress } from "./workflow-progress"

function confirmShoot(content: ReactNode, options: { title?: string; okText?: string } = {}): Promise<boolean> {
  return new Promise((resolve) => {
    Modal.confirm({
      title: options.title || "确认提交分段出片？",
      content,
      width: 460,
      centered: true,
      okText: options.okText || "确认出片",
      cancelText: "取消",
      onOk: () => resolve(true),
      onCancel: () => resolve(false),
    })
  })
}

function warnShootBlocked(blocking: string[], episodeLabel: string): Promise<boolean> {
  return new Promise((resolve) => {
    Modal.confirm({
      title: "出片前置还需要处理",
      width: 520,
      centered: true,
      content: <div className="assistant-shoot-confirm">
        <p>{episodeLabel || "当前分集"}还不能提交分段出片：</p>
        {blocking.slice(0, 8).map((item) => <p key={item}>· {item}</p>)}
        {blocking.length > 8 ? <p>…等 {blocking.length} 项</p> : null}
        <p>请到工坊镜头检视器补齐后重试。</p>
      </div>,
      okText: "去工坊处理",
      cancelText: "取消",
      onOk: () => resolve(true),
      onCancel: () => resolve(false),
    })
  })
}

export default function WorkflowProgressCard({
  projectId,
  csrfToken,
  open,
  busy,
  canPrompt,
  onPrompt,
  onNavigate,
}: {
  projectId: string
  csrfToken: string
  open: boolean
  busy: boolean
  canPrompt: boolean
  onPrompt: (text: string) => void
  onNavigate: (menu: "content" | "workshop", episodeId?: string) => void
}) {
  const [progress, setProgress] = useState<WorkflowProgress | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [acting, setActing] = useState(false)
  const [preflight, setPreflight] = useState<EpisodeShootPreflight | null>(null)
  const [preflightEpisodeId, setPreflightEpisodeId] = useState("")
  const [prepProgress, setPrepProgress] = useState<ShootPrepProgress | null>(null)
  const [prepStartedAt, setPrepStartedAt] = useState(0)
  const [prepFailure, setPrepFailure] = useState("")
  const [shotProgress, setShotProgress] = useState<ShotTaskProgress | null>(null)
  const [shotFailure, setShotFailure] = useState<{ submitted: number; lines: string[] } | null>(null)
  const [promptProgress, setPromptProgress] = useState<ShotPromptPrepProgress | null>(null)
  const [promptFailure, setPromptFailure] = useState<{ prepared: number; lines: string[] } | null>(null)
  const [, setPrepTick] = useState(0)
  const shootLock = useRef(false)
  const shotSubmitted = useRef(new Set<string>())
  const generation = useRef(0)
  const preflightGeneration = useRef(0)

  const load = useCallback(async (silent = false) => {
    const current = ++generation.current
    if (!silent) setLoading(true)
    try {
      const [documents, assets, episodes] = await Promise.all([
        listDocuments(projectId),
        listAssets(projectId),
        listEpisodes(projectId),
      ])
      if (generation.current !== current) return
      setProgress(buildWorkflowProgress({ documents, assets, episodes }))
      setError("")
    } catch (e) {
      if (generation.current === current) setError(director2ErrorDetail(e, "读取创作流程失败"))
    } finally {
      if (generation.current === current) setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    setProgress(null)
    setError("")
    generation.current += 1
  }, [projectId])

  const actionEpisodeId = progress?.action?.kind === "open-workshop" ? String(progress.action.episodeId || "") : ""
  useEffect(() => {
    shotSubmitted.current.clear()
    setShotFailure(null)
    setShotProgress(null)
    setPromptProgress(null)
    setPromptFailure(null)
  }, [projectId, actionEpisodeId])

  useEffect(() => {
    if (!open) return
    void load()
  }, [open, projectId, load])

  useEffect(() => {
    if (!open) return
    function refresh(event: Event) {
      if (String((event as CustomEvent).detail?.projectId || "") !== projectId) return
      void load(true)
    }
    window.addEventListener("director-assistant-project-updated", refresh)
    return () => window.removeEventListener("director-assistant-project-updated", refresh)
  }, [open, projectId, load])

  const planning = !!progress && progress.steps.some(step => step.running)
  useEffect(() => {
    if (!open || !planning) return
    const timer = window.setInterval(() => { void load(true) }, 4000)
    return () => window.clearInterval(timer)
  }, [open, planning, load])

  useEffect(() => {
    if (!prepProgress) return
    const timer = window.setInterval(() => setPrepTick((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [prepProgress])

  useEffect(() => {
    const action = progress?.action
    const episodeId = action?.kind === "open-workshop" && action.episodeShots ? String(action.episodeId || "") : ""
    const current = ++preflightGeneration.current
    if (!open || !episodeId) {
      setPreflight(null)
      setPreflightEpisodeId("")
      return
    }
    void (async () => {
      try {
        const [detail, assets] = await Promise.all([
          getEpisodeDetail(projectId, episodeId),
          listAssets(projectId),
        ])
        if (preflightGeneration.current !== current) return
        setPreflight(evaluateEpisodeShootPreflight({ beats: detail.beats || [], assets }))
        setPreflightEpisodeId(episodeId)
      } catch {
        if (preflightGeneration.current === current) {
          setPreflight(null)
          setPreflightEpisodeId("")
        }
      }
    })()
    return () => { preflightGeneration.current += 1 }
  }, [open, projectId, progress])

  async function shootEpisode(action: WorkflowAction) {
    const episodeId = action.episodeId
    if (!episodeId || !action.episodeShots) { onNavigate("workshop", episodeId); return }
    if (shootLock.current) return
    shootLock.current = true
    setActing(true)
    try {
      const [modes, detail, resolution, assets, jobs] = await Promise.all([
        listVideoWorkflowModes().then((payload) => payload.modes || []).catch(() => []),
        getEpisodeDetail(projectId, episodeId),
        projectVideoResolution(projectId),
        listAssets(projectId),
        listJobs(projectId),
      ])
      let beats = detail.beats || []
      if (!beats.length) {
        message.warning("这一集还没有可出片的分镜")
        onNavigate("workshop", episodeId)
        return
      }
      const maxShotDurationSec = Math.max(0, ...beats.map((beat) => beatDurationSec(beat.video_duration)))
      const plan = resolveEpisodeShootPlan(modes, loadSavedVideoSettings(projectId), resolution?.value)
      let activity = activeEpisodeVideoJobs(jobs, episodeId)
      if (activity.blockingJobId) {
        message.warning({
          content: `该分集已有进行中的整集任务 ${activity.blockingJobId}，请等待完成后再提交分段任务`,
          duration: 8,
        })
        return
      }
      const shotTargets = beats.filter((beat) => {
        const id = String(beat.id || "")
        return !!id && !shotSubmitted.current.has(id) && !activity.activeBeatIds.includes(id) && !beatHasVideo(beat)
      })
      if (!shotTargets.length) {
        message.warning("所有镜头都已有成片或正在生成，请到工坊逐镜查看")
        onNavigate("workshop", episodeId)
        return
      }
      const episodeLabel = progress?.workshop.episodeLabel || ""
      const check = evaluateEpisodeShootPreflight({ beats, assets })
      if (!check.ready && !check.canFix) {
        const goWorkshop = await warnShootBlocked(check.blocking, episodeLabel)
        if (goWorkshop) onNavigate("workshop", episodeId)
        return
      }
      const prepLines = episodeShootPrepLines(check)
      const paidPrep = hasPaidShootPrep(check)
      const warning = refineForceWarning(plan.values, maxShotDurationSec)
      const promptPrepCount = shotTargets.filter((beat) => !String(beat.h3_prompt || "").trim()).length
      const videoLines = episodeShotTaskConfirmLines({
        episodeLabel,
        shotCount: shotTargets.length,
        maxShotDurationSec,
        plan,
      })
      const confirmed = await confirmShoot(<div className="assistant-shoot-confirm">
        {prepLines.map((line) => <p key={line}>{line}</p>)}
        {videoLines.map((line) => <p key={line}>{line}</p>)}
        {promptPrepCount ? <p>其中 {promptPrepCount} 个镜头缺少 H3 提示词，提交视频任务前会先调用大模型生成官方六段式提示词。</p> : null}
        {warning ? <p className="is-warning">{warning}</p> : null}
        <p>{paidPrep
          ? `补齐素材会调用生图模型，每张约 1-3 分钟；确认后会创建 ${shotTargets.length} 个逐镜视频任务并排队执行。`
          : `将创建 ${shotTargets.length} 个逐镜视频任务并排队执行，可在「全部任务 → 视频生成」分别查看。`}</p>
      </div>, {
        title: paidPrep ? "补齐素材并分段出片？" : "确认提交分段出片？",
        okText: paidPrep ? "补齐并提交" : `提交 ${shotTargets.length} 个任务`,
      })
      if (!confirmed) return
      let generated = 0
      if (!check.ready) {
        setPrepFailure("")
        setPrepStartedAt(Date.now())
        const prepared = await prepareEpisodeShootAssets({
          projectId,
          episodeId,
          beats,
          assets,
          plan: check,
          api: {
            createAsset: (pid, data) => createAsset(csrfToken, pid, data),
            updateAsset: (pid, assetId, data) => updateAsset(csrfToken, pid, assetId, data),
            updateEpisodeBeat: (pid, eid, beatId, patch) => updateEpisodeBeat(csrfToken, pid, eid, beatId, patch),
            generateAssetImage: (pid, assetId, data) => generateAssetImage(csrfToken, pid, assetId, data),
            getEpisodeDetail,
            listAssets,
          },
          onProgress: (next) => setPrepProgress(next),
        })
        setPrepProgress(null)
        generated = prepared.generated
        if (!prepared.ok) {
          const detail = prepared.message || "补齐出片素材失败"
          setPrepFailure(detail)
          message.error({ content: detail, duration: 10 })
          window.dispatchEvent(new CustomEvent("director-assistant-project-updated", { detail: { projectId } }))
          await load(true)
          return
        }
        setPrepFailure("")
      }
      const [freshDetail, freshJobs] = await Promise.all([
        getEpisodeDetail(projectId, episodeId),
        listJobs(projectId),
      ])
      beats = freshDetail.beats || beats
      activity = activeEpisodeVideoJobs(freshJobs, episodeId)
      if (activity.blockingJobId) {
        message.warning({
          content: `该分集刚刚开始了一个整集任务 ${activity.blockingJobId}，请等待完成后再提交分段任务`,
          duration: 8,
        })
        return
      }
      const remaining = beats.filter((beat) => {
        const id = String(beat.id || "")
        return !!id && !shotSubmitted.current.has(id) && !activity.activeBeatIds.includes(id) && !beatHasVideo(beat)
      })
      if (!remaining.length) {
        message.warning("提交前检查发现所有镜头都已有成片或正在生成，请到工坊逐镜查看")
        onNavigate("workshop", episodeId)
        return
      }
      setShotFailure(null)
      setPromptFailure(null)
      const promptPrep = await ensureEpisodeShotPrompts({
        beats: remaining,
        skipBeatIds: shotSubmitted.current,
        api: {
          generateBeatPrompt: (beatId) => generateBeatH3Prompt(csrfToken, projectId, episodeId, beatId, {}),
          listJobs: () => listJobs(projectId),
        },
        onProgress: setPromptProgress,
      })
      setPromptProgress(null)
      if (!promptPrep.ok) {
        const lines = promptPrep.failures.map((item) => `Beat ${item.sequence || "?"}：${item.message}`)
        setPromptFailure({ prepared: promptPrep.prepared, lines })
        message.error({
          content: `H3 提示词准备失败：${lines.slice(0, 3).join("；")}${lines.length > 3 ? " …" : ""}；视频任务尚未提交，再次点击只重试缺少的提示词`,
          duration: 10,
        })
        await load(true)
        return
      }
      if (promptPrep.prepared) {
        beats = (await getEpisodeDetail(projectId, episodeId)).beats || beats
      }
      const submitted = await submitEpisodeShotTasks({
        beats,
        options: episodeShootOptions(plan),
        skipBeatIds: shotSubmitted.current,
        inFlightBeatIds: activity.activeBeatIds,
        api: {
          generateBeatVideo: (beatId, data) => generateBeatVideo(csrfToken, projectId, episodeId, beatId, data),
        },
        onProgress: setShotProgress,
      })
      setShotProgress(null)
      for (const beatId of submitted.submittedBeatIds) shotSubmitted.current.add(beatId)
      if (submitted.submitted) {
        window.dispatchEvent(new CustomEvent("director-assistant-project-updated", { detail: { projectId } }))
      }
      if (submitted.failures.length) {
        const lines = submitted.failures.map((item) => `Beat ${item.sequence}：${item.message}`)
        setShotFailure({ submitted: submitted.submitted, lines })
        message.error({
          content: `已提交 ${submitted.submitted} 个逐镜任务，${submitted.failures.length} 个提交失败；再次点击只重试失败的镜头`,
          duration: 10,
        })
        if (submitted.submitted) await load(true)
        return
      }
      if (!submitted.submitted) {
        message.warning("没有可提交的镜头，可能都已有成片或正在生成")
        onNavigate("workshop", episodeId)
        return
      }
      message.success({
        content: `${generated ? `已补齐 ${generated} 张素材，` : ""}已提交 ${submitted.submitted} 个逐镜任务${submitted.skipped ? `（跳过 ${submitted.skipped} 个已有成片或进行中的镜头）` : ""}，可在工坊分别查看`,
        duration: 8,
      })
      shotSubmitted.current.clear()
      onNavigate("workshop", episodeId)
    } catch (e) {
      message.error({ content: director2ErrorDetail(e, "分段出片失败"), duration: 10 })
    } finally {
      shootLock.current = false
      setPrepProgress(null)
      setPromptProgress(null)
      setShotProgress(null)
      setActing(false)
    }
  }

  async function runAction() {
    if (!progress || acting) return
    const action = progress.action
    if (action.kind === "import-script" || action.kind === "check-script") { onNavigate("content"); return }
    if (action.kind === "open-workshop") { await shootEpisode(action); return }
    if (action.kind === "draft-assets") { onPrompt(assetDraftPrompt(progress.document?.filename)); return }
    if (action.kind === "planning" || !action.documentId) return
    setActing(true)
    try {
      if (action.kind === "plan-shots") {
        await enqueueDocumentShotPlan(csrfToken, projectId, action.documentId)
        message.success("已开始规划出片镜头，完成后这里会自动更新")
      } else {
        const result = await transferEpisodesFromDoc(csrfToken, projectId, action.documentId, "overwrite")
        const count = Number(result.created || 0) + Number(result.replaced || 0)
        message.success(count ? `已同步 ${count} 集到剧集工坊` : "已同步到剧集工坊")
        onNavigate("workshop")
      }
      window.dispatchEvent(new CustomEvent("director-assistant-project-updated", { detail: { projectId } }))
      await load(true)
    } catch (e) {
      message.error(director2ErrorDetail(e, action.kind === "plan-shots" ? "启动镜头规划失败" : "同步到剧集工坊失败"))
    } finally {
      setActing(false)
    }
  }

  const action = progress?.action
  const waiting = action?.kind === "planning"
  const actionLoading = acting || waiting
  const shootReady = !!action?.episodeShots
  const shootEpisodeId = action?.kind === "open-workshop" && shootReady ? String(action.episodeId || "") : ""
  const shootCheck = preflight && preflightEpisodeId === shootEpisodeId ? preflight : null
  const shootPrepNeeded = !!shootCheck && !shootCheck.ready
  const prepElapsed = prepProgress && prepStartedAt ? Math.max(0, Math.floor((Date.now() - prepStartedAt) / 1000)) : 0
  const prepPhaseLabel = prepProgress?.phase === "scene" ? "场景主视图" : "角色造型"
  const actionTitle = prepProgress
    ? "正在补齐出片素材"
    : promptProgress
      ? "正在准备 H3 提示词"
      : shotProgress
        ? "正在提交逐镜任务"
        : shootPrepNeeded
          ? (shootCheck.canFix ? "补齐出片素材" : "出片前置需要处理")
          : action?.title || ""
  const actionDetail = prepProgress
    ? `正在生成${prepPhaseLabel} ${prepProgress.index}/${prepProgress.total}：${prepProgress.label} · 已等待 ${formatShootPrepElapsed(prepElapsed)}`
    : promptProgress
      ? promptProgress.phase === "wait"
        ? `正在等待 H3 提示词生成 ${promptProgress.index}/${promptProgress.total}；完成后会自动提交逐镜视频任务。`
        : `正在提交第 ${promptProgress.index}/${promptProgress.total} 个 H3 提示词任务：Beat ${promptProgress.sequence}`
      : shotProgress
        ? `正在提交第 ${shotProgress.index}/${shotProgress.total} 个任务：Beat ${shotProgress.sequence}`
        : shootPrepNeeded
          ? (prepFailure ? "上次补齐未完成，点击只重试缺少的素材。" : episodeShootPrepSummary(shootCheck))
          : shootReady
            ? promptFailure
              ? `已有 ${promptFailure.prepared} 个提示词就绪，还有 ${promptFailure.lines.length} 个镜头缺少 H3 提示词；视频任务尚未提交，再次点击只重试缺少的提示词。`
              : shotFailure
                ? `已提交 ${shotFailure.submitted} 个，还有 ${shotFailure.lines.length} 个镜头未提交；再次点击只重试失败的镜头。`
                : `为 ${action?.episodeShots || 0} 个镜头各提交一个独立任务，可在工坊逐个查看和重做；整集出片请在剧集工坊手动操作。`
            : action?.detail || ""
  const actionButtonLabel = prepProgress
    ? `补齐中 ${prepProgress.index}/${prepProgress.total}`
    : promptProgress
      ? promptProgress.phase === "wait"
        ? `等待提示词 ${promptProgress.index}/${promptProgress.total}`
        : `准备提示词 ${promptProgress.index}/${promptProgress.total}`
      : shotProgress
        ? `提交中 ${shotProgress.index}/${shotProgress.total}`
        : shootPrepNeeded
          ? (shootCheck.canFix ? "补齐素材并分段出片" : "去工坊处理")
          : shootReady
            ? promptFailure
              ? `重试缺少的提示词（${promptFailure.lines.length}）`
              : shotFailure
                ? `重试未提交镜头（${shotFailure.lines.length}）`
                : `提交 ${action?.episodeShots || 0} 个逐镜任务`
            : action?.button || ""
  const actionDisabled = actionLoading
    || (action?.kind === "draft-assets" && (!canPrompt || busy))
    || (action?.kind === "open-workshop" && shootReady && busy)
    || ((action?.kind === "plan-shots" || action?.kind === "sync-episodes") && busy)

  return <section className="assistant-workflow" aria-label="创作流程进度">
    <div className="assistant-workflow-head">
      <strong><Route size={13} />创作流程</strong>
      <span className="assistant-workflow-count">{progress ? `${progress.completed}/${progress.total}` : ""}</span>
      <Tooltip classNames={{ root: "director-assistant-tooltip" }} title="刷新进度"><Button type="text" size="small" aria-label="刷新创作流程" loading={loading} disabled={acting} icon={<RefreshCw size={12} />} onClick={() => void load()} /></Tooltip>
    </div>
    {!progress ? <div className={`assistant-workflow-status${error ? " is-error" : ""}`}>
      {error || (loading ? <><Spin size="small" />正在读取创作流程…</> : "正在读取创作流程…")}
      {error && <Button type="link" size="small" onClick={() => void load()}>重试</Button>}
    </div> : <>
      <Steps
        className="assistant-workflow-steps"
        size="small"
        responsive={false}
        items={progress.steps.map(step => ({
          title: <Tooltip classNames={{ root: "director-assistant-tooltip" }} title={step.detail}><span className="assistant-workflow-step-label">{step.label}</span></Tooltip>,
          status: step.state === "done" ? "finish" : step.state === "current" ? "process" : "wait",
        }))}
      />
      {action && <div className="assistant-workflow-next">
        <div className="assistant-workflow-copy">
          <strong>{actionTitle}</strong>
          <span>{actionDetail}</span>
        </div>
        <div className="assistant-workflow-actions">
          {action.kind === "open-workshop" && action.episodeId && shootReady && (
            <Button type="text" size="small" disabled={acting} onClick={() => onNavigate("workshop", action.episodeId || undefined)}>进入工坊</Button>
          )}
          <Button
            type="primary"
            size="small"
            icon={action.kind === "open-workshop" && shootReady ? <Video size={13} /> : <ArrowRight size={13} />}
            iconPlacement="end"
            loading={actionLoading}
            disabled={actionDisabled}
            onClick={() => void runAction()}
          >{actionButtonLabel}</Button>
        </div>
      </div>}
      {shootReady && promptFailure && !promptProgress && <div className="assistant-shoot-prep is-error" role="status">
        <strong>有 {promptFailure.lines.length} 个镜头缺少 H3 提示词</strong>
        {promptFailure.lines.slice(0, 3).map((line, index) => <span key={`${index}-${line}`}>{line.length > 180 ? `${line.slice(0, 180)}…` : line}</span>)}
        {promptFailure.lines.length > 3 ? <span>…等 {promptFailure.lines.length} 项</span> : null}
        <em>{promptFailure.prepared ? `已准备的 ${promptFailure.prepared} 个提示词会保留，视频任务尚未提交；再次点击只重试缺少的提示词。` : "视频任务尚未提交；再次点击会重新准备提示词。"}</em>
      </div>}
      {shootReady && shotFailure && !shotProgress && <div className="assistant-shoot-prep is-error" role="status">
        <strong>有 {shotFailure.lines.length} 个镜头未提交</strong>
        {shotFailure.lines.slice(0, 3).map((line, index) => <span key={`${index}-${line}`}>{line.length > 180 ? `${line.slice(0, 180)}…` : line}</span>)}
        {shotFailure.lines.length > 3 ? <span>…等 {shotFailure.lines.length} 项</span> : null}
        <em>{shotFailure.submitted ? `已提交的 ${shotFailure.submitted} 个任务会继续生成，再次点击只补交失败的镜头。` : "再次点击会重新尝试这些镜头。"}</em>
      </div>}
      {prepFailure && !prepProgress && <div className="assistant-shoot-prep is-error" role="status">
        <strong>上次补齐未完成</strong>
        {prepFailure.split("\n").slice(0, 3).map((line) => <span key={line}>{line.length > 180 ? `${line.slice(0, 180)}…` : line}</span>)}
        {prepFailure.split("\n").length > 3 ? <span>…等 {prepFailure.split("\n").length} 项</span> : null}
        <em>已生成的素材会保留，再次点击只补齐缺少的部分。</em>
      </div>}
      {error && <p className="assistant-workflow-status is-error">{error}<Button type="link" size="small" onClick={() => void load()}>重试</Button></p>}
    </>}
  </section>
}
