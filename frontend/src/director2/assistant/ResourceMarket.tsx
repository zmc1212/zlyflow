import { useState } from "react"
import { Alert, Button, Collapse, Dropdown, Empty, Form, Input, Modal, Popconfirm, Select, Space, Tabs, Upload, message } from "antd"
import type { MenuProps } from "antd"
import { Check, Copy, Download, MoreHorizontal, Pencil, Plus, Search, Star, Trash2, Upload as UploadIcon, Wand2, X, Zap } from "lucide-react"
import { director2ErrorDetail } from "../api"
import { ASSISTANT_API, assistantMutate, assistantUpload, type AssistantResource } from "./api"
import ResourceCover from "./ResourceCover"
import { filterResources, quickResources, resourceCategories, resourceSource, resourceSourceLabels, type ResourceKind, type ResourceScope } from "./resource-market"

type ResourceEditor = Partial<AssistantResource> & { ignored_files?: string[]; scope?: "personal" | "platform" }

const SCOPES: { label: string; value: ResourceScope }[] = [
  { label: "全部来源", value: "全部" },
  { label: "平台资源", value: "平台" },
  { label: "我的收藏", value: "收藏" },
  { label: "个人资源", value: "我的" },
]

export default function ResourceMarket({ open, tab, resources, csrfToken, canManagePlatform, selectedVersions, onClose, onRefresh, onSelect }: {
  open: boolean; tab: ResourceKind; resources: AssistantResource[]; csrfToken: string; canManagePlatform?: boolean; selectedVersions: Record<ResourceKind, string | null | undefined>
  onClose: () => void; onRefresh: () => Promise<void>; onSelect: (resource: AssistantResource) => void
}) {
  const [kind, setKind] = useState<ResourceKind>(tab)
  const [search, setSearch] = useState("")
  const [category, setCategory] = useState("全部")
  const [scope, setScope] = useState<ResourceScope>("全部")
  const [editor, setEditor] = useState<ResourceEditor | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()
  const noun = kind === "skill" ? "Skill" : "专家"
  const selectedVersionId = selectedVersions[kind]
  const categories = resourceCategories(resources, kind)
  const visible = filterResources(resources, kind, category, scope, search)
  const total = resources.filter(resource => resource.resource_type === kind).length
  const quick = quickResources(resources, kind, selectedVersionId)

  function edit(resource: ResourceEditor) {
    setEditor(resource)
    form.setFieldsValue({ resource_type: kind, name: "", category: "个人", description: "", instructions: "", scope: "personal", ...resource })
  }
  async function save() {
    try {
      const values = await form.validateFields()
      setSaving(true)
      const update = !!editor?.id && !editor.builtin
      await assistantMutate(csrfToken, update ? `/resources/${editor!.id}` : "/resources", {
        resource_type: values.resource_type, name: values.name, category: values.category,
        description: values.description, instructions: values.instructions,
        scope: values.scope || (editor?.platform ? "platform" : "personal"),
        version: editor?.version, references: editor?.references || {},
      }, update ? "PUT" : "POST")
      await onRefresh(); setEditor(null); message.success("已保存创作资源")
    } catch (e) {
      if (!(e && typeof e === "object" && "errorFields" in e)) message.error(director2ErrorDetail(e, "保存失败"))
    } finally { setSaving(false) }
  }
  async function remove(resource: AssistantResource) {
    try { await assistantMutate(csrfToken, `/resources/${resource.id}`, undefined, "DELETE"); await onRefresh() }
    catch (e) { message.error(director2ErrorDetail(e, "删除失败")) }
  }
  async function toggleFavorite(resource: AssistantResource) {
    try { await assistantMutate(csrfToken, `/resources/${resource.id}/favorite`, { enabled: !resource.favorite }, "PUT"); await onRefresh() }
    catch (e) { message.error(director2ErrorDetail(e, "收藏失败")) }
  }
  async function importFile(file: File) {
    try { edit(await assistantUpload<ResourceEditor>(csrfToken, "/resources/import-preview", file)) }
    catch (e) { message.error(director2ErrorDetail(e, "导入失败")) }
    return Upload.LIST_IGNORE
  }
  function menu(resource: AssistantResource): MenuProps {
    return {
      items: [
        { key: "export", label: "导出资源", icon: <Download size={14} /> },
        { key: "copy", label: "复制为个人资源", icon: <Copy size={14} /> },
        ...(resource.manageable ? [{ type: "divider" as const }, { key: "edit", label: "编辑资源", icon: <Pencil size={14} /> }] : []),
      ],
      onClick: ({ key, domEvent }) => {
        domEvent.stopPropagation()
        if (key === "export") window.location.assign(`${ASSISTANT_API}/resources/${resource.id}/export`)
        if (key === "copy") edit({ ...resource, id: undefined, version: undefined, version_id: undefined, name: `${resource.name} · 副本`, builtin: false, platform: false, manageable: true, scope: "personal" })
        if (key === "edit") edit(resource)
      },
    }
  }

  return <>
    <Modal open={open} onCancel={onClose} footer={null} width={1280} className="assistant-market" destroyOnHidden closable={false} zIndex={1200} centered styles={{ body: { padding: 0 } }}>
      <div className="assistant-market-shell">
        <header className="assistant-market-head">
          <Tabs className="assistant-market-kind" activeKey={kind} onChange={value => { setKind(value as ResourceKind); setCategory("全部") }} items={[
            { key: "expert", label: <span><Wand2 size={15} />专家</span> },
            { key: "skill", label: <span><Zap size={15} />Skill</span> },
          ]} />
          <div className="assistant-market-head-right">
            <span>{total} 个{noun}</span>
            <Button type="text" aria-label="关闭资源市场" icon={<X size={18} />} onClick={onClose} />
          </div>
        </header>
        <Tabs className="assistant-market-categories" activeKey={category} onChange={setCategory} items={["全部", ...categories].map(name => ({ key: name, label: name }))} tabBarExtraContent={<div className="assistant-market-search">
          <Input size="small" allowClear prefix={<Search size={14} />} placeholder={`搜索${noun}名称或能力`} value={search} onChange={event => setSearch(event.target.value)} />
          <Select size="small" aria-label="资源来源" value={scope} onChange={value => setScope(value)} options={SCOPES} />
        </div>} />
        <div className="assistant-market-body">
          <section className="assistant-market-results">
            <div className="assistant-market-grid">
              {visible.map(resource => {
                const selected = resource.version_id === selectedVersionId
                return <article className="assistant-resource-card" data-selected={selected ? "true" : undefined} key={resource.id}>
                  <ResourceCover resource={resource} favorite={resource.favorite} onToggleFavorite={() => void toggleFavorite(resource)} />
                  <div className="assistant-resource-body">
                    <div className="assistant-resource-heading"><h3 title={resource.name}>{resource.name}</h3></div>
                    <p>{resource.description || "自定义创作方法与专业视角"}</p>
                    <div className="assistant-resource-foot">
                      <span className="assistant-resource-meta">{resource.category} · v{resource.version}</span>
                      <Space size={2}>
                        <Dropdown menu={menu(resource)} trigger={["click"]} placement="bottomRight"><Button type="text" size="small" aria-label={`${resource.name} 更多操作`} icon={<MoreHorizontal size={15} />} /></Dropdown>
                        {resource.manageable && <Popconfirm title={resource.platform ? "删除这个平台资源？所有账号将不再看到它，历史会话仍可引用原版本。" : "删除这个个人资源？历史会话仍可引用原版本。"} onConfirm={() => remove(resource)}><Button type="text" size="small" danger aria-label="删除资源" icon={<Trash2 size={14} />} /></Popconfirm>}
                        <Button size="small" className="assistant-resource-use" type={selected ? "default" : "primary"} icon={selected ? <Check size={13} /> : undefined} onClick={() => { onSelect(resource); onClose() }}>{selected ? "使用中" : "选用"}</Button>
                      </Space>
                    </div>
                  </div>
                </article>
              })}
            </div>
            {!visible.length && <Empty description="没有符合条件的资源，可以调整分类、来源或搜索词" />}
          </section>
          <aside className="assistant-market-side">
            <div className="assistant-market-side-head">
              <div><strong>我的{noun}</strong><small>已选、收藏与常用</small></div>
              <Space size={6}>
                <Button size="small" icon={<Plus size={13} />} onClick={() => edit({ resource_type: kind })}>新建</Button>
                <Upload accept=".md,.zip" showUploadList={false} beforeUpload={importFile}><Button size="small" icon={<UploadIcon size={13} />}>导入</Button></Upload>
              </Space>
            </div>
            <div className="assistant-market-side-list">
              {quick.map(resource => <div className={`assistant-market-side-row${resource.version_id === selectedVersionId ? " is-selected" : ""}`} key={resource.id}>
                <Button type="text" className="assistant-market-side-pick" onClick={() => { onSelect(resource); onClose() }}>
                  <ResourceCover resource={resource} variant="picker" />
                  <span><strong>{resource.name}</strong><small>{resourceSourceLabels[resourceSource(resource)]} · {resource.category}</small></span>
                </Button>
                <Button type="text" size="small" className="assistant-market-side-star" data-favorite={resource.favorite ? "true" : undefined} aria-label={resource.favorite ? "取消收藏" : "收藏资源"} icon={<Star size={13} fill={resource.favorite ? "currentColor" : "none"} />} onClick={() => void toggleFavorite(resource)} />
              </div>)}
              {!quick.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂时没有可用资源" />}
            </div>
            <div className="assistant-market-side-foot">平台资源由管理员统一维护；收藏后会固定在列表顶部。</div>
          </aside>
        </div>
      </div>
    </Modal>
    <Modal title={editor?.platform ? "编辑平台资源" : editor?.id ? "编辑个人资源" : "创建创作资源"} open={!!editor} onCancel={() => { if (!saving) setEditor(null) }} onOk={save} confirmLoading={saving} okText="保存资源" cancelText="取消" width={760} forceRender zIndex={1300}>
      {!!editor?.ignored_files?.length && <Alert type="info" showIcon title="已识别以下不支持的文件，将不会导入或执行" description={editor.ignored_files.join("、")} />}
      <Form name="assistant-resource-editor" form={form} layout="vertical">
        <Form.Item name="resource_type" label="资源类型"><Select options={[{ label: "Skill", value: "skill" }, { label: "专家", value: "expert" }]} /></Form.Item>
        {!editor?.id && canManagePlatform && <Form.Item name="scope" label="资源范围" extra="平台资源对所有账号可见，仅管理员可编辑或删除。"><Select options={[{ label: "个人", value: "personal" }, { label: "平台", value: "platform" }]} /></Form.Item>}
        <Form.Item name="name" label="名称" rules={[{ required: true, whitespace: true, message: "请输入名称" }]}><Input maxLength={100} /></Form.Item>
        <Form.Item name="category" label="分类"><Input maxLength={30} /></Form.Item>
        <Form.Item name="description" label="简介"><Input.TextArea rows={2} maxLength={500} /></Form.Item>
        <Form.Item name="instructions" label="创作指令" extra="描述适用任务、工作方法、引导步骤及交付要求。" rules={[{ required: true, whitespace: true, message: "请输入创作指令" }]}><Input.TextArea rows={12} maxLength={100000} /></Form.Item>
        {!!Object.keys(editor?.references || {}).length && <Collapse items={[{ key: "references", label: `参考资料（${Object.keys(editor?.references || {}).length}）`, children: Object.entries(editor?.references || {}).map(([name, text]) => <details key={name}><summary>{name}</summary><pre className="assistant-reference-text">{text}</pre></details>) }]} />}
      </Form>
    </Modal>
  </>
}
