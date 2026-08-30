import { Collapse, Menu, Tag } from "antd"
import { AudioLines, Clapperboard, FileStack, PackageCheck, type LucideIcon } from "lucide-react"
import {
  RECIPE_READINESS_LABELS,
  RECIPE_READINESS_TAG_COLOR,
  RECIPE_STAGE_GROUPS,
  RECIPE_STAGE_LABELS,
  RecipeReadiness,
  RecipeStageId,
} from "../recipe-readiness"

const GROUP_ICONS: Record<string, LucideIcon> = {
  plan: FileStack,
  production: Clapperboard,
  sound: AudioLines,
  delivery: PackageCheck,
}

export default function DirectorStageNav({
  activeStage,
  readiness,
  defaultOpenGroups,
  onSelect,
}: {
  activeStage: RecipeStageId
  readiness: RecipeReadiness
  defaultOpenGroups: string[]
  onSelect: (stage: RecipeStageId) => void
}) {
  return (
    <nav className="director-stage-nav" aria-label="创作任务">
      <Collapse
        defaultActiveKey={defaultOpenGroups}
        className="director-stage-collapse"
        items={RECIPE_STAGE_GROUPS.map((group) => {
          const Icon = GROUP_ICONS[group.id]
          const readyCount = group.stages.filter((stage) => readiness[stage].level === "ready").length
          return {
            key: group.id,
            label: (
              <span className="director-stage-group-label">
                <span className="director-stage-group-icon"><Icon size={15} /></span>
                <strong>{group.label}</strong>
                <em>{readyCount}/{group.stages.length}</em>
              </span>
            ),
            children: (
              <Menu
                mode="inline"
                selectable
                selectedKeys={[activeStage]}
                onClick={({ key }) => onSelect(key as RecipeStageId)}
                items={group.stages.map((stage) => {
                  const item = readiness[stage]
                  return {
                    key: stage,
                    label: (
                      <span className="director-stage-item">
                        <span className={`director-stage-dot is-${item.level}`} aria-hidden="true" />
                        <span className="director-stage-name">{RECIPE_STAGE_LABELS[stage]}</span>
                        <Tag color={RECIPE_READINESS_TAG_COLOR[item.level]}>
                          {RECIPE_READINESS_LABELS[item.level]}
                        </Tag>
                      </span>
                    ),
                  }
                })}
              />
            ),
          }
        })}
      />
    </nav>
  )
}
