import { useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Button, Card, Empty, Input, InputNumber, Progress, Select, Space, Tabs, Tag, Typography, message,
} from "antd"
import { ArrowLeft, Clapperboard, ImagePlus, Play, RefreshCw, Wand2 } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { User } from "../api"
import JianyingExportModal from "../media/JianyingExportModal"
import type { JianyingMediaItem } from "../media/jianying-draft-builder"
import JobErrorNotice from "./components/JobErrorNotice"
import SequencePlayerModal from "./components/SequencePlayerModal"
import { DirectorMobileBottomBar, DirectorMobileHeader } from "./DirectorMobileChrome"
import "./prompt-compiler.contract"
import {
  generateDirectorAssets, getDirectorProject, listDirectorArtStyles, listWorkflowModes, recipePayloadFromApi,
  renderDirectorShots, runDirectorRecipe, runDirectorRecipeStep, updateDirectorProjectRecord,
} from "./director-api"
import { assetGenerationState, assetPreviewUrl, jobProgressFromJob, jobStoredImageUrl, jobVideoUrl, mergeDirectorStatus, shotGenerationState, shotStatusFromJob, summarizeJobError } from "./director-submit"
import { directorStatusColor, directorStatusLabel, isDirectorFailedStatus } from "./status-labels"
import {
  createEmptyRecipe, flattenRecipeShots, RECIPE_AGENT_LABELS, RecipeAgentId, RecipeAgentRunStatus,
  RecipeCharacter, RecipeLocation, RecipeProject, RecipeShot, artStylePreviewUrl, recipeArtStyleFromCatalog, recipeShotsToPlayer,
  DIRECTOR_FINAL_CANVAS_OPTIONS, DIRECTOR_SPEED_OPTIONS, H3_CANVAS_PRESETS, applyRecipeOutputSettings,
  recipeCanvasPreset, DirectorQuality, DirectorSpeed, userFacingCopy,
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

function notifyFailure(error: unknown, fallback: string) {
  message.error(summarizeJobError(error instanceof Error ? error.message : "").summary || fallback)
}

const AGENT_ORDER: RecipeAgentId[] = [
  "research", "script", "art_style", "storyboard", "characters", "locations", "voice", "music", "media",
]

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
): RecipeProject {
  return {
    ...recipe,
    agentStatus: recipe.agentStatus.map((item) => (
      item.id === agentId ? { ...item, status, error: null } : item
    )),
  }
}

