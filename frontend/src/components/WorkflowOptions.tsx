// 工作流选择器共享渲染 —— 从生成页（App.tsx）抽出，供生成页与资产画布 Prompt Bar 复用。
// 选项行展示：图标 + 名称（默认标）+ 描述 + GRS 平台标价积分；分组信息来自 /api/modes 的 catalog_group 字段。
import { ImagePlus } from "lucide-react"

/** /api/modes 单条工作流的最小结构；App 的 Workflow 与画布的 CanvasWorkflowMode 均满足。 */
export type WorkflowOptionSource = {
  id: string
  name: string
  description?: string
  available?: boolean
  is_default?: boolean
  credit_cost?: number | null
  catalog_group?: string
  catalog_group_label?: string
  catalog_group_order?: number
}

export type WorkflowSelectOption = {
  value: string
  label: string
  title?: string
  disabled?: boolean
  description?: string
  creditCost?: number | null
  isDefault?: boolean
}

export function groupedWorkflowOptions(workflows: readonly WorkflowOptionSource[]) {
  const groups = new Map<string, { label: string; order: number; options: WorkflowSelectOption[] }>()
  const ungrouped: WorkflowSelectOption[] = []
  for (const item of workflows) {
    const option: WorkflowSelectOption = {
      value: item.id,
      label: item.name,
      title: item.description,
      disabled: !item.available,
      description: item.description,
      creditCost: item.credit_cost ?? null,
      isDefault: Boolean(item.is_default),
    }
    if (!item.catalog_group) {
      ungrouped.push(option)
      continue
    }
    const existing = groups.get(item.catalog_group)
    if (existing) {
      existing.options.push(option)
      continue
    }
    groups.set(item.catalog_group, {
      label: item.catalog_group_label || item.catalog_group,
      order: item.catalog_group_order ?? 100,
      options: [option],
    })
  }
  const grouped = [...groups.values()]
    .sort((left, right) => left.order - right.order || left.label.localeCompare(right.label, "zh-CN"))
    .map((group) => ({ label: group.label, options: group.options }))
  return ungrouped.length ? [...grouped, ...ungrouped] : grouped
}

export function WorkflowOptionRow({ item }: { item: WorkflowSelectOption }) {
  return (
    <span className="studio-workflow-option">
      <ImagePlus className="studio-workflow-option-icon" size={16} aria-hidden />
      <span className="studio-workflow-option-main">
        <span className="studio-workflow-option-title">
          {item.label}
          {item.isDefault ? <em className="studio-workflow-option-flag">默认</em> : null}
        </span>
        {item.description ? <span className="studio-workflow-option-desc">{item.description}</span> : null}
      </span>
      {typeof item.creditCost === "number" ? (
        <span className="studio-workflow-option-cost">{item.creditCost} 积分/张</span>
      ) : null}
    </span>
  )
}
