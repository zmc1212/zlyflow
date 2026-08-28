import { Button, Drawer, Input, InputNumber, Tag, Tooltip, message } from "antd"
import ShotCameraFields from "./ShotCameraFields"
import {
  Camera, Check, CheckCircle2, CircleStop, Clapperboard, Copy, Film, History, ImagePlus, Link,
  RefreshCw, Sparkles, Star, Trash2, Video, Volume2, X,
} from "lucide-react"
import React, { useRef, useState } from "react"
import { fileToDataUrl } from "../director-submit"
import { H3_MAX_DURATION_SEC, H3_MIN_DURATION_SEC, DirectorRenderPass, directorRenderPassLabel, snapH3DurationSec } from "../prompt-compiler"
import {
  DirectorShot, ShotTake, SubjectSlot,
} from "../types"

interface ShotInspectorDrawerProps {
  open: boolean
  shot: DirectorShot | null
  subjectSlots: SubjectSlot[]
  onClose: () => void
  onUpdateShot: (updated: DirectorShot) => void
  onRenderShot: (shot: DirectorShot, renderPass?: DirectorRenderPass) => void
  onCancelShot?: (shot: DirectorShot) => void
  onOpenFrameScrubber?: (shot: DirectorShot) => void
}

export default function ShotInspectorDrawer({
  open,
  shot,
  subjectSlots,
  onClose,
  onUpdateShot,
  onRenderShot,
  onCancelShot,
  onOpenFrameScrubber,
}: ShotInspectorDrawerProps) {
  if (!shot) return null

  const firstFrameInputRef = useRef<HTMLInputElement>(null)
  const endFrameInputRef = useRef<HTMLInputElement>(null)

  const takes = shot.takes || []
  const activeTake = takes[shot.activeTakeIndex] || null

  const handleFirstFrameUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    void fileToDataUrl(file).then((previewUrl) => {
      onUpdateShot({
        ...shot,
        firstFrameFile: file,
        firstFrameUrl: previewUrl,
        usePreviousEndFrame: false,
      })
    }).catch((error: Error) => message.error(error.message))
  }

  const handleEndFrameUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    void fileToDataUrl(file).then((previewUrl) => {
      onUpdateShot({
        ...shot,
        endFrameFile: file,
        endFrameUrl: previewUrl,
      })
    }).catch((error: Error) => message.error(error.message))
  }

  const handleInsertTag = (tag: string) => {
    const nextPrompt = shot.prompt ? `${shot.prompt} ${tag}` : tag
    onUpdateShot({
      ...shot,
      prompt: nextPrompt,
      referencedSubjectIds: Array.from(new Set([...(shot.referencedSubjectIds || []), tag])),
    })
    message.success(`已插入 ${tag}`)
  }

  const handleSelectTake = (index: number) => {
    const targetTake = takes[index]
    if (!targetTake) return
    onUpdateShot({
      ...shot,
      activeTakeIndex: index,
      outputVideoUrl: targetTake.videoUrl,
      outputPath: targetTake.outputPath,
      status: targetTake.status,
    })
    message.success(`已将 Take ${targetTake.takeNumber} 设为定版镜头`)
  }

  const isRendering = shot.status === "queued" || shot.status === "running" || shot.status === "interrupted"

  return (
    <Drawer
      open={open}
      title={
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Film size={18} className="text-[#7047f6]" />
            <span className="font-bold text-[#111827]">分镜检视器 — {shot.title}</span>
          </div>
          <Tag color="purple">Shot {shot.shotNumber}</Tag>
        </div>
      }
      onClose={onClose}
      width={460}
      className="studio-shot-inspector-drawer"
    >
      <div className="flex flex-col gap-5 pb-8">
        {/* 基础属性：标题与时长 */}
        <section className="bg-[#f8f9fa] p-3.5 rounded-xl border border-black/[0.06] flex flex-col gap-3">
          <div className="flex items-center gap-3">
            <div className="flex-1">
              <label className="text-[11px] font-semibold text-[#4b5563] mb-1 block">分镜名称</label>
              <Input
                value={shot.title}
                onChange={(e) => onUpdateShot({ ...shot, title: e.target.value })}
                className="text-xs"
              />
            </div>
            <div className="w-24">
              <label className="text-[11px] font-semibold text-[#4b5563] mb-1 block">时长 (秒)</label>
              <InputNumber
                min={H3_MIN_DURATION_SEC}
                max={H3_MAX_DURATION_SEC}
                value={shot.durationSec || H3_MIN_DURATION_SEC}
                onChange={(val) => onUpdateShot({ ...shot, durationSec: snapH3DurationSec(val ?? H3_MIN_DURATION_SEC) })}
                className="w-full text-xs"
              />
            </div>
          </div>
        </section>

        {/* 多 Take 试拍版本列表 */}
        <section className="bg-white p-3.5 rounded-xl border border-black/[0.08] shadow-sm">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-1.5 text-xs font-bold text-[#111827]">
              <History size={15} className="text-[#7047f6]" />
              <span>多版本试拍库 ({takes.length} Takes)</span>
            </div>
            {isRendering && onCancelShot ? (
              <Button
                danger
                size="small"
                onClick={() => onCancelShot(shot)}
                icon={<CircleStop size={13} />}
                className="text-xs font-medium"
              >
                停止生成
              </Button>
            ) : (
              <div className="flex items-center gap-1.5">
                <Button size="small" disabled={isRendering} onClick={() => onRenderShot(shot, "preview")} className="text-xs font-medium">
                  预览
                </Button>
                <Button
                  type="primary"
                  size="small"
                  disabled={isRendering}
                  onClick={() => onRenderShot(shot, "final")}
                  icon={<RefreshCw size={13} />}
                  className="bg-[#7047f6] text-xs font-medium"
                >
                  成片
                </Button>
              </div>
            )}
          </div>

          {takes.length === 0 ? (
            <div className="py-4 text-center text-xs text-[#9ca3af] bg-[#f9fafb] rounded-lg border border-dashed border-black/[0.08]">
              暂无已生成的 Take，可先预览再成片
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {takes.map((take, idx) => {
                const isActive = idx === shot.activeTakeIndex
                return (
                  <div
                    key={take.id}
                    className={`flex items-center justify-between p-2 rounded-lg border transition ${
                      isActive
                        ? "border-[#7047f6] bg-[#7047f6]/[0.04] ring-1 ring-[#7047f6]"
                        : "border-black/[0.06] bg-[#f9fafb] hover:bg-white"
                    }`}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <div className="relative size-10 rounded overflow-hidden bg-black/10 shrink-0">
                        {take.videoUrl ? (
                          <video src={take.videoUrl} className="w-full h-full object-cover" />
                        ) : (
                          <div className="w-full h-full grid place-items-center text-[10px] text-[#9ca3af]">无画面</div>
                        )}
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs font-bold text-[#111827]">Take {take.takeNumber}</span>
                          {take.renderPass ? <Tag className="!m-0 text-[10px]">{directorRenderPassLabel(take.renderPass)}</Tag> : null}
                          {isActive && <Tag color="purple" className="!m-0 text-[10px]">定版 Active</Tag>}
                        </div>
                        <span className="text-[10px] text-[#9ca3af] block truncate">
                          {take.createdAt ? new Date(take.createdAt).toLocaleTimeString() : ""}
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center gap-1.5">
                      {!isActive && (
                        <Button
                          size="small"
                          onClick={() => handleSelectTake(idx)}
                          icon={<Star size={12} />}
                          className="text-xs"
                        >
                          设为定版
                        </Button>
                      )}
                      {take.videoUrl && onOpenFrameScrubber && (
                        <Tooltip title="截取此 Take 的画面">
                          <Button
                            size="small"
                            onClick={() => onOpenFrameScrubber(shot)}
                            icon={<Camera size={12} />}
                          />
                        </Tooltip>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </section>

        {/* 提示词与主体标签快速插入 */}
        <section className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <label className="text-xs font-bold text-[#111827]">分镜画面描述 (Visual Prompt)</label>
            <span className="text-[11px] text-[#9ca3af]">键入主体标签保持角色一致</span>
          </div>

          {/* 主体快捷插入标签栏 */}
          <div className="flex flex-wrap gap-1.5">
            {subjectSlots
              .filter((s) => s.previewUrl || s.file)
              .map((slot) => (
                <button
                  key={slot.id}
                  type="button"
                  onClick={() => handleInsertTag(slot.id)}
                  className="px-2 py-0.5 text-xs font-semibold text-[#7047f6] bg-[#7047f6]/10 rounded-full hover:bg-[#7047f6]/20 transition flex items-center gap-1"
                >
                  <span>{slot.id}</span>
                  <span className="text-[10px] font-normal text-[#6b7280]">({slot.kind})</span>
                </button>
              ))}
          </div>

          <Input.TextArea
            rows={4}
            value={shot.prompt}
            onChange={(e) => onUpdateShot({ ...shot, prompt: e.target.value })}
            placeholder="描述此分镜的主体动作、场景细节与光影..."
            className="text-xs font-mono"
          />
        </section>

        {/* 台词与音效 */}
        <section className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-[11px] font-semibold text-[#4b5563] mb-1 block">角色台词对白 (Dialogue)</label>
            <Input.TextArea
              rows={2}
              value={shot.dialogue}
              onChange={(e) => onUpdateShot({ ...shot, dialogue: e.target.value })}
              placeholder="如: 李白轻笑一声说..."
              className="text-xs"
            />
          </div>
          <div>
            <label className="text-[11px] font-semibold text-[#4b5563] mb-1 block">分镜音效 (Soundscape)</label>
            <Input.TextArea
              rows={2}
              value={shot.soundscape}
              onChange={(e) => onUpdateShot({ ...shot, soundscape: e.target.value })}
              placeholder="如: 长剑出鞘的清脆金属声..."
              className="text-xs"
            />
          </div>
        </section>

        {/* 电影机位运镜控制器 */}
        <section className="bg-[#f8f9fa] p-3.5 rounded-xl border border-black/[0.06] flex flex-col gap-3">
          <div className="flex items-center gap-1.5 text-xs font-bold text-[#111827]">
            <Camera size={15} className="text-[#7047f6]" />
            <span>机位与运镜</span>
          </div>

          <ShotCameraFields
            camera={shot.camera}
            onChange={(camera) => onUpdateShot({ ...shot, camera })}
          />
        </section>

        {/* 首尾帧锚点 */}
        <section className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-[11px] font-semibold text-[#4b5563] mb-1 block">首帧锚点 (First Frame)</label>
            <input
              type="file"
              accept="image/*"
              ref={firstFrameInputRef}
              onChange={handleFirstFrameUpload}
              className="hidden"
            />
            <div
              onClick={() => firstFrameInputRef.current?.click()}
              className="h-24 rounded-lg border border-dashed border-black/[0.15] bg-[#f9fafb] flex flex-col items-center justify-center cursor-pointer hover:bg-white transition relative overflow-hidden"
            >
              {shot.firstFrameUrl ? (
                <>
                  <img src={shot.firstFrameUrl} alt="首帧" className="w-full h-full object-cover" />
                  <span className="absolute bottom-1 right-1 px-1 py-0.5 text-[9px] bg-black/65 text-white rounded">替换</span>
                </>
              ) : (
                <>
                  <ImagePlus size={16} className="text-[#9ca3af] mb-1" />
                  <span className="text-[10px] text-[#6b7280]">点击上传首帧</span>
                </>
              )}
            </div>
          </div>

          <div>
            <label className="text-[11px] font-semibold text-[#4b5563] mb-1 block">尾帧锚点 (End Frame)</label>
            <input
              type="file"
              accept="image/*"
              ref={endFrameInputRef}
              onChange={handleEndFrameUpload}
              className="hidden"
            />
            <div
              onClick={() => endFrameInputRef.current?.click()}
              className="h-24 rounded-lg border border-dashed border-black/[0.15] bg-[#f9fafb] flex flex-col items-center justify-center cursor-pointer hover:bg-white transition relative overflow-hidden"
            >
              {shot.endFrameUrl ? (
                <>
                  <img src={shot.endFrameUrl} alt="尾帧" className="w-full h-full object-cover" />
                  <span className="absolute bottom-1 right-1 px-1 py-0.5 text-[9px] bg-black/65 text-white rounded">替换</span>
                </>
              ) : (
                <>
                  <ImagePlus size={16} className="text-[#9ca3af] mb-1" />
                  <span className="text-[10px] text-[#6b7280]">可选尾帧</span>
                </>
              )}
            </div>
          </div>
        </section>
      </div>
    </Drawer>
  )
}
