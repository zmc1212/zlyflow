import { Button, Select, Space, Tag, Tooltip } from "antd"
import {
  ArrowRight,
  Clapperboard,
  FileText,
  MapPinned,
  Mic2,
  Music2,
  Package,
  PackageCheck,
  Palette,
  UserRound,
  type LucideIcon,
} from "lucide-react"
import {
  RECIPE_READINESS_LABELS,
  RECIPE_READINESS_TAG_COLOR,
  RECIPE_STAGE_GROUPS,
  RECIPE_STAGE_LABELS,
  RecipeReadiness,
  RecipeStageId,
} from "../recipe-readiness"

const STAGE_DETAILS: Record<RecipeStageId, { description: string; icon: LucideIcon }> = {
  script: {
    description: "把一句话创意整理成完整故事。这里决定人物动机、冲突和结尾，后续分镜都以此为准。",
    icon: FileText,
  },
  art_style: {
    description: "选定整支影片的视觉母版。画风会进入定妆图、静帧和镜头提示词，保持成片一致。",
    icon: Palette,
  },
  characters: {
    description: "固定人物与关键道具的外观。已完成的定妆图会按镜头自动装入参考图，最多 9 张。",
    icon: UserRound,
  },
  locations: {
    description: "固定主要场景的空间、材质和光线，减少镜头之间的环境跳变。",
    icon: MapPinned,
  },
  props: {
    description: "为关键道具生成多视角转面图，道具出现在镜头里时形态保持一致。",
    icon: Package,
  },
  shots: {
    description: "设计并制作每个镜头：先在「设计」里编辑镜头序列与提示词，再在「制作」里按镜生成静帧、预览或终稿。工作流会依据本镜素材自动选择文生、首尾帧或多参考模式。",
    icon: Clapperboard,
  },
  voice: {
    description: "检查每镜对白、说话人与音色，再生成可独立重试的逐镜配音。",
    icon: Mic2,
  },
  music: {
    description: "为整支影片设置配乐与音量包络；环境声仍由各镜头的声音方案控制。",
    icon: Music2,
  },
  export: {
    description: "串播已出片镜头，混合配音与配乐，并导出工作台成片、FCPXML、EDL 或剪映草稿。",
    icon: PackageCheck,
  },
}

export default function DirectorTaskHeader({
  activeStage,
  readiness,
  onSelect,
  compact = false,
  summary,
  primary,
  nextStage,
}: {
  activeStage: RecipeStageId
  readiness: RecipeReadiness
  onSelect: (stage: RecipeStageId) => void
  compact?: boolean
  summary?: string
  primary?: { label: string; onClick: () => void; loading?: boolean; disabled?: boolean }
  nextStage?: RecipeStageId
}) {
  const activeGroup = RECIPE_STAGE_GROUPS.find((group) => (
    (group.stages as readonly RecipeStageId[]).includes(activeStage)
  )) || RECIPE_STAGE_GROUPS[0]
  const stagePosition = activeGroup.stages.indexOf(activeStage as never) + 1
  const detail = STAGE_DETAILS[activeStage]
  const Icon = detail.icon
  const state = readiness[activeStage]

  return (
    <>
      <div className="director-mobile-stage-picker">
        <span>当前任务</span>
        <Select
          aria-label="当前创作任务"
          value={activeStage}
          onChange={(value: RecipeStageId) => onSelect(value)}
          options={RECIPE_STAGE_GROUPS.map((group) => ({
            label: group.label,
            options: group.stages.map((stage) => ({ value: stage, label: RECIPE_STAGE_LABELS[stage] })),
          }))}
        />
      </div>
      <section
        className={`director-task-context${compact ? " is-compact" : ""}`}
        aria-labelledby="director-active-task-title"
      >
        <div className="director-task-icon" aria-hidden="true">
          {compact ? (
            <Tooltip title={detail.description}>
              <span className="director-task-icon-hit"><Icon size={16} /></span>
            </Tooltip>
          ) : (
            <Icon size={20} />
          )}
        </div>
        <div className="director-task-copy">
          <span className="director-task-path">
            {activeGroup.label} · {stagePosition} / {activeGroup.stages.length}
          </span>
          <h1 id="director-active-task-title">{RECIPE_STAGE_LABELS[activeStage]}</h1>
          <p>{summary || detail.description}</p>
        </div>
        <div className="director-task-state">
          <div className="director-task-state-line">
            <Tag color={RECIPE_READINESS_TAG_COLOR[state.level]}>
              {RECIPE_READINESS_LABELS[state.level]}
            </Tag>
            {state.total > 1 ? <span>{state.done} / {state.total}</span> : null}
          </div>
          {/* 下一步引导（2026-09-13 重设计）：固定显示在标题卡状态区，全部阶段统一；
              主按钮行的「前往xxx」纯跳转已由 jump 标记移除，不再与本引导重复。
              成片是流程终点（next 回环到镜头设计），不显示。 */}
          {nextStage && activeStage !== "export" ? (
            <Button type="link" size="small" className="director-next-step" onClick={() => onSelect(nextStage)}>
              下一步：{RECIPE_STAGE_LABELS[nextStage]}
              <ArrowRight size={13} />
            </Button>
          ) : null}
        </div>
      </section>
      {primary ? (
        <Space wrap className="director-stage-actions">
          <Button type="primary" loading={primary.loading} disabled={primary.disabled} onClick={primary.onClick}>{primary.label}</Button>
        </Space>
      ) : null}
    </>
  )
}
