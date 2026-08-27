import { Button, Dropdown, Input, Select, Tag, Tooltip, message } from "antd"
import {
  Bot, Check, Eye, ImagePlus, LoaderCircle, Sparkles, Trash2, UserCheck, X,
} from "lucide-react"
import React, { useRef } from "react"
import { fileToDataUrl } from "../director-submit"
import {
  SUBJECT_KIND_LABELS, SUBJECT_RETENTION_LABELS, SubjectSlot, SubjectSlotKind, SubjectSlotRetention,
} from "../types"

interface TimelineTrackSubjectsProps {
  subjectSlots: SubjectSlot[]
  activeSlotId?: string
  onUpdateSlot: (updatedSlot: SubjectSlot) => void
  onInsertSlotTagToShot?: (slotId: string) => void
  onAnalyzeSlot?: (slot: SubjectSlot) => void
  analyzeDisabledReason?: string
}

export default function TimelineTrackSubjects({
  subjectSlots,
  activeSlotId,
  onUpdateSlot,
  onInsertSlotTagToShot,
  onAnalyzeSlot,
  analyzeDisabledReason,
}: TimelineTrackSubjectsProps) {
  const fileInputRefs = useRef<Record<string, HTMLInputElement | null>>({})

  const handleFileUpload = (slot: SubjectSlot, e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    void fileToDataUrl(file).then((previewUrl) => {
      onUpdateSlot({
        ...slot,
        file,
        previewUrl,
      })
      message.success(`已上传 ${slot.id} 主体参考图`)
    }).catch((error: Error) => message.error(error.message))
  }

  const handleClearSlot = (slot: SubjectSlot) => {
    onUpdateSlot({
      ...slot,
      file: undefined,
      previewUrl: undefined,
      description: "",
    })
  }

  return (
    <section className="border-b border-black/[0.06] bg-white p-3">
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1 text-xs font-semibold text-[#111827]">
            <UserCheck size={14} className="text-[#7047f6]" />
            主体资产轨 (@ref1 ~ @ref9)
          </span>
          <span className="text-[11px] text-[#6b7280]">
            已配置 {subjectSlots.filter((s) => s.previewUrl || s.file).length} / 9 个参考槽位
          </span>
        </div>
        <span className="text-[11px] text-[#9ca3af]">
          点击主体槽位标签可直接将 <code className="text-[#7047f6] bg-[#7047f6]/10 px-1 py-0.5 rounded">@ref1</code> 插入分镜提示词
        </span>
      </div>

      <div className="flex gap-2.5 overflow-x-auto pb-1.5 scrollbar-thin">
        {subjectSlots.map((slot) => {
          const hasImage = Boolean(slot.previewUrl || slot.file)
          const isActive = activeSlotId === slot.id

          return (
            <div
              key={slot.id}
              className={`relative flex flex-col w-[112px] shrink-0 rounded-lg border p-1.5 bg-[#fcfcfd] transition shadow-sm ${
                hasImage ? "border-[#7047f6]/40 bg-white" : "border-dashed border-black/[0.12]"
              } ${isActive ? "ring-2 ring-[#7047f6]" : ""}`}
            >
              {/* 槽位头部 */}
              <div className="flex items-center justify-between mb-1">
                <Tooltip title="插入此主体标签">
                  <button
                    type="button"
                    onClick={() => onInsertSlotTagToShot?.(slot.id)}
                    className="flex items-center gap-0.5 px-1 py-0.5 text-[9px] font-bold text-[#7047f6] bg-[#7047f6]/10 rounded hover:bg-[#7047f6]/20 transition"
                  >
                    <span>{slot.id}</span>
                  </button>
                </Tooltip>

                {hasImage && (
                  <button
                    type="button"
                    onClick={() => handleClearSlot(slot)}
                    className="p-0.5 text-[#9ca3af] hover:text-red-500 rounded transition"
                  >
                    <X size={11} />
                  </button>
                )}
              </div>

              {/* 图像预览 / 上传区域 */}
              <input
                type="file"
                accept="image/*"
                ref={(el) => {
                  fileInputRefs.current[slot.id] = el
                }}
                onChange={(e) => handleFileUpload(slot, e)}
                className="hidden"
              />

              <div
                onClick={() => !hasImage && fileInputRefs.current[slot.id]?.click()}
                className={`relative h-[68px] w-full rounded-md overflow-hidden flex flex-col items-center justify-center cursor-pointer mb-1.5 transition ${
                  hasImage ? "bg-black" : "bg-[#f3f4f6] hover:bg-[#eceef1] text-[#9ca3af]"
                }`}
              >
                {hasImage ? (
                  <>
                    <img src={slot.previewUrl} alt={slot.name} className="w-full h-full object-cover" />
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        fileInputRefs.current[slot.id]?.click()
                      }}
                      className="absolute bottom-0.5 right-0.5 px-1 py-0.5 text-[8px] bg-black/60 text-white rounded backdrop-blur hover:bg-black/80 transition"
                    >
                      替换
                    </button>
                  </>
                ) : (
                  <>
                    <ImagePlus size={14} className="mb-0.5 text-[#7047f6]/60" />
                    <span className="text-[9px] font-medium text-[#6b7280]">添加参考</span>
                  </>
                )}
              </div>

              {/* 主体类型与保留度配置 */}
              <div className="flex flex-col gap-1">
                <Select
                  size="small"
                  value={slot.kind}
                  onChange={(val: SubjectSlotKind) => onUpdateSlot({ ...slot, kind: val })}
                  options={Object.entries(SUBJECT_KIND_LABELS).map(([k, v]) => ({
                    value: k,
                    label: v.label.split(" ")[0],
                  }))}
                  className="w-full text-[10px]"
                  style={{ fontSize: "10px" }}
                />

                <Select
                  size="small"
                  value={slot.retention}
                  onChange={(val: SubjectSlotRetention) => onUpdateSlot({ ...slot, retention: val })}
                  options={Object.entries(SUBJECT_RETENTION_LABELS).map(([k, v]) => ({
                    value: k,
                    label: v.label.split(" ")[0],
                  }))}
                  className="w-full text-[10px]"
                  style={{ fontSize: "10px" }}
                />

                {/* 智能分析按钮与输入框 */}
                <div className="relative flex items-center">
                  <Input
                    placeholder="特征..."
                    value={slot.description}
                    onChange={(e) => onUpdateSlot({ ...slot, description: e.target.value })}
                    className="w-full text-[10px] pr-5 py-0.5 h-6"
                  />
                  {hasImage && onAnalyzeSlot && (
                    <Tooltip title={analyzeDisabledReason || "根据参考图提取外貌特征"}>
                      <button
                        type="button"
                        onClick={() => !analyzeDisabledReason && onAnalyzeSlot(slot)}
                        disabled={slot.analyzing || Boolean(analyzeDisabledReason)}
                        className="absolute right-1 text-[#7047f6] hover:text-[#5b38d4] disabled:opacity-50"
                      >
                        {slot.analyzing ? <LoaderCircle size={10} className="animate-spin" /> : <Bot size={10} />}
                      </button>
                    </Tooltip>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
