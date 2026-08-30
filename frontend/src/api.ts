export type UserRole = "super_admin" | "admin" | "employee"

export type User = {
  id: string
  username: string
  display_name: string
  role: UserRole
  is_active: boolean
  must_change_password: boolean
  created_at: string
  updated_at: string
  last_login_at?: string | null
}

export type AuthStatus = {
  setup_required: boolean
  authenticated: boolean
  user?: User | null
  csrf_token?: string | null
}

type ValidationIssue = {
  loc?: unknown[]
  msg?: unknown
  type?: string
  ctx?: Record<string, unknown>
}

const fieldLabels: Record<string, string> = {
  username: "账号",
  display_name: "姓名",
  password: "密码",
  current_password: "当前密码",
  new_password: "新密码",
  role: "角色",
  prompt: "提示词",
  references: "参考图",
}

function validationIssueMessage(issue: ValidationIssue): string {
  const field = String(issue.loc?.[issue.loc.length - 1] ?? "")
  const label = fieldLabels[field] ?? "提交内容"
  const limit = issue.ctx?.min_length ?? issue.ctx?.max_length

  if (issue.type === "missing") return `请填写${label}`
  if (issue.type === "string_too_short") return `${label}至少需要 ${limit ?? "规定数量的"} 个字符`
  if (issue.type === "string_too_long") return `${label}不能超过 ${limit ?? "规定数量的"} 个字符`
  if (issue.type === "string_pattern_mismatch" && field === "username") {
    return "账号只能包含字母、数字、点、下划线和连字符"
  }
  if (typeof issue.msg === "string" && /[\u4e00-\u9fff]/.test(issue.msg)) return issue.msg
  return `${label}格式不正确`
}

export function apiErrorMessage(body: unknown, fallback = "请求失败"): string {
  if (typeof body === "string") return body.trim() || fallback
  if (!body || typeof body !== "object") return fallback

  const detail = (body as { detail?: unknown }).detail
  if (typeof detail === "string") return detail.trim() || fallback
  if (Array.isArray(detail)) {
    const messages = detail
      .filter((issue): issue is ValidationIssue => Boolean(issue) && typeof issue === "object")
      .map(validationIssueMessage)
    return [...new Set(messages)].join("；") || fallback
  }
  if (detail && typeof detail === "object") {
    const message = (detail as { message?: unknown }).message
    if (typeof message === "string") return message.trim() || fallback
  }
  return fallback
}

export class ApiRequestError extends Error {
  status: number
  body: unknown

  constructor(status: number, body: unknown, fallback = "请求失败") {
    super(apiErrorMessage(body, fallback))
    this.name = "ApiRequestError"
    this.status = status
    this.body = body
  }
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    const contentType = response.headers.get("content-type") ?? ""
    if (contentType.includes("application/json")) {
      const body = await response.json().catch(() => null)
      throw new ApiRequestError(response.status, body)
    }
    const text = await response.text().catch(() => "")
    throw new ApiRequestError(response.status, text.trim() || `请求失败（HTTP ${response.status}）`)
  }
  if (!(response.headers.get("content-type") ?? "").includes("application/json")) {
    throw new Error("服务端返回了非 JSON 响应，请确认工作台后端已启动")
  }
  return response.json() as Promise<T>
}


export function jsonMutation(csrfToken: string, body?: unknown, method = "POST"): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: body === undefined ? undefined : JSON.stringify(body),
  }
}
