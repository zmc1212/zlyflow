import { useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Button, Card, Checkbox, Collapse, Drawer, Dropdown, Empty, Input, Modal, Progress, Segmented, Select, Space, Tag, Tooltip, Typography, message,
} from "antd"
import { ArrowLeft, Clapperboard, Film, ImagePlus, Library, MoreHorizontal, Play, RefreshCw, Wand2 } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { ApiRequestError, User } from "../api"
import JianyingExportModal from "../media/JianyingExportModal"
import type { JianyingMediaItem } from "../media/jianying-draft-builder"
import JobErrorNotice from "./components/JobErrorNotice"
import DirectorExportPanel from "./components/DirectorExportPanel"
import DirectorStageNav from "./components/DirectorStageNav"
import DirectorTaskHeader from "./components/DirectorTaskHeader"
import DirectorTimelineView from "./components/DirectorTimelineView"
import RecipeShotInspector from "./components/RecipeShotInspector"
import SequencePlayerModal from "./components/SequencePlayerModal"
import DirectorAssetLibrary from "./DirectorAssetLibrary"
import MediaPreviewModal from "../components/MediaPreviewModal"
import { DirectorMobileBottomBar, DirectorMobileHeader } from "./DirectorMobileChrome"
import {
  PLAN_GENERATION_CONNECTING,
  PLAN_GENERATION_FAILURE,
  PLAN_GENERATION_HINT,
  PLAN_GENERATION_LABEL,
  PLAN_GENERATION_SUCCESS,
  boardBatchConfirm,
  boardBatchLabel,
  muxBatchConfirm,
  muxBatchLabel,
  plateBatchConfirm,
  plateBatchLabel,
  ttsBatchConfirm,
  ttsBatchLabel,
} from "./action-copy"
import {
  cancelDirectorJob, cancelDirectorOperation, createDirectorOperation, generateDirectorAssets, generateDirectorStills,
  generateDirectorTts, getDirectorOperation, getDirectorProject,
  insertDirectorLibraryAssets, listDirectorArtStyles, listWorkflowModes, muxDirectorFilm, recipePayloadFromApi,
  saveRecipeAssetsToLibrary, downloadDirectorExport,
  updateDirectorProjectRecord, uploadDirectorBgm, uploadDirectorShotFrame,
  DirectorOperationResponse, DirectorProjectResponse,
} from "./director-api"
import { assetGenerationState, assetPreviewUrl, jobProgressFromJob, jobStoredImageUrl, jobVideoUrl, mergeDirectorStatus, overlaySubmittingState, shotGenerationState, shotStatusFromJob, summarizeJobError } from "./director-submit"
import { directorStatusColor, directorStatusLabel, isDirectorFailedStatus } from "./status-labels"
import { directorRenderPassLabel } from "./prompt-compiler"
import {
  createEmptyRecipe, featuredArtStyles, RECIPE_AGENT_LABELS, RECIPE_AGENT_ORDER, RECIPE_AGENT_RUNNING_MESSAGES,
  recipeShotsToPlayer,
  DIRECTOR_FINAL_CANVAS_OPTIONS, DIRECTOR_SPEED_OPTIONS, DIRECTOR_WEIGHT_OPTIONS, H3_CANVAS_PRESETS, applyRecipeOutputSettings,
  recipeCanvasPreset, DirectorQuality, DirectorSpeed, DirectorWeightProfile, userFacingCopy,
  estimateStoryboardSkeletonCount, recipePipelineProgress,
  insertRecipeShotAfter, removeRecipeShot, duplicateRecipeShot,
} from "./types"
import {
  artStylePreviewUrl, flattenRecipeShots, isPlaceholderRecipeBoard, recipeArtStyleFromCatalog,
  recipeAudio, recipeExportState, recipeSubtitles, shotIsMuxable,
  type RecipeAgentId, type RecipeAgentRunStatus, type RecipeCharacter, type RecipeLocation,
  type RecipeProject, type RecipeShot,
} from "./recipe-model"
import {
  DIRECTOR_RECIPE_VIEW_LABELS, RECIPE_STAGE_GROUPS, parseRecipeStage, recipeReadiness,
  resolveDirectorRecipeView, type DirectorRecipeView, type RecipeStageId,
} from "./recipe-readiness"
import { DEFAULT_DIRECTOR_WORKFLOW_FAMILY, directorWorkflowFamilies } from "./director-workflows"
import { hasLatestShotSubmissionFailure, mergeRecipeExecutionState } from "./recipe-execution"

type JobLike = {
  id: string
  status?: string
  stage?: string
  progress?: number
  error?: string | null
  outputs?: Array<{ kind?: string; download_url?: string; cloud_url?: string; path?: string }>
}

type SaveStatus = "idle" | "saving" | "saved" | "failed"
type RenderPass = "preview" | "final"
type BoardMode = "still" | RenderPass
type ContentConflict = { remote: DirectorProjectResponse }

function conflictProject(error: unknown): DirectorProjectResponse | null {
  if (!(error instanceof ApiRequestError) || error.status !== 409) return null
  const detail = error.body && typeof error.body === "object"
    ? (error.body as { detail?: unknown }).detail
    : null
  if (!detail || typeof detail !== "object") return null
  const record = detail as { code?: unknown; current_project?: unknown }
  if (record.code !== "DIRECTOR_CONTENT_CONFLICT" || !record.current_project || typeof record.current_project !== "object") {
    return null
  }
  return record.current_project as DirectorProjectResponse
}

function notifyFailure(error: unknown, fallback: string) {
  const raw = error instanceof Error ? error.message : typeof error === "string" ? error : ""
  message.error(summarizeJobError(raw).summary || fallback)
}

function failedAgentLog(recipe: RecipeProject): string {
  return recipe.agentStatus
    .filter((item) => item.status === "failed" && item.error)
    .map((item) => `${RECIPE_AGENT_LABELS[item.id]}：${item.error}`)
    .join("\n")
}

function useIsMobile(query = "(max-width: 767px)") {
  const [matches, setMatches] = useState(() => (
    typeof window !== "undefined" ? window.matchMedia(query).matches : false
  ))
  useEffect(() => {
    const media = window.matchMedia(query)
    const update = () => setMatches(media.matches)
    update()
    media.addEventListener("change", update)
    return () => media.removeEventListener("change", update)
  }, [query])
  return matches
}

const AGENT_ORDER: RecipeAgentId[] = RECIPE_AGENT_ORDER

interface DirectorRecipeStudioProps {
  projectId: string
  csrfToken: string
  user: User
  allJobs: JobLike[]
  onBack: () => void
  onExitDirector?: () => void
}

function ArtStyleCover({
  style,
  className = "director-style-cover",
  showPlaceholder = true,
}: {
  style: { id: string; name_zh?: string; imageUrl?: string | null }
  className?: string
  showPlaceholder?: boolean
}) {
  const [failed, setFailed] = useState(false)
  if (failed) {
    return showPlaceholder ? <div className={`${className} is-empty`.trim()}>无预览</div> : null
  }
  return (
    <img
      src={artStylePreviewUrl(style)}
      alt={style.name_zh || ""}
      className={className}
      onError={() => setFailed(true)}
    />
  )
}

function setLocalAgentStatus(
  recipe: RecipeProject,
  agentId: RecipeAgentId,
  status: RecipeAgentRunStatus,
  message?: string | null,
): RecipeProject {
  return {
    ...recipe,
    agentStatus: recipe.agentStatus.map((item) => (
      item.id === agentId
        ? {
            ...item,
            status,
            error: null,
            message: message === undefined
              ? (status === "running" ? RECIPE_AGENT_RUNNING_MESSAGES[agentId] : item.message)
              : message,
          }
        : item
    )),
  }
}

function formatElapsed(seconds: number): string {
  if (seconds < 8) return ""
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return minutes > 0 ? ` · 已 ${minutes} 分 ${rest} 秒` : ` · 已 ${rest} 秒`
}

function confirmHeavyAction(options: {
  title: string
  countLabel: string
  costLabel: string
}): Promise<boolean> {
  return new Promise((resolve) => {
    Modal.confirm({
      title: options.title,
      content: (
        <div className="director-heavy-confirm">
          <p>{options.countLabel}</p>
          <p className="director-output-hint">{options.costLabel}</p>
        </div>
      ),
      okText: "提交",
      cancelText: "取消",
      centered: true,
      onOk: () => resolve(true),
      onCancel: () => resolve(false),
    })
  })
}

function startLocalPipelineRun(
  recipe: RecipeProject,
  agents: RecipeAgentId[],
  runningId: RecipeAgentId = agents[0],
): RecipeProject {
  const runningIndex = agents.indexOf(runningId)
  return {
    ...recipe,
    pipelineRun: { agents, active: true },
    agentStatus: recipe.agentStatus.map((item) => {
      const index = agents.indexOf(item.id)
      if (item.id === runningId) {
        return { ...item, status: "running" as const, error: null, message: RECIPE_AGENT_RUNNING_MESSAGES[item.id] }
      }
      if (index > runningIndex) {
        return { ...item, status: "pending" as const, error: null, message: null }
      }
      return item
    }),
  }
}

