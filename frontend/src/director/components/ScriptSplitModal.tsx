import { useMutation } from "@tanstack/react-query"
import { Button, Input, InputNumber, message, Modal, Select, Space, Tag } from "antd"
import { Film, Sparkles, Wand2 } from "lucide-react"
import { useEffect, useState } from "react"
import { requestJson } from "../../api"
import { CameraDirection, CastAsset, defaultCameraDirection, DirectorShot } from "../types"

export interface ScriptSplitApplyResult {
  projectTitle: string
  summary: string
  shots: DirectorShot[]
  sourceScript: string
  styleVibe: string
  requestedShotCount: number
}

interface ScriptSplitModalProps {
  open: boolean
  csrfToken: string
  castList?: CastAsset[]
  initialScript?: string
  initialStyleVibe?: string
  initialShotCount?: number
  applyLabel?: string
  onApply: (result: ScriptSplitApplyResult) => void
  onCancel: () => void
}

interface SplitResponse {
  project_title: string
  summary: string
  shots: Array<{
    shot_number: number
    title: string
    prompt: string
    scale: string
    movement: string
    angle: string
    speed: string
    lighting: string
    sfx: string
  }>
}

const SAMPLE_SCRIPTS = [
  {
    title: "雨夜仿生人追缉",
    vibe: "赛博朋克",
    text: "在2088年的霓虹雨夜，侦探穿过积水泛光的暗巷，追踪一名失控的仿生人。仿生人突然从高处跃下，在闪烁的电子招牌下与侦探对峙，最终消失在暴雨弥漫的夜色中。",
  },
  {
    title: "深空探险与未知遗迹",
    vibe: "科幻史诗",
    text: "探险飞船降落在一颗孤寂的冰封异星。宇航员踏入古老的晶体神殿，随着中央能源装置被激活，巨大的全息星图升起，揭示出古老文明的秘密。",
  },
  {
    title: "侠客竹林决斗",
    vibe: "东方武侠",
    text: "晨雾弥漫的翠绿竹海中，白衣剑客静立在竹尖上。黑衣杀手破雾而出，剑光如匹练交错，落叶纷纷，胜负在一瞬之间分晓。",
  },
]

