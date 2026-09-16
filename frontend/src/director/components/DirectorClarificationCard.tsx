import { ArrowUp, ChevronLeft, ChevronRight } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import {
  SCRIPT_CLARIFY_CUSTOM_PLACEHOLDER,
  SCRIPT_CLARIFY_SKIP_ALL,
  SCRIPT_CLARIFY_SKIP_ONE,
  SCRIPT_CLARIFY_SUBMIT,
} from "../action-copy"
import {
  commitClarification,
  completeClarifications,
  emptyClarificationState,
  moveClarification,
  selectClarificationOption,
  skipClarification,
  writeCustomClarification,
} from "./director-clarification-state"

export type DirectorClarificationOption = {
  label: string
  value: string
  recommended?: boolean
}

export type DirectorClarificationQuestion = {
  id?: string
  question: string
  why?: string
  options?: DirectorClarificationOption[]
}

export type DirectorClarificationAnswer = {
  id?: string
  question: string
  answer: string
  /** 选项展示文案；Agent 仍读 `answer`（如集数 value="1"）。 */
  label?: string
}

export default function DirectorClarificationCard({
  questions,
  disabled = false,
  onConfirm,
}: {
  questions: DirectorClarificationQuestion[]
  disabled?: boolean
  onConfirm: (answers: DirectorClarificationAnswer[]) => void
}) {
  const [state, setState] = useState(emptyClarificationState)
  const autoAdvanceRef = useRef<number | null>(null)

  useEffect(() => {
    setState(emptyClarificationState())
  }, [questions])

  useEffect(() => () => {
    if (autoAdvanceRef.current !== null) window.clearTimeout(autoAdvanceRef.current)
  }, [])

  const { questionIndex, customValue, selectedOption } = state
  const current = questions[questionIndex]
  if (!current) return null

  const last = questionIndex === questions.length - 1
  const customAnswer = customValue.trim()
  const hasAnswer = selectedOption !== null || customAnswer.length > 0

  const moveTo = (index: number) => {
    if (autoAdvanceRef.current !== null) window.clearTimeout(autoAdvanceRef.current)
    autoAdvanceRef.current = null
    setState((currentState) => moveClarification(currentState, index))
  }

  const answerCurrent = (value: string) => {
    if (autoAdvanceRef.current !== null) window.clearTimeout(autoAdvanceRef.current)
    autoAdvanceRef.current = null
    const result = commitClarification(state, questions, value)
    setState(result.state)
    if (result.completedAnswers) onConfirm(result.completedAnswers)
  }

  const handleSelect = (value: string) => {
    if (autoAdvanceRef.current !== null) window.clearTimeout(autoAdvanceRef.current)
    setState((currentState) => selectClarificationOption(currentState, value))
    autoAdvanceRef.current = window.setTimeout(() => {
      autoAdvanceRef.current = null
      answerCurrent(value)
    }, 480)
  }

  const skipOne = () => {
    if (autoAdvanceRef.current !== null) window.clearTimeout(autoAdvanceRef.current)
    autoAdvanceRef.current = null
    const result = skipClarification(state, questions.length)
    setState(result.state)
    if (result.completedAnswers) onConfirm(result.completedAnswers)
  }

  const submitArrow = () => {
    if (selectedOption) answerCurrent(selectedOption)
    else if (customAnswer) answerCurrent(customAnswer)
    else skipOne()
  }

  return (
    <div className="director-approval">
      <div key={questionIndex} className="director-approval-card">
        <div className="director-approval-question"><span>{current.question}</span></div>
        {current.why ? <p className="director-approval-why">{current.why}</p> : null}
        <div className="director-approval-options">
          {(current.options || []).map((option) => {
            const on = selectedOption === option.value
            return (
              <button
                key={option.value}
                type="button"
                aria-pressed={on}
                disabled={disabled}
                className="director-approval-option"
                onClick={() => handleSelect(option.value)}
              >
                <span className={`director-approval-radio${on ? " is-on" : ""}`} aria-hidden><span className="director-approval-radio-dot" /></span>
                <span className={`director-approval-option-label${on ? " is-on" : ""}`}>{option.label}</span>
                {option.recommended ? <em className="director-approval-recommended">推荐</em> : null}
              </button>
            )
          })}
          <label className="director-approval-option is-custom">
            <span className={`director-approval-radio${customValue.trim() ? " is-on" : ""}`} aria-hidden><span className="director-approval-radio-dot" /></span>
            <span className="director-approval-option-label is-custom-label">{SCRIPT_CLARIFY_CUSTOM_PLACEHOLDER}</span>
            <input
              value={customValue}
              disabled={disabled}
              aria-label={SCRIPT_CLARIFY_CUSTOM_PLACEHOLDER}
              placeholder={SCRIPT_CLARIFY_CUSTOM_PLACEHOLDER}
              onChange={(event) => setState((currentState) => writeCustomClarification(currentState, event.target.value))}
              onKeyDown={(event) => { if (event.key === "Enter" && customAnswer) answerCurrent(customAnswer) }}
            />
          </label>
        </div>
        <div className="director-approval-footer">
          <span className="director-approval-pager">
            <button type="button" aria-label="上一题" disabled={questionIndex === 0 || disabled} onClick={() => moveTo(Math.max(0, questionIndex - 1))}><ChevronLeft size={14} /></button>
            <span className="director-approval-dots">
              {questions.map((_, index) => (
                <button
                  key={index}
                  type="button"
                  aria-label={`第 ${index + 1} 题`}
                  aria-current={index === questionIndex || undefined}
                  disabled={disabled}
                  className={`director-approval-dot${index === questionIndex ? " is-current" : ""}${index < questionIndex ? " is-done" : ""}`}
                  onClick={() => moveTo(index)}
                />
              ))}
            </span>
            <button type="button" aria-label="下一题" disabled={last || disabled} onClick={() => moveTo(Math.min(questions.length - 1, questionIndex + 1))}><ChevronRight size={14} /></button>
          </span>
          <button
            type="button"
            aria-label={hasAnswer ? "确认这个方向" : SCRIPT_CLARIFY_SKIP_ONE}
            title={hasAnswer ? (last ? SCRIPT_CLARIFY_SUBMIT : "下一题") : SCRIPT_CLARIFY_SKIP_ONE}
            disabled={disabled}
            className={`director-approval-send${hasAnswer ? " is-armed" : ""}`}
            onClick={submitArrow}
          >
            <ArrowUp size={14} />
          </button>
        </div>
      </div>
      <button type="button" className="director-approval-skip-all" disabled={disabled} onClick={() => {
        if (autoAdvanceRef.current !== null) window.clearTimeout(autoAdvanceRef.current)
        autoAdvanceRef.current = null
        onConfirm(completeClarifications(state))
      }}>
        {SCRIPT_CLARIFY_SKIP_ALL}
      </button>
    </div>
  )
}
