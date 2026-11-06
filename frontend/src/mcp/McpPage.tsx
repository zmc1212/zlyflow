import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, Button, Empty, message, Popconfirm, Table, Tag, Tooltip } from "antd"
import { ArrowLeft, ArrowRight, Check, Copy, ExternalLink, Link2, Plus, RefreshCw, ShieldCheck, Terminal } from "lucide-react"
import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { requestJson, type User } from "../api"
import ThemeToggle from "../components/ThemeToggle"
import { PATHS } from "../paths"
import { CLIENT_LOGOS } from "./client-logos"
import { CLIENT_GUIDES, CLIENT_ORDER, connectionConfig, type McpClient, type McpConnection, type McpInfo } from "./mcp-client"
import "./mcp.css"

const EXAMPLES = [
  { title: "一句话生成视频", text: "请使用 ZLY AI Studio，先查询可用视频工作流，再生成一段电影感视频：橘猫趴在午后窗台，阳光洒在毛发上，镜头缓慢推进。提交后告诉我任务链接，并帮我查看生成结果。" },
  { title: "用参考图创作", text: "请使用 ZLY AI Studio，列出我的参考图并按我指定的顺序使用。先查询图生视频工作流和创作参数，确认参考图对应关系后生成视频。" },
  { title: "查看创作进度", text: "请使用 ZLY AI Studio，查看我最近的图片和视频任务，告诉我哪些已经完成，并返回可下载的成功结果。" },
  { title: "自动剪辑与字幕", text: "请使用 ZLY AI Studio，列出我的导演工程和分集，打开指定分集的剪辑时间线。先智能铺轨，再生成自动字幕；把预览清单和字幕数量告诉我，等我确认后再写入时间线。" },
]
const SCOPE_LABELS: Record<string, string> = { "studio:read": "读取", "studio:generate": "创作", "studio:edit": "剪辑" }
const formatTime = (value: number | null) => value ? new Date(value * 1000).toLocaleString("zh-CN", { hour12: false }) : "尚未调用"

async function copy(text: string, label = "已复制") {
  try { await navigator.clipboard.writeText(text); message.success(label) }
  catch { message.error("复制失败，请选中文字手动复制") }
}

