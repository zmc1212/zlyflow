import { Button } from "antd"
import { FileVideo, Image as ImageIcon, ImagePlus, Maximize2, Play, Video, X } from "lucide-react"
import { useId } from "react"
import type { MotionReferenceAsset } from "./motion-transfer"
import "./motion-transfer.css"

export default function MotionTransferReferences({
  labels, portrait, motion, onPickPortrait, onPickMotion, onRemovePortrait, onRemoveMotion,
  onPreviewPortrait, onPreviewMotion, onMotionDuration, variant = "compact",
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
  variant?: "compact" | "tool"
}) {
  const id = useId()
  return <div className={`studio-motion-references${variant === "tool" ? " studio-motion-references-tool" : ""}`} aria-label="动作迁移参考素材">
    {(["image", "video"] as const).map((kind, index) => {
      const asset = kind === "image" ? portrait : motion
      const label = labels[index] || (kind === "image" ? "角色形象图" : "动作参考视频")
      const pick = kind === "image" ? onPickPortrait : onPickMotion
      return <div key={kind} className={`studio-motion-reference ${asset ? "is-filled" : ""}`}
        onDragOver={(event) => { event.preventDefault(); event.stopPropagation() }}
        onDrop={(event) => { event.preventDefault(); event.stopPropagation(); pick(event.dataTransfer.files) }}>
        {variant === "tool" ? <h2 className="studio-motion-reference-heading">
          {kind === "image" ? <ImageIcon size={19} /> : <Video size={19} />}{label}
        </h2> : null}
        <div className="studio-motion-reference-stage">
        {asset ? <Button type="text" className="studio-motion-reference-preview" aria-label={`预览${label}`}
          onClick={kind === "image" ? onPreviewPortrait : onPreviewMotion}>
          {kind === "image" ? <img src={asset.preview} alt={label} /> : <video key={asset.id} src={asset.preview} muted preload="metadata"
            onLoadedMetadata={(event) => onMotionDuration(asset.id, event.currentTarget.duration)} />}
          {variant === "tool" && kind === "video"
            ? <span className="studio-motion-reference-play"><Play size={24} fill="currentColor" /></span>
            : <Maximize2 size={13} className="studio-motion-reference-enlarge" />}
        </Button> : <label className="studio-motion-reference-placeholder" htmlFor={`${id}-${kind}`}>
          {kind === "image" ? <ImagePlus size={19} /> : <FileVideo size={19} />}
          {variant === "tool" ? <span>点击或拖入{label}</span> : null}
        </label>}
        <label className="studio-motion-reference-label" htmlFor={`${id}-${kind}`}>
          {variant === "compact" ? <strong title={label}>{label}</strong> : null}
          <span title={asset?.file.name}>{variant === "tool"
            ? kind === "image" ? `全身清晰 · 点击${asset ? "替换" : "上传"}` : asset ? "点击替换" : "MP4 / MOV · ≤50 MB"
            : asset
            ? kind === "video" && asset.duration ? `${asset.duration.toFixed(1)} 秒 · 点击替换` : "点击替换"
            : kind === "image" ? "全身清晰 · 点击上传" : "MP4 / MOV · ≤50 MB"}</span>
        </label>
        {variant === "tool" && kind === "video" && asset?.duration ? <span className="studio-motion-reference-duration">{asset.duration.toFixed(1)} 秒</span> : null}
        </div>
        <input id={`${id}-${kind}`} aria-label={`上传${label}`} type="file" className="sr-only"
          accept={kind === "image" ? "image/*" : "video/*,.mp4,.mov,.webm,.mkv,.m4v,.avi"}
          onChange={(event) => { pick(event.target.files); event.target.value = "" }} />
        {asset ? <Button type="text" size="small" className="studio-motion-reference-remove" aria-label={`移除${label}`}
          onClick={kind === "image" ? onRemovePortrait : onRemoveMotion} icon={<X size={11} />} /> : null}
      </div>
    })}
  </div>
}
