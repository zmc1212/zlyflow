import type { TextAreaRef } from "antd/es/input/TextArea"
import { Dropdown, Input, Progress, Tag, Tooltip } from "antd"
import {
  ArrowDown, ArrowUp, Camera, CircleStop, Copy, Film, ImagePlus, Link, LoaderCircle,
  MoreHorizontal, RefreshCw, Sliders, Sparkles, Trash2, X,
} from "lucide-react"
import React, { useRef, useState } from "react"
import { fileToDataUrl, shotHasActiveRender } from "../director-submit"
import {
  CAMERA_ANGLE_LABELS, CAMERA_LIGHTING_LABELS, CAMERA_MOVEMENT_LABELS, CAMERA_SCALE_LABELS,
  DirectorShot, SubjectSlot,
} from "../types"
import CameraControlModal from "./CameraControlModal"

interface ShotCardProps {
  shot: DirectorShot
  totalShots: number
  subjectSlots?: SubjectSlot[]
  castList?: any[]
  onUpdate: (updatedShot: DirectorShot) => void
  onDelete: () => void
  onMoveUp: () => void
  onMoveDown: () => void
  onDuplicate: () => void
  onRender: (shot: DirectorShot) => void
  onCancel?: (shot: DirectorShot) => void
  onChainToNext?: (sourceShot: DirectorShot) => void
  onOpenInspector?: (shot: DirectorShot) => void
  onOpenFrameScrubber?: (shot: DirectorShot) => void
}

