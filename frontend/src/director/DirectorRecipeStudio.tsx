import { useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Button, Card, Checkbox, Collapse, Drawer, Empty, Input, Progress, Segmented, Select, Space, Tabs, Tag, Typography, message,
} from "antd"
import { ArrowLeft, Clapperboard, Film, ImagePlus, Library, Play, RefreshCw, Wand2 } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { User } from "../api"
import JianyingExportModal from "../media/JianyingExportModal"
import type { JianyingMediaItem } from "../media/jianying-draft-builder"
import JobErrorNotice from "./components/JobErrorNotice"
import DirectorExportPanel from "./components/DirectorExportPanel"
import RecipeShotInspector from "./components/RecipeShotInspector"
import SequencePlayerModal from "./components/SequencePlayerModal"
import DirectorAssetLibrary from "./DirectorAssetLibrary"
import MediaPreviewModal from "../components/MediaPreviewModal"
import { DirectorMobileBottomBar, DirectorMobileHeader } from "./DirectorMobileChrome"
import "./prompt-compiler.contract"
import {
  cancelDirectorJob, generateDirectorAssets, generateDirectorStills, generateDirectorTts, getDirectorProject,
  insertDirectorLibraryAssets, listDirectorArtStyles, listWorkflowModes, muxDirectorFilm, recipePayloadFromApi,
  renderDirectorShots, runDirectorRecipe, runDirectorRecipeStep, saveRecipeAssetsToLibrary, downloadDirectorExport,
  updateDirectorProjectRecord, uploadDirectorBgm, uploadDirectorShotFrame,
} from "./director-api"
import { assetGenerationState, assetPreviewUrl, jobProgressFromJob, jobStoredImageUrl, jobVideoUrl, mergeDirectorStatus, shotGenerationState, shotStatusFromJob, summarizeJobError } from "./director-submit"
import { directorStatusColor, directorStatusLabel, isDirectorFailedStatus } from "./status-labels"
import { directorRenderPassLabel } from "./prompt-compiler"
import {
  createEmptyRecipe, featuredArtStyles, flattenRecipeShots, RECIPE_AGENT_LABELS, RECIPE_AGENT_ORDER, RECIPE_AGENT_RUNNING_MESSAGES,
  RecipeAgentId, RecipeAgentRunStatus,
  RecipeCharacter, RecipeLocation, RecipeProject, RecipeShot, artStylePreviewUrl, recipeArtStyleFromCatalog, recipeShotsToPlayer,
  DIRECTOR_FINAL_CANVAS_OPTIONS, DIRECTOR_SPEED_OPTIONS, DIRECTOR_WEIGHT_OPTIONS, H3_CANVAS_PRESETS, applyRecipeOutputSettings,
  recipeCanvasPreset, DirectorQuality, DirectorSpeed, DirectorWeightProfile, userFacingCopy, recipeAudio, recipeExportState, recipeSubtitles,
  shotIsMuxable, isPlaceholderRecipeBoard, estimateStoryboardSkeletonCount, recipePipelineProgress,
} from "./types"
import { DEFAULT_DIRECTOR_WORKFLOW_FAMILY, directorWorkflowFamilies } from "./director-workflows"

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