export default function ScriptSplitModal({
  open,
  csrfToken,
  castList = [],
  initialScript = "",
  initialStyleVibe = "电影级大片",
  initialShotCount = 4,
  applyLabel,
  onApply,
  onCancel,
}: ScriptSplitModalProps) {
  const [script, setScript] = useState(initialScript)
  const [shotCount, setShotCount] = useState<number>(initialShotCount)
  const [styleVibe, setStyleVibe] = useState(initialStyleVibe || "电影级大片")
  const [previewResult, setPreviewResult] = useState<SplitResponse | null>(null)

  useEffect(() => {
    if (!open) return
    setScript(initialScript)
    setShotCount(initialShotCount || 4)
    setStyleVibe(initialStyleVibe || "电影级大片")
    setPreviewResult(null)
  }, [open, initialScript, initialShotCount, initialStyleVibe])

  const splitMutation = useMutation({
    mutationFn: () =>
      requestJson<SplitResponse>("/api/llm/split-script", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({
          script: script.trim(),
          shot_count: shotCount,
          style_vibe: styleVibe,
          cast_names: castList.map((c) => c.name),
        }),
      }),
    onSuccess: (data) => {
      setPreviewResult(data)
      message.success("剧本分镜拆解成功！可在下方核对后导入")
    },
    onError: (err) => {
      message.error(`剧本拆解失败：${err instanceof Error ? err.message : "未知错误"}`)
    },
  })

  const handleApply = () => {
    if (!previewResult) return
    const shots: DirectorShot[] = previewResult.shots.map((s, idx) => {
      const camera: CameraDirection = {
        ...defaultCameraDirection(),
        scale: (s.scale as any) || "MS",
        movement: (s.movement as any) || "zoom_in",
        angle: (s.angle as any) || "eye_level",
        speed: (s.speed as any) || "smooth",
        lighting: (s.lighting as any) || "cinematic_soft",
        sfx: s.sfx || "",
      }
      return {
        id: `shot-${Date.now()}-${idx + 1}-${Math.random().toString(36).slice(2, 6)}`,
        shotNumber: idx + 1,
        title: s.title || `分镜 ${idx + 1}`,
        startSec: idx * 5,
        durationSec: 5, // H3 单镜默认吸附 5 秒
        prompt: s.prompt || "",
        camera,
        referencedSubjectIds: [],
        takes: [],
        activeTakeIndex: 0,
        status: "idle",
        progress: 0,
        retakeCount: 0,
      }
    })

    onApply({
      projectTitle: previewResult.project_title,
      summary: previewResult.summary,
      shots,
      sourceScript: script.trim(),
      styleVibe,
      requestedShotCount: shotCount,
    })
    onCancel()
  }


  return (
    <Modal
      title={
        <div className="flex items-center gap-2 text-base font-semibold text-[#111827]">
          <Wand2 size={20} className="text-[#4d6bfe]" />
          <span>AI 拆分剧本</span>
        </div>
      }
      open={open}
      onCancel={onCancel}
      footer={
        <div className="flex items-center justify-between">
          <span className="text-xs text-[#6b7280]">
            结合内置大模型影视视听语言体系智能拆解
          </span>
          <Space>
            <Button onClick={onCancel}>取消</Button>
            {previewResult ? (
                <Button type="primary" onClick={handleApply} className="bg-[#4d6bfe]">
                {applyLabel || "导入时间轴"}（{previewResult.shots.length} 个镜头）
              </Button>
            ) : (
              <Button
                type="primary"
                onClick={() => splitMutation.mutate()}
                loading={splitMutation.isPending}
                disabled={!script.trim()}
                className="bg-[#4d6bfe]"
                icon={<Sparkles size={15} />}
              >
                开始智能拆解
              </Button>
            )}
          </Space>
        </div>
      }
      width={780}
      className="director-split-modal"
      destroyOnHidden
    >
      <div className="space-y-4 py-2">
        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-xs font-semibold text-[#374151]">
              剧本文案 / 故事大纲 / 旁白描述
            </span>
            <div className="flex items-center gap-1 text-xs text-[#6b7280]">
                  <span>快速填入：</span>
              {SAMPLE_SCRIPTS.map((item) => (
                <button
                  key={item.title}
                  type="button"
                  onClick={() => {
                    setScript(item.text)
                    setStyleVibe(item.vibe)
                  }}
                  className="rounded px-1.5 py-0.5 text-[#4d6bfe] hover:bg-[#4d6bfe]/10"
                >
                  {item.title}
                </button>
              ))}
            </div>
          </div>
          <Input.TextArea
            rows={4}
            value={script}
            onChange={(e) => setScript(e.target.value)}
            placeholder="输入您的一段剧本文案、故事情节或视频创意大纲，AI 导演将自动拆解为连续分镜镜头..."
            className="rounded-lg text-sm"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <span className="mb-1.5 block text-xs font-semibold text-[#374151]">
              期望镜头数量
            </span>
            <InputNumber
              min={2}
              max={10}
              value={shotCount}
              onChange={(val) => setShotCount(val || 4)}
              className="w-full rounded-lg"
              addonAfter="个镜头"
            />
          </div>
          <div>
            <span className="mb-1.5 block text-xs font-semibold text-[#374151]">
              影视风格基调
            </span>
            <Select
              className="w-full"
              value={styleVibe}
              onChange={setStyleVibe}
              options={[
                { value: "电影级大片", label: "电影级大片" },
                { value: "赛博朋克", label: "赛博朋克" },
                { value: "3D动画短片", label: "3D 动画短片" },
                { value: "东方武侠古风", label: "东方武侠古风" },
                { value: "微缩定格动画", label: "微缩定格动画" },
                { value: "纪实纪录片", label: "纪实纪录片" },
              ]}
            />
          </div>
        </div>

        {/* 预览拆解结果 */}
        {previewResult && (
          <div className="mt-4 rounded-xl border border-[#7047f6]/20 bg-[#7047f6]/[0.02] p-4">
            <div className="mb-3 flex items-center justify-between border-b border-black/[0.06] pb-2">
              <div className="flex items-center gap-2">
                <Film size={16} className="text-[#7047f6]" />
                <span className="font-semibold text-[#111827]">
                  {previewResult.project_title}
                </span>
              </div>
              <span className="text-xs text-[#6b7280]">
                {previewResult.summary}
              </span>
            </div>
            <div className="max-h-60 space-y-2 overflow-y-auto pr-1">
              {previewResult.shots.map((shot, idx) => (
                <div
                  key={idx}
                  className="flex items-start gap-3 rounded-lg border border-black/[0.06] bg-white p-2.5 text-xs shadow-xs"
                >
                  <span className="grid size-6 shrink-0 place-items-center rounded bg-[#7047f6]/10 font-bold text-[#7047f6]">
                    {idx + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 flex items-center gap-2">
                      <span className="font-semibold text-[#111827]">{shot.title}</span>
                      <Tag color="blue">{shot.scale}</Tag>
                      <Tag color="purple">{shot.movement}</Tag>
                      <Tag>{shot.lighting}</Tag>
                    </div>
                    <p className="line-clamp-2 text-[#4b5563]">{shot.prompt}</p>
                    {shot.sfx ? (
                      <p className="mt-1 text-[11px] text-[#9ca3af]">
                        🎵 音效: {shot.sfx}
                      </p>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </Modal>
  )
}
