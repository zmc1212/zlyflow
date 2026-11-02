import { afterEach, describe, expect, it, vi } from "vitest"
import { assistantReplyNotification, assistantReplyText, requestAssistantNotificationPermission, shouldNotifyReply, showAssistantReplyNotification } from "./assistant-notify"
import { emptySelections, type AssistantArtifact, type AssistantDetail, type AssistantQuestion, type AssistantRun, type AssistantSession, type AssistantMessage } from "./api"

function run(overrides: Partial<AssistantRun> = {}): AssistantRun {
  return { id: "r", session_id: "s", message_id: "m", cancel_requested: false, status: "succeeded", version: 1, created_at: "now", updated_at: "now", ...overrides }
}
function session(overrides: Partial<AssistantSession> = {}): AssistantSession {
  return { id: "s", status: "ready", version: 1, created_at: "now", updated_at: "now", title: "西游创作", project_id: "project-a", selections: emptySelections(), resource_snapshot: {}, active_run_id: null, pending_question: null, ...overrides }
}
function message(parts: AssistantMessage["parts"], overrides: Partial<AssistantMessage> = {}): AssistantMessage {
  return { id: "m", role: "assistant", status: "ready", version: 1, created_at: "now", updated_at: "now", run_id: "r", parts, selections: emptySelections(), ...overrides }
}
function detail(overrides: Partial<AssistantDetail> = {}): AssistantDetail {
  return { session: session(), messages: [], artifacts: [], proposals: [], executions: [], run: run(), ...overrides }
}
const question: AssistantQuestion = { id: "q", title: "这一集想走哪种悬疑？", type: "single", allow_custom: true, options: [] }
const artifact: AssistantArtifact = { id: "a1", status: "ready", version: 1, created_at: "now", updated_at: "now", title: "第一集剧本", artifact_type: "script", content: "正文", revision: 1, session_id: "s", data: {} }

describe("assistant reply notifications", () => {
  afterEach(() => { vi.unstubAllGlobals() })
  it("only wakes the user when the page is hidden or unfocused", () => {
    expect(shouldNotifyReply("hidden", true)).toBe(true)
    expect(shouldNotifyReply("visible", false)).toBe(true)
    expect(shouldNotifyReply("visible", true)).toBe(false)
  })
  it("uses the pending question as the reason to come back", () => {
    expect(assistantReplyNotification(detail({ session: session({ pending_question: question }), messages: [message([{ type: "markdown", text: "请选择方向" }])] })))
      .toEqual({ title: "智能助手在等你回答", body: "这一集想走哪种悬疑？" })
  })
  it("summarizes the latest markdown reply without code blocks or markdown noise", () => {
    const text = "## 第一集\n\n**雨夜**，[链接](https://example.com) 里出现了\n\n```js\nconst a=1\n```\n用户看到尸体。"
    expect(assistantReplyNotification(detail({ messages: [message([{ type: "markdown", text }])] })))
      .toEqual({ title: "智能助手已回复", body: "第一集 雨夜，链接 里出现了 用户看到尸体。" })
  })
  it("keeps the notification excerpt short", () => {
    expect(assistantReplyText(message([{ type: "markdown", text: "长".repeat(120) }]))).toBe(`${"长".repeat(96)}…`)
  })
  it("reports failed and interrupted runs with the error", () => {
    expect(assistantReplyNotification(detail({ run: run({ status: "failed", error: "供应商超时" }), messages: [message([], { error: "供应商超时" })] })))
      .toEqual({ title: "智能助手回复中断", body: "供应商超时" })
    expect(assistantReplyNotification(detail({ run: run({ status: "interrupted" }) })))
      .toEqual({ title: "智能助手回复中断", body: "本轮回复没有完成，打开智能助手可继续创作。" })
  })
  it("stays quiet for cancelled runs and active runs", () => {
    expect(assistantReplyNotification(detail({ run: run({ status: "cancelled" }) }))).toBeNull()
    expect(assistantReplyNotification(detail({ run: run({ status: "running" }) }))).toBeNull()
  })
  it("falls back to the generated artifact when the reply has no text", () => {
    expect(assistantReplyNotification(detail({ artifacts: [artifact], messages: [message([{ type: "artifact", artifact_id: "a1" }])] })))
      .toEqual({ title: "智能助手已回复", body: "已生成《第一集剧本》，打开助手查看并按需采纳。" })
  })
  it("still has a body when the reply is empty and has no artifact", () => {
    expect(assistantReplyNotification(detail())).toEqual({ title: "智能助手已回复", body: "回复已完成，打开智能助手查看详情。" })
  })
  it("asks for notification permission once per tab session", async () => {
    const values = new Map<string, string>()
    const requestPermission = vi.fn().mockResolvedValue("granted")
    class AskNotification {
      static permission: NotificationPermission = "default"
      static requestPermission = requestPermission
    }
    vi.stubGlobal("window", { Notification: AskNotification })
    vi.stubGlobal("Notification", AskNotification)
    vi.stubGlobal("sessionStorage", {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value) },
    })
    await expect(requestAssistantNotificationPermission()).resolves.toBe(true)
    await expect(requestAssistantNotificationPermission()).resolves.toBe(false)
    expect(requestPermission).toHaveBeenCalledTimes(1)
  })
  it("creates a notification and opens the assistant on click", () => {
    const focus = vi.fn()
    const close = vi.fn()
    let created: { title: string; options?: NotificationOptions } | null = null
    class GrantedNotification {
      static permission: NotificationPermission = "granted"
      onclick: (() => void) | null = null
      onerror: (() => void) | null = null
      close = close
      constructor(title: string, options?: NotificationOptions) { created = { title, options } }
    }
    vi.stubGlobal("window", { focus, Notification: GrantedNotification })
    vi.stubGlobal("Notification", GrantedNotification)
    const onClick = vi.fn()
    const shown = showAssistantReplyNotification({ title: "智能助手已回复", body: "镜头规划已完成。" }, onClick)
    expect(shown).toBeInstanceOf(GrantedNotification)
    expect(created).toMatchObject({ title: "智能助手已回复", options: { body: "镜头规划已完成。", tag: "director-assistant-reply", lang: "zh-CN" } })
    ;(shown as unknown as GrantedNotification).onclick?.()
    expect(focus).toHaveBeenCalled()
    expect(onClick).toHaveBeenCalled()
    expect(close).toHaveBeenCalled()
  })
  it("does not create notifications when the browser blocked them", () => {
    class DeniedNotification {
      static permission: NotificationPermission = "denied"
    }
    vi.stubGlobal("window", { Notification: DeniedNotification })
    vi.stubGlobal("Notification", DeniedNotification)
    expect(showAssistantReplyNotification({ title: "智能助手已回复", body: "完成" })).toBeNull()
  })
})
