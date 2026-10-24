export type McpClient = "codex" | "cursor" | "generic"

export type McpInfo = {
  enabled: boolean; configured: boolean; message: string | null; url: string | null
  transport: string; authorization: string; scopes: Record<string, string>
}
export type McpConnection = {
  id: string; client_name: string; scopes: string[]; created_at: number
  last_used_at: number | null; expires_at: number; status: "active" | "revoked" | "expired"
}
export type McpReference = {
  id: string; name: string; width: number; height: number; size: number
  mime_type: string; created_at: number; preview_url: string
}
export type GeneratedImage = { job_id: string; generation_item_id: string; output_index: number; label: string; preview_url: string }
export type AuthorizationRequest = {
  request_id: string; client_name: string; account: string; redirect_uri: string
  scopes: { id: string; label: string }[]; expires_at: number
}

export function connectionConfig(client: McpClient, url: string) {
  if (client === "codex") return `codex mcp add zly-ai-studio --url "${url}"\ncodex mcp login zly-ai-studio`
  if (client === "cursor") return JSON.stringify({ mcpServers: { "zly-ai-studio": { url } } }, null, 2)
  return `服务地址：${url}\n传输方式：Streamable HTTP\n认证方式：OAuth 2.1（浏览器登录授权）`
}

export function referenceInstruction(references: Pick<McpReference, "id">[]) {
  return references.map((reference, index) => `<Picture ${index + 1}>：${reference.id}`).join("\n")
}

export function moveReference(ids: string[], index: number, direction: -1 | 1) {
  const target = index + direction
  if (index < 0 || target < 0 || index >= ids.length || target >= ids.length) return ids
  const next = [...ids]
  ;[next[index], next[target]] = [next[target], next[index]]
  return next
}
