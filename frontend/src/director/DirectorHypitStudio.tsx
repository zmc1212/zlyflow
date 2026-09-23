import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, Button, Card, Input, Progress, Segmented, Select, Space, Typography, Upload, message } from "antd"
import { ArrowLeft, FolderOpen, RefreshCw, Upload as UploadIcon } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import ThemeToggle from "../components/ThemeToggle"
import {
  createHypitOperation,
  getDirectorOperation,
  getDirectorProject,
  revealHypitWorkspace,
  updateDirectorProjectRecord,
  uploadHypitSourceVideo,
} from "./director-api"
import { DirectorMobileHeader } from "./DirectorMobileChrome"
import { streamDirectorOperationEvents } from "./director-operation-stream"
import {
  HYPIT_H3_QUALITIES,
  conflictingDirectorOperationId,
  hypitOperationMessage,
  hypitResumeFromProject,
  hypitStatusLineFromPayload,
  isHypitPayload,
  normalizeHypitPayload,
} from "./hypit-model"
import type { HypitH3Quality, HypitPayload } from "./hypit-model"

const HINT = "当前功能按参考片结构重新制作视频，会改变画面、动作或背景，不是保留原片的逐帧换脸。制作流程：转写参考片 → Coding Agent 制作工程 → 编译成片。"

function formatTime(seconds: number): string {
  const total = Math.max(0, Math.round(seconds * 10) / 10)
  const minutes = Math.floor(total / 60)
  const rest = total - minutes * 60
  return minutes > 0 ? `${minutes}分${rest.toFixed(1)}秒` : `${rest.toFixed(1)}秒`
}

interface DirectorHypitStudioProps {
  projectId: string
  csrfToken: string
  onBack: () => void
  onExitDirector?: () => void
}

