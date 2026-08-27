import { Alert, Button, Input, Radio, Switch, Tag, message } from "antd"
import {
  Copy, FileText,
} from "lucide-react"
import { ShotSubmission, directorSpeedLabel } from "../prompt-compiler"
import { TimelineProject } from "../types"

interface CompiledPromptInspectorProps {
  project: TimelineProject
  submission: ShotSubmission
  clipSubmission: ShotSubmission
  previewMode: "shot" | "clip"
  onPreviewModeChange: (mode: "shot" | "clip") => void
  onUpdateProject: (updated: TimelineProject) => void
  onSubmitClip?: () => void
}

export default function CompiledPromptInspector({
  project,
  submission,
  clipSubmission,
  previewMode,
  onPreviewModeChange,
  onUpdateProject,
  onSubmitClip,
}: CompiledPromptInspectorProps) {
  const active = previewMode === "clip" ? clipSubmission : submission
  const workflowLabel = {
    "minimax-h3-t2v": "T2V 文生",
    "minimax-h3-i2v": "I2V 首尾帧",
    "minimax-h3-r2v": "R2V 参考图",
  }[active.workflowId]

  const handleCopy = () => {
    navigator.clipboard.writeText(active.prompt)
    message.success("已复制即将提交的提示词")
  }

  const handleToggleManualOverride = (enabled: boolean) => {
    onUpdateProject({
      ...project,
      manualPromptOverrideEnabled: enabled,
      manualPromptOverrideText: enabled ? active.prompt : "",
    })
  }

  return (
    <section className="border-t border-black/[0.06] bg-[#fbfbfd] p-4 rounded-b-2xl">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1 text-xs font-bold text-[#111827]">
            <FileText size={15} className="text-[#7047f6]" />
            即将提交的提示词
          </span>
          <Tag color="purple" className="!m-0 text-[11px]">{workflowLabel}</Tag>
          {active.isOverride && <Tag color="gold" className="!m-0 text-[11px]">手动覆写</Tag>}
          {active.isClip && <Tag color="blue" className="!m-0 text-[11px]">整段</Tag>}
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs">
          <Radio.Group
            size="small"
            value={previewMode}
            onChange={(event) => onPreviewModeChange(event.target.value)}
            optionType="button"
            buttonStyle="solid"
          >
            <Radio.Button value="shot">单镜</Radio.Button>
            <Radio.Button value="clip" disabled={!clipSubmission.clipAllowed}>
              整段{clipSubmission.clipAllowed ? "" : " (>15s)"}
            </Radio.Button>
          </Radio.Group>

          <div className="flex items-center gap-1 px-2 py-1 bg-white border border-black/[0.06] rounded-lg shadow-sm">
            <span className="text-[#6b7280]">时长:</span>
            <strong className="text-[#111827]">{active.durationSec}s</strong>
          </div>
          <div className="flex items-center gap-1 px-2 py-1 bg-white border border-black/[0.06] rounded-lg shadow-sm">
            <span className="text-[#6b7280]">画质:</span>
            <strong className="text-[#111827]">{active.quality} MP</strong>
          </div>
          <div className="flex items-center gap-1 px-2 py-1 bg-white border border-black/[0.06] rounded-lg shadow-sm">
            <span className="text-[#6b7280]">速度:</span>
            <strong className="text-[#111827]">{directorSpeedLabel(active.speed)}</strong>
          </div>
          <div className="flex items-center gap-1 px-2 py-1 bg-white border border-black/[0.06] rounded-lg shadow-sm">
            <span className="text-[#6b7280]">参考图:</span>
            <strong className={`${active.plan.items.length > 9 ? "text-red-600" : "text-[#111827]"}`}>
              {active.plan.items.length}/9
            </strong>
          </div>
          <div className="flex items-center gap-1 px-2 py-1 bg-white border border-black/[0.06] rounded-lg shadow-sm">
            <span className="text-[#6b7280]">词数:</span>
            <strong className={`${active.wordCount > 500 ? "text-amber-600" : "text-[#111827]"}`}>
              {active.wordCount}
            </strong>
          </div>

          <div className="flex items-center gap-2 ml-2">
            <span className="text-[11px] text-[#6b7280]">手动覆写:</span>
            <Switch size="small" checked={project.manualPromptOverrideEnabled} onChange={handleToggleManualOverride} />
          </div>
          <Button size="small" onClick={handleCopy} icon={<Copy size={12} />} className="flex items-center gap-1 text-xs">
            复制
          </Button>
          {previewMode === "clip" && clipSubmission.clipAllowed && onSubmitClip && (
            <Button size="small" type="primary" onClick={onSubmitClip} className="bg-[#7047f6] text-xs">
              整段提交
            </Button>
          )}
        </div>
      </div>

      {active.plan.items.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1.5">
          {active.plan.items.map((item) => (
            <Tag key={`${item.role}-${item.pictureIndex}`} className="!m-0 text-[11px] text-[#1f2937]">
              {item.label}
            </Tag>
          ))}
        </div>
      )}

      {[...active.errors, ...active.warnings].length > 0 && (
        <div className="mb-3">
          {active.errors.map((text, index) => (
            <Alert
              key={`e-${index}`}
              type="error"
              showIcon
              message={<span className="text-xs text-red-700">{text}</span>}
              className="py-1 px-3 mb-1.5 rounded-lg"
            />
          ))}
          {active.warnings.map((text, index) => (
            <Alert
              key={`w-${index}`}
              type="warning"
              showIcon
              message={<span className="text-xs text-[#92400e]">{text}</span>}
              className="py-1 px-3 mb-1.5 rounded-lg border-amber-200 bg-amber-50"
            />
          ))}
        </div>
      )}

      {project.manualPromptOverrideEnabled ? (
        <Input.TextArea
          rows={6}
          value={project.manualPromptOverrideText}
          onChange={(event) =>
            onUpdateProject({
              ...project,
              manualPromptOverrideText: event.target.value,
            })
          }
          placeholder="输入即将提交的这一条提示词（不会改写整条未提交时间轴）"
          className="font-mono text-xs text-[#1f2937] bg-white border border-black/[0.1] rounded-xl p-3 shadow-inner"
        />
      ) : (
        <div className="relative font-mono text-xs text-[#374151] bg-white border border-black/[0.08] rounded-xl p-3.5 max-h-48 overflow-y-auto whitespace-pre-wrap leading-relaxed shadow-inner select-text">
          {active.prompt || "请先选择分镜"}
        </div>
      )}
    </section>
  )
}