export default function DirectorRecipeStudio({
  projectId, csrfToken, allJobs, onBack, onExitDirector,
}: DirectorRecipeStudioProps) {
  const queryClient = useQueryClient()
  const operationStorageKey = `director-operation:${projectId}`
  const [searchParams, setSearchParams] = useSearchParams()
  const [goal, setGoal] = useState("")
  const [recipe, setRecipe] = useState<RecipeProject>(() => createEmptyRecipe())
  const [running, setRunning] = useState(false)
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle")
  const [boardMode, setBoardMode] = useState<BoardMode>("preview")
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null)
  const [checkedShotIds, setCheckedShotIds] = useState<string[]>([])
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [styleDrawerOpen, setStyleDrawerOpen] = useState(false)
  const [libraryDrawerOpen, setLibraryDrawerOpen] = useState(false)
  const [styleKeyword, setStyleKeyword] = useState("")
  const [styleCategory, setStyleCategory] = useState<string | undefined>(undefined)
  const [playerOpen, setPlayerOpen] = useState(false)
  const [jianyingOpen, setJianyingOpen] = useState(false)
  const activeStage = parseRecipeStage(searchParams.get("stage")) ?? "script"
  const [ttsBusy, setTtsBusy] = useState(false)
  const [muxBusy, setMuxBusy] = useState(false)
  const [previewingCharacterId, setPreviewingCharacterId] = useState<string | null>(null)
  const [submittingShotIds, setSubmittingShotIds] = useState<string[]>([])
  const [submittingStillIds, setSubmittingStillIds] = useState<string[]>([])
  const [skeletonCount, setSkeletonCount] = useState(0)
  const [elapsedSec, setElapsedSec] = useState(0)
  const [activeOperationId, setActiveOperationId] = useState<string | null>(() => (
    typeof window === "undefined" ? null : window.localStorage.getItem(operationStorageKey)
  ))
  const [contentConflict, setContentConflict] = useState<ContentConflict | null>(null)
  const runStartedAtRef = useRef(0)
  const recipeRef = useRef(recipe)
  const goalRef = useRef(goal)
  const saveTimerRef = useRef<number | null>(null)
  const boardAutoRunRef = useRef(false)
  const projectRevisionRef = useRef(0)
  const contentRevisionRef = useRef(0)
  const editVersionRef = useRef(0)
  const savedEditVersionRef = useRef(0)
  const saveInFlightRef = useRef<Promise<boolean> | null>(null)
  const conflictRef = useRef<ContentConflict | null>(null)
  const handledOperationIdsRef = useRef(new Set<string>())
  const operationToastKeysRef = useRef(new Map<string, string>())
  const isMobile = useIsMobile()
  const activeView = resolveDirectorRecipeView(searchParams.get("view"), { mobile: isMobile })
  const isTimelineView = activeView === "timeline"

  const projectQuery = useQuery({
    queryKey: ["director-project", projectId],
    queryFn: () => getDirectorProject(projectId),
    refetchInterval: running || submittingShotIds.length > 0 || submittingStillIds.length > 0 ? 1500 : false,
  })
  const operationQuery = useQuery({
    queryKey: ["director-operation", activeOperationId],
    queryFn: () => getDirectorOperation(activeOperationId as string),
    enabled: Boolean(activeOperationId),
    refetchInterval: activeOperationId ? 1200 : false,
    retry: false,
  })
  const stylesQuery = useQuery({
    queryKey: ["director-art-styles"],
    queryFn: listDirectorArtStyles,
  })
  const modesQuery = useQuery({
    queryKey: ["modes"],
    queryFn: listWorkflowModes,
  })

  useEffect(() => {
    conflictRef.current = contentConflict
  }, [contentConflict])

  useEffect(() => {
    const row = projectQuery.data
    if (!row) return
    projectRevisionRef.current = row.revision || projectRevisionRef.current
    const payload = recipePayloadFromApi(row)
    if (payload) {
      const dirty = editVersionRef.current > savedEditVersionRef.current
      const executionOnly = submittingShotIds.length > 0
        || submittingStillIds.length > 0
        || operationQuery.data?.kind === "shot_render_prepare"
      const preserveLocalContent = contentRevisionRef.current > 0 && (dirty || executionOnly || Boolean(contentConflict)) && !running
      if (preserveLocalContent) {
        setRecipe((current) => mergeRecipeExecutionState(current, payload))
      } else {
        setRecipe(payload)
        contentRevisionRef.current = row.content_revision || contentRevisionRef.current
        savedEditVersionRef.current = editVersionRef.current
      }
    }
    setGoal((current) => current || row.source_script || payload?.script.fullStory || payload?.script.summary || "")
  }, [contentConflict, operationQuery.data?.kind, projectQuery.data, running, submittingShotIds.length, submittingStillIds.length])

  useEffect(() => {
    const operation = operationQuery.data
    if (!operation) return
    if (typeof window !== "undefined") window.localStorage.setItem(operationStorageKey, operation.id)
    if (operation.status === "queued" || operation.status === "running") {
      if (operation.kind === "plan_pipeline") {
        if (!runStartedAtRef.current) runStartedAtRef.current = Date.parse(operation.created_at) || Date.now()
        setRunning(true)
      } else {
        const requested = operation.request.shot_ids || []
        const targets = requested.length ? requested : flattenRecipeShots(recipeRef.current).map((shot) => shot.id)
        setSubmittingShotIds((current) => Array.from(new Set([...current, ...targets])))
      }
      return
    }
    if (handledOperationIdsRef.current.has(operation.id)) return
    handledOperationIdsRef.current.add(operation.id)

    void (async () => {
      try {
        const refreshed = await projectQuery.refetch()
        const row = refreshed.data
        const payload = row ? recipePayloadFromApi(row) : null
        if (operation.kind === "plan_pipeline") {
          if (payload && row) {
            recipeRef.current = payload
            setRecipe(payload)
            projectRevisionRef.current = row.revision
            contentRevisionRef.current = row.content_revision
            savedEditVersionRef.current = editVersionRef.current
            const nextShots = flattenRecipeShots(payload)
            if (nextShots.length) setSelectedShotId(nextShots[0].id)
          }
          const failedAgents = operation.result.failed_agents || payload?.agentStatus
            .filter((item) => item.status === "failed")
            .map((item) => item.id) || []
          if (operation.status === "succeeded" && failedAgents.length === 0) {
            const agents = operation.request.agents || []
            if (agents.includes("storyboard") && agents.length <= 2) {
              const count = payload ? flattenRecipeShots(payload).length : 0
              message.success(count ? `已根据剧本生成 ${count} 个镜头` : "分镜已生成")
              setActiveStage("storyboard")
            } else {
              message.success(PLAN_GENERATION_SUCCESS)
              setActiveStage("storyboard")
            }
          } else if (operation.status === "succeeded") {
            message.error(`生成未完整完成：${failedAgents.map((id) => RECIPE_AGENT_LABELS[id as RecipeAgentId] || id).join("、")}`)
          } else {
            notifyFailure(operation.error, operation.status === "cancelled" ? "生成已取消" : PLAN_GENERATION_FAILURE)
          }
        } else {
          const targets = operation.request.shot_ids?.length
            ? operation.request.shot_ids
            : flattenRecipeShots(recipeRef.current).map((shot) => shot.id)
          if (payload) setRecipe((current) => mergeRecipeExecutionState(current, payload))
          if (operation.status === "succeeded") {
            const submitted = operation.result.job_ids?.length || 0
            const rendered = payload ? flattenRecipeShots(payload).filter((shot) => targets.includes(shot.id)) : []
            const failed = rendered.filter((shot) => shot.error && !shot.jobId)
            if (!submitted) {
              message.warning(failed[0]?.error || "没有提交成功的镜头，请检查镜头素材后重试")
            } else if (failed.length) {
              message.warning(`已提交 ${submitted} 镜，${failed.length} 镜失败`)
            } else {
              const previewing = operation.request.render_pass === "preview"
              message.success(targets.length === 1
                ? (previewing ? "已提交预览" : "已提交这一镜")
                : (previewing ? "已提交全部预览" : "已提交分镜视频"))
            }
          } else {
            notifyFailure(operation.error, operation.status === "cancelled" ? "提交已取消" : "提交失败")
          }
          setSubmittingShotIds((current) => current.filter((id) => !targets.includes(id)))
          await queryClient.invalidateQueries({ queryKey: ["jobs"] })
        }
        await queryClient.invalidateQueries({ queryKey: ["director-projects"] })
      } finally {
        const toastKey = operationToastKeysRef.current.get(operation.id)
        if (toastKey) message.destroy(toastKey)
        operationToastKeysRef.current.delete(operation.id)
        if (operation.kind === "plan_pipeline") {
          runStartedAtRef.current = 0
          setRunning(false)
        }
        if (typeof window !== "undefined") window.localStorage.removeItem(operationStorageKey)
        setActiveOperationId((current) => current === operation.id ? null : current)
      }
    })()
  }, [operationQuery.data])

  useEffect(() => {
    const error = operationQuery.error
    if (!(error instanceof ApiRequestError) || error.status !== 404 || !activeOperationId) return
    if (typeof window !== "undefined") window.localStorage.removeItem(operationStorageKey)
    setActiveOperationId(null)
    runStartedAtRef.current = 0
    setRunning(false)
    setSubmittingShotIds([])
  }, [activeOperationId, operationQuery.error, operationStorageKey])

  useEffect(() => {
    setRecipe((prev) => {
      let changed = false
      const characters = prev.characters.map((item) => {
        if (!item.imageJobId) return item
        const job = allJobs.find((entry) => entry.id === item.imageJobId)
        const url = jobStoredImageUrl(job)
        if (url && url !== item.imageUrl) {
          changed = true
          return { ...item, imageUrl: url }
        }
        return item
      })
      const locations = prev.locations.map((item) => {
        if (!item.imageJobId) return item
        const job = allJobs.find((entry) => entry.id === item.imageJobId)
        const url = jobStoredImageUrl(job)
        if (url && url !== item.imageUrl) {
          changed = true
          return { ...item, imageUrl: url }
        }
        return item
      })
      const scenes = prev.scenes.map((scene) => ({
        ...scene,
        shots: scene.shots.map((shot) => {
          let next = shot
          if (shot.stillJobId) {
            const stillJob = allJobs.find((entry) => entry.id === shot.stillJobId)
            const stillUrl = jobStoredImageUrl(stillJob)
            const stillStatus = stillJob ? shotStatusFromJob(stillJob) : shot.stillStatus
            if ((stillUrl && stillUrl !== shot.stillUrl) || (stillStatus && stillStatus !== shot.stillStatus)) {
              changed = true
              next = { ...next, stillUrl: stillUrl || shot.stillUrl, stillStatus: stillStatus || shot.stillStatus }
            }
          }
          const takes = (next.takes || []).map((take) => {
            const takeJob = allJobs.find((entry) => entry.id === take.jobId)
            if (!takeJob) return take
            const status = mergeDirectorStatus(take.status, shotStatusFromJob(takeJob))
            const url = jobVideoUrl(takeJob)
            const progress = jobProgressFromJob(takeJob, take.progress || 0)
            if (status !== take.status || url !== take.videoUrl || progress !== take.progress) {
              changed = true
              return { ...take, status, videoUrl: url || take.videoUrl, progress }
            }
            return take
          })
          if (takes !== next.takes) next = { ...next, takes }
          const job = allJobs.find((entry) => entry.id === next.jobId)
          if (!job) return next
          const status = mergeDirectorStatus(next.status, shotStatusFromJob(job))
          const url = jobVideoUrl(job)
          const progress = jobProgressFromJob(job, next.progress || 0)
          if (status !== next.status || url !== next.outputVideoUrl || progress !== next.progress) {
            changed = true
            return { ...next, status, outputVideoUrl: url || next.outputVideoUrl, progress }
          }
          return next
        }),
      }))
      return changed ? { ...prev, characters, locations, scenes } : prev
    })
  }, [allJobs])

  const shots = useMemo(() => flattenRecipeShots(recipe), [recipe])
  const placeholderBoard = useMemo(
    () => isPlaceholderRecipeBoard(shots, goal, recipe.script.fullStory),
    [goal, recipe.script.fullStory, shots],
  )
  const visibleShots = placeholderBoard ? [] : shots
  const readiness = useMemo(() => recipeReadiness(recipe, goal), [goal, recipe])
  recipeRef.current = recipe
  goalRef.current = goal
  const renderPass: RenderPass = boardMode === "final" ? "final" : "preview"
  const completedShots = shots.filter((shot) => shot.status === "succeeded" && shot.outputVideoUrl)
  const failedShotIds = shots.filter((shot) => {
    if (boardMode === "still") {
      const stillJob = allJobs.find((entry) => entry.id === shot.stillJobId)
      const status = stillJob
        ? mergeDirectorStatus(shot.stillStatus || "idle", shotStatusFromJob(stillJob))
        : (shot.stillStatus || "idle")
      return isDirectorFailedStatus(status)
    }
    const job = allJobs.find((entry) => entry.id === shot.jobId)
    const status = job ? mergeDirectorStatus(shot.status, shotStatusFromJob(job)) : shot.status
    return isDirectorFailedStatus(status) || hasLatestShotSubmissionFailure({ ...shot, status }, "video")
  }).map((shot) => shot.id)
  const outputPreset = recipeCanvasPreset(recipe)
  const aspectOptions = H3_CANVAS_PRESETS.filter((item) => item.tier === "native").map((item) => ({
    value: item.ratio,
    label: item.label.replace(/\s*\(.*$/, ""),
  }))
  const styles = stylesQuery.data?.styles || []
  const categories = stylesQuery.data?.categories || []
  const workflowFamilies = useMemo(
    () => directorWorkflowFamilies(modesQuery.data?.modes || []),
    [modesQuery.data],
  )
  const workflowFamilyId = recipe.videoWorkflowFamily || DEFAULT_DIRECTOR_WORKFLOW_FAMILY
  const workflowFamilyOptions = useMemo(() => {
    const options = workflowFamilies.map((item) => ({ value: item.id, label: item.label }))
    if (workflowFamilyId && !options.some((item) => item.value === workflowFamilyId)) {
      options.unshift({ value: workflowFamilyId, label: workflowFamilyId })
    }
    return options
  }, [workflowFamilies, workflowFamilyId])
  const recommendedStyles = useMemo(() => featuredArtStyles(styles), [styles])
  const filteredCatalogStyles = useMemo(() => {
    const keyword = styleKeyword.trim().toLowerCase()
    return styles.filter((style) => {
      if (styleCategory && style.category !== styleCategory) return false
      if (!keyword) return true
      return [style.name_zh, style.name_en, style.description, style.category_name_zh]
        .some((item) => (item || "").toLowerCase().includes(keyword))
    })
  }, [styles, styleCategory, styleKeyword])
  const selectedShot = visibleShots.find((shot) => shot.id === selectedShotId) || visibleShots[0] || null
  const selectedShotIndex = selectedShot ? visibleShots.findIndex((item) => item.id === selectedShot.id) : -1
  const previousShot = selectedShotIndex > 0 ? visibleShots[selectedShotIndex - 1] : null
  const checkedShots = visibleShots.filter((shot) => checkedShotIds.includes(shot.id))

  useEffect(() => {
    if (!visibleShots.length) {
      setSelectedShotId(null)
      return
    }
    if (!selectedShotId || !visibleShots.some((shot) => shot.id === selectedShotId)) {
      setSelectedShotId(visibleShots[0].id)
    }
  }, [visibleShots, selectedShotId])

  useEffect(() => {
    const validIds = new Set(visibleShots.map((shot) => shot.id))
    setCheckedShotIds((current) => {
      const next = current.filter((id) => validIds.has(id))
      return next.length === current.length ? current : next
    })
  }, [visibleShots])

  useEffect(() => () => {
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current)
  }, [])

  const completedAgents = recipe.agentStatus.filter((item) => item.status === "completed").length
  const pipeline = recipePipelineProgress(recipe.agentStatus, recipe.pipelineRun, AGENT_ORDER)
  const runningAgent = recipe.agentStatus.find((item) => item.id === pipeline.runningId) || recipe.agentStatus.find((item) => item.status === "running")
  const pipelineError = failedAgentLog(recipe)
  const pipelinePercent = pipeline.percent
  const storyboardAgent = recipe.agentStatus.find((item) => item.id === "storyboard")
  const generatingBoard = running && !visibleShots.length && (
    storyboardAgent?.status === "running" || storyboardAgent?.status === "pending" || pipeline.runningId === "script"
  )
  const skeletonTarget = estimateStoryboardSkeletonCount(recipe.script.fullStory, goal)

  useEffect(() => {
    if (!running) {
      setElapsedSec(0)
      return
    }
    const tick = () => {
      const started = runStartedAtRef.current
      setElapsedSec(started ? Math.max(0, Math.floor((Date.now() - started) / 1000)) : 0)
    }
    tick()
    const timer = window.setInterval(tick, 1000)
    return () => window.clearInterval(timer)
  }, [running])

  useEffect(() => {
    if (!generatingBoard) {
      setSkeletonCount(0)
      return
    }
    setSkeletonCount(Math.min(4, skeletonTarget))
    const timer = window.setInterval(() => {
      setSkeletonCount((count) => Math.min(skeletonTarget, count + 1))
    }, 700)
    return () => window.clearInterval(timer)
  }, [generatingBoard, skeletonTarget])

  async function persistNow(_next = recipeRef.current, extra?: { title?: string; source_script?: string }) {
    if (runStartedAtRef.current) return true
    if (conflictRef.current) return false
    if (saveInFlightRef.current) await saveInFlightRef.current
    if (runStartedAtRef.current) return true
    if (conflictRef.current) return false

    const snapshot = recipeRef.current
    const snapshotEditVersion = editVersionRef.current
    const request = (async () => {
      setSaveStatus("saving")
      try {
        const row = await updateDirectorProjectRecord(projectId, {
          title: extra?.title?.trim() || snapshot.script.title.trim() || "未命名导演工程",
          summary: snapshot.script.summary,
          source_script: extra?.source_script ?? goalRef.current,
          payload: snapshot,
          ...(contentRevisionRef.current > 0
            ? { expected_content_revision: contentRevisionRef.current }
            : {}),
        }, csrfToken)
        projectRevisionRef.current = row.revision
        contentRevisionRef.current = row.content_revision
        savedEditVersionRef.current = Math.max(savedEditVersionRef.current, snapshotEditVersion)
        setSaveStatus(editVersionRef.current === snapshotEditVersion ? "saved" : "idle")
        return true
      } catch (error) {
        const remote = conflictProject(error)
        if (remote) {
          const conflict = { remote }
          conflictRef.current = conflict
          setContentConflict(conflict)
          setSaveStatus("failed")
          return false
        }
        setSaveStatus("failed")
        notifyFailure(error, "保存失败")
        return false
      }
    })()
    saveInFlightRef.current = request
    try {
      return await request
    } finally {
      if (saveInFlightRef.current === request) saveInFlightRef.current = null
    }
  }

  function scheduleSave() {
    editVersionRef.current += 1
    if (runStartedAtRef.current || conflictRef.current) return
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current)
    saveTimerRef.current = window.setTimeout(() => {
      saveTimerRef.current = null
      void persistNow()
    }, 800)
  }

  async function flushSave() {
    if (saveTimerRef.current) {
      window.clearTimeout(saveTimerRef.current)
      saveTimerRef.current = null
    }
    return persistNow()
  }

  function loadRemoteConflictVersion() {
    if (!contentConflict) return
    const payload = recipePayloadFromApi(contentConflict.remote)
    if (payload) {
      recipeRef.current = payload
      setRecipe(payload)
    }
    const source = contentConflict.remote.source_script || payload?.script.fullStory || payload?.script.summary || ""
    goalRef.current = source
    setGoal(source)
    projectRevisionRef.current = contentConflict.remote.revision
    contentRevisionRef.current = contentConflict.remote.content_revision
    savedEditVersionRef.current = editVersionRef.current
    conflictRef.current = null
    setContentConflict(null)
    setSaveStatus("saved")
    queryClient.setQueryData(["director-project", projectId], contentConflict.remote)
  }

  async function overwriteRemoteConflict() {
    if (!contentConflict) return
    const snapshot = recipeRef.current
    setSaveStatus("saving")
    try {
      const row = await updateDirectorProjectRecord(projectId, {
        title: snapshot.script.title.trim() || "未命名导演工程",
        summary: snapshot.script.summary,
        source_script: goalRef.current,
        payload: snapshot,
        expected_content_revision: contentConflict.remote.content_revision,
        force: true,
      }, csrfToken)
      projectRevisionRef.current = row.revision
      contentRevisionRef.current = row.content_revision
      savedEditVersionRef.current = editVersionRef.current
      conflictRef.current = null
      setContentConflict(null)
      setSaveStatus("saved")
      queryClient.setQueryData(["director-project", projectId], row)
      message.success("已用当前窗口内容覆盖云端版本")
    } catch (error) {
      setSaveStatus("failed")
      notifyFailure(error, "覆盖保存失败")
    }
  }

  function patchStudioSearch(
    patch: { stage?: RecipeStageId; view?: DirectorRecipeView },
    options?: { replace?: boolean },
  ) {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (patch.stage) next.set("stage", patch.stage)
      if (patch.view === "plan") next.delete("view")
      else if (patch.view === "timeline") next.set("view", "timeline")
      if (next.toString() === prev.toString()) return prev
      return next
    }, options?.replace ? { replace: true } : undefined)
  }

  function setActiveStage(stage: RecipeStageId) {
    patchStudioSearch({ stage })
  }

  function setActiveView(view: DirectorRecipeView) {
    if (isMobile) return
    if (view === "timeline") {
      patchStudioSearch({ view: "timeline", stage: "shots" })
      return
    }
    patchStudioSearch({ view: "plan" })
  }

  function rememberDirectorOperation(operation: DirectorOperationResponse, toastKey?: string) {
    handledOperationIdsRef.current.delete(operation.id)
    if (toastKey) operationToastKeysRef.current.set(operation.id, toastKey)
    if (typeof window !== "undefined") window.localStorage.setItem(operationStorageKey, operation.id)
    queryClient.setQueryData(["director-operation", operation.id], operation)
    setActiveOperationId(operation.id)
  }

  async function handleCancelActiveOperation() {
    if (!activeOperationId) return
    try {
      const operation = await cancelDirectorOperation(activeOperationId, csrfToken)
      queryClient.setQueryData(["director-operation", activeOperationId], operation)
      message.info("已请求取消，当前步骤结束后会停止")
    } catch (error) {
      notifyFailure(error, "取消操作失败")
    }
  }

  async function handleRun() {
    const text = goal.trim()
    if (!text) {
      message.warning("请先写一句创意或故事")
      return
    }
    if (activeOperationId) {
      message.warning("已有导演操作正在执行，请完成或取消后再试")
      return
    }
    const saved = await flushSave()
    if (!saved) return
    boardAutoRunRef.current = true
    setRunning(true)
    runStartedAtRef.current = Date.now()
    setRecipe((current) => startLocalPipelineRun(
      setLocalAgentStatus(current, "research", "completed", "无事实核查需求，已跳过"),
      AGENT_ORDER,
      "script",
    ))
    try {
      const operation = await createDirectorOperation(projectId, {
        kind: "plan_pipeline",
        goal: text,
        art_style_id: recipe.artStyle?.id,
        skip_research: true,
      }, csrfToken)
      rememberDirectorOperation(operation)
    } catch (error) {
      notifyFailure(error, PLAN_GENERATION_FAILURE)
      runStartedAtRef.current = 0
      setRunning(false)
    }
  }

  async function handleRerun(agentId: RecipeAgentId) {
    if (agentId === "storyboard") {
      await handleGenerateStoryboard({ force: true })
      return
    }
    if (activeOperationId) {
      message.warning("已有导演操作正在执行，请完成或取消后再试")
      return
    }
    const saved = await flushSave()
    if (!saved) return
    setRunning(true)
    runStartedAtRef.current = Date.now()
    setRecipe((current) => startLocalPipelineRun(current, [agentId]))
    try {
      const operation = await createDirectorOperation(projectId, {
        kind: "plan_pipeline",
        goal,
        agents: [agentId],
        art_style_id: recipe.artStyle?.id,
        skip_research: agentId === "research",
      }, csrfToken)
      rememberDirectorOperation(operation)
    } catch (error) {
      notifyFailure(error, "重跑失败")
      runStartedAtRef.current = 0
      setRunning(false)
    }
  }

  async function handleGenerateStoryboard(options?: { force?: boolean }) {
    const current = recipeRef.current
    const currentShots = flattenRecipeShots(current)
    const idea = goalRef.current.trim()
    const story = current.script.fullStory.trim()
    const text = idea || story
    if (!text) {
      message.warning("请先写一句创意，或在「剧本」页写完整剧本")
      return
    }
    if (!options?.force && !isPlaceholderRecipeBoard(currentShots, idea, story)) {
      return
    }
    if (activeOperationId) {
      message.warning("已有导演操作正在执行，请完成或取消后再试")
      return
    }
    const hasRealScript = story.length >= 80 && story !== idea
    const agents = (hasRealScript ? ["storyboard"] : ["script", "storyboard"]) as RecipeAgentId[]
    if (saveTimerRef.current) {
      window.clearTimeout(saveTimerRef.current)
      saveTimerRef.current = null
    }
    const saved = await persistNow(current)
    if (!saved) return
    boardAutoRunRef.current = true
    setActiveStage("storyboard")
    setRunning(true)
    runStartedAtRef.current = Date.now()
    setRecipe((currentRecipe) => startLocalPipelineRun(currentRecipe, agents))
    try {
      const operation = await createDirectorOperation(projectId, {
        kind: "plan_pipeline",
        goal: text,
        art_style_id: current.artStyle?.id,
        skip_research: true,
        agents,
      }, csrfToken)
      rememberDirectorOperation(operation)
    } catch (error) {
      notifyFailure(error, "分镜生成失败")
      runStartedAtRef.current = 0
      setRunning(false)
    }
  }

  function handleStageChange(stage: RecipeStageId) {
    if (stage === "shots" && !isMobile) {
      patchStudioSearch({ stage, view: "timeline" })
    } else {
      patchStudioSearch({ stage, view: "plan" })
    }
    if ((stage === "storyboard" || stage === "shots") && !boardAutoRunRef.current) {
      boardAutoRunRef.current = true
      void handleGenerateStoryboard()
    }
  }

  useEffect(() => {
    if (activeStage !== "storyboard" && activeStage !== "shots") return
    if (boardAutoRunRef.current) return
    boardAutoRunRef.current = true
    void handleGenerateStoryboard()
  }, [activeStage])

  useEffect(() => {
    const raw = searchParams.get("view")
    if (raw == null) return
    if (raw === "plan") return
    if (raw === "timeline" && !isMobile) return
    patchStudioSearch({ view: "plan" }, { replace: true })
  }, [isMobile, searchParams])

  async function handleGenerateAssets(characterIds?: string[], locationIds?: string[], force = false) {
    try {
      const saved = await flushSave()
      if (!saved) return
      const row = await generateDirectorAssets(projectId, {
        character_ids: characterIds,
        location_ids: locationIds,
        force,
      }, csrfToken)
      const payload = recipePayloadFromApi(row)
      if (payload) setRecipe((current) => mergeRecipeExecutionState(current, payload))
      await queryClient.invalidateQueries({ queryKey: ["jobs"] })
      message.success("已提交定妆图任务")
    } catch (error) {
      notifyFailure(error, "定妆失败")
    }
  }

  async function handleSaveToLibrary(characterIds: string[] = [], locationIds: string[] = []) {
    try {
      const saved = await flushSave()
      if (!saved) return
      const result = await saveRecipeAssetsToLibrary({
        project_id: projectId,
        character_ids: characterIds,
        location_ids: locationIds,
      }, csrfToken)
      await queryClient.invalidateQueries({ queryKey: ["director-library-assets"] })
      message.success(`已存入资产库 ${result.imported} 项`)
    } catch (error) {
      notifyFailure(error, "存入资产库失败")
    }
  }

  async function handleInsertFromLibrary(assetIds: string[]) {
    try {
      const saved = await flushSave()
      if (!saved) return
      const row = await insertDirectorLibraryAssets(projectId, assetIds, csrfToken)
      const payload = recipePayloadFromApi(row)
      if (payload) setRecipe(payload)
      await queryClient.invalidateQueries({ queryKey: ["director-project", projectId] })
      setLibraryDrawerOpen(false)
      message.success(`已插入 ${assetIds.length} 项`)
    } catch (error) {
      notifyFailure(error, "插入资产失败")
    }
  }

  function submitTargets(shotIds?: string[]) {
    const visibleIds = new Set(visibleShots.map((shot) => shot.id))
    const requested = shotIds?.length ? shotIds : [...visibleIds]
    return Array.from(new Set(requested.filter((shotId) => visibleIds.has(shotId))))
  }

  function shotBoardState(shot: RecipeShot) {
    const submitting = submittingShotIds.includes(shot.id)
    return overlaySubmittingState(
      shotGenerationState(allJobs.find((entry) => entry.id === shot.jobId), shot.outputVideoUrl, shot.jobId, {
        status: shot.status,
        progress: shot.progress,
      }),
      submitting,
      "正在润色提示词并提交…",
    )
  }

  async function handleRender(shotIds?: string[]) {
    if (running) {
      message.warning("分镜还在生成，请等写完后再出片")
      return
    }
    const targets = submitTargets(shotIds)
    if (!targets.length) {
      message.warning("没有可生成的镜头")
      return
    }
    if (activeOperationId) {
      message.warning("已有导演操作正在执行，请完成或取消后再试")
      return
    }
    const toastKey = `director-render-${targets.join("|")}`
    message.loading({
      content: targets.length === 1 ? "正在润色提示词并提交这一镜…" : "正在润色提示词并提交分镜…",
      key: toastKey,
      duration: 0,
    })
    setSubmittingShotIds((current) => Array.from(new Set([...current, ...targets])))
    try {
      const saved = await flushSave()
      if (!saved) {
        message.destroy(toastKey)
        setSubmittingShotIds((current) => current.filter((id) => !targets.includes(id)))
        return
      }
      const operation = await createDirectorOperation(projectId, {
        kind: "shot_render_prepare",
        shot_ids: targets,
        render_pass: renderPass,
      }, csrfToken)
      rememberDirectorOperation(operation, toastKey)
    } catch (error) {
      notifyFailure(error, "提交失败")
      message.destroy(toastKey)
      setSubmittingShotIds((current) => current.filter((id) => !targets.includes(id)))
    }
  }

  async function handleStills(shotIds?: string[]) {
    if (running) {
      message.warning("分镜还在生成，请等写完后再出片")
      return
    }
    const targets = submitTargets(shotIds)
    if (!targets.length) {
      message.warning("没有可生成的镜头")
      return
    }
    const toastKey = `director-still-${targets.join("|")}`
    message.loading({
      content: targets.length === 1 ? "正在提交本镜静帧…" : "正在提交静帧…",
      key: toastKey,
      duration: 0,
    })
    setSubmittingStillIds((current) => Array.from(new Set([...current, ...targets])))
    try {
      const saved = await flushSave()
      if (!saved) return
      const row = await generateDirectorStills(projectId, { shot_ids: targets, force: true }, csrfToken)
      const payload = recipePayloadFromApi(row)
      if (payload) setRecipe((current) => mergeRecipeExecutionState(current, payload))
      await queryClient.invalidateQueries({ queryKey: ["jobs"] })
      message.success(targets.length === 1 ? "已提交本镜静帧" : "已提交静帧")
    } catch (error) {
      notifyFailure(error, "静帧失败")
    } finally {
      message.destroy(toastKey)
      setSubmittingStillIds((current) => current.filter((id) => !targets.includes(id)))
    }
  }

  async function handleBoardGenerate(shotIds?: string[]) {
    if (boardMode === "still") {
      await handleStills(shotIds)
      return
    }
    await handleRender(shotIds)
  }

  async function handleUploadFrame(shotId: string, slot: "first" | "end", file: File) {
    try {
      const saved = await flushSave()
      if (!saved) return
      const row = await uploadDirectorShotFrame(projectId, { shot_id: shotId, slot, file }, csrfToken)
      const payload = recipePayloadFromApi(row)
      if (payload) setRecipe((current) => mergeRecipeExecutionState(current, payload))
      message.success(slot === "end" ? "已保存尾帧" : "已保存首帧")
    } catch (error) {
      notifyFailure(error, "上传分镜帧失败")
    }
  }

  async function handleCancelShots(shotIds: string[]) {
    const targets = shots.filter((shot) => shotIds.includes(shot.id))
    const jobIds = targets.flatMap((shot) => [shot.jobId, shot.stillJobId]).filter((item): item is string => Boolean(item))
    const operation = operationQuery.data
    const requestedIds = operation?.request.shot_ids || []
    const cancelPreparingOperation = Boolean(
      activeOperationId
      && (operation?.kind === "shot_render_prepare" || submittingShotIds.some((id) => shotIds.includes(id)))
      && (!requestedIds.length || requestedIds.some((id) => shotIds.includes(id))),
    )
    if (!jobIds.length && !cancelPreparingOperation) {
      message.warning("选中的分镜没有正在生成的任务")
      return
    }
    try {
      await Promise.all([
        ...jobIds.map((jobId) => cancelDirectorJob(jobId, csrfToken)),
        ...(cancelPreparingOperation && activeOperationId
          ? [cancelDirectorOperation(activeOperationId, csrfToken)]
          : []),
      ])
      await queryClient.invalidateQueries({ queryKey: ["jobs"] })
      message.success(cancelPreparingOperation ? "已请求取消提交，正在收尾" : "已停止选中分镜")
    } catch (error) {
      notifyFailure(error, "停止失败")
    }
  }

  async function handleGenerateTts(shotIds?: string[], characterId?: string, text?: string) {
    try {
      const saved = await flushSave()
      if (!saved) return
      setTtsBusy(true)
      const row = await generateDirectorTts(projectId, {
        shot_ids: shotIds,
        character_id: characterId,
        text,
      }, csrfToken)
      const payload = recipePayloadFromApi(row)
      if (payload) setRecipe((current) => mergeRecipeExecutionState(current, payload))
      message.success(characterId ? "已生成角色试听" : shotIds?.length === 1 ? "已生成本镜配音" : "已生成全部配音")
    } catch (error) {
      notifyFailure(error, "配音失败")
    } finally {
      setTtsBusy(false)
      setPreviewingCharacterId(null)
    }
  }

  async function handlePreviewCharacter(character: RecipeCharacter) {
    setPreviewingCharacterId(character.id)
    await handleGenerateTts(undefined, character.id)
  }

  async function handleUploadBgm(file: File) {
    try {
      const saved = await flushSave()
      if (!saved) return
      const row = await uploadDirectorBgm(projectId, file, csrfToken)
      const payload = recipePayloadFromApi(row)
      if (payload) setRecipe((current) => mergeRecipeExecutionState(current, payload))
      message.success("配乐已上传")
    } catch (error) {
      notifyFailure(error, "上传配乐失败")
    }
  }

  async function handleMux() {
    try {
      const saved = await flushSave()
      if (!saved) return
      setMuxBusy(true)
      const row = await muxDirectorFilm(
        projectId,
        { burn_subtitles: Boolean(recipeExportState(recipeRef.current).burnSubtitles) },
        csrfToken,
      )
      const payload = recipePayloadFromApi(row)
      if (payload) setRecipe((current) => mergeRecipeExecutionState(current, payload))
      if (payload?.export?.muxStatus === "succeeded") {
        message.success("成片已导出")
      } else {
        notifyFailure(payload?.export?.muxError, "导出成片失败")
      }
    } catch (error) {
      notifyFailure(error, "导出成片失败")
    } finally {
      setMuxBusy(false)
      await queryClient.invalidateQueries({ queryKey: ["director-project", projectId] })
    }
  }

  async function requestGenerateAssets(characterIds?: string[], locationIds?: string[], force = false) {
    const charIds = characterIds || []
    const locIds = locationIds || []
    if (force && charIds.length + locIds.length === 1) {
      await handleGenerateAssets(characterIds, locationIds, force)
      return
    }
    const chars = recipe.characters.filter((item) => charIds.includes(item.id))
    const locs = recipe.locations.filter((item) => locIds.includes(item.id))
    const pending = [...chars, ...locs].filter((item) => !item.imageUrl).length
    const total = chars.length + locs.length
    const sceneOnly = locs.length > 0 && chars.length === 0
    const ok = await confirmHeavyAction(plateBatchConfirm(sceneOnly ? "location" : "character", total, pending))
    if (!ok) return
    await handleGenerateAssets(characterIds, locationIds, force)
  }

  async function requestBoardGenerate(shotIds?: string[], title?: string) {
    if (shotIds?.length === 1) {
      await handleBoardGenerate(shotIds)
      return
    }
    const targets = shotIds?.length ? shotIds : visibleShots.map((shot) => shot.id)
    const ok = await confirmHeavyAction(boardBatchConfirm(boardMode, targets.length, title))
    if (!ok) return
    await handleBoardGenerate(shotIds)
  }

  async function requestGenerateAllTts() {
    const count = shots.filter((shot) => shot.dialogue.trim()).length
    const ok = await confirmHeavyAction({
      title: "生成全部配音",
      countLabel: `将为 ${count} 条对白生成配音。`,
      costLabel: `预计消耗：${count} 次 TTS 调用；已有音频的镜头会重新生成。`,
    })
    if (!ok) return
    await handleGenerateTts()
  }

  async function requestMux() {
    const count = shots.filter(shotIsMuxable).length
    const ok = await confirmHeavyAction(muxBatchConfirm(count))
    if (!ok) return
    await handleMux()
  }

  async function handleDownloadExport(kind: "mux" | "fcpxml" | "edl") {
    const title = (recipe.script.title || "director").replace(/[^\w\u4e00-\u9fff-]+/g, "_") || "director"
    const suffix = kind === "mux" ? ".mp4" : kind === "fcpxml" ? ".fcpxml" : ".edl"
    try {
      await downloadDirectorExport(projectId, kind, `${title}${suffix}`)
    } catch (error) {
      notifyFailure(error, "下载失败")
    }
  }

  function toggleCheckedShot(shotId: string, checked: boolean) {
    setCheckedShotIds((current) => (
      checked ? Array.from(new Set([...current, shotId])) : current.filter((item) => item !== shotId)
    ))
  }

  function updateOutputSettings(patch: Partial<Pick<RecipeProject, "aspectRatio" | "finalQuality" | "finalSpeed" | "weightProfile" | "videoWorkflowFamily">>) {
    updateRecipe((current) => applyRecipeOutputSettings(current, patch))
  }

  function updateRecipe(updater: (current: RecipeProject) => RecipeProject) {
    setRecipe((current) => {
      const next = updater(current)
      recipeRef.current = next
      return next
    })
    scheduleSave()
  }

  function patchShot(shotId: string, patch: Partial<RecipeShot>) {
    updateRecipe((current) => ({
      ...current,
      scenes: current.scenes.map((scene) => ({
        ...scene,
        shots: scene.shots.map((shot) => shot.id === shotId ? { ...shot, ...patch } : shot),
      })),
    }))
  }

  function selectShot(shotId: string) {
    setSelectedShotId(shotId)
    if (isMobile) setInspectorOpen(true)
  }

  function handleAddShot() {
    let createdId: string | null = null
    updateRecipe((current) => {
      const next = insertRecipeShotAfter(current, selectedShotId)
      createdId = next.shot.id
      return next.recipe
    })
    if (createdId) setSelectedShotId(createdId)
  }

  function handleDeleteShot(shotId: string) {
    if (visibleShots.length <= 1) {
      message.warning("至少保留一镜")
      return
    }
    if (submittingShotIds.includes(shotId) || submittingStillIds.includes(shotId)) {
      message.warning("请先停止这一镜的生成任务")
      return
    }
    const nextSelectedId = selectedShotId === shotId
      ? visibleShots.find((item) => item.id !== shotId)?.id || null
      : selectedShotId
    setCheckedShotIds((current) => current.filter((item) => item !== shotId))
    setSelectedShotId(nextSelectedId)
    if (!nextSelectedId) setInspectorOpen(false)
    updateRecipe((current) => removeRecipeShot(current, shotId))
  }

  function handleDuplicateShot(shotId: string) {
    let createdId: string | null = null
    updateRecipe((current) => {
      const next = duplicateRecipeShot(current, shotId)
      if (!next) return current
      createdId = next.shot.id
      return next.recipe
    })
    if (createdId) setSelectedShotId(createdId)
  }

  const jianyingItems: JianyingMediaItem[] = completedShots.map((shot) => ({
    id: shot.id,
    title: shot.title,
    kind: "video",
    path: shot.outputVideoUrl || "",
    url: shot.outputVideoUrl || "",
    durationSeconds: shot.durationSec,
  }))
  const muxableCount = shots.filter(shotIsMuxable).length
  const pendingCharacterCount = recipe.characters.filter((item) => !item.imageUrl).length
  const pendingLocationCount = recipe.locations.filter((item) => !item.imageUrl).length
  const dialogueShotCount = shots.filter((shot) => shot.dialogue.trim()).length
  const planStagePrimary = activeStage === "script" || activeStage === "art_style"
  const characterActionLabel = plateBatchLabel("character", pendingCharacterCount || recipe.characters.length)
  const locationActionLabel = plateBatchLabel("location", pendingLocationCount || recipe.locations.length)
  const boardActionLabel = boardBatchLabel(boardMode, visibleShots.length)
  const ttsActionLabel = ttsBatchLabel(dialogueShotCount)
  const muxActionLabel = muxBatchLabel(muxableCount)
  const mobileTitle = recipe.script.title.trim() || "未命名导演工程"
  const mobilePrimary = running && activeOperationId
    ? {
      label: operationQuery.data?.cancel_requested ? "正在取消…" : "取消生成",
      onClick: () => { void handleCancelActiveOperation() },
      loading: Boolean(operationQuery.data?.cancel_requested),
      disabled: Boolean(operationQuery.data?.cancel_requested),
    }
    : activeStage === "characters" || activeStage === "locations"
    ? {
      label: activeStage === "locations" ? locationActionLabel : characterActionLabel,
      onClick: () => {
        void (activeStage === "locations"
          ? requestGenerateAssets([], recipe.locations.map((item) => item.id))
          : requestGenerateAssets(recipe.characters.map((item) => item.id), []))
      },
      loading: false,
      disabled: activeStage === "locations" ? !recipe.locations.length : !recipe.characters.length,
    }
    : activeStage === "storyboard" || activeStage === "shots"
      ? placeholderBoard
        ? {
          label: "根据剧本生成分镜",
          onClick: () => { void handleGenerateStoryboard({ force: true }) },
          loading: running,
          disabled: running,
        }
        : {
        label: boardActionLabel,
        onClick: () => { void requestBoardGenerate() },
        loading: submittingShotIds.length > 0 || submittingStillIds.length > 0,
        disabled: !visibleShots.length || running || submittingShotIds.length > 0 || submittingStillIds.length > 0,
      }
      : activeStage === "voice"
        ? {
          label: ttsActionLabel,
          onClick: () => { void requestGenerateAllTts() },
          loading: ttsBusy,
          disabled: ttsBusy || !dialogueShotCount,
        }
      : activeStage === "export"
        ? {
          label: muxActionLabel,
          onClick: () => { void requestMux() },
          loading: muxBusy,
          disabled: muxBusy || !muxableCount,
        }
      : {
        label: PLAN_GENERATION_LABEL,
        onClick: () => { void handleRun() },
        loading: running,
        disabled: running,
      }
  const projectDurationSec = visibleShots.reduce((sum, shot) => sum + shot.durationSec, 0)
  const projectMetaLabel = visibleShots.length
    ? `${visibleShots.length} 镜 · ${projectDurationSec} 秒 · ${recipe.aspectRatio}`
    : `${recipe.aspectRatio} · ${recipe.fps} fps`

  function handleTopMenu(key: string) {
    if (key === "workspace") onExitDirector?.()
    if (key === "export") {
      setActiveStage("export")
      void requestMux()
    }
    if (key === "jianying") setJianyingOpen(true)
  }

  return (
    <div className="director-recipe-shell !h-0 !min-h-0 flex-1 overflow-hidden" data-director-view={activeView}>
      <DirectorMobileHeader
        title={mobileTitle}
        onBack={onBack}
        menuItems={[
          { key: "studio", label: "创作工作台", onClick: onExitDirector },
          { key: "play", label: "串播", disabled: !completedShots.length, onClick: () => setPlayerOpen(true) },
          { key: "export", label: muxActionLabel, disabled: !muxableCount, onClick: () => { setActiveStage("export"); void requestMux() } },
          { key: "jianying", label: "剪映", disabled: !completedShots.length, onClick: () => setJianyingOpen(true) },
        ]}
      />
      <header className="director-topbar">
        <div className="director-project-heading">
          <button type="button" className="director-back-library" onClick={onBack}><ArrowLeft size={16} />工程库</button>
          <div className="director-project-identity">
            <Input
              variant="borderless"
              className="director-project-title"
              disabled={running}
              value={recipe.script.title}
              placeholder="未命名导演工程"
              onChange={(event) => updateRecipe((current) => ({
                ...current,
                script: { ...current.script, title: event.target.value },
              }))}
            />
            <div className="director-project-subline">
              <span>{projectMetaLabel}</span>
              {saveStatus === "failed" ? (
                <Tag className="director-project-meta" color="error" onClick={() => { void persistNow() }}>保存失败，重试</Tag>
              ) : (
                <Tag
                  className="director-project-meta"
                  color={saveStatus === "saving" ? "processing" : saveStatus === "saved" ? "success" : "default"}
                >
                  {saveStatus === "saving" ? "保存中" : saveStatus === "saved" ? "已保存" : "自动保存"}
                </Tag>
              )}
            </div>
          </div>
        </div>
        {!isMobile && (
          <Segmented
            className="director-view-switch"
            aria-label="导演台视图"
            value={activeView}
            options={[
              { label: DIRECTOR_RECIPE_VIEW_LABELS.plan, value: "plan" },
              { label: DIRECTOR_RECIPE_VIEW_LABELS.timeline, value: "timeline" },
            ]}
            onChange={(value) => setActiveView(value as DirectorRecipeView)}
          />
        )}
        <Space wrap className="director-top-actions">
          <Button icon={<Play size={14} />} disabled={!completedShots.length} onClick={() => setPlayerOpen(true)}>串播</Button>
          <Dropdown
            trigger={["click"]}
            menu={{
              items: [
                { key: "workspace", label: "返回创作工作台" },
                { key: "export", label: muxActionLabel, disabled: muxBusy || !muxableCount, icon: <Film size={14} /> },
                { key: "jianying", label: "剪映导出", disabled: !completedShots.length },
              ],
              onClick: ({ key }) => handleTopMenu(key),
            }}
          >
            <Button icon={<MoreHorizontal size={15} />}>更多</Button>
          </Dropdown>
          <Tooltip title={PLAN_GENERATION_HINT}>
            <Button type={planStagePrimary ? "primary" : "default"} icon={<Wand2 size={14} />} loading={running} onClick={handleRun}>
              {PLAN_GENERATION_LABEL}
            </Button>
          </Tooltip>
          {running && activeOperationId ? (
            <Button
              danger
              loading={Boolean(operationQuery.data?.cancel_requested)}
              disabled={Boolean(operationQuery.data?.cancel_requested)}
              onClick={() => { void handleCancelActiveOperation() }}
            >
              {operationQuery.data?.cancel_requested ? "正在取消" : "取消生成"}
            </Button>
          ) : null}
        </Space>
      </header>

      <div
        className={`director-recipe-layout${isTimelineView ? " is-timeline-view" : ""}`}
        aria-busy={running}
        {...(running ? { inert: true } : {})}
        {...(isTimelineView ? { role: "region" as const, "aria-label": "剪辑视图" } : {})}
      >
        {isTimelineView ? null : (
        <aside className="director-recipe-rail">
          <section className="director-brief-card" aria-labelledby="director-brief-title">
            <div className="director-brief-head">
              <span><Wand2 size={15} /><strong id="director-brief-title">创意简报</strong></span>
              <em>{goal.trim().length} 字</em>
            </div>
            <Input.TextArea
              value={goal}
              onChange={(event) => {
                const value = event.target.value
                setGoal(value)
                goalRef.current = value
                scheduleSave()
              }}
              autoSize={{ minRows: 4, maxRows: 8 }}
              placeholder="例如：雨夜里侦探穿过霓虹暗巷，追上一个撑红伞的女人。"
            />
            <p>生成方案只整理创意，不会自动消耗定妆、视频或配音额度。</p>
          </section>
          <DirectorStageNav
            activeStage={activeStage}
            readiness={readiness}
            defaultOpenGroups={
              isMobile
                ? [RECIPE_STAGE_GROUPS.find((group) => (group.stages as readonly RecipeStageId[]).includes(activeStage))?.id || "plan"]
                : RECIPE_STAGE_GROUPS.map((group) => group.id)
            }
            onSelect={handleStageChange}
          />
          <Collapse
            ghost
            className="director-agent-collapse"
            items={[{
              key: "agents",
              label: pipeline.stage ? `AI 运行详情 · ${pipeline.stage}` : "AI 运行详情",
              children: (
                <>
                  <div className="director-agent-progress">
                    <Progress
                      percent={pipelinePercent}
                      size="small"
                      status={running || runningAgent ? "active" : completedAgents === AGENT_ORDER.length ? "success" : "normal"}
                    />
                    <p>
                      {runningAgent
                        ? `正在运行：${RECIPE_AGENT_LABELS[runningAgent.id]}${pipeline.stage ? ` · ${pipeline.stage}` : ""}（${pipeline.completed} / ${pipeline.total}）${running ? formatElapsed(elapsedSec) : ""}`
                        : running
                          ? `${PLAN_GENERATION_CONNECTING}…${formatElapsed(elapsedSec)}`
                          : `已完成 ${completedAgents} / ${AGENT_ORDER.length} 步`}
                    </p>
                  </div>
                  <ol className="director-agent-list">
                    {AGENT_ORDER.map((agentId) => {
                      const item = recipe.agentStatus.find((entry) => entry.id === agentId)
                      const pending = !item || item.status === "pending" || item.status === "failed"
                      const generateBoard = agentId === "storyboard"
                      return (
                        <li key={agentId}>
                          <div className="director-agent-row">
                            <Tag color={directorStatusColor(item?.status)}>{RECIPE_AGENT_LABELS[agentId]}</Tag>
                            <Button
                              type="link"
                              size="small"
                              disabled={running}
                              onClick={() => generateBoard ? void handleGenerateStoryboard({ force: true }) : handleRerun(agentId)}
                            >
                              {pending || (generateBoard && placeholderBoard) ? "生成" : "重跑"}
                            </Button>
                          </div>
                          {item?.message && item.status !== "pending" ? (
                            <p className="director-agent-stage">{item.message}</p>
                          ) : null}
                          {item?.status === "failed" && item.error ? <JobErrorNotice error={item.error} /> : null}
                        </li>
                      )
                    })}
                  </ol>
                  {storyboardAgent?.message && storyboardAgent.status !== "pending" && storyboardAgent.status !== "running" ? (
                    <p className="director-agent-summary">最近一次分镜：{storyboardAgent.message}</p>
                  ) : null}
                </>
              ),
            }]}
          />
        </aside>
        )}

        <section className="director-recipe-main">
          {!isTimelineView ? (
            <DirectorTaskHeader
              activeStage={activeStage}
              readiness={readiness}
              onSelect={handleStageChange}
            />
          ) : null}
          {!isTimelineView && activeStage === "script" ? (
                  <div className="director-recipe-form">
                    <div className="director-mobile-brief-card">
                      <span>创意简报</span>
                      <Input.TextArea
                        value={goal}
                        autoSize={{ minRows: 3, maxRows: 6 }}
                        placeholder="用一句话描述你想拍的故事"
                        onChange={(event) => {
                          const value = event.target.value
                          setGoal(value)
                          goalRef.current = value
                          scheduleSave()
                        }}
                      />
                    </div>
                    <div className="director-script-sheet">
                      <label className="director-script-field">
                        <span>片名</span>
                        <Input
                          value={recipe.script.title}
                          placeholder="未命名故事"
                          onChange={(event) => updateRecipe((current) => ({
                            ...current, script: { ...current.script, title: event.target.value },
                          }))}
                        />
                      </label>
                      <label className="director-script-field">
                        <span>一句话梗概</span>
                        <Input.TextArea
                          value={recipe.script.summary}
                          placeholder="用一句话说清主角、目标与冲突"
                          autoSize={{ minRows: 2, maxRows: 4 }}
                          onChange={(event) => updateRecipe((current) => ({
                            ...current, script: { ...current.script, summary: event.target.value },
                          }))}
                        />
                      </label>
                      <label className="director-script-field is-story">
                        <span>完整故事 <em>{recipe.script.fullStory.trim().length} 字</em></span>
                        <Input.TextArea
                          value={recipe.script.fullStory}
                          placeholder="完整写下故事进展、关键动作、对白与结尾。分镜会严格从这里拆解。"
                          autoSize={{ minRows: 12, maxRows: 22 }}
                          onChange={(event) => updateRecipe((current) => ({
                            ...current, script: { ...current.script, fullStory: event.target.value },
                          }))}
                        />
                      </label>
                    </div>
                  </div>
          ) : null}
          {!isTimelineView && activeStage === "art_style" ? (
                  <div className="director-recipe-form">
                    <div className="director-style-toolbar">
                      <p>推荐 6 种常用画风。其余可按分类搜索，或浏览全部 34 条。</p>
                      <Button onClick={() => setStyleDrawerOpen(true)}>浏览全部</Button>
                    </div>
                    <div className="director-style-grid">
                      {recommendedStyles.map((style) => (
                        <button
                          key={style.id}
                          type="button"
                          className={`director-style-card${recipe.artStyle?.id === style.id ? " is-active" : ""}`}
                          onClick={() => updateRecipe((current) => ({
                            ...current,
                            artStyle: recipeArtStyleFromCatalog(style),
                          }))}
                        >
                          <ArtStyleCover style={style} />
                          <span className="director-style-copy">
                            <strong>{style.name_zh}</strong>
                            <span>{style.category_name_zh} · {style.name_en}</span>
                            <em>{style.description}</em>
                          </span>
                        </button>
                      ))}
                    </div>
                    {recipe.artStyle && !recommendedStyles.some((item) => item.id === recipe.artStyle?.id) ? (
                      <p className="director-output-hint">当前画风：{recipe.artStyle.name}</p>
                    ) : null}
                    <Drawer
                      title="全部画风"
                      open={styleDrawerOpen}
                      onClose={() => setStyleDrawerOpen(false)}
                      width={isMobile ? "100%" : 560}
                    >
                      <div className="director-style-filters">
                        <Select
                          allowClear
                          placeholder="分类"
                          value={styleCategory}
                          options={categories.map((item) => ({ value: item.id, label: item.name_zh }))}
                          onChange={(value?: string) => setStyleCategory(value)}
                        />
                        <Input
                          allowClear
                          placeholder="搜索画风"
                          value={styleKeyword}
                          onChange={(event) => setStyleKeyword(event.target.value)}
                        />
                      </div>
                      <div className="director-style-grid">
                        {filteredCatalogStyles.map((style) => (
                          <button
                            key={style.id}
                            type="button"
                            className={`director-style-card${recipe.artStyle?.id === style.id ? " is-active" : ""}`}
                            onClick={() => {
                              updateRecipe((current) => ({
                                ...current,
                                artStyle: recipeArtStyleFromCatalog(style),
                              }))
                              setStyleDrawerOpen(false)
                            }}
                          >
                            <ArtStyleCover style={style} />
                            <span className="director-style-copy">
                              <strong>{style.name_zh}</strong>
                              <span>{style.category_name_zh} · {style.name_en}</span>
                              <em>{style.description}</em>
                            </span>
                          </button>
                        ))}
                        {!filteredCatalogStyles.length && <Empty description="没有匹配的画风" />}
                      </div>
                    </Drawer>
                  </div>
          ) : null}
          {!isTimelineView && activeStage === "characters" ? (
                  <div className="director-asset-section">
                    <div className="director-section-head">
                      <Typography.Title level={5}>人物与道具 · {recipe.characters.length}</Typography.Title>
                      <Space wrap>
                        <Button size="small" icon={<Library size={14} />} onClick={() => setLibraryDrawerOpen(true)}>从库插入</Button>
                        <Button size="small" icon={<Library size={14} />} onClick={() => void handleSaveToLibrary(recipe.characters.map((item) => item.id), [])} disabled={!recipe.characters.length}>存入资产库</Button>
                        <Button type="primary" size="small" icon={<ImagePlus size={14} />} onClick={() => { void requestGenerateAssets(recipe.characters.map((item) => item.id), []) }}>{characterActionLabel}</Button>
                      </Space>
                    </div>
                    <div className="director-asset-grid">
                      {recipe.characters.map((character) => (
                        <AssetCard
                          key={character.id}
                          title={character.name}
                          description={userFacingCopy(character.description, character.name)}
                          imageUrl={character.imageUrl}
                          imageJobId={character.imageJobId}
                          kind="character"
                          job={allJobs.find((entry) => entry.id === character.imageJobId)}
                          onGenerate={() => handleGenerateAssets([character.id], [], true)}
                          onSaveToLibrary={() => void handleSaveToLibrary([character.id], [])}
                          onChange={(patch) => updateRecipe((current) => ({
                            ...current,
                            characters: current.characters.map((item) => item.id === character.id ? { ...item, ...patch } : item),
                          }))}
                        />
                      ))}
                      {!recipe.characters.length && <Empty description="生成创作方案或从资产库插入人物、道具" />}
                    </div>
                  </div>
          ) : null}
          {!isTimelineView && activeStage === "locations" ? (
                  <div className="director-asset-section">
                    <div className="director-section-head">
                      <Typography.Title level={5}>场景清单 · {recipe.locations.length}</Typography.Title>
                      <Space wrap>
                        <Button size="small" icon={<Library size={14} />} onClick={() => setLibraryDrawerOpen(true)}>从库插入</Button>
                        <Button size="small" icon={<Library size={14} />} onClick={() => void handleSaveToLibrary([], recipe.locations.map((item) => item.id))} disabled={!recipe.locations.length}>存入资产库</Button>
                        <Button type="primary" size="small" icon={<ImagePlus size={14} />} onClick={() => { void requestGenerateAssets([], recipe.locations.map((item) => item.id)) }}>{locationActionLabel}</Button>
                      </Space>
                    </div>
                    <div className="director-asset-grid">
                      {recipe.locations.map((location) => (
                        <AssetCard
                          key={location.id}
                          title={location.name}
                          description={userFacingCopy(location.description, location.name)}
                          imageUrl={location.imageUrl}
                          imageJobId={location.imageJobId}
                          kind="location"
                          job={allJobs.find((entry) => entry.id === location.imageJobId)}
                          onGenerate={() => handleGenerateAssets([], [location.id], true)}
                          onSaveToLibrary={() => void handleSaveToLibrary([], [location.id])}
                          onChange={(patch) => updateRecipe((current) => ({
                            ...current,
                            locations: current.locations.map((item) => item.id === location.id ? { ...item, ...patch } : item),
                          }))}
                        />
                      ))}
                      {!recipe.locations.length && <Empty description="生成创作方案或从资产库插入场景" />}
                    </div>
                  </div>
          ) : null}
          {isTimelineView ? (
            <DirectorTimelineView
              recipe={recipe}
              shots={visibleShots}
              selectedShot={selectedShot}
              previousShot={previousShot}
              checkedShotIds={checkedShotIds}
              jobs={allJobs}
              submittingShotIds={submittingShotIds}
              submittingStillIds={submittingStillIds}
              ttsBusy={ttsBusy}
              generatingBoard={generatingBoard}
              pipelineError={pipelineError}
              pipelinePercent={pipelinePercent}
              pipelineStage={pipeline.stage}
              boardActionLabel={boardActionLabel}
              boardBusy={submittingShotIds.length > 0 || submittingStillIds.length > 0}
              running={running}
              failedShotCount={failedShotIds.length}
              onSelectShot={selectShot}
              onSetCheckedShotIds={setCheckedShotIds}
              onChangeShot={patchShot}
              onAddShot={handleAddShot}
              onDeleteShot={handleDeleteShot}
              onDuplicateShot={handleDuplicateShot}
              onRenderShot={(shotId) => { void handleBoardGenerate([shotId]) }}
              onGenerateStill={(shotId) => { void handleStills([shotId]) }}
              onUploadFrame={handleUploadFrame}
              onExtractEndFrame={(shotId, file) => handleUploadFrame(shotId, "end", file)}
              onGenerateTts={(shotId) => { void handleGenerateTts([shotId]) }}
              onGenerateBoard={() => { void requestBoardGenerate() }}
              onGenerateSelected={() => { void requestBoardGenerate(checkedShotIds, "生成选中") }}
              onRetryFailed={() => { void requestBoardGenerate(failedShotIds, "仅重试失败项") }}
              onCancelSelected={() => { void handleCancelShots(checkedShotIds) }}
            />
          ) : null}
          {!isTimelineView && (activeStage === "storyboard" || activeStage === "shots") ? (
                  <div className="director-shot-section">
                    <div className="director-shot-commandbar">
                      <div className="director-shot-command-copy">
                        <Typography.Title level={5}>输出设置</Typography.Title>
                        <p className="director-output-hint">
                          {boardMode === "still"
                            ? "当前静帧：复用定妆同一 GRS 通道，出图后可设为首帧再出视频"
                            : renderPass === "preview"
                              ? `当前预览 ${recipe.previewQuality} MP · ${DIRECTOR_SPEED_OPTIONS.find((item) => item.value === recipe.previewSpeed)?.label || recipe.previewSpeed}`
                              : outputPreset
                                ? `当前终稿 ${outputPreset.width}×${outputPreset.height}`
                                : `当前终稿 ${recipe.finalQuality} MP`}
                          {boardMode === "final" && recipe.finalQuality !== "0.4" ? " · 16GB 显卡请改 0.4 MP 后再出片" : ""}
                          {boardMode !== "still" ? " · 文生 / 首尾帧 / 多参考按镜头素材自动匹配" : ""}
                          {activeStage === "shots" ? " · 生成创作方案不会出视频，需在本区提交出片" : ""}
                        </p>
                      </div>
                      <div className="director-output-settings">
                        <label className="director-setting-field is-workflow">
                          <span>视频工作流</span>
                          <Select
                            aria-label="工作流"
                            className="director-workflow-select"
                            value={workflowFamilyId}
                            options={workflowFamilyOptions}
                            onChange={(value: string) => updateOutputSettings({ videoWorkflowFamily: value })}
                            popupMatchSelectWidth={false}
                          />
                        </label>
                        <label className="director-setting-field">
                          <span>画面比例</span>
                          <Select
                            aria-label="画面比例"
                            value={recipe.aspectRatio}
                            options={aspectOptions}
                            onChange={(value: string) => updateOutputSettings({ aspectRatio: value })}
                            popupMatchSelectWidth={false}
                          />
                        </label>
                        <label className="director-setting-field is-pass">
                          <span>生成内容</span>
                          <Segmented
                            aria-label="渲染档位"
                            value={boardMode}
                            options={[
                              { label: "静帧", value: "still" },
                              { label: "预览", value: "preview" },
                              { label: "终稿", value: "final" },
                            ]}
                            onChange={(value) => setBoardMode(value as BoardMode)}
                          />
                        </label>
                        <label className="director-setting-field">
                          <span>分辨率</span>
                          <Select
                            aria-label="分辨率"
                            value={recipe.finalQuality}
                            options={DIRECTOR_FINAL_CANVAS_OPTIONS.map((item) => ({
                              value: item.quality,
                              label: item.label,
                            }))}
                            onChange={(value: DirectorQuality) => updateOutputSettings({ finalQuality: value })}
                            popupMatchSelectWidth={false}
                          />
                        </label>
                        <label className="director-setting-field">
                          <span>生成速度</span>
                          <Select
                            aria-label="生成速度"
                            value={recipe.finalSpeed}
                            options={DIRECTOR_SPEED_OPTIONS.map((item) => ({
                              value: item.value,
                              label: item.label,
                            }))}
                            onChange={(value: DirectorSpeed) => updateOutputSettings({ finalSpeed: value })}
                            popupMatchSelectWidth={false}
                          />
                        </label>
                        <label className="director-setting-field">
                          <span>模型体积</span>
                          <Select
                            aria-label="模型体积"
                            value={recipe.weightProfile || "full"}
                            options={DIRECTOR_WEIGHT_OPTIONS}
                            onChange={(value: DirectorWeightProfile) => updateOutputSettings({ weightProfile: value })}
                            popupMatchSelectWidth={false}
                          />
                        </label>
                      </div>
                      <div className="director-shot-actions">
                        <Space wrap>
                        <Button
                          loading={running}
                          disabled={running}
                          onClick={() => { void handleGenerateStoryboard({ force: true }) }}
                        >
                          {placeholderBoard || !visibleShots.length ? "根据剧本生成分镜" : "按剧本重新生成"}
                        </Button>
                        <Button disabled={!failedShotIds.length || running} onClick={() => { void requestBoardGenerate(failedShotIds, "仅重试失败项") }}>仅重试失败项（{failedShotIds.length}）</Button>
                        <Button disabled={!checkedShots.length || running} onClick={() => { void requestBoardGenerate(checkedShotIds, "生成选中") }}>生成选中（{checkedShots.length}）</Button>
                        <Button disabled={!checkedShots.length} onClick={() => { void handleCancelShots(checkedShotIds) }}>取消选中</Button>
                        </Space>
                        <Button
                          type="primary"
                          icon={<Clapperboard size={14} />}
                          loading={submittingShotIds.length > 0 || submittingStillIds.length > 0}
                          disabled={!visibleShots.length || running}
                          onClick={() => { void requestBoardGenerate() }}
                        >
                          {boardActionLabel}
                        </Button>
                      </div>
                    </div>
                    {visibleShots.length ? (
                      <div className="director-shot-workspace">
                        <aside className="director-shot-bin">
                          <div className="director-shot-list">
                            {visibleShots.map((shot) => {
                              const state = shotBoardState(shot)
                              const displayStatus = state.generating ? state.status : (state.status !== "idle" ? state.status : shot.status)
                              const selected = selectedShot?.id === shot.id
                              const takes = shot.takes || []
                              const latestTake = takes[takes.length - 1]
                              const thumb = shot.outputVideoUrl || shot.stillUrl || shot.firstFrameUrl
                              return (
                                <div
                                  key={shot.id}
                                  className={`director-shot-list-item${selected ? " director-shot-list-item-selected" : ""}`}
                                >
                                  <Checkbox
                                    className="director-shot-check"
                                    checked={checkedShotIds.includes(shot.id)}
                                    onClick={(event) => event.stopPropagation()}
                                    onChange={(event) => toggleCheckedShot(shot.id, event.target.checked)}
                                  />
                                  <button type="button" className="director-shot-list-button" onClick={() => selectShot(shot.id)}>
                                    <div className="director-shot-list-meta">
                                      <span>#{shot.shotNumber}</span>
                                      <span>{shot.durationSec}s</span>
                                    </div>
                                    <div className={`director-shot-thumb${state.generating ? " is-running" : ""}`}>
                                      {shot.outputVideoUrl ? (
                                        <video src={shot.outputVideoUrl} muted playsInline />
                                      ) : thumb ? (
                                        <img src={thumb} alt="" />
                                      ) : (
                                        <Clapperboard size={18} />
                                      )}
                                    </div>
                                    <div className="director-shot-list-title">{shot.title}</div>
                                    <div className="director-shot-list-status">
                                      <Tag color={directorStatusColor(displayStatus)}>{directorStatusLabel(displayStatus)}</Tag>
                                      {shot.stillUrl ? <Tag>静帧</Tag> : null}
                                      {latestTake?.renderPass ? <Tag>{directorRenderPassLabel(latestTake.renderPass)}</Tag> : null}
                                      {shot.approvedTakeId ? <Tag color="success">已批准</Tag> : null}
                                    </div>
                                  </button>
                                </div>
                              )
                            })}
                          </div>
                        </aside>
                        {!isMobile && selectedShot ? (
                          <RecipeShotInspector
                            shot={selectedShot}
                            recipe={recipe}
                            previousShot={previousShot}
                            job={allJobs.find((entry) => entry.id === selectedShot.jobId)}
                            stillJob={allJobs.find((entry) => entry.id === selectedShot.stillJobId)}
                            compareDesktop
                            onChange={(patch) => patchShot(selectedShot.id, patch)}
                            submitting={submittingShotIds.includes(selectedShot.id)}
                            submittingStill={submittingStillIds.includes(selectedShot.id)}
                            onRender={() => { void handleBoardGenerate([selectedShot.id]) }}
                            onGenerateStill={() => { void handleStills([selectedShot.id]) }}
                            onUploadFrame={(slot, file) => handleUploadFrame(selectedShot.id, slot, file)}
                            onExtractEndFrame={(file) => handleUploadFrame(selectedShot.id, "end", file)}
                            onGenerateTts={() => { void handleGenerateTts([selectedShot.id]) }}
                            ttsBusy={ttsBusy}
                          />
                        ) : null}
                      </div>
                    ) : generatingBoard ? (
                      <div className="director-shot-workspace is-generating">
                        <aside className="director-shot-bin">
                          <div className="director-shot-list" aria-busy="true" aria-label="正在生成分镜">
                            {Array.from({ length: Math.max(skeletonCount, 4) }, (_, index) => (
                              <div key={`skeleton-${index}`} className="director-shot-list-item is-skeleton">
                                <div className="director-shot-list-button">
                                  <div className="director-shot-list-meta">
                                    <span>#{index + 1}</span>
                                    <span>--s</span>
                                  </div>
                                  <div className="director-shot-thumb is-skeleton" />
                                  <div className="director-shot-list-title is-skeleton-text">镜头生成中</div>
                                  <div className="director-shot-list-status">
                                    <Tag>生成中</Tag>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </aside>
                        {!isMobile ? (
                          <div className="director-recipe-inspector director-board-generating">
                            <Typography.Title level={5}>正在生成分镜</Typography.Title>
                            <p>
                              {(pipeline.stage
                                || (pipeline.runningId === "script" ? "正在根据创意写剧本，写完后会拆成全部镜头" : "正在根据剧本拆全部镜头"))
                                + formatElapsed(elapsedSec)}
                            </p>
                            <Progress percent={pipelinePercent} status="active" />
                            <p className="director-output-hint">
                              大模型正在流式写分镜，字数增加就说明没卡住。不会展示模型原文或思考过程，镜头列表会在拆完后出现。
                            </p>
                          </div>
                        ) : (
                          <p className="director-board-generating-mobile">
                            {(pipeline.stage || "正在根据剧本生成全部分镜…") + formatElapsed(elapsedSec)}
                          </p>
                        )}
                      </div>
                    ) : (
                      <Empty
                        description={pipelineError ? "分镜生成失败" : "点击分镜后会根据剧本一次性生成全部镜头"}
                      >
                        {pipelineError ? <JobErrorNotice error={pipelineError} /> : null}
                        <Button
                          type="primary"
                          icon={<Clapperboard size={14} />}
                          loading={running}
                          disabled={running}
                          onClick={() => { void handleGenerateStoryboard({ force: true }) }}
                        >
                          根据剧本生成全部分镜
                        </Button>
                      </Empty>
                    )}
                  </div>
          ) : null}
          {!isTimelineView && (activeStage === "voice" || activeStage === "music" || activeStage === "export") ? (
                  <DirectorExportPanel
                    recipe={recipe}
                    ttsBusy={ttsBusy}
                    muxBusy={muxBusy}
                    previewingCharacterId={previewingCharacterId}
                    visibleSections={
                      activeStage === "voice"
                        ? ["ttsAlert", "voice"]
                        : activeStage === "music"
                          ? ["music"]
                          : ["ffmpegAlert", "subtitles", "film"]
                    }
                    onChangeRecipe={(patch) => updateRecipe((current) => ({ ...current, ...patch }))}
                    onGenerateAllTts={() => { void requestGenerateAllTts() }}
                    onPreviewCharacter={(character) => { void handlePreviewCharacter(character) }}
                    onChangeCharacterVoice={(characterId, voiceId) => updateRecipe((current) => ({
                      ...current,
                      characters: current.characters.map((item) => item.id === characterId ? { ...item, voiceId } : item),
                    }))}
                    onUploadBgm={(file) => { void handleUploadBgm(file) }}
                    onMux={() => { void requestMux() }}
                    onDownload={(kind) => { void handleDownloadExport(kind) }}
                    onPlaySequence={() => setPlayerOpen(true)}
                    onJianying={() => setJianyingOpen(true)}
                  />
          ) : null}
          <div className="director-recipe-scroll-end" aria-hidden="true" />
        </section>
      </div>

      <Modal
        open={Boolean(contentConflict)}
        title="检测到其他窗口的修改"
        closable={false}
        keyboard={false}
        maskClosable={false}
        footer={[
          <Button key="remote" type="primary" onClick={loadRemoteConflictVersion}>
            加载云端版本
          </Button>,
          <Button
            key="local"
            danger
            loading={saveStatus === "saving"}
            onClick={() => { void overwriteRemoteConflict() }}
          >
            用本窗口内容覆盖云端
          </Button>,
        ]}
      >
        <Typography.Paragraph>
          为避免丢失任何一方的创作内容，自动保存已暂停。请选择保留云端新版本，或明确用当前窗口覆盖它。
        </Typography.Paragraph>
        {contentConflict ? (
          <Typography.Text type="secondary">
            云端内容版本：{contentConflict.remote.content_revision}，更新时间：{contentConflict.remote.updated_at}
          </Typography.Text>
        ) : null}
      </Modal>
      <SequencePlayerModal
        open={playerOpen}
        projectTitle={recipe.script.title || "导演工程"}
        shots={recipeShotsToPlayer(completedShots)}
        subtitleStyle={recipeSubtitles(recipe)}
        audio={recipeAudio(recipe)}
        onClose={() => setPlayerOpen(false)}
        onBatchDeliver={() => { setPlayerOpen(false); setJianyingOpen(true) }}
      />
      <JianyingExportModal
        open={jianyingOpen}
        onClose={() => setJianyingOpen(false)}
        items={jianyingItems}
        defaultAspectRatio={recipe.aspectRatio === "9:16" ? "9:16" : "16:9"}
      />
      <Drawer
        title={selectedShot ? `#${selectedShot.shotNumber} ${selectedShot.title}` : "分镜"}
        open={isMobile && inspectorOpen && Boolean(selectedShot)}
        onClose={() => setInspectorOpen(false)}
        width="100%"
        destroyOnHidden
      >
        {selectedShot ? (
          <RecipeShotInspector
            shot={selectedShot}
            recipe={recipe}
            previousShot={previousShot}
            job={allJobs.find((entry) => entry.id === selectedShot.jobId)}
            stillJob={allJobs.find((entry) => entry.id === selectedShot.stillJobId)}
            compareDesktop={false}
            onChange={(patch) => patchShot(selectedShot.id, patch)}
            submitting={submittingShotIds.includes(selectedShot.id)}
            submittingStill={submittingStillIds.includes(selectedShot.id)}
            onRender={() => { void handleBoardGenerate([selectedShot.id]) }}
            onGenerateStill={() => { void handleStills([selectedShot.id]) }}
            onUploadFrame={(slot, file) => handleUploadFrame(selectedShot.id, slot, file)}
            onExtractEndFrame={(file) => handleUploadFrame(selectedShot.id, "end", file)}
            onGenerateTts={() => { void handleGenerateTts([selectedShot.id]) }}
            ttsBusy={ttsBusy}
          />
        ) : null}
      </Drawer>
      <Drawer
        title="从资产库插入"
        open={libraryDrawerOpen}
        onClose={() => setLibraryDrawerOpen(false)}
        width={isMobile ? "100%" : 520}
        destroyOnHidden
      >
        <DirectorAssetLibrary
          csrfToken={csrfToken}
          mode="picker"
          onInsert={handleInsertFromLibrary}
        />
      </Drawer>
      <DirectorMobileBottomBar
        label={mobilePrimary.label}
        onClick={mobilePrimary.onClick}
        loading={mobilePrimary.loading}
        disabled={mobilePrimary.disabled}
      />
    </div>
  )
}

function AssetCard({
  title,
  description,
  imageUrl,
  imageJobId,
  kind,
  job,
  onGenerate,
  onSaveToLibrary,
  onChange,
}: {
  title: string
  description: string
  imageUrl?: string | null
  imageJobId?: string | null
  kind: "character" | "location"
  job?: JobLike
  onGenerate: () => void
  onSaveToLibrary: () => void
  onChange: (patch: Partial<RecipeCharacter & RecipeLocation>) => void
}) {
  const [previewOpen, setPreviewOpen] = useState(false)
  const state = assetGenerationState(job, imageUrl, imageJobId, kind)
  const previewUrl = assetPreviewUrl(job, imageUrl, imageJobId)
  const showImage = Boolean(previewUrl) && !state.generating
  return (
    <Card
      className="director-asset-card"
      size="small"
      cover={showImage ? (
        <button type="button" className="director-asset-preview-trigger" onClick={() => setPreviewOpen(true)} aria-label={`放大查看${title}`}>
          <img src={previewUrl || ""} alt={title} className="director-asset-cover" />
          <span>放大查看</span>
        </button>
      ) : (
        <div className="director-asset-placeholder">
          {state.generating ? (
            <>
              <Progress percent={state.progress} size="small" status="active" showInfo={false} />
              <span className="director-asset-status">{state.label}</span>
            </>
          ) : state.status === "failed" || state.status === "interrupted" || state.status === "cancelled" ? (
            <span className="director-asset-error">{state.label}</span>
          ) : (
            kind === "location" ? "待生成场景" : "待定妆"
          )}
        </div>
      )}
    >
      <Input value={title} onChange={(event) => onChange({ name: event.target.value })} />
      <Input.TextArea
        value={description}
        autoSize={{ minRows: 2, maxRows: 4 }}
        onChange={(event) => onChange({ description: event.target.value })}
      />
      <div className="director-asset-card-actions">
        <JobErrorNotice error={state.error} />
        <Button size="small" icon={<RefreshCw size={12} />} loading={state.generating} onClick={onGenerate}>
          {isDirectorFailedStatus(state.status)
            ? "重试这一项"
            : showImage ? "重新定妆" : kind === "location" ? "生成场景" : "生成定妆"}
        </Button>
        <Button size="small" icon={<Library size={12} />} onClick={onSaveToLibrary}>
          存入资产库
        </Button>
      </div>
      {showImage && previewUrl ? <MediaPreviewModal
        open={previewOpen}
        kind="image"
        src={previewUrl}
        title={title}
        description={description}
        onClose={() => setPreviewOpen(false)}
        actions={[
          { key: "generate", label: kind === "location" ? "重新生成场景" : "重新生成定妆", icon: <RefreshCw size={15} />, type: "primary", onClick: () => { onGenerate(); setPreviewOpen(false) } },
          { key: "save", label: "存入资产库", icon: <Library size={15} />, onClick: () => { onSaveToLibrary(); setPreviewOpen(false) } },
        ]}
      /> : null}
    </Card>
  )
}
