import { useEffect, useMemo, useState } from "react"
import type { WorkshopPromptLiveState } from "./workshop-prompt-stream"
import "./workshop-prompt-live.css"

function Chevron({ open }: { open: boolean }) {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden>
      <path d="M2.2 3.6 5 6.4 7.8 3.6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function elapsedLabel(startedAt: number, working: boolean): string {
  const seconds = Math.max(0, Math.round((Date.now() - startedAt) / 1000))
  if (working) return seconds > 0 ? `思考中 ${seconds}s` : "正在思考"
  return seconds > 0 ? `思考了 ${seconds} 秒` : "思考完成"
}

function reasoningRows(text: string): string[] {
  return String(text || "")
    .split(/\n{2,}/)
    .map((row) => row.trim())
    .filter(Boolean)
}

export function splitStreamTokens(text: string): string[] {
  const source = String(text || "")
  if (!source) return []
  return source.match(/(\s+|[A-Za-z0-9_'’-]+|[^\sA-Za-z0-9])/g) || [source]
}

export function WorkshopPromptLive({
  state,
}: {
  state: WorkshopPromptLiveState
}) {
  const [manualExpanded, setManualExpanded] = useState<boolean | null>(null)
  const [now, setNow] = useState(Date.now())
  const hasReasoning = Boolean(state.reasoning.trim())
  const autoExpanded = state.working || hasReasoning
  const expanded = manualExpanded ?? autoExpanded
  const rows = useMemo(() => reasoningRows(state.reasoning), [state.reasoning])
  const tokens = useMemo(() => splitStreamTokens(state.text), [state.text])
  const header = state.working
    ? (hasReasoning ? elapsedLabel(state.startedAt, true) : (state.message || "正在思考"))
    : elapsedLabel(state.startedAt, false)

  useEffect(() => {
    if (!state.working) return undefined
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [state.working])
  void now

  return (
    <div className="workshop-prompt-live" data-working={state.working ? "true" : "false"}>
      <button
        type="button"
        className="workshop-think-head"
        onClick={() => setManualExpanded((current) => !(current ?? autoExpanded))}
      >
        {state.working ? <span className="workshop-think-spinner" aria-hidden /> : <span className="workshop-think-dot" aria-hidden />}
        <span className={state.working ? "workshop-think-status" : "workshop-think-done"}>{header}</span>
        <span className={`workshop-think-chevron${expanded ? " is-open" : ""}`}><Chevron open={expanded} /></span>
      </button>
      <div className={`workshop-think-fold${expanded ? " is-open" : ""}`}>
        <div>
          {hasReasoning ? (
            <div className="workshop-think-trace">
              {rows.map((row, index) => (
                <p key={`${index}-${row.slice(0, 24)}`} className="workshop-think-row">{row}</p>
              ))}
            </div>
          ) : state.working ? (
            <div className="workshop-pixel-loader" aria-hidden>
              <div className="workshop-pixel-grid">
                {Array.from({ length: 9 }, (_, index) => <span key={index} />)}
              </div>
              <span className="workshop-pixel-label">正在等待模型开始输出</span>
            </div>
          ) : null}
        </div>
      </div>
      {state.text || state.working ? (
        <div className="workshop-stream-text">
          {tokens.map((token, index) => (
            <span key={`${index}-${token.slice(0, 8)}`} className="workshop-stream-token">{token}</span>
          ))}
          {state.working ? <span className="workshop-stream-caret" aria-hidden /> : null}
        </div>
      ) : null}
    </div>
  )
}
