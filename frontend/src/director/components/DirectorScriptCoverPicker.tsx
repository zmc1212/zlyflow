import { Button, Tag, Upload, message } from "antd"
import { ImagePlus, Trash2 } from "lucide-react"

type Props = {
  coverUrl?: string | null
  busy?: boolean
  compact?: boolean
  onUpload: (file: File) => void | Promise<void>
  onRemove?: () => void | Promise<void>
}

const ACCEPT = ".png,.jpg,.jpeg,.webp,.gif,.bmp"
const MAX_BYTES = 10 * 1024 * 1024

function beforeUpload(file: File, onUpload: Props["onUpload"]): false | string {
  const isImage = file.type.startsWith("image/") || /\.(png|jpe?g|webp|gif|bmp)$/i.test(file.name)
  if (!isImage) {
    void message.error("请选择图片格式的剧本封面")
    return Upload.LIST_IGNORE
  }
  if (file.size > MAX_BYTES) {
    void message.error("剧本封面不能超过 10 MB")
    return Upload.LIST_IGNORE
  }
  void onUpload(file)
  return false
}

export default function DirectorScriptCoverPicker({ coverUrl, busy = false, compact = false, onUpload, onRemove }: Props) {
  return (
    <div className={`director-script-cover-picker${compact ? " is-compact" : ""}`}>
      <div className="director-script-cover-label">
        <span>剧本封面图</span>
        <Tag>可选</Tag>
      </div>
      {coverUrl ? (
        <div className="director-script-cover-preview">
          <img src={coverUrl} alt="剧本封面预览" />
          <div className="director-script-cover-actions">
            <Upload
              accept={ACCEPT}
              showUploadList={false}
              beforeUpload={(file) => beforeUpload(file, onUpload)}
              disabled={busy}
            >
              <Button size="small" icon={<ImagePlus size={14} />} disabled={busy}>替换</Button>
            </Upload>
            {onRemove ? (
              <Button
                size="small"
                type="text"
                danger
                icon={<Trash2 size={14} />}
                disabled={busy}
                onClick={() => { void onRemove() }}
              >
                移除
              </Button>
            ) : null}
          </div>
        </div>
      ) : (
        <Upload
          accept={ACCEPT}
          showUploadList={false}
          beforeUpload={(file) => beforeUpload(file, onUpload)}
          disabled={busy}
        >
          <button type="button" className="director-script-cover-empty" disabled={busy}>
            <ImagePlus size={18} />
            <span>
              <strong>上传一张封面图</strong>
              <small>PNG / JPG / WebP，最大 10 MB</small>
            </span>
          </button>
        </Upload>
      )}
      <p className="director-script-cover-hint">用于工程卡片与创作回放识别，不会自动成为故事场景。</p>
    </div>
  )
}
