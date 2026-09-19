import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, Button, Card, Input, Progress, Segmented, Space, Typography, Upload, message } from "antd"
import { ArrowLeft, FolderOpen, RefreshCw, Upload as UploadIcon } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import ThemeToggle from "../components/ThemeToggle"
import {
  createHypitOperation,
  getDirectorProject,
  revealHypitWorkspace,
  updateDirectorProjectRecord,
  uploadHypitSourceVideo,
} from "./director-api"
import { DirectorMobileHeader } from "./DirectorMobileChrome"
import { streamDirectorOperationEvents } from "./director-operation-stream"
import { isHypitPayload, normalizeHypitPayload } from "./hypit-model"
import type { HypitPayload } from "./hypit-model"

const HINT = "拆爆款结构（台词、字幕、B-roll、图形），不是锁运镜转绘。拉片走本机 WhisperX；写 SVML 仍需 Coding Agent（工作台对话不能代替）；编译走本机 Hypit CLI。若 Source 里有 H3 镜头，画面走局域网 ComfyUI http://192.168.10.54:8188，不占用本机 8188、也不会新开实例。"

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
  const [revision, setRevision] = useState(1)
  const [operationId, setOperationId] = useState<string | null>(null)
  const [statusLine, setStatusLine] = useState<{ progress: number; message?: string } | null>(null)
  const [starting, setStarting] = useState(false)
  const saveTimerRef = useRef<number | null>(null)
  const dirtyRef = useRef(false)
  const revisionRef = useRef(1)

  const projectQuery = useQuery({
    queryKey: ["director-project", projectId],
    queryFn: () => getDirectorProject(projectId),
    refetchInterval: operationId ? 1500 : false,
  })

  useEffect(() => {
    const record = projectQuery.data
    if (!record?.payload || dirtyRef.current) return
    if (!isHypitPayload(record.payload)) {
      message.error("这个工程不是 Hypit 复刻，请从首页第四张卡进入")
      return
    }
    setPayload(normalizeHypitPayload(record.payload))
    setRevision(record.content_revision)
    revisionRef.current = record.content_revision
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
        setOperationId(null)
        void queryClient.invalidateQueries({ queryKey: ["director-project", projectId] })
      }
      if (event.event === "error" || event.event === "cancelled") {
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
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current)
    saveTimerRef.current = window.setTimeout(() => {
      void persist(next)
    }, 500)
  }

  async function persist(current: HypitPayload) {
    try {
      const saved = await updateDirectorProjectRecord(projectId, {
        payload: current,
        expected_content_revision: revisionRef.current,
      }, csrfToken)
      setRevision(saved.content_revision)
      revisionRef.current = saved.content_revision
      dirtyRef.current = false
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存失败")
    }
  }

  async function customUpload(options: { file: File | Blob; onSuccess?: (body: unknown) => void; onError?: (error: Error) => void }) {
    const file = options.file instanceof File ? options.file : new File([options.file], "source.mp4")
    try {
      const saved = await uploadHypitSourceVideo(projectId, {
        file,
        expected_content_revision: revisionRef.current,
      }, csrfToken)
      if (isHypitPayload(saved.payload)) {
        setPayload(normalizeHypitPayload(saved.payload))
        setRevision(saved.content_revision)
        revisionRef.current = saved.content_revision
        dirtyRef.current = false
      }
      options.onSuccess?.(saved)
      message.success("参考片已上传")
    } catch (error) {
      const failed = error instanceof Error ? error : new Error("上传失败")
      options.onError?.(failed)
      message.error(failed.message)
    }
  }

  async function startOperation(kind: "hypit_transcribe" | "hypit_compile") {
    setStarting(true)
    try {
      if (dirtyRef.current) await persist(payload)
      const operation = await createHypitOperation(projectId, {
        kind,
        language: payload.language,
      }, csrfToken)
      setOperationId(operation.id)
      setStatusLine({ progress: operation.progress, message: kind === "hypit_transcribe" ? "正在拉片转写" : "正在编译" })
    } catch (error) {
      message.error(error instanceof Error ? error.message : "操作失败")
    } finally {
      setStarting(false)
    }
  }

  async function openFolder() {
    try {
      const revealed = await revealHypitWorkspace(projectId, csrfToken)
      message.success(`已打开 ${revealed.path}`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : "无法打开工程目录")
    }
  }

  const hasSource = Boolean(payload.sourceVideo?.url)
  const busy = starting || Boolean(operationId)
  const mobileTitle = payload.title || "Hypit 复刻"

  return (
    <div className="director-recipe-shell !h-0 !min-h-0 flex-1 overflow-hidden flex-col">
      <DirectorMobileHeader
        title={mobileTitle}
        onBack={onBack}
        menuItems={[{ key: "studio", label: "创作工作台", onClick: onExitDirector }]}
      />
      <header className="director-topbar">
        <button type="button" className="director-back-library" onClick={onBack}><ArrowLeft size={16} />返回</button>
        <div className="director-project-heading">
          <Typography.Title level={4} style={{ margin: 0 }}>Hypit 复刻</Typography.Title>
        </div>
        <Space>
          <ThemeToggle />
          <Button onClick={onExitDirector}>创作工作台</Button>
        </Space>
      </header>

      <div className="director-batch-scroll">
        <div className="replication-layout hypit-layout">
          <div className="replication-side">
            <Alert type="info" showIcon message="与参考片复刻并列" description={HINT} />
            <Card title="参考片" size="small">
              {!hasSource ? (
                <Upload.Dragger
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
                    accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm,.m4v"
                    showUploadList={false}
                    customRequest={(options) => { void customUpload(options) }}
                  >
                    <Button size="small" icon={<RefreshCw size={13} />}>更换参考片</Button>
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
                <Button type="primary" disabled={!hasSource || busy} loading={busy && payload.transcript.status === "running"} onClick={() => void startOperation("hypit_transcribe")}>
                  开始拉片
                </Button>
                <Button disabled={busy} onClick={() => void startOperation("hypit_compile")}>
                  编译成片
                </Button>
                <Button icon={<FolderOpen size={14} />} onClick={() => void openFolder()}>打开项目目录</Button>
              </Space>
            </Card>
          </div>

          <div className="replication-list">
            {statusLine ? (
              <div className="replication-progress">
                <Progress percent={statusLine.progress} status={payload.compile.status === "failed" || payload.transcript.status === "failed" ? "exception" : "active"} />
                <p className="replication-note">{statusLine.message}</p>
              </div>
            ) : null}
            {payload.transcript.error ? <Alert type="error" showIcon message={payload.transcript.error} /> : null}
            {payload.compile.error ? <Alert type="error" showIcon message={payload.compile.error} /> : null}
            {payload.transcript.status === "done" ? (
              <Card title="拉片转写" size="small">
                <p className="replication-note">
                  {payload.transcript.wordCount} 个词
                  {payload.transcript.durationSec ? ` · ${formatTime(payload.transcript.durationSec)}` : ""}
                  。这是 WhisperX 证据，还不是 SVML。
                </p>
                {payload.transcript.url ? <Button type="link" href={payload.transcript.url} target="_blank">查看 transcript JSON</Button> : null}
              </Card>
            ) : (
              <Card className="replication-empty" size="small">
                <p className="replication-note">上传参考片并填写「改什么」，然后拉片。没有 Agent 写好的 authors/*.svml 与 runs/*.svrun 时，编译会提示打开目录。</p>
              </Card>
            )}
            {payload.result.url ? (
              <Card title="成片预览" size="small">
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
