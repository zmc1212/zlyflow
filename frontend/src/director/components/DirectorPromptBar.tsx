import { Button } from "antd"
import { ArrowUp } from "lucide-react"
import { useRef } from "react"
import { PLAN_GENERATION_LABEL, SCRIPT_PROM_BAR_HINT } from "../action-copy"

export type PromptBarPhase = "idle" | "streaming" | "clarify"

type Props = {
  value: string
  phase: PromptBarPhase
  statusText?: string
  submitLabel?: string
  placeholder?: string
  onChange: (value: string) => void
  onSubmit: () => void
  onCancel?: () => void
  cancelRequested?: boolean
}

/**
 * Chat-style prompt bar docked at the bottom of the creation area
 * (beautifului Prompt Bar pattern): the input lives where the answer shows up.
 */
export default function DirectorPromptBar({
  value, phase, statusText, submitLabel, placeholder, onChange, onSubmit, onCancel, cancelRequested = false,
}: Props) {
  const composingRef = useRef(false)
  const streaming = phase === "streaming"
  const clarify = phase === "clarify"
  const canSubmit = !streaming && !clarify && value.trim().length > 0 && !cancelRequested

  return (
    <div className={`director-prompt-bar is-${phase}`}>
      {streaming ? (
        <div className="director-prompt-status">
          <span className="director-stream-pulse" aria-hidden />
          <span className="director-prompt-status-text">{statusText || "AI 导演正在创作…"}</span>
          {onCancel ? (
            <Button size="small" danger loading={cancelRequested} disabled={cancelRequested} onClick={onCancel}>
              {cancelRequested ? "正在取消" : "取消生成"}
            </Button>
          ) : null}
        </div>
      ) : (
        <>
          <div className="director-prompt-input">
            <textarea
              className="director-prompt-textarea"
              value={value}
              disabled={clarify}
              placeholder={placeholder}
              rows={1}
              onCompositionStart={() => { composingRef.current = true }}
              onCompositionEnd={() => { composingRef.current = false }}
              onChange={(event) => onChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !composingRef.current) {
                  event.preventDefault()
                  if (canSubmit) onSubmit()
                }
              }}
            />
            <button
              type="button"
              className={`director-prompt-send${canSubmit ? " is-armed" : ""}`}
              disabled={!canSubmit}
              aria-label={submitLabel || PLAN_GENERATION_LABEL}
              title={submitLabel || PLAN_GENERATION_LABEL}
              onClick={() => { if (canSubmit) onSubmit() }}
            >
              <ArrowUp size={15} strokeWidth={2.4} />
            </button>
          </div>
          <p className="director-prompt-hint">
            {clarify ? "回答上方的问题后才会开始生成。" : SCRIPT_PROM_BAR_HINT}
          </p>
        </>
      )}
    </div>
  )
}
