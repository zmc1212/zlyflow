import { useEffect, useState } from "react"
import { Alert, Button, Empty, Input, Modal, Popconfirm, Space, Tag, Upload, message } from "antd"
import { FileText, Plus, RefreshCw, Trash2, Upload as UploadIcon } from "lucide-react"
import { director2ErrorDetail } from "../api"
import { assistantMutate, assistantUpload, type KnowledgeLibrary } from "./api"

const labels: Record<string, string> = { ready: "就绪", parsing: "正在解析", failed: "解析失败" }

export default function KnowledgeManager({ open, libraries, csrfToken, onClose, onRefresh }: {
  open: boolean; libraries: KnowledgeLibrary[]; csrfToken: string; onClose: () => void; onRefresh: () => Promise<void>
}) {
  const [name, setName] = useState("")
  const [uploading, setUploading] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const parsing = libraries.some(k => k.documents.some(d => d.status === "parsing"))
  useEffect(() => {
    if (!open || !parsing) return
    const timer = window.setInterval(() => { void onRefresh() }, 2500)
    return () => window.clearInterval(timer)
  }, [open, parsing, onRefresh])
  async function mutate(path: string, value?: unknown, method?: string) {
    try { await assistantMutate(csrfToken, path, value, method); await onRefresh() }
    catch (e) { message.error(director2ErrorDetail(e, "操作失败")) }
  }
  async function create() {
    if (!name.trim()) return
    setCreating(true)
    try { await assistantMutate(csrfToken, "/knowledge", { name: name.trim() }); setName(""); await onRefresh() }
    catch (e) { message.error(director2ErrorDetail(e, "创建失败")) }
    finally { setCreating(false) }
  }
  async function upload(kid: string, file: File) {
    setUploading(kid)
    try { await assistantUpload(csrfToken, `/knowledge/${kid}/documents`, file); await onRefresh() }
    catch (e) { message.error(director2ErrorDetail(e, "上传失败")) }
    finally { setUploading(null) }
    return Upload.LIST_IGNORE
  }
  return <Modal title="知识库管理" open={open} onCancel={onClose} footer={null} width={880} className="assistant-knowledge-manager" zIndex={1200} centered styles={{ body: { maxHeight: "70vh", overflowY: "auto" } }}>
    <p className="assistant-secondary">导入设定、原著或制作规范，助手会检索所选资料并展示原文出处。支持20MB以内的 TXT、Markdown、DOCX 和文字型 PDF。</p>
    <div className="assistant-knowledge-create"><Input aria-label="知识库名称" placeholder="新知识库名称" maxLength={100} value={name} onChange={e => setName(e.target.value)} onPressEnter={() => { void create() }} /><Button type="primary" loading={creating} disabled={!name.trim()} onClick={create} icon={<Plus size={15} />}>新建知识库</Button></div>
    {!libraries.length && <Empty description="创建知识库后导入第一份资料" />}
    {libraries.map(kb => <section className="assistant-knowledge-library" key={kb.id}>
      <div className="assistant-section-heading"><div><h3>{kb.name} {kb.builtin && <Tag>内置示例</Tag>}</h3>{kb.description && <p>{kb.description}</p>}</div>
        {!kb.builtin && <Space><Upload accept=".txt,.md,.docx,.pdf" showUploadList={false} beforeUpload={file => upload(kb.id, file)}><Button loading={uploading === kb.id} icon={<UploadIcon size={14} />}>导入资料</Button></Upload><Popconfirm title="删除知识库？历史会话的引用仍会保留。" onConfirm={() => mutate(`/knowledge/${kb.id}`, undefined, "DELETE")}><Button type="text" danger aria-label="删除知识库" icon={<Trash2 size={15} />} /></Popconfirm></Space>}
      </div>
      {!kb.documents.length && <p className="assistant-secondary">还没有资料，导入后即可在助手工具栏选择。</p>}
      {kb.documents.map(doc => <div className="assistant-document-row" key={doc.id}>
        <FileText size={17} /><div><strong>{doc.filename}</strong><span>{labels[doc.status] || doc.status}{doc.chunk_count ? ` · ${doc.chunk_count} 个片段` : ""}</span>{doc.error && <Alert type="error" title={doc.error} />}</div>
        {!kb.builtin && <Space>{doc.status === "failed" && <Button size="small" icon={<RefreshCw size={13} />} onClick={() => mutate(`/knowledge/documents/${doc.id}/retry`)}>重试</Button>}<Popconfirm title="移除此资料？" onConfirm={() => mutate(`/knowledge/documents/${doc.id}`, undefined, "DELETE")}><Button type="text" danger disabled={doc.status === "parsing"} aria-label="移除资料" icon={<Trash2 size={14} />} /></Popconfirm></Space>}
      </div>)}
    </section>)}
  </Modal>
}