export default function DirectorHypitStudio({
  projectId, csrfToken, onBack, onExitDirector,
}: DirectorHypitStudioProps) {
  const queryClient = useQueryClient()
  const [payload, setPayload] = useState<HypitPayload>(() => normalizeHypitPayload(null))
  const [operationId, setOperationId] = useState<string | null>(null)
  const [statusLine, setStatusLine] = useState<{ progress: number; message?: string } | null>(null)
  const [starting, setStarting] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [saveState, setSaveState] = useState<"saved" | "pending" | "failed">("saved")
  const saveTimerRef = useRef<number | null>(null)
  const dirtyRef = useRef(false)
  const revisionRef = useRef(1)
  const attachedOpRef = useRef<string | null>(null)
  const editVersionRef = useRef(0)
  const pendingSaveRef = useRef<Promise<void> | null>(null)
  const actionRef = useRef(false)

  useEffect(() => () => {
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current)
  }, [])

  const projectQuery = useQuery({
    queryKey: ["director-project", projectId],
    queryFn: () => getDirectorProject(projectId),
    refetchInterval: operationId || payload.transcript.status === "running" || payload.compile.status === "running" ? 1500 : false,
  })

  useEffect(() => {
    const record = projectQuery.data
    if (!record?.payload || dirtyRef.current) return
    if (!isHypitPayload(record.payload)) {
      message.error("这个工程不是 Hypit 复刻，请从首页第四张卡进入")
      return
    }
    const next = normalizeHypitPayload(record.payload)
    setPayload(next)
    revisionRef.current = record.content_revision

    const resume = hypitResumeFromProject(record)
    if (resume && attachedOpRef.current !== resume.operationId) {
      attachedOpRef.current = resume.operationId
      setOperationId(resume.operationId)
      setStatusLine((current) => current ?? { progress: resume.progress, message: resume.message })
    }
    const stored = hypitStatusLineFromPayload(next)
    const failed = next.compile.status === "failed" || next.transcript.status === "failed"
    if (stored && (resume || failed)) {
      setStatusLine((current) => {
        if (!current) return stored
        if (stored.progress > current.progress) return stored
        return current
      })
    }
  }, [projectQuery.data])

  useEffect(() => {
    if (!operationId) return undefined
    const abort = new AbortController()
    let cancelled = false
    void streamDirectorOperationEvents(operationId, (event) => {
      if (event.event === "status") {
        setStatusLine({ progress: event.data.progress ?? 0, message: event.data.message })
      }
      if (event.event === "done") {
        attachedOpRef.current = null
        setOperationId(null)
        void queryClient.invalidateQueries({ queryKey: ["director-project", projectId] })
      }
      if (event.event === "error" || event.event === "cancelled") {
        attachedOpRef.current = null
        setOperationId(null)
        setStatusLine({ progress: 100, message: event.data.message || "操作失败" })
        message.error(event.data.message || "操作失败")
        void queryClient.invalidateQueries({ queryKey: ["director-project", projectId] })
      }
    }, { signal: abort.signal, shouldContinue: () => !cancelled })
    return () => {
      cancelled = true
      abort.abort()
    }
  }, [operationId, projectId, queryClient])

  function queueSave(next: HypitPayload) {
    setPayload(next)
    dirtyRef.current = true
    editVersionRef.current += 1
    setSaveState("pending")
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current)
    saveTimerRef.current = window.setTimeout(() => {
      saveTimerRef.current = null
      void persist(next, editVersionRef.current).catch(() => undefined)
    }, 500)
  }

  function persist(current: HypitPayload, editVersion: number): Promise<void> {
    const previous = pendingSaveRef.current
    const request = (async () => {
      // Serialize writes so every request uses the revision returned by its predecessor.
      if (previous) await previous
      try {
        const saved = await updateDirectorProjectRecord(projectId, {
          payload: current,
          expected_content_revision: revisionRef.current,
        }, csrfToken)
        revisionRef.current = saved.content_revision
        if (editVersion === editVersionRef.current) {
          dirtyRef.current = false
          setSaveState("saved")
          queryClient.setQueryData(["director-project", projectId], saved)
        }
      } catch (error) {
        setSaveState("failed")
        message.error(error instanceof Error ? error.message : "保存失败")
        throw error
      }
    })()
    pendingSaveRef.current = request
    void request.finally(() => {
      if (pendingSaveRef.current === request) pendingSaveRef.current = null
    }).catch(() => undefined)
    return request
  }

  async function flushSave() {
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current)
    saveTimerRef.current = null
    if (pendingSaveRef.current) await pendingSaveRef.current
    if (dirtyRef.current) await persist(payload, editVersionRef.current)
  }

  async function leave(action: (() => void) | undefined) {
    try {
      await flushSave()
      action?.()
    } catch { /* Keep the draft visible when saving fails. */ }
  }

  async function customUpload(options: { file: File | Blob | string; onSuccess?: (body: unknown) => void; onError?: (error: Error) => void }) {
    if (actionRef.current) return
    if (typeof options.file === "string") {
      const failed = new Error("无效的参考片文件")
      options.onError?.(failed)
      message.error(failed.message)
      return
    }
    const file = options.file instanceof File ? options.file : new File([options.file], "source.mp4")
    actionRef.current = true
    setUploading(true)
    try {
      await flushSave()
      const saved = await uploadHypitSourceVideo(projectId, {
        file,
        expected_content_revision: revisionRef.current,
      }, csrfToken)
      if (isHypitPayload(saved.payload)) {
        setPayload(normalizeHypitPayload(saved.payload))
        revisionRef.current = saved.content_revision
        dirtyRef.current = false
        queryClient.setQueryData(["director-project", projectId], saved)
        setStatusLine(null)
      }
      options.onSuccess?.(saved)
      message.success("参考片已上传")
    } catch (error) {
      const failed = error instanceof Error ? error : new Error("上传失败")
      options.onError?.(failed)
      message.error(failed.message)
    } finally {
      actionRef.current = false
      setUploading(false)
    }
  }

  async function startOperation(kind: "hypit_transcribe" | "hypit_compile") {
    if (actionRef.current) return
    actionRef.current = true
    setStarting(true)
    try {
      await flushSave()
      const operation = await createHypitOperation(projectId, {
        kind,
        language: payload.language,
      }, csrfToken)
      attachedOpRef.current = operation.id
      setOperationId(operation.id)
      setStatusLine({ progress: operation.progress, message: hypitOperationMessage(kind) })
    } catch (error) {
      const existing = conflictingDirectorOperationId(error)
      if (existing) {
        attachedOpRef.current = existing
        setOperationId(existing)
        try {
          const current = await getDirectorOperation(existing)
          setStatusLine({
            progress: current.progress,
            message: hypitOperationMessage(current.kind),
          })
        } catch {
          setStatusLine({ progress: 0, message: "正在恢复未完成的任务" })
        }
        return
      }
      message.error(error instanceof Error ? error.message : "操作失败")
    } finally {
      actionRef.current = false
      setStarting(false)
    }
  }

  async function openFolder() {
    if (actionRef.current) return
    actionRef.current = true
    try {
      await flushSave()
      const revealed = await revealHypitWorkspace(projectId, csrfToken)
      message.success(`已打开 ${revealed.path}`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : "无法打开工程目录")
    } finally {
      actionRef.current = false
    }
  }

  const hasSource = Boolean(payload.sourceVideo?.url)
  const resume = hypitResumeFromProject(projectQuery.data)
  const live = Boolean(operationId) || Boolean(resume)
  const storedProgress = hypitStatusLineFromPayload(payload)
  const staleRunning = (payload.transcript.status === "running" || payload.compile.status === "running") && !live
  const progressView = staleRunning ? null : (statusLine ?? storedProgress)
  const jobRunning = live
  const busy = starting || uploading || live
  const mobileTitle = payload.title || "Hypit 复刻"

  return (
    <div className="director-recipe-shell !h-0 !min-h-0 flex-1 overflow-hidden flex-col">
      <DirectorMobileHeader
        title={mobileTitle}
        onBack={() => void leave(onBack)}
        menuItems={[{ key: "studio", label: "创作工作台", onClick: () => void leave(onExitDirector) }]}
      />
      <header className="director-topbar">
        <button type="button" className="director-back-library" onClick={() => void leave(onBack)}><ArrowLeft size={16} />返回</button>
        <div className="director-project-heading">
          <Typography.Title level={4} style={{ margin: 0 }}>Hypit 复刻</Typography.Title>
        </div>
        <Space>
          <ThemeToggle />
          <Button onClick={() => void leave(onExitDirector)}>创作工作台</Button>
        </Space>
      </header>

      <div className="director-batch-scroll">
        <div className="replication-layout hypit-layout">
          <div className="replication-side">
            <Alert type="info" showIcon message="Hypit 结构改编 · 非原片换脸" description={HINT} />
            <Card title="参考片" size="small">
              {!hasSource ? (
                <Upload.Dragger
                  disabled={busy}
                  maxCount={1}
                  accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm,.m4v"
                  showUploadList={false}
                  customRequest={(options) => { void customUpload(options) }}
                >
                  <p className="ant-upload-drag-icon"><UploadIcon size={28} /></p>
                  <p className="ant-upload-text">点击或拖入参考片</p>
                  <p className="ant-upload-hint">支持 mp4 / mov / webm，最大 2GB。用于拆结构，不是 VACE 深度转绘。</p>
                </Upload.Dragger>
              ) : (
                <div className="replication-source">
                  <video src={payload.sourceVideo!.url!} controls playsInline className="director-shot-video" />
                  <p className="replication-note">
                    {payload.sourceVideo!.width}×{payload.sourceVideo!.height}
                    {" · "}{formatTime(payload.sourceVideo!.durationSec)}
                  </p>
                  <Upload
                    disabled={busy}
                    maxCount={1}
                    accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm,.m4v"
                    showUploadList={false}
                    customRequest={(options) => { void customUpload(options) }}
                  >
                    <Button size="small" disabled={busy} loading={uploading} icon={<RefreshCw size={13} />}>更换参考片</Button>
                  </Upload>
                </div>
              )}
            </Card>

            <Card title="改什么" size="small">
              <Space direction="vertical" style={{ width: "100%" }} size={10}>
                <Input.TextArea
                  value={payload.brief}
                  rows={4}
                  maxLength={2000}
                  showCount
                  disabled={busy}
                  placeholder="例如：保留口播节奏，把产品和字幕换成我们的新品；不要锁原片运镜去转绘。"
                  onChange={(event) => queueSave({ ...payload, brief: event.target.value })}
                />
                <Typography.Text type={saveState === "failed" ? "danger" : "secondary"}>
                  {saveState === "saved" ? "需求已保存" : saveState === "pending" ? "正在保存需求…" : "保存失败，请重试；任务尚未启动"}
                </Typography.Text>
                {saveState === "failed" ? <Button size="small" onClick={() => void flushSave().catch(() => undefined)}>重试保存</Button> : null}
                <label className="replication-field">
                  转写语言
                  <Segmented
                    value={payload.language}
                    disabled={busy}
                    onChange={(value) => queueSave({ ...payload, language: value as "zh" | "en" })}
                    options={[
                      { label: "中文", value: "zh" },
                      { label: "英文", value: "en" },
                    ]}
                  />
                </label>
                <label className="replication-field">
                  H3 画质
                  <Select
                    value={payload.h3Quality}
                    disabled={busy}
                    onChange={(value) => queueSave({ ...payload, h3Quality: value as HypitH3Quality })}
                    options={HYPIT_H3_QUALITIES.map((item) => ({
                      value: item.value,
                      label: `${item.label} · ${item.width}×${item.height}`,
                      title: item.hint,
                    }))}
                  />
                  <span className="replication-note">
                    {HYPIT_H3_QUALITIES.find((item) => item.value === payload.h3Quality)?.hint
                      ?? "合成画布仍是 720×1280，这里只改 H3 原片尺寸。"}
                  </span>
                </label>
                <Button type="primary" disabled={!hasSource || busy} loading={busy && payload.transcript.status === "running"} onClick={() => void startOperation("hypit_transcribe")}>
                  1. 转写参考片
                </Button>
                <Button disabled={busy} icon={<FolderOpen size={14} />} onClick={() => void openFolder()}>2. 打开工程交给 Agent 制作</Button>
                <Button disabled={busy} onClick={() => void startOperation("hypit_compile")}>
                  3. 编译成片
                </Button>
                <p className="replication-note">打开工程时会同步最新需求。Agent 完成画面、配音和字幕制作后再编译。H3 使用「管理设置 → AI 供应商 → ComfyUI」中的地址。</p>
              </Space>
            </Card>
          </div>

          <div className="replication-list">
            {progressView ? (
              <div className="replication-progress">
                <Progress
                  percent={progressView.progress}
                  status={payload.compile.status === "failed" || payload.transcript.status === "failed"
                    ? "exception"
                    : payload.compile.status === "done" && !jobRunning && !operationId
                      ? "success"
                      : "active"}
                />
                <p className="replication-note">{progressView.message}</p>
              </div>
            ) : null}
            {payload.transcript.error ? <Alert type="error" showIcon message={payload.transcript.error} /> : null}
            {payload.compile.error ? <Alert type="error" showIcon message={payload.compile.error} /> : null}
            {payload.transcript.status === "done" ? (
              <Card title="转写证据 · 待 Agent 分析与制作" size="small">
                <p className="replication-note">
                  {payload.transcript.wordCount} 个词
                  {payload.transcript.durationSec ? ` · ${formatTime(payload.transcript.durationSec)}` : ""}
                  。这是 WhisperX 证据，还不是 SVML。
                </p>
                {payload.transcript.url ? <Button type="link" href={payload.transcript.url} target="_blank">查看 transcript JSON</Button> : null}
              </Card>
            ) : (
              <Card className="replication-empty" size="small">
                <p className="replication-note">上传参考片并填写「改什么」，先提取台词，再交给 Agent 分析画面、字幕、B-roll 和图形节奏。转写完成后仍需制作工程，才能编译成片。</p>
              </Card>
            )}
            {payload.result.url ? (
              <Card title={payload.compile.status === "failed" ? "上次成功成片 · 本次编译失败" : "成片预览"} size="small">
                <video src={payload.result.url} controls playsInline className="director-shot-video" />
                {payload.result.buildId ? <p className="replication-note">Hypit Build {payload.result.buildId}</p> : null}
              </Card>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  )
}
