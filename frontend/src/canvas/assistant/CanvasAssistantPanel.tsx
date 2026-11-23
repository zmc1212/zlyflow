import { useCallback, useEffect, useMemo, useRef, useState, type ComponentRef } from "react"
import { Alert, Button, Collapse, Dropdown, Input, Popover, Select, Space, Spin, Tag, Tooltip } from "antd"
import { ArrowUp, Check, ChevronDown, Globe, MousePointer2, Plus, Settings2, Sparkles, Square, X, Zap } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import QuestionCard from "../../director2/assistant/QuestionCard"
import ResourcePicker from "../../director2/assistant/ResourcePicker"
import {
  canvasAssistantGet,
  canvasAssistantMutate,
  isAssistantRunning,
  mergeAssistantEvent,
  type AssistantCatalog,
  type AssistantDetail,
  type AssistantMessage,
  type AssistantQuestion,
  type AssistantRun,
  type AssistantSelections,
  type AssistantSession,
  type MessageContext,
} from "./api"
import { emptySelections, type CanvasWorkflowModeLite } from "./api"
import type { CanvasAssistantBridge } from "./assistant-bridge"
import CanvasProposalCard from "./proposal-card"

// 画布助手复用导演台对话工作区的同一份样式表与 token（assistant.css 作用域含 .canvas-assistant）。
// DOM 结构与 DirectorAssistant.tsx 的 workspace 逐类名对齐：assistant-feed / assistant-message /
// assistant-markdown / assistant-tool-trace / assistant-composer* / assistant-usage-line。
import "../../director2/assistant/assistant.css"
import "./assistant.css"

const STORAGE_PREFIX = "canvas-assistant-session"

const QUICK_PROMPTS: { label: string; desc: string; prompt: string }[] = [
  { label: "文生图节点", desc: "按描述生成一张图片", prompt: "在画布上生成一张赛博朋克城市夜景图片，16:9 画幅" },
  { label: "图片转视频", desc: "让选中的图片动起来", prompt: "把选中的图片转成一段 5 秒视频，先给方案" },
  { label: "整理画布", desc: "梳理现有节点并给创作建议", prompt: "看一下当前画布，帮我整理创作思路" },
]

function errorText(error: unknown, fallback: string): string {
  const detail = (error as { detail?: string; message?: string })?.detail || (error as Error)?.message
  const text = typeof detail === "string" && detail ? detail : fallback
  // 后端校验类 400 带技术字段名（如「正文不能超过 50000 个字符（body.text）」），
  // 对新手翻译成可执行的指引；其余错误原样透传。
  if (/50000/.test(text)) return "消息超过 5 万字上限，请精简后再发送（输入内容已保留）"
  return text
}

function formatCny(value: number, digits = 6): string {
  return `¥${value.toFixed(digits).replace(/0+$/, "").replace(/\.$/, "")}`
}

function Markdown({ text }: { text: string }) {
  return <div className="assistant-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml disallowedElements={["img"]}>{text}</ReactMarkdown></div>
}

