import { Button } from "antd"
import { ArrowLeft, ArrowRight, FileVideo, Image as ImageIcon, ImagePlus, Maximize2, Play, Video, X } from "lucide-react"
import { useId, type DragEvent } from "react"
import type { MotionReferenceAsset } from "./motion-transfer"
import "./motion-transfer.css"

/** 多人动作迁移:1-6 张角色形象图(顺序即 <Picture n> 顺序) + 1 个动作参考视频。 */
export default function MotionRefVideoReferences({
  labels, characters, maxCharacters, motion,
  onPickCharacters, onReplaceCharacter, onRemoveCharacter, onMoveCharacter, onPreviewCharacter,
  onPickMotion, onRemoveMotion, onPreviewMotion, onMotionDuration,
  variant = "compact",
}: {
  labels: string[]
  characters: MotionReferenceAsset[]
  maxCharacters: number
  motion: MotionReferenceAsset | null
  onPickCharacters: (files: FileList | File[] | null) => void
  onReplaceCharacter: (index: number, files: FileList | File[] | null) => void
  onRemoveCharacter: (index: number) => void
  onMoveCharacter: (index: number, direction: -1 | 1) => void
  onPreviewCharacter: (index: number) => void
  onPickMotion: (files: FileList | File[] | null) => void
  onRemoveMotion: () => void
  onPreviewMotion: () => void
  onMotionDuration: (id: string, duration: number) => void
  variant?: "compact" | "tool"
}) {
  const id = useId()
  const dropTargets = (index: number | null) => ({
    onDragOver: (event: DragEvent<HTMLDivElement>) => { event.preventDefault(); event.stopPropagation() },
    onDrop: (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault(); event.stopPropagation()
      const images = Array.from(event.dataTransfer.files).filter((file) => file.type.startsWith("image/"))
      if (index === null) onPickCharacters(images)
      else if (images[0]) onReplaceCharacter(index, [images[0]])
    },
  })
  const tool = variant === "tool"
  return <div className={`studio-motion-references${tool ? " studio-motion-references-tool studio-motion-references-multi" : ""}`} aria-label="多人动作迁移参考素材">
    {characters.map((asset, index) => {
      const label = labels[index] || `角色形象图 ${index + 1}`
      return <div key={asset.id} className="studio-motion-reference is-filled" {...dropTargets(index)}>
        {tool ? <h2 className="studio-motion-reference-heading"><ImageIcon size={19} />{label}</h2> : null}
        <div className="studio-motion-reference-stage">
          <Button type="text" className="studio-motion-reference-preview" aria-label={`预览${label}`} onClick={() => onPreviewCharacter(index)}>
            <img src={asset.preview} alt={label} />
            <Maximize2 size={13} className="studio-motion-reference-enlarge" />
          </Button>
          <label className="studio-motion-reference-label" htmlFor={`${id}-char-${index}`}>
            {tool ? null : <strong title={label}>{label}</strong>}
            <span title={asset.file.name}>{tool ? `表演者 ${index + 1} · 点击或拖入替换` : `表演者 ${index + 1} · 点击替换`}</span>
          </label>
        </div>
        <input id={`${id}-char-${index}`} aria-label={`替换${label}`} type="file" accept="image/*" className="sr-only"
          onChange={(event) => { onReplaceCharacter(index, event.target.files); event.target.value = "" }} />
        {index > 0 ? <Button type="text" size="small" className="studio-motion-reference-move" aria-label={`${label}前移`}
          onClick={() => onMoveCharacter(index, -1)} icon={<ArrowLeft size={11} />} /> : null}
        {index < characters.length - 1 ? <Button type="text" size="small" className="studio-motion-reference-move" aria-label={`${label}后移`}
          onClick={() => onMoveCharacter(index, 1)} icon={<ArrowRight size={11} />} /> : null}
        <Button type="text" size="small" className="studio-motion-reference-remove" aria-label={`移除${label}`}
          onClick={() => onRemoveCharacter(index)} icon={<X size={11} />} />
      </div>
    })}
    {characters.length < maxCharacters ? <div className="studio-motion-reference" {...dropTargets(null)}>
      {tool ? <h2 className="studio-motion-reference-heading"><ImagePlus size={19} />添加角色</h2> : null}
      <div className="studio-motion-reference-stage">
        <label className="studio-motion-reference-placeholder" htmlFor={`${id}-char-add`}>
          <ImagePlus size={19} />
          {tool ? <span>点击或拖入角色形象图（可多选）</span> : null}
        </label>
        <label className="studio-motion-reference-label" htmlFor={`${id}-char-add`}>
          {tool ? null : <strong>添加角色</strong>}
          <span title={`已添加 ${characters.length} / ${maxCharacters} · 顺序对应视频中表演者`}>已添加 {characters.length} / {maxCharacters} · 顺序对应视频中表演者</span>
        </label>
      </div>
      <input id={`${id}-char-add`} aria-label="添加角色形象图" type="file" accept="image/*" multiple className="sr-only"
        onChange={(event) => { onPickCharacters(event.target.files); event.target.value = "" }} />
    </div> : null}
    <div className={`studio-motion-reference${motion ? " is-filled" : ""}`} {...dropTargets(null)}>
      {tool ? <h2 className="studio-motion-reference-heading"><Video size={19} />{labels[maxCharacters] || "动作参考视频"}</h2> : null}
      <div className="studio-motion-reference-stage">
        {motion ? <Button type="text" className="studio-motion-reference-preview" aria-label="预览动作参考视频" onClick={onPreviewMotion}>
          <video key={motion.id} src={motion.preview} muted preload="metadata"
            onLoadedMetadata={(event) => onMotionDuration(motion.id, event.currentTarget.duration)} />
          <span className="studio-motion-reference-play"><Play size={24} fill="currentColor" /></span>
        </Button> : <label className="studio-motion-reference-placeholder" htmlFor={`${id}-motion`}>
          <FileVideo size={19} />
          {tool ? <span>点击或拖入动作参考视频</span> : null}
        </label>}
        <label className="studio-motion-reference-label" htmlFor={`${id}-motion`}>
          {tool ? null : <strong title={labels[maxCharacters] || "动作参考视频"}>{labels[maxCharacters] || "动作参考视频"}</strong>}
          <span title={motion?.file.name}>{tool
            ? (motion ? "点击替换" : "MP4 / MOV · ≤50 MB")
            : motion
            ? motion.duration ? `${motion.duration.toFixed(1)} 秒 · 点击替换` : "点击替换"
            : "MP4 / MOV · ≤50 MB"}</span>
        </label>
        {motion?.duration ? <span className="studio-motion-reference-duration">{motion.duration.toFixed(1)} 秒</span> : null}
      </div>
      <input id={`${id}-motion`} aria-label="上传动作参考视频" type="file" accept="video/*,.mp4,.mov,.webm,.mkv,.m4v,.avi" className="sr-only"
        onChange={(event) => { onPickMotion(event.target.files); event.target.value = "" }} />
      {motion ? <Button type="text" size="small" className="studio-motion-reference-remove" aria-label="移除动作参考视频"
        onClick={onRemoveMotion} icon={<X size={11} />} /> : null}
    </div>
  </div>
}
