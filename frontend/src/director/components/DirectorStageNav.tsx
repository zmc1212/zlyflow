import { Collapse, Menu, Tag } from "antd"
import {
  RECIPE_READINESS_LABELS,
  RECIPE_READINESS_TAG_COLOR,
  RECIPE_STAGE_GROUPS,
  RECIPE_STAGE_LABELS,
  RecipeReadiness,
  RecipeStageId,
} from "../types"

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
        items={RECIPE_STAGE_GROUPS.map((group) => ({
          key: group.id,
          label: group.label,
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
                      <span>{RECIPE_STAGE_LABELS[stage]}</span>
                      <Tag color={RECIPE_READINESS_TAG_COLOR[item.level]}>
                        {RECIPE_READINESS_LABELS[item.level]}
                      </Tag>
                    </span>
                  ),
                }
              })}
            />
          ),
        }))}
      />
    </nav>
  )
}
