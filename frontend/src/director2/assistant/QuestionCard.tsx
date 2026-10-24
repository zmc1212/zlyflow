import { useState } from "react"
import { Button, Checkbox, Input, Radio, Space, Tag } from "antd"
import type { AssistantQuestion } from "./api"

export default function QuestionCard({ question, active, busy, onAnswer }: {
  question: AssistantQuestion; active: boolean; busy: boolean
  onAnswer: (answer: { question_id: string; answer_values?: string[]; text?: string; skip?: boolean }) => Promise<void>
}) {
  const [values, setValues] = useState<string[]>([])
  const [custom, setCustom] = useState("")
  return <section className={`assistant-question${!active ? " is-answered" : ""}`} aria-label="创作澄清问题">
    <div className="assistant-question-heading"><strong>{question.title}</strong><span>{question.type === "multiple" ? "多选" : question.type === "text" ? "自由回答" : "单选"}</span></div>
    {active ? <>
      {question.type === "single" && <Radio.Group value={values[0]} onChange={e => setValues([e.target.value])} disabled={busy} className="assistant-question-options">{question.options.map(o => <Radio key={o.value} value={o.value}>{o.label}{o.recommended && <Tag variant="filled">建议</Tag>}</Radio>)}</Radio.Group>}
      {question.type === "multiple" && <Checkbox.Group value={values} onChange={v => setValues(v.map(String))} disabled={busy} className="assistant-question-options">{question.options.map(o => <Checkbox key={o.value} value={o.value}>{o.label}</Checkbox>)}</Checkbox.Group>}
      {(question.allow_custom || question.type === "text") && <Input.TextArea aria-label="自定义回答" value={custom} onChange={e => setCustom(e.target.value)} placeholder="也可以直接说你的想法" autoSize={{ minRows: 2, maxRows: 6 }} maxLength={10000} disabled={busy} />}
      <div className="assistant-question-actions"><Space><Button type="text" aria-label="跳过问题" disabled={busy} onClick={() => onAnswer({ question_id: question.id, skip: true })}>跳过</Button><Button type="primary" aria-label="提交回答" loading={busy} disabled={!values.length && !custom.trim()} onClick={() => onAnswer({ question_id: question.id, answer_values: values, text: custom })}>提交</Button></Space></div>
    </> : <p className="assistant-secondary">已结束询问，回答见下方对话。</p>}
  </section>
}
