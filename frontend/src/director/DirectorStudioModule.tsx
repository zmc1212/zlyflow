import { useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Button, Dropdown, Input, InputNumber, message, Modal, Radio, Select,
} from "antd"
import {
  ArrowLeft, CircleStop, FileText, Film, FolderPlus, Grid, ImagePlus,
  MoreHorizontal, Pause, Play, Plus, Search, SkipBack, SkipForward, Sliders, Wand2,
} from "lucide-react"
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { requestJson, User } from "../api"
import { DirectoryHandleLike } from "../local-resource-store"
import CompiledPromptInspector from "./components/CompiledPromptInspector"
import CameraControlModal from "./components/CameraControlModal"
import FrameScrubberModal from "./components/FrameScrubberModal"
import ScriptDocumentDrawer from "./components/ScriptDocumentDrawer"
import ScriptSplitModal, { ScriptSplitApplyResult } from "./components/ScriptSplitModal"
import ShotInspectorDrawer from "./components/ShotInspectorDrawer"
import TimelineRuler from "./components/TimelineRuler"
import TimelineTrackMain from "./components/TimelineTrackMain"
import TimelineTrackSubjects from "./components/TimelineTrackSubjects"
import SequencePlayerModal from "./components/SequencePlayerModal"
import JianyingExportModal from "../media/JianyingExportModal"
import type { JianyingMediaItem } from "../media/jianying-draft-builder"
import DirectorProjectLibrary from "./DirectorProjectLibrary"
import {
  copyDirectorProject, createDirectorProject, deleteDirectorProject, getDirectorProject,
  listDirectorProjects, migrateDirectorProjects, timelineProjectFromApi, updateDirectorProject,
} from "./director-api"
import {
  createExampleProject, hasDirectorProjectsMigrated, markDirectorProjectsMigrated,
  peekLocalDirectorProjects,
} from "./director-storage"
import { extractVideoFrame, fileFromUrl, fileToDataUrl, jobProgressFromJob, jobVideoUrl, mergeDirectorStatus, shotStatusFromJob, waitForJobTerminal } from "./director-submit"
import "./prompt-compiler.contract"
import {
  directorJobOptions,
  directorSpeedSteps,
  ReferencePlan,
  ReferencePlanItem,
  ShotSubmission,
  DirectorRenderPass,
  directorRenderPassLabel,
  resolveClipSubmission,
  resolveShotSubmission,
  snapH3DurationSec,
  sumShotDurationSec,
  H3_MIN_DURATION_SEC,
  H3_MAX_DURATION_SEC,
} from "./prompt-compiler"
import {
  CAMERA_ANGLE_LABELS, CAMERA_LIGHTING_LABELS, CAMERA_MOVEMENT_LABELS, CAMERA_SCALE_LABELS,
  applyDirectorFinalQuality, createEmptyProject, createEmptyShot, DIRECTOR_QUALITY_OPTIONS,
  DIRECTOR_SPEED_OPTIONS, projectHasGeneratedTakes,
  DirectorQuality, DirectorShot, DirectorSpeed, ShotTake, SubjectSlot, TimelineProject,
} from "./types"

