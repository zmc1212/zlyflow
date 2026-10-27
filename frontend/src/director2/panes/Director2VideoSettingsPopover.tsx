import { Button, Collapse, Popover, Select, Space, Switch } from "antd"
import { SlidersHorizontal } from "lucide-react"
import { useMemo, useState } from "react"
import {
  episodeVideoRenderMode,
  formatRefineDuration,
  groupedVideoWorkflowOptions,
  optionChoices,
  refinePlan,
  videoOptionVisible,
  videoSettingsSummary,
  type Director2VideoOptionField,
  type Director2WorkflowMode,
} from "../director2-video-settings"

export default function Director2VideoSettingsPopover({
  workflowId,
  workflows,
  fields,
  values,
  durationSec,
  onWorkflowChange,
  onChange,
}: {
  workflowId: string
  workflows: Director2WorkflowMode[]
  fields: Director2VideoOptionField[]
  values: Record<string, string>
  durationSec?: number
  onWorkflowChange: (workflowId: string) => void
  onChange: (name: string, value: string) => void
}) {
  const [open, setOpen] = useState(false)
  const primary = useMemo(
    () => fields.filter((item) => item.ui_group === "primary" && videoOptionVisible(item, values)),
    [fields, values],
  )
  const advanced = useMemo(
    () => fields.filter((item) => item.ui_group === "advanced" && videoOptionVisible(item, values)),
    [fields, values],
  )
  const workflowOptions = groupedVideoWorkflowOptions(workflows)
  const previewFirstPass = episodeVideoRenderMode(workflows.find((item) => item.id === workflowId)) !== "episode"
  const summary = `生成设置 · ${videoSettingsSummary(fields, values, durationSec, previewFirstPass)}`
  const refineHint = useMemo(() => {
    if (values.refine_enabled !== "true" || !durationSec || durationSec <= 0) return null
    const plan = refinePlan(
      values.refine_quality || "1.0",
      values.refine_quality_mode || "auto",
      durationSec,
      values.aspect_ratio || "16:9",
    )
    return { ...plan, durationLabel: formatRefineDuration(plan.estimatedSeconds) }
  }, [values, durationSec])

  function renderField(field: Director2VideoOptionField) {
    const current = values[field.name] || String(field.definition.default)
    if (field.definition.type === "boolean") {
      return (
        <label className="d2-video-settings-field is-switch" key={field.name}>
          <span>{field.definition.label}</span>
          <Switch
            aria-label={field.definition.label}
            checked={current === "true"}
            onChange={(checked) => onChange(field.name, checked ? "true" : "false")}
            size="small"
          />
          {field.definition.description ? <em>{field.definition.description}</em> : null}
        </label>
      )
    }
    const choices = optionChoices(field, values)
    const options = choices.some((item) => item.value === current)
      ? choices
      : [...choices, { value: current, label: `${current}（已有设置）` }]
    return (
      <label className="d2-video-settings-field" key={field.name}>
        <span>{field.definition.label}</span>
        <Select
          aria-label={field.definition.label}
          value={current}
          options={options}
          onChange={(next) => onChange(field.name, String(next))}
        />
        {field.definition.description ? <em>{field.definition.description}</em> : null}
      </label>
    )
  }

  const content = (
    <div className="d2-video-settings-form">
      {workflows.length ? (
        <label className="d2-video-settings-field">
          <span>视频工作流</span>
          <Select
            aria-label="视频工作流"
            value={workflowId}
            options={workflowOptions}
            onChange={(next) => onWorkflowChange(String(next))}
          />
        </label>
      ) : null}
      {primary.map(renderField)}
      {refineHint ? (
        <div className="d2-video-settings-refine-hint">
          <strong>
            二采输出 {refineHint.resolutionLabel || `${refineHint.effectiveMegapixels.toFixed(1)} MP`}
            （{refineHint.effectiveMegapixels.toFixed(1)} MP）
          </strong>
          {refineHint.estimatedSeconds ? (
            <span>
              本镜约 {Math.round(durationSec || 0)} 秒，预计全程 {refineHint.durationLabel}（一采 + 二采）。
            </span>
          ) : (
            <span>超出平台安全预算：长片二采可能超过 30 分钟，并可能因显存不足失败。</span>
          )}
          {refineHint.capped ? (
            <span>
              目标 {refineHint.requestedMegapixels.toFixed(1)} MP 已按片长自动降档；需要原尺寸请把清晰度策略改为「强制高清」。
            </span>
          ) : null}
          {refineHint.forced ? (
            <span>
              强制高清严格按 {refineHint.requestedMegapixels.toFixed(1)} MP 输出，超出安全预算时提交前会再次确认。
            </span>
          ) : null}
        </div>
      ) : null}
      {advanced.length ? (
        <Collapse
          defaultActiveKey={["advanced"]}
          items={[{
            key: "advanced",
            label: "更多设置",
            children: <Space direction="vertical" className="w-full">{advanced.map(renderField)}</Space>,
          }]}
        />
      ) : null}
    </div>
  )

  return (
    <Popover
      trigger="click"
      placement="bottomRight"
      open={open}
      onOpenChange={setOpen}
      overlayClassName="d2-video-settings-popover"
      content={content}
    >
      <Button icon={<SlidersHorizontal size={14} />} aria-expanded={open} aria-label={summary}>
        {summary}
      </Button>
    </Popover>
  )
}
