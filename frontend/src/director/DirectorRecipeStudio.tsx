import { useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Button, Checkbox, Collapse, Drawer, Dropdown, Empty, Input, Modal, Progress, Radio, Segmented, Select, Space, Spin, Switch, Tabs, Tag, Typography, message,
} from "antd"
import { ArrowLeft, CheckCircle2, Clapperboard, Film, ImagePlus, Library, MoreHorizontal, Play, Plus, Wand2 } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { ApiRequestError, User, notifyUnauthorized, requestJson } from "../api"
import JianyingExportModal from "../media/JianyingExportModal"
import type { JianyingMediaItem } from "../media/jianying-draft-builder"
import JobErrorNotice from "./components/JobErrorNotice"
import DirectorExportPanel from "./components/DirectorExportPanel"
import DirectorStageNav from "./components/DirectorStageNav"
import DirectorTaskHeader from "./components/DirectorTaskHeader"
import DirectorScriptDocument from "./components/DirectorScriptDocument"
import DirectorScriptCoverPicker from "./components/DirectorScriptCoverPicker"
import DirectorScriptStreamPanel, { type ClarifyAnswer, type ClarifyQuestion } from "./components/DirectorScriptStreamPanel"
import DirectorPromptBar from "./components/DirectorPromptBar"
import DirectorCreationModeSwitch from "./components/DirectorCreationModeSwitch"
import { DIRECTOR_CREATION_MODE_LABELS, parseDirectorCreationMode, readStoredCreationMode, storeCreationMode, type DirectorCreationMode } from "./creation-mode"
import DirectorCompletionCard from "./components/DirectorCompletionCard"
import { useDirectorProjectSession } from "./useDirectorProjectSession"
import { useDirectorOperation } from "./useDirectorOperation"
import DirectorProductionSettings from "./components/DirectorProductionSettings"
import { recipeShotFlow, recipeStageFlow } from "./recipe-flow"
import { recipeShotVideoUrl } from "./recipe-timeline"
import "./guided-flow.css"
import DirectorTimelineView from "./components/DirectorTimelineView"
import RecipeShotInspector from "./components/RecipeShotInspector"
import { CharacterAssetCard, SimpleRenditionAssetCard, type RecipeAssetTargetKind } from "./components/RecipeAssetWorkbench"
import RecipeAssetStageToolbar from "./components/RecipeAssetStageToolbar"
import SequencePlayerModal from "./components/SequencePlayerModal"
import DirectorAssetLibrary from "./DirectorAssetLibrary"
import { ArtStyleCatalogPicker } from "./ArtStylePicker"
import ThemeToggle from "../components/ThemeToggle"
import { DirectorMobileBottomBar, DirectorMobileHeader } from "./DirectorMobileChrome"
import {
  PLAN_GENERATION_CONNECTING,
  PLAN_GENERATION_FAILURE,
  PLAN_GENERATION_LABEL,
  PLAN_GENERATION_SUCCESS,
  SCRIPT_EMPTY_HINT,
  SCRIPT_EMPTY_TITLE,
  SCRIPT_ART_CHANGE_HINT,
  SCRIPT_ART_PICKER_TITLE,
  SCRIPT_IDEA_EXAMPLES,
  SCRIPT_PROM_BAR_CLARIFY_PLACEHOLDER,
  SCRIPT_PROM_BAR_PLACEHOLDER,
  SCRIPT_STEP_REGENERATE_TITLE,
  SCRIPT_REGENERATE_ADJUST_LABEL,
  SCRIPT_REGENERATE_DIRECT_LABEL,
  SCRIPT_REGENERATE_DOWNSTREAM_PREFIX,
  SCRIPT_REGENERATE_NO_DOWNSTREAM_HINT,
  SCRIPT_REGENERATE_SCOPE_FOLLOWING,
  SCRIPT_REGENERATE_SCOPE_FOLLOWING_HINT,
  SCRIPT_REGENERATE_SCOPE_ONLY,
  SCRIPT_REGENERATE_SCOPE_ONLY_HINT,
  SCRIPT_REGENERATE_STORYBOARD_NOTE,
  SCRIPT_REGENERATE_TITLE,
  STAGE_CLARIFY_FAILED_LABEL,
  GUIDED_RESUME_PREFIX,
  approveBatchConfirm,
  approveBatchLabel,
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
  GUIDED_STEP_AGENTS, guidedFlowHasBrief, nextGuidedStep, parseClarifyScope, tagClarifyAnswers,
  type ClarifyScope, type GuidedStepAgent,
} from "./guided-flow"
import {
  approveDirectorAssetVersion, cancelDirectorJob, cancelDirectorOperation, createDirectorOperation, generateDirectorAssets, generateDirectorStills,
  generateDirectorTts, getDirectorOperation, getDirectorProject,
  insertDirectorLibraryAssets, listDirectorArtStyles, listWorkflowModes, muxDirectorFilm, recipePayloadFromApi,
  saveRecipeAssetsToLibrary, downloadDirectorExport,
  repairDirectorContinuity, translateDirectorShotPrompt,
  removeDirectorScriptCover, updateDirectorProjectRecord, uploadDirectorBgm, uploadDirectorScriptCover, uploadDirectorShotFrame,
  DirectorOperationResponse,
} from "./director-api"
import { extractVideoFrame, fileToDataUrl, jobProgressFromJob, jobStoredImageUrl, jobVideoUrl, mergeDirectorStatus, overlaySubmittingState, shotGenerationState, shotHasActiveRender, shotStatusFromJob, summarizeJobError, waitForJobTerminal } from "./director-submit"
import { directorStatusColor, directorStatusLabel, isDirectorFailedStatus } from "./status-labels"
import { directorRenderPassLabel } from "./prompt-compiler"
import {
  createEmptyRecipe, RECIPE_AGENT_LABELS, RECIPE_AGENT_ORDER, RECIPE_AGENT_RUNNING_MESSAGES,
  recipeShotsToPlayer,
  DIRECTOR_FINAL_CANVAS_OPTIONS, DIRECTOR_SPEED_OPTIONS, DIRECTOR_WEIGHT_OPTIONS, H3_CANVAS_PRESETS, applyRecipeOutputSettings,
  recipeCanvasPreset, DirectorQuality, DirectorSpeed, DirectorWeightProfile, ShotTake,
  estimateStoryboardSkeletonCount, recipePipelineProgress,
  insertRecipeShotAfter, removeRecipeShot, duplicateRecipeShot, moveRecipeShotToIndex, newRecipeEntityId,
} from "./types"
import {
  createEmptyRecipeCharacter, createEmptyRecipeLocation, createEmptyRecipeProp,
  ensureRecipeAssetRendition, flattenRecipeShots, isPlaceholderRecipeBoard, recipeApprovableAssetVersion, recipeArtStyleFromCatalog,
  recipeAudio, recipeExportState, recipeSubtitles, shotIsMuxable,
  type RecipeAgentId, type RecipeAgentRunStatus, type RecipeAssetRendition, type RecipeCharacter,
  type RecipeProject, type RecipeShot,
} from "./recipe-model"
import {
  DIRECTOR_RECIPE_VIEW_LABELS, RECIPE_STAGE_GROUPS, parseRecipeStage, recipeReadiness, recipeAssetIsAdopted,
  resolveDirectorRecipeView, type DirectorRecipeView, type RecipeStageId,
} from "./recipe-readiness"
import { DEFAULT_DIRECTOR_WORKFLOW_FAMILY, directorWorkflowFamilies } from "./director-workflows"
import {
  hasLatestShotSubmissionFailure,
  mergeRecipeApprovedAssetState,
  mergeRecipeExecutionState,
  mergeRecipeShotFrameState,
  reconcileShotJobExecution,
} from "./recipe-execution"
import { mergeContinuityRepair } from "./recipe-continuity"
import ManualStoryboardModal from "./components/ManualStoryboardModal"
import { parseManualStoryboard } from "./manual-import"
import {
  formatSimpleAssetStageSummary,
  simpleAssetStageCounts,
} from "./asset-stage-summary"
import {
  directorFailureMessage, readDirectorContentConflict, reconcileDirectorShotSelection,
  mergeInsertedDirectorAssets, shouldPreserveLocalDirectorContent, type DirectorContentConflict,
} from "./director-project-controller"
import {
  conflictingDirectorOperationId, directorOperationFailedAgents, directorOperationIsActive, directorOperationStorageKey,
  directorOperationTargetShotIds,
} from "./director-operation-controller"

type JobLike = {
  id: string
  status?: string
  stage?: string
  progress?: number
  error?: string | null
  mode?: string
  options?: Record<string, unknown>
  outputs?: Array<{ kind?: string; download_url?: string; cloud_url?: string; path?: string }>
}

type SaveStatus = "idle" | "saving" | "saved" | "failed"
type RenderPass = "preview" | "final"
type BoardMode = "still" | RenderPass | "custom"

function recipeAssetRenditions(recipe: RecipeProject): RecipeAssetRendition[] {
  return [
    ...recipe.characters.flatMap((character) => [
      ensureRecipeAssetRendition(character.portrait),
      ...(character.looks || []).map((look) => ensureRecipeAssetRendition(look.sheet)),
    ]),
    ...recipe.locations.map((location) => ensureRecipeAssetRendition(location.plate)),
    ...recipe.props.map((prop) => ensureRecipeAssetRendition(prop.turnaround)),
  ]
}

function recipeHasActiveAssetJobs(recipe: RecipeProject): boolean {
  return recipeAssetRenditions(recipe).some((rendition) => rendition.versions.some((version) => (
    version.id === rendition.activeVersionId && (version.status === "queued" || version.status === "running")
  )))
}

function recipeHasActiveShotJobs(recipe: RecipeProject): boolean {
  return flattenRecipeShots(recipe).some((shot) => shotHasActiveRender(shot))
}

function syncAssetRenditionFromJobs(
  rendition: RecipeAssetRendition | undefined,
  jobs: JobLike[],
): { rendition: RecipeAssetRendition; changed: boolean } {
  const current = ensureRecipeAssetRendition(rendition)
  let changed = current !== rendition
  const versions = current.versions.map((version) => {
    if (!version.jobId) return version
    const job = jobs.find((item) => item.id === version.jobId)
    if (!job) return version
    const imageUrl = jobStoredImageUrl(job) || version.imageUrl
    const jobStatus = shotStatusFromJob(job)
    const status = jobStatus
    if (status === version.status && imageUrl === version.imageUrl) return version
    changed = true
    return { ...version, status, imageUrl }
  })
  return { rendition: changed ? { ...current, versions } : current, changed }
}