function cameraZh(label?: string) {
  return (label || "").split(/[\s(（]/)[0] || label || ""
}

function DirectorRenderSettingsBar({
  project,
  onChange,
}: {
  project: TimelineProject
  onChange: (updater: (proj: TimelineProject) => TimelineProject) => void
}) {
  const preview = directorJobOptions("preview", project)
  const final = directorJobOptions("final", project)
  return (
    <div className="director-render-bar">
      <div className="director-render-group">
        <span>预览渲染</span>
        <Select
          size="small"
          aria-label="预览分辨率"
          value={preview.quality}
          style={{ minWidth: 96 }}
          options={DIRECTOR_QUALITY_OPTIONS}
          onChange={(quality: DirectorQuality) => onChange((proj) => ({ ...proj, previewQuality: quality }))}
        />
        <Select
          size="small"
          aria-label="预览步数"
          value={preview.speed}
          style={{ minWidth: 132 }}
          options={DIRECTOR_SPEED_OPTIONS.map((item) => ({ value: item.value, label: item.label }))}
          onChange={(speed: DirectorSpeed) => onChange((proj) => ({ ...proj, previewSpeed: speed }))}
        />
      </div>
      <div className="director-render-group">
        <span>成片渲染</span>
        <Select
          size="small"
          aria-label="成片分辨率"
          value={final.quality}
          style={{ minWidth: 96 }}
          options={DIRECTOR_QUALITY_OPTIONS}
          onChange={(quality: DirectorQuality) => onChange((proj) => applyDirectorFinalQuality(proj, quality))}
        />
        <Select
          size="small"
          aria-label="成片步数"
          value={final.speed}
          style={{ minWidth: 132 }}
          options={DIRECTOR_SPEED_OPTIONS.map((item) => ({ value: item.value, label: item.label }))}
          onChange={(speed: DirectorSpeed) => onChange((proj) => ({ ...proj, finalSpeed: speed }))}
        />
      </div>
    </div>
  )
}

function formatTimecode(sec: number) {
  const clamped = Math.max(0, sec)
  const minutes = Math.floor(clamped / 60)
  const seconds = clamped % 60
  return `${String(minutes).padStart(2, "0")}:${seconds.toFixed(1).padStart(4, "0")}`
}

interface DirectorStudioModuleProps {
  user: User
  csrfToken: string
  allJobs: any[]
  directoryHandle?: DirectoryHandleLike
  onOpenDirectoryModal?: () => void
  onExitDirector?: () => void
}

function jianyingAspectRatio(ratio: string): "16:9" | "9:16" | "1:1" | "4:3" | "21:9" {
  if (ratio === "9:16" || ratio === "1:1" || ratio === "4:3" || ratio === "21:9") return ratio
  return "16:9"
}

async function fileForPlanItem(item: ReferencePlanItem, project: TimelineProject, shot: DirectorShot): Promise<File> {
  if (item.role === "first_frame") {
    if (shot.firstFrameFile) return shot.firstFrameFile
    if (shot.firstFrameUrl) return fileFromUrl(shot.firstFrameUrl, "first_frame.png")
  }
  if (item.role === "last_frame") {
    if (shot.endFrameFile) return shot.endFrameFile
    if (shot.endFrameUrl) return fileFromUrl(shot.endFrameUrl, "last_frame.png")
  }
  if (item.role === "subject" && item.slotId) {
    const slot = project.subjectSlots.find((candidate) => candidate.id === item.slotId)
    if (slot?.file) return slot.file
    if (slot?.previewUrl) return fileFromUrl(slot.previewUrl, `${slot.id}.png`)
  }
  throw new Error(`无法读取 ${item.label} 对应的参考图`)
}

async function filesForPlan(plan: ReferencePlan, project: TimelineProject, shot: DirectorShot): Promise<File[]> {
  const files: File[] = []
  for (const item of plan.items) {
    files.push(await fileForPlanItem(item, project, shot))
  }
  return files
}

function directorShotStatus(status: DirectorShot["status"], progress = 0): { label: string; tone: "idle" | "running" | "success" | "error" } {
  if (status === "succeeded") return { label: "已完成", tone: "success" }
  if (status === "failed") return { label: "需要处理", tone: "error" }
  if (status === "cancelled") return { label: "已停止", tone: "error" }
  if (status === "interrupted") return { label: "已中断", tone: "error" }
  if (status === "queued") return { label: "排队中", tone: "running" }
  if (status === "running") return { label: `生成中 ${progress}%`, tone: "running" }
  return { label: "待生成", tone: "idle" }
}

function directorProgressCaption(status: DirectorShot["status"]): string {
  if (status === "queued") return "排队中"
  if (status === "interrupted") return "已中断"
  if (status === "cancelled") return "已停止"
  if (status === "failed") return "需要处理"
  return "生成中"
}

function shotMediaUrl(shot: DirectorShot): string | undefined {
  return shot.outputVideoUrl || shot.firstFrameUrl || shot.endFrameUrl
}

export default function DirectorStudioModule({
  user,
  csrfToken,
  allJobs,
  directoryHandle,
  onOpenDirectoryModal,
  onExitDirector,
}: DirectorStudioModuleProps) {
  const queryClient = useQueryClient()
  const fallbackProjectRef = useRef<TimelineProject>(createEmptyProject())
  const [studioView, setStudioView] = useState<"library" | "workspace">("library")
  const [workspaceProject, setWorkspaceProject] = useState<TimelineProject | null>(null)
  const [scriptSplitModalOpen, setScriptSplitModalOpen] = useState(false)
  const [scriptSplitMode, setScriptSplitMode] = useState<"library" | "workspace">("library")
  const [scriptDocumentOpen, setScriptDocumentOpen] = useState(false)
  const [scriptSaving, setScriptSaving] = useState(false)
  const [pendingSplit, setPendingSplit] = useState<ScriptSplitApplyResult | null>(null)
  const [splitDisposition, setSplitDisposition] = useState<"replace" | "saveAs">("replace")
  const skipPersistRef = useRef(true)
  const [sequencePlayerOpen, setSequencePlayerOpen] = useState(false)
  const [jianyingOpen, setJianyingOpen] = useState(false)
  const [jianyingItems, setJianyingItems] = useState<JianyingMediaItem[]>([])
  const [isEditingProjectTitle, setIsEditingProjectTitle] = useState(false)
  const [isBatchRendering, setIsBatchRendering] = useState(false)
  const [previewMode, setPreviewMode] = useState<"shot" | "clip">("shot")
  const [shotSearch, setShotSearch] = useState("")

  // 时间轴状态
  const [viewMode, setViewMode] = useState<"timeline" | "storyboard">("timeline")
  const [currentTimeSec, setCurrentTimeSec] = useState(0)
  const [pixelsPerSecond, setPixelsPerSecond] = useState(48)
  const [rulerUnit, setRulerUnit] = useState<"seconds" | "frames">("seconds")
  const [selectedShotId, setSelectedShotId] = useState<string | undefined>()
  const [inspectorTab, setInspectorTab] = useState<"shot" | "subjects" | "run">("shot")
  const [snapEnabled, setSnapEnabled] = useState(true)
  const [cameraModalOpen, setCameraModalOpen] = useState(false)
  const [previewPlaying, setPreviewPlaying] = useState(false)
  const [previewTime, setPreviewTime] = useState(0)
  const previewVideoRef = useRef<HTMLVideoElement>(null)
  const firstFrameInputRef = useRef<HTMLInputElement>(null)
  const endFrameInputRef = useRef<HTMLInputElement>(null)

  // 抽屉与定格截取弹窗
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [inspectedShot, setInspectedShot] = useState<DirectorShot | null>(null)
  const [scrubberOpen, setScrubberOpen] = useState(false)
  const [scrubbingShot, setScrubbingShot] = useState<DirectorShot | null>(null)

  const activeProject = workspaceProject ?? fallbackProjectRef.current
  const projectRef = useRef(activeProject)
  projectRef.current = activeProject

  const timelineDurationSec = useMemo(() => sumShotDurationSec(activeProject.shots), [activeProject.shots])
  const selectedShot = useMemo(() => {
    return activeProject.shots.find((shot) => shot.id === selectedShotId) || activeProject.shots[0]
  }, [activeProject.shots, selectedShotId])
  const shotSubmission = useMemo((): ShotSubmission | null => {
    if (!selectedShot) return null
    return resolveShotSubmission(activeProject, selectedShot)
  }, [activeProject, selectedShot])
  const clipSubmission = useMemo(() => resolveClipSubmission(activeProject), [activeProject])
  const previewJob = useMemo(() => directorJobOptions("preview", activeProject), [activeProject])
  const finalJob = useMemo(() => directorJobOptions("final", activeProject), [activeProject])

  const llmStatusQuery = useQuery({
    queryKey: ["llm-status"],
    queryFn: () => requestJson<{ available: boolean; message?: string; supports_vision?: boolean; model?: string }>("/api/llm/status"),
  })
  const projectsQuery = useQuery({
    queryKey: ["director-projects", user.id],
    queryFn: listDirectorProjects,
  })
  const analyzeDisabledReason = !llmStatusQuery.isFetched
    ? "正在确认大模型是否支持视觉输入"
    : llmStatusQuery.data?.supports_vision
      ? undefined
      : (llmStatusQuery.data?.message
        || "当前大模型不支持视觉输入，无法根据参考图提取外貌。请在管理设置中改用带 VL/Vision 的模型。")

  useEffect(() => {
    if (previewMode === "clip" && !clipSubmission.clipAllowed) {
      setPreviewMode("shot")
    }
  }, [previewMode, clipSubmission.clipAllowed])

  useEffect(() => {
    let cancelled = false
    const migrate = async () => {
      if (hasDirectorProjectsMigrated(user.id)) return
      const localProjects = peekLocalDirectorProjects(user.id)
      if (localProjects.length > 0) {
        await migrateDirectorProjects(localProjects, csrfToken)
      }
      markDirectorProjectsMigrated(user.id)
      if (!cancelled) {
        await queryClient.invalidateQueries({ queryKey: ["director-projects", user.id] })
      }
    }
    void migrate().catch((error: Error) => {
      if (!cancelled) message.error(error.message || "迁入本地导演工程失败")
    })
    return () => {
      cancelled = true
    }
  }, [csrfToken, queryClient, user.id])

  useEffect(() => {
    if (studioView !== "workspace" || !workspaceProject || skipPersistRef.current) return
    const timer = window.setTimeout(() => {
      void updateDirectorProject(projectRef.current, csrfToken).catch((error: Error) => {
        message.warning(error.message || "工程自动保存失败")
      })
    }, 800)
    return () => window.clearTimeout(timer)
  }, [csrfToken, studioView, workspaceProject])

  useEffect(() => () => {
    if (!skipPersistRef.current && projectRef.current?.id && studioView === "workspace") {
      void updateDirectorProject(projectRef.current, csrfToken).catch(() => undefined)
    }
  }, [csrfToken, studioView])

  useEffect(() => {
    if (studioView !== "workspace" || !workspaceProject || !allJobs.length) return
    const jobMap = new Map<string, any>()
    for (const j of allJobs) {
      jobMap.set(j.id, j)
    }

    setWorkspaceProject((prev) => {
      if (!prev) return prev
      let changed = false
      const nextShots = prev.shots.map((shot) => {
        if (!shot.jobId) return shot
        const matchedJob = jobMap.get(shot.jobId)
        if (!matchedJob) return shot

        const outputVideo = matchedJob.outputs?.find((o: any) => o.kind === "video")
        const videoUrl = jobVideoUrl(matchedJob)
        const nextStatus = mergeDirectorStatus(shot.status, shotStatusFromJob(matchedJob))
        const nextProgress = jobProgressFromJob(matchedJob, shot.progress)

        let nextTakes = shot.takes
        if (nextTakes.length > 0 && shot.activeTakeIndex < nextTakes.length) {
          const curTake = nextTakes[shot.activeTakeIndex]
          if (curTake && (curTake.status !== nextStatus || curTake.progress !== nextProgress || (videoUrl && curTake.videoUrl !== videoUrl))) {
            nextTakes = [...nextTakes]
            nextTakes[shot.activeTakeIndex] = {
              ...curTake,
              status: nextStatus,
              progress: nextProgress,
              videoUrl: videoUrl || curTake.videoUrl,
              outputPath: outputVideo?.path || curTake.outputPath,
              error: matchedJob.error || curTake.error,
            }
            changed = true
          }
        }

        if (
          shot.status !== nextStatus ||
          shot.progress !== nextProgress ||
          (videoUrl && shot.outputVideoUrl !== videoUrl)
        ) {
          changed = true
          return {
            ...shot,
            status: nextStatus,
            progress: nextProgress,
            outputVideoUrl: videoUrl || shot.outputVideoUrl,
            outputPath: outputVideo?.path || shot.outputPath,
            error: matchedJob.error || shot.error,
            takes: nextTakes,
          }
        }
        return nextTakes !== shot.takes ? { ...shot, takes: nextTakes } : shot
      })

      return changed ? { ...prev, shots: nextShots, updatedAt: new Date().toISOString() } : prev
    })
  }, [allJobs, studioView, workspaceProject?.id])

  const updateActiveProject = (updater: (proj: TimelineProject) => TimelineProject) => {
    if (!workspaceProject) return
    const next = updater(projectRef.current)
    if (next === projectRef.current) return
    const updated = { ...next, updatedAt: new Date().toISOString() }
    projectRef.current = updated
    setWorkspaceProject(updated)
  }

  const openProject = useCallback(async (projectId: string) => {
    skipPersistRef.current = true
    const row = await getDirectorProject(projectId)
    const project = timelineProjectFromApi(row)
    projectRef.current = project
    setWorkspaceProject(project)
    setSelectedShotId(project.shots[0]?.id)
    setStudioView("workspace")
    window.setTimeout(() => {
      skipPersistRef.current = false
    }, 0)
  }, [])

  const returnToLibrary = useCallback(async () => {
    if (workspaceProject && !skipPersistRef.current) {
      try {
        await updateDirectorProject(projectRef.current, csrfToken)
      } catch (error: any) {
        message.warning(error?.message || "返回前保存失败")
      }
    }
    skipPersistRef.current = true
    setStudioView("library")
    setWorkspaceProject(null)
    setScriptDocumentOpen(false)
    setPendingSplit(null)
    setIsEditingProjectTitle(false)
    await queryClient.invalidateQueries({ queryKey: ["director-projects", user.id] })
  }, [csrfToken, queryClient, user.id, workspaceProject])

  const handleCreateBlank = async () => {
    try {
      const created = await createDirectorProject(createEmptyProject(), csrfToken)
      await queryClient.invalidateQueries({ queryKey: ["director-projects", user.id] })
      await openProject(created.id)
    } catch (error: any) {
      message.error(error?.message || "创建工程失败")
    }
  }

  const handleCreateExample = async () => {
    try {
      const created = await createDirectorProject(createExampleProject(), csrfToken)
      await queryClient.invalidateQueries({ queryKey: ["director-projects", user.id] })
      await openProject(created.id)
      message.success("已用示例分镜创建工程")
    } catch (error: any) {
      message.error(error?.message || "创建示例工程失败")
    }
  }

  const handleCopyProject = async (projectId: string) => {
    try {
      await copyDirectorProject(projectId, csrfToken)
      await queryClient.invalidateQueries({ queryKey: ["director-projects", user.id] })
      message.success("已复制工程")
    } catch (error: any) {
      message.error(error?.message || "复制失败")
    }
  }

  const handleDeleteProject = async (projectId: string) => {
    try {
      await deleteDirectorProject(projectId, csrfToken)
      await queryClient.invalidateQueries({ queryKey: ["director-projects", user.id] })
      message.success("已删除工程")
    } catch (error: any) {
      message.error(error?.message || "删除失败")
    }
  }

  const applySplitResult = (result: ScriptSplitApplyResult, target: TimelineProject): TimelineProject => {
    let curTime = 0
    const timelineShots: DirectorShot[] = result.shots.map((shot, idx) => {
      const dur = snapH3DurationSec(shot.durationSec || 5)
      const nextShot: DirectorShot = {
        ...shot,
        id: `shot-${Date.now()}-${idx}-${Math.random().toString(36).slice(2, 5)}`,
        shotNumber: idx + 1,
        startSec: curTime,
        durationSec: dur,
        referencedSubjectIds: [],
        takes: [],
        activeTakeIndex: 0,
        status: "idle",
        progress: 0,
        retakeCount: 0,
      }
      curTime += dur
      return nextShot
    })
    return {
      ...target,
      title: result.projectTitle || target.title,
      summary: result.summary || target.summary,
      sourceScript: result.sourceScript,
      styleVibe: result.styleVibe,
      requestedShotCount: result.requestedShotCount,
      shots: timelineShots,
      updatedAt: new Date().toISOString(),
    }
  }

  const handleSplitApply = async (result: ScriptSplitApplyResult) => {
    if (scriptSplitMode === "library" || studioView === "library") {
      try {
        const created = await createDirectorProject(applySplitResult(result, createEmptyProject(result.projectTitle || "未命名分镜工程")), csrfToken)
        await queryClient.invalidateQueries({ queryKey: ["director-projects", user.id] })
        await openProject(created.id)
        message.success(`已从剧本创建工程，共 ${result.shots.length} 个镜头`)
      } catch (error: any) {
        message.error(error?.message || "保存拆分结果失败")
      }
      return
    }
    const hasTakes = projectHasGeneratedTakes(projectRef.current)
    setSplitDisposition(hasTakes ? "saveAs" : "replace")
    setPendingSplit(result)
  }

  const splitOntoCurrentCanvas = (result: ScriptSplitApplyResult, current: TimelineProject): TimelineProject => {
    return applySplitResult(result, {
      ...createEmptyProject(result.projectTitle || current.title || "未命名分镜工程"),
      aspectRatio: current.aspectRatio,
      canvasTier: current.canvasTier,
      previewQuality: current.previewQuality,
      previewSpeed: current.previewSpeed,
      finalQuality: current.finalQuality,
      finalSpeed: current.finalSpeed,
      width: current.width,
      height: current.height,
      fps: current.fps,
      refsMode: current.refsMode,
      globalSoundscape: current.globalSoundscape,
      globalMusic: current.globalMusic,
      subjectSlots: current.subjectSlots,
    })
  }

  const handleConfirmSplit = async () => {
    if (!pendingSplit) return
    const result = pendingSplit
    try {
      if (splitDisposition === "saveAs") {
        const created = await createDirectorProject(splitOntoCurrentCanvas(result, projectRef.current), csrfToken)
        setPendingSplit(null)
        await queryClient.invalidateQueries({ queryKey: ["director-projects", user.id] })
        await openProject(created.id)
        message.success(`已另存为新工程，共 ${result.shots.length} 个镜头，原文已写入`)
        return
      }
      updateActiveProject((proj) => applySplitResult(result, proj))
      setPendingSplit(null)
      await updateDirectorProject(projectRef.current, csrfToken)
      message.success(`已替换当前分镜，共 ${result.shots.length} 个镜头，原文已写入工程`)
    } catch (error: any) {
      message.error(error?.message || "保存拆分结果失败")
    }
  }

  const handleSaveSourceScript = async () => {
    if (!workspaceProject) return
    setScriptSaving(true)
    try {
      await updateDirectorProject(projectRef.current, csrfToken)
      message.success("剧本文档已保存")
    } catch (error: any) {
      message.warning(error?.message || "保存原文失败")
    } finally {
      setScriptSaving(false)
    }
  }

  const openScriptSplit = (mode: "library" | "workspace") => {
    setScriptSplitMode(mode)
    setScriptDocumentOpen(false)
    setScriptSplitModalOpen(true)
  }

  const applyJobSnapshot = (shotId: string, job: any) => {
    if (!job?.id) return
    const videoUrl = jobVideoUrl(job)
    const outputPath = job.outputs?.find((item: any) => item.kind === "video")?.path as string | undefined
    const nextStatus = shotStatusFromJob(job)
    const nextProgress = jobProgressFromJob(job)
    updateActiveProject((proj) => {
      let changed = false
      const shots = proj.shots.map((shot) => {
        if (shot.id !== shotId && shot.jobId !== job.id) return shot
        const mergedStatus = mergeDirectorStatus(shot.status, nextStatus)
        let nextTakes = shot.takes
        if (nextTakes.length > 0 && shot.activeTakeIndex < nextTakes.length) {
          const curTake = nextTakes[shot.activeTakeIndex]
          if (curTake && (curTake.status !== mergedStatus || curTake.progress !== nextProgress || (videoUrl && curTake.videoUrl !== videoUrl))) {
            nextTakes = [...nextTakes]
            nextTakes[shot.activeTakeIndex] = {
              ...curTake,
              jobId: job.id || curTake.jobId,
              status: mergedStatus,
              progress: nextProgress,
              videoUrl: videoUrl || curTake.videoUrl,
              outputPath: outputPath || curTake.outputPath,
              error: job.error || curTake.error,
            }
            changed = true
          }
        }
        if (
          shot.status !== mergedStatus ||
          shot.progress !== nextProgress ||
          shot.jobId !== job.id ||
          (videoUrl && shot.outputVideoUrl !== videoUrl)
        ) {
          changed = true
          return {
            ...shot,
            jobId: job.id || shot.jobId,
            status: mergedStatus,
            progress: nextProgress,
            outputVideoUrl: videoUrl || shot.outputVideoUrl,
            outputPath: outputPath || shot.outputPath,
            error: job.error || shot.error,
            takes: nextTakes,
          }
        }
        return changed ? { ...shot, takes: nextTakes } : shot
      })
      return changed ? { ...proj, shots } : proj
    })
  }

  const renderShot = async (targetShot: DirectorShot, options?: {
    submission?: ShotSubmission
    clipShot?: DirectorShot
    renderPass?: DirectorRenderPass
  }) => {
    const project = projectRef.current
    const latestShot = project.shots.find((shot) => shot.id === targetShot.id) || targetShot
    const renderPass = options?.renderPass || options?.submission?.renderPass || "final"
    const submission = options?.submission || resolveShotSubmission(project, latestShot, renderPass)
    if (submission.errors.length) {
      message.error(submission.errors[0])
      return undefined
    }
    try {
      const form = new FormData()
      form.append("mode", submission.workflowId)
      form.append("prompt", submission.prompt)
      form.append("title", options?.submission?.isClip ? `${project.title} 整段` : `${latestShot.title} #${latestShot.shotNumber}`)
      form.append("options", JSON.stringify({
        aspect_ratio: submission.aspectRatio,
        quality: submission.quality,
        speed: submission.speed,
        duration: submission.durationSec,
      }))

      const attachShot = options?.clipShot || latestShot
      const files = await filesForPlan(submission.plan, project, attachShot)
      for (const file of files) {
        form.append("references", file)
      }

      const takeNumber = latestShot.takes.length + 1
      const newTake: ShotTake = {
        id: `take-${Date.now()}-${takeNumber}`,
        takeNumber,
        status: "queued",
        progress: 0,
        createdAt: new Date().toISOString(),
        promptSnapshot: submission.prompt,
        renderPass: submission.renderPass,
      }
      const updatedTakes = [...latestShot.takes, newTake]
      updateActiveProject((proj) => ({
        ...proj,
        shots: proj.shots.map((shot) =>
          shot.id === latestShot.id
            ? {
                ...shot,
                status: "queued",
                progress: 0,
                takes: updatedTakes,
                activeTakeIndex: updatedTakes.length - 1,
                outputVideoUrl: undefined,
                outputPath: undefined,
                error: undefined,
              }
            : shot,
        ),
      }))

      const response = await fetch("/api/jobs", {
        method: "POST",
        headers: { "X-CSRF-Token": csrfToken },
        body: form,
      })
      if (!response.ok) {
        const errJson = await response.json().catch(() => ({}))
        throw new Error(typeof errJson.detail === "string" ? errJson.detail : "提交分镜任务失败")
      }
      const jobData = await response.json()
      applyJobSnapshot(latestShot.id, jobData)
      void waitForJobTerminal(jobData.id, {
        onProgress: (job) => {
          applyJobSnapshot(latestShot.id, job)
          void queryClient.invalidateQueries({ queryKey: ["jobs"] })
        },
      }).catch(() => undefined)
      message.success(
        submission.isClip
          ? `整段 ${submission.durationSec}s 已提交（${directorRenderPassLabel(submission.renderPass)} ${submission.quality} / ${submission.speed}）`
          : `分镜 #${latestShot.shotNumber} ${directorRenderPassLabel(submission.renderPass)} Take ${takeNumber} 已提交（${submission.quality} / ${submission.speed}）`,
      )
      queryClient.invalidateQueries({ queryKey: ["jobs"] })
      return jobData.id as string
    } catch (err: any) {
      console.error(err)
      message.error(err.message || "提交失败")
      updateActiveProject((proj) => ({
        ...proj,
        shots: proj.shots.map((shot) => (shot.id === latestShot.id ? { ...shot, status: "failed", error: err.message } : shot)),
      }))
      return undefined
    }
  }

  const cancelShot = async (targetShot: DirectorShot) => {
    const shot = projectRef.current.shots.find((item) => item.id === targetShot.id) || targetShot
    if (!shot.jobId || (shot.status !== "queued" && shot.status !== "running" && shot.status !== "interrupted")) {
      return
    }
    try {
      await requestJson(`/api/jobs/${encodeURIComponent(shot.jobId)}/cancel`, {
        method: "POST",
        headers: { "X-CSRF-Token": csrfToken },
      })
      void queryClient.invalidateQueries({ queryKey: ["jobs"] })
      message.success(`已停止分镜 #${shot.shotNumber}`)
    } catch (error: any) {
      message.error(error?.message || "停止生成失败")
    }
  }

  const handleSubmitClip = async () => {
    const project = projectRef.current
    const firstShot = project.shots[0]
    const lastShot = project.shots[project.shots.length - 1]
    if (!firstShot || !clipSubmission.clipAllowed) {
      message.warning(clipSubmission.errors[0] || "当前分镜合计超过 15 秒，不能整段提交")
      return
    }
    await renderShot(firstShot, {
      submission: resolveClipSubmission(project, "final"),
      renderPass: "final",
      clipShot: {
        ...firstShot,
        endFrameFile: lastShot?.endFrameFile,
        endFrameUrl: lastShot?.endFrameUrl,
      },
    })
  }

  const handleBatchRenderAll = async () => {
    setIsBatchRendering(true)
    message.loading({ content: "正在按镜头接龙渲染成片：成功后抽尾帧再交下一镜", key: "batch-render", duration: 0 })
    try {
      const shotIds = projectRef.current.shots.map((shot) => shot.id)
      for (let index = 0; index < shotIds.length; index += 1) {
        const shot = projectRef.current.shots.find((item) => item.id === shotIds[index])
        if (!shot) continue
        message.loading({ content: `正在渲染分镜 ${index + 1}/${shotIds.length}`, key: "batch-render", duration: 0 })
        const jobId = await renderShot(shot, { renderPass: "final" })
        if (!jobId) {
          throw new Error(`分镜 #${shot.shotNumber} 提交失败，已中止接龙`)
        }
        const job = await waitForJobTerminal(jobId, {
          onProgress: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        })
        const videoUrl = jobVideoUrl(job)
        const nextShot = projectRef.current.shots.find((item) => item.id === shotIds[index + 1])
        if (videoUrl && nextShot) {
          try {
            const frame = await extractVideoFrame(videoUrl)
            updateActiveProject((proj) => ({
              ...proj,
              shots: proj.shots.map((item) =>
                item.id === nextShot.id
                  ? {
                      ...item,
                      firstFrameFile: frame.file,
                      firstFrameUrl: frame.dataUrl,
                      usePreviousEndFrame: true,
                    }
                  : item,
              ),
            }))
          } catch (error: any) {
            message.warning(`分镜 #${shot.shotNumber} 已成功，但抽取尾帧失败：${error.message || "未知错误"}`)
          }
        }
      }
      message.success({ content: "全部分镜已按接龙顺序渲染完成", key: "batch-render" })
    } catch (error: any) {
      message.error({ content: error.message || "批量接龙渲染已中止", key: "batch-render" })
    } finally {
      setIsBatchRendering(false)
    }
  }

  const handleAnalyzeSlot = async (slot: SubjectSlot) => {
    if (analyzeDisabledReason) {
      message.warning(analyzeDisabledReason)
      return
    }
    if (!slot.previewUrl && !slot.file) {
      message.warning("请先上传该槽位的主体参考图")
      return
    }

    updateActiveProject((proj) => ({
      ...proj,
      subjectSlots: proj.subjectSlots.map((item) => (item.id === slot.id ? { ...item, analyzing: true } : item)),
    }))

    try {
      let imageFile = slot.file
      if (!imageFile && slot.previewUrl) {
        imageFile = await fileFromUrl(slot.previewUrl, `${slot.id}.png`)
      }
      if (!imageFile) {
        throw new Error("无法读取主体参考图")
      }
      const form = new FormData()
      form.append("image", imageFile)
      form.append("kind", slot.kind)
      form.append("name", slot.name)
      const res = await requestJson<{ description: string }>("/api/llm/analyze-subject", {
        method: "POST",
        headers: { "X-CSRF-Token": csrfToken },
        body: form,
      })
      updateActiveProject((proj) => ({
        ...proj,
        subjectSlots: proj.subjectSlots.map((item) =>
          item.id === slot.id ? { ...item, description: res.description.trim(), analyzing: false } : item,
        ),
      }))
      message.success(`已根据参考图提取 ${slot.id} 特征描述`)
    } catch (err: any) {
      updateActiveProject((proj) => ({
        ...proj,
        subjectSlots: proj.subjectSlots.map((item) => (item.id === slot.id ? { ...item, analyzing: false } : item)),
      }))
      message.error(err.message || "视觉提取失败")
    }
  }

  // 首尾帧接龙
  const handleChainToNext = async (sourceShot: DirectorShot) => {
    if (!sourceShot.outputVideoUrl) return
    const nextShot = activeProject.shots.find((s) => s.shotNumber === sourceShot.shotNumber + 1)
    if (!nextShot) {
      message.info("已是最后一个分镜")
      return
    }

    setScrubbingShot(sourceShot)
    setScrubberOpen(true)
  }

  const slotLabel = (slotId: string) => {
    const slot = activeProject.subjectSlots.find((item) => item.id === slotId)
    return slot?.name && slot.name !== `主体 ${slot.slotIndex}` ? `${slotId} ${slot.name}` : slotId
  }

  const handleAnchorUpload = (kind: "first" | "end", file?: File) => {
    if (!selectedShot || !file) return
    void fileToDataUrl(file).then((previewUrl) => {
      updateActiveProject((proj) => ({
        ...proj,
        shots: proj.shots.map((shot) => shot.id === selectedShot.id
          ? kind === "first"
            ? { ...shot, firstFrameFile: file, firstFrameUrl: previewUrl, usePreviousEndFrame: false }
            : { ...shot, endFrameFile: file, endFrameUrl: previewUrl }
          : shot),
      }))
    }).catch((error: Error) => message.error(error.message))
  }

  const togglePreviewPlayback = () => {
    const video = previewVideoRef.current
    if (!video) return
    if (video.paused) {
      void video.play()
      setPreviewPlaying(true)
    } else {
      video.pause()
      setPreviewPlaying(false)
    }
  }

  const compiling = selectedShot?.status === "running" || selectedShot?.status === "queued" || selectedShot?.status === "interrupted"
  const compileLabel = shotSubmission?.workflowId === "minimax-h3-r2v"
    ? `R2V · <Picture 1-${Math.max(1, shotSubmission.plan.items.length)}>`
    : shotSubmission?.workflowId === "minimax-h3-i2v"
      ? "I2V · 首尾帧"
      : "T2V · 文生"
  const compileOk = !shotSubmission?.errors?.length

  if (studioView === "library") {
    return (
      <div className="director-shell">
        <DirectorProjectLibrary
          items={projectsQuery.data || []}
          loading={projectsQuery.isLoading}
          onCreateBlank={() => void handleCreateBlank()}
          onCreateFromScript={() => openScriptSplit("library")}
          onCreateExample={() => void handleCreateExample()}
          onOpen={(projectId) => {
            void openProject(projectId).catch((error: Error) => message.error(error.message || "打开工程失败"))
          }}
          onCopy={(projectId) => void handleCopyProject(projectId)}
          onDelete={(projectId) => void handleDeleteProject(projectId)}
          onExitDirector={onExitDirector}
        />
        <ScriptSplitModal
          open={scriptSplitModalOpen}
          csrfToken={csrfToken}
          initialScript=""
          applyLabel="创建工程"
          onCancel={() => setScriptSplitModalOpen(false)}
          onApply={(result) => {
            void handleSplitApply(result)
            setScriptSplitModalOpen(false)
          }}
        />
      </div>
    )
  }

  return (
    <div className="director-shell">
      <header className="director-mobile-header">
        <button type="button" aria-label="返回项目库" onClick={() => void returnToLibrary()}><ArrowLeft size={20} /></button>
        <strong title={activeProject.title}>{activeProject.title}</strong>
        <Dropdown
          trigger={["click"]}
          menu={{
            items: [
              { key: "script", label: "剧本文档", icon: <FileText size={14} />, onClick: () => setScriptDocumentOpen(true) },
              { key: "split", label: "AI 拆分剧本", icon: <Wand2 size={14} />, onClick: () => openScriptSplit("workspace") },
              { key: "preview", label: "成片预览", icon: <Play size={14} />, onClick: () => setSequencePlayerOpen(true) },
              { key: "library", label: "返回项目库", icon: <FolderPlus size={14} />, onClick: () => void returnToLibrary() },
            ],
          }}
        >
          <button type="button" aria-label="更多导演台操作"><MoreHorizontal size={20} /></button>
        </Dropdown>
      </header>
      <header className="director-topbar">
        <div className="director-project-heading">
          <div className="director-project-title-row">
            {isEditingProjectTitle ? (
              <Input
                size="small"
                value={activeProject.title}
                autoFocus
                onBlur={() => setIsEditingProjectTitle(false)}
                onPressEnter={() => setIsEditingProjectTitle(false)}
                onChange={(e) => updateActiveProject((p) => ({ ...p, title: e.target.value }))}
                className="h-8 w-56 text-sm font-semibold"
              />
            ) : (
              <button type="button" onClick={() => setIsEditingProjectTitle(true)} className="director-project-title" title="重命名工程">
                {activeProject.title}
              </button>
            )}
            <button type="button" className="director-back-library" onClick={() => void returnToLibrary()}>
              <ArrowLeft size={13} /> 返回项目库
            </button>
            <div className="director-project-meta">
              {activeProject.aspectRatio} · {activeProject.fps}fps · {timelineDurationSec.toFixed(0)}秒
            </div>
          </div>
        </div>
        <div className="director-top-actions">
          <Button size="small" onClick={() => setScriptDocumentOpen(true)} icon={<FileText size={14} />}>剧本文档</Button>
          <Button size="small" onClick={() => openScriptSplit("workspace")}>AI 拆分剧本</Button>
          <Button size="small" onClick={() => setSequencePlayerOpen(true)}>成片预览</Button>
          <Button
            size="small"
            onClick={() => {
              const items: JianyingMediaItem[] = activeProject.shots.filter((shot) => shot.outputVideoUrl).map((shot) => ({
                id: shot.id,
                title: shot.title || `分镜 ${shot.shotNumber}`,
                kind: "video" as const,
                path: shot.outputPath || shot.outputVideoUrl || shot.id,
                url: shot.outputVideoUrl || "",
                durationSeconds: snapH3DurationSec(shot.durationSec || 5),
              }))
              if (!items.length) {
                message.warning("请先完成至少一个镜头后再导出剪映草稿")
                return
              }
              setJianyingItems(items)
              setJianyingOpen(true)
            }}
          >导出剪映</Button>
          <Button type="primary" size="small" loading={isBatchRendering} onClick={handleBatchRenderAll} className="director-primary-button">批量接龙生成</Button>
        </div>
      </header>
      <DirectorRenderSettingsBar project={activeProject} onChange={updateActiveProject} />

      <details className="director-reference-disclosure">
        <summary><span>主体资产</span><span>{activeProject.subjectSlots.filter((slot) => slot.previewUrl || slot.file).length}/9 已配置</span></summary>
        <TimelineTrackSubjects
          subjectSlots={activeProject.subjectSlots || []}
          onUpdateSlot={(slot) => updateActiveProject((proj) => ({ ...proj, subjectSlots: proj.subjectSlots.map((s) => (s.id === slot.id ? slot : s)) }))}
          onInsertSlotTagToShot={(slotId) => {
            const targetShot = activeProject.shots.find((shot) => shot.id === selectedShotId) || activeProject.shots[0]
            if (!targetShot) return
            updateActiveProject((proj) => ({
              ...proj,
              shots: proj.shots.map((shot) => shot.id === targetShot.id
                ? { ...shot, prompt: shot.prompt ? `${shot.prompt} ${slotId}` : slotId, referencedSubjectIds: Array.from(new Set([...shot.referencedSubjectIds, slotId])) }
                : shot),
            }))
            message.success(`已将 ${slotId} 插入镜头 #${targetShot.shotNumber}`)
          }}
          onAnalyzeSlot={handleAnalyzeSlot}
          analyzeDisabledReason={analyzeDisabledReason}
        />
      </details>

      <div className="director-workspace-grid">
        <aside className="director-shot-bin">
          <div className="director-bin-header">
            <div className="director-section-label">镜头序列</div>
            <span className="director-mobile-bin-meta">{activeProject.aspectRatio} · {activeProject.fps}fps · {timelineDurationSec.toFixed(0)}s</span>
          </div>
          <Input size="small" prefix={<Search size={13} />} value={shotSearch} onChange={(e) => setShotSearch(e.target.value)} placeholder="搜索镜头..." className="director-search" />
          <div className="director-shot-list">
            {activeProject.shots.filter((shot) => !shotSearch.trim() || `${shot.title} ${shot.shotNumber}`.toLowerCase().includes(shotSearch.trim().toLowerCase())).map((shot) => {
              const state = directorShotStatus(shot.status, shot.progress)
              const isSelected = shot.id === selectedShot?.id
              const media = shotMediaUrl(shot)
              const running = shot.status === "running" || shot.status === "queued"
              return (
                <button
                  type="button"
                  key={shot.id}
                  onClick={() => { setSelectedShotId(shot.id); setInspectedShot(shot) }}
                  className={`director-shot-list-item ${isSelected ? "director-shot-list-item-selected" : ""}`}
                >
                  <div className="director-shot-list-meta"><span>{String(shot.shotNumber).padStart(2, "0")}</span><span className={`director-status director-status-${state.tone}`}>{state.label}</span></div>
                  <div className={`director-shot-thumb ${running ? "is-running" : ""}`}>
                    {media ? (shot.outputVideoUrl ? <video src={media} muted playsInline /> : <img src={media} alt="" />) : <Plus size={22} />}
                    {running ? <span className="director-thumb-spinner"><i /></span> : null}
                    {running ? <span className="director-thumb-progress" style={{ width: `${Math.max(4, shot.progress)}%` }} /> : null}
                  </div>
                  <div className="director-shot-list-title">{shot.title}</div>
                </button>
              )
            })}
          </div>
          <button type="button" className="director-add-shot" onClick={() => updateActiveProject((proj) => ({ ...proj, shots: [...proj.shots, createEmptyShot(proj.shots.length + 1, timelineDurationSec, 5)] }))}><Plus size={15} /> 添加镜头</button>
        </aside>

        <main className="director-center-column">
          <div className="director-preview-header">
            <div className="min-w-0">
              <div className="director-current-shot-title">
                <span className={`director-live-dot ${compiling ? "is-live" : ""}`} />
                {selectedShot ? `镜头 ${String(selectedShot.shotNumber).padStart(2, "0")} · ${selectedShot.title}` : "还没有镜头"}
                <span className="director-take-label">{selectedShot?.takes.length ? `Take ${selectedShot.activeTakeIndex + 1}` : "未拍摄"}</span>
              </div>
            </div>
            <Radio.Group size="small" value={viewMode} onChange={(e) => setViewMode(e.target.value)} className="director-view-switch">
              <Radio.Button value="timeline">预览</Radio.Button>
              <Radio.Button value="storyboard">故事板</Radio.Button>
            </Radio.Group>
          </div>

          {viewMode === "storyboard" ? (
            <div className="director-storyboard-strip">
              {activeProject.shots.map((shot) => (
                <button type="button" key={shot.id} onClick={() => setSelectedShotId(shot.id)} className={`director-storyboard-card ${shot.id === selectedShot?.id ? "is-selected" : ""}`}>
                  <div className="director-storyboard-media">{shotMediaUrl(shot) ? <img src={shotMediaUrl(shot)} alt="" /> : <Plus size={18} />}</div>
                  <span>#{shot.shotNumber} {shot.title}</span>
                </button>
              ))}
            </div>
          ) : (
            <div className="director-preview-stage">
              {selectedShot ? <div className="director-mobile-shot-badge">镜头 {String(selectedShot.shotNumber).padStart(2, "0")} · {selectedShot.takes.length ? `Take ${selectedShot.activeTakeIndex + 1}` : "未拍摄"}</div> : null}
              {selectedShot?.outputVideoUrl ? (
                <video
                  ref={previewVideoRef}
                  src={selectedShot.outputVideoUrl}
                  playsInline
                  className={`director-preview-media ${compiling ? "is-running" : ""}`}
                  onTimeUpdate={(event) => setPreviewTime(event.currentTarget.currentTime)}
                  onPlay={() => setPreviewPlaying(true)}
                  onPause={() => setPreviewPlaying(false)}
                />
              ) : selectedShot?.firstFrameUrl ? (
                <img src={selectedShot.firstFrameUrl} alt={`${selectedShot.title} 首帧`} className={`director-preview-media ${compiling ? "is-running" : ""}`} />
              ) : (
                <div className="director-preview-empty"><Film size={34} /><strong>{selectedShot ? "这个镜头还没有成片" : "从剧本开始或手动添加第一个镜头"}</strong><span>{selectedShot ? "先补充提示词和参考图，再生成当前镜头" : "AI 拆分剧本会自动生成可编辑的镜头序列"}</span></div>
              )}
              {selectedShot?.outputVideoUrl ? (
                <div className="director-preview-hud">
                  <div className="director-preview-hud-meta">
                    <span>{formatTimecode(previewTime)} / {formatTimecode(selectedShot.durationSec)}</span>
                    {compiling ? <strong>{directorShotStatus(selectedShot.status, selectedShot.progress).label}</strong> : <span>{activeProject.title}</span>}
                  </div>
                  <div className="director-preview-hud-bar"><span style={{ width: `${Math.min(100, (previewTime / Math.max(0.1, selectedShot.durationSec)) * 100)}%` }} /></div>
                  <div className="director-preview-hud-controls">
                    <button type="button" aria-label="上一镜" onClick={() => {
                      const index = activeProject.shots.findIndex((shot) => shot.id === selectedShot.id)
                      if (index > 0) setSelectedShotId(activeProject.shots[index - 1].id)
                    }}><SkipBack size={18} /></button>
                    <button type="button" className="director-play" aria-label={previewPlaying ? "暂停" : "播放"} onClick={togglePreviewPlayback}>{previewPlaying ? <Pause size={28} /> : <Play size={28} />}</button>
                    <button type="button" aria-label="下一镜" onClick={() => {
                      const index = activeProject.shots.findIndex((shot) => shot.id === selectedShot.id)
                      if (index >= 0 && index < activeProject.shots.length - 1) setSelectedShotId(activeProject.shots[index + 1].id)
                    }}><SkipForward size={18} /></button>
                  </div>
                </div>
              ) : null}
              {compiling && selectedShot ? <div className="director-preview-progress"><b>{selectedShot.progress || 0}<small>%</small></b><span>{directorProgressCaption(selectedShot.status)}</span></div> : null}
            </div>
          )}

          <div className="director-context-actions">
            <Button size="middle" onClick={() => firstFrameInputRef.current?.click()} icon={<ImagePlus size={14} />}>首帧</Button>
            <Button size="middle" onClick={() => endFrameInputRef.current?.click()} icon={<ImagePlus size={14} />}>尾帧</Button>
            <span className="director-context-divider" />
            <Button size="middle" onClick={() => selectedShot && handleChainToNext(selectedShot)}>续接上一镜</Button>
            <Button size="middle" disabled={!selectedShot || compiling} onClick={() => selectedShot && renderShot(selectedShot, { renderPass: "preview" })}>预览渲染</Button>
            <Button size="middle" disabled={!selectedShot || compiling} onClick={() => selectedShot && renderShot(selectedShot, { renderPass: "final" })}>成片渲染</Button>
          </div>
          <input ref={firstFrameInputRef} type="file" accept="image/*" hidden onChange={(event) => { handleAnchorUpload("first", event.target.files?.[0]); event.currentTarget.value = "" }} />
          <input ref={endFrameInputRef} type="file" accept="image/*" hidden onChange={(event) => { handleAnchorUpload("end", event.target.files?.[0]); event.currentTarget.value = "" }} />

          <details className="director-continuity-summary">
            <summary><span>续接轨道</span><span>展开</span></summary>
            <div className="director-continuity-ruler"><span>0s</span><span>5s</span><span>10s</span><span>15s</span><i style={{ left: `${Math.min(94, ((currentTimeSec || 5) / Math.max(15, timelineDurationSec)) * 100)}%` }} /></div>
            <div className="director-reference-chips" style={{ padding: "9px 12px 12px" }}>{(selectedShot?.referencedSubjectIds || []).map((id) => <span key={id} className="director-ref-chip">{slotLabel(id)}</span>)}{!(selectedShot?.referencedSubjectIds || []).length ? <span>选择右侧主体引用，保持角色和场景连续</span> : null}</div>
          </details>
        </main>

        <aside className="director-inspector-panel">
          <div className="director-inspector-tabs">
            <button type="button" className={inspectorTab === "shot" ? "is-active" : ""} onClick={() => setInspectorTab("shot")}>镜头</button>
            <button type="button" className={inspectorTab === "subjects" ? "is-active" : ""} onClick={() => setInspectorTab("subjects")}>主体</button>
            <button type="button" className={inspectorTab === "run" ? "is-active" : ""} onClick={() => setInspectorTab("run")}>运行</button>
          </div>
          {!selectedShot ? (
            <div className="director-inspector-empty"><Sliders size={28} /><span>选择镜头后可编辑画面锚点与提示词</span></div>
          ) : inspectorTab === "subjects" ? (
            <div className="director-inspector-scroll director-inspector-subjects">
              <TimelineTrackSubjects
                subjectSlots={activeProject.subjectSlots || []}
                onUpdateSlot={(slot) => updateActiveProject((proj) => ({ ...proj, subjectSlots: proj.subjectSlots.map((s) => (s.id === slot.id ? slot : s)) }))}
                onInsertSlotTagToShot={(slotId) => {
                  updateActiveProject((proj) => ({
                    ...proj,
                    shots: proj.shots.map((shot) => shot.id === selectedShot.id
                      ? { ...shot, prompt: shot.prompt ? `${shot.prompt} ${slotId}` : slotId, referencedSubjectIds: Array.from(new Set([...shot.referencedSubjectIds, slotId])) }
                      : shot),
                  }))
                  message.success(`已将 ${slotId} 插入镜头 #${selectedShot.shotNumber}`)
                }}
                onAnalyzeSlot={handleAnalyzeSlot}
                analyzeDisabledReason={analyzeDisabledReason}
              />
            </div>
          ) : inspectorTab === "run" && shotSubmission ? (
            <div className="director-inspector-scroll">
              <CompiledPromptInspector project={activeProject} submission={shotSubmission} clipSubmission={clipSubmission} previewMode={previewMode} onPreviewModeChange={setPreviewMode} onUpdateProject={(updated) => updateActiveProject(() => updated)} onSubmitClip={handleSubmitClip} />
            </div>
          ) : (
            <div className="director-inspector-scroll">
              <section className="director-inspector-section">
                <div className="director-inspector-heading">镜头时长</div>
                <div className="director-duration-row">
                  <InputNumber min={H3_MIN_DURATION_SEC} max={H3_MAX_DURATION_SEC} value={selectedShot.durationSec || H3_MIN_DURATION_SEC} onChange={(val) => updateActiveProject((proj) => ({ ...proj, shots: proj.shots.map((shot) => shot.id === selectedShot.id ? { ...shot, durationSec: snapH3DurationSec(val ?? H3_MIN_DURATION_SEC) } : shot) }))} />
                  <span>秒（{Math.round((selectedShot.durationSec || H3_MIN_DURATION_SEC) * activeProject.fps)} 帧）</span>
                </div>
              </section>
              <section className="director-inspector-section">
                <div className="director-inspector-heading"><span>画面锚点</span><button type="button" onClick={() => setInspectorOpen(true)}>编辑</button></div>
                <div className="director-anchor-grid">
                  <button type="button" onClick={() => firstFrameInputRef.current?.click()} className="director-anchor-slot">{selectedShot.firstFrameUrl ? <img src={selectedShot.firstFrameUrl} alt="首帧" /> : <><Plus size={17} /><span>首帧插槽</span></>}</button>
                  <button type="button" onClick={() => endFrameInputRef.current?.click()} className="director-anchor-slot">{selectedShot.endFrameUrl ? <img src={selectedShot.endFrameUrl} alt="尾帧" /> : <><Plus size={17} /><span>尾帧插槽</span></>}</button>
                </div>
              </section>
              <section className="director-inspector-section">
                <div className="director-inspector-heading">镜头提示词</div>
                <div className="director-prompt-box">
                  <Input.TextArea value={selectedShot.prompt} onChange={(e) => updateActiveProject((proj) => ({ ...proj, shots: proj.shots.map((shot) => shot.id === selectedShot.id ? { ...shot, prompt: e.target.value } : shot) }))} rows={4} placeholder="描述主体动作、场景细节与光影..." className="director-prompt-input" />
                  <div className="director-reference-chips" style={{ marginTop: 8 }}>
                    {selectedShot.referencedSubjectIds.map((id) => <span key={id} className="director-ref-chip">{slotLabel(id)}</span>)}
                    {!selectedShot.referencedSubjectIds.length ? <span className="director-muted-copy">在主体页选择引用</span> : null}
                  </div>
                </div>
              </section>
              <section className="director-inspector-section">
                <div className="director-inspector-heading"><span>摄影机参数</span><button type="button" onClick={() => setCameraModalOpen(true)}>调整</button></div>
                <div className="director-camera-tags">
                  <button type="button" className="director-camera-tag" onClick={() => setCameraModalOpen(true)}>{cameraZh(CAMERA_SCALE_LABELS[selectedShot.camera.scale]?.label)}</button>
                  <button type="button" className="director-camera-tag" onClick={() => setCameraModalOpen(true)}>{cameraZh(CAMERA_MOVEMENT_LABELS[selectedShot.camera.movement]?.label)}</button>
                  <button type="button" className="director-camera-tag" onClick={() => setCameraModalOpen(true)}>{cameraZh(CAMERA_ANGLE_LABELS[selectedShot.camera.angle]?.label)}</button>
                  <button type="button" className="director-camera-tag" onClick={() => setCameraModalOpen(true)}>{cameraZh(CAMERA_LIGHTING_LABELS[selectedShot.camera.lighting]?.label)}</button>
                </div>
              </section>
              <div className="director-inspector-footer">
                <div className={`director-compile-card ${compileOk ? "" : "is-error"}`}>
                  <div>
                    <div className="director-compile-ok">{compileLabel}</div>
                    <div className="director-compile-copy">{compileOk ? `预览 ${previewJob.quality} MP / ${directorSpeedSteps(previewJob.speed)} 步 · 成片 ${finalJob.quality} MP / ${directorSpeedSteps(finalJob.speed)} 步` : shotSubmission?.errors[0]}</div>
                  </div>
                  <span className="director-compile-ok">{compileOk ? "无错误" : "待处理"}</span>
                </div>
                {compiling ? (
                  <Button type="primary" danger block loading={false} onClick={() => cancelShot(selectedShot)} icon={<CircleStop size={15} />} className="director-primary-button director-generate-shot">停止生成</Button>
                ) : (
                  <div className="director-generate-pair">
                    <Button block disabled={!compileOk} onClick={() => renderShot(selectedShot, { renderPass: "preview" })}>预览渲染</Button>
                    <Button type="primary" block disabled={!compileOk} onClick={() => renderShot(selectedShot, { renderPass: "final" })} icon={<Play size={15} />} className="director-primary-button director-generate-shot">成片渲染</Button>
                  </div>
                )}
              </div>
            </div>
          )}
        </aside>
      </div>

      <section className="director-timeline-panel">
        <TimelineRuler totalDurationSec={timelineDurationSec} currentTimeSec={currentTimeSec} pixelsPerSecond={pixelsPerSecond} unit={rulerUnit} snapEnabled={snapEnabled} onSeek={setCurrentTimeSec} onUnitToggle={() => setRulerUnit((unit) => unit === "seconds" ? "frames" : "seconds")} onZoomChange={setPixelsPerSecond} onSnapChange={setSnapEnabled} />
        <TimelineTrackMain
          shots={activeProject.shots || []}
          subjectSlots={activeProject.subjectSlots}
          selectedShotId={selectedShot?.id}
          pixelsPerSecond={pixelsPerSecond}
          currentTimeSec={currentTimeSec}
          onSelectShot={(shot) => { setSelectedShotId(shot.id); setInspectedShot(shot) }}
          onAddShot={() => updateActiveProject((proj) => ({ ...proj, shots: [...proj.shots, createEmptyShot(proj.shots.length + 1, timelineDurationSec, 5)] }))}
          onDeleteShot={(shotId) => updateActiveProject((proj) => ({ ...proj, shots: proj.shots.filter((shot) => shot.id !== shotId).map((shot, index) => ({ ...shot, shotNumber: index + 1, title: shot.title || `分镜 ${index + 1}` })) }))}
          onDuplicateShot={(shot) => updateActiveProject((proj) => ({ ...proj, shots: [...proj.shots, { ...shot, id: `shot-${Date.now()}`, shotNumber: proj.shots.length + 1, title: `${shot.title}（副本）`, takes: [], activeTakeIndex: 0, status: "idle", outputVideoUrl: undefined, jobId: undefined }] }))}
          onRenderShot={renderShot}
          onUpdateShotDuration={(shotId, durationSec) => updateActiveProject((proj) => ({ ...proj, shots: proj.shots.map((shot) => shot.id === shotId ? { ...shot, durationSec: snapH3DurationSec(durationSec) } : shot) }))}
          onOpenFrameScrubber={(shot) => { setScrubbingShot(shot); setScrubberOpen(true) }}
        />
      </section>

      {selectedShot && shotSubmission ? <details className="director-compiled-details"><summary>完整提示词与运行参数 <span>默认折叠，便于复现与排障</span></summary><CompiledPromptInspector project={activeProject} submission={shotSubmission} clipSubmission={clipSubmission} previewMode={previewMode} onPreviewModeChange={setPreviewMode} onUpdateProject={(updated) => updateActiveProject(() => updated)} onSubmitClip={handleSubmitClip} /></details> : null}

      <div className="director-mobile-bottom-bar">
        <button type="button" aria-label="打开镜头设置" onClick={() => selectedShot && setInspectorOpen(true)}><Sliders size={18} /></button>
        {selectedShot && (selectedShot.status === "running" || selectedShot.status === "queued" || selectedShot.status === "interrupted") ? (
          <button type="button" className="director-mobile-generate director-mobile-stop-span" onClick={() => void cancelShot(selectedShot)}><CircleStop size={17} />停止生成</button>
        ) : (
          <>
            <button type="button" className="director-mobile-preview" disabled={!selectedShot} onClick={() => selectedShot && renderShot(selectedShot, { renderPass: "preview" })}>预览</button>
            <button type="button" className="director-mobile-generate" disabled={!selectedShot || selectedShot.status === "running" || selectedShot.status === "queued"} onClick={() => selectedShot && renderShot(selectedShot, { renderPass: "final" })}><Play size={17} />成片</button>
          </>
        )}
        <button type="button" aria-label="打开故事板" onClick={() => setViewMode("storyboard")}><Grid size={18} /></button>
      </div>

      {selectedShot ? (
        <CameraControlModal
          open={cameraModalOpen}
          camera={selectedShot.camera}
          shotTitle={selectedShot.title}
          onSave={(nextCamera) => {
            updateActiveProject((proj) => ({
              ...proj,
              shots: proj.shots.map((shot) => shot.id === selectedShot.id ? { ...shot, camera: nextCamera } : shot),
            }))
            setCameraModalOpen(false)
          }}
          onCancel={() => setCameraModalOpen(false)}
        />
      ) : null}

      {/* 深度分镜检视器抽屉 */}
      <ShotInspectorDrawer
        open={inspectorOpen}
        shot={inspectedShot || activeProject.shots.find((s) => s.id === selectedShotId) || null}
        subjectSlots={activeProject.subjectSlots}
        onClose={() => setInspectorOpen(false)}
        onUpdateShot={(updated) => {
          setInspectedShot(updated)
          updateActiveProject((proj) => ({
            ...proj,
            shots: proj.shots.map((s) => (s.id === updated.id ? updated : s)),
          }))
        }}
        onRenderShot={(shot, renderPass = "final") => {
          renderShot(shot, { renderPass })
        }}
        onCancelShot={(shot) => {
          void cancelShot(shot)
        }}
        onOpenFrameScrubber={(shot) => {
          setScrubbingShot(shot)
          setScrubberOpen(true)
        }}
      />

      {/* 视频任意帧捕获定格器 */}
      {scrubbingShot && scrubbingShot.outputVideoUrl && (
        <FrameScrubberModal
          open={scrubberOpen}
          videoUrl={scrubbingShot.outputVideoUrl}
          sourceShotTitle={scrubbingShot.title}
          onClose={() => setScrubberOpen(false)}
          onCaptureFrame={(frameFile, frameDataUrl) => {
            const nextShot = activeProject.shots.find((s) => s.shotNumber === scrubbingShot.shotNumber + 1)
            if (nextShot) {
              updateActiveProject((proj) => ({
                ...proj,
                shots: proj.shots.map((s) =>
                  s.id === nextShot.id
                    ? {
                        ...s,
                        firstFrameFile: frameFile,
                        firstFrameUrl: frameDataUrl,
                        usePreviousEndFrame: true,
                      }
                    : s,
                ),
              }))
              message.success(`已将定格画面注入到下一分镜 #${nextShot.shotNumber} 首帧`)
            } else {
              // 作为当前镜头的尾帧
              updateActiveProject((proj) => ({
                ...proj,
                shots: proj.shots.map((s) =>
                  s.id === scrubbingShot.id
                    ? {
                        ...s,
                        endFrameFile: frameFile,
                        endFrameUrl: frameDataUrl,
                      }
                    : s,
                ),
              }))
              message.success(`已将定格画面存为当前分镜尾帧`)
            }
          }}
        />
      )}

      {/* AI 剧本智能拆解弹窗 */}
      <ScriptSplitModal
        open={scriptSplitModalOpen}
        csrfToken={csrfToken}
        initialScript={activeProject.sourceScript || ""}
        initialStyleVibe={activeProject.styleVibe || "电影级大片"}
        initialShotCount={activeProject.requestedShotCount || 4}
        applyLabel="应用到工程"
        onCancel={() => setScriptSplitModalOpen(false)}
        onApply={(result) => {
          void handleSplitApply(result)
          setScriptSplitModalOpen(false)
        }}
      />

      <ScriptDocumentDrawer
        open={scriptDocumentOpen}
        projectTitle={activeProject.title}
        sourceScript={activeProject.sourceScript || ""}
        styleVibe={activeProject.styleVibe}
        requestedShotCount={activeProject.requestedShotCount}
        saving={scriptSaving}
        onChangeScript={(value) => updateActiveProject((proj) => ({ ...proj, sourceScript: value }))}
        onSave={() => void handleSaveSourceScript()}
        onSplit={() => openScriptSplit("workspace")}
        onClose={() => setScriptDocumentOpen(false)}
      />

      <Modal
        title="如何应用这次拆分？"
        open={Boolean(pendingSplit)}
        onCancel={() => setPendingSplit(null)}
        okText={splitDisposition === "saveAs" ? "另存为新工程" : "替换当前分镜"}
        cancelText="取消"
        okButtonProps={{ danger: splitDisposition === "replace" && projectHasGeneratedTakes(activeProject) }}
        onOk={() => handleConfirmSplit()}
      >
        <p className="director-split-confirm-copy">
          {projectHasGeneratedTakes(activeProject)
            ? "当前工程已有生成结果。替换会清空已生成的 Take；另存会保留本工程，把新分镜和原文写入新工程。"
            : "替换会用新分镜覆盖当前时间轴；另存会新建工程，当前分镜保持不变。"}
        </p>
        <Radio.Group
          className="director-split-confirm-options"
          value={splitDisposition}
          onChange={(event) => setSplitDisposition(event.target.value)}
        >
          <Radio value="replace">替换当前分镜</Radio>
          <Radio value="saveAs">另存为新工程</Radio>
        </Radio.Group>
      </Modal>

      {/* 故事板成片连续串播播放器 */}
      <SequencePlayerModal
        open={sequencePlayerOpen}
        shots={activeProject.shots}
        projectTitle={activeProject.title}
        onClose={() => setSequencePlayerOpen(false)}
      />

      <JianyingExportModal
        open={jianyingOpen}
        onClose={() => setJianyingOpen(false)}
        items={jianyingItems}
        onRemoveItem={(id) => setJianyingItems((prev) => prev.filter((item) => item.id !== id))}
        defaultAspectRatio={jianyingAspectRatio(activeProject.aspectRatio)}
      />

    </div>
  )
}
