import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Button, Card, Input, InputNumber, Select, Space, Tag, Typography, message } from "antd"
import { ArrowLeft, Layers } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import JobErrorNotice from "./components/JobErrorNotice"
import { DirectorMobileBottomBar, DirectorMobileHeader } from "./DirectorMobileChrome"
import {
  batchPayloadFromApi, createDirectorBatch, getDirectorProject, listDirectorArtStyles, listWorkflowModes,
  renderDirectorBatchItems, updateDirectorProjectRecord,
} from "./director-api"
import { jobVideoUrl, mergeDirectorStatus, shotGenerationState, shotStatusFromJob } from "./director-submit"
import { DEFAULT_DIRECTOR_WORKFLOW_FAMILY, directorWorkflowFamilies } from "./director-workflows"
import { directorStatusColor, directorStatusLabel, isDirectorFailedStatus } from "./status-labels"
import { BatchRunPayload, createEmptyBatch, artStylePreviewUrl, recipeArtStyleFromCatalog, userFacingCopy, DIRECTOR_WEIGHT_OPTIONS, DirectorWeightProfile } from "./types"

type JobLike = {
  id: string
  status?: string
  progress?: number
  error?: string | null
  outputs?: Array<{ kind?: string; download_url?: string; path?: string }>
}

interface DirectorBatchStudioProps {
  projectId: string
  csrfToken: string
  allJobs: JobLike[]
  onBack: () => void
  onExitDirector?: () => void
}

