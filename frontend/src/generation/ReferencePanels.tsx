import { FileVideo, ImagePlus, Maximize2, Mic, MoveLeft, MoveRight, Plus, X } from "lucide-react"
import { useState, type RefObject } from "react"
import type { MotionReferenceAsset } from "./motion-transfer"

/** 参考面板只依赖窄栏布局需要的字段，避免把整页 Workflow 类型带进组件。 */
export type ReferencePanelWorkflow = {
  reference_mode: "none" | "keyframes" | "collection" | "fixed"
  reference_labels: string[]
  max_references: number
}

export type ReferenceAsset = MotionReferenceAsset

/**
 * 窄栏内的参考槽统一使用 studio-reference-stack 两行等分布局：
 * 首尾帧、数字人形象图/音频都复用同一套高度、图标尺寸与文本省略规则。
 */
export function AvatarReferencePanel({
  workflow, portrait, audio, onPickAudio, onRemoveAudio, onReplacePortrait, onRemovePortrait, onPreview,
}: {
  workflow: ReferencePanelWorkflow; portrait?: ReferenceAsset; audio: { file: File; duration: number } | null
  onPickAudio: (files: FileList | File[] | null) => void; onRemoveAudio: () => void
  onReplacePortrait: (index: number, files: FileList | null) => void; onRemovePortrait: (index: number) => void
  onPreview: (index: number) => void
}) {
  const [portraitLabel, audioLabel] = workflow.reference_labels?.length === 2 ? workflow.reference_labels : ["人物形象图", "口播音频"]
  return <div className="studio-reference-panel studio-reference-stack grid gap-2">
    <label className={`studio-reference-slot group relative flex min-h-0 min-w-0 cursor-pointer items-center gap-2 overflow-hidden rounded-xl border px-2 transition ${portrait ? "border-[#7655ff]/80 bg-[#222329] shadow-[0_8px_22px_rgba(0,0,0,0.2)]" : "border-dashed border-[#565762] bg-[#202126]"} hover:border-[#9b83ff] hover:bg-[#292a31]`}>
      {portrait
        ? <button type="button" onClick={(event) => { event.preventDefault(); onPreview(0) }} title="预览形象图" className="size-9 shrink-0 overflow-hidden rounded-md"><img src={portrait.preview} alt={portraitLabel} className="h-full w-full object-cover transition duration-200 group-hover:scale-105" /></button>
        : <span className="grid size-9 shrink-0 place-items-center rounded-md bg-[#2b2c33]"><ImagePlus className="text-[#a18cff]" size={16} /></span>}
      <span className="min-w-0 flex-1">
        <span title={portraitLabel} className="block truncate text-[11px] leading-4 text-[#d3d3da]">{portraitLabel}</span>
        <span className="block truncate text-[10px] leading-[14px] text-[#777780]">{portrait ? "点击放大预览，重新上传可替换" : "正面高清人物图，点击上传"}</span>
      </span>
      {portrait && <button type="button" onClick={(event) => { event.preventDefault(); onRemovePortrait(0) }} title="移除形象图" className="absolute right-1 top-1 grid size-5 place-items-center rounded-full border border-white/10 bg-black/65 text-white opacity-0 transition group-hover:opacity-100"><X size={11} /></button>}
      <input type="file" className="hidden" accept="image/*" onChange={(event) => onReplacePortrait(0, event.target.files)} />
    </label>
    <label className={`studio-reference-slot group relative flex min-h-0 min-w-0 cursor-pointer items-center gap-2 overflow-hidden rounded-xl border px-2 transition ${audio ? "border-[#7655ff]/80 bg-[#222329] shadow-[0_8px_22px_rgba(0,0,0,0.2)]" : "border-dashed border-[#565762] bg-[#202126]"} hover:border-[#9b83ff] hover:bg-[#292a31]`}>
      <span className={`grid size-9 shrink-0 place-items-center rounded-md ${audio ? "bg-[#7047ff]/20" : "bg-[#2b2c33]"}`}><Mic className={audio ? "text-[#b5a4ff]" : "text-[#8f78ff]"} size={16} /></span>
      <span className="min-w-0 flex-1">
        <span title={audio ? audio.file.name : audioLabel} className="block truncate text-[11px] leading-4 text-[#d3d3da]">{audio ? audio.file.name : audioLabel}</span>
        <span className="block truncate text-[10px] leading-[14px] text-[#777780]">{audio ? `${audio.duration > 0 ? `${audio.duration.toFixed(1)} 秒 · ` : ""}数字人口型将与此音频同步` : "WAV / MP3，5 秒以内，点击上传"}</span>
      </span>
      {audio && <button type="button" onClick={(event) => { event.preventDefault(); onRemoveAudio() }} title="移除口播音频" className="absolute right-1 top-1 grid size-5 place-items-center rounded-full border border-white/10 bg-black/65 text-white opacity-0 transition group-hover:opacity-100"><X size={11} /></button>}
      <input type="file" className="hidden" accept="audio/*,.wav,.mp3,.m4a,.aac,.ogg,.flac" onChange={(event) => onPickAudio(event.target.files)} />
    </label>
  </div>
}