export default function DirectorRecipeStudio({
  projectId, csrfToken, allJobs, onBack, onExitDirector,
}: DirectorRecipeStudioProps) {
  const queryClient = useQueryClient()
  const [goal, setGoal] = useState("")
  const [recipe, setRecipe] = useState<RecipeProject>(() => createEmptyRecipe())
  const [running, setRunning] = useState(false)
  const [saving, setSaving] = useState(false)
  const [playerOpen, setPlayerOpen] = useState(false)
  const [jianyingOpen, setJianyingOpen] = useState(false)
  const [activeTab, setActiveTab] = useState("story")
  const runStartedAtRef = useRef(0)

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
          if (!shot.jobId) return shot
          const job = allJobs.find((entry) => entry.id === shot.jobId)
          if (!job) return shot
          const status = mergeDirectorStatus(shot.status, shotStatusFromJob(job))
          const url = jobVideoUrl(job)
          const progress = jobProgressFromJob(job, shot.progress || 0)
          if (status !== shot.status || url !== shot.outputVideoUrl || progress !== shot.progress) {
            changed = true
            return { ...shot, status, outputVideoUrl: url || shot.outputVideoUrl, progress }
          }
          return shot
        }),
      }))
      return changed ? { ...prev, characters, locations, scenes } : prev
    })
  }, [allJobs])

  const shots = useMemo(() => flattenRecipeShots(recipe), [recipe])
  const completedShots = shots.filter((shot) => shot.status === "succeeded" && shot.outputVideoUrl)
  const failedShotIds = shots.filter((shot) => {
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
  const groupedStyleOptions = categories.map((category) => ({
    label: category.name_zh,
    options: styles.filter((style) => style.category === category.id).map((style) => ({
      value: style.id,
      label: `${style.name_zh} / ${style.name_en}`,
    })),
  }))

  const completedAgents = recipe.agentStatus.filter((item) => item.status === "completed").length
  const runningAgent = recipe.agentStatus.find((item) => item.status === "running")
  const pipelinePercent = Math.round(
    ((completedAgents + (runningAgent ? 0.5 : 0)) / AGENT_ORDER.length) * 100,
  )

  async function persist(next: RecipeProject, extra?: { title?: string; source_script?: string }) {
    setSaving(true)
    try {
      await updateDirectorProjectRecord(projectId, {
        title: extra?.title ?? next.script.title ?? "未命名导演工程",
        summary: next.script.summary,
        source_script: extra?.source_script ?? goal,
        payload: next,
      }, csrfToken)
      return true
    } catch (error) {
      notifyFailure(error, "保存失败")
      return false
    } finally {
      setSaving(false)
    }
  }

  async function handleRun() {
    const text = goal.trim()
    if (!text) {
      message.warning("请先写一句创意或故事")
      return
    }
    setRunning(true)
    runStartedAtRef.current = Date.now()
    setRecipe((current) => setLocalAgentStatus(
      setLocalAgentStatus(current, "research", "completed"),
      "script",
      "running",
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
    setRunning(true)
    runStartedAtRef.current = Date.now()
    setRecipe((current) => setLocalAgentStatus(current, agentId, "running"))
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

  async function handleRender(shotIds?: string[]) {
    try {
      const saved = await persist(recipe)
      if (!saved) return
      const row = await renderDirectorShots(projectId, { shot_ids: shotIds, render_pass: "final" }, csrfToken)
      const payload = recipePayloadFromApi(row)
      if (payload) setRecipe(payload)
      await queryClient.invalidateQueries({ queryKey: ["jobs"] })
      message.success(shotIds?.length === 1 ? "已提交这一镜" : "已提交分镜视频")
    } catch (error) {
      notifyFailure(error, "提交失败")
    }
  }

  function updateOutputSettings(patch: Partial<Pick<RecipeProject, "aspectRatio" | "finalQuality" | "finalSpeed" | "videoWorkflowFamily">>) {
    updateRecipe((current) => applyRecipeOutputSettings(current, patch))
  }

  function updateRecipe(updater: (current: RecipeProject) => RecipeProject) {
    setRecipe((current) => {
      const next = updater(current)
      void persist(next)
      return next
    })
  }

  const jianyingItems: JianyingMediaItem[] = completedShots.map((shot) => ({
    id: shot.id,
    title: shot.title,
    kind: "video",
    path: shot.outputVideoUrl || "",
    url: shot.outputVideoUrl || "",
    durationSeconds: shot.durationSec,
  }))
  const mobileTitle = recipe.script.title.trim() || "未命名导演工程"
  const mobilePrimary = activeTab === "assets"
    ? {
      label: "全部定妆",
      onClick: () => { void handleGenerateAssets() },
      loading: false,
      disabled: !recipe.characters.length && !recipe.locations.length,
    }
    : activeTab === "board"
      ? {
        label: "全部出片",
        onClick: () => { void handleRender() },
        loading: false,
        disabled: !shots.length,
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
          <span className="director-project-meta">{saving ? "保存中" : "Recipe"}</span>
        </div>
        <Space wrap className="director-top-actions">
          <Button onClick={onExitDirector}>创作工作台</Button>
          <Button icon={<Play size={14} />} disabled={!completedShots.length} onClick={() => setPlayerOpen(true)}>串播</Button>
          <Button disabled={!completedShots.length} onClick={() => setJianyingOpen(true)}>剪映导出</Button>
          <Button type="primary" icon={<Wand2 size={14} />} loading={running} onClick={handleRun}>运行导演流水线</Button>
        </Space>
      </header>

      <div className="director-recipe-layout">
        <aside className="director-recipe-rail">
          <Typography.Title level={5}>一句话创意</Typography.Title>
          <Input.TextArea
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
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
                ? `正在运行：${RECIPE_AGENT_LABELS[runningAgent.id]}（${completedAgents} / ${AGENT_ORDER.length}）`
                : running
                  ? "正在连接导演流水线…"
                  : `已完成 ${completedAgents} / ${AGENT_ORDER.length} 步`}
            </p>
          </div>
          <ol className="director-agent-list">
            {AGENT_ORDER.map((agentId) => {
              const item = recipe.agentStatus.find((entry) => entry.id === agentId)
              return (
                <li key={agentId}>
                  <Tag color={directorStatusColor(item?.status)}>{RECIPE_AGENT_LABELS[agentId]}</Tag>
                  <Button type="link" size="small" disabled={running} onClick={() => handleRerun(agentId)}>重跑</Button>
                </li>
              )
            })}
          </ol>
        </aside>

        <section className="director-recipe-main">
          <Tabs
            className="director-recipe-tabs"
            activeKey={activeTab}
            onChange={setActiveTab}
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
                    <Select
                      showSearch
                      optionFilterProp="label"
                      placeholder="从 34 条目录选择画风"
                      value={recipe.artStyle?.id}
                      options={groupedStyleOptions}
                      optionRender={(option) => {
                        const style = styles.find((item) => item.id === option.value)
                        return (
                          <span className="director-style-option">
                            {style ? <ArtStyleCover style={style} className="" showPlaceholder={false} /> : null}
                            <span>{option.label}</span>
                          </span>
                        )
                      }}
                      onChange={(styleId: string) => {
                        const style = styles.find((item) => item.id === styleId)
                        if (!style) return
                        updateRecipe((current) => ({
                          ...current,
                          artStyle: recipeArtStyleFromCatalog(style),
                        }))
                      }}
                    />
                    <div className="director-style-grid">
                      {styles.map((style) => (
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
                      <Button size="small" icon={<ImagePlus size={14} />} onClick={() => handleGenerateAssets(recipe.characters.map((item) => item.id), [])}>全部定妆</Button>
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
                          onChange={(patch) => updateRecipe((current) => ({
                            ...current,
                            characters: current.characters.map((item) => item.id === character.id ? { ...item, ...patch } : item),
                          }))}
                        />
                      ))}
                      {!recipe.characters.length && <Empty description="运行流水线后会出现人物卡" />}
                    </div>
                    <div className="director-section-head">
                      <Typography.Title level={5}>场景</Typography.Title>
                      <Button size="small" icon={<ImagePlus size={14} />} onClick={() => handleGenerateAssets([], recipe.locations.map((item) => item.id))}>全部场景</Button>
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
                          onChange={(patch) => updateRecipe((current) => ({
                            ...current,
                            locations: current.locations.map((item) => item.id === location.id ? { ...item, ...patch } : item),
                          }))}
                        />
                      ))}
                      {!recipe.locations.length && <Empty description="运行流水线后会出现场景卡" />}
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
                        <Typography.Title level={5}>分镜预览</Typography.Title>
                        <p className="director-output-hint">
                          {outputPreset
                            ? `当前成片 ${outputPreset.width}×${outputPreset.height}`
                            : `当前成片 ${recipe.finalQuality} MP`}
                          {recipe.finalQuality !== "0.4" ? " · 16GB 显卡请改 0.4 MP 后再出片" : ""}
                          {" · 文生 / 首尾帧 / 多参考按镜头素材自动匹配"}
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
                        <Button disabled={!failedShotIds.length} onClick={() => handleRender(failedShotIds)}>仅重试失败项</Button>
                        <Button type="primary" icon={<Clapperboard size={14} />} disabled={!shots.length} onClick={() => handleRender()}>全部出片</Button>
                      </div>
                    </div>
                    <div className="director-shot-wall">
                      {shots.map((shot) => (
                        <RecipeShotCard
                          key={shot.id}
                          shot={shot}
                          job={allJobs.find((entry) => entry.id === shot.jobId)}
                          onRender={() => handleRender([shot.id])}
                        />
                      ))}
                      {!shots.length && <Empty description="运行流水线后会出现分镜卡片" />}
                    </div>
                  </div>
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
        onClose={() => setPlayerOpen(false)}
        onBatchDeliver={() => { setPlayerOpen(false); setJianyingOpen(true) }}
      />
      <JianyingExportModal
        open={jianyingOpen}
        onClose={() => setJianyingOpen(false)}
        items={jianyingItems}
        defaultAspectRatio={recipe.aspectRatio === "9:16" ? "9:16" : "16:9"}
      />
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
  onChange,
}: {
  title: string
  description: string
  imageUrl?: string | null
  imageJobId?: string | null
  kind: "character" | "location"
  job?: JobLike
  onGenerate: () => void
  onChange: (patch: Partial<RecipeCharacter & RecipeLocation>) => void
}) {
  const state = assetGenerationState(job, imageUrl, imageJobId, kind)
  const previewUrl = assetPreviewUrl(job, imageUrl, imageJobId)
  const showImage = Boolean(previewUrl) && !state.generating
  return (
    <Card
      className="director-asset-card"
      size="small"
      cover={showImage ? (
        <img src={previewUrl || ""} alt={title} className="director-asset-cover" />
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
    </Card>
  )
}

function RecipeShotCard({
  shot,
  job,
  onRender,
}: {
  shot: RecipeShot
  job?: JobLike
  onRender: () => void
}) {
  const state = shotGenerationState(job, shot.outputVideoUrl, shot.jobId, {
    status: shot.status,
    progress: shot.progress,
  })
  const showVideo = Boolean(shot.outputVideoUrl) && !state.generating
  const displayStatus = state.generating ? state.status : (state.status !== "idle" ? state.status : shot.status)
  const failed = !state.generating && isDirectorFailedStatus(displayStatus)
  const displayCopy = userFacingCopy(shot.description, shot.title)
  return (
    <Card className="director-shot-card" size="small" title={`#${shot.shotNumber} ${shot.title}`}>
      {showVideo ? (
        <video src={shot.outputVideoUrl || ""} controls playsInline className="director-shot-video" />
      ) : null}
      {state.generating ? (
        <div className="director-shot-progress">
          <Progress percent={state.progress} size="small" status="active" showInfo={false} />
          <span className="director-asset-status">{state.label}</span>
        </div>
      ) : null}
      {!showVideo && displayCopy ? <p className="director-shot-desc">{displayCopy}</p> : null}
      {shot.dialogue ? <p className="director-shot-dialogue">「{shot.dialogue}」</p> : null}
      <div className="director-shot-meta">
        <Tag color={directorStatusColor(displayStatus)}>
          {directorStatusLabel(displayStatus)}
        </Tag>
        <span>{shot.durationSec}s</span>
        <span>{shot.characterNames.join("、") || "无角色"}</span>
      </div>
      <JobErrorNotice error={state.error} />
      <Button size="small" loading={state.generating} onClick={onRender}>
        {failed ? "重试这一项" : "生成这一镜"}
      </Button>
    </Card>
  )
}