export default function DirectorBatchStudio({
  projectId, csrfToken, allJobs, onBack, onExitDirector,
}: DirectorBatchStudioProps) {
  const queryClient = useQueryClient()
  const [payload, setPayload] = useState<BatchRunPayload>(() => createEmptyBatch())
  const [running, setRunning] = useState(false)
  const [retryingId, setRetryingId] = useState<string | null>(null)

  const projectQuery = useQuery({
    queryKey: ["director-project", projectId],
    queryFn: () => getDirectorProject(projectId),
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
    const batch = batchPayloadFromApi(row)
    if (batch) setPayload(batch)
    else if (row.source_script) setPayload((current) => ({ ...current, theme: row.source_script }))
  }, [projectQuery.data])

  useEffect(() => {
    setPayload((prev) => ({
      ...prev,
      items: prev.items.map((item) => {
        if (!item.jobId) return item
        const job = allJobs.find((entry) => entry.id === item.jobId)
        if (!job) return item
        return {
          ...item,
          status: mergeDirectorStatus(item.status, shotStatusFromJob(job)),
          outputVideoUrl: jobVideoUrl(job) || item.outputVideoUrl,
          error: job.error || item.error,
        }
      }),
    }))
  }, [allJobs])

  const styles = stylesQuery.data?.styles || []
  const categories = stylesQuery.data?.categories || []
  const workflowFamilies = useMemo(
    () => directorWorkflowFamilies(modesQuery.data?.modes || []),
    [modesQuery.data],
  )
  const workflowFamilyId = payload.videoWorkflowFamily || DEFAULT_DIRECTOR_WORKFLOW_FAMILY
  const workflowFamilyOptions = useMemo(() => {
    const options = workflowFamilies.map((item) => ({ value: item.id, label: item.label }))
    if (workflowFamilyId && !options.some((item) => item.value === workflowFamilyId)) {
      options.unshift({ value: workflowFamilyId, label: workflowFamilyId })
    }
    return options
  }, [workflowFamilies, workflowFamilyId])
  const mobileTitle = payload.theme.trim().slice(0, 24) || "短视频批量"

  async function handleRun() {
    const theme = payload.theme.trim()
    if (!theme) {
      message.warning("请填写主题")
      return
    }
    setRunning(true)
    try {
      await updateDirectorProjectRecord(projectId, {
        title: theme.slice(0, 24) || "批量短视频",
        summary: theme,
        source_script: theme,
        payload,
      }, csrfToken)
      const row = await createDirectorBatch({
        theme,
        count: payload.count,
        aspect_ratio: payload.aspectRatio,
        duration_sec: payload.durationSec,
        video_workflow_family: payload.videoWorkflowFamily || DEFAULT_DIRECTOR_WORKFLOW_FAMILY,
        art_style_id: payload.artStyle?.id,
        title: theme.slice(0, 24),
        project_id: projectId,
      }, csrfToken)
      const batch = batchPayloadFromApi(row)
      if (batch) setPayload(batch)
      await queryClient.invalidateQueries({ queryKey: ["jobs"] })
      message.success(`已裂变 ${batch?.items.length || payload.count} 条并入队`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : "批量失败")
    } finally {
      setRunning(false)
    }
  }

  async function handleRetryItem(itemId: string) {
    setRetryingId(itemId)
    try {
      const row = await renderDirectorBatchItems(projectId, { item_ids: [itemId] }, csrfToken)
      const batch = batchPayloadFromApi(row)
      if (batch) setPayload(batch)
      await queryClient.invalidateQueries({ queryKey: ["jobs"] })
      message.success("已重新提交这一项")
    } catch (error) {
      message.error(error instanceof Error ? error.message : "重试失败")
    } finally {
      setRetryingId(null)
    }
  }

  return (
    <div className="director-recipe-shell !h-0 !min-h-0 flex-1 overflow-hidden">
      <DirectorMobileHeader
        title={mobileTitle}
        onBack={onBack}
        menuItems={[
          { key: "studio", label: "创作工作台", onClick: onExitDirector },
        ]}
      />
      <header className="director-topbar">
        <button type="button" className="director-back-library" onClick={onBack}><ArrowLeft size={16} />返回</button>
        <div className="director-project-heading">
          <Typography.Title level={4} style={{ margin: 0 }}>短视频批量</Typography.Title>
        </div>
        <Space>
          <Button onClick={onExitDirector}>创作工作台</Button>
          <Button type="primary" icon={<Layers size={14} />} loading={running} onClick={handleRun}>裂变并生成</Button>
        </Space>
      </header>

      <div className="director-batch-layout">
        <Card className="director-batch-form" title="主题与参数">
          <Input.TextArea
            value={payload.theme}
            onChange={(event) => setPayload((current) => ({ ...current, theme: event.target.value }))}
            autoSize={{ minRows: 4, maxRows: 8 }}
            placeholder="例如：办公室久坐的人如何用 60 秒学会肩颈拉伸"
          />
          <div className="director-batch-fields">
            <label>
              条数
              <InputNumber min={1} max={8} value={payload.count} onChange={(value) => setPayload((current) => ({ ...current, count: Number(value) || 1 }))} />
            </label>
            <label>
              比例
              <Select
                value={payload.aspectRatio}
                options={[{ value: "9:16", label: "9:16 竖屏" }, { value: "16:9", label: "16:9 横屏" }, { value: "1:1", label: "1:1" }]}
                onChange={(value: string) => setPayload((current) => ({ ...current, aspectRatio: value }))}
              />
            </label>
            <label>
              时长（秒）
              <InputNumber min={2} max={15} value={payload.durationSec} onChange={(value) => setPayload((current) => ({ ...current, durationSec: Number(value) || 8 }))} />
            </label>
            <label>
              工作流
              <Select
                aria-label="工作流"
                value={workflowFamilyId}
                options={workflowFamilyOptions}
                onChange={(value: string) => setPayload((current) => ({ ...current, videoWorkflowFamily: value }))}
                popupMatchSelectWidth={false}
              />
            </label>
            <label>
              模型体积
              <Select
                aria-label="模型体积"
                value={payload.weightProfile || "full"}
                options={DIRECTOR_WEIGHT_OPTIONS}
                onChange={(value: DirectorWeightProfile) => setPayload((current) => ({ ...current, weightProfile: value }))}
                popupMatchSelectWidth={false}
              />
            </label>
          </div>
          <Select
            allowClear
            placeholder="可选画风"
            value={payload.artStyle?.id}
            options={categories.map((category) => ({
              label: category.name_zh,
              options: styles.filter((style) => style.category === category.id).map((style) => ({
                value: style.id,
                label: `${style.name_zh} / ${style.name_en}`,
              })),
            }))}
            optionRender={(option) => {
              const style = styles.find((item) => item.id === option.value)
              return (
                <span className="director-style-option">
                  {style ? (
                    <img src={artStylePreviewUrl(style)} alt="" onError={(event) => { event.currentTarget.style.display = "none" }} />
                  ) : null}
                  <span>{option.label}</span>
                </span>
              )
            }}
            onChange={(styleId: string | undefined) => {
              const style = styles.find((item) => item.id === styleId)
              setPayload((current) => ({
                ...current,
                artStyle: style ? recipeArtStyleFromCatalog(style) : null,
              }))
            }}
          />
        </Card>

        <div className="director-batch-list">
          {payload.items.map((item) => {
            const job = allJobs.find((entry) => entry.id === item.jobId)
            const state = shotGenerationState(job, item.outputVideoUrl, item.jobId, { status: item.status })
            const displayStatus = state.generating ? state.status : (state.status !== "idle" ? state.status : item.status)
            const failed = !state.generating && isDirectorFailedStatus(displayStatus)
            return (
              <Card
                key={item.id}
                className="director-shot-card"
                title={item.title}
                extra={<Tag color={directorStatusColor(displayStatus)}>{directorStatusLabel(displayStatus)}</Tag>}
              >
                <p className="director-shot-desc">{userFacingCopy(item.description, item.title)}</p>
                {item.outputVideoUrl && !state.generating ? (
                  <video src={item.outputVideoUrl} controls playsInline className="director-shot-video" />
                ) : (
                  <p className="director-project-meta">
                    {item.jobId ? `任务 ${item.jobId}` : "尚未入队"}
                  </p>
                )}
                <JobErrorNotice error={state.error || item.error} />
                {failed ? (
                  <Button
                    size="small"
                    loading={retryingId === item.id}
                    onClick={() => handleRetryItem(item.id)}
                  >
                    重试这一项
                  </Button>
                ) : null}
              </Card>
            )
          })}
          {!payload.items.length && (
            <Card><Typography.Text type="secondary">填写主题后点击「裂变并生成」，会按所选工作流并行提交文生视频。</Typography.Text></Card>
          )}
        </div>
      </div>
      <DirectorMobileBottomBar
        label="裂变并生成"
        onClick={() => { void handleRun() }}
        loading={running}
        disabled={running}
      />
    </div>
  )
}
