import { Button } from "antd"
import { FileVideo, ImagePlus, Maximize2, X } from "lucide-react"
import { useId } from "react"
import type { MotionReferenceAsset } from "./motion-transfer"
import "./motion-transfer.css"

export default function MotionTransferReferences({
  labels, portrait, motion, onPickPortrait, onPickMotion, onRemovePortrait, onRemoveMotion,
  onPreviewPortrait, onPreviewMotion, onMotionDuration,
}: {
  labels: string[]
  portrait?: MotionReferenceAsset
  motion: MotionReferenceAsset | null
  onPickPortrait: (files: FileList | File[] | null) => void
  onPickMotion: (files: FileList | File[] | null) => void
  onRemovePortrait: () => void
  onRemoveMotion: () => void
  onPreviewPortrait: () => void
  onPreviewMotion: () => void
  onMotionDuration: (id: string, duration: number) => void
}) {
  const id = useId()
  return <div className="studio-motion-references" aria-label="动作迁移参考素材">
    {(["image", "video"] as const).map((kind, index) => {
      const asset = kind === "image" ? portrait : motion
      const label = labels[index] || (kind === "image" ? "角色形象图" : "动作参考视频")
      const pick = kind === "image" ? onPickPortrait : onPickMotion
      return <div key={kind} className={`studio-motion-reference ${asset ? "is-filled" : ""}`}
        onDragOver={(event) => { event.preventDefault(); event.stopPropagation() }}
        onDrop={(event) => { event.preventDefault(); event.stopPropagation(); pick(event.dataTransfer.files) }}>
        {asset ? <Button type="text" className="studio-motion-reference-preview" aria-label={`预览${label}`}
          onClick={kind === "image" ? onPreviewPortrait : onPreviewMotion}>
          {kind === "image" ? <img src={asset.preview} alt={label} /> : <video key={asset.id} src={asset.preview} muted preload="metadata"
            onLoadedMetadata={(event) => onMotionDuration(asset.id, event.currentTarget.duration)} />}
          <Maximize2 size={13} className="studio-motion-reference-enlarge" />
        </Button> : <label className="studio-motion-reference-placeholder" htmlFor={`${id}-${kind}`}>
          {kind === "image" ? <ImagePlus size={19} /> : <FileVideo size={19} />}
        </label>}
        <label className="studio-motion-reference-label" htmlFor={`${id}-${kind}`}>
          <strong>{label}</strong>
          <span title={asset?.file.name}>{asset
            ? kind === "video" && asset.duration ? `${asset.duration.toFixed(1)} 秒 · 点击替换` : "点击替换"
            : kind === "image" ? "全身清晰 · 点击上传" : "MP4 / MOV · ≤50 MB"}</span>
        </label>
        <input id={`${id}-${kind}`} aria-label={`上传${label}`} type="file" className="sr-only"
          accept={kind === "image" ? "image/*" : "video/*,.mp4,.mov,.webm,.mkv,.m4v,.avi"}
          onChange={(event) => { pick(event.target.files); event.target.value = "" }} />
        {asset ? <Button type="text" size="small" className="studio-motion-reference-remove" aria-label={`移除${label}`}
          onClick={kind === "image" ? onRemovePortrait : onRemoveMotion} icon={<X size={11} />} /> : null}
      </div>
    })}
  </div>
}
