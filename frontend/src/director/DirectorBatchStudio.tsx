import { useQuery } from "@tanstack/react-query"
import { Button, Card, Input, InputNumber, Select, Space, Tag, Typography, message } from "antd"
import { ArrowLeft, Layers } from "lucide-react"
import { useEffect, useState } from "react"
import {
  batchPayloadFromApi, createDirectorBatch, getDirectorProject, listDirectorArtStyles,
  updateDirectorProjectRecord,
} from "./director-api"
import { jobVideoUrl, mergeDirectorStatus, shotStatusFromJob } from "./director-submit"
import { BatchRunPayload, createEmptyBatch } from "./types"

type JobLike = {
  id: string
  status?: string
  progress?: number
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
  const [payload, setPayload] = useState<BatchRunPayload>(() => createEmptyBatch())
  const [running, setRunning] = useState(false)

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
        }
      }),
    }))
  }, [allJobs])

  const styles = stylesQuery.data?.styles || []
  const categories = stylesQuery.data?.categories || []

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
        art_style_id: payload.artStyle?.id,
        title: theme.slice(0, 24),
        project_id: projectId,
      }, csrfToken)
      const batch = batchPayloadFromApi(row)
      if (batch) setPayload(batch)
      message.success(`已裂变 ${batch?.items.length || payload.count} 条并入队`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : "批量失败")
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="director-recipe-shell">
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
            onChange={(styleId: string | undefined) => {
              const style = styles.find((item) => item.id === styleId)
              setPayload((current) => ({
                ...current,
                artStyle: style ? { id: style.id, name: style.name_zh, name_en: style.name_en, promptPrefix: style.promptPrefix } : null,
              }))
            }}
          />
        </Card>

        <div className="director-batch-list">
          {payload.items.map((item) => (
            <Card key={item.id} className="director-shot-card" title={item.title} extra={<Tag>{item.status}</Tag>}>
              <p className="director-shot-desc">{item.script}</p>
              {item.outputVideoUrl ? (
                <video src={item.outputVideoUrl} controls playsInline className="director-shot-video" />
              ) : (
                <p className="director-project-meta">
                  {item.jobId ? `任务 ${item.jobId}` : "尚未入队"}
                </p>
              )}
            </Card>
          ))}
          {!payload.items.length && (
            <Card><Typography.Text type="secondary">填写主题后点击「裂变并生成」，会并行提交 H3 文生视频。</Typography.Text></Card>
          )}
        </div>
      </div>
    </div>
  )
}
