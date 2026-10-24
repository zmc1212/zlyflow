import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Alert, Button, Checkbox, Empty, Image, message, Modal, Pagination, Popconfirm, Spin, Table, Tabs, Tag, Tooltip } from "antd"
import { ArrowLeft, ArrowRight, Check, ChevronLeft, ChevronRight, Copy, ImagePlus, Link2, Plus, RefreshCw, ShieldCheck, Terminal, Trash2 } from "lucide-react"
import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { jsonMutation, requestJson, type User } from "../api"
import ThemeToggle from "../components/ThemeToggle"
import { PATHS } from "../paths"
import { connectionConfig, moveReference, referenceInstruction, type GeneratedImage, type McpClient, type McpConnection, type McpInfo, type McpReference } from "./mcp-client"
import "./mcp.css"

const EXAMPLES = [
  { title: "一句话生成视频", text: "请使用 ZLY AI Studio，先查询可用视频工作流，再生成一段电影感视频：橘猫趴在午后窗台，阳光洒在毛发上，镜头缓慢推进。提交后告诉我任务链接，并帮我查看生成结果。" },
  { title: "用参考图创作", text: "请使用 ZLY AI Studio，列出我的参考图并按我指定的顺序使用。先查询图生视频工作流和创作参数，确认参考图对应关系后生成视频。" },
  { title: "查看创作进度", text: "请使用 ZLY AI Studio，查看我最近的图片和视频任务，告诉我哪些已经完成，并返回可下载的成功结果。" },
  { title: "自动剪辑与字幕", text: "请使用 ZLY AI Studio，列出我的导演工程和分集，打开指定分集的剪辑时间线。先智能铺轨，再生成自动字幕；把预览清单和字幕数量告诉我，等我确认后再写入时间线。" },
]
const SCOPE_LABELS: Record<string, string> = { "studio:read": "读取", "studio:generate": "创作", "studio:edit": "剪辑" }
const formatTime = (value: number | null) => value ? new Date(value * 1000).toLocaleString("zh-CN", { hour12: false }) : "尚未调用"
const formatSize = (bytes: number) => bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`

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
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [galleryOpen, setGalleryOpen] = useState(false)
  const [galleryPage, setGalleryPage] = useState(1)
  const [chosenImage, setChosenImage] = useState<GeneratedImage | null>(null)
  const info = useQuery({ queryKey: ["mcp-info", user.id], queryFn: () => requestJson<McpInfo>("/api/mcp/info") })
  const connections = useQuery({ queryKey: ["mcp-connections", user.id], queryFn: () => requestJson<McpConnection[]>("/api/mcp/connections"), refetchInterval: 15000, refetchOnWindowFocus: true })
  const references = useQuery({ queryKey: ["mcp-references", user.id], queryFn: () => requestJson<McpReference[]>("/api/mcp/references") })
  const images = useQuery({ queryKey: ["mcp-generated-images", user.id], queryFn: () => requestJson<GeneratedImage[]>("/api/mcp/generated-images"), enabled: galleryOpen })
  const invalidateReferences = () => queryClient.invalidateQueries({ queryKey: ["mcp-references", user.id] })
  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData(); form.append("file", file)
      return requestJson<McpReference>("/api/mcp/references", { method: "POST", headers: { "X-CSRF-Token": csrfToken }, body: form })
    },
    onSuccess: (asset) => { void invalidateReferences(); setSelectedIds((ids) => [...ids, asset.id]); message.success("参考图已上传") },
    onError: (error) => message.error(error.message),
  })
  const remove = useMutation({
    mutationFn: (id: string) => requestJson("/api/mcp/references/" + encodeURIComponent(id), { method: "DELETE", headers: { "X-CSRF-Token": csrfToken } }),
    onSuccess: (_, id) => { setSelectedIds((ids) => ids.filter((value) => value !== id)); void invalidateReferences(); message.success("参考图已删除") },
    onError: (error) => message.error(error.message),
  })
  const revoke = useMutation({
    mutationFn: (id: string) => requestJson("/api/mcp/connections/" + encodeURIComponent(id), { method: "DELETE", headers: { "X-CSRF-Token": csrfToken } }),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["mcp-connections", user.id] }); message.success("授权已撤销") },
    onError: (error) => message.error(error.message),
  })
  const importImage = useMutation({
    mutationFn: (image: GeneratedImage) => requestJson<McpReference>("/api/mcp/references/from-output", jsonMutation(csrfToken, { job_id: image.job_id, generation_item_id: image.generation_item_id, output_index: image.output_index })),
    onSuccess: (asset) => { void invalidateReferences(); setSelectedIds((ids) => [...ids, asset.id]); setGalleryOpen(false); setChosenImage(null); message.success("已添加到参考图") },
    onError: (error) => message.error(error.message),
  })
  const url = info.data?.url
  const config = connectionConfig(client, url || "https://你的工作台域名/api/mcp")
  const selected = selectedIds.map((id) => references.data?.find((asset) => asset.id === id)).filter((asset): asset is McpReference => Boolean(asset))
  const activeCount = connections.data?.filter((item) => item.status === "active").length ?? 0

  return <div className="mcp-page">
    <header className="mcp-header">
      <div className="mcp-header-title"><Button type="text" icon={<ArrowLeft size={18} />} onClick={() => navigate(PATHS.generateVideo)} aria-label="返回创作工作台" /><Link2 size={20} /><strong>MCP 连接</strong><span>ZLY AI Studio</span></div>
      <div className="mcp-header-actions"><span>{user.display_name}</span><ThemeToggle /><Button type="text" onClick={onLogout} loading={logoutPending}>退出登录</Button></div>
    </header>
    <main className="mcp-main">
      <div className="mcp-intro"><span className="mcp-eyebrow">连接你的 AI 助手</span><h1>在对话里，把创意变成作品。</h1><p>连接 Codex 或 Cursor，使用工作台的图片、视频能力，并在导演台智能剪辑里完成铺轨、字幕和成片剪辑。</p></div>
      {info.isError ? <Alert type="error" showIcon title="读取连接配置失败" description={info.error.message} action={<Button onClick={() => void info.refetch()}>重试</Button>} /> : null}
      {info.data && !info.data.configured ? <Alert type="warning" showIcon title={info.data.enabled ? "MCP 等待管理员配置" : "MCP 连接已关闭"} description={info.data.message} /> : null}
      <div className="mcp-address"><div><Link2 size={17} /><span>服务地址</span><code>{url || (info.isLoading ? "正在读取…" : "尚未配置对外服务地址")}</code></div><div><Tag color={url ? "success" : "default"}>{url ? "OAuth 2.1" : "待配置"}</Tag><Button icon={<Copy size={15} />} disabled={!url} onClick={() => void copy(url!)}>复制地址</Button></div></div>

      <section className="mcp-connect" aria-label="客户端接入引导">
        <Tabs activeKey={client} onChange={(key) => setClient(key as McpClient)} items={[
          { key: "codex", label: <span className="mcp-tab"><Terminal size={16} />Codex</span> },
          { key: "cursor", label: "Cursor" }, { key: "generic", label: "通用客户端" },
        ]} />
        <div className="mcp-steps">
          <div className="mcp-step"><span className="mcp-step-number">1</span><h2>连接工作台</h2>
            <p>{client === "codex" ? "在终端依次执行以下命令，浏览器会打开工作台登录与授权页面。" : client === "cursor" ? "将配置添加到个人 ~/.cursor/mcp.json，保存后在客户端的 MCP 设置中连接并登录。" : "在支持 Streamable HTTP 与 OAuth 的 MCP 客户端中添加以下配置，并完成浏览器授权。"}</p>
            <div className="mcp-code"><pre>{config}</pre><Tooltip title="复制连接配置"><Button type="text" icon={<Copy size={15} />} aria-label="复制连接配置" disabled={!url} onClick={() => void copy(config)} /></Tooltip></div>
            <div className="mcp-step-note"><ShieldCheck size={15} />使用你的工作台账号授权，仅访问自己的任务、参考图与剪辑时间线。</div>
          </div>
          <div className="mcp-step"><span className="mcp-step-number">2</span><h2>开始创作</h2><p>授权完成后，回到 AI 客户端发送创作或剪辑指令。工作台会处理生成任务和剪辑方案，AI 可以继续查询进度。</p>
            <div className="mcp-prompt">{EXAMPLES[0].text}</div><Button type="primary" icon={<Copy size={15} />} onClick={() => void copy(EXAMPLES[0].text, "创作指令已复制，可粘贴到 AI 客户端")}>复制创作指令</Button>
          </div>
        </div>
        <div className="mcp-examples">{EXAMPLES.map((example) => <Button key={example.title} type="text" icon={<Plus size={14} />} onClick={() => void copy(example.text)}>{example.title}<ArrowRight size={14} /></Button>)}</div>
      </section>

      <section className="mcp-section" aria-labelledby="mcp-references-title">
        <div className="mcp-section-heading"><div><h2 id="mcp-references-title">参考图</h2><p>选中图片后按顺序引用，<code>&lt;Picture n&gt;</code> 与下方顺序对应。</p></div><div className="mcp-section-actions">
          <Button icon={<ImagePlus size={15} />} onClick={() => { setGalleryOpen(true); setGalleryPage(1) }}>从我的作品选择</Button>
          <label className="mcp-upload-label"><Button type="primary" icon={<Plus size={16} />} loading={upload.isPending} onClick={() => document.getElementById("mcp-reference-input")?.click()}>上传参考图</Button><input id="mcp-reference-input" type="file" accept="image/png,image/jpeg,image/webp" multiple hidden onChange={(event) => { for (const file of Array.from(event.target.files ?? [])) upload.mutate(file); event.target.value = "" }} /></label>
        </div></div>
        {references.isError ? <Alert type="error" showIcon title={references.error.message} action={<Button onClick={() => void references.refetch()}>重试</Button>} /> : null}
        {selected.length ? <div className="mcp-reference-order"><div>{selected.map((asset, index) => <Tag key={asset.id} className="mcp-order-tag"><span>&lt;Picture {index + 1}&gt; {asset.name}</span><Button type="text" size="small" icon={<ChevronLeft size={12} />} disabled={index === 0} aria-label={`将参考图 ${index + 1} 前移`} onClick={() => setSelectedIds(moveReference(selectedIds, index, -1))} /><Button type="text" size="small" icon={<ChevronRight size={12} />} disabled={index === selected.length - 1} aria-label={`将参考图 ${index + 1} 后移`} onClick={() => setSelectedIds(moveReference(selectedIds, index, 1))} /></Tag>)}</div><Button icon={<Copy size={14} />} onClick={() => void copy("请按以下顺序使用参考图：\n" + referenceInstruction(selected))}>复制引用顺序</Button></div> : null}
        {references.isLoading ? <div className="mcp-loading"><Spin /></div> : references.data?.length ? <div className="mcp-reference-grid"><Image.PreviewGroup>{references.data.map((asset) => <article className={`mcp-reference${selectedIds.includes(asset.id) ? " is-selected" : ""}`} key={asset.id}>
          <Image src={asset.preview_url} alt={asset.name} width="100%" height={136} style={{ objectFit: "cover" }} />
          <div className="mcp-reference-meta"><Checkbox checked={selectedIds.includes(asset.id)} onChange={(event) => setSelectedIds((ids) => event.target.checked ? [...ids, asset.id] : ids.filter((id) => id !== asset.id))}><Tooltip title={asset.name}><span>{asset.name}</span></Tooltip></Checkbox><Popconfirm title="删除此参考图？" description="已提交任务中的参考图会保留。" onConfirm={() => remove.mutateAsync(asset.id)} okText="删除" cancelText="保留"><Button size="small" type="text" danger icon={<Trash2 size={14} />} aria-label={`删除参考图 ${asset.name}`} loading={remove.isPending && remove.variables === asset.id} /></Popconfirm></div>
          <div className="mcp-reference-id"><code>{asset.id}</code><Tooltip title="复制素材 ID"><Button type="text" size="small" icon={<Copy size={13} />} aria-label={`复制 ${asset.name} 的素材 ID`} onClick={() => void copy(asset.id)} /></Tooltip></div><span className="mcp-reference-size">{asset.width} × {asset.height} · {formatSize(asset.size)}</span>
        </article>)}</Image.PreviewGroup></div> : !references.isError ? <div className="mcp-empty"><ImagePlus size={28} /><strong>给 AI 一些画面参考</strong><span>上传 PNG、JPEG 或 WebP，单张最多 50 MB，也可以从自己的生成图片中选取。</span></div> : null}
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
    <Modal open={galleryOpen} title="从我的生成图片选择" width={880} onCancel={() => setGalleryOpen(false)} okText="添加为参考图" cancelText="取消" okButtonProps={{ disabled: !chosenImage }} confirmLoading={importImage.isPending} onOk={() => { if (chosenImage) importImage.mutate(chosenImage) }}>
      {images.isLoading ? <div className="mcp-loading"><Spin /></div> : images.isError ? <Alert type="error" title={images.error.message} /> : !images.data?.length ? <Empty description="暂无可用的生成图片" /> : <><div className="mcp-gallery">{images.data.slice((galleryPage - 1) * 12, galleryPage * 12).map((image) => <button key={image.generation_item_id + ":" + image.output_index} type="button" className={`mcp-gallery-image${chosenImage?.generation_item_id === image.generation_item_id && chosenImage.output_index === image.output_index ? " is-selected" : ""}`} onClick={() => setChosenImage(image)}><img src={image.preview_url} alt={image.label} /><span>{image.label}</span></button>)}</div><Pagination current={galleryPage} onChange={setGalleryPage} total={images.data.length} pageSize={12} hideOnSinglePage showSizeChanger={false} /></>}
    </Modal>
  </div>
}
