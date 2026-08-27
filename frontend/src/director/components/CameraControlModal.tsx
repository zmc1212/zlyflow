import { Input, Modal, Radio, Select, Space, Tag } from "antd"
import {
  Activity, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Camera, Compass, Eye,
  Maximize, Minimize, Move, Orbit, Play, RotateCcw, Sparkles, Sun, Video, Volume2,
} from "lucide-react"
import { useState } from "react"
import {
  CameraAngle, CameraDirection, CameraLighting, CameraMovement, CameraScale, CameraSpeed,
  CAMERA_ANGLE_LABELS, CAMERA_LIGHTING_LABELS, CAMERA_MOVEMENT_LABELS,
  CAMERA_SCALE_LABELS, CAMERA_SPEED_LABELS,
} from "../types"

interface CameraControlModalProps {
  open: boolean
  camera: CameraDirection
  shotTitle: string
  onSave: (nextCamera: CameraDirection) => void
  onCancel: () => void
}

const QUICK_SFX_PRESETS = [
  "城市车流喧嚣与人群嘈杂",
  "倾盆雷暴雨与呼啸风声",
  "深沉安静的室内呼吸与滴答时钟",
  "科幻机械运转与低频嗡鸣",
  "鸟鸣森林微风与落叶沙沙",
  "紧张沉重的心跳声",
  "轻柔抒情的电影配乐旋律",
]

