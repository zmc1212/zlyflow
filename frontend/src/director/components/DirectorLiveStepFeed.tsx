import { Button, Space } from "antd"
import { CheckCircle2, ChevronRight, XCircle, type LucideIcon } from "lucide-react"
import type { ReactNode } from "react"
import { SCRIPT_PATH_LABEL } from "../action-copy"

function RegenerateIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" />
    </svg>
  )
}

export type DirectorLiveStepChoice = {
  question: string
  answer: string
}

export type DirectorPathChipGroup = {
  id: string
  label: string
  items: DirectorLiveStepChoice[]
}

/** 记录流顶部创作路径：按阶段分组的只读 Tool Chips，不是手风琴。 */
export function DirectorPathChips({
  label = SCRIPT_PATH_LABEL,
  groups,
}: {
  label?: string
  groups: DirectorPathChipGroup[]
}) {
  if (!groups.length) return null
  return (
    <div className="director-direction-chips is-path" aria-label={label}>
      <span className="director-direction-label">{label}</span>
      <div className="director-direction-stages">
        {groups.map((group) => (
          <div key={group.id} className="director-direction-stage">
            <span className="director-direction-stage-label">{group.label}</span>
            <span className="director-direction-stage-chips">
              {group.items.map((item, index) => {
                const title = `${item.question} → ${item.answer}`
                return (
                  <span key={`${item.question}-${item.answer}-${index}`} className="director-direction-chip" title={title}>
                    {item.answer}
                  </span>
                )
              })}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function DirectorLiveStepChoices({
  items,
  fallback,
  inset = true,
}: {
  items?: DirectorLiveStepChoice[]
  fallback?: string
  inset?: boolean
}) {
  if (items?.length) {
    return (
      <div className={`director-step-row-choices${inset ? "" : " is-flush"}`} aria-label="已确认选项">
        {items.map((item, index) => {
          const label = `${item.question} → ${item.answer}`
          return (
            <div key={`${item.question}-${item.answer}-${index}`} className="director-step-choice" title={label}>
              <span className="director-step-choice-q">{item.question}</span>
              <span className="director-step-choice-a">{item.answer}</span>
            </div>
          )
        })}
      </div>
    )
  }
  if (fallback) {
    return (
      <div className={`director-step-row-choices${inset ? "" : " is-flush"}`} aria-label="已确认选项">
        <span className="director-step-choice-chip is-muted">{fallback}</span>
      </div>
    )
  }
  return null
}

export function DirectorLiveStepRow({
  id,
  label,
  status,
  preview,
  viewLabel = "查看详情",
  regenerateTitle = "重新生成",
  choices,
  choiceFallback,
  onOpen,
  onRegenerate,
}: {
  id: string
  label: string
  status: string
  preview: string
  viewLabel?: string
  regenerateTitle?: string
  choices?: DirectorLiveStepChoice[]
  choiceFallback?: string
  onOpen?: (id: string) => void
  onRegenerate?: (id: string) => void
}) {
  const failed = status === "failed"
  return (
    <div className={`director-step-row is-${status}`}>
      <div className="director-step-row-main">
        <button
          type="button"
          className="director-step-row-head"
          title={`${label} · ${viewLabel}`}
          onClick={() => onOpen?.(id)}
        >
          <span className="director-step-row-icon" aria-hidden>
            {failed
              ? <XCircle size={14} className="is-failed" />
              : <CheckCircle2 size={14} className="is-done" />}
            <ChevronRight size={12} className="director-step-row-icon-chevron" />
          </span>
          <span className="director-step-row-name">{label}</span>
          <span className="director-step-row-chip">{preview}</span>
        </button>
        {onRegenerate ? (
          <button
            type="button"
            className="director-step-regen"
            title={regenerateTitle}
            onClick={(event) => {
              event.stopPropagation()
              onRegenerate(id)
            }}
          >
            <span className="director-step-regen-icon" aria-hidden><RegenerateIcon /></span>
          </button>
        ) : null}
      </div>
      <DirectorLiveStepChoices items={choices} fallback={choiceFallback} />
    </div>
  )
}

export function DirectorLiveBlock({
  label,
  message,
  icon: Icon,
  children,
}: {
  label: string
  message?: string
  icon?: LucideIcon
  children?: ReactNode
}) {
  return (
    <section className="director-block is-running is-live">
      <div className="director-block-head">
        <span className="director-step-spinner" aria-hidden />
        {Icon ? <Icon size={13} className="director-block-icon" /> : null}
        <span className="director-block-title">{label}</span>
        {message ? <span className="director-step-status">{message}</span> : null}
      </div>
      <div className="director-block-body">
        {children || (
          <div className="director-live-skeleton" aria-hidden>
            <span style={{ width: "38%" }} />
            <span style={{ width: "72%" }} />
            <span style={{ width: "56%" }} />
            <span style={{ width: "64%" }} />
          </div>
        )}
      </div>
    </section>
  )
}

/** 阶段跑完后的确认卡：复用直播块与完成卡类名，暂停态无 spinner。 */
export function DirectorReviewBlock({
  label,
  message,
  icon: Icon,
  lastStep = false,
  busy = false,
  onAccept,
  onRevise,
  children,
}: {
  label: string
  message?: string
  icon?: LucideIcon
  lastStep?: boolean
  busy?: boolean
  onAccept: () => void
  onRevise: () => void
  children?: ReactNode
}) {
  return (
    <section className="director-block">
      <div className="director-block-head">
        {Icon ? <Icon size={13} className="director-block-icon" /> : null}
        <span className="director-block-title">{label}</span>
        {message ? <span className="director-block-preview">{message}</span> : null}
      </div>
      <div className="director-block-body">
        {children}
        <div className="director-completion-card">
          <div className="director-completion-copy">
            <strong>{lastStep ? "分镜已经生成，确认后完成本次创作" : "这一步可以进入下一步吗？"}</strong>
            <span>采纳后{lastStep ? "完成本次生成" : "进入下一阶段"}；不满意可在下方说明想怎么改。</span>
          </div>
          <Space wrap>
            <Button disabled={busy} onClick={onRevise}>不满意，调整</Button>
            <Button type="primary" loading={busy} disabled={busy} onClick={onAccept}>
              {lastStep ? "采纳，完成创作" : "采纳，继续下一步"}
            </Button>
          </Space>
        </div>
      </div>
    </section>
  )
}
