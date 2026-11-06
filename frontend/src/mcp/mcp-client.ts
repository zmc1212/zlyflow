export type McpClient = "codex" | "chatgpt" | "claude" | "cursor" | "generic"

export type McpClientGuide = {
  label: string
  step1: { title: string; desc: string; config: "command" | "json" | "instruction"; copyLabel: string }
  step2: { title: string; desc: string; action?: { label: string; kind: "copy-prompt" | "link"; url?: string } }
}

export const CLIENT_ORDER: McpClient[] = ["codex", "chatgpt", "claude", "cursor", "generic"]

export const CLIENT_GUIDES: Record<McpClient, McpClientGuide> = {
  codex: {
    label: "Codex CLI",
    step1: { title: "安装工作台连接器", desc: "在终端依次执行以下命令，浏览器会打开工作台登录与授权页面。未安装 Codex 客户端请先安装。", config: "command", copyLabel: "复制命令" },
    step2: { title: "开始创作", desc: "授权完成后，回到 Codex 发送创作或剪辑指令，工作台会处理生成任务和剪辑方案，AI 可以继续查询进度。", action: { label: "复制创作指令", kind: "copy-prompt" } },
  },
  chatgpt: {
    label: "ChatGPT",
    step1: { title: "将工作台 MCP 添加到 ChatGPT", desc: "在 ChatGPT 插件目录或自定义 MCP 中添加以下配置。添加后按提示完成 OAuth 登录。", config: "json", copyLabel: "复制 MCP 配置" },
    step2: { title: "连接并开始创作", desc: "授权完成后，让 ChatGPT 用 ZLY AI Studio 生成图片或视频。", action: { label: "开始创作", kind: "copy-prompt" } },
  },
  claude: {
    label: "Claude",
    step1: { title: "复制工作台 connector 配置", desc: "下一步粘贴到 Claude，添加后按提示完成 OAuth 登录，无需填写 API Token。", config: "json", copyLabel: "复制 MCP 配置" },
    step2: { title: "前往 Claude → Customize", desc: "在 Claude desktop 或 claude.ai，进入 Customize → Connectors。命名为 ZLY AI Studio 并粘贴配置。", action: { label: "打开 Claude Customize", kind: "link", url: "https://claude.ai/customize/connectors" } },
  },
  cursor: {
    label: "Cursor",
    step1: { title: "将工作台 MCP 添加到 Cursor", desc: "在 Cursor Settings → MCP 中添加，或把配置写入 .cursor/mcp.json。添加后按提示完成 OAuth 登录。", config: "json", copyLabel: "复制 MCP 配置" },
    step2: { title: "连接并开始创作", desc: "授权完成后，让 Cursor 用 ZLY AI Studio 生成图片或视频。", action: { label: "开始创作", kind: "copy-prompt" } },
  },
  generic: {
    label: "通用 Agent",
    step1: { title: "复制安装指令，发送给你的 Agent", desc: "把下方指令整段发给任意支持 MCP 的 Agent（本列表之外的自研或第三方客户端都适用），指令里已带上工作台 MCP 配置。", config: "instruction", copyLabel: "复制安装指令" },
    step2: { title: "让 Agent 完成安装与授权", desc: "Agent 会写入本地 MCP 配置并重载，随后打开浏览器完成 ZLY AI Studio OAuth 授权。授权完成后直接让它生成图片或视频即可。" },
  },
}

export type McpInfo = {
  enabled: boolean; configured: boolean; message: string | null; url: string | null
  transport: string; authorization: string; scopes: Record<string, string>
}
export type McpConnection = {
  id: string; client_name: string; scopes: string[]; created_at: number
  last_used_at: number | null; expires_at: number; status: "active" | "revoked" | "expired"
}
export type AuthorizationRequest = {
  request_id: string; client_name: string; account: string; redirect_uri: string
  scopes: { id: string; label: string }[]; expires_at: number
}

export function mcpServersConfig(url: string) {
  return JSON.stringify({ mcpServers: { "zly-ai-studio": { type: "http", url } } }, null, 2)
}

export function connectionConfig(client: McpClient, url: string) {
  if (client === "codex") return `codex mcp add zly-ai-studio --url "${url}"\ncodex mcp login zly-ai-studio`
  if (client === "generic") return [
    "请帮我安装 ZLY AI Studio 的 MCP，装好后用它生成图片或视频。",
    "",
    "把下面的配置合并进你本地的 MCP 设置（JSON 里的 mcpServers 段），不要覆盖其它已有服务：",
    "```json",
    mcpServersConfig(url),
    "```",
    "",
    "该服务使用 Streamable HTTP 传输与 OAuth 2.1 浏览器登录授权，无需填写 API Token。",
  ].join("\n")
  return mcpServersConfig(url)
}