export function ReferencePanel({
  workflow, references, onAppend, onReplaceKeyframe, onRemove, onMove, onPreview, fileInputRef,
}: {
  workflow?: ReferencePanelWorkflow; references: ReferenceAsset[]; onAppend: (files: FileList | File[] | null) => void
  onReplaceKeyframe: (index: number, files: FileList | null) => void; onRemove: (index: number) => void
  onMove: (index: number, direction: -1 | 1) => void; onPreview: (index: number) => void
  fileInputRef: RefObject<HTMLInputElement | null>
}) {
  const [stackExpanded, setStackExpanded] = useState(false)
  const [hoveredReference, setHoveredReference] = useState<number | null>(null)

  if (!workflow || workflow.reference_mode === "none") return <div className="flex min-h-[106px] flex-col items-center justify-center rounded-xl border border-dashed border-white/[0.12] bg-[#202126]/65 px-3 text-center text-xs leading-5 text-[#85858d]"><FileVideo className="mb-2 text-[#8f78ff]" size={20} /><span>文生视频无需参考图</span></div>
  if (workflow.reference_mode === "keyframes") return <div className="studio-reference-panel studio-reference-stack grid gap-2">
    {[0, 1].map((index) => {
      const asset = references[index]
      const disabled = index === 1 && !references[0]
      return <label key={index} className={`studio-reference-slot group relative flex min-h-0 min-w-0 cursor-pointer items-center gap-2 overflow-hidden rounded-xl border px-2 transition ${asset ? "border-[#7655ff]/80 bg-[#222329] shadow-[0_8px_22px_rgba(0,0,0,0.2)]" : "border-dashed border-[#565762] bg-[#202126]"} ${disabled ? "cursor-not-allowed opacity-35" : "hover:border-[#9b83ff] hover:bg-[#292a31]"}`}>
        {asset ? <><img src={asset.preview} alt={workflow.reference_labels[index]} className="absolute inset-0 h-full w-full object-cover transition duration-200 group-hover:scale-105" /><button type="button" onClick={(event) => { event.preventDefault(); onPreview(index) }} className="studio-reference-preview-button absolute inset-0 grid place-items-center bg-black/0 text-white opacity-0 transition group-hover:bg-black/25 group-hover:opacity-100"><Maximize2 size={18} /></button></> : <div className="flex min-w-0 items-center gap-2"><ImagePlus className="shrink-0 text-[#a18cff]" size={17} /><span className="min-w-0 flex-1"><span title={workflow.reference_labels[index]} className="block truncate text-[11px] leading-4 text-[#d3d3da]">{workflow.reference_labels[index]}</span>{index === 0 && <span className="block truncate text-[10px] leading-[14px] text-[#777780]">点击上传</span>}</span></div>}
        {asset && <button type="button" onClick={(event) => { event.preventDefault(); onRemove(index) }} title="移除参考图" className="studio-reference-remove-button absolute right-1.5 top-1.5 grid size-6 place-items-center rounded-full border border-white/10 bg-black/65 text-white opacity-0 transition group-hover:opacity-100"><X size={12} /></button>}
        <input type="file" className="hidden" accept="image/*" disabled={disabled} onChange={(event) => onReplaceKeyframe(index, event.target.files)} />
      </label>
    })}
  </div>
  const stackOffset = (index: number) => stackExpanded ? index * 65 : index * 4
  const stackWidth = stackExpanded ? Math.max(71, references.length * 65 + 71) : 112

  return <div
    className="studio-reference-panel relative flex min-h-[106px] items-center overflow-visible"
    onMouseEnter={() => setStackExpanded(true)}
    onMouseLeave={() => { setStackExpanded(false); setHoveredReference(null) }}
    onFocus={() => setStackExpanded(true)}
    onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) { setStackExpanded(false); setHoveredReference(null) } }}
  >
    <div className="relative h-[92px] overflow-visible transition-[width] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]" style={{ width: stackWidth }}>
      {references.map((asset, index) => {
        const hovered = hoveredReference === index
        const rotation = [-5, 7, -4, 6, -7, 4][index % 6]
        return <div
          key={asset.id}
          role="button"
          tabIndex={0}
          aria-label={`预览第 ${index + 1} 张参考图`}
          className={`group absolute left-0 top-2 h-[78px] w-[61px] cursor-pointer rounded-md border border-[#8b72ff]/80 bg-[#222226] shadow-[0_6px_14px_rgba(0,0,0,0.28)] outline-none transition-[transform,box-shadow] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] hover:z-30 hover:shadow-[0_16px_28px_rgba(0,0,0,0.38)] focus-visible:z-30 focus-visible:ring-2 focus-visible:ring-[#a584ff] ${hovered ? "z-30 shadow-[0_16px_28px_rgba(0,0,0,0.38)]" : ""}`}
          style={{ transform: `translate3d(${stackOffset(index)}px, ${hovered ? -8 : index % 2 ? -1 : 1}px, 0) rotate(${rotation}deg) scale(${hovered ? 1.08 : 1})`, zIndex: stackExpanded ? index + 1 : index + 2 }}
          onClick={() => onPreview(index)}
          onMouseEnter={() => setHoveredReference(index)}
          onMouseLeave={() => setHoveredReference((current) => current === index ? null : current)}
          onFocus={() => setHoveredReference(index)}
          onBlur={() => setHoveredReference((current) => current === index ? null : current)}
          onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onPreview(index) } }}
        >
          <img src={asset.preview} alt={`参考图 ${index + 1}`} className="h-full w-full rounded-[5px] object-cover" />
          <span aria-hidden className="studio-reference-index absolute left-1 top-1 flex min-w-[18px] items-center justify-center rounded-full border border-white/30 bg-[#17171f]/80 px-1 text-[10px] font-semibold leading-4 text-white">{index + 1}</span>
          <div className={`absolute inset-x-0 bottom-1 flex justify-center gap-0.5 transition ${stackExpanded ? "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100" : "pointer-events-none opacity-0"}`}>
            <button type="button" disabled={index === 0} onClick={(event) => { event.stopPropagation(); onMove(index, -1) }} title="向前移动" className="studio-reference-move-button grid size-5 place-items-center rounded-md bg-black/75 text-white hover:bg-black disabled:opacity-30"><MoveLeft size={11} /></button>
            <button type="button" disabled={index === references.length - 1} onClick={(event) => { event.stopPropagation(); onMove(index, 1) }} title="向后移动" className="studio-reference-move-button grid size-5 place-items-center rounded-md bg-black/75 text-white hover:bg-black disabled:opacity-30"><MoveRight size={11} /></button>
          </div>
          <button type="button" aria-label={`移除第 ${index + 1} 张参考图`} onClick={(event) => { event.stopPropagation(); onRemove(index) }} title="移除参考图" className={`studio-reference-remove-button absolute -right-2 -top-2 grid size-6 place-items-center rounded-full border border-white/10 bg-[#414148] text-white shadow-lg transition hover:bg-[#5b5b64] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#a584ff] ${stackExpanded ? "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100" : "pointer-events-none opacity-0"}`}><X size={13} /></button>
        </div>
      })}
      {references.length < workflow.max_references && <label
        title="添加参考图"
        className="studio-reference-add group absolute left-0 top-2 flex h-[68px] w-[52px] cursor-pointer items-center justify-center rounded-md transition-[transform,background-color] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] hover:-translate-y-1"
        style={{ transform: `translate3d(${stackExpanded ? references.length * 65 : references.length ? Math.max(44, references.length * 4 + 38) : 0}px, 0, 0) rotate(-8deg)`, zIndex: stackExpanded ? references.length + 2 : 20 }}
      >
        <Plus className="transition group-hover:scale-110" size={23} /><span className="sr-only">添加参考图</span>
        <input ref={fileInputRef} type="file" accept="image/*" multiple className="hidden" onChange={(event) => onAppend(event.target.files)} />
      </label>}
    </div>
  </div>
}
