import { Button, Collapse, Popover, Select, Space } from "antd"
import { SlidersHorizontal } from "lucide-react"
import { useMemo, useState } from "react"
import {
  groupedVideoWorkflowOptions,
  optionChoices,
  videoSettingsSummary,
  type Director2VideoOptionField,
  type Director2WorkflowMode,
} from "../director2-video-settings"

export default function Director2VideoSettingsPopover({
  workflowId,
  workflows,
  fields,
  values,
  onWorkflowChange,
  onChange,
}: {
  workflowId: string
  workflows: Director2WorkflowMode[]
  fields: Director2VideoOptionField[]
  values: Record<string, string>
  onWorkflowChange: (workflowId: string) => void
  onChange: (name: string, value: string) => void
}) {
  const [open, setOpen] = useState(false)
  const primary = useMemo(() => fields.filter((item) => item.ui_group === "primary"), [fields])
  const advanced = useMemo(() => fields.filter((item) => item.ui_group === "advanced"), [fields])
  const workflowOptions = groupedVideoWorkflowOptions(workflows)
  const summary = `生成设置 · ${videoSettingsSummary(fields, values)}`

  function renderField(field: Director2VideoOptionField) {
    const choices = optionChoices(field, values)
    const current = values[field.name] || String(field.definition.default)
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
