import { useMutation, useQuery } from "@tanstack/react-query"
import { Alert, Button, Spin } from "antd"
import { ArrowLeft, Check, Link2, ShieldCheck } from "lucide-react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { jsonMutation, requestJson, type User } from "../api"
import ThemeToggle from "../components/ThemeToggle"
import type { AuthorizationRequest } from "./mcp-client"
import "./mcp.css"

export default function McpAuthorizePage({ user, csrfToken }: { user: User; csrfToken: string }) {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const requestId = params.get("request_id") || ""
  const details = useQuery({ queryKey: ["mcp-authorization", user.id, requestId], queryFn: () => requestJson<AuthorizationRequest>("/api/mcp/authorization-requests/" + encodeURIComponent(requestId)), enabled: Boolean(requestId), retry: false })
  const decision = useMutation({ mutationFn: (allow: boolean) => requestJson<{ redirect_url: string }>("/api/mcp/authorization-requests/" + encodeURIComponent(requestId), jsonMutation(csrfToken, { allow })), onSuccess: (result) => window.location.assign(result.redirect_url) })
  return <div className="mcp-page mcp-authorization-page"><div className="mcp-authorization-toolbar"><Button type="text" icon={<ArrowLeft size={16} />} onClick={() => navigate("/mcp")}>MCP 连接</Button><ThemeToggle /></div>
    <main className="mcp-authorization"><div className="mcp-authorization-symbol"><Link2 size={28} /></div><span className="mcp-eyebrow">ZLY AI Studio</span><h1>连接你的创作工作台</h1>
      {details.isLoading ? <div className="mcp-loading"><Spin /></div> : details.data ? <><p><strong>{details.data.client_name}</strong> 请求使用你的工作台创作能力。</p><div className="mcp-authorizing-account"><ShieldCheck size={18} /><div><span>正在授权的账号</span><strong>{user.display_name} <span>（{user.username}）</span></strong></div></div>
        <h2>允许此客户端</h2><ul className="mcp-permissions">{details.data.scopes.map((scope) => <li key={scope.id}><Check size={17} /><span>{scope.label}</span></li>)}</ul><p className="mcp-authorization-note">生成会使用工作台当前配置的 AI 服务。你可以在「MCP 连接」页面随时撤销授权。</p>
        {decision.isError ? <Alert type="error" showIcon title="授权未完成" description={decision.error.message} /> : null}
        <div className="mcp-authorization-buttons"><Button size="large" disabled={decision.isPending} onClick={() => decision.mutate(false)}>拒绝</Button><Button type="primary" size="large" loading={decision.isPending && decision.variables === true} disabled={decision.isPending && decision.variables === false} onClick={() => decision.mutate(true)}>允许并连接</Button></div>
      </> : <><Alert type="error" showIcon title="无法继续授权" description={details.error?.message || "缺少授权请求，请从 Codex 或 Cursor 重新发起连接。"} /><Button onClick={() => navigate("/mcp")}>返回连接页</Button></>}
    </main>
  </div>
}
