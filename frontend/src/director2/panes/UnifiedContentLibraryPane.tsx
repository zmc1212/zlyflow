import { useCallback, useEffect, useState } from "react"
import { useNavigate, useSearchParams } from "react-router-dom"
import { Alert, Button, Collapse, Empty, Form, Input, Modal, Space, Tag, Tabs, Typography, Upload, message } from "antd"
import { createDocument, director2ErrorDetail, listDocuments, type Director2Document } from "../api"
import { FileText, Plus } from "lucide-react"
import "./content-library.css"
import ScriptDevelopmentPanel from "./ScriptDevelopmentPanel"

export default function UnifiedContentLibraryPane({ csrfToken, projectId, onProjectUpdated }: {
  csrfToken: string; projectId: string; onProjectUpdated?: () => void; [key: string]: unknown
}) {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [docs, setDocs] = useState<Director2Document[]>([])
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState("")
  const [text, setText] = useState("")
  const [busy, setBusy] = useState(false)
  const selected = docs.find(d => d.id === params.get("doc")) || docs[0]
  const load = useCallback(async () => {
    try { setDocs(await listDocuments(projectId)) } catch (err) { message.error(director2ErrorDetail(err, "读取内容库失败")) }
  }, [projectId])
  useEffect(() => { void load() }, [load])
  async function create() {
    setBusy(true)
    try {
      const doc = await createDocument(csrfToken, projectId, { filename: title.trim() || "创意草稿", raw_text: text, input_mode: "text" })
      setParams({ doc: doc.id }); setOpen(false); setText(""); setTitle("")
      await load(); onProjectUpdated?.()
    } catch (err) { message.error(director2ErrorDetail(err, "保存草稿失败")) }
    finally { setBusy(false) }
  }
  const episodeRows = (doc?: Director2Document) => Array.isArray(doc?.analysis?.episodes) ? doc.analysis.episodes as Array<{episode_num:number;title:string;summary?:string;script_text?:string;body?:string}> : []
  const accepted = selected?.analysis?.script_development as { revision?: number; script_text?: string } | undefined
  return <div className="content-library-pane d2-content-library">
    <div className="sub-pane-header"><div><h2 className="sub-pane-title">内容库</h2><p className="sub-pane-subtitle">导入大纲、简稿或完整剧本，诊断、策划、扩写和采纳后进入工坊制作。</p></div><Button type="primary" className="primary-btn" icon={<Plus size={16} />} onClick={() => setOpen(true)}>新建创意／导入剧本</Button></div>
    {docs.length ? <div className="content-layout">
      <div className="doc-list-sidebar"><div className="doc-list-header"><span>已导入剧本 ({docs.length})</span></div><div className="doc-items-scroll">{docs.map(doc => <div key={doc.id} className={`doc-item${selected?.id === doc.id ? " active" : ""}`} role="button" tabIndex={0} onClick={() => setParams({doc:doc.id})} onKeyDown={event => {if(event.key === "Enter") setParams({doc:doc.id})}}><div className="doc-item-title"><FileText size={16} className="doc-icon" /><span className="name" title={doc.filename}>{doc.filename}</span></div><div className="doc-item-meta"><Tag color="purple">{episodeRows(doc).length ? `${episodeRows(doc).length} 集` : "草稿"}</Tag>{Boolean(doc.analysis?.script_development) && <Tag color="success">已采纳</Tag>}<span className="time">{doc.created_at?.slice(5,16)}</span></div></div>)}</div></div>
      <div className="doc-detail-main">
        {selected && <ScriptDevelopmentPanel key={selected.id} projectId={projectId} documentId={selected.id} csrfToken={csrfToken} onAdopted={() => { void load(); onProjectUpdated?.() }} />}
        {accepted && <Alert type="success" showIcon message={`剧本已采纳 · 版本 ${accepted.revision}`} description="工坊分集已关联；进入工坊规划镜头，现有镜头和视频会保留。" action={<Button onClick={() => navigate(`/director/projects/${projectId}/workshop`)}>进入剧集工坊</Button>} />}
        <div className="detail-top-card"><div className="detail-top-header"><div className="detail-top-info"><h3 className="detail-title">{selected?.filename}</h3><div className="detail-tags"><Tag color="purple">{episodeRows(selected).length || 0} 集</Tag><span className="char-count">约 {selected?.raw_text?.length || 0} 字符</span></div></div></div>{Boolean(selected?.analysis?.summary) && <div className="summary-box"><span className="summary-label">内容解析摘要：</span><p className="summary-text">{String(selected?.analysis?.summary || "")}</p></div>}</div>
        <div className="analysis-tabs-wrap"><Tabs type="card" items={[{key:"episodes",label:"分集剧本",children:episodeRows(selected).length ? <div className="episodes-container"><Collapse bordered={false} className="episodes-collapse" items={episodeRows(selected).map(ep => ({key:String(ep.episode_num),label:<div className="ep-collapse-header"><div className="ep-title-group"><span className="ep-badge">第 {ep.episode_num} 集</span><span className="ep-main-title">{ep.title}</span></div></div>,children:<Typography.Paragraph style={{whiteSpace:"pre-wrap"}}>{String((ep as unknown as Record<string,unknown>).script_text || (ep as unknown as Record<string,unknown>).body || ep.summary || "完整采纳稿见剧本发展区域")}</Typography.Paragraph>}))} /></div> : <Empty description="采纳剧本后显示分集" />},{key:"source",label:"导入原文",children:<div className="script-preview-card"><Typography.Paragraph style={{whiteSpace:"pre-wrap"}}>{selected?.raw_text}</Typography.Paragraph></div>}]} /></div>
      </div>
    </div> : <div className="empty-doc-box"><div className="empty-icon-wrap"><FileText size={40} /></div><h3>暂无导入的剧本文档</h3><p>输入一句话创意，或导入已有剧本。</p><Button type="primary" onClick={() => setOpen(true)}>立即导入剧本</Button></div>}
    <Modal title="新建创意／导入剧本" open={open} onCancel={() => setOpen(false)} onOk={() => void create()} confirmLoading={busy} okButtonProps={{ disabled: !text.trim() }} okText="保存并发展剧本" width={760}>
      <Form layout="vertical"><Form.Item label="标题"><Input value={title} onChange={e => setTitle(e.target.value)} /></Form.Item>
        <Form.Item label="创意或完整剧本"><Input.TextArea value={text} onChange={e => setText(e.target.value)} rows={14} placeholder="一句话创意、大纲、简稿或完整剧本均可" /></Form.Item>
        <Upload accept=".txt,.md" showUploadList={false} beforeUpload={async file => { setText(await file.text()); setTitle(file.name); return false }}><Button>读取 TXT／Markdown</Button></Upload>
      </Form>
    </Modal>
  </div>
}
