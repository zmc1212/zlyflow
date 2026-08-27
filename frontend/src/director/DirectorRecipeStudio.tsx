import { useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Button, Card, Empty, Input, InputNumber, Progress, Select, Space, Tabs, Tag, Typography, message,
} from "antd"
import { ArrowLeft, Clapperboard, ImagePlus, Play, RefreshCw, Wand2 } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { User } from "../api"
import JianyingExportModal from "../media/JianyingExportModal"
import type { JianyingMediaItem } from "../media/jianying-draft-builder"
import SequencePlayerModal from "./components/SequencePlayerModal"
import {
  generateDirectorAssets, getDirectorProject, listDirectorArtStyles, recipePayloadFromApi,
  renderDirectorShots, runDirectorRecipe, runDirectorRecipeStep, updateDirectorProjectRecord,
} from "./director-api"
import { jobImageUrl, jobProgressFromJob, jobVideoUrl, mergeDirectorStatus, shotStatusFromJob } from "./director-submit"
import {
  createEmptyRecipe, flattenRecipeShots, RECIPE_AGENT_LABELS, RecipeAgentId, RecipeCharacter,
  RecipeLocation, RecipeProject, recipeShotsToPlayer,
} from "./types"

type JobLike = {
  id: string
  status?: string
  progress?: number
  outputs?: Array<{ kind?: string; download_url?: string; path?: string }>
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

function statusColor(status: string | undefined) {
  if (status === "completed" || status === "succeeded") return "success"
  if (status === "running" || status === "queued") return "processing"
  if (status === "failed") return "error"
  return "default"
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

  const projectQuery = useQuery({
    queryKey: ["director-project", projectId],
    queryFn: () => getDirectorProject(projectId),
  })
  const stylesQuery = useQuery({
    queryKey: ["director-art-styles"],
    queryFn: listDirectorArtStyles,
  })

  useEffect(() => {
    const row = projectQuery.data
    if (!row) return
    const payload = recipePayloadFromApi(row)
    if (payload) setRecipe(payload)
    if (!goal) setGoal(row.source_script || payload?.script.fullStory || payload?.script.summary || "")
  }, [projectQuery.data])

  useEffect(() => {
    setRecipe((prev) => {
      let changed = false
      const characters = prev.characters.map((item) => {
        if (!item.imageJobId) return item
        const job = allJobs.find((entry) => entry.id === item.imageJobId)
        const url = jobImageUrl(job)
        if (url && url !== item.imageUrl) {
          changed = true
          return { ...item, imageUrl: url }
        }
        return item
      })
      const locations = prev.locations.map((item) => {
        if (!item.imageJobId) return item
        const job = allJobs.find((entry) => entry.id === item.imageJobId)
        const url = jobImageUrl(job)
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
  const styles = stylesQuery.data?.styles || []
  const categories = stylesQuery.data?.categories || []
  const groupedStyleOptions = categories.map((category) => ({
    label: category.name_zh,
    options: styles.filter((style) => style.category === category.id).map((style) => ({
      value: style.id,
      label: `${style.name_zh} / ${style.name_en}`,
    })),
  }))

  const completedAgents = recipe.agentStatus.filter((item) => item.status === "completed").length
  const runningAgent = recipe.agentStatus.find((item) => item.status === "running")

  async function persist(next: RecipeProject, extra?: { title?: string; source_script?: string }) {
    setSaving(true)
    try {
      await updateDirectorProjectRecord(projectId, {
        title: extra?.title ?? next.script.title ?? "未命名导演工程",
        summary: next.script.summary,
        source_script: extra?.source_script ?? goal,
        payload: next,
      }, csrfToken)
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存失败")
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
      await queryClient.invalidateQueries({ queryKey: ["director-project", projectId] })
      await queryClient.invalidateQueries({ queryKey: ["director-projects"] })
      message.success("导演流水线已完成")
    } catch (error) {
      message.error(error instanceof Error ? error.message : "流水线失败")
    } finally {
      setRunning(false)
    }
  }

  async function handleRerun(agentId: RecipeAgentId) {
    setRunning(true)
    try {
      const row = await runDirectorRecipeStep(projectId, { agent_id: agentId, goal, art_style_id: recipe.artStyle?.id }, csrfToken)
      const payload = recipePayloadFromApi(row)
      if (payload) setRecipe(payload)
    } catch (error) {
      message.error(error instanceof Error ? error.message : "重跑失败")
    } finally {
      setRunning(false)
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
      message.error(error instanceof Error ? error.message : "定妆失败")
    }
  }

  async function handleRender(shotIds?: string[]) {
    try {
      const row = await renderDirectorShots(projectId, { shot_ids: shotIds, render_pass: "final" }, csrfToken)
      const payload = recipePayloadFromApi(row)
      if (payload) setRecipe(payload)
      await queryClient.invalidateQueries({ queryKey: ["jobs"] })
      message.success(shotIds?.length === 1 ? "已提交这一镜" : "已提交分镜视频")
    } catch (error) {
      message.error(error instanceof Error ? error.message : "提交失败")
    }
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

  return (
    <div className="director-recipe-shell">
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
            <Progress percent={Math.round((completedAgents / AGENT_ORDER.length) * 100)} size="small" />
            <p>{runningAgent ? `正在运行：${RECIPE_AGENT_LABELS[runningAgent.id]}` : `已完成 ${completedAgents} / ${AGENT_ORDER.length} 步`}</p>
          </div>
          <ol className="director-agent-list">
            {AGENT_ORDER.map((agentId) => {
              const item = recipe.agentStatus.find((entry) => entry.id === agentId)
              return (
                <li key={agentId}>
                  <Tag color={statusColor(item?.status)}>{RECIPE_AGENT_LABELS[agentId]}</Tag>
                  <Button type="link" size="small" disabled={running} onClick={() => handleRerun(agentId)}>重跑</Button>
                </li>
              )
            })}
          </ol>
        </aside>

        <section className="director-recipe-main">
          <Tabs
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
                      onChange={(styleId: string) => {
                        const style = styles.find((item) => item.id === styleId)
                        if (!style) return
                        updateRecipe((current) => ({
                          ...current,
                          artStyle: { id: style.id, name: style.name_zh, name_en: style.name_en, promptPrefix: style.promptPrefix },
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
                            artStyle: { id: style.id, name: style.name_zh, name_en: style.name_en, promptPrefix: style.promptPrefix },
                          }))}
                        >
                          <strong>{style.name_zh}</strong>
                          <span>{style.category_name_zh}</span>
                          <em>{style.description}</em>
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
                          description={character.promptText || character.description}
                          imageUrl={character.imageUrl}
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
                          description={location.promptText || location.description}
                          imageUrl={location.imageUrl}
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
                      <Typography.Title level={5}>分镜预览</Typography.Title>
                      <Button type="primary" icon={<Clapperboard size={14} />} disabled={!shots.length} onClick={() => handleRender()}>全部出片</Button>
                    </div>
                    <div className="director-shot-wall">
                      {shots.map((shot) => (
                        <Card key={shot.id} className="director-shot-card" size="small" title={`#${shot.shotNumber} ${shot.title}`}>
                          {shot.outputVideoUrl ? (
                            <video src={shot.outputVideoUrl} controls playsInline className="director-shot-video" />
                          ) : (
                            <p className="director-shot-desc">{shot.description}</p>
                          )}
                          {shot.dialogue ? <p className="director-shot-dialogue">「{shot.dialogue}」</p> : null}
                          <div className="director-shot-meta">
                            <Tag color={statusColor(shot.status)}>{shot.status}</Tag>
                            <span>{shot.durationSec}s</span>
                            <span>{shot.characterNames.join("、") || "无角色"}</span>
                          </div>
                          <Space>
                            <Button size="small" loading={shot.status === "queued" || shot.status === "running"} onClick={() => handleRender([shot.id])}>生成这一镜</Button>
                          </Space>
                        </Card>
                      ))}
                      {!shots.length && <Empty description="运行流水线后会出现分镜卡片" />}
                    </div>
                  </div>
                ),
              },
            ]}
          />
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
    </div>
  )
}

function AssetCard({
  title,
  description,
  imageUrl,
  onGenerate,
  onChange,
}: {
  title: string
  description: string
  imageUrl?: string | null
  onGenerate: () => void
  onChange: (patch: Partial<RecipeCharacter & RecipeLocation>) => void
}) {
  return (
    <Card
      className="director-asset-card"
      size="small"
      cover={imageUrl ? <img src={imageUrl} alt={title} className="director-asset-cover" /> : <div className="director-asset-placeholder">待定妆</div>}
    >
      <Input value={title} onChange={(event) => onChange({ name: event.target.value })} />
      <Input.TextArea
        value={description}
        autoSize={{ minRows: 2, maxRows: 4 }}
        onChange={(event) => onChange({ promptText: event.target.value, description: event.target.value })}
      />
      <Button size="small" icon={<RefreshCw size={12} />} onClick={onGenerate}>生成定妆</Button>
    </Card>
  )
}