export default function CanvasAssistantPanel({ canvasId, csrfToken, bridge, modes, open, onClose }: {
  canvasId: string
  csrfToken: string
  bridge: CanvasAssistantBridge
  modes: CanvasWorkflowModeLite[]
  open: boolean
  onClose: () => void
}) {
  const [catalog, setCatalog] = useState<AssistantCatalog | null>(null)
  const [catalogError, setCatalogError] = useState("")
  const [sid, setSid] = useState<string | null>(null)
  const [detail, setDetail] = useState<AssistantDetail | null>(null)
  const [selections, setSelections] = useState<AssistantSelections>(() => {
    // 新画布默认继承上次的模型偏好（localStorage），不必每个画布都设一遍。
    try {
      const stored = localStorage.getItem("canvas-assistant-prefs")
      if (stored) return { ...emptySelections(), ...JSON.parse(stored) as Partial<AssistantSelections> }
    } catch { /* 解析失败按默认 */ }
    return emptySelections()
  })
  const [draft, setDraft] = useState("")
  const [sending, setSending] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [phase, setPhase] = useState("")
  const [history, setHistory] = useState<AssistantSession[]>([])
  const [selectionCount, setSelectionCount] = useState(0)
  const sidRef = useRef<string | null>(null)
  const detailRef = useRef<AssistantDetail | null>(null)
  const loadGeneration = useRef(0)
  const feed = useRef<HTMLDivElement>(null)
  const followTail = useRef(true)
  const submission = useRef<string | null>(null)
  const composerInput = useRef<ComponentRef<typeof Input.TextArea>>(null)
  const storageKey = `${STORAGE_PREFIX}:${canvasId}`
  sidRef.current = sid
  detailRef.current = detail
  const enabled = !!catalog?.enabled
  const running = isAssistantRunning(detail?.run)
  const busy = loading || sending || running
  const webSearchSupported = !!catalog?.models.find(m => m.id === selections.model_id)?.capabilities?.web_search

  useEffect(() => {
    let restored: string | null = null
    try { restored = localStorage.getItem(storageKey) } catch { /* 服务端历史仍可用 */ }
    loadGeneration.current++
    sidRef.current = restored
    setSid(restored); setDetail(null); setDraft(""); setError(""); setPhase(""); setLoading(false)
  }, [storageKey])

  useEffect(() => {
    if (!open) return
    canvasAssistantGet<AssistantCatalog>("/catalog")
      .then(next => {
        setCatalog(next); setCatalogError("")
        // 模型清单变化（停用/切换供应商）时自动回落到默认模型，避免发送时报"所选模型已停用"。
        setSelections(current => {
          const modelIds = next.models.map(m => m.id)
          if (current.model_id && modelIds.includes(current.model_id)) return current
          return { ...current, model_id: modelIds[0] || "" }
        })
      })
      .catch(e => setCatalogError(errorText(e, "助手暂时无法加载")))
  }, [open])

  const loadDetail = useCallback(async (id: string) => {
    const generation = ++loadGeneration.current
    const next = await canvasAssistantGet<AssistantDetail>(`/sessions/${id}`)
    if (sidRef.current !== id || generation !== loadGeneration.current) return null
    setDetail(next); setSelections(next.session.selections)
    return next
  }, [])

  useEffect(() => {
    if (!enabled || !sid || sidRef.current !== sid) return
    setLoading(true)
    // 恢复会话成功时不再无条件清空 error：首条消息发送失败（如超长 400）会在
    // createSession→setSid 触发本 effect 的同一窗口内被 .then(setError("")) 抹掉，
    // 新手看到的就是「点了发送毫无反应」。错误只由用户关闭或下一次发送覆盖。
    loadDetail(sid).catch((e: { status?: number }) => {
      if (sidRef.current !== sid) return
      if (e?.status === 404 || e?.status === 403) {
        // 本地残留的会话 ID 属于可自愈状态：清理后回到欢迎页。
        sidRef.current = null; setSid(null); setDetail(null); setError("")
        try { localStorage.removeItem(storageKey) } catch { /* 仅本地偏好 */ }
      } else setError(errorText(e, "无法恢复上次会话，可创建新对话"))
    })
    .finally(() => { if (sidRef.current === sid) setLoading(false) })
  }, [sid, enabled, loadDetail, storageKey])

  useEffect(() => {
    if (!open) return
    canvasAssistantGet<AssistantSession[]>("/sessions")
      .then(list => setHistory(list.filter(item => item.canvas_id === canvasId)))
      .catch(() => {})
  }, [open, canvasId, sid, detail?.session.updated_at])

  useEffect(() => {
    if (!open) return
    const tick = () => setSelectionCount(bridge.getSelectionIds().length)
    tick()
    const timer = window.setInterval(tick, 1500)
    return () => window.clearInterval(timer)
  }, [open, bridge])

  const runId = detail?.run && isAssistantRunning(detail.run) ? detail.run.id : null
  useEffect(() => {
    if (!runId) return
    const run = detailRef.current?.run
    if (!run) return
    const source = new EventSource(`/api/canvas-assistant/runs/${runId}/events`)
    let finished = false
    const finish = () => {
      if (finished) return
      finished = true; source.close(); setPhase("")
      const current = sidRef.current
      if (current) loadDetail(current).catch(() => {
        setDetail(state => state ? { ...state, run: null } : state)
      })
    }
    source.addEventListener("text", event => {
      const data = JSON.parse((event as MessageEvent).data)
      setDetail(current => current && current.run?.id === runId ? mergeAssistantEvent(current, data, run.message_id) : current)
    })
    source.addEventListener("snapshot", event => {
      const data = JSON.parse((event as MessageEvent).data)
      setDetail(current => current && current.run?.id === runId ? mergeAssistantEvent(current, data, run.message_id) : current)
    })
    source.addEventListener("status", event => setPhase(JSON.parse((event as MessageEvent).data).label))
    source.addEventListener("done", finish)
    source.addEventListener("terminal", finish)
    source.onerror = () => { if (!finished) setPhase("连接暂时中断，正在恢复回复…") }
    const fallback = window.setInterval(() => {
      if (source.readyState !== EventSource.OPEN && sidRef.current) void loadDetail(sidRef.current).catch(() => {})
    }, 5000)
    return () => { finished = true; source.close(); window.clearInterval(fallback) }
  }, [runId, loadDetail])

  const createSession = useCallback(async (): Promise<string> => {
    const session = await canvasAssistantMutate<AssistantSession>(csrfToken, "/sessions", {
      canvas_id: canvasId,
      selections,
    })
    sidRef.current = session.id
    setSid(session.id)
    try { localStorage.setItem(storageKey, session.id) } catch { /* 仅本地偏好 */ }
    return session.id
  }, [canvasId, csrfToken, selections, storageKey])

  async function send(answer?: { question_id?: string; answer_values?: string[]; text?: string; skip?: boolean }) {
    if (busy || (!answer && !draft.trim())) return
    if (!catalog?.enabled || !catalog.available) return
    // 立即进入发送态：POST 期间禁用输入与按钮，防止慢网络下重复触发（此前只有 finally 里的复位）。
    setSending(true)
    followTail.current = true
    const text = answer?.text ?? draft
    const context: MessageContext = {
      selection_ids: bridge.getSelectionIds().slice(0, 40),
      viewport_node_ids: bridge.getViewportNodeIds().slice(0, 200),
    }
    try {
      let currentSid = sidRef.current
      if (!currentSid) currentSid = await createSession()
      if (!submission.current) submission.current = crypto.randomUUID()
      const run = await canvasAssistantMutate<AssistantRun>(csrfToken, `/sessions/${currentSid}/messages`, {
        ...answer, text, client_message_id: submission.current, context,
      })
      submission.current = null
      const next = await loadDetail(currentSid)
      // 落盘兜底：202 只代表请求受理，若刷新后的会话里找不到这条用户消息
      // （网络抖动/后端异常），明确报错并保留输入，绝不静默丢失。
      if (next && run.user_message_id && !next.messages.some(m => m.id === run.user_message_id)) {
        throw new Error("消息可能未保存成功（网络波动），请重试；输入内容已保留")
      }
      // 发送成功后清掉上一轮残留的错误提示（失败提示仍保留，见 session effect 注释）。
      setError("")
      if (!answer) setDraft("")
    } catch (e) { setError(errorText(e, "发送失败，输入内容已保留")) }
    finally { setSending(false) }
  }

  async function stop() {
    if (!detail?.run) return
    try { await canvasAssistantMutate(csrfToken, `/runs/${detail.run.id}/cancel`); setPhase("正在停止当前回复…") }
    catch (e) { setError(errorText(e, "停止失败")) }
  }

  async function retry(id: string) {
    if (busy) return
    setSending(true)
    try { await canvasAssistantMutate(csrfToken, `/runs/${id}/retry`, { client_message_id: crypto.randomUUID() }); if (sidRef.current) await loadDetail(sidRef.current) }
    catch (e) { setError(errorText(e, "重试失败")) }
    finally { setSending(false) }
  }

  async function changeSelection(field: "image_workflow_id" | "video_workflow_id" | "skill_id", value: string) {
    const next = { ...selections, [field]: value }
    setSelections(next)
    if (field !== "skill_id") {
      try { localStorage.setItem("canvas-assistant-prefs", JSON.stringify({ image_workflow_id: next.image_workflow_id, video_workflow_id: next.video_workflow_id })) } catch { /* 仅本地偏好 */ }
    }
    if (!detail || busy) return
    const targetId = detail.session.id
    try {
      let session: AssistantSession
      try {
        session = await canvasAssistantMutate<AssistantSession>(csrfToken, `/sessions/${targetId}`, { version: detail.session.version, selections: next }, "PATCH")
      } catch (e) {
        if (!(e as { status?: number })?.status || (e as { status?: number }).status !== 409) throw e
        const fresh = await canvasAssistantGet<AssistantDetail>(`/sessions/${targetId}`)
        session = await canvasAssistantMutate<AssistantSession>(csrfToken, `/sessions/${targetId}`, { version: fresh.session.version, selections: next }, "PATCH")
      }
      setDetail(current => current && current.session.id === session.id ? { ...current, session } : current)
    } catch { /* 偏好已在本地生效；服务端同步失败不打断输入 */ }
  }

  async function newConversation() {
    if (busy) return
    loadGeneration.current++
    sidRef.current = null; setSid(null); setDetail(null); setDraft(""); setError(""); setPhase("")
    try { localStorage.removeItem(storageKey) } catch { /* 仅本地偏好 */ }
  }

  function selectHistorySession(id: string) {
    if (busy || sidRef.current === id) return
    setDetail(null)
    sidRef.current = id
    setSid(id)
    followTail.current = true
  }

  const proposalsById = useMemo(() => {
    const map = new Map<string, AssistantDetail["proposals"][number]>()
    for (const proposal of detail?.proposals || []) map.set(proposal.id, proposal)
    return map
  }, [detail?.proposals])

  // 同会话里已有更新的待确认方案时，旧卡提示已被取代，防止把两张待确认卡都应用造成重复节点。
  const supersededProposalIds = useMemo(() => {
    const pendingInOrder: string[] = []
    for (const msg of detail?.messages || []) {
      for (const part of msg.parts || []) {
        if (part.type !== "proposal") continue
        const proposal = proposalsById.get(part.proposal_id)
        if (!proposal || proposal.status !== "awaiting_approval" || proposal.apply_result) continue
        pendingInOrder.push(proposal.id)
      }
    }
    return new Set(pendingInOrder.slice(0, -1))
  }, [detail?.messages, proposalsById])

  const historyItems = useMemo(() => history.map(item => ({
    key: item.id,
    label: <span className="canvas-assistant-history-item-label">
      <span className="canvas-assistant-history-item-title">{item.title}</span>
      <small>{new Date(item.updated_at).toLocaleString()}</small>
    </span>,
  })), [history])

  function renderPart(part: AssistantMessage["parts"][number], index: number) {
    if (part.type === "markdown") {
      return part.text ? <Markdown key={index} text={part.text} /> : null
    }
    if (part.type === "tool") {
      return <div key={index} className="assistant-tool-trace">{part.status === "failed" ? <X size={12} /> : <Check size={12} />}<span>{part.label}</span>{part.detail && <small>{part.detail}</small>}</div>
    }
    if (part.type === "question") {
      const question: AssistantQuestion = part.question
      const active = detail?.session.pending_question?.id === question.id
      return <QuestionCard key={question.id} question={question} active={active} busy={busy} onAnswer={answer => send(answer)} />
    }
    if (part.type === "proposal") {
      const proposal = proposalsById.get(part.proposal_id)
      if (!proposal) return null
      return <CanvasProposalCard key={proposal.id} proposal={proposal} modes={modes} csrfToken={csrfToken}
        apply={ops => bridge.applyProposal(ops)}
        describeNode={bridge.describeNode}
        checkNodes={bridge.filterMissingNodeIds}
        superseded={supersededProposalIds.has(proposal.id)}
        onSettled={() => { if (sidRef.current) void loadDetail(sidRef.current) }} />
    }
    if (part.type === "usage") {
      const usage = part.usage
      const cached = usage.cached_tokens || 0
      const requests = usage.requests || 0
      const cost = typeof usage.cost_cny === "number" ? usage.cost_cny : null
      const credits = typeof usage.unit_credits === "number" ? usage.unit_credits : null
      return <div key={index} className="assistant-usage-line">输入 {usage.prompt_tokens.toLocaleString("zh-CN")} · 输出 {usage.completion_tokens.toLocaleString("zh-CN")} tokens{cached > 0 && ` · 缓存命中 ${cached.toLocaleString("zh-CN")}`}{cost !== null && ` · ≈${formatCny(cost)}${usage.cost_basis === "estimated" ? "（估算）" : ""}`}{credits !== null && ` · ${credits} 积分`}{requests > 1 && ` · ${requests} 次请求`}</div>
    }
    if (part.type === "web_search") {
      return <Collapse key={index} ghost size="small" items={[{ key: "web", label: `联网来源 · ${part.results.length} 处`, children: part.results.map((item, i) => <a className="assistant-web-result" key={`${item.url}-${i}`} href={item.url} target="_blank" rel="noreferrer noopener"><strong>{item.title}</strong>{item.site && <small>{item.site}</small>}</a>) }]} />
    }
    return null
  }

  const selectedSkill = detail?.session.resource_snapshot?.skill
    ? { name: detail.session.resource_snapshot.skill.name, version_id: detail.session.resource_snapshot.skill.version_id }
    : (selections.skill_id ? { name: catalog?.skills.find(s => s.version_id === selections.skill_id)?.name || "已选技能", version_id: selections.skill_id } : null)
  const tooltipProps = { classNames: { root: "director-assistant-tooltip" } } as const

  return (
    <aside className={`canvas-assistant${open ? " is-open" : ""}`} aria-label="画布智能助手" aria-hidden={!open}>
      <header className="canvas-assistant-head">
        <span className="assistant-title"><Sparkles size={16} />画布助手</span>
        <Space size={2}>
          <Dropdown trigger={["click"]} menu={{
            items: historyItems.length ? historyItems : [{ key: "empty", label: "暂无本画布的会话", disabled: true }],
            onClick: ({ key }) => { if (key !== "empty") selectHistorySession(key) },
          }} classNames={{ root: "director-assistant-tooltip" }}>
            <Button type="text" size="small" aria-label="历史会话" disabled={busy}>历史</Button>
          </Dropdown>
          <Tooltip {...tooltipProps} title="新对话"><Button type="text" size="small" aria-label="新对话" disabled={busy} icon={<Plus size={16} />} onClick={() => void newConversation()} /></Tooltip>
          <Tooltip {...tooltipProps} title="关闭智能助手"><Button type="text" size="small" aria-label="关闭智能助手" icon={<X size={16} />} onClick={onClose} /></Tooltip>
        </Space>
      </header>
      <div className="assistant-workspace">
        <div ref={feed} className="assistant-feed" onScroll={() => { const node = feed.current; if (node) followTail.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80 }} aria-live="polite">
          {loading && <Spin className="assistant-loading" />}
          {(!sid || (detail && detail.messages.length === 0)) && !loading && <div className="assistant-welcome">
            {/* 空会话（含首条消息发送失败后）保留欢迎引导，避免「三空」页面让新手无从下手。 */}
            <div className="assistant-welcome-symbol"><Sparkles size={25} /></div>
            <h2>把想法铺上画布</h2>
            <p>助手会先读取当前画布，再给出节点与提交方案；<br />所有改动确认「应用到画布」后才会生效。</p>
            <div className="assistant-welcome-skills">
              {QUICK_PROMPTS.map(item => <Button key={item.label} className="assistant-welcome-skill" disabled={busy || !enabled} onClick={() => { setDraft(item.prompt); composerInput.current?.focus() }}><span><strong>{item.label}</strong><small>{item.desc}</small></span></Button>)}
            </div>
            <p className="assistant-welcome-example">也可以直接说：“画一张赛博朋克城市夜景，16:9”。</p>
          </div>}
          {catalogError && <Alert className="assistant-error" type="error" title={catalogError} />}
          {(detail?.messages || []).map(m => <article className={`assistant-message is-${m.role}`} key={m.id}>
            {m.role === "assistant" && <div className="assistant-speaker"><Sparkles size={13} /><span>{m.resource_names?.skill || "画布助手"}</span></div>}
            {m.parts.map((part, index) => renderPart(part, index))}
            {(m.error || m.status === "cancelled") && <Alert type="error" title={m.error || "本轮已手动停止"} action={<Button size="small" disabled={busy} onClick={() => void retry(m.run_id)}>重试继续</Button>} />}
          </article>)}
          {busy && <div className="assistant-phase"><Spin size="small" /><span>{phase || "正在准备回复…"}</span></div>}
          {error && <Alert className="assistant-error" type="error" showIcon title={error} closable onClose={() => setError("")} />}
        </div>
        <div className="assistant-composer-shell">
          {selectionCount > 0 && !running && <div className="canvas-assistant-quick-actions">
            {[["转成视频", "把选中的图片转成一段 5 秒视频，先给方案"],
              ["以此生成变体", "以选中的节点为参考生成一个新变体，先给方案"],
              ["检查任务状态", "检查选中节点上的生成任务状态，如有失败请解释原因并给修复建议"]].map(([label, prompt]) => (
              <button key={label} type="button" disabled={busy || !enabled} onClick={() => void send({ text: prompt })}>{label}</button>
            ))}
          </div>}
          <div className="assistant-composer">
            <div className="assistant-composer-body">
              {(selectionCount > 0 || selectedSkill) && <div className="assistant-selection-chips">
                {selectedSkill && <Tooltip {...tooltipProps} title={`已选技能：${selectedSkill.name}（在技能列表中可清除）`}>
                  <Tag className="assistant-skill-tag" icon={<Zap size={11} />} closable={!busy} closeIcon={<X size={11} aria-label="移除技能" />} onClose={e => { e.preventDefault(); if (!busy) void changeSelection("skill_id", "") }}><span className="assistant-chip-label">{selectedSkill.name}</span></Tag>
                </Tooltip>}
                {selectionCount > 0 && <Tooltip {...tooltipProps} title="助手会优先结合选中节点作答；点击叉号清除画布选中">
                  <Tag className="assistant-skill-tag" icon={<MousePointer2 size={11} />} closable closeIcon={<X size={11} aria-label="清除画布选中" />} onClose={e => { e.preventDefault(); bridge.clearSelection?.() }}><span className="assistant-chip-label">已选中 {selectionCount} 个节点</span></Tag>
                </Tooltip>}
              </div>}
              <Input.TextArea
                ref={composerInput}
                value={draft}
                onChange={e => setDraft(e.target.value)}
                placeholder="描述你想在画布上做什么，或告诉我接下来怎么调整…"
                aria-label="给画布助手发送消息"
                autoSize={{ minRows: 2, maxRows: 10 }}
                maxLength={50000}
                disabled={busy || !enabled}
                onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); if (busy || !enabled) return; void send() } }}
                variant="borderless"
              />
              <div className="assistant-composer-toolbar">
                <Popover
                  trigger="click"
                  placement="topLeft"
                  content={<div className="assistant-picker canvas-assistant-skill-picker">
                    <strong>创作技能</strong>
                    <p className="assistant-secondary">技能定义本次会话的创作方法（来自导演台技能库，编辑请前往导演台）。</p>
                    <ResourcePicker
                      kind="skill"
                      resources={catalog?.skills || []}
                      selectedVersionId={selections.skill_id || null}
                      busy={busy || !enabled}
                      onSelect={resource => { void changeSelection("skill_id", selections.skill_id === resource.version_id ? "" : resource.version_id) }}
                      onOpenMarket={() => {}}
                    />
                  </div>}
                >
                  <Button type="text" size="small" aria-label="创作技能" aria-pressed={!!selections.skill_id}
                    className={selections.skill_id ? "assistant-tool-selected" : undefined}
                    disabled={busy || !enabled} icon={<Zap size={14} />}>技能</Button>
                </Popover>
                <Popover
                  trigger="click"
                  placement="topLeft"
                  content={<div className="assistant-picker"><strong>推理模型</strong><Select aria-label="选择助手模型" showSearch optionFilterProp="label" value={selections.model_id || undefined} options={(catalog?.models || []).map(m => ({ label: m.label, value: m.id }))} disabled={busy || !enabled} onChange={v => setSelections(current => ({ ...current, model_id: v }))} /><p className="assistant-secondary">由管理员开放，切换仅影响本会话后续任务。</p></div>}
                >
                  <Button type="text" size="small" disabled={busy || !enabled} icon={<Sparkles size={13} />}>模型<ChevronDown size={10} /></Button>
                </Popover>
                <Tooltip {...tooltipProps} title={webSearchSupported ? (selections.web_search ? "已开启联网搜索，本轮可获取实时信息" : "开启联网搜索，获取实时信息并标注来源") : "当前模型未开放联网搜索"}>
                  <Button type="text" size="small" aria-label="联网搜索" aria-pressed={!!selections.web_search} className={selections.web_search && webSearchSupported ? "assistant-tool-selected" : undefined} disabled={busy || !enabled || !webSearchSupported} icon={<Globe size={14} />} onClick={() => setSelections(current => ({ ...current, web_search: !current.web_search }))}>联网</Button>
                </Tooltip>
                <Popover
                  trigger="click"
                  placement="topLeft"
                  content={<div className="assistant-picker">
                    <strong>生成偏好</strong>
                    <label className="canvas-assistant-pref-row"><span>生图默认模型</span>
                      <Select allowClear placeholder="每次先询问" aria-label="生图默认模型" value={selections.image_workflow_id || undefined} disabled={busy || !enabled}
                        options={modes.filter(m => (m.media_type || "image") === "image").map(m => ({ label: m.name, value: m.id }))}
                        onChange={v => void changeSelection("image_workflow_id", v || "")} />
                    </label>
                    <label className="canvas-assistant-pref-row"><span>生视频默认模型</span>
                      <Select allowClear placeholder="每次先询问" aria-label="生视频默认模型" value={selections.video_workflow_id || undefined} disabled={busy || !enabled}
                        options={modes.filter(m => (m.media_type || "video") === "video").map(m => ({ label: m.name, value: m.id }))}
                        onChange={v => void changeSelection("video_workflow_id", v || "")} />
                    </label>
                    <p className="assistant-secondary">设为默认后助手直接用该工作流出方案；清空则每次先用问题卡询问一次并记住。</p>
                  </div>}
                >
                  <Button type="text" size="small" aria-label="生成偏好" aria-pressed={!!selections.image_workflow_id || !!selections.video_workflow_id}
                    className={selections.image_workflow_id || selections.video_workflow_id ? "assistant-tool-selected" : undefined}
                    disabled={busy || !enabled} icon={<Settings2 size={14} />}>偏好</Button>
                </Popover>
                <span className="assistant-toolbar-spacer" />
                {running
                  ? <Tooltip {...tooltipProps} title="停止回复"><Button className="assistant-send" type="primary" shape="circle" aria-label="停止回复" icon={<Square size={12} />} onClick={() => void stop()} /></Tooltip>
                  : <Button className="assistant-send" type="primary" shape="circle" aria-label="发送消息" loading={sending} disabled={!draft.trim() || !enabled || !catalog?.available || busy} icon={<ArrowUp size={16} />} onClick={() => void send()} />}
              </div>
            </div>
          </div>
          <p className="assistant-composer-hint" title={selections.model_id}>{selections.model_id || "尚未选择模型"} · Enter 发送，Shift+Enter 换行</p>
        </div>
      </div>
    </aside>
  )
}