export default function McpPage({ user, csrfToken, onLogout, logoutPending }: {
  user: User; csrfToken: string; onLogout: () => void; logoutPending: boolean
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [client, setClient] = useState<McpClient>("codex")
  const info = useQuery({ queryKey: ["mcp-info", user.id], queryFn: () => requestJson<McpInfo>("/api/mcp/info") })
  const connections = useQuery({ queryKey: ["mcp-connections", user.id], queryFn: () => requestJson<McpConnection[]>("/api/mcp/connections"), refetchInterval: 15000, refetchOnWindowFocus: true })
  const revoke = useMutation({
    mutationFn: (id: string) => requestJson("/api/mcp/connections/" + encodeURIComponent(id), { method: "DELETE", headers: { "X-CSRF-Token": csrfToken } }),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["mcp-connections", user.id] }); message.success("授权已撤销") },
    onError: (error) => message.error(error.message),
  })
  const url = info.data?.url
  const config = connectionConfig(client, url || "https://你的工作台域名/api/mcp")
  const activeCount = connections.data?.filter((item) => item.status === "active").length ?? 0

  return <div className="mcp-page">
    <header className="mcp-header">
      <div className="mcp-header-title"><Button type="text" icon={<ArrowLeft size={18} />} onClick={() => navigate(PATHS.generateVideo)} aria-label="返回创作工作台" /><Link2 size={20} /><strong>MCP 连接</strong><span>ZLY AI Studio</span></div>
      <div className="mcp-header-actions"><span>{user.display_name}</span><ThemeToggle /><Button type="text" onClick={onLogout} loading={logoutPending}>退出登录</Button></div>
    </header>
    <main className="mcp-main">
      <div className="mcp-intro"><span className="mcp-eyebrow">连接你的 AI 助手</span><h1>在对话里，把创意变成作品。</h1><p>连接 ChatGPT、Claude、Cursor、Codex 等 AI 客户端，使用工作台的图片、视频能力，并在导演台智能剪辑里完成铺轨、字幕和成片剪辑。</p></div>
      {info.isError ? <Alert type="error" showIcon title="读取连接配置失败" description={info.error.message} action={<Button onClick={() => void info.refetch()}>重试</Button>} /> : null}
      {info.data && !info.data.configured ? <Alert type="warning" showIcon title={info.data.enabled ? "MCP 等待管理员配置" : "MCP 连接已关闭"} description={info.data.message} /> : null}
      <div className="mcp-address"><div><Link2 size={17} /><span>服务地址</span><code>{url || (info.isLoading ? "正在读取…" : "尚未配置对外服务地址")}</code></div><div><Tag color={url ? "success" : "default"}>{url ? "OAuth 2.1" : "待配置"}</Tag><Button icon={<Copy size={15} />} disabled={!url} onClick={() => void copy(url!)}>复制地址</Button></div></div>

      <section className="mcp-connect" aria-label="客户端接入引导">
        <div className="mcp-clients" role="tablist" aria-label="AI 客户端">
          {CLIENT_ORDER.map((key) => { const Logo = CLIENT_LOGOS[key]; return <button key={key} type="button" role="tab" aria-selected={client === key} className={`mcp-client-chip${client === key ? " is-active" : ""}`} onClick={() => setClient(key)}><Logo size={15} /><span>{CLIENT_GUIDES[key].label}</span></button> })}
        </div>
        {(() => {
          const guide = CLIENT_GUIDES[client]
          const action = guide.step2.action
          return <div className="mcp-steps">
            <div className="mcp-step"><span className="mcp-step-number">1</span><h2>{guide.step1.title}</h2>
              <p>{guide.step1.desc}</p>
              <div className="mcp-code"><pre>{config}</pre><Tooltip title="复制连接配置"><Button type="text" icon={<Copy size={15} />} aria-label="复制连接配置" disabled={!url} onClick={() => void copy(config)} /></Tooltip></div>
              <div className="mcp-step-actions"><Button type="primary" icon={<Copy size={15} />} disabled={!url} onClick={() => void copy(config, `${guide.step1.copyLabel}成功，可粘贴到客户端`)}>{guide.step1.copyLabel}</Button></div>
              <div className="mcp-step-note"><ShieldCheck size={15} />使用你的工作台账号授权，仅访问自己的任务、参考图与剪辑时间线。</div>
            </div>
            <div className="mcp-step"><span className="mcp-step-number">2</span><h2>{guide.step2.title}</h2><p>{guide.step2.desc}</p>
              {action?.kind === "copy-prompt" ? <><div className="mcp-prompt">{EXAMPLES[0].text}</div><Button type="primary" icon={<Copy size={15} />} onClick={() => void copy(EXAMPLES[0].text, "创作指令已复制，可粘贴到 AI 客户端")}>{action.label}</Button></> : null}
              {action?.kind === "link" ? <Button type="primary" icon={<ExternalLink size={15} />} onClick={() => window.open(action.url, "_blank", "noopener,noreferrer")}>{action.label}</Button> : null}
            </div>
          </div>
        })()}
        <div className="mcp-examples">{EXAMPLES.map((example) => <Button key={example.title} type="text" icon={<Plus size={14} />} onClick={() => void copy(example.text)}>{example.title}<ArrowRight size={14} /></Button>)}</div>
      </section>

      <section className="mcp-section" aria-labelledby="mcp-connections-title"><div className="mcp-section-heading"><div><h2 id="mcp-connections-title">已授权连接 <span className="mcp-count">{activeCount}</span></h2><p>授权后持续有效，可随时撤销。最近调用时间来自真实请求。</p></div><Button icon={<RefreshCw size={14} />} onClick={() => void connections.refetch()} loading={connections.isFetching}>刷新</Button></div>
        {connections.isError ? <Alert type="error" showIcon title={connections.error.message} /> : null}
        <Table<McpConnection> rowKey="id" dataSource={connections.data ?? []} loading={connections.isLoading} pagination={{ pageSize: 6, hideOnSinglePage: true }} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无授权连接，完成客户端登录后会显示在这里" /> }} columns={[
          { title: "客户端", dataIndex: "client_name", render: (value: string) => <span className="mcp-client-name"><Terminal size={15} />{value}</span> },
          { title: "状态", dataIndex: "status", width: 104, render: (status: McpConnection["status"]) => <Tag color={status === "active" ? "success" : "default"} icon={status === "active" ? <Check size={12} /> : undefined}>{({ active: "已授权", revoked: "已撤销", expired: "已过期" })[status]}</Tag> },
          { title: "授权范围", dataIndex: "scopes", render: (scopes: string[]) => scopes.map((scope) => SCOPE_LABELS[scope] ?? scope).join(" · ") },
          { title: "授权时间", dataIndex: "created_at", render: formatTime }, { title: "最近调用", dataIndex: "last_used_at", render: formatTime },
          { title: "操作", width: 100, render: (_, item) => <Popconfirm title="撤销此客户端的授权？" description="撤销后需在客户端重新登录授权。" okText="撤销授权" cancelText="保留" onConfirm={() => revoke.mutateAsync(item.id)}><Button type="text" danger disabled={item.status !== "active"} loading={revoke.isPending && revoke.variables === item.id}>撤销</Button></Popconfirm> },
        ]} />
      </section>
    </main>
  </div>
}