function approvedAssetProjection(rendition: RecipeAssetRendition): { imageUrl?: string | null; jobId?: string | null } {
  const version = rendition.versions.find((item) => item.id === rendition.approvedVersionId)
  return { imageUrl: version?.imageUrl, jobId: version?.jobId }
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

function confirmBoardBatch(options: {
  title: string
  countLabel: string
  costLabel: string
}): Promise<{ confirmed: boolean; chainShots: boolean }> {
  return new Promise((resolve) => {
    let chainShots = false
    Modal.confirm({
      title: options.title,
      content: (
        <div className="director-heavy-confirm">
          <p>{options.countLabel}</p>
          <p className="director-output-hint">{options.costLabel}</p>
          <div style={{ marginTop: 16 }}>
            <Checkbox onChange={(e) => { chainShots = e.target.checked }}>
              开启镜头首尾相接连贯生成（将自动转为排队串行，耗时较长）
            </Checkbox>
          </div>
        </div>
      ),
      okText: "提交",
      cancelText: "取消",
      onOk: () => resolve({ confirmed: true, chainShots }),
      onCancel: () => resolve({ confirmed: false, chainShots: false }),
    })
  })
}

type RegenerateChoice = { action: "direct" | "adjust" | null; resetFollowing: boolean }

/** 重新生成确认弹窗：选择影响范围（仅本环节 / 连同后续环节清空）与是否先调整创作要求。 */
function confirmRegenerateStage(options: {
  agentLabel: string
  downstreamLabels: string[]
  storyboardNote?: boolean
  /** 仅引导链环节支持阶段澄清；脚本/研究/媒体没有可调整的要求卡。 */
  adjustEnabled?: boolean
}): Promise<RegenerateChoice> {
  return new Promise((resolve) => {
    let resetFollowing = false
    const cancel = { action: null, resetFollowing: false } as const
    const modal = Modal.confirm({
      title: SCRIPT_REGENERATE_TITLE(options.agentLabel),
      content: (
        <div className="director-heavy-confirm director-regenerate-confirm">
          {options.storyboardNote ? (
            <p className="director-output-hint">{SCRIPT_REGENERATE_STORYBOARD_NOTE}</p>
          ) : null}
          {options.downstreamLabels.length ? (
            <>
              <p>{SCRIPT_REGENERATE_DOWNSTREAM_PREFIX}{options.downstreamLabels.join("、")}</p>
              <Radio.Group
                defaultValue={false}
                onChange={(event) => { resetFollowing = event.target.value }}
              >
                <Space direction="vertical" size={8}>
                  <Radio value={false}>
                    <span className="director-regenerate-scope">{SCRIPT_REGENERATE_SCOPE_ONLY}</span>
                    <span className="director-regenerate-scope-hint">{SCRIPT_REGENERATE_SCOPE_ONLY_HINT}</span>
                  </Radio>
                  <Radio value={true}>
                    <span className="director-regenerate-scope">{SCRIPT_REGENERATE_SCOPE_FOLLOWING}</span>
                    <span className="director-regenerate-scope-hint">{SCRIPT_REGENERATE_SCOPE_FOLLOWING_HINT}</span>
                  </Radio>
                </Space>
              </Radio.Group>
            </>
          ) : (
            <p>{SCRIPT_REGENERATE_NO_DOWNSTREAM_HINT}</p>
          )}
        </div>
      ),
      footer: (
        <div className="director-regenerate-footer">
          <Button onClick={() => { modal.destroy(); resolve({ ...cancel }) }}>取消</Button>
          {options.adjustEnabled ? (
            <Button onClick={() => { modal.destroy(); resolve({ action: "adjust", resetFollowing }) }}>
              {SCRIPT_REGENERATE_ADJUST_LABEL}
            </Button>
          ) : null}
          <Button type="primary" onClick={() => { modal.destroy(); resolve({ action: "direct", resetFollowing }) }}>
            {SCRIPT_REGENERATE_DIRECT_LABEL}
          </Button>
        </div>
      ),
      centered: true,
      onCancel: () => resolve({ action: null, resetFollowing: false }),
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
  const [messageApi, messageContextHolder] = message.useMessage()
  const notifyFailure = (error: unknown, fallback: string) => {
    messageApi.error(directorFailureMessage(error, fallback))
  }
  const { operationStorageKey, activeOperationId, setActiveOperationId, handledOperationIdsRef, operationToastKeysRef, operationQuery } = useDirectorOperation(projectId)
  const [searchParams, setSearchParams] = useSearchParams()
  const [goal, setGoal] = useState("")
  const [recipe, setRecipe] = useState<RecipeProject>(() => createEmptyRecipe())
  const [running, setRunning] = useState(false)
  const [boardMode, setBoardMode] = useState<BoardMode>("preview")
  const promptPolishStorageKey = `director.prompt-polish:${projectId}`
  const [polishPrompt, setPolishPrompt] = useState(() => {
    if (typeof window === "undefined") return true
    return window.localStorage.getItem(promptPolishStorageKey) !== "false"
  })
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null)
  const [checkedShotIds, setCheckedShotIds] = useState<string[]>([])
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [libraryDrawerOpen, setLibraryDrawerOpen] = useState(false)
  const [activityOpen, setActivityOpen] = useState(false)
  const [playerOpen, setPlayerOpen] = useState(false)
  const [jianyingOpen, setJianyingOpen] = useState(false)
  const activeStage = parseRecipeStage(searchParams.get("stage")) ?? "script"
  // 镜头设计阶段内的「设计 / 制作」模式：设计=编辑分镜与提示词，制作=生成静帧与视频。
  const [shotMode, setShotMode] = useState<"design" | "production">("design")
  useEffect(() => {
    setShotMode("design")
  }, [projectId])
  const [ttsBusy, setTtsBusy] = useState(false)
  const [muxBusy, setMuxBusy] = useState(false)
  const [continuityRepairKey, setContinuityRepairKey] = useState<string | null>(null)
  const [previewingCharacterId, setPreviewingCharacterId] = useState<string | null>(null)
  const [submittingShotIds, setSubmittingShotIds] = useState<string[]>([])
  const [submittingStillIds, setSubmittingStillIds] = useState<string[]>([])
  const [manualImportBusy, setManualImportBusy] = useState(false)
  const [manualImportOpen, setManualImportOpen] = useState(false)
  const [skeletonCount, setSkeletonCount] = useState(0)
  const [elapsedSec, setElapsedSec] = useState(0)
  const [scriptEditMode, setScriptEditMode] = useState(false)
  // 创作模式：URL ?mode= 优先，其次工程级记忆，缺省 AI 生成。
  const [creationMode, setCreationModeState] = useState<DirectorCreationMode>(() => (
    parseDirectorCreationMode(searchParams.get("mode")) ?? readStoredCreationMode(projectId)
  ))
  const clarifyStorageKey = `director-clarify:${projectId}`
  // 当前待回答的确认题及所属环节（agent 为空表示剧本创作方向）。
  const [clarifyScope, setClarifyScope] = useState<ClarifyScope | null>(() => {
    if (typeof window === "undefined") return null
    return parseClarifyScope(window.localStorage.getItem(`director-clarify:${projectId}`))
  })
  const [scriptAnswers, setScriptAnswers] = useState<ClarifyAnswer[]>([])
  const clarifyScopeRef = useRef<ClarifyScope | null>(clarifyScope)
  clarifyScopeRef.current = clarifyScope
  // 「调整要求后重新生成」选择级联时，待该环节确认问题生成后把标记写入澄清作用域。
  const pendingRegenerateScopeRef = useRef<RecipeAgentId | null>(null)
  const runStartedAtRef = useRef(0)
  const recipeRef = useRef(recipe)
  const goalRef = useRef(goal)
  const deletedTakeIdsRef = useRef(new Set<string>())
  const { saveStatus, setSaveStatus, contentConflict, setContentConflict, saveTimerRef, projectRevisionRef, contentRevisionRef, editVersionRef, savedEditVersionRef, conflictRef, persistNow, scheduleSave, flushSave } = useDirectorProjectSession({ projectId, csrfToken, recipeRef, goalRef, runStartedAtRef, deletedTakeIdsRef, notifyFailure })
  const activeOperationIdRef = useRef(activeOperationId)
  activeOperationIdRef.current = activeOperationId
  const isMobile = useIsMobile()
  const compactInspector = useIsMobile("(max-width: 1199px)")
  const returnStageRef = useRef<RecipeStageId | null>(null)
  const returnScrollRef = useRef({ main: 0, shots: 0 })
  const activeView = resolveDirectorRecipeView(searchParams.get("view"), { mobile: isMobile })
  const isTimelineView = activeView === "timeline"
  const assetGenerationActive = recipeHasActiveAssetJobs(recipe)
  const shotGenerationActive = recipeHasActiveShotJobs(recipe)

  const projectQuery = useQuery({
    queryKey: ["director-project", projectId],
    queryFn: () => getDirectorProject(projectId),
    refetchInterval: running || assetGenerationActive || shotGenerationActive || submittingShotIds.length > 0 || submittingStillIds.length > 0 ? 1500 : false,
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
    window.localStorage.setItem(promptPolishStorageKey, String(polishPrompt))
  }, [polishPrompt, promptPolishStorageKey])

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
      // 如果轮询返回的 content_revision 低于本地已知版本，说明这条轮询数据在
      // 最近一次保存之前就已发出（竞态），属于陈旧响应。此时强制走 merge 路径，
      // 确保 deletedTakeIdsRef 中记录的已删 take 不会从旧 payload 里复活。
      const incomingRevision = row.content_revision || 0
      const staleRevision = contentRevisionRef.current > 0
        && incomingRevision > 0
        && incomingRevision < contentRevisionRef.current
      const preserveLocalContent = staleRevision || shouldPreserveLocalDirectorContent({
        contentRevision: contentRevisionRef.current,
        dirty,
        executionOnly,
        hasConflict: Boolean(contentConflict),
        runningPlan: running,
      })
      if (preserveLocalContent) {
        setRecipe((current) => mergeRecipeExecutionState(current, payload, deletedTakeIdsRef.current))
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
    if (directorOperationIsActive(operation)) {
      if (operation.kind === "plan_pipeline" || operation.kind === "plan_clarify") {
        if (!runStartedAtRef.current) runStartedAtRef.current = Date.parse(operation.created_at) || Date.now()
        setRunning(true)
      } else {
        const targets = directorOperationTargetShotIds(operation, flattenRecipeShots(recipeRef.current))
        setSubmittingShotIds((current) => Array.from(new Set([...current, ...targets])))
        const toastKey = operationToastKeysRef.current.get(operation.id)
        if (toastKey && operation.result?.message) {
          messageApi.open({
            type: "loading",
            content: operation.result.message as string,
            key: toastKey,
            duration: 0,
          })
        }
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
        if (operation.kind === "plan_clarify") {
          const questions = operation.result?.questions
          if (operation.status === "succeeded" && Array.isArray(questions) && questions.length) {
            // 「调整要求后重新生成」选择的级联标记，随问题卡一起持久化，回答后注入重生成请求。
            const pendingRef = pendingRegenerateScopeRef.current
            pendingRegenerateScopeRef.current = null
            const pendingAgent = operation.request.agent || undefined
            const regenerateResetFollowing = pendingRef != null && pendingRef === pendingAgent
            const pending: ClarifyScope = {
              agent: pendingAgent,
              questions: questions as ClarifyQuestion[],
              ...(regenerateResetFollowing ? { regenerateResetFollowing: true } : {}),
            }
            setClarifyScope(pending)
            if (typeof window !== "undefined") window.localStorage.setItem(clarifyStorageKey, JSON.stringify(pending))
          } else if (operation.status !== "succeeded") {
            notifyFailure(operation.error, operation.status === "cancelled" ? "生成已取消" : PLAN_GENERATION_FAILURE)
          } else {
            messageApi.warning("AI 没有给出创作方向问题，请直接重新生成")
          }
        } else if (operation.kind === "plan_pipeline") {
          if (payload && row) {
            recipeRef.current = payload
            setRecipe(payload)
            projectRevisionRef.current = row.revision
            contentRevisionRef.current = row.content_revision
            savedEditVersionRef.current = editVersionRef.current
            const nextShots = flattenRecipeShots(payload)
            if (nextShots.length) setSelectedShotId(nextShots[0].id)
          }
          const failedAgents = directorOperationFailedAgents(operation, payload)
          // 逐步确认流程：本环节完成且无失败时，自动衔接下一环节的确认问题；
          // 全部环节完成或中途失败才落完成卡。
          const nextStep = operation.request.guided && operation.status === "succeeded" && !failedAgents.length
            ? nextGuidedStep(payload || recipeRef.current)
            : null
          if (nextStep) {
            void continueGuidedFlow(nextStep)
          } else {
            const planOutcome = {
              ok: operation.status === "succeeded" && failedAgents.length === 0,
              failedAgents,
              shotCount: payload ? flattenRecipeShots(payload).length : 0,
            }
            setLastPlanCompletion(planOutcome)
            if (typeof window !== "undefined") {
              window.localStorage.setItem(planCompletionStorageKey, JSON.stringify(planOutcome))
            }
            if (operation.status === "succeeded" && failedAgents.length === 0) {
              const agents = operation.request.agents || []
              if (agents.includes("storyboard") && agents.length <= 2) {
                const count = payload ? flattenRecipeShots(payload).length : 0
                messageApi.success(count ? `已根据剧本生成 ${count} 个镜头` : "分镜已生成")
                setShotMode("design")
                setActiveStage("shots")
              } else {
                // 生成完成后停留在剧本页展示成稿，由用户通过「进入镜头设计」继续。
                messageApi.success(PLAN_GENERATION_SUCCESS)
              }
            } else if (operation.status === "succeeded") {
              messageApi.error(`生成未完整完成：${failedAgents.map((id) => RECIPE_AGENT_LABELS[id as RecipeAgentId] || id).join("、")}`)
            } else {
              notifyFailure(operation.error, operation.status === "cancelled" ? "生成已取消" : PLAN_GENERATION_FAILURE)
            }
          }
        } else {
          const targets = directorOperationTargetShotIds(operation, flattenRecipeShots(recipeRef.current))
          if (payload) setRecipe((current) => mergeRecipeExecutionState(current, payload, deletedTakeIdsRef.current))
          if (operation.status === "succeeded") {
            const submitted = operation.result.job_ids?.length || 0
            const rendered = payload ? flattenRecipeShots(payload).filter((shot) => targets.includes(shot.id)) : []
            const failed = rendered.filter((shot) => shot.error && !shot.jobId)
            if (!submitted) {
              messageApi.warning(failed[0]?.error || "没有提交成功的镜头，请检查镜头素材后重试")
            } else if (failed.length) {
              messageApi.warning(`已提交 ${submitted} 镜，${failed.length} 镜失败`)
            } else {
              const previewing = operation.request.render_pass === "preview"
              messageApi.success(targets.length === 1
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
        if (toastKey) messageApi.destroy(toastKey)
        operationToastKeysRef.current.delete(operation.id)
        if (operation.kind === "plan_pipeline" || operation.kind === "plan_clarify") {
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
        const portraitResult = syncAssetRenditionFromJobs(item.portrait, allJobs)
        const looks = (item.looks || []).map((look) => {
          const result = syncAssetRenditionFromJobs(look.sheet, allJobs)
          if (result.changed) changed = true
          return result.changed ? { ...look, sheet: result.rendition } : look
        })
        if (portraitResult.changed) changed = true
        const firstLook = looks[0]
        const projection = firstLook
          ? approvedAssetProjection(firstLook.sheet)
          : approvedAssetProjection(portraitResult.rendition)
        const imageUrl = projection.imageUrl || approvedAssetProjection(portraitResult.rendition).imageUrl || null
        const activeVersion = firstLook?.sheet.versions.find((version) => version.id === firstLook.sheet.activeVersionId)
          || portraitResult.rendition.versions.find((version) => version.id === portraitResult.rendition.activeVersionId)
        const imageJobId = activeVersion?.jobId || null
        if (imageUrl !== item.imageUrl || imageJobId !== item.imageJobId) changed = true
        return {
          ...item,
          portrait: portraitResult.rendition,
          looks,
          imageUrl,
          imageJobId,
        }
      })
      const locations = prev.locations.map((item) => {
        const result = syncAssetRenditionFromJobs(item.plate, allJobs)
        const projection = approvedAssetProjection(result.rendition)
        const active = result.rendition.versions.find((version) => version.id === result.rendition.activeVersionId)
        if (result.changed || projection.imageUrl !== item.imageUrl || active?.jobId !== item.imageJobId) changed = true
        return { ...item, plate: result.rendition, imageUrl: projection.imageUrl || null, imageJobId: active?.jobId || null }
      })
      const props = prev.props.map((item) => {
        const result = syncAssetRenditionFromJobs(item.turnaround, allJobs)
        const projection = approvedAssetProjection(result.rendition)
        const active = result.rendition.versions.find((version) => version.id === result.rendition.activeVersionId)
        if (result.changed || projection.imageUrl !== item.imageUrl || active?.jobId !== item.imageJobId) changed = true
        return { ...item, turnaround: result.rendition, imageUrl: projection.imageUrl || null, imageJobId: active?.jobId || null }
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
            const error = isDirectorFailedStatus(status) ? (takeJob.error || take.error) : undefined
            const hasStoredOptions = Boolean(take.options && Object.keys(take.options).length > 0)
            const options = hasStoredOptions
              ? take.options
              : (takeJob.options && typeof takeJob.options === "object" ? takeJob.options as ShotTake["options"] : take.options)
            const workflowId = take.workflowId || takeJob.mode || take.workflowId
            if (
              status !== take.status
              || (url && url !== take.videoUrl)
              || progress !== take.progress
              || error !== take.error
              || options !== take.options
              || workflowId !== take.workflowId
            ) {
              changed = true
              return { ...take, status, videoUrl: url || take.videoUrl, progress, error, options, workflowId }
            }
            return take
          }).filter(take => {
            const key = take.id || take.jobId || ""
            if (key && deletedTakeIdsRef.current.has(key)) {
              changed = true
              return false
            }
            return true
          })
          if (takes !== next.takes) next = { ...next, takes }
          const job = allJobs.find((entry) => entry.id === next.jobId)
          if (!job) return next
          const status = mergeDirectorStatus(next.status, shotStatusFromJob(job))
          const url = jobVideoUrl(job)
          const progress = jobProgressFromJob(job, next.progress || 0)
          const reconciled = reconcileShotJobExecution(next, {
            status,
            progress,
            videoUrl: url,
            error: job.error,
          })
          if (
            reconciled.status !== next.status
            || reconciled.outputVideoUrl !== next.outputVideoUrl
            || reconciled.progress !== next.progress
            || reconciled.error !== next.error
          ) {
            changed = true
            return reconciled
          }
          return next
        }),
      }))
      return changed ? { ...prev, characters, locations, props, scenes } : prev
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
  const renderPass: RenderPass = (boardMode === "final" || boardMode === "custom") ? "final" : "preview"
  const completedShots = shots.filter(shotIsMuxable).map((shot) => ({ ...shot, outputVideoUrl: recipeShotVideoUrl(shot) || undefined }))
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
  const productionModeId = workflowFamilies.find((item) => item.id === workflowFamilyId)?.routes.t2v
  const productionControls = modesQuery.data?.modes.find((item) => item.id === productionModeId)?.director_controls || []
  const workflowFamilyOptions = useMemo(() => {
    const options = workflowFamilies.map((item) => ({ value: item.id, label: item.label }))
    if (workflowFamilyId && !options.some((item) => item.value === workflowFamilyId)) {
      options.unshift({ value: workflowFamilyId, label: workflowFamilyId })
    }
    return options
  }, [workflowFamilies, workflowFamilyId])
  const selectedShot = visibleShots.find((shot) => shot.id === selectedShotId) || visibleShots[0] || null
  const selectedShotIndex = selectedShot ? visibleShots.findIndex((item) => item.id === selectedShot.id) : -1
  const previousShot = selectedShotIndex > 0 ? visibleShots[selectedShotIndex - 1] : null
  const checkedShots = visibleShots.filter((shot) => checkedShotIds.includes(shot.id))

  useEffect(() => {
    const reconciled = reconcileDirectorShotSelection(visibleShots, selectedShotId, checkedShotIds)
    if (reconciled.selectedShotId !== selectedShotId) setSelectedShotId(reconciled.selectedShotId)
    setCheckedShotIds((current) => {
      const next = reconcileDirectorShotSelection(visibleShots, selectedShotId, current).checkedShotIds
      return next.length === current.length ? current : next
    })
  }, [checkedShotIds, selectedShotId, visibleShots])

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
        deleted_take_ids: Array.from(deletedTakeIdsRef.current),
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
      messageApi.success("已用当前窗口内容覆盖云端版本")
    } catch (error) {
      setSaveStatus("failed")
      notifyFailure(error, "覆盖保存失败")
    }
  }

  function patchStudioSearch(
    patch: { stage?: RecipeStageId; view?: DirectorRecipeView; mode?: DirectorCreationMode },
    options?: { replace?: boolean },
  ) {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (patch.stage) next.set("stage", patch.stage)
      if (patch.view === "plan") next.delete("view")
      else if (patch.view === "timeline") next.set("view", "timeline")
      if (patch.mode === "manual") next.set("mode", "manual")
      else if (patch.mode === "agent") next.delete("mode")
      if (next.toString() === prev.toString()) return prev
      return next
    }, options?.replace ? { replace: true } : undefined)
  }

  function setCreationMode(mode: DirectorCreationMode) {
    setCreationModeState(mode)
    storeCreationMode(projectId, mode)
    patchStudioSearch({ mode })
    // 画风等阶段两种模式界面几乎一致，切换必须给即时反馈，否则用户会误以为没切成功。
    messageApi.success(mode === "manual" ? "已切换到手动编辑，可直接编写各环节内容" : "已切换到 AI 生成，可继续用 AI 打磨各环节")
  }

  function setActiveStage(stage: RecipeStageId) {
    patchStudioSearch({ stage })
  }

  function setActiveView(view: DirectorRecipeView) {
    if (isMobile) return
    if (view === "timeline") {
      returnStageRef.current = activeStage
      returnScrollRef.current = { main: document.querySelector(".director-recipe-main")?.scrollTop || 0, shots: document.querySelector(".director-shot-list")?.scrollTop || 0 }
      patchStudioSearch({ view: "timeline" })
      return
    }
    patchStudioSearch({ view: "plan", stage: returnStageRef.current || activeStage })
  }

  useEffect(() => {
    if (isTimelineView || !returnStageRef.current) return
    const frame = requestAnimationFrame(() => {
      const main = document.querySelector(".director-recipe-main")
      const shots = document.querySelector(".director-shot-list")
      if (main) main.scrollTop = returnScrollRef.current.main
      if (shots) shots.scrollTop = returnScrollRef.current.shots
    })
    return () => cancelAnimationFrame(frame)
  }, [isTimelineView])

  function rememberDirectorOperation(operation: DirectorOperationResponse, toastKey?: string) {
    handledOperationIdsRef.current.delete(operation.id)
    if (toastKey) operationToastKeysRef.current.set(operation.id, toastKey)
    if (typeof window !== "undefined") window.localStorage.setItem(operationStorageKey, operation.id)
    queryClient.setQueryData(["director-operation", operation.id], operation)
    setActiveOperationId(operation.id)
  }

  async function resumeConflictingDirectorOperation(error: unknown): Promise<boolean> {
    const operationId = conflictingDirectorOperationId(error)
    if (!operationId) return false
    try {
      const operation = await getDirectorOperation(operationId)
      rememberDirectorOperation(operation)
      messageApi.info("已恢复正在执行的导演操作")
      return true
    } catch {
      return false
    }
  }

  async function handleCancelActiveOperation() {
    if (!activeOperationId) return
    try {
      const operation = await cancelDirectorOperation(activeOperationId, csrfToken)
      queryClient.setQueryData(["director-operation", activeOperationId], operation)
      messageApi.info("已请求取消，当前步骤结束后会停止")
    } catch (error) {
      notifyFailure(error, "取消操作失败")
    }
  }

  async function handleRun() {
    const text = goal.trim()
    if (!text) {
      messageApi.warning("请先写一句创意或故事")
      return
    }
    if (activeOperationId) {
      messageApi.warning("已有导演操作正在执行，请完成或取消后再试")
      return
    }
    const saved = await flushSave()
    if (!saved) return
    setRunning(true)
    setScriptEditMode(false)
    setLastPlanCompletion(null)
    if (typeof window !== "undefined") window.localStorage.removeItem(planCompletionStorageKey)
    // 新一轮生成前丢弃未回答的旧问题卡，避免旧卡叠在新澄清上被误答。
    setClarifyScope(null)
    if (typeof window !== "undefined") window.localStorage.removeItem(clarifyStorageKey)
    pendingRegenerateScopeRef.current = null
    setActiveStage("script")
    runStartedAtRef.current = Date.now()
    try {
      const operation = await createDirectorOperation(projectId, {
        kind: "plan_clarify",
        goal: text,
      }, csrfToken)
      rememberDirectorOperation(operation)
    } catch (error) {
      notifyFailure(error, PLAN_GENERATION_FAILURE)
      runStartedAtRef.current = 0
      setRunning(false)
    }
  }

  async function handleStartPipeline(answers: ClarifyAnswer[]) {
    // SSE 的问题事件可能早于轮询落作用域：先短暂等待，再判断问题卡是否过期。
    let scope = clarifyScopeRef.current
    for (let attempt = 0; !scope && attempt < 15 && !activeOperationIdRef.current; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 200))
      scope = clarifyScopeRef.current
    }
    if (!scope) {
      messageApi.warning("这组问题已过期，请回答最新的确认问题")
      return
    }
    // 无 agent 标记 = 剧本创作方向确认（只跑 script），有标记 = 对应环节确认（只跑该环节）。
    const scopeAgent = scope.agent
    setClarifyScope(null)
    if (typeof window !== "undefined") window.localStorage.removeItem(clarifyStorageKey)
    if (!scopeAgent) setScriptAnswers(answers)
    // 等 clarify 操作的完成处理清掉活动操作后再创建 pipeline，避免单飞约束 409。
    for (let attempt = 0; attempt < 100 && activeOperationIdRef.current; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 100))
    }
    if (activeOperationIdRef.current) {
      messageApi.warning("AI 正在准备新的确认问题，请稍后回答最新的问题")
      return
    }
    const text = goalRef.current.trim() || recipeRef.current.script.fullStory.trim()
    if (!text) {
      messageApi.warning("请先写一句创意或故事")
      return
    }
    setRunning(true)
    setLastPlanCompletion(null)
    if (typeof window !== "undefined") window.localStorage.removeItem(planCompletionStorageKey)
    runStartedAtRef.current = Date.now()
    const agentId = scopeAgent as RecipeAgentId | undefined
    setRecipe((current) => startLocalPipelineRun(
      agentId ? current : setLocalAgentStatus(current, "research", "completed", "无事实核查需求，已跳过"),
      agentId ? [agentId] : ["script"],
    ))
    try {
      const operation = await createDirectorOperation(projectId, {
        kind: "plan_pipeline",
        goal: text,
        agents: agentId ? [agentId] : ["script"],
        art_style_id: recipeRef.current.artStyle?.id,
        skip_research: true,
        guided: true,
        // 「调整要求后重新生成」选择级联时，由确认问题卡作用域携带该标记。
        reset_following: scope.regenerateResetFollowing || undefined,
        clarifications: answers.length
          ? (agentId ? tagClarifyAnswers(answers, agentId) : answers)
          : undefined,
      }, csrfToken)
      rememberDirectorOperation(operation)
    } catch (error) {
      notifyFailure(error, PLAN_GENERATION_FAILURE)
      runStartedAtRef.current = 0
      setRunning(false)
    }
  }

  // 逐步确认流程：为下一个缺失环节发起确认提问；全部完成后由 pipeline 完成回调落完成卡。
  async function continueGuidedFlow(step: GuidedStepAgent) {
    if (!guidedFlowHasBrief(recipeRef.current, goalRef.current)) return
    // 新一轮提问前丢弃未回答的旧问题卡，保证问题卡与当前环节一致。
    setClarifyScope(null)
    if (typeof window !== "undefined") window.localStorage.removeItem(clarifyStorageKey)
    for (let attempt = 0; attempt < 100 && activeOperationIdRef.current; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 100))
    }
    if (activeOperationIdRef.current) return
    const script = recipeRef.current.script
    const text = goalRef.current.trim() || script.fullStory.trim() || script.summary.trim() || script.title.trim()
    if (!text) return
    setRunning(true)
    runStartedAtRef.current = Date.now()
    try {
      const operation = await createDirectorOperation(projectId, {
        kind: "plan_clarify",
        goal: text,
        agent: step,
        guided: true,
      }, csrfToken)
      rememberDirectorOperation(operation)
    } catch (error) {
      if (await resumeConflictingDirectorOperation(error)) return
      notifyFailure(error, STAGE_CLARIFY_FAILED_LABEL)
      runStartedAtRef.current = 0
      setRunning(false)
    }
  }

  async function handleRerun(agentId: RecipeAgentId) {
    if (agentId === "storyboard") {
      // 分镜重试统一走续跑：保留已产出镜头只补后续处理；无镜头时内部回落完整重拆。
      await handleResumeStoryboard()
      return
    }
    if (activeOperationId) {
      messageApi.warning("已有导演操作正在执行，请完成或取消后再试")
      return
    }
    const saved = await flushSave()
    if (!saved) return
    setRunning(true)
    // 重跑期间不保留上一轮的完成卡，避免失败后仍显示旧的「创作方案已完成」。
    setLastPlanCompletion(null)
    if (typeof window !== "undefined") window.localStorage.removeItem(planCompletionStorageKey)
    runStartedAtRef.current = Date.now()
    setRecipe((current) => startLocalPipelineRun(current, [agentId]))
    try {
      const operation = await createDirectorOperation(projectId, {
        kind: "plan_pipeline",
        goal,
        agents: [agentId],
        art_style_id: recipe.artStyle?.id,
        // 只有重跑研究本身才允许做研究；其余环节重跑不重跑事实核查。
        skip_research: agentId !== "research",
        // 重跑剧本时沿用本次会话已确认的创作方向（含镜头数量），避免重跑后 Beat 数量失控。
        clarifications: agentId === "script" && scriptAnswers.length ? scriptAnswers : undefined,
      }, csrfToken)
      rememberDirectorOperation(operation)
    } catch (error) {
      notifyFailure(error, "重跑失败")
      runStartedAtRef.current = 0
      setRunning(false)
    }
  }

  // 分镜失败但有已产出镜头：保留镜头续跑（只补对白/时长/衔接），不重头拆镜；无镜头时回落完整重拆。
  async function handleResumeStoryboard() {
    if (!flattenRecipeShots(recipeRef.current).length) {
      await handleGenerateStoryboard({ force: true, stayInChat: true })
      return
    }
    if (activeOperationId) {
      messageApi.warning("已有导演操作正在执行，请完成或取消后再试")
      return
    }
    const saved = await flushSave()
    if (!saved) return
    setRunning(true)
    // 续跑期间不保留上一轮的完成卡，避免旧警告卡遮挡新一轮生成直播。
    setLastPlanCompletion(null)
    if (typeof window !== "undefined") window.localStorage.removeItem(planCompletionStorageKey)
    runStartedAtRef.current = Date.now()
    setRecipe((current) => startLocalPipelineRun(current, ["storyboard"]))
    try {
      const operation = await createDirectorOperation(projectId, {
        kind: "plan_pipeline",
        goal: goalRef.current.trim() || recipeRef.current.script.fullStory.trim() || recipeRef.current.script.summary.trim(),
        agents: ["storyboard"],
        art_style_id: recipe.artStyle?.id,
        skip_research: true,
        guided: true,
        resume: true,
      }, csrfToken)
      rememberDirectorOperation(operation)
    } catch (error) {
      if (await resumeConflictingDirectorOperation(error)) return
      notifyFailure(error, "分镜续跑失败")
      runStartedAtRef.current = 0
      setRunning(false)
    }
  }

  // 失败环节重试（完成卡重试按钮与任务栏失败 pill 共用）：分镜走续跑，其余环节单环节重跑。
  function handleRetryFailedAgent(agentId: RecipeAgentId) {
    if (agentId === "storyboard") {
      void handleResumeStoryboard()
      return
    }
    void handleRerun(agentId)
  }

  /** 重新生成（直接重跑）：单环节重跑并在选择级联时清空后续环节；完成后引导链自动续跑。 */
  async function handleRegenerateDirect(agentId: RecipeAgentId, resetFollowing: boolean) {
    if (agentId === "storyboard") {
      // 从对话直播视图重新生成分镜：留在原地观看生成，范围已在重生成弹窗里确认过。
      await handleGenerateStoryboard({
        force: true, stayInChat: true, skipConfirm: true, guided: true, resetFollowing,
      })
      return
    }
    if (activeOperationId) {
      messageApi.warning("已有导演操作正在执行，请完成或取消后再试")
      return
    }
    const saved = await flushSave()
    if (!saved) return
    setRunning(true)
    setLastPlanCompletion(null)
    if (typeof window !== "undefined") window.localStorage.removeItem(planCompletionStorageKey)
    runStartedAtRef.current = Date.now()
    setRecipe((current) => startLocalPipelineRun(current, [agentId]))
    try {
      const operation = await createDirectorOperation(projectId, {
        kind: "plan_pipeline",
        goal,
        agents: [agentId],
        art_style_id: recipe.artStyle?.id,
        skip_research: agentId !== "research",
        guided: true,
        reset_following: resetFollowing || undefined,
        // 重生成剧本时沿用本次会话已确认的创作方向（含镜头数量）。
        clarifications: agentId === "script" && scriptAnswers.length ? scriptAnswers : undefined,
      }, csrfToken)
      rememberDirectorOperation(operation)
    } catch (error) {
      if (await resumeConflictingDirectorOperation(error)) return
      notifyFailure(error, "重新生成失败")
      runStartedAtRef.current = 0
      setRunning(false)
    }
  }

  /** 重新生成（调整要求）：重新走该环节的确认问题卡，答案随重生成请求注入对应环节。 */
  function handleRegenerateAdjust(agentId: GuidedStepAgent, resetFollowing: boolean) {
    pendingRegenerateScopeRef.current = resetFollowing ? (agentId as RecipeAgentId) : null
    void continueGuidedFlow(agentId)
  }

  /** 已完成环节行内的「重新生成」入口：先弹窗确认范围与方式，再执行。 */
  function handleRegenerateRequest(agentId: string) {
    if (running) return
    const id = agentId as RecipeAgentId
    const index = RECIPE_AGENT_ORDER.indexOf(id)
    const downstream = index >= 0
      ? RECIPE_AGENT_ORDER.slice(index + 1).filter((agent) => (
        recipe.agentStatus.find((item) => item.id === agent)?.status === "completed"
      ))
      : []
    void confirmRegenerateStage({
      agentLabel: RECIPE_AGENT_LABELS[id] || id,
      downstreamLabels: downstream.map((agent) => RECIPE_AGENT_LABELS[agent]),
      storyboardNote: id === "storyboard",
      adjustEnabled: (GUIDED_STEP_AGENTS as readonly string[]).includes(id),
    }).then(({ action, resetFollowing }) => {
      if (action === "direct") void handleRegenerateDirect(id, resetFollowing)
      if (action === "adjust") handleRegenerateAdjust(id as GuidedStepAgent, resetFollowing)
    })
  }

  async function handleGenerateStoryboard(options?: {
    force?: boolean
    stayInChat?: boolean
    /** 重新生成弹窗已确认过影响，跳过二次确认。 */
    skipConfirm?: boolean
    guided?: boolean
    resetFollowing?: boolean
  }) {
    if (!projectQuery.isFetched) return
    const current = recipeRef.current
    const currentShots = flattenRecipeShots(current)
    const idea = goalRef.current.trim()
    const story = current.script.fullStory.trim()
    const text = idea || story
    if (!text) {
      messageApi.warning("请先写一句创意，或在「剧本」页写完整剧本")
      return
    }
    if (!options?.force && !isPlaceholderRecipeBoard(currentShots, idea, story)) {
      return
    }
    if (options?.force && !options?.skipConfirm && !isPlaceholderRecipeBoard(currentShots, idea, story)) {
      const confirmed = await confirmHeavyAction({ title: "重新生成分镜", countLabel: `将替换现有 ${currentShots.length} 个镜头的分镜结构。`, costLabel: "已有镜头的媒体关联可能失效；原任务媒体不会被删除。" })
      if (!confirmed) return
    }
    if (activeOperationId) {
      messageApi.warning("已有导演操作正在执行，请完成或取消后再试")
      return
    }
    const hasRealScript = story.length >= 80 && story !== idea
    const agents = [
      ...(!hasRealScript ? ["script" as const] : []),
      ...(!current.characters.length ? ["characters" as const] : []),
      ...(!current.locations.length ? ["locations" as const] : []),
      "storyboard" as const,
    ] as RecipeAgentId[]
    if (saveTimerRef.current) {
      window.clearTimeout(saveTimerRef.current)
      saveTimerRef.current = null
    }
    const saved = await persistNow(current)
    if (!saved) return
    // 对话直播视图里的分镜重试留在原地（镜头设计工作台的重生成仍切到设计模式）。
    if (!options?.stayInChat) {
      setShotMode("design")
      setActiveStage("shots")
    }
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
        guided: options?.guided || undefined,
        reset_following: options?.resetFollowing || undefined,
      }, csrfToken)
      rememberDirectorOperation(operation)
    } catch (error) {
      if (await resumeConflictingDirectorOperation(error)) return
      notifyFailure(error, "分镜生成失败")
      runStartedAtRef.current = 0
      setRunning(false)
    }
  }

  function handleStageChange(stage: RecipeStageId) {
    patchStudioSearch({ stage, view: "plan" })
  }

  useEffect(() => {
    const raw = searchParams.get("view")
    if (raw == null) return
    if (raw === "plan") return
    if (raw === "timeline" && !isMobile) return
    patchStudioSearch({ view: "plan" }, { replace: true })
  }, [isMobile, searchParams])

  async function handleGenerateAssets(
    characterIds?: string[],
    locationIds?: string[],
    force = false,
    targets?: Array<{ kind: RecipeAssetTargetKind; asset_id: string; look_id?: string }>,
  ) {
    try {
      const saved = await flushSave()
      if (!saved) return
      const row = await generateDirectorAssets(projectId, {
        character_ids: characterIds,
        location_ids: locationIds,
        targets,
        force,
      }, csrfToken)
      const payload = recipePayloadFromApi(row)
      if (payload) setRecipe((current) => mergeRecipeExecutionState(current, payload, deletedTakeIdsRef.current))
      await queryClient.invalidateQueries({ queryKey: ["jobs"] })
      messageApi.success("已提交定妆图任务")
    } catch (error) {
      notifyFailure(error, "定妆失败")
    }
  }

  async function handleGenerateAssetTarget(kind: RecipeAssetTargetKind, assetId: string, lookId?: string) {
    try {
      const saved = await flushSave()
      if (!saved) return
      const row = await generateDirectorAssets(projectId, {
        targets: [{ kind, asset_id: assetId, ...(lookId ? { look_id: lookId } : {}) }],
        force: true,
      }, csrfToken)
      const payload = recipePayloadFromApi(row)
      if (payload) setRecipe((current) => mergeRecipeExecutionState(current, payload, deletedTakeIdsRef.current))
      await queryClient.invalidateQueries({ queryKey: ["jobs"] })
      messageApi.success(
        kind === "location" ? "已提交场景任务"
          : kind === "prop" ? "已提交道具任务"
            : kind === "character_sheet" ? "已提交定妆板任务"
              : "已提交身份肖像任务",
      )
    } catch (error) {
      notifyFailure(error, "定妆失败")
    }
  }

  async function handleApproveAssetVersion(kind: RecipeAssetTargetKind, assetId: string, versionId: string, lookId?: string) {
    try {
      const row = await approveDirectorAssetVersion(projectId, {
        kind,
        asset_id: assetId,
        version_id: versionId,
        look_id: lookId,
        content_revision: contentRevisionRef.current || undefined,
      }, csrfToken)
      const payload = recipePayloadFromApi(row)
      projectRevisionRef.current = row.revision
      contentRevisionRef.current = row.content_revision
      if (payload) setRecipe((current) => mergeRecipeApprovedAssetState(current, payload, deletedTakeIdsRef.current))
      await queryClient.invalidateQueries({ queryKey: ["director-project", projectId] })
      messageApi.success("已批准这一版")
    } catch (error) {
      const remote = readDirectorContentConflict(error)
      if (remote) {
        const conflict = { remote }
        conflictRef.current = conflict
        setContentConflict(conflict)
        setSaveStatus("failed")
        return
      }
      notifyFailure(error, "批准失败")
    }
  }

  function collectApprovableSimpleAssets(
    kind: "location" | "prop",
    assetIds?: string[],
  ): Array<{ assetId: string; versionId: string }> {
    if (kind === "location") {
      const items = assetIds?.length
        ? recipe.locations.filter((item) => assetIds.includes(item.id))
        : recipe.locations
      return items.flatMap((item) => {
        const version = recipeApprovableAssetVersion(ensureRecipeAssetRendition(item.plate), allJobs)
        return version ? [{ assetId: item.id, versionId: version.id }] : []
      })
    }
    const items = assetIds?.length
      ? recipe.props.filter((item) => assetIds.includes(item.id))
      : recipe.props
    return items.flatMap((item) => {
      const version = recipeApprovableAssetVersion(ensureRecipeAssetRendition(item.turnaround), allJobs)
      return version ? [{ assetId: item.id, versionId: version.id }] : []
    })
  }

  async function handleBatchApproveSimpleAssets(kind: "location" | "prop", assetIds?: string[]) {
    const targets = collectApprovableSimpleAssets(kind, assetIds)
    if (!targets.length) {
      messageApi.info(kind === "location" ? "没有可批准的场景候选" : "没有可批准的道具候选")
      return
    }
    try {
      let revision = contentRevisionRef.current || undefined
      for (const target of targets) {
        const row = await approveDirectorAssetVersion(projectId, {
          kind,
          asset_id: target.assetId,
          version_id: target.versionId,
          content_revision: revision,
        }, csrfToken)
        revision = row.content_revision
        projectRevisionRef.current = row.revision
        contentRevisionRef.current = row.content_revision
        const payload = recipePayloadFromApi(row)
        if (payload) setRecipe((current) => mergeRecipeApprovedAssetState(current, payload, deletedTakeIdsRef.current))
      }
      await queryClient.invalidateQueries({ queryKey: ["director-project", projectId] })
      messageApi.success(`已批准 ${targets.length} 个${kind === "location" ? "场景" : "道具"}`)
    } catch (error) {
      const remote = readDirectorContentConflict(error)
      if (remote) {
        const conflict = { remote }
        conflictRef.current = conflict
        setContentConflict(conflict)
        setSaveStatus("failed")
        return
      }
      notifyFailure(error, "批量批准失败")
    }
  }

  function collectApprovableCharacterAssets(
    characterIds?: string[],
  ): Array<{
    assetId: string
    versionId: string
    kind: "character_portrait" | "character_sheet"
    lookId?: string
  }> {
    const items = characterIds?.length
      ? recipe.characters.filter((item) => characterIds.includes(item.id))
      : recipe.characters
    const targets: Array<{
      assetId: string
      versionId: string
      kind: "character_portrait" | "character_sheet"
      lookId?: string
    }> = []
    for (const character of items) {
      const look = character.looks?.[0]
      const sheetApprovable = look
        ? recipeApprovableAssetVersion(ensureRecipeAssetRendition(look.sheet), allJobs)
        : undefined
      if (sheetApprovable) {
        targets.push({
          assetId: character.id,
          versionId: sheetApprovable.id,
          kind: "character_sheet",
          lookId: look?.id,
        })
        continue
      }
      const portraitApprovable = recipeApprovableAssetVersion(ensureRecipeAssetRendition(character.portrait), allJobs)
      if (portraitApprovable) {
        targets.push({
          assetId: character.id,
          versionId: portraitApprovable.id,
          kind: "character_portrait",
        })
      }
    }
    return targets
  }

  async function handleBatchApproveCharacters(characterIds?: string[]) {
    const targets = collectApprovableCharacterAssets(characterIds)
    if (!targets.length) {
      messageApi.info("没有可批准的角色候选")
      return
    }
    try {
      let revision = contentRevisionRef.current || undefined
      for (const target of targets) {
        const row = await approveDirectorAssetVersion(projectId, {
          kind: target.kind,
          asset_id: target.assetId,
          version_id: target.versionId,
          look_id: target.lookId,
          content_revision: revision,
        }, csrfToken)
        revision = row.content_revision
        projectRevisionRef.current = row.revision
        contentRevisionRef.current = row.content_revision
        const payload = recipePayloadFromApi(row)
        if (payload) setRecipe((current) => mergeRecipeApprovedAssetState(current, payload, deletedTakeIdsRef.current))
      }
      await queryClient.invalidateQueries({ queryKey: ["director-project", projectId] })
      messageApi.success(`已批准 ${targets.length} 个角色候选`)
    } catch (error) {
      const remote = readDirectorContentConflict(error)
      if (remote) {
        const conflict = { remote }
        conflictRef.current = conflict
        setContentConflict(conflict)
        setSaveStatus("failed")
        return
      }
      notifyFailure(error, "批量批准失败")
    }
  }

  async function requestApproveCharacters(characterIds?: string[]) {
    const targets = collectApprovableCharacterAssets(characterIds)
    if (!targets.length) {
      messageApi.info("没有可批准的角色候选")
      return
    }
    if (targets.length === 1 && characterIds?.length === 1) {
      const target = targets[0]
      await handleApproveAssetVersion(target.kind, target.assetId, target.versionId, target.lookId)
      return
    }
    const ok = await confirmHeavyAction(approveBatchConfirm("character", targets.length))
    if (!ok) return
    await handleBatchApproveCharacters(characterIds)
  }

  async function requestApproveSimpleAssets(kind: "location" | "prop", assetIds?: string[]) {
    const targets = collectApprovableSimpleAssets(kind, assetIds)
    if (!targets.length) {
      messageApi.info(kind === "location" ? "没有可批准的场景候选" : "没有可批准的道具候选")
      return
    }
    if (targets.length === 1 && assetIds?.length === 1) {
      const target = targets[0]
      await handleApproveAssetVersion(kind, target.assetId, target.versionId)
      return
    }
    const ok = await confirmHeavyAction(approveBatchConfirm(kind, targets.length))
    if (!ok) return
    await handleBatchApproveSimpleAssets(kind, assetIds)
  }

  async function handleSaveToLibrary(characterIds: string[] = [], locationIds: string[] = [], propIds: string[] = []) {
    try {
      const saved = await flushSave()
      if (!saved) return
      const result = await saveRecipeAssetsToLibrary({
        project_id: projectId,
        character_ids: characterIds,
        location_ids: locationIds,
        prop_ids: propIds,
      }, csrfToken)
      await queryClient.invalidateQueries({ queryKey: ["director-library-assets"] })
      messageApi.success(`已存入资产库 ${result.imported} 项`)
    } catch (error) {
      notifyFailure(error, "存入资产库失败")
    }
  }

  async function handleGenerateProps(propIds?: string[], force = false) {
    try {
      const saved = await flushSave()
      if (!saved) return
      const row = await generateDirectorAssets(projectId, { prop_ids: propIds, force }, csrfToken)
      const payload = recipePayloadFromApi(row)
      if (payload) setRecipe((current) => mergeRecipeExecutionState(current, payload, deletedTakeIdsRef.current))
      await queryClient.invalidateQueries({ queryKey: ["jobs"] })
      messageApi.success("已提交道具转面任务")
    } catch (error) {
      notifyFailure(error, "道具生成失败")
    }
  }

  async function handleInsertFromLibrary(assetIds: string[]) {
    try {
      const saved = await flushSave()
      if (!saved) return
      const row = await insertDirectorLibraryAssets(
        projectId,
        assetIds,
        contentRevisionRef.current || undefined,
        csrfToken,
      )
      const payload = recipePayloadFromApi(row)
      projectRevisionRef.current = row.revision
      contentRevisionRef.current = row.content_revision
      if (payload) setRecipe((current) => mergeInsertedDirectorAssets(current, payload, assetIds))
      await queryClient.invalidateQueries({ queryKey: ["director-project", projectId] })
      setLibraryDrawerOpen(false)
      messageApi.success(`已插入 ${assetIds.length} 项`)
    } catch (error) {
      const remote = readDirectorContentConflict(error)
      if (remote) {
        const conflict = { remote }
        conflictRef.current = conflict
        setContentConflict(conflict)
        setSaveStatus("failed")
        return
      }
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
    const operation = operationQuery.data
    const message = operation?.kind === "shot_render_prepare" && operation.result?.message
      ? operation.result.message as string
      : polishPrompt ? "正在润色提示词并提交…" : "正在使用当前提示词提交…"

    return overlaySubmittingState(
      shotGenerationState(allJobs.find((entry) => entry.id === shot.jobId), shot.outputVideoUrl, shot.jobId, {
        status: shot.status,
        progress: shot.progress,
      }),
      submitting,
      message,
    )
  }

  async function handleRender(shotIds?: string[]) {

    const targets = submitTargets(shotIds)
    if (!targets.length) {
      messageApi.warning("没有可生成的镜头")
      return
    }
    const untranslated = flattenRecipeShots(recipeRef.current)
      .filter((shot) => targets.includes(shot.id)
        && !String(shot.promptText || "").trim()
        && (String(shot.promptTextZh || "").trim() || String(shot.description || "").trim()))
    if (untranslated.length) {
      const numbers = untranslated.map((shot) => shot.shotNumber).join("、")
      messageApi.warning(`第 ${numbers} 镜英文正文未生成，本次会按中文描述提交；建议先在镜头详情里“翻译为英文正文”`)
    }
    const toastKey = `director-render-${targets.join("|")}`
    messageApi.loading({
      content: polishPrompt
        ? (targets.length === 1 ? "正在润色提示词并提交这一镜…" : "正在润色提示词并提交分镜…")
        : (targets.length === 1 ? "正在使用当前提示词提交这一镜…" : "正在使用当前提示词提交分镜…"),
      key: toastKey,
      duration: 0,
    })
    setSubmittingShotIds((current) => Array.from(new Set([...current, ...targets])))
    try {
      const saved = await flushSave()
      if (!saved) {
        messageApi.destroy(toastKey)
        setSubmittingShotIds((current) => current.filter((id) => !targets.includes(id)))
        return
      }
      const operation = await createDirectorOperation(projectId, {
        kind: "shot_render_prepare",
        shot_ids: targets,
        render_pass: renderPass,
        polish_prompt: polishPrompt,
      }, csrfToken)
      rememberDirectorOperation(operation, toastKey)
    } catch (error) {
      notifyFailure(error, "提交失败")
      messageApi.destroy(toastKey)
      setSubmittingShotIds((current) => current.filter((id) => !targets.includes(id)))
    }
  }

  async function handleStills(shotIds?: string[]) {

    const targets = submitTargets(shotIds)
    if (!targets.length) {
      messageApi.warning("没有可生成的镜头")
      return
    }
    const toastKey = `director-still-${targets.join("|")}`
    messageApi.loading({
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
      if (payload) setRecipe((current) => mergeRecipeExecutionState(current, payload, deletedTakeIdsRef.current))
      await queryClient.invalidateQueries({ queryKey: ["jobs"] })
      messageApi.success(targets.length === 1 ? "已提交本镜静帧" : "已提交静帧")
    } catch (error) {
      notifyFailure(error, "静帧失败")
    } finally {
      messageApi.destroy(toastKey)
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

  async function handleChainedBoardGenerate(targets: string[]) {
    if (boardMode === "still") {
      messageApi.warning("连贯生成不支持静帧，将降级为常规生成")
      await handleStills(targets)
      return
    }
    if (running) {
      messageApi.warning("已有生成任务或操作正在执行，请完成后再试")
      return
    }
    
    const sortedTargets = targets.slice().sort((a, b) => {
      const ia = shots.findIndex((s) => s.id === a)
      const ib = shots.findIndex((s) => s.id === b)
      return ia - ib
    })

    const toastKey = `chain-board-${Date.now()}`
    messageApi.loading({
      content: "开始首尾相接连贯生成...",
      key: toastKey,
      duration: 0,
    })

    setSubmittingShotIds((current) => Array.from(new Set([...current, ...sortedTargets])))

    try {
      for (let i = 0; i < sortedTargets.length; i++) {
        const targetId = sortedTargets[i]
        const shotIndex = shots.findIndex(s => s.id === targetId)
        const prevShotId = shotIndex > 0 ? shots[shotIndex - 1].id : null
        
        const freshProject = queryClient.getQueryData<any>(["project", projectId])
        const freshRecipe = freshProject?.payload || recipeRef.current
        const freshShots = freshRecipe?.scenes.flatMap((s: any) => s.shots) || shots
        const freshPrevShot = freshShots.find((s: any) => s.id === prevShotId)
        
        let videoUrl = freshPrevShot?.outputVideoUrl
        if (!videoUrl && freshPrevShot?.jobId) {
           const jobRes = await fetch(`/api/jobs/${encodeURIComponent(freshPrevShot.jobId)}`)
           if (jobRes.status === 401) notifyUnauthorized()
           if (jobRes.ok) {
             const job = await jobRes.json()
             videoUrl = jobVideoUrl(job)
           }
        }

        if (videoUrl) {
          messageApi.loading({
            content: `(${i + 1}/${sortedTargets.length}) 正在从上个镜头提取尾帧...`,
            key: toastKey,
            duration: 0,
          })
          try {
            const { file } = await extractVideoFrame(videoUrl)
            await handleUploadFrame(targetId, "first", file)
          } catch (e) {
            console.warn("Failed to extract frame:", e)
          }
        }

        messageApi.loading({
          content: `(${i + 1}/${sortedTargets.length}) 正在提交并等待本镜生成...`,
          key: toastKey,
          duration: 0,
        })

        const saved = await flushSave()
        if (!saved) throw new Error("保存失败")
        
        const operation = await createDirectorOperation(projectId, {
          kind: "shot_render_prepare",
          shot_ids: [targetId],
          render_pass: renderPass,
          polish_prompt: polishPrompt,
        }, csrfToken)
        
        let opFinished = false
        let jobIds: string[] = []
        while (!opFinished) {
          await new Promise(r => setTimeout(r, 2000))
          let op
          try {
            op = await getDirectorOperation(operation.id)
          } catch (err) {
            continue
          }
          if (op.status === "succeeded") {
            opFinished = true
            jobIds = op.result?.job_ids || []
          } else if (op.status === "failed" || op.status === "cancelled") {
            throw new Error(op.error || "提交操作失败")
          }
        }
        
        if (jobIds.length > 0) {
          await waitForJobTerminal(jobIds[0])
          await queryClient.invalidateQueries({ queryKey: ["project", projectId] })
        }
        
        setSubmittingShotIds((current) => current.filter((id) => id !== targetId))
      }
      messageApi.success({ content: "连贯生成完成", key: toastKey, duration: 3 })
    } catch (error) {
      notifyFailure(error, "连贯生成中止")
      messageApi.destroy(toastKey)
      setSubmittingShotIds((current) => current.filter((id) => !sortedTargets.includes(id)))
    }
  }

  async function handleUploadFrame(shotId: string, slot: "first" | "end", file: File) {
    try {
      const saved = await flushSave()
      if (!saved) return
      const row = await uploadDirectorShotFrame(projectId, {
        shot_id: shotId,
        slot,
        file,
        expected_content_revision: contentRevisionRef.current || undefined,
      }, csrfToken)
      const payload = recipePayloadFromApi(row)
      projectRevisionRef.current = row.revision
      contentRevisionRef.current = row.content_revision
      if (payload) setRecipe((current) => mergeRecipeShotFrameState(current, payload, shotId))
      messageApi.success(slot === "end" ? "已保存尾帧" : "已保存首帧")
    } catch (error) {
      const remote = readDirectorContentConflict(error)
      if (remote) {
        const conflict = { remote }
        conflictRef.current = conflict
        setContentConflict(conflict)
        setSaveStatus("failed")
        return
      }
      notifyFailure(error, "上传分镜帧失败")
    }
  }

  async function handleUploadScriptCover(file: File) {
    try {
      const saved = await flushSave()
      if (!saved) return
      const row = await uploadDirectorScriptCover(
        projectId,
        file,
        contentRevisionRef.current || undefined,
        csrfToken,
      )
      const payload = recipePayloadFromApi(row)
      projectRevisionRef.current = row.revision
      contentRevisionRef.current = row.content_revision
      if (payload) {
        recipeRef.current = payload
        setRecipe(payload)
      }
      queryClient.setQueryData(["director-project", projectId], row)
      messageApi.success("剧本封面已上传")
    } catch (error) {
      const remote = readDirectorContentConflict(error)
      if (remote) {
        const conflict = { remote }
        conflictRef.current = conflict
        setContentConflict(conflict)
        setSaveStatus("failed")
        return
      }
      notifyFailure(error, "上传剧本封面失败")
    }
  }

  async function handleRemoveScriptCover() {
    try {
      const saved = await flushSave()
      if (!saved) return
      const row = await removeDirectorScriptCover(
        projectId,
        contentRevisionRef.current || undefined,
        csrfToken,
      )
      const payload = recipePayloadFromApi(row)
      projectRevisionRef.current = row.revision
      contentRevisionRef.current = row.content_revision
      if (payload) {
        recipeRef.current = payload
        setRecipe(payload)
      }
      queryClient.setQueryData(["director-project", projectId], row)
      messageApi.success("剧本封面已移除")
    } catch (error) {
      const remote = readDirectorContentConflict(error)
      if (remote) {
        const conflict = { remote }
        conflictRef.current = conflict
        setContentConflict(conflict)
        setSaveStatus("failed")
        return
      }
      notifyFailure(error, "移除剧本封面失败")
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
      messageApi.warning("选中的分镜没有正在生成的任务")
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
      messageApi.success(cancelPreparingOperation ? "已请求取消提交，正在收尾" : "已停止选中分镜")
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
      if (payload) setRecipe((current) => mergeRecipeExecutionState(current, payload, deletedTakeIdsRef.current))
      messageApi.success(characterId ? "已生成角色试听" : shotIds?.length === 1 ? "已生成本镜配音" : "已生成全部配音")
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
      if (payload) setRecipe((current) => mergeRecipeExecutionState(current, payload, deletedTakeIdsRef.current))
      messageApi.success("配乐已上传")
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
      if (payload) setRecipe((current) => mergeRecipeExecutionState(current, payload, deletedTakeIdsRef.current))
      if (payload?.export?.muxStatus === "succeeded") {
        messageApi.success("成片已导出")
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
    const { confirmed, chainShots } = await confirmBoardBatch(boardBatchConfirm(boardMode, targets.length, title))
    if (!confirmed) return
    if (chainShots) {
      await handleChainedBoardGenerate(targets)
    } else {
      await handleBoardGenerate(shotIds)
    }
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
    const excluded = shots.filter((shot) => !shotIsMuxable(shot))
    const confirmation = muxBatchConfirm(count)
    const ok = await confirmHeavyAction(excluded.length ? {
      ...confirmation,
      title: `仅导出可用镜头（${count}）`,
      countLabel: `将导出 ${count} 镜；排除 ${excluded.map((shot) => `#${shot.shotNumber} ${shot.title}`).join("、")}。`,
    } : confirmation)
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
    updateRecipe((current) => {
      let scenes = current.scenes
      if (patch.takes) {
        const shot = current.scenes.flatMap(s => s.shots).find(s => s.id === shotId)
        if (shot) {
          const newTakeKeys = new Set(patch.takes.map((t) => t.id || t.jobId || ""))
          for (const t of shot.takes) {
            const key = t.id || t.jobId || ""
            if (key && !newTakeKeys.has(key)) {
              deletedTakeIdsRef.current.add(key)
            }
          }
        }
      }
      return {
        ...current,
        scenes: scenes.map((scene) => ({
          ...scene,
          shots: scene.shots.map((shot) => shot.id === shotId ? { ...shot, ...patch } : shot),
        })),
      }
    })
  }

  async function importManualStoryboard(file: File) {
    setManualImportBusy(true)
    try {
      const text = await file.text()
      const result = parseManualStoryboard(text)
      if (!result.scenes.length) { messageApi.warning(result.warnings[0] || "未识别到分镜"); return }
      updateRecipe((current) => ({ ...current, scenes: result.scenes, agentStatus: current.agentStatus.map((item) => item.id === "storyboard" ? { ...item, status: "completed", message: "已手动导入分镜" } : item) }))
      await persistNow()
      messageApi.success(`已导入 ${result.scenes.reduce((n, scene) => n + scene.shots.length, 0)} 个手动镜头`)
      if (result.warnings.length) messageApi.warning(result.warnings.slice(0, 2).join("；"))
    } finally { setManualImportBusy(false) }
  }

  async function applyManualStoryboard(scenes: any[], mode: "replace" | "append") {
    if (mode === "replace" && flattenRecipeShots(recipeRef.current).length) {
      const confirmed = await confirmHeavyAction({ title: "替换现有分镜", countLabel: `将替换当前 ${flattenRecipeShots(recipeRef.current).length} 个镜头。`, costLabel: "当前镜头与已生成媒体的关联将被替换；需要保留时请选择追加导入。原任务媒体不会删除。" })
      if (!confirmed) return
    }
    const merged = mode === "replace" || !recipeRef.current.scenes.length ? scenes : [...recipeRef.current.scenes, ...scenes]
    let number = 1
    const normalized = merged.map((scene: any, si: number) => ({ ...scene, sceneNumber: si + 1, shots: scene.shots.map((shot: any) => ({ ...shot, shotNumber: number++ })) }))
    const next = { ...recipeRef.current, scenes: normalized }
    recipeRef.current = next
    setRecipe(next)
    scheduleSave()
    setManualImportOpen(false)
    const saved = await flushSave()
    if (!saved) return
    const total = normalized.reduce((sum: number, scene: any) => sum + scene.shots.reduce((n: number, shot: any) => n + Number(shot.durationSec || 0), 0), 0)
    messageApi.success(`手动分镜已导入，共 ${number - 1} 镜，${total} 秒`)
    if (total !== 30) messageApi.warning(`当前总时长为 ${total} 秒，目标为 30 秒，请在时间线调整`)
  }

  async function handleContinuityRepair(fromShot: number, toShot: number) {
    const key = `${fromShot}:${toShot}`
    if (continuityRepairKey) return
    setContinuityRepairKey(key)
    try {
      const result = await repairDirectorContinuity(recipeRef.current, fromShot, toShot, csrfToken)
      if (result.alreadyPassed) {
        messageApi.info(`第 ${fromShot} → ${toShot} 镜已通过连续性检查`)
        return
      }
      updateRecipe((current) => mergeContinuityRepair(current, result.recipe, fromShot, toShot))
      if (result.resplitRequired?.length) {
        messageApi.warning(`第 ${fromShot} → ${toShot} 镜需要重新拆分，LLM 未直接改写镜头结构`)
      } else if (result.pair.status === "passed") {
        messageApi.success(`已修复第 ${fromShot} → ${toShot} 镜，连续性检查通过`)
      } else {
        messageApi.warning(`已更新第 ${fromShot} → ${toShot} 镜，但仍有衔接风险：${result.pair.reason || "请人工检查"}`)
      }
    } catch (error) {
      notifyFailure(error, `第 ${fromShot} → ${toShot} 镜修复失败`)
    } finally {
      setContinuityRepairKey(null)
    }
  }

  async function handleTranslateShotPrompt(shotId: string, text?: string) {
    try {
      const result = await translateDirectorShotPrompt(projectId, shotId, text, csrfToken)
      return result.promptText
    } catch (error) {
      notifyFailure(error, "镜头正文翻译失败")
      throw error
    }
  }

  function selectShot(shotId: string) {
    setSelectedShotId(shotId)
    if (compactInspector) setInspectorOpen(true)
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

  function handleAddCharacter() {
    updateRecipe((current) => ({
      ...current,
      characters: [...current.characters, createEmptyRecipeCharacter({
        id: newRecipeEntityId("char"),
        name: `角色 ${current.characters.length + 1}`,
      })],
    }))
  }

  function handleAddLocation() {
    updateRecipe((current) => ({
      ...current,
      locations: [...current.locations, createEmptyRecipeLocation({
        id: newRecipeEntityId("loc"),
        name: `场景 ${current.locations.length + 1}`,
      })],
    }))
  }

  function handleAddProp() {
    updateRecipe((current) => ({
      ...current,
      props: [...(current.props || []), createEmptyRecipeProp({
        id: newRecipeEntityId("prop"),
        name: `道具 ${(current.props?.length || 0) + 1}`,
      })],
    }))
  }

  function handleDeleteShot(shotId: string) {
    if (visibleShots.length <= 1) {
      messageApi.warning("至少保留一镜")
      return
    }
    if (submittingShotIds.includes(shotId) || submittingStillIds.includes(shotId)) {
      messageApi.warning("请先停止这一镜的生成任务")
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

  function handleMoveShot(shotId: string, targetIndex: number) {
    updateRecipe((current) => moveRecipeShotToIndex(current, shotId, targetIndex))
    setSelectedShotId(shotId)
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
  const pendingCharacterCount = recipe.characters.filter((item) => !recipeAssetIsAdopted(item.looks?.[0]?.sheet, item.imageUrl)).length
  const pendingLocationCount = recipe.locations.filter((item) => !recipeAssetIsAdopted(item.plate, item.imageUrl)).length
  const pendingPropCount = recipe.props.filter((item) => !item.imageUrl).length
  const approvableLocationCount = recipe.locations.filter((item) => (
    Boolean(recipeApprovableAssetVersion(ensureRecipeAssetRendition(item.plate), allJobs))
  )).length
  const approvablePropCount = recipe.props.filter((item) => (
    Boolean(recipeApprovableAssetVersion(ensureRecipeAssetRendition(item.turnaround), allJobs))
  )).length
  const approvableCharacterCount = recipe.characters.filter((item) => {
    const look = item.looks?.[0]
    return Boolean(
      recipeApprovableAssetVersion(ensureRecipeAssetRendition(item.portrait), allJobs)
      || (look && recipeApprovableAssetVersion(ensureRecipeAssetRendition(look.sheet), allJobs)),
    )
  }).length
  const locationStageCounts = useMemo(
    () => simpleAssetStageCounts(recipe.locations, "plate", allJobs),
    [allJobs, recipe.locations],
  )
  const propStageCounts = useMemo(
    () => simpleAssetStageCounts(recipe.props, "turnaround", allJobs),
    [allJobs, recipe.props],
  )
  const locationStageSummary = formatSimpleAssetStageSummary(locationStageCounts, "场景")
  const propStageSummary = formatSimpleAssetStageSummary(propStageCounts, "道具")
  const characterStageSummary = recipe.characters.length
    ? `${recipe.characters.filter((item) => item.imageUrl).length} 已定妆 · ${approvableCharacterCount} 待批准`
    : "暂无人物"
  const dialogueShotCount = shots.filter((shot) => shot.dialogue.trim()).length
  const planStagePrimary = activeStage === "script" || activeStage === "art_style"
  const planPipelineRunning = running && operationQuery.data?.kind !== "shot_render_prepare"
  const clarifyQuestions = clarifyScope?.questions ?? null
  const clarifyActive = Boolean(clarifyQuestions?.length) && !planPipelineRunning
  const manualMode = creationMode === "manual"
  // 仅流水线进行中锁定模式切换（流式进度与取消入口可见）；
  // 澄清问题待答不锁定：未答卡片保留在剧本对话室，可随时切模式后再回答。
  const creationModeLocked = planPipelineRunning
  const scriptManualActive = manualMode && !creationModeLocked
  // 进入手动编辑时剧本默认展开为编辑态；「完成编辑」后仍可一键回到编辑。
  useEffect(() => {
    if (scriptManualActive) setScriptEditMode(true)
  }, [scriptManualActive])
  // 只看真实创作内容：工程创建时 title/summary 会被写入工程名，不能作为「已有剧本」的依据。
  const hasScriptContent = Boolean(recipe.script.fullStory.trim())
  const scriptStageMode: "streaming" | "empty" | "history" = planPipelineRunning || clarifyActive
    ? "streaming"
    : hasScriptContent ? "history" : "empty"
  // 剧本阶段是对话式创作室：流式进行中的状态与取消由流面板头部承担，
  // 底部 Prompt Bar 只在空闲/澄清应答时作为输入区渲染，避免双份「正在创作 + 取消生成」。
  // 手动编辑模式不进入对话室：与普通阶段一致显示左侧阶段导航，可直接跳转其他环节编辑。
  const scriptRoomActive = activeStage === "script" && !isTimelineView && !scriptManualActive
  // 逐步确认流程还没有走完时，在成稿区提供「继续生成」入口（刷新/中断后可恢复）。
  const guidedNextStep = useMemo(() => {
    if (running || clarifyActive || isTimelineView) return null
    if (!recipe.script.fullStory.trim()) return null
    return nextGuidedStep(recipe)
  }, [clarifyActive, isTimelineView, recipe, running])
  const [artStylePickerOpen, setArtStylePickerOpen] = useState(false)
  const planCompletionStorageKey = `director-plan-completion:${projectId}`
  const [lastPlanCompletion, setLastPlanCompletion] = useState<{ ok: boolean; failedAgents: string[]; shotCount: number } | null>(() => {
    if (typeof window === "undefined") return null
    try {
      const raw = window.localStorage.getItem(`director-plan-completion:${projectId}`)
      const parsed = raw ? JSON.parse(raw) : null
      return parsed && typeof parsed === "object" && typeof parsed.ok === "boolean" ? parsed : null
    } catch {
      return null
    }
  })
  const characterActionLabel = plateBatchLabel("character", pendingCharacterCount || recipe.characters.length)
  const locationActionLabel = plateBatchLabel("location", pendingLocationCount || recipe.locations.length)
  const locationApproveLabel = approveBatchLabel("location", approvableLocationCount)
  const propApproveLabel = approveBatchLabel("prop", approvablePropCount)
  const characterApproveLabel = approveBatchLabel("character", approvableCharacterCount)
  const boardActionLabel = boardBatchLabel(boardMode, visibleShots.length)
  const ttsActionLabel = ttsBatchLabel(dialogueShotCount)
  const muxActionLabel = muxBatchLabel(muxableCount)
  const mobileTitle = recipe.script.title.trim() || "未命名导演工程"
  const legacyPrimary = running && activeOperationId
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
    : activeStage === "shots"
      ? placeholderBoard
        ? manualMode
          // 手动模式不提供 AI 拆解入口，空态区的「新建镜头 / 导入分镜」承接创作。
          ? null
          : {
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
      : manualMode
        // 手动模式下剧本/画风阶段不提供「生成创作方案」，改由手动编辑与目录选择承接。
        ? null
        : {
        label: PLAN_GENERATION_LABEL,
        onClick: () => { void handleRun() },
        loading: running,
        disabled: running,
      }
  const stageFlow = recipeStageFlow(recipe, activeStage, goal)
  // jump=true 标记「进入下一阶段」性质的纯跳转：桌面端主按钮行不再展示（由任务头「下一步」引导承担），
  // 移动端底部操作条仍保留；「先写创意 / 查看未完成镜头」等前置补课跳转保持 jump=false，继续作为主按钮。
  const goToStage = (stage: RecipeStageId, label: string, jump = false) => ({ label, onClick: () => handleStageChange(stage), loading: false, disabled: false, jump })
  const pendingProductionShots = boardMode === "still" ? visibleShots.filter((shot) => !shot.stillUrl && !["queued", "running"].includes(shot.stillStatus || "idle")) : stageFlow.pending
  const productionTargets = checkedShotIds.length ? checkedShotIds : pendingProductionShots.map((shot) => shot.id)
  const mobilePrimary = running && activeOperationId ? legacyPrimary
    : activeStage === "shots" && placeholderBoard && !goal.trim() && !recipe.script.fullStory.trim() ? goToStage("script", "先写创意，或在下方导入分镜")
    : activeStage === "shots" && !placeholderBoard && shotMode === "design" ? goToStage("characters", "前往视觉素材", true)
    : activeStage === "shots" && !placeholderBoard && shotMode === "production" && !productionTargets.length && !stageFlow.missing.length ? goToStage("voice", "前往声音与交付", true)
    : activeStage === "shots" && !placeholderBoard ? {
      label: checkedShotIds.length ? `生成选中（${productionTargets.length}）` : `生成待处理镜头（${productionTargets.length}）`,
      onClick: () => { if (productionTargets.length) void requestBoardGenerate(productionTargets) },
      loading: submittingShotIds.length > 0 || submittingStillIds.length > 0,
      disabled: !productionTargets.length || running || submittingShotIds.length > 0 || submittingStillIds.length > 0,
    }
    : activeStage === "export" && stageFlow.missing.length ? goToStage("shots", "查看未完成镜头")
    : activeStage === "export" && !shots.length ? goToStage("shots", "前往镜头设计")
    : activeStage === "props" ? (approvablePropCount ? { label: `采用道具（${approvablePropCount}）`, onClick: () => { void requestApproveSimpleAssets("prop") }, loading: false, disabled: false } : pendingPropCount ? { label: `生成待处理道具（${pendingPropCount}）`, onClick: () => { void handleGenerateProps() }, loading: false, disabled: false } : goToStage("shots", "前往镜头设计", true))
    : activeStage === "characters" && approvableCharacterCount > 0 ? { label: `采用候选素材（${approvableCharacterCount}）`, onClick: () => { void requestApproveCharacters() }, loading: false, disabled: false }
    : activeStage === "locations" && approvableLocationCount > 0 ? { label: `采用场景（${approvableLocationCount}）`, onClick: () => { void requestApproveSimpleAssets("location") }, loading: false, disabled: false }
    : (activeStage === "characters" && !pendingCharacterCount) || (activeStage === "locations" && !pendingLocationCount) ? goToStage("shots", "前往镜头设计", true)
    : activeStage === "voice" && !dialogueShotCount ? goToStage("music", "无需配音，前往配乐", true)
    : activeStage === "music" ? goToStage("export", "前往成片", true)
    : planStagePrimary && readiness.script.level === "ready" ? goToStage("characters", "前往视觉素材", true)
    : legacyPrimary
  // 桌面端任务头主按钮：仅保留当前阶段的工作动作，「下一步」纯跳转交由标题卡的「下一步」引导；
  // 内容区工具条/空态区/导出面板已承载同款动作时（定妆/场景/道具、有创意待拆解的分镜空态、
  // 勾选镜头后的「生成选中」、配音、成片导出）不在头部重复渲染；运行中保留「取消生成」入口。
  const stageContentHasPrimary = !(running && activeOperationId) && (
    activeStage === "characters" || activeStage === "locations" || activeStage === "props"
    || (activeStage === "shots" && shotMode === "design" && placeholderBoard && !manualMode && (Boolean(goal.trim()) || Boolean(recipe.script.fullStory.trim())))
    || (activeStage === "shots" && shotMode === "production" && checkedShotIds.length > 0)
    || activeStage === "voice"
    || (activeStage === "export" && !stageFlow.missing.length && shots.length > 0)
  )
  const headerPrimary = mobilePrimary && !("jump" in mobilePrimary && mobilePrimary.jump) && !stageContentHasPrimary ? mobilePrimary : null
  const projectDurationSec = visibleShots.reduce((sum, shot) => sum + shot.durationSec, 0)
  const projectMetaLabel = visibleShots.length
    ? `${visibleShots.length} 镜 · ${projectDurationSec} 秒 · ${recipe.aspectRatio}`
    : `${recipe.aspectRatio} · ${recipe.fps} fps`
  const shotWorkspaceStage = !isTimelineView && activeStage === "shots"

  function handleTopMenu(key: string) {
    if (key === "workspace") onExitDirector?.()
    if (key === "export") {
      handleStageChange("export")
    }
    if (key === "jianying") setJianyingOpen(true)
  }

  if (projectQuery.isPending && !projectQuery.data) {
    return (
      <div className="director-recipe-shell !h-0 !min-h-0 flex-1 overflow-hidden">
        <div className="director-library-loading"><Spin /><span>正在加载工程</span></div>
      </div>
    )
  }

  return (
    <div className="director-recipe-shell !h-0 !min-h-0 flex-1 overflow-hidden" data-director-view={activeView} data-look={scriptRoomActive ? "cinema" : undefined}>
      {messageContextHolder}
<Drawer title="任务活动" open={activityOpen} onClose={() => setActivityOpen(false)} size={isMobile ? "100%" : 480}>          <Collapse
            defaultActiveKey={["agents"]}
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
                            {!manualMode ? (
                              <Button
                                type="link"
                                size="small"
                                disabled={running}
                                onClick={() => generateBoard ? void handleGenerateStoryboard({ force: true }) : handleRerun(agentId)}
                              >
                                {pending || (generateBoard && placeholderBoard) ? "生成" : "重跑"}
                              </Button>
                            ) : null}
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
          /></Drawer>
      <Modal
        title={SCRIPT_ART_PICKER_TITLE}
        open={artStylePickerOpen}
        footer={null}
        width={isMobile ? "100%" : 860}
        onCancel={() => setArtStylePickerOpen(false)}
      >
        <ArtStyleCatalogPicker
          styles={styles}
          categories={categories}
          value={recipe.artStyle?.id}
          disabled={running}
          onChange={(style) => {
            updateRecipe((current) => ({ ...current, artStyle: recipeArtStyleFromCatalog(style) }))
            setArtStylePickerOpen(false)
            messageApi.success(SCRIPT_ART_CHANGE_HINT)
          }}
        />
      </Modal>
      <ManualStoryboardModal open={manualImportOpen} onCancel={() => setManualImportOpen(false)} onImport={applyManualStoryboard} />
      <DirectorMobileHeader
        title={mobileTitle}
        onBack={onBack}
        menuItems={[
          { key: "activity", label: "任务活动", onClick: () => setActivityOpen(true) },
          { key: "studio", label: "创作工作台", onClick: onExitDirector },
          { key: "play", label: "串播", disabled: !completedShots.length, onClick: () => setPlayerOpen(true) },
          { key: "export", label: "查看成片与交付", onClick: () => handleStageChange("export") },
          { key: "jianying", label: "剪映", disabled: !completedShots.length, onClick: () => setJianyingOpen(true) },
        ]}
      >
        <DirectorCreationModeSwitch compact value={creationMode} onChange={setCreationMode} disabled={creationModeLocked} />
      </DirectorMobileHeader>
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
              {contentConflict ? <Tag color="error">存在冲突</Tag> : saveStatus === "failed" ? (
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
        {!isMobile && (isTimelineView || activeStage === "shots" || activeStage === "export") && (
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
          <DirectorCreationModeSwitch
            className="director-creation-mode-switch"
            value={creationMode}
            onChange={setCreationMode}
            disabled={creationModeLocked}
          />
          {!scriptRoomActive ? <Button onClick={() => setActivityOpen(true)}>任务活动{running ? " · 进行中" : ""}</Button> : null}
          <ThemeToggle />
          <Button icon={<Play size={14} />} disabled={!completedShots.length} onClick={() => setPlayerOpen(true)}>串播</Button>
          <Dropdown
            trigger={["click"]}
            menu={{
              items: [
                ...(scriptRoomActive ? [{ key: "activity", label: `任务活动${running ? " · 进行中" : ""}`, onClick: () => setActivityOpen(true) }] : []),
                { key: "workspace", label: "返回创作工作台" },
                { key: "export", label: "查看成片与交付", icon: <Film size={14} /> },
                { key: "jianying", label: "剪映导出", disabled: !completedShots.length },
              ],
              onClick: ({ key }) => handleTopMenu(key),
            }}
          >
            <Button icon={<MoreHorizontal size={15} />}>更多</Button>
          </Dropdown>
          {!scriptRoomActive && running && activeOperationId ? (
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
        className={`director-recipe-layout${isTimelineView ? " is-timeline-view" : ""}${scriptRoomActive ? " is-chat" : ""}`}
        aria-busy={running}
        {...(isTimelineView ? { role: "region" as const, "aria-label": "剪辑视图" } : {})}
      >
        {isTimelineView || scriptRoomActive ? null : (
        <aside className="director-recipe-rail">
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
        </aside>
        )}

        <section className={`director-recipe-main${shotWorkspaceStage ? " is-shot-workspace" : ""}`}>
          {!isTimelineView && !scriptRoomActive ? (
            <DirectorTaskHeader
              activeStage={activeStage}
              readiness={readiness}
              onSelect={handleStageChange}
              compact={shotWorkspaceStage}
              summary={stageFlow.summary}
              primary={scriptRoomActive ? undefined : headerPrimary ?? undefined}
              nextStage={stageFlow.nextStage}
            />
          ) : null}
          {!isTimelineView && activeStage === "art_style" ? (
          <Tabs activeKey="art_style" items={[{ key: "script", label: "剧本" }, { key: "art_style", label: "画风" }]} onChange={(key) => handleStageChange(key as RecipeStageId)} />
          ) : null}
          {!isTimelineView && ["characters", "locations", "props"].includes(activeStage) ? <Tabs activeKey={activeStage} items={[{ key: "characters", label: "角色" }, { key: "locations", label: "场景" }, { key: "props", label: "道具" }]} onChange={(key) => handleStageChange(key as RecipeStageId)} /> : null}
          {!isTimelineView && ["voice", "music", "export"].includes(activeStage) ? <Tabs activeKey={activeStage} items={[{ key: "voice", label: "配音" }, { key: "music", label: "配乐" }, { key: "export", label: "成片" }]} onChange={(key) => handleStageChange(key as RecipeStageId)} /> : null}
          {!isTimelineView && activeStage === "script" ? (
                  <div className={`director-script-room${planPipelineRunning ? " is-streaming" : ""}`}>
                    {scriptManualActive ? (
                      <div className="director-script-manual">
                        <div className="director-script-manual-head">
                          <strong>手动编辑剧本</strong>
                          <p>直接修改片名、梗概与完整故事，改动会自动保存；左侧阶段导航可随时切换到分镜、角色、配乐等环节手动编辑。切回「{DIRECTOR_CREATION_MODE_LABELS.agent}」可继续用 AI 打磨或重跑后续环节。</p>
                        </div>
                        <DirectorScriptDocument
                          script={recipe.script}
                          mode={scriptEditMode ? "edit" : "document"}
                          busy={running}
                          onEdit={() => setScriptEditMode(true)}
                          onDoneEdit={() => setScriptEditMode(false)}
                          onChange={(patch) => updateRecipe((current) => ({
                            ...current,
                            script: { ...current.script, ...patch },
                          }))}
                          onUploadCover={handleUploadScriptCover}
                          onRemoveCover={handleRemoveScriptCover}
                          onNext={() => setActiveStage("characters")}
                        />
                      </div>
                    ) : scriptStageMode === "empty" ? (
                      <div className="director-hero">
                        <span className="director-hero-icon"><Wand2 size={22} /></span>
                        <strong>{SCRIPT_EMPTY_TITLE}</strong>
                        <p>{SCRIPT_EMPTY_HINT}</p>
                        <DirectorScriptCoverPicker
                          coverUrl={recipe.script.coverUrl}
                          busy={running}
                          onUpload={handleUploadScriptCover}
                          onRemove={handleRemoveScriptCover}
                        />
                        <div className="director-hero-examples">
                          {SCRIPT_IDEA_EXAMPLES.map((example) => (
                            <button
                              key={example}
                              type="button"
                              className="director-hero-example"
                              disabled={running}
                              onClick={() => {
                                setGoal(example)
                                goalRef.current = example
                                scheduleSave()
                              }}
                            >
                              {example}
                            </button>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <DirectorScriptStreamPanel
                        operationId={activeOperationId || ""}
                        operationKind={operationQuery.data?.kind || (clarifyActive ? "plan_clarify" : "plan_pipeline")}
                        startedAt={runStartedAtRef.current}
                        agentStatus={recipe.agentStatus}
                        artStyleName={recipe.artStyle?.name || ""}
                        cancelRequested={Boolean(operationQuery.data?.cancel_requested)}
                        brief={operationQuery.data?.request?.agent ? goal : (operationQuery.data?.request?.goal || goal)}
                        initialQuestions={clarifyQuestions || undefined}
                        clarifyAgent={clarifyScope?.agent
                          ?? (operationQuery.data?.kind === "plan_clarify" ? operationQuery.data?.request?.agent : undefined)}
                        clarifications={scriptAnswers}
                        onOpenPicker={() => setArtStylePickerOpen(true)}
                        historyMode={!planPipelineRunning && !clarifyActive}
                        recipe={recipe}
                        /* agent 模式 footer 不放剧本成稿/编辑入口：封面、片名、梗概编辑属于手动编辑模式，
                            剧本内容看记录流的「剧本」步骤行（点击开抽屉读全文）。 */
                        transcriptFooter={!planPipelineRunning && !clarifyActive ? (
                          <>
                            {lastPlanCompletion ? (
                              <DirectorCompletionCard
                                completion={lastPlanCompletion}
                                failedLabels={lastPlanCompletion.failedAgents.map((id) => RECIPE_AGENT_LABELS[id as RecipeAgentId] || id)}
                                onRetryAgent={(agentId) => handleRetryFailedAgent(agentId as RecipeAgentId)}
                              />
                            ) : null}
                            {guidedNextStep ? (
                              <div className="director-guided-resume">
                                <Button
                                  type="primary"
                                  size="small"
                                  onClick={() => { void continueGuidedFlow(guidedNextStep) }}
                                >
                                  {GUIDED_RESUME_PREFIX}{RECIPE_AGENT_LABELS[guidedNextStep]}
                                </Button>
                              </div>
                            ) : null}
                          </>
                        ) : undefined}
                        onCancel={() => { void handleCancelActiveOperation() }}
                        onConfirmStep={(answers) => { void handleStartPipeline(answers) }}
                        onRetryAgent={(agentId) => handleRetryFailedAgent(agentId as RecipeAgentId)}
                        onRegenerateAgent={handleRegenerateRequest}
                      />
                    )}
                    {!planPipelineRunning && !scriptManualActive ? (
                      <DirectorPromptBar
                        value={goal}
                        phase={clarifyActive ? "clarify" : "idle"}
                        placeholder={clarifyActive ? SCRIPT_PROM_BAR_CLARIFY_PLACEHOLDER : SCRIPT_PROM_BAR_PLACEHOLDER}
                        onChange={(value) => {
                          setGoal(value)
                          goalRef.current = value
                          scheduleSave()
                        }}
                        onSubmit={() => { void handleRun() }}
                        onCancel={() => { void handleCancelActiveOperation() }}
                        cancelRequested={Boolean(operationQuery.data?.cancel_requested)}
                      />
                    ) : null}
                  </div>
          ) : null}
          {!isTimelineView && activeStage === "art_style" ? (
            <ArtStyleCatalogPicker
              styles={styles}
              categories={categories}
              value={recipe.artStyle?.id}
              disabled={running}
              onChange={(style) => updateRecipe((current) => ({
                ...current,
                artStyle: recipeArtStyleFromCatalog(style),
              }))}
            />
          ) : null}
          {!isTimelineView && (activeStage === "characters" || activeStage === "props") ? (
                  <div className="director-asset-section">
                    <div hidden={activeStage === "props"}>
                    <RecipeAssetStageToolbar
                      title={`人物与道具 · ${recipe.characters.length}`}
                      summary={characterStageSummary}
                      primaryActions={(
                        <Space wrap size={[8, 8]}>
                          <Button size="small" icon={<Plus size={14} />} onClick={handleAddCharacter}>新增角色</Button>
                          {approvableCharacterCount ? (
                            <Button type="primary" size="small" icon={<CheckCircle2 size={14} />} onClick={() => { void requestApproveCharacters() }}>
                              {characterApproveLabel}
                            </Button>
                          ) : null}
                          <Button type={!approvableCharacterCount && pendingCharacterCount > 0 ? "primary" : "default"} size="small" icon={<ImagePlus size={14} />} disabled={!recipe.characters.length} onClick={() => { void requestGenerateAssets(recipe.characters.map((item) => item.id), []) }}>
                            {characterActionLabel}
                          </Button>
                        </Space>
                      )}
                      moreMenuItems={[
                        { key: "insert", label: "从库插入", icon: <Library size={14} />, onClick: () => setLibraryDrawerOpen(true) },
                        {
                          key: "save",
                          label: "存入资产库",
                          icon: <Library size={14} />,
                          disabled: !recipe.characters.length,
                          onClick: () => { void handleSaveToLibrary(recipe.characters.map((item) => item.id), []) },
                        },
                      ]}
                    />
                    <div className="director-asset-grid director-asset-grid--actions">
                      {recipe.characters.map((character) => (
                        <CharacterAssetCard
                          key={character.id}
                          character={character}
                          jobs={allJobs}
                          onChange={(patch) => updateRecipe((current) => ({
                            ...current,
                            characters: current.characters.map((item) => item.id === character.id ? { ...item, ...patch } : item),
                          }))}
                          onGenerate={(kind, lookId) => { void handleGenerateAssetTarget(kind, character.id, lookId) }}
                          onApprove={(kind, versionId, lookId) => { void handleApproveAssetVersion(kind, character.id, versionId, lookId) }}
                          onSaveToLibrary={() => void handleSaveToLibrary([character.id], [])}
                        />
                      ))}
                      {!recipe.characters.length && (
                        <Empty description="手动新增、AI 生成或从资产库插入人物、道具">
                          <Button icon={<Plus size={14} />} onClick={handleAddCharacter}>新增角色</Button>
                        </Empty>
                      )}
                    </div>
                    </div>
                    {activeStage === "props" ? (
                      <div className="director-prop-section">
                        <RecipeAssetStageToolbar
                          title={`道具转面 · ${recipe.props.length}`}
                          summary={propStageSummary}
                          primaryActions={(
                            <Space wrap size={[8, 8]}>
                              <Button size="small" icon={<Plus size={14} />} onClick={handleAddProp}>新增道具</Button>
                              {approvablePropCount ? (
                                <Button type="primary" size="small" icon={<CheckCircle2 size={14} />} onClick={() => { void requestApproveSimpleAssets("prop") }}>
                                  {propApproveLabel}
                                </Button>
                              ) : null}
                              <Button type={approvablePropCount ? "default" : "primary"} size="small" icon={<ImagePlus size={14} />} onClick={() => { void handleGenerateProps() }}>
                                {pendingPropCount ? `生成 ${pendingPropCount} 件道具` : "重新生成道具"}
                              </Button>
                            </Space>
                          )}
                        />
                        <div className="director-asset-grid director-asset-grid--actions">
                          {!recipe.props.length ? <Empty description="暂无道具，可从资产库插入或继续制作" ><Button onClick={() => setLibraryDrawerOpen(true)}>从资产库插入</Button></Empty> : null}
                          {recipe.props.map((prop) => (
                            <SimpleRenditionAssetCard
                              key={prop.id}
                              asset={prop}
                              kind="prop"
                              jobs={allJobs}
                              onChange={(patch) => updateRecipe((current) => ({
                                ...current,
                                props: current.props.map((item) => item.id === prop.id ? { ...item, ...patch } : item),
                              }))}
                              onGenerate={() => { void handleGenerateAssetTarget("prop", prop.id) }}
                              onApprove={(versionId) => { void handleApproveAssetVersion("prop", prop.id, versionId) }}
                              onSaveToLibrary={() => void handleSaveToLibrary([], [], [prop.id])}
                            />
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </div>
          ) : null}
          {!isTimelineView && activeStage === "locations" ? (
                  <div className="director-asset-section">
                    <RecipeAssetStageToolbar
                      title={`场景清单 · ${recipe.locations.length}`}
                      summary={locationStageSummary}
                      primaryActions={(
                        <Space wrap size={[8, 8]}>
                          <Button size="small" icon={<Plus size={14} />} onClick={handleAddLocation}>新增场景</Button>
                          {approvableLocationCount ? (
                            <Button type="primary" size="small" icon={<CheckCircle2 size={14} />} onClick={() => { void requestApproveSimpleAssets("location") }}>
                              {locationApproveLabel}
                            </Button>
                          ) : null}
                          <Button type={approvableLocationCount ? "default" : "primary"} size="small" icon={<ImagePlus size={14} />} disabled={!recipe.locations.length} onClick={() => { void requestGenerateAssets([], recipe.locations.map((item) => item.id)) }}>
                            {locationActionLabel}
                          </Button>
                        </Space>
                      )}
                      moreMenuItems={[
                        { key: "insert", label: "从库插入", icon: <Library size={14} />, onClick: () => setLibraryDrawerOpen(true) },
                        {
                          key: "save",
                          label: "存入资产库",
                          icon: <Library size={14} />,
                          disabled: !recipe.locations.length,
                          onClick: () => { void handleSaveToLibrary([], recipe.locations.map((item) => item.id)) },
                        },
                      ]}
                    />
                    <div className="director-asset-grid director-asset-grid--actions">
                      {recipe.locations.map((location) => (
                        <SimpleRenditionAssetCard
                          key={location.id}
                          asset={location}
                          kind="location"
                          jobs={allJobs}
                          onChange={(patch) => updateRecipe((current) => ({
                            ...current,
                            locations: current.locations.map((item) => item.id === location.id ? { ...item, ...patch } : item),
                          }))}
                          onGenerate={() => { void handleGenerateAssetTarget("location", location.id) }}
                          onApprove={(versionId) => { void handleApproveAssetVersion("location", location.id, versionId) }}
                          onSaveToLibrary={() => void handleSaveToLibrary([], [location.id])}
                        />
                      ))}
                      {!recipe.locations.length && (
                        <Empty description="手动新增、AI 生成或从资产库插入场景">
                          <Space wrap size={[8, 8]}>
                            <Button icon={<Plus size={14} />} onClick={handleAddLocation}>新增场景</Button>
                            <Button onClick={() => setLibraryDrawerOpen(true)}>从资产库插入</Button>
                          </Space>
                        </Empty>
                      )}
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
              onMoveShot={handleMoveShot}
              onRenderShot={(shotId) => { void handleBoardGenerate([shotId]) }}
              onGenerateStill={(shotId) => { void handleStills([shotId]) }}
              onUploadFrame={handleUploadFrame}
              onExtractEndFrame={(shotId, file) => handleUploadFrame(shotId, "end", file)}
              onGenerateTts={(shotId) => { void handleGenerateTts([shotId]) }}
              onGenerateBoard={() => { void requestBoardGenerate() }}
              onGenerateSelected={() => { void requestBoardGenerate(checkedShotIds, "生成选中") }}
              onRetryFailed={() => { void requestBoardGenerate(failedShotIds, "仅重试失败项") }}
              onCancelSelected={() => { void handleCancelShots(checkedShotIds) }}
              onCancelShot={(shotId) => { void handleCancelShots([shotId]) }}
              onContinuityRepair={handleContinuityRepair}
              onTranslatePrompt={handleTranslateShotPrompt}
              continuityRepairing={Boolean(continuityRepairKey)}
            />
          ) : null}
          {!isTimelineView && activeStage === "shots" ? (
                  <div className="director-shot-section">
                    {visibleShots.length ? (
                      <>
                        <Space wrap className="director-shot-selection-actions">
                          <Segmented
                            value={shotMode}
                            onChange={(value) => setShotMode(value as "design" | "production")}
                            options={[
                              { label: "设计", value: "design" },
                              { label: "制作", value: "production" },
                            ]}
                          />
                          {shotMode === "production" ? <DirectorProductionSettings recipe={recipe} controls={productionControls} families={workflowFamilyOptions} family={workflowFamilyId} mode={boardMode} mobile={isMobile} polish={polishPrompt} onMode={setBoardMode} onPolish={setPolishPrompt} onChange={updateOutputSettings} /> : null}
                          <Button loading={manualImportBusy} onClick={() => setManualImportOpen(true)}>导入分镜</Button>
                        {shotMode === "production" && failedShotIds.length > 0 ? <Button disabled={running} onClick={() => { void requestBoardGenerate(failedShotIds, "仅重试失败项") }}>重试失败镜头（{failedShotIds.length}）</Button> : null}
                        {checkedShotIds.length > 0 && shotMode === "production" ? <>
                          <Button disabled={running} onClick={() => { void requestBoardGenerate(checkedShotIds, "生成选中") }}>生成选中（{checkedShotIds.length}）</Button>
                          <Button danger onClick={() => { void handleCancelShots(checkedShotIds) }}>停止选中</Button>
                          <Button onClick={() => setCheckedShotIds([])}>清空选择</Button>
                        </> : null}
                        {(() => {
                          const shotMoreItems = [
                            ...(!manualMode && shotMode === "design" ? [{ key: "rebuild", label: "按剧本重新生成分镜", disabled: running }] : []),
                            ...(shotMode === "production" ? [{ key: "all", label: "重新生成全部镜头", disabled: running }] : []),
                          ]
                          if (!shotMoreItems.length) return null
                          return (
                            <Dropdown menu={{ items: shotMoreItems, onClick: ({ key }) => { if (key === "rebuild") void handleGenerateStoryboard({ force: true }); if (key === "all") void requestBoardGenerate() } }}><Button>更多操作</Button></Dropdown>
                          )
                        })()}
                      </Space>
                      <div className="director-shot-workspace">
                        <aside className="director-shot-bin">
                          <div className="director-shot-bin-toolbar">
                            <Button size="small" icon={<Plus size={14} />} onClick={handleAddShot}>新增镜头</Button>
                            <Button size="small" loading={manualImportBusy} onClick={() => setManualImportOpen(true)}>
                              重新导入分镜
                            </Button>
                            <div className="director-shot-bin-select-row">
                              <Checkbox
                                checked={visibleShots.length > 0 && checkedShotIds.length === visibleShots.length}
                                indeterminate={checkedShotIds.length > 0 && checkedShotIds.length < visibleShots.length}
                                onChange={(event) => {
                                  if (event.target.checked) {
                                    setCheckedShotIds(visibleShots.map((shot) => shot.id))
                                  } else {
                                    setCheckedShotIds([])
                                  }
                                }}
                              >
                                <span className="director-shot-bin-title">
                                  {checkedShotIds.length ? `已选 ${checkedShotIds.length} / ${visibleShots.length} 镜` : `全选（共 ${visibleShots.length} 镜）`}
                                </span>
                              </Checkbox>
                              {checkedShotIds.length ? (
                                <Button
                                  type="link"
                                  size="small"
                                  onClick={() => setCheckedShotIds([])}
                                  style={{ padding: 0, height: "auto", fontSize: 12 }}
                                >
                                  清空
                                </Button>
                              ) : null}
                            </div>
                          </div>
                          <div className="director-shot-list">
                            {visibleShots.map((shot) => {
                              const state = shotBoardState(shot)
                              const flow = recipeShotFlow(shot)
                              const displayStatus = state.generating ? state.status : flow.status
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
                                      <Tag color={directorStatusColor(displayStatus)} title={flow.label}>{flow.label}</Tag>
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
                        {!compactInspector && selectedShot ? (
                          <RecipeShotInspector
                            key={selectedShot.id}
                            shot={selectedShot}
                            recipe={recipe}
                            previousShot={previousShot}
                            job={allJobs.find((entry) => entry.id === selectedShot.jobId)}
                            stillJob={allJobs.find((entry) => entry.id === selectedShot.stillJobId)}
                            takeJobs={allJobs}
                            compareDesktop
                            focus={shotMode}
                            onGoToProduction={() => setShotMode("production")}
                            onGoToVoice={() => handleStageChange("voice")}
                            onChange={(patch) => patchShot(selectedShot.id, patch)}
                            submitting={submittingShotIds.includes(selectedShot.id)}
                            submittingMessage={operationQuery.data?.kind === "shot_render_prepare" && operationQuery.data.result?.message ? operationQuery.data.result.message as string : undefined}
                            submittingStill={submittingStillIds.includes(selectedShot.id)}
                            onRender={() => { void handleBoardGenerate([selectedShot.id]) }}
                            onGenerateStill={() => { void handleStills([selectedShot.id]) }}
                            onUploadFrame={(slot, file) => handleUploadFrame(selectedShot.id, slot, file)}
                            onExtractEndFrame={(file) => handleUploadFrame(selectedShot.id, "end", file)}
                            onGenerateTts={() => { void handleGenerateTts([selectedShot.id]) }}
                            onCancelShot={() => { void handleCancelShots([selectedShot.id]) }}
                            onContinuityRepair={handleContinuityRepair}
                            onTranslatePrompt={handleTranslateShotPrompt}
                            continuityRepairing={Boolean(continuityRepairKey)}
                            ttsBusy={ttsBusy}
                          />
                        ) : null}
                      </div>
                      </>
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
                        description={pipelineError ? "分镜生成失败，可重试或导入已有分镜" : "生成、导入或新建分镜，开始设计镜头"}
                      >
                        {pipelineError ? <JobErrorNotice error={pipelineError} /> : null}
                        <Space wrap size={[8, 8]} style={{ justifyContent: "center" }}>
                          {!manualMode ? (
                            <Button
                              type="primary"
                              icon={<Clapperboard size={14} />}
                              loading={running}
                              disabled={running}
                              onClick={() => { void handleGenerateStoryboard({ force: true }) }}
                            >
                              根据剧本生成全部分镜
                            </Button>
                          ) : null}
                          <Button icon={<Plus size={14} />} onClick={handleAddShot}>新建空白镜头</Button>
                          <Button loading={manualImportBusy} onClick={() => setManualImportOpen(true)}>导入手动分镜（粘贴 Markdown）</Button>
                        </Space>
                      </Empty>
                    )}
                  </div>
          ) : null}
          {!isTimelineView && (activeStage === "voice" || activeStage === "music" || activeStage === "export") ? (
                  <DirectorExportPanel
                    onLocateShot={(id) => { setSelectedShotId(id); handleStageChange("shots") }}
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
        mask={{ closable: false }}
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
        open={compactInspector && inspectorOpen && Boolean(selectedShot)}
        onClose={() => setInspectorOpen(false)}
        size={isMobile ? "100%" : 640}
        destroyOnHidden
      >
        {selectedShot ? (
          <RecipeShotInspector
            key={selectedShot.id}
            shot={selectedShot}
            recipe={recipe}
            previousShot={previousShot}
            job={allJobs.find((entry) => entry.id === selectedShot.jobId)}
            stillJob={allJobs.find((entry) => entry.id === selectedShot.stillJobId)}
            takeJobs={allJobs}
            compareDesktop={false}
            focus={shotMode}
            onGoToProduction={() => { setInspectorOpen(false); setShotMode("production") }}
            onGoToVoice={() => { setInspectorOpen(false); handleStageChange("voice") }}
            onChange={(patch) => patchShot(selectedShot.id, patch)}
            submitting={submittingShotIds.includes(selectedShot.id)}
            submittingStill={submittingStillIds.includes(selectedShot.id)}
            onRender={() => { void handleBoardGenerate([selectedShot.id]) }}
            onGenerateStill={() => { void handleStills([selectedShot.id]) }}
            onUploadFrame={(slot, file) => handleUploadFrame(selectedShot.id, slot, file)}
            onExtractEndFrame={(file) => handleUploadFrame(selectedShot.id, "end", file)}
            onGenerateTts={() => { void handleGenerateTts([selectedShot.id]) }}
            onCancelShot={() => { void handleCancelShots([selectedShot.id]) }}
            onContinuityRepair={handleContinuityRepair}
            onTranslatePrompt={handleTranslateShotPrompt}
            continuityRepairing={Boolean(continuityRepairKey)}
            ttsBusy={ttsBusy}
          />
        ) : null}
      </Drawer>
      <Drawer
        title="从资产库插入"
        open={libraryDrawerOpen}
        onClose={() => setLibraryDrawerOpen(false)}
        size={isMobile ? "100%" : 520}
        destroyOnHidden
      >
        <DirectorAssetLibrary
          csrfToken={csrfToken}
          mode="picker"
          onInsert={handleInsertFromLibrary}
        />
      </Drawer>
      {!scriptRoomActive && mobilePrimary ? (
        <DirectorMobileBottomBar
          label={mobilePrimary.label}
          onClick={mobilePrimary.onClick}
          loading={mobilePrimary.loading}
          disabled={mobilePrimary.disabled}
        />
      ) : null}
    </div>
  )
}
