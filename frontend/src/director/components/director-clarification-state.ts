import type { DirectorClarificationAnswer, DirectorClarificationQuestion } from "./DirectorClarificationCard"

export type DirectorClarificationState = {
  questionIndex: number
  customValue: string
  selectedOption: string | null
  answers: DirectorClarificationAnswer[]
}

export function emptyClarificationState(): DirectorClarificationState {
  return { questionIndex: 0, customValue: "", selectedOption: null, answers: [] }
}

export function selectClarificationOption(state: DirectorClarificationState, value: string): DirectorClarificationState {
  return { ...state, selectedOption: value, customValue: "" }
}

export function writeCustomClarification(state: DirectorClarificationState, value: string): DirectorClarificationState {
  return { ...state, selectedOption: null, customValue: value }
}

export function moveClarification(state: DirectorClarificationState, index: number): DirectorClarificationState {
  return { ...state, questionIndex: index, selectedOption: null, customValue: "" }
}

export function commitClarification(
  state: DirectorClarificationState,
  questions: DirectorClarificationQuestion[],
  value: string,
): { state: DirectorClarificationState; completedAnswers?: DirectorClarificationAnswer[] } {
  const current = questions[state.questionIndex]
  if (!current) return { state }
  const option = (current.options || []).find((item) => item.value === value)
  const label = option?.label?.trim()
  const answers = [...state.answers, {
    id: current.id,
    question: current.question,
    answer: value,
    ...(label && label !== value ? { label } : {}),
  }]
  const completed = value === "保留并跳过 AI 生成" || state.questionIndex + 1 >= questions.length
  return {
    state: { questionIndex: completed ? state.questionIndex : state.questionIndex + 1, customValue: "", selectedOption: null, answers },
    completedAnswers: completed ? answers : undefined,
  }
}

export function skipClarification(
  state: DirectorClarificationState,
  questionCount: number,
): { state: DirectorClarificationState; completedAnswers?: DirectorClarificationAnswer[] } {
  const completed = state.questionIndex + 1 >= questionCount
  return {
    state: { ...state, questionIndex: completed ? state.questionIndex : state.questionIndex + 1, customValue: "", selectedOption: null },
    completedAnswers: completed ? state.answers : undefined,
  }
}

export function completeClarifications(state: DirectorClarificationState): DirectorClarificationAnswer[] {
  return state.answers
}
