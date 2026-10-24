import { useState } from "react"
import { Alert, Button, Collapse, Empty, Form, Input, Modal, Popconfirm, Segmented, Select, Space, Tag, Upload, message } from "antd"
import { BookOpen, Copy, Download, Pencil, Plus, Search, Star, Trash2, Upload as UploadIcon, Zap } from "lucide-react"
import { director2ErrorDetail } from "../api"
import { ASSISTANT_API, assistantMutate, assistantUpload, type AssistantResource } from "./api"

type ResourceEditor = Partial<AssistantResource> & { ignored_files?: string[] }

export default function ResourceMarket({ open, tab, resources, csrfToken, onClose, onRefresh, onSelect }: {
  open: boolean; tab: "skill" | "expert"; resources: AssistantResource[]; csrfToken: string
  onClose: () => void; onRefresh: () => Promise<void>; onSelect: (resource: AssistantResource) => void
}) {
  const [kind, setKind] = useState(tab)
  const [search, setSearch] = useState("")
  const [category, setCategory] = useState("全部")
  const [filter, setFilter] = useState("全部")
  const [editor, setEditor] = useState<ResourceEditor | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()
  const visible = resources.filter(r => r.resource_type === kind && (category === "全部" || r.category === category) && (filter !== "收藏" || r.favorite) && (filter !== "我的" || !r.builtin) && `${r.name} ${r.description}`.toLowerCase().includes(search.toLowerCase()))
  const categories = ["全部", ...new Set(resources.filter(r => r.resource_type === kind).map(r => r.category))]

  function edit(resource: ResourceEditor) {
    setEditor(resource)
    form.setFieldsValue({ resource_type: kind, name: "", category: "个人", description: "", instructions: "", ...resource })
  }
  async function save() {
    try {
      const values = await form.validateFields()
      setSaving(true)
      const update = !!editor?.id && !editor.builtin
      await assistantMutate(csrfToken, update ? `/resources/${editor!.id}` : "/resources", { ...values, version: editor?.version, references: editor?.references || {} }, update ? "PUT" : "POST")
      await onRefresh(); setEditor(null); message.success("已保存创作资源")
    } catch (e) {
      if (!(e && typeof e === "object" && "errorFields" in e)) message.error(director2ErrorDetail(e, "保存失败"))
    } finally { setSaving(false) }
  }
  async function remove(resource: AssistantResource) {
    try { await assistantMutate(csrfToken, `/resources/${resource.id}`, undefined, "DELETE"); await onRefresh() }
    catch (e) { message.error(director2ErrorDetail(e, "删除失败")) }
  }
  async function importFile(file: File) {
    try { edit(await assistantUpload<ResourceEditor>(csrfToken, "/resources/import-preview", file)) }
    catch (e) { message.error(director2ErrorDetail(e, "导入失败")) }
    return Upload.LIST_IGNORE
  }

  return <>
    <Modal open={open} onCancel={onClose} footer={null} width={1120} title="创作资源市场" className="assistant-market" destroyOnHidden zIndex={1200} centered>
      <div className="assistant-market-toolbar">
        <Segmented value={kind} onChange={v => { setKind(v as typeof kind); setCategory("全部") }} options={[{ label: "Skill", value: "skill" }, { label: "专家", value: "expert" }]} />
        <Input prefix={<Search size={15} />} placeholder="搜索名称或创作能力" value={search} onChange={e => setSearch(e.target.value)} allowClear />
        <Upload accept=".md,.zip" showUploadList={false} beforeUpload={importFile}><Button icon={<UploadIcon size={14} />}>导入</Button></Upload>
        <Button type="primary" icon={<Plus size={15} />} onClick={() => edit({ resource_type: kind })}>新建{kind === "skill" ? " Skill" : "专家"}</Button>
      </div>
      <div className="assistant-market-filters">
        <Segmented value={filter} onChange={v => setFilter(String(v))} options={["全部", "收藏", "我的"]} />
        <Select aria-label="资源分类" value={category} onChange={setCategory} options={categories.map(c => ({ label: c, value: c }))} />
      </div>
      <div className="assistant-market-grid">
        {visible.map(resource => <article className="assistant-resource" key={resource.id}>
          <div className="assistant-resource-symbol" data-kind={resource.resource_type}>{resource.resource_type === "skill" ? <Zap size={25} /> : <BookOpen size={25} />}</div>
          <div className="assistant-resource-heading"><h3>{resource.name}</h3><Tag>{resource.builtin ? "内置" : "个人"}</Tag></div>
          <p>{resource.description || "自定义创作方法与专业视角"}</p>
          <div className="assistant-resource-footer"><Tag variant="filled">{resource.category}</Tag><Space size={2}>
            <Button type="text" aria-label={resource.favorite ? "取消收藏" : "收藏"} icon={<Star size={15} fill={resource.favorite ? "currentColor" : "none"} />} onClick={async () => { try { await assistantMutate(csrfToken, `/resources/${resource.id}/favorite`, { enabled: !resource.favorite }, "PUT"); await onRefresh() } catch (e) { message.error(director2ErrorDetail(e, "收藏失败")) } }} />
            <Button type="text" aria-label="导出资源" href={`${ASSISTANT_API}/resources/${resource.id}/export`} icon={<Download size={15} />} />
            <Button type="text" aria-label="复制资源" icon={<Copy size={15} />} onClick={() => edit({ ...resource, id: undefined, version: undefined, version_id: undefined, name: `${resource.name} · 副本`, builtin: false })} />
            {!resource.builtin && <Button type="text" aria-label="编辑资源" icon={<Pencil size={15} />} onClick={() => edit(resource)} />}
            {!resource.builtin && <Popconfirm title="删除这个个人资源？历史会话仍可引用原版本。" onConfirm={() => remove(resource)}><Button type="text" danger aria-label="删除资源" icon={<Trash2 size={14} />} /></Popconfirm>}
          </Space></div>
          <Button block onClick={() => { onSelect(resource); onClose() }}>选用{resource.resource_type === "skill" ? " Skill" : "专家"}</Button>
        </article>)}
      </div>
      {!visible.length && <Empty description="没有符合条件的资源，可以调整筛选或创建自己的资源" />}
    </Modal>
    <Modal title={editor?.id ? "编辑个人资源" : "创建创作资源"} open={!!editor} onCancel={() => { if (!saving) setEditor(null) }} onOk={save} confirmLoading={saving} okText="保存资源" cancelText="取消" width={760} forceRender zIndex={1300}>
      {!!editor?.ignored_files?.length && <Alert type="info" showIcon title="已识别以下不支持的文件，将不会导入或执行" description={editor.ignored_files.join("、")} />}
      <Form name="assistant-resource-editor" form={form} layout="vertical">
        <Form.Item name="resource_type" label="资源类型"><Select options={[{ label: "Skill", value: "skill" }, { label: "专家", value: "expert" }]} /></Form.Item>
        <Form.Item name="name" label="名称" rules={[{ required: true, whitespace: true, message: "请输入名称" }]}><Input maxLength={100} /></Form.Item>
        <Form.Item name="category" label="分类"><Input maxLength={30} /></Form.Item>
        <Form.Item name="description" label="简介"><Input.TextArea rows={2} maxLength={500} /></Form.Item>
        <Form.Item name="instructions" label="创作指令" extra="描述适用任务、工作方法、引导步骤及交付要求。" rules={[{ required: true, whitespace: true, message: "请输入创作指令" }]}><Input.TextArea rows={12} maxLength={100000} /></Form.Item>
        {!!Object.keys(editor?.references || {}).length && <Collapse items={[{ key: "references", label: `参考资料（${Object.keys(editor?.references || {}).length}）`, children: Object.entries(editor?.references || {}).map(([name, text]) => <details key={name}><summary>{name}</summary><pre className="assistant-reference-text">{text}</pre></details>) }]} />}
      </Form>
    </Modal>
  </>
}
