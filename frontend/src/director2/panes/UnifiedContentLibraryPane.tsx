import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { Alert, Button, Collapse, Empty, Form, Input, Modal, Skeleton, Tabs, Tag, Upload, message } from "antd"
import { ArrowRight, BookOpen, FileText, Plus, Sparkles } from "lucide-react"
import { createDocument, director2ErrorDetail, listDocuments, type Director2Document } from "../api"
import ScriptDevelopmentPanel from "./ScriptDevelopmentPanel"
import ContentLibraryReader, { contentLibraryEpisodes } from "./ContentLibraryReader"
import "./content-library.css"
import "./unified-content-library.css"

function DocumentWorkspace({ doc, projectId, csrfToken, onAdopted }: {
  doc: Director2Document; projectId: string; csrfToken: string; onAdopted: () => void
}) {
  const navigate = useNavigate()
  const episodes = contentLibraryEpisodes(doc)
  const [activeTab, setActiveTab] = useState(episodes.length ? "episodes" : "development")
  const accepted = doc.analysis?.script_development as { revision?: number; script_text?: string } | undefined
  const rawText = doc.raw_text || ""
  return <section className="doc-detail-main ucl-workspace" aria-label="剧本内容工作区">
    <header className="ucl-document-header">
      <div className="ucl-document-heading">
        <div className="ucl-document-identity">
          <h3>{doc.filename}</h3>
          <div className="ucl-document-meta">
            <Tag color={accepted ? "success" : "default"}>{accepted ? "已采纳" : "待采纳"}</Tag>
            {accepted?.revision ? <span>版本 {accepted.revision}</span> : null}
            <span>{episodes.length} 集</span><span>原文 {rawText.length.toLocaleString()} 字符</span>
          </div>
        </div>
        {accepted ? <Button type="primary" icon={<ArrowRight size={15} />} iconPlacement="end" onClick={() => navigate("/director/projects/" + projectId + "/workshop")}>进入剧集工坊</Button> : null}
      </div>
      <p className="ucl-document-hint">{accepted
        ? "工坊分集已关联。可继续阅读或完善剧本，已有镜头与视频会保留。"
        : "原始内容已保留。在「剧本发展」中确认策划、审核完整稿，采纳后进入工坊。"}</p>
    </header>
    <Tabs className="ucl-workspace-tabs" activeKey={activeTab} onChange={setActiveTab} items={[
      {
        key: "episodes",
        label: <span className="ucl-tab-label"><BookOpen size={15} />分集剧本<span className="ucl-tab-count">{episodes.length}</span></span>,
        children: episodes.length ? <ContentLibraryReader episodes={episodes} accepted={Boolean(accepted)} />
          : <div className="ucl-empty-reader"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂时没有分集剧本" /><p>先在剧本发展中完成策划并采纳，原始内容随时可以查看。</p><Button type="primary" onClick={() => setActiveTab("development")}>前往剧本发展</Button><Button onClick={() => setActiveTab("source")}>查看导入原文</Button></div>,
      },
      {
        key: "development", label: <span className="ucl-tab-label"><Sparkles size={15} />剧本发展</span>, forceRender: true,
        children: <div className="ucl-development"><ScriptDevelopmentPanel projectId={projectId} documentId={doc.id} csrfToken={csrfToken} onAdopted={() => { onAdopted(); setActiveTab("episodes") }} /></div>,
      },
      {
        key: "source", label: <span className="ucl-tab-label"><FileText size={15} />导入原文</span>,
        children: <section className="ucl-source" aria-label="导入原文">
          <div className="ucl-reader-toolbar"><div><strong>导入原文</strong><span className="ucl-toolbar-note">保留导入时的内容，供对照阅读</span></div></div>
          {rawText.trim() ? <div className="ucl-reading-scroll" tabIndex={0} role="region" aria-label="导入原文正文"><article className="ucl-reading-page">
            {Boolean(doc.analysis?.summary) && <Collapse className="ucl-source-summary" ghost items={[{ key: "summary", label: "查看解析摘要", children: <p>{String(doc.analysis?.summary)}</p> }]} />}
            <pre className="ucl-original-text">{rawText}</pre>
          </article></div> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="此文档没有导入原文" />}
        </section>,
      },
    ]} />
  </section>
}

