import { useRef, useState } from "react"
import { Button, Popconfirm } from "antd"
import { ImagePlus, Sparkles, Trash2 } from "lucide-react"
import type { Director2Asset } from "../../api"
import {
  MAX_SOURCE_REFERENCES,
  remainingSourceReferenceSlots,
  sourceReferenceHint,
  sourceReferencesOf,
} from "../../asset-source-references"
import { useMediaPreview } from "../../media-preview"

const ACCEPT = "image/jpeg,image/png,image/webp,image/gif,.jpg,.jpeg,.png,.webp,.gif"

interface AssetSourceReferenceStripProps {
  asset: Director2Asset
  uploading: boolean
  inferring?: boolean
  onUpload: (files: File[]) => void
  onRemove: (refId: string) => void
  onInferPrompts?: () => void
}

export default function AssetSourceReferenceStrip({
  asset,
  uploading,
  inferring = false,
  onUpload,
  onRemove,
  onInferPrompts,
}: AssetSourceReferenceStripProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)
  const { openMediaPreview } = useMediaPreview()
  const items = sourceReferencesOf(asset)
  const remaining = remainingSourceReferenceSlots(asset)
  const hint = sourceReferenceHint(asset.kind)
  const canUpload = remaining > 0 && !uploading
  const inferCopy = asset.kind === "character"
    ? "会覆盖头像提示词、面部提示词、描述和当前造型的服装描述。"
    : asset.kind === "scene"
      ? "会覆盖主视角、反打和全景提示词。"
      : "会覆盖道具概念图提示词和描述。"

  function takeFiles(list: FileList | null) {
    if (!canUpload || !list?.length) return
    const files = Array.from(list).filter((file) => file instanceof File)
    if (files.length) onUpload(files)
    if (inputRef.current) inputRef.current.value = ""
  }

  function prevent(event: React.DragEvent) {
    event.preventDefault()
    event.stopPropagation()
  }

  const thumbs = items.length ? (
    <div
      className="asset-source-ref-row"
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => event.stopPropagation()}
    >
      {items.map((item, index) => (
        <div
          key={item.id}
          className="asset-source-ref-thumb"
          role="button"
          tabIndex={0}
          title="放大查看"
          onClick={(event) => {
            event.stopPropagation()
            openMediaPreview({ src: item.url, title: item.filename || `原片参考图 ${index + 1}` })
          }}
          onKeyDown={(event) => {
            if (event.key !== "Enter" && event.key !== " ") return
            event.preventDefault()
            event.stopPropagation()
            openMediaPreview({ src: item.url, title: item.filename || `原片参考图 ${index + 1}` })
          }}
        >
          <img src={item.url} alt={item.filename || `参考图 ${index + 1}`} />
          <span className="asset-source-ref-index">{index + 1}</span>
          <Popconfirm
            title="删除这张原片参考图？"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => onRemove(item.id)}
          >
            <button
              type="button"
              className="asset-source-ref-remove"
              title="删除参考图"
              onClick={(event) => event.stopPropagation()}
            >
              <Trash2 size={11} />
            </button>
          </Popconfirm>
        </div>
      ))}
    </div>
  ) : null

  const dropCopy = remaining > 0 ? (
    <div className="asset-source-ref-drop-copy">
      <ImagePlus size={22} />
      <strong>{items.length ? "继续拖入截图" : "拖入原片截图"}</strong>
      <span>{uploading ? "正在上传…" : "也可以点击选择文件"}</span>
    </div>
  ) : (
    <p className="asset-source-ref-full">已满 {MAX_SOURCE_REFERENCES} 张</p>
  )

  return (
    <div className="asset-source-ref-strip">
      <div className="asset-source-ref-label-row">
        <span className="asset-source-ref-label">原片参考</span>
        <span className="asset-source-ref-count">{items.length}/{MAX_SOURCE_REFERENCES}</span>
      </div>
      <div
        className={[
          "asset-source-ref-dropzone",
          items.length ? "has-items" : "",
          remaining <= 0 ? "is-full" : "",
          dragOver && canUpload ? "is-hover" : "",
        ].filter(Boolean).join(" ")}
        onDragEnter={(event) => {
          prevent(event)
          if (canUpload) setDragOver(true)
        }}
        onDragOver={(event) => {
          prevent(event)
          event.dataTransfer.dropEffect = canUpload ? "copy" : "none"
        }}
        onDragLeave={(event) => {
          prevent(event)
          if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragOver(false)
        }}
        onDrop={(event) => {
          prevent(event)
          setDragOver(false)
          takeFiles(event.dataTransfer.files)
        }}
        onClick={() => {
          if (canUpload) inputRef.current?.click()
        }}
        onKeyDown={(event) => {
          if (!canUpload) return
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault()
            inputRef.current?.click()
          }
        }}
        role="button"
        tabIndex={canUpload ? 0 : -1}
        aria-label="上传原片参考图"
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          multiple
          hidden
          disabled={!canUpload}
          onClick={(event) => event.stopPropagation()}
          onChange={(event) => takeFiles(event.target.files)}
        />
        {thumbs}
        {dropCopy}
      </div>
      <p className="asset-source-ref-hint">{hint}</p>
      {items.length && onInferPrompts ? (
        <Popconfirm
          title="用原片截图重写提示词？"
          description={inferCopy}
          okText="覆盖"
          cancelText="取消"
          onConfirm={onInferPrompts}
        >
          <Button
            size="small"
            className="asset-source-ref-infer"
            loading={inferring}
            disabled={uploading}
            icon={<Sparkles size={13} />}
            onClick={(event) => event.stopPropagation()}
          >
            根据原片反推提示词
          </Button>
        </Popconfirm>
      ) : null}
    </div>
  )
}
