import type { AssistantDetail, AssistantMessage } from "./api"

const ASKED_KEY = "director-assistant-notification-asked"
const NOTIFICATION_TAG = "director-assistant-reply"

export type AssistantNotification = { title: string; body: string }

function notificationSupported() {
  return typeof window !== "undefined" && "Notification" in window
}

let permissionRequest: Promise<boolean> | null = null

export function requestAssistantNotificationPermission(): Promise<boolean> {
  if (!notificationSupported()) return Promise.resolve(false)
  if (Notification.permission === "granted") return Promise.resolve(true)
  if (Notification.permission === "denied") return Promise.resolve(false)
  try {
    if (sessionStorage.getItem(ASKED_KEY)) return Promise.resolve(false)
    sessionStorage.setItem(ASKED_KEY, "1")
  } catch {
    // Storage can be unavailable; the browser still coalesces duplicate prompts.
  }
  if (!permissionRequest) {
    try {
      permissionRequest = Promise.resolve(Notification.requestPermission())
        .then(value => value === "granted")
        .catch(() => false)
        .finally(() => { permissionRequest = null })
    } catch {
      return Promise.resolve(false)
    }
  }
  return permissionRequest
}

export function shouldNotifyReply(visibility: DocumentVisibilityState, focused: boolean) {
  return visibility === "hidden" || !focused
}

export function assistantReplyText(message: AssistantMessage | undefined) {
  const text = (message?.parts || []).flatMap(part => part.type === "markdown" ? [part.text] : []).join("\n")
  return plainExcerpt(text)
}

function plainExcerpt(text: string) {
  const plain = String(text || "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/<[^>]+>/g, " ")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s{0,3}>\s?/gm, "")
    .replace(/^\s*(?:[-+*]|\d+[.)])\s+/gm, "")
    .replace(/[*_~]/g, "")
    .replace(/\s+/g, " ")
    .trim()
  return plain.length > 96 ? `${plain.slice(0, 96)}…` : plain
}

export function assistantReplyNotification(detail: AssistantDetail): AssistantNotification | null {
  const run = detail.run
  if (run?.status === "cancelled") return null
  if (run && (run.status === "queued" || run.status === "running")) return null
  const assistant = (run ? detail.messages.find(message => message.id === run.message_id) : undefined)
    || [...detail.messages].reverse().find(message => message.role === "assistant")
  if (run && (run.status === "failed" || run.status === "interrupted")) {
    return {
      title: "智能助手回复中断",
      body: plainExcerpt(assistant?.error || run.error || "") || "本轮回复没有完成，打开智能助手可继续创作。",
    }
  }
  const question = detail.session.pending_question?.title?.trim()
  if (question) return { title: "智能助手在等你回答", body: question }
  const text = assistantReplyText(assistant)
  if (text) return { title: "智能助手已回复", body: text }
  const artifactPart = assistant?.parts.find(part => part.type === "artifact")
  const artifact = artifactPart ? detail.artifacts.find(item => item.id === artifactPart.artifact_id) : undefined
  return { title: "智能助手已回复", body: artifact ? `已生成《${artifact.title}》，打开助手查看并按需采纳。` : "回复已完成，打开智能助手查看详情。" }
}

export function showAssistantReplyNotification(content: AssistantNotification, onClick?: () => void): Notification | null {
  if (!notificationSupported() || Notification.permission !== "granted") return null
  try {
    const notification = new Notification(content.title, {
      body: content.body,
      tag: NOTIFICATION_TAG,
      lang: "zh-CN",
    })
    notification.onclick = () => {
      try { window.focus() } catch { /* Focus is best effort. */ }
      onClick?.()
      notification.close()
    }
    notification.onerror = () => notification.close()
    return notification
  } catch {
    // Some mobile browsers only allow notifications through a service worker.
    return null
  }
}