function notifyFailure(error: unknown, fallback: string) {
  const raw = error instanceof Error ? error.message : ""
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
  const [activeTab, setActiveTab] = useState("story")
  const [ttsBusy, setTtsBusy] = useState(false)
  const [muxBusy, setMuxBusy] = useState(false)
  const [previewingCharacterId, setPreviewingCharacterId] = useState<string | null>(null)
  const [skeletonCount, setSkeletonCount] = useState(0)
  const runStartedAtRef = useRef(0)
  const recipeRef = useRef(recipe)
  const goalRef = useRef(goal)
  const saveTimerRef = useRef<number | null>(null)
  const boardAutoRunRef = useRef(false)
  const isMobile = useIsMobile()

  const projectQuery = useQuery({
    queryKey: ["director-project", projectId],
    queryFn: () => getDirectorProject(projectId),
    refetchInterval: running ? 1500 : false,
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
    const row = projectQuery.data
    if (!row) return
    const payload = recipePayloadFromApi(row)
    if (payload) {
      const updated = Date.parse(String(row.updated_at || ""))
      const started = runStartedAtRef.current
      const stale = started > 0 && Number.isFinite(updated) && updated < started - 2000
      if (!stale) setRecipe(payload)
    }
    if (!goal) setGoal(row.source_script || payload?.script.fullStory || payload?.script.summary || "")
  }, [projectQuery.data])

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
    return isDirectorFailedStatus(status)
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

  async function persistNow(next = recipeRef.current, extra?: { title?: string; source_script?: string }) {
    if (runStartedAtRef.current) return true
    setSaveStatus("saving")
    try {
      await updateDirectorProjectRecord(projectId, {
        title: extra?.title?.trim() || next.script.title.trim() || "未命名导演工程",
        summary: next.script.summary,
        source_script: extra?.source_script ?? goalRef.current,
        payload: next,
      }, csrfToken)
      setSaveStatus("saved")
      return true
    } catch (error) {
      setSaveStatus("failed")
      notifyFailure(error, "保存失败")
      return false
    }
  }

  function scheduleSave() {
    if (runStartedAtRef.current) return
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

  async function handleRun() {
    const text = goal.trim()
    if (!text) {
      message.warning("请先写一句创意或故事")
      return
    }
    setRunning(true)
    runStartedAtRef.current = Date.now()
    setRecipe((current) => startLocalPipelineRun(
      setLocalAgentStatus(current, "research", "completed", "无事实核查需求，已跳过"),
      AGENT_ORDER,
      "script",
    ))
    try {
      const row = await runDirectorRecipe({
        goal: text,
        project_id: projectId,
        art_style_id: recipe.artStyle?.id,
        skip_research: true,
      }, csrfToken)
      const payload = recipePayloadFromApi(row)
      if (payload) {
        setRecipe(payload)
        setActiveTab("board")
      }
      await queryClient.invalidateQueries({ queryKey: ["director-projects"] })
      message.success("导演流水线已完成")
    } catch (error) {
      notifyFailure(error, "流水线失败")
    } finally {
      runStartedAtRef.current = 0
      setRunning(false)
      await queryClient.invalidateQueries({ queryKey: ["director-project", projectId] })
    }
  }

  async function handleRerun(agentId: RecipeAgentId) {
    if (agentId === "storyboard") {
      await handleGenerateStoryboard({ force: true })
      return
    }
    setRunning(true)
    runStartedAtRef.current = Date.now()
    setRecipe((current) => startLocalPipelineRun(current, [agentId]))
    try {
      const row = await runDirectorRecipeStep(projectId, { agent_id: agentId, goal, art_style_id: recipe.artStyle?.id }, csrfToken)
      const payload = recipePayloadFromApi(row)
      if (payload) setRecipe(payload)
    } catch (error) {
      notifyFailure(error, "重跑失败")
    } finally {
      runStartedAtRef.current = 0
      setRunning(false)
      await queryClient.invalidateQueries({ queryKey: ["director-project", projectId] })
    }
  }

  async function handleGenerateStoryboard(options?: { force?: boolean }) {
    const current = recipeRef.current
    const currentShots = flattenRecipeShots(current)
    const idea = goalRef.current.trim()
    const story = current.script.fullStory.trim()
    const text = idea || story
    if (!text) {
      message.warning("请先写一句创意，或在「故事」页写完整剧本")
      return
    }
    if (!options?.force && !isPlaceholderRecipeBoard(currentShots, idea, story)) {
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
    setActiveTab("board")
    setRunning(true)
    runStartedAtRef.current = Date.now()
    setRecipe((currentRecipe) => startLocalPipelineRun(currentRecipe, agents))
    try {
      const row = await runDirectorRecipe({
        goal: text,
        project_id: projectId,
        art_style_id: current.artStyle?.id,
        skip_research: true,
        agents,
      }, csrfToken)
      const payload = recipePayloadFromApi(row)
      if (payload) {
        setRecipe(payload)
        const nextShots = flattenRecipeShots(payload)
        const storyboard = payload.agentStatus.find((item) => item.id === "storyboard")
        const scriptAgent = payload.agentStatus.find((item) => item.id === "script")
        if (nextShots.length) {
          message.success(`已根据剧本生成 ${nextShots.length} 个镜头`)
          setSelectedShotId(nextShots[0]?.id || null)
        } else {
          const agentError = failedAgentLog(payload)
          message.error(summarizeJobError(agentError || storyboard?.error || scriptAgent?.error || "").summary || "分镜生成失败，请查看错误日志后重试")
        }
      }
      await queryClient.invalidateQueries({ queryKey: ["director-projects"] })
    } catch (error) {
      notifyFailure(error, "分镜生成失败")
    } finally {
      runStartedAtRef.current = 0
      setRunning(false)
      await queryClient.invalidateQueries({ queryKey: ["director-project", projectId] })
    }
  }

  function handleTabChange(key: string) {
    setActiveTab(key)
    if (key === "board" && !boardAutoRunRef.current) {
      boardAutoRunRef.current = true
      void handleGenerateStoryboard()
    }
  }

  async function handleGenerateAssets(characterIds?: string[], locationIds?: string[], force = false) {
    try {
      const row = await generateDirectorAssets(projectId, {
        character_ids: characterIds,
        location_ids: locationIds,
        force,
      }, csrfToken)
      const payload = recipePayloadFromApi(row)
      if (payload) setRecipe(payload)
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
      await flushSave()
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

  async function handleRender(shotIds?: string[]) {
    try {
      const saved = await flushSave()
      if (!saved) return
      const row = await renderDirectorShots(projectId, { shot_ids: shotIds, render_pass: renderPass }, csrfToken)
      const payload = recipePayloadFromApi(row)
      if (payload) setRecipe(payload)
      await queryClient.invalidateQueries({ queryKey: ["jobs"] })
      const previewing = renderPass === "preview"
      message.success(
        shotIds?.length === 1
          ? (previewing ? "已提交预览" : "已提交这一镜")
          : (previewing ? "已提交全部预览" : "已提交分镜视频"),
      )
    } catch (error) {
      notifyFailure(error, "提交失败")
    }
  }

  async function handleStills(shotIds?: string[]) {
    try {
      const saved = await flushSave()
      if (!saved) return
      const row = await generateDirectorStills(projectId, { shot_ids: shotIds, force: true }, csrfToken)
      const payload = recipePayloadFromApi(row)
      if (payload) setRecipe(payload)
      await queryClient.invalidateQueries({ queryKey: ["jobs"] })
      message.success(shotIds?.length === 1 ? "已提交本镜静帧" : "已提交静帧")
    } catch (error) {
      notifyFailure(error, "静帧失败")
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
      if (payload) setRecipe(payload)
      message.success(slot === "end" ? "已保存尾帧" : "已保存首帧")
    } catch (error) {
      notifyFailure(error, "上传分镜帧失败")
    }
  }

  async function handleCancelShots(shotIds: string[]) {
    const targets = shots.filter((shot) => shotIds.includes(shot.id))
    const jobIds = targets.flatMap((shot) => [shot.jobId, shot.stillJobId]).filter((item): item is string => Boolean(item))
    if (!jobIds.length) {
      message.warning("选中的分镜没有正在生成的任务")
      return
    }
    try {
      await Promise.all(jobIds.map((jobId) => cancelDirectorJob(jobId, csrfToken)))
      await queryClient.invalidateQueries({ queryKey: ["jobs"] })
      message.success("已停止选中分镜")
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
      if (payload) setRecipe(payload)
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
      if (payload) setRecipe(payload)
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
      if (payload) setRecipe(payload)
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

  const jianyingItems: JianyingMediaItem[] = completedShots.map((shot) => ({
    id: shot.id,
    title: shot.title,
    kind: "video",
    path: shot.outputVideoUrl || "",
    url: shot.outputVideoUrl || "",
    durationSeconds: shot.durationSec,
  }))
  const muxableCount = shots.filter(shotIsMuxable).length
  const mobileTitle = recipe.script.title.trim() || "未命名导演工程"
  const mobilePrimary = activeTab === "assets"
    ? {
      label: "全部定妆",
      onClick: () => { void handleGenerateAssets() },
      loading: false,
      disabled: !recipe.characters.length && !recipe.locations.length,
    }
    : activeTab === "board"
      ? placeholderBoard
        ? {
          label: "根据剧本生成分镜",
          onClick: () => { void handleGenerateStoryboard({ force: true }) },
          loading: running,
          disabled: running,
        }
        : {
        label: boardMode === "still" ? "全部静帧" : renderPass === "preview" ? "全部预览" : "全部出片",
        onClick: () => { void handleBoardGenerate() },
        loading: false,
        disabled: !visibleShots.length,
      }
      : activeTab === "export"
        ? {
          label: "导出成片",
          onClick: () => { void handleMux() },
          loading: muxBusy,
          disabled: muxBusy || !muxableCount,
        }
      : {
        label: "运行导演流水线",
        onClick: () => { void handleRun() },
        loading: running,
        disabled: running,
      }

  return (
    <div className="director-recipe-shell !h-0 !min-h-0 flex-1 overflow-hidden">
      <DirectorMobileHeader
        title={mobileTitle}
        onBack={onBack}
        menuItems={[
          { key: "studio", label: "创作工作台", onClick: onExitDirector },
          { key: "play", label: "串播", disabled: !completedShots.length, onClick: () => setPlayerOpen(true) },
          { key: "export", label: "导出成片", disabled: !muxableCount, onClick: () => { setActiveTab("export"); void handleMux() } },
          { key: "jianying", label: "剪映", disabled: !completedShots.length, onClick: () => setJianyingOpen(true) },
        ]}
      />
      <header className="director-topbar">
        <button type="button" className="director-back-library" onClick={onBack}><ArrowLeft size={16} />返回</button>
        <div className="director-project-heading">
          <Input
            variant="borderless"
            className="director-project-title"
            value={recipe.script.title}
            placeholder="未命名导演工程"
            onChange={(event) => updateRecipe((current) => ({
              ...current,
              script: { ...current.script, title: event.target.value },
            }))}
          />
          <span className="director-project-meta">
            {saveStatus === "saving" ? "保存中" : saveStatus === "saved" ? "已保存" : saveStatus === "failed" ? (
              <button type="button" className="director-save-retry" onClick={() => { void persistNow() }}>保存失败，重试</button>
            ) : "Recipe"}
          </span>
        </div>
        <Space wrap className="director-top-actions">
          <Select
            aria-label="画面比例"
            value={recipe.aspectRatio}
            options={aspectOptions}
            onChange={(value: string) => updateOutputSettings({ aspectRatio: value })}
            popupMatchSelectWidth={false}
          />
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
          <Button onClick={onExitDirector}>创作工作台</Button>
          <Button icon={<Play size={14} />} disabled={!completedShots.length} onClick={() => setPlayerOpen(true)}>串播</Button>
          <Button
            type={activeTab === "export" ? "primary" : "default"}
            icon={<Film size={14} />}
            loading={muxBusy}
            disabled={muxBusy || !muxableCount}
            onClick={() => {
              setActiveTab("export")
              void handleMux()
            }}
          >
            导出成片
          </Button>
          <Button disabled={!completedShots.length} onClick={() => setJianyingOpen(true)}>剪映导出</Button>
          <Button type={activeTab === "export" ? "default" : "primary"} icon={<Wand2 size={14} />} loading={running} onClick={handleRun}>运行导演流水线</Button>
        </Space>
      </header>

      <div className="director-recipe-layout">
        <aside className="director-recipe-rail">
          <Typography.Title level={5}>一句话创意</Typography.Title>
          <Input.TextArea
            value={goal}
            onChange={(event) => {
              const value = event.target.value
              setGoal(value)
              goalRef.current = value
              scheduleSave()
            }}
            autoSize={{ minRows: 5, maxRows: 10 }}
            placeholder="例如：雨夜里侦探穿过霓虹暗巷，追上一个撑红伞的女人。"
          />
          <div className="director-agent-progress">
            <Progress
              percent={pipelinePercent}
              size="small"
              status={running || runningAgent ? "active" : completedAgents === AGENT_ORDER.length ? "success" : "normal"}
            />
            <p>
              {runningAgent
                ? `正在运行：${RECIPE_AGENT_LABELS[runningAgent.id]}${pipeline.stage ? ` · ${pipeline.stage}` : ""}（${pipeline.completed} / ${pipeline.total}）`
                : running
                  ? "正在连接导演流水线…"
                  : `已完成 ${completedAgents} / ${AGENT_ORDER.length} 步`}
            </p>
          </div>
          <Collapse
            ghost
            className="director-agent-collapse"
            items={[{
              key: "agents",
              label: pipeline.stage ? `AI 运行详情 · ${pipeline.stage}` : "AI 运行详情",
              children: (
                <>
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

        <section className="director-recipe-main">
          <Tabs
            className="director-recipe-tabs"
            activeKey={activeTab}
            onChange={handleTabChange}
            items={[
              {
                key: "story",
                label: "故事",
                children: (
                  <div className="director-recipe-form">
                    <Input
                      value={recipe.script.title}
                      placeholder="标题"
                      onChange={(event) => updateRecipe((current) => ({
                        ...current, script: { ...current.script, title: event.target.value },
                      }))}
                    />
                    <Input.TextArea
                      value={recipe.script.summary}
                      placeholder="一句话梗概"
                      autoSize={{ minRows: 2, maxRows: 4 }}
                      onChange={(event) => updateRecipe((current) => ({
                        ...current, script: { ...current.script, summary: event.target.value },
                      }))}
                    />
                    <Input.TextArea
                      value={recipe.script.fullStory}
                      placeholder="完整故事"
                      autoSize={{ minRows: 8, maxRows: 16 }}
                      onChange={(event) => updateRecipe((current) => ({
                        ...current, script: { ...current.script, fullStory: event.target.value },
                      }))}
                    />
                  </div>
                ),
              },
              {
                key: "style",
                label: "画风",
                children: (
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
                ),
              },
              {
                key: "assets",
                label: "人物 / 场景",
                children: (
                  <div className="director-asset-section">
                    <div className="director-section-head">
                      <Typography.Title level={5}>人物与道具</Typography.Title>
                      <Space wrap>
                        <Button size="small" icon={<Library size={14} />} onClick={() => setLibraryDrawerOpen(true)}>从库插入</Button>
                        <Button size="small" icon={<Library size={14} />} onClick={() => void handleSaveToLibrary(recipe.characters.map((item) => item.id), [])} disabled={!recipe.characters.length}>存入资产库</Button>
                        <Button size="small" icon={<ImagePlus size={14} />} onClick={() => handleGenerateAssets(recipe.characters.map((item) => item.id), [])}>全部定妆</Button>
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
                      {!recipe.characters.length && <Empty description="运行流水线或从资产库插入人物、道具" />}
                    </div>
                    <div className="director-section-head">
                      <Typography.Title level={5}>场景</Typography.Title>
                      <Space wrap>
                        <Button size="small" icon={<Library size={14} />} onClick={() => setLibraryDrawerOpen(true)}>从库插入</Button>
                        <Button size="small" icon={<Library size={14} />} onClick={() => void handleSaveToLibrary([], recipe.locations.map((item) => item.id))} disabled={!recipe.locations.length}>存入资产库</Button>
                        <Button size="small" icon={<ImagePlus size={14} />} onClick={() => handleGenerateAssets([], recipe.locations.map((item) => item.id))}>全部场景</Button>
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
                      {!recipe.locations.length && <Empty description="运行流水线或从资产库插入场景" />}
                    </div>
                  </div>
                ),
              },
              {
                key: "board",
                label: "分镜",
                children: (
                  <div className="director-shot-section">
                    <div className="director-section-head">
                      <div>
                        <Typography.Title level={5}>分镜</Typography.Title>
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
                        </p>
                      </div>
                      <div className="director-output-settings">
                        <Select
                          aria-label="工作流"
                          className="director-workflow-select"
                          value={workflowFamilyId}
                          options={workflowFamilyOptions}
                          onChange={(value: string) => updateOutputSettings({ videoWorkflowFamily: value })}
                          popupMatchSelectWidth={false}
                        />
                        <Select
                          aria-label="画面比例"
                          value={recipe.aspectRatio}
                          options={aspectOptions}
                          onChange={(value: string) => updateOutputSettings({ aspectRatio: value })}
                          popupMatchSelectWidth={false}
                        />
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
                        <Select
                          aria-label="模型体积"
                          value={recipe.weightProfile || "full"}
                          options={DIRECTOR_WEIGHT_OPTIONS}
                          onChange={(value: DirectorWeightProfile) => updateOutputSettings({ weightProfile: value })}
                          popupMatchSelectWidth={false}
                        />
                        <Button
                          loading={running}
                          disabled={running}
                          onClick={() => { void handleGenerateStoryboard({ force: true }) }}
                        >
                          {placeholderBoard || !visibleShots.length ? "根据剧本生成分镜" : "按剧本重新生成"}
                        </Button>
                        <Button disabled={!failedShotIds.length} onClick={() => { void handleBoardGenerate(failedShotIds) }}>仅重试失败项</Button>
                        <Button disabled={!checkedShots.length} onClick={() => handleBoardGenerate(checkedShotIds)}>生成选中</Button>
                        <Button disabled={!checkedShots.length} onClick={() => { void handleCancelShots(checkedShotIds) }}>取消选中</Button>
                        <Button type="primary" icon={<Clapperboard size={14} />} disabled={!visibleShots.length} onClick={() => handleBoardGenerate()}>
                          {boardMode === "still" ? "全部静帧" : renderPass === "preview" ? "全部预览" : "全部出片"}
                        </Button>
                      </div>
                    </div>
                    {visibleShots.length ? (
                      <div className="director-shot-workspace">
                        <aside className="director-shot-bin">
                          <div className="director-shot-list">
                            {visibleShots.map((shot) => {
                              const job = allJobs.find((entry) => entry.id === shot.jobId)
                              const state = shotGenerationState(job, shot.outputVideoUrl, shot.jobId, {
                                status: shot.status,
                                progress: shot.progress,
                              })
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
                              {pipeline.stage
                                || (pipeline.runningId === "script" ? "正在根据创意写剧本，写完后会拆成全部镜头" : "正在根据剧本拆全部镜头")}
                            </p>
                            <Progress percent={pipelinePercent} status="active" />
                            <p className="director-output-hint">
                              不会展示模型原文或思考过程。镜头列表会在拆完后替换这些占位卡。
                            </p>
                          </div>
                        ) : (
                          <p className="director-board-generating-mobile">
                            {pipeline.stage || "正在根据剧本生成全部分镜…"}
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
                ),
              },
              {
                key: "export",
                label: "出片",
                children: (
                  <DirectorExportPanel
                    recipe={recipe}
                    ttsBusy={ttsBusy}
                    muxBusy={muxBusy}
                    previewingCharacterId={previewingCharacterId}
                    onChangeRecipe={(patch) => updateRecipe((current) => ({ ...current, ...patch }))}
                    onGenerateAllTts={() => { void handleGenerateTts() }}
                    onPreviewCharacter={(character) => { void handlePreviewCharacter(character) }}
                    onChangeCharacterVoice={(characterId, voiceId) => updateRecipe((current) => ({
                      ...current,
                      characters: current.characters.map((item) => item.id === characterId ? { ...item, voiceId } : item),
                    }))}
                    onUploadBgm={(file) => { void handleUploadBgm(file) }}
                    onMux={() => { void handleMux() }}
                    onDownload={(kind) => { void handleDownloadExport(kind) }}
                    onPlaySequence={() => setPlayerOpen(true)}
                    onJianying={() => setJianyingOpen(true)}
                  />
                ),
              },
            ]}
          />
          <div className="director-recipe-scroll-end" aria-hidden="true" />
        </section>
      </div>

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
      <JobErrorNotice error={state.error} />
      <Button size="small" icon={<RefreshCw size={12} />} loading={state.generating} onClick={onGenerate}>
        {isDirectorFailedStatus(state.status)
          ? "重试这一项"
          : showImage ? "重新定妆" : kind === "location" ? "生成场景" : "生成定妆"}
      </Button>
      <Button size="small" icon={<Library size={12} />} onClick={onSaveToLibrary}>
        存入资产库
      </Button>
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