export default function UnifiedContentLibraryPane({ csrfToken, projectId, onProjectUpdated }: {
  csrfToken: string; projectId: string; onProjectUpdated?: () => void; [key: string]: unknown
}) {
  const [params, setParams] = useSearchParams()
  const [docs, setDocs] = useState<Director2Document[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")
  const requestId = useRef(0)
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState("")
  const [text, setText] = useState("")
  const [busy, setBusy] = useState(false)
  const selected = docs.find(doc => doc.id === params.get("doc")) || docs[0]
  const load = useCallback(async () => {
    const request = ++requestId.current
    setLoading(true)
    try {
      const next = await listDocuments(projectId)
      if (request !== requestId.current) return
      setDocs(next); setLoadError("")
    } catch (err) {
      if (request === requestId.current) setLoadError(director2ErrorDetail(err, "读取内容库失败，请重试"))
    } finally { if (request === requestId.current) setLoading(false) }
  }, [projectId])
  useEffect(() => { setDocs([]); void load(); return () => { requestId.current += 1 } }, [load])
  function selectDocument(id: string) {
    setParams(previous => { const next = new URLSearchParams(previous); next.set("doc", id); return next })
  }
  async function create() {
    if (busy || !text.trim()) return
    setBusy(true)
    try {
      const doc = await createDocument(csrfToken, projectId, { filename: title.trim() || "创意草稿", raw_text: text, input_mode: "text" })
      selectDocument(doc.id); setOpen(false); setText(""); setTitle("")
      await load(); onProjectUpdated?.()
    } catch (err) { message.error(director2ErrorDetail(err, "保存草稿失败")) }
    finally { setBusy(false) }
  }
  return <div className="content-library-pane d2-content-library ucl-library">
    <div className="sub-pane-header">
      <div><h2 className="sub-pane-title">内容库</h2><p className="sub-pane-subtitle">管理创意与剧本，完善故事后进入工坊制作。</p></div>
      <Button icon={<Plus size={16} />} onClick={() => setOpen(true)}>新建创意／导入剧本</Button>
    </div>
    {loadError ? <Alert className="ucl-load-error" type="error" showIcon title={loadError} action={<Button size="small" loading={loading} onClick={() => void load()}>重新加载</Button>} /> : null}
    {loading && !docs.length ? <div className="ucl-loading" aria-label="正在加载内容库"><Skeleton active title paragraph={{ rows: 7 }} /></div> : docs.length ? <div className="content-layout">
      <aside className="doc-list-sidebar" aria-label="剧本文档">
        <div className="doc-list-header"><span>已导入剧本 ({docs.length})</span></div>
        <div className="doc-items-scroll">{docs.map(doc => <button key={doc.id} type="button" className={"doc-item" + (selected?.id === doc.id ? " active" : "")} aria-current={selected?.id === doc.id ? "true" : undefined} onClick={() => selectDocument(doc.id)}>
          <div className="doc-item-title"><FileText size={16} className="doc-icon" /><span className="name" title={doc.filename}>{doc.filename}</span></div>
          <div className="doc-item-meta"><Tag>{contentLibraryEpisodes(doc).length ? contentLibraryEpisodes(doc).length + " 集" : "草稿"}</Tag>{Boolean(doc.analysis?.script_development) && <Tag color="success">已采纳</Tag>}<span className="time">{doc.created_at?.slice(5, 16).replace("T", " ")}</span></div>
        </button>)}</div>
      </aside>
      {selected ? <DocumentWorkspace key={selected.id} doc={selected} projectId={projectId} csrfToken={csrfToken} onAdopted={() => { void load(); onProjectUpdated?.() }} /> : null}
    </div> : !loadError ? <div className="empty-doc-box"><div className="empty-icon-wrap"><FileText size={40} /></div><h3>暂无导入的剧本文档</h3><p>输入一句话创意，或导入已有剧本。</p><Button type="primary" onClick={() => setOpen(true)}>立即导入剧本</Button></div> : null}
    <Modal title="新建创意／导入剧本" open={open} onCancel={() => { if (!busy) setOpen(false) }} onOk={() => void create()} confirmLoading={busy} okButtonProps={{ disabled: !text.trim() }} okText="保存并发展剧本" width={760}>
      <Form layout="vertical"><Form.Item label="标题"><Input value={title} onChange={event => setTitle(event.target.value)} disabled={busy} /></Form.Item>
        <Form.Item label="创意或完整剧本"><Input.TextArea value={text} onChange={event => setText(event.target.value)} disabled={busy} rows={14} placeholder="一句话创意、大纲、简稿或完整剧本均可" /></Form.Item>
        <Upload accept=".txt,.md" disabled={busy} showUploadList={false} beforeUpload={async file => { try { setText(await file.text()); setTitle(file.name) } catch { message.error("文件读取失败，请重试或粘贴文本") } return false }}><Button disabled={busy}>读取 TXT／Markdown</Button></Upload>
      </Form>
    </Modal>
  </div>
}
