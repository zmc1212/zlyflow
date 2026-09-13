import { Segmented, Tooltip } from "antd"
import { PenLine, Wand2 } from "lucide-react"
import { DIRECTOR_CREATION_MODE_LABELS, type DirectorCreationMode } from "../creation-mode"

const OPTIONS: { value: DirectorCreationMode; icon: typeof Wand2; title: string }[] = [
  { value: "agent", icon: Wand2, title: "AI 生成：按环节自动创作" },
  { value: "manual", icon: PenLine, title: "手动编辑：直接编写与修改各环节内容" },
]

export default function DirectorCreationModeSwitch({
  value,
  onChange,
  disabled = false,
  compact = false,
  className,
}: {
  value: DirectorCreationMode
  onChange: (mode: DirectorCreationMode) => void
  disabled?: boolean
  compact?: boolean
  className?: string
}) {
  return (
    <Segmented
      className={className ? `${className}${compact ? " is-compact" : ""}` : undefined}
      aria-label="创作模式"
      value={value}
      disabled={disabled}
      onChange={(mode) => onChange(mode as DirectorCreationMode)}
      options={OPTIONS.map(({ value: mode, icon: Icon, title }) => ({
        value: mode,
        label: compact ? (
          <Tooltip title={`${DIRECTOR_CREATION_MODE_LABELS[mode]} · ${title}`}>
            <span className="director-creation-mode-option" role="img" aria-label={DIRECTOR_CREATION_MODE_LABELS[mode]}>
              <Icon size={14} />
            </span>
          </Tooltip>
        ) : (
          <span className="director-creation-mode-option">
            <Icon size={14} />
            {DIRECTOR_CREATION_MODE_LABELS[mode]}
          </span>
        ),
      }))}
    />
  )
}