export default function ShotCard({
  shot,
  totalShots,
  subjectSlots = [],
  onUpdate,
  onDelete,
  onMoveUp,
  onMoveDown,
  onDuplicate,
  onRender,
  onCancel,
  onChainToNext,
  onOpenInspector,
  onOpenFrameScrubber,
}: ShotCardProps) {
  const [cameraModalOpen, setCameraModalOpen] = useState(false)
  const [isEditingTitle, setIsEditingTitle] = useState(false)
  const promptTextareaRef = useRef<TextAreaRef>(null)
  const firstFrameInputRef = useRef<HTMLInputElement>(null)

  const handleFirstFrameUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    void fileToDataUrl(file).then((previewUrl) => {
      onUpdate({
        ...shot,
        firstFrameFile: file,
        firstFrameUrl: previewUrl,
        usePreviousEndFrame: false,
      })
    }).catch((error: Error) => {
      console.error(error)
    })
  }

  const insertTag = (tag: string) => {
    const textarea = promptTextareaRef.current?.resizableTextArea?.textArea
    if (!textarea) {
      onUpdate({ ...shot, prompt: shot.prompt ? `${shot.prompt} ${tag}` : tag })
      return
    }
    const start = textarea.selectionStart || 0
    const end = textarea.selectionEnd || 0
    const prev = shot.prompt
    const nextPrompt = prev.substring(0, start) + tag + prev.substring(end)
    onUpdate({ ...shot, prompt: nextPrompt })
    setTimeout(() => {
      textarea.focus()
      textarea.setSelectionRange(start + tag.length, start + tag.length)
    }, 50)
  }

  const isRendering = shotHasActiveRender(shot)
  const isDone = shot.status === "succeeded" && Boolean(shot.outputVideoUrl)

  return (
    <div
      className={`group relative flex flex-col rounded-2xl border bg-white p-4 shadow-sm transition-all duration-200 ${
        isRendering
          ? "border-[#7047f6] ring-2 ring-[#7047f6]/10"
          : isDone
          ? "border-emerald-500/30 hover:border-emerald-500/60"
          : "border-black/[0.08] hover:border-black/20"
      }`}
    >
      {/* 头部：镜头序号、标题与更多操作 */}
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="grid size-6 place-items-center rounded-md bg-[#7047f6] text-xs font-bold text-white shadow-xs">
            {shot.shotNumber}
          </span>
          {isEditingTitle ? (
            <Input
              size="small"
              value={shot.title}
              autoFocus
              onBlur={() => setIsEditingTitle(false)}
              onPressEnter={() => setIsEditingTitle(false)}
              onChange={(e) => onUpdate({ ...shot, title: e.target.value })}
              className="h-7 text-xs font-semibold"
            />
          ) : (
            <span
              onClick={() => setIsEditingTitle(true)}
              className="cursor-pointer text-xs font-bold text-[#111827] hover:text-[#7047f6] transition"
              title="点击修改分镜名称"
            >
              {shot.title}
            </span>
          )}

          {/* Take 版本角标 */}
          {shot.takes && shot.takes.length > 0 && (
            <Tag color="purple" className="!m-0 text-[10px] cursor-pointer" onClick={() => onOpenInspector?.(shot)}>
              Take {shot.activeTakeIndex + 1}/{shot.takes.length}
            </Tag>
          )}
        </div>

        <div className="flex items-center gap-1">
          {onOpenInspector && (
            <Tooltip title="打开详细检视器与机位设置">
              <button
                type="button"
                onClick={() => onOpenInspector(shot)}
                className="grid size-7 place-items-center rounded-md text-[#6b7280] hover:bg-[#7047f6]/10 hover:text-[#7047f6]"
              >
                <Sliders size={14} />
              </button>
            </Tooltip>
          )}

          <Dropdown
            trigger={["click"]}
            menu={{
              items: [
                {
                  key: "up",
                  label: "上移镜头",
                  icon: <ArrowUp size={13} />,
                  disabled: shot.shotNumber === 1,
                  onClick: onMoveUp,
                },
                {
                  key: "down",
                  label: "下移镜头",
                  icon: <ArrowDown size={13} />,
                  disabled: shot.shotNumber === totalShots,
                  onClick: onMoveDown,
                },
                {
                  key: "dup",
                  label: "复制分镜",
                  icon: <Copy size={13} />,
                  onClick: onDuplicate,
                },
                {
                  key: "scrub",
                  label: "定格截取当前帧",
                  icon: <Camera size={13} />,
                  disabled: !shot.outputVideoUrl,
                  onClick: () => onOpenFrameScrubber?.(shot),
                },
                {
                  key: "del",
                  label: "删除分镜",
                  icon: <Trash2 size={13} />,
                  danger: true,
                  disabled: totalShots <= 1,
                  onClick: onDelete,
                },
              ],
            }}
          >
            <button
              type="button"
              className="grid size-7 place-items-center rounded-md text-[#6b7280] hover:bg-black/[0.05] hover:text-[#111827]"
            >
              <MoreHorizontal size={16} />
            </button>
          </Dropdown>
        </div>
      </div>

      {/* 机位与摄影标签栏 */}
      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        <Tag
          color="blue"
          className="cursor-pointer text-[11px] font-medium"
          onClick={() => setCameraModalOpen(true)}
        >
          {CAMERA_SCALE_LABELS[shot.camera.scale]?.label.split(" ")[0]}
        </Tag>
        <Tag
          color="purple"
          className="cursor-pointer text-[11px] font-medium"
          onClick={() => setCameraModalOpen(true)}
        >
          {CAMERA_MOVEMENT_LABELS[shot.camera.movement]?.label.split(" ")[0]}
        </Tag>
        <Tag
          className="cursor-pointer text-[11px]"
          onClick={() => setCameraModalOpen(true)}
        >
          {CAMERA_ANGLE_LABELS[shot.camera.angle]?.label}
        </Tag>
        <Tag
          className="cursor-pointer text-[11px]"
          onClick={() => setCameraModalOpen(true)}
        >
          {CAMERA_LIGHTING_LABELS[shot.camera.lighting]?.label}
        </Tag>
      </div>

      {/* 媒体视窗（未生成 / 生成中 / 播放器） */}
      <div className="relative mb-3 aspect-video w-full overflow-hidden rounded-xl border border-black/[0.06] bg-[#f8f9fa]">
        {isDone ? (
          <div className="relative h-full w-full group">
            <video
              src={shot.outputVideoUrl}
              className="h-full w-full object-cover"
              controls
              playsInline
              preload="metadata"
            />
            {onOpenFrameScrubber && (
              <button
                type="button"
                onClick={() => onOpenFrameScrubber(shot)}
                className="absolute top-2 right-2 flex items-center gap-1 px-2 py-1 bg-black/60 hover:bg-black/85 text-white text-[10px] rounded-md backdrop-blur transition opacity-0 group-hover:opacity-100"
              >
                <Camera size={11} />
                <span>截取帧</span>
              </button>
            )}
          </div>
        ) : isRendering ? (
          <div className="flex h-full w-full flex-col items-center justify-center p-4 text-center">
            <LoaderCircle size={28} className="animate-spin text-[#7047f6]" />
            <p className="mt-2 text-xs font-semibold text-[#111827]">
              {shot.status === "queued" ? "等待队列中..." : `生成中 ${Math.round(shot.progress)}%`}
            </p>
            <p className="mt-0.5 text-[11px] text-[#6b7280]">
              MiniMax H3 正在采样渲染...
            </p>
          </div>
        ) : (
          <div className="relative flex h-full w-full flex-col items-center justify-center p-3 text-center">
            {shot.firstFrameUrl ? (
              <div className="relative h-full w-full">
                <img
                  src={shot.firstFrameUrl}
                  alt="首帧参考"
                  className="h-full w-full object-cover"
                />
                <button
                  type="button"
                  onClick={() => onUpdate({ ...shot, firstFrameUrl: undefined, firstFrameFile: undefined })}
                  className="absolute right-1 top-1 grid size-6 place-items-center rounded-full bg-black/60 text-white hover:bg-black/80"
                  title="移除首帧"
                >
                  <X size={12} />
                </button>
                <span className="absolute bottom-1 left-1 rounded bg-black/60 px-1.5 py-0.5 text-[10px] text-white">
                  首帧参考
                </span>
              </div>
            ) : (
              <div className="flex flex-col items-center text-[#9ca3af]">
                <Film size={28} className="mb-1.5 text-[#cbd5e1]" />
                <span className="text-xs">尚未生成分镜视频</span>
                <button
                  type="button"
                  onClick={() => firstFrameInputRef.current?.click()}
                  className="mt-2 flex items-center gap-1 rounded-md border border-black/[0.08] bg-white px-2 py-1 text-[11px] font-medium text-[#4b5563] shadow-xs hover:border-[#7047f6] hover:text-[#7047f6]"
                >
                  <ImagePlus size={13} />
                  <span>添加首帧 (I2V)</span>
                </button>
              </div>
            )}
            <input
              ref={firstFrameInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={handleFirstFrameUpload}
            />
          </div>
        )}
      </div>

      {/* 镜头接龙按钮（续接至下一镜首帧） */}
      {isDone && onChainToNext && shot.shotNumber < totalShots ? (
        <button
          type="button"
          onClick={() => onChainToNext(shot)}
          className="mb-3 flex items-center justify-center gap-1.5 rounded-lg border border-emerald-500/20 bg-emerald-50/50 py-1.5 text-xs font-medium text-emerald-700 transition hover:bg-emerald-100/60"
        >
          <Link size={13} />
          <span>🔗 续接此镜头尾帧到 Shot {shot.shotNumber + 1} 首帧</span>
        </button>
      ) : null}

      {/* 全局主体参考标签快速插入 */}
      {subjectSlots.filter((s) => s.previewUrl || s.file).length > 0 ? (
        <div className="mb-2 flex flex-wrap items-center gap-1">
          <span className="text-[11px] text-[#6b7280]">插入主体:</span>
          {subjectSlots
            .filter((s) => s.previewUrl || s.file)
            .map((slot) => (
              <button
                key={slot.id}
                type="button"
                onClick={() => insertTag(slot.id)}
                className="flex items-center gap-1 rounded border border-black/[0.08] bg-white px-1.5 py-0.5 text-[11px] text-[#4b5563] hover:border-[#7047f6] hover:bg-[#7047f6]/5 hover:text-[#7047f6]"
                title={`点击插入 ${slot.id} (${slot.kind})`}
              >
                <span className="font-semibold text-[#7047f6]">{slot.id}</span>
                <span>{slot.name}</span>
              </button>
            ))}
        </div>
      ) : null}

      {/* 提示词输入区 */}
      <div className="mb-3 flex-1">
        <Input.TextArea
          ref={promptTextareaRef}
          rows={3}
          value={shot.prompt}
          onChange={(e) => onUpdate({ ...shot, prompt: e.target.value })}
          placeholder="输入该分镜的画面主体、动作演变与环境细节..."
          className="rounded-lg text-xs"
        />
        {shot.dialogue ? (
          <p className="mt-1 text-[11px] text-[#4b5563] truncate">
            <span className="font-semibold text-[#7047f6]">台词:</span> {shot.dialogue}
          </p>
        ) : null}
      </div>

      {/* 底部操作工具栏 */}
      <div className="flex items-center justify-between border-t border-black/[0.06] pt-3">
        <button
          type="button"
          onClick={() => setCameraModalOpen(true)}
          className="flex items-center gap-1 rounded-lg border border-black/[0.08] bg-[#f8f9fa] px-2.5 py-1.5 text-xs font-medium text-[#374151] transition hover:border-[#7047f6] hover:text-[#7047f6]"
        >
          <Camera size={14} />
          <span>🎥 运镜调度</span>
        </button>

        <button
          type="button"
          disabled={!isRendering && !shot.prompt.trim()}
          onClick={() => (isRendering && onCancel ? onCancel(shot) : onRender(shot))}
          className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-white transition disabled:cursor-not-allowed disabled:opacity-40 ${
            isRendering
              ? "bg-red-600 hover:bg-red-700"
              : isDone
                ? "bg-amber-600 hover:bg-amber-700"
                : "bg-[#7047f6] hover:bg-[#7c58f8]"
          }`}
        >
          {isRendering ? (
            <CircleStop size={14} />
          ) : isDone ? (
            <RefreshCw size={13} />
          ) : (
            <Sparkles size={13} />
          )}
          <span>{isRendering ? "停止生成" : isDone ? "重拍 (New Take)" : "生成此镜头"}</span>
        </button>
      </div>

      {/* 摄影机控制弹窗 */}
      <CameraControlModal
        open={cameraModalOpen}
        camera={shot.camera}
        shotTitle={shot.title}
        onSave={(nextCamera) => {
          onUpdate({ ...shot, camera: nextCamera })
          setCameraModalOpen(false)
        }}
        onCancel={() => setCameraModalOpen(false)}
      />
    </div>
  )
}