export default function CameraControlModal({
  open,
  camera,
  shotTitle,
  onSave,
  onCancel,
}: CameraControlModalProps) {
  const [draft, setDraft] = useState<CameraDirection>(camera)

  const handleSave = () => {
    onSave(draft)
  }

  return (
    <Modal
      title={
        <div className="flex items-center gap-2 text-base font-semibold text-[#111827]">
          <Camera size={20} className="text-[#7047f6]" />
          <span>电影级机位与运镜</span>
          <Tag color="purple" className="ml-2">
            {shotTitle}
          </Tag>
        </div>
      }
      open={open}
      onOk={handleSave}
      onCancel={onCancel}
      okText="应用机位参数"
      cancelText="取消"
      width={720}
      className="director-camera-modal"
      destroyOnClose
    >
      <div className="space-y-6 py-3">
        {/* 1. 景别选择器 */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-[#4b5563]">
              1. 景别范围（Shot Scale）
            </span>
            <span className="text-xs text-[#6b7280]">
              {CAMERA_SCALE_LABELS[draft.scale]?.desc ?? ""}
            </span>
          </div>
          <div className="grid grid-cols-5 gap-2">
            {(Object.keys(CAMERA_SCALE_LABELS) as CameraScale[]).map((scale) => {
              const item = CAMERA_SCALE_LABELS[scale]
              const active = draft.scale === scale
              return (
                <button
                  key={scale}
                  type="button"
                  onClick={() => setDraft((prev) => ({ ...prev, scale }))}
                  className={`flex flex-col items-center justify-center rounded-xl border p-2.5 text-center transition ${
                    active
                      ? "border-[#7047f6] bg-[#7047f6]/10 font-semibold text-[#7047f6] shadow-sm"
                      : "border-black/[0.08] bg-white text-[#374151] hover:border-black/20 hover:bg-[#f9fafb]"
                  }`}
                >
                  <span className="text-xs font-bold">{scale}</span>
                  <span className="mt-0.5 text-[11px] leading-tight opacity-90">
                    {item.label.split(" ")[0]}
                  </span>
                </button>
              )
            })}
          </div>
        </div>

        {/* 2. 运镜运动方式 */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-[#4b5563]">
              2. 运镜轨迹与动作（Camera Motion）
            </span>
            <span className="text-xs text-[#6b7280]">
              {CAMERA_MOVEMENT_LABELS[draft.movement]?.desc ?? ""}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-2.5 sm:grid-cols-3">
            {(Object.keys(CAMERA_MOVEMENT_LABELS) as CameraMovement[]).map((movement) => {
              const item = CAMERA_MOVEMENT_LABELS[movement]
              const active = draft.movement === movement
              return (
                <button
                  key={movement}
                  type="button"
                  onClick={() => setDraft((prev) => ({ ...prev, movement }))}
                  className={`flex items-center gap-2.5 rounded-xl border px-3 py-2.5 text-left text-xs transition ${
                    active
                      ? "border-[#7047f6] bg-[#7047f6]/10 font-medium text-[#7047f6] shadow-sm"
                      : "border-black/[0.08] bg-white text-[#374151] hover:border-black/20 hover:bg-[#f9fafb]"
                  }`}
                >
                  <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-black/[0.04]">
                    {movement === "zoom_in" && <Maximize size={15} />}
                    {movement === "zoom_out" && <Minimize size={15} />}
                    {movement === "pan_left" && <ArrowLeft size={15} />}
                    {movement === "pan_right" && <ArrowRight size={15} />}
                    {movement === "tilt_up" && <ArrowUp size={15} />}
                    {movement === "tilt_down" && <ArrowDown size={15} />}
                    {movement === "orbit" && <Orbit size={15} />}
                    {movement === "tracking" && <Move size={15} />}
                    {movement === "static" && <Video size={15} />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-semibold">{item.label}</p>
                  </div>
                </button>
              )
            })}
          </div>
        </div>

        {/* 3. 机位角度与运镜节奏 */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-[#4b5563]">
              3. 拍摄机位高度（Angle）
            </span>
            <Select
              className="w-full"
              value={draft.angle}
              onChange={(angle: CameraAngle) => setDraft((prev) => ({ ...prev, angle }))}
              options={(Object.keys(CAMERA_ANGLE_LABELS) as CameraAngle[]).map((angle) => ({
                value: angle,
                label: `${CAMERA_ANGLE_LABELS[angle].label} - ${CAMERA_ANGLE_LABELS[angle].desc}`,
              }))}
            />
          </div>

          <div>
            <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-[#4b5563]">
              4. 运镜节奏与速度（Dynamics）
            </span>
            <Select
              className="w-full"
              value={draft.speed}
              onChange={(speed: CameraSpeed) => setDraft((prev) => ({ ...prev, speed }))}
              options={(Object.keys(CAMERA_SPEED_LABELS) as CameraSpeed[]).map((speed) => ({
                value: speed,
                label: `${CAMERA_SPEED_LABELS[speed].label} - ${CAMERA_SPEED_LABELS[speed].desc}`,
              }))}
            />
          </div>
        </div>

        {/* 4. 影调布光风格 */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-[#4b5563]">
              5. 影调与布光预设（Lighting & Atmos）
            </span>
            <span className="text-xs text-[#6b7280]">
              {CAMERA_LIGHTING_LABELS[draft.lighting]?.desc ?? ""}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {(Object.keys(CAMERA_LIGHTING_LABELS) as CameraLighting[]).map((lighting) => {
              const item = CAMERA_LIGHTING_LABELS[lighting]
              const active = draft.lighting === lighting
              return (
                <button
                  key={lighting}
                  type="button"
                  onClick={() => setDraft((prev) => ({ ...prev, lighting }))}
                  className={`flex items-center gap-2 rounded-xl border p-2 text-left text-xs transition ${
                    active
                      ? "border-[#7047f6] bg-[#7047f6]/10 font-semibold text-[#7047f6]"
                      : "border-black/[0.08] bg-white text-[#374151] hover:bg-[#f9fafb]"
                  }`}
                >
                  <Sun size={14} className={active ? "text-[#7047f6]" : "text-[#6b7280]"} />
                  <span className="truncate">{item.label}</span>
                </button>
              )
            })}
          </div>
        </div>

        {/* 5. 环境音效与配乐 (MiniMax H3 音频通道) */}
        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-[#4b5563]">
              6. 环境拟音与音效描述（MiniMax H3 音画一体）
            </span>
            <span className="text-xs text-[#9ca3af]">可选填</span>
          </div>
          <Input
            prefix={<Volume2 size={15} className="mr-1 text-[#9ca3af]" />}
            placeholder="例如：大雨落水声、远方引擎轰鸣、沉重的金属脚步..."
            value={draft.sfx}
            onChange={(e) => setDraft((prev) => ({ ...prev, sfx: e.target.value }))}
            className="rounded-lg"
          />
          <div className="mt-2 flex flex-wrap gap-1.5">
            {QUICK_SFX_PRESETS.map((preset) => (
              <button
                key={preset}
                type="button"
                onClick={() => setDraft((prev) => ({ ...prev, sfx: preset }))}
                className="rounded-md border border-black/[0.08] bg-white px-2 py-0.5 text-[11px] text-[#4b5563] transition hover:border-[#7047f6] hover:text-[#7047f6]"
              >
                + {preset}
              </button>
            ))}
          </div>
        </div>
      </div>
    </Modal>
  )
}
