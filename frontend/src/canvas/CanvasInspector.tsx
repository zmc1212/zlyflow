import { useReactFlow } from "@xyflow/react"
import { Alert, Button, Input, InputNumber, Tag, Typography, message } from "antd"
import { Images, Play, Upload } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { isSafeMediaUrl, type CanvasCoverPatch, type CanvasMediaKind, type CanvasNode } from "./canvas-model"
import {
  CANVAS_COVER_FILE_MAX_BYTES,
  canvasCoverFromFile,
  canvasCoverSummary,
  forgetCanvasCoverCapture,
  readCanvasCover,
  requestCanvasCoverCapture,
  type CanvasCoverCropRect,
} from "./canvas-cover"
import CanvasCoverCropModal from "./CanvasCoverCropModal"
import { readCanvasRunSnapshot } from "./canvas-generation"
import type { CanvasMediaPreview } from "./CanvasNodes"
import { CanvasRunTrace } from "./CanvasRunTrace"

export function CanvasNodeInspector({ node, onPreview, onReplaceAsset, onUpdateCover, onOpenJob }: {
  node: CanvasNode
  onPreview: (preview: CanvasMediaPreview) => void
  onReplaceAsset: (nodeId: string, kind: CanvasMediaKind) => void
  onUpdateCover: (nodeId: string, patch: CanvasCoverPatch) => void
  onOpenJob: (jobId: string, kind?: CanvasMediaKind) => void
}) {
  const { updateNodeData } = useReactFlow()
  const mediaKind: CanvasMediaKind | null = node.type === "image" || node.type === "video"
    ? node.type
    : null
  const [urlDraft, setUrlDraft] = useState(String(node.data.url ?? ""))
  const [coverTimeDraft, setCoverTimeDraft] = useState<string | number>("")
  const [coverBusy, setCoverBusy] = useState(false)
  const [coverCropFile, setCoverCropFile] = useState<File | null>(null)
  const [coverApplying, setCoverApplying] = useState(false)
  const coverFileRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    setUrlDraft(String(node.data.url ?? ""))
  }, [node.id, node.data.url])

  useEffect(() => {
    setCoverTimeDraft(
      typeof node.data.coverTime === "number" && node.data.coverTime > 0 ? node.data.coverTime : "",
    )
  }, [node.id, node.data.coverTime])

  useEffect(() => {
    setCoverCropFile(null)
  }, [node.id])

  if (node.type === "unknown") {
    return (
      <div className="canvas-inspector">
        <Alert
          type="warning"
          showIcon
          title="未识别节点"
          description={`该节点由更新版本创建（类型「${node.data.originalType || "unknown"}」），当前版本只保留内容，不提供属性编辑。`}
        />
        <dl className="canvas-inspector-meta">
          <dt>原始类型</dt>
          <dd><Typography.Text code>{node.data.originalType || "unknown"}</Typography.Text></dd>
          <dt>节点 ID</dt>
          <dd><Typography.Text code copyable={{ text: node.id }} ellipsis>{node.id}</Typography.Text></dd>
        </dl>
      </div>
    )
  }

  const urlInvalid = Boolean(urlDraft.trim()) && !isSafeMediaUrl(urlDraft, mediaKind ?? "image")
  const videoUrl = String(node.data.url ?? "").trim()
  const cover = mediaKind === "video" ? readCanvasCover(node.data) : null
  const changeUrl = (value: string) => {
    setUrlDraft(value)
    const trimmed = value.trim()
    if (!trimmed || isSafeMediaUrl(trimmed, mediaKind ?? "image")) {
      if (trimmed === String(node.data.url ?? "")) return
      updateNodeData(node.id, mediaKind === "video"
        ? { url: trimmed, cover: undefined, coverSource: undefined, coverTime: undefined }
        : { url: trimmed })
    }
  }
  const retakeCover = () => {
    forgetCanvasCoverCapture(videoUrl)
    onUpdateCover(node.id, { cover: undefined, coverSource: undefined, coverTime: undefined })
    setCoverTimeDraft("")
    message.info("已恢复自动取帧")
  }
  const captureCoverAt = async () => {
    if (!videoUrl) return
    const seconds = typeof coverTimeDraft === "number"
      ? coverTimeDraft
      : coverTimeDraft.trim() === "" ? Number.NaN : Number(coverTimeDraft)
    if (!Number.isFinite(seconds) || seconds < 0) {
      message.warning("请输入不小于 0 的取帧时间")
      return
    }
    setCoverBusy(true)
    forgetCanvasCoverCapture(videoUrl)
    try {
      const capture = await requestCanvasCoverCapture(videoUrl, seconds)
      if (!capture) {
        message.error("无法从该视频取帧，跨域视频需目标服务器允许 CORS")
        return
      }
      const actual = Math.round(capture.time * 100) / 100
      onUpdateCover(node.id, { cover: capture.cover, coverSource: videoUrl, coverTime: actual })
      setCoverTimeDraft(actual)
      message.success(`已截取 ${actual.toFixed(1)} 秒处的封面`)
    } catch {
      message.error("封面截取失败，请重试")
    } finally {
      setCoverBusy(false)
    }
  }
  const openCoverCrop = (file: File) => {
    if (!videoUrl) return
    if (!file.type.startsWith("image/")) {
      message.warning("请选择图片文件")
      return
    }
    if (file.size > CANVAS_COVER_FILE_MAX_BYTES) {
      message.error("封面图片需小于 16 MB")
      return
    }
    setCoverCropFile(file)
  }
  const applyCoverCrop = async (crop: CanvasCoverCropRect) => {
    const file = coverCropFile
    if (!file || !videoUrl) return
    setCoverApplying(true)
    try {
      const capture = await canvasCoverFromFile(file, crop)
      if (!capture) {
        message.error("封面图片读取失败，请选择小于 16 MB 的图片")
        return
      }
      onUpdateCover(node.id, { cover: capture.cover, coverSource: videoUrl, coverTime: undefined })
      setCoverTimeDraft("")
      setCoverCropFile(null)
      message.success("已裁切并写入封面")
    } catch {
      message.error("封面图片读取失败，请重试")
    } finally {
      setCoverApplying(false)
    }
  }

  return (
    <div className="canvas-inspector">
      {node.type === "text" ? (
        <section className="canvas-inspector-section">
          <h4 className="canvas-inspector-section-title">文字</h4>
          <div className="canvas-inspector-field">
            <span className="canvas-inspector-field-label">文字内容</span>
            <Input.TextArea
              id={`canvas-inspector-text-${node.id}`}
              name="canvas-inspector-text"
              value={node.data.text ?? ""}
              autoSize={{ minRows: 6, maxRows: 14 }}
              placeholder="输入画布上的文字…"
              onChange={(event) => updateNodeData(node.id, { text: event.target.value })}
            />
          </div>
          <p className="canvas-inspector-hint">修改会立即进入自动保存与撤销链路。</p>
        </section>
      ) : null}

      {node.type === "artboard" ? (
        <section className="canvas-inspector-section">
          <h4 className="canvas-inspector-section-title">画板</h4>
          <div className="canvas-inspector-field">
            <span className="canvas-inspector-field-label">标题</span>
            <Input
              id={`canvas-inspector-artboard-${node.id}`}
              name="canvas-inspector-artboard"
              value={node.data.label ?? ""}
              maxLength={80}
              placeholder="画板标题"
              onChange={(event) => updateNodeData(node.id, { label: event.target.value })}
            />
          </div>
          <p className="canvas-inspector-hint">当前尺寸 {artboardSizeLabel(node)}，可在画布上拖动节点手柄调整。</p>
        </section>
      ) : null}

      {mediaKind ? (
        <>
          <section className="canvas-inspector-section">
            <h4 className="canvas-inspector-section-title">基础信息</h4>
            <div className="canvas-inspector-field">
              <span className="canvas-inspector-field-label">标签</span>
              <Input
                id={`canvas-inspector-label-${node.id}`}
                name="canvas-inspector-label"
                aria-label="素材标签"
                value={node.data.label ?? ""}
                maxLength={80}
                placeholder="用于识别这张素材"
                onChange={(event) => updateNodeData(node.id, { label: event.target.value })}
              />
            </div>
            <div className="canvas-inspector-field">
              <span className="canvas-inspector-field-label">说明 / 字幕</span>
              <Input.TextArea
                id={`canvas-inspector-caption-${node.id}`}
                name="canvas-inspector-caption"
                aria-label="说明与字幕"
                value={node.data.caption ?? ""}
                autoSize={{ minRows: 2, maxRows: 5 }}
                maxLength={300}
                placeholder="补充画面说明、台词或字幕"
                onChange={(event) => updateNodeData(node.id, { caption: event.target.value })}
              />
            </div>
          </section>

          <section className="canvas-inspector-section">
            <h4 className="canvas-inspector-section-title">媒体</h4>
            <div className="canvas-inspector-field">
              <span className="canvas-inspector-field-label">地址</span>
              <Input
                id={`canvas-inspector-url-${node.id}`}
                name="canvas-inspector-url"
                aria-label="媒体地址"
                value={urlDraft}
                status={urlInvalid ? "error" : undefined}
                placeholder="https://… 或 /api/media/…"
                onChange={(event) => changeUrl(event.target.value)}
                onPressEnter={(event) => (event.target as HTMLInputElement).blur()}
              />
              <p className={`canvas-inspector-hint${urlInvalid ? " is-error" : ""}`}>
                {urlInvalid
                  ? mediaKind === "image"
                    ? "地址需以 http(s):// 或 / 开头，也可使用 data:image 地址。"
                    : "地址需以 http(s):// 或 / 开头，视频不支持 data: 或其它协议。"
                  : mediaKind === "image"
                    ? "支持 http(s)、站内路径和 data:image 地址；留空显示图片占位。"
                    : "支持 http(s) 和站内路径；留空显示视频占位。"}
              </p>
            </div>
            {mediaKind === "video" ? (
              <div className="canvas-inspector-field">
                <span className="canvas-inspector-field-label">封面帧</span>
                {cover ? (
                  <div className="canvas-cover-preview">
                    <img className="canvas-cover-thumb" src={cover} alt="视频封面帧" />
                    <div className="canvas-cover-meta">
                      <span>{canvasCoverSummary(cover, node.data.coverTime)}</span>
                    </div>
                  </div>
                ) : (
                  <p className="canvas-inspector-hint">暂未截取封面。视频加载后会自动从开头取一帧；跨域视频需目标服务器允许 CORS。</p>
                )}
                <div className="canvas-cover-controls">
                  <InputNumber
                    id={`canvas-inspector-cover-time-${node.id}`}
                    name="canvas-inspector-cover-time"
                    aria-label="封面取帧时间（秒）"
                    min={0}
                    step={0.1}
                    precision={2}
                    value={coverTimeDraft}
                    placeholder="取帧秒数"
                    disabled={!videoUrl || coverBusy}
                    style={{ width: 112 }}
                    onChange={(value) => setCoverTimeDraft(value ?? "")}
                  />
                  <Button size="small" aria-label="按时间取帧" aria-busy={coverBusy} loading={coverBusy} disabled={!videoUrl} onClick={() => { void captureCoverAt() }}>
                    按时间取帧
                  </Button>
                  <Button
                    size="small"
                    icon={<Upload size={14} />}
                    disabled={!videoUrl || coverBusy}
                    onClick={() => coverFileRef.current?.click()}
                  >
                    上传封面
                  </Button>
                  <Button size="small" disabled={!videoUrl || coverBusy} onClick={retakeCover}>自动取帧</Button>
                </div>
                <input
                  ref={coverFileRef}
                  type="file"
                  accept="image/*"
                  hidden
                  aria-label="上传封面图片"
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    event.target.value = ""
                    if (file) openCoverCrop(file)
                  }}
                />
                <p className="canvas-inspector-hint">
                  上传图片可先裁切比例与取景，再压缩成 320 px JPEG；封面改动随草稿自动保存，不进入撤销栈。
                </p>
              </div>
            ) : null}
            <div className="canvas-inspector-actions">
              <Button
                icon={<Play size={15} />}
                disabled={!node.data.url}
                onClick={() => onPreview({
                  url: String(node.data.url),
                  label: node.data.label,
                  kind: mediaKind,
                  poster: cover ?? undefined,
                })}
              >
                打开预览
              </Button>
              <Button icon={<Images size={15} />} onClick={() => onReplaceAsset(node.id, mediaKind)}>
                从作品库替换
              </Button>
            </div>
          </section>

          <section className="canvas-inspector-section">
            <h4 className="canvas-inspector-section-title">来源</h4>
            <dl className="canvas-inspector-meta">
              <dt>媒体类型</dt>
              <dd><Tag variant="filled">{mediaKind === "video" ? "视频" : "图片"}</Tag></dd>
              <dt>来源素材</dt>
              <dd>
                {node.data.assetPath ? (
                  <Typography.Text code copyable={{ text: node.data.assetPath }} ellipsis>
                    {node.data.assetPath}
                  </Typography.Text>
                ) : (
                  <span className="canvas-inspector-empty">未关联作品库素材</span>
                )}
              </dd>
              {!node.data.sourceJobId ? (
                <>
                  <dt>来源任务</dt>
                  <dd><span className="canvas-inspector-empty">未关联生成任务</span></dd>
                </>
              ) : null}
            </dl>
          </section>

          <CanvasRunTrace
            title="来源任务与运行参数"
            jobId={node.data.sourceJobId ?? null}
            snapshot={readCanvasRunSnapshot(node.data.sourceRun)}
            mediaKind={mediaKind}
            onOpenJob={onOpenJob}
          />
        </>
      ) : null}

      <CanvasCoverCropModal
        open={Boolean(coverCropFile)}
        file={coverCropFile}
        applying={coverApplying}
        onCancel={() => {
          if (!coverApplying) setCoverCropFile(null)
        }}
        onApply={(crop) => {
          void applyCoverCrop(crop)
        }}
      />
    </div>
  )
}

function artboardSizeLabel(node: CanvasNode) {
  const width = Math.round(Number(node.measured?.width ?? node.style?.width ?? node.width ?? 0))
  const height = Math.round(Number(node.measured?.height ?? node.style?.height ?? node.height ?? 0))
  return width && height ? `${width} × ${height}` : "未知"
}
