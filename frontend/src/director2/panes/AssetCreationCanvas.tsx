import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react"
import { Background, BackgroundVariant, Handle, MiniMap, Panel, Position, ReactFlow, ReactFlowProvider, applyNodeChanges, useReactFlow, type Connection, type NodeProps, type XYPosition } from "@xyflow/react"
import { Alert, Button, Drawer, Dropdown, Empty, Form, Input, Modal, Segmented, Spin, Tag, Tooltip, message } from "antd"
import { ArrowRight, Boxes, Check, ChevronDown, FileText, FolderOpen, Image as ImageIcon, LayoutGrid, Map, Maximize2, Mic, MoreHorizontal, Pencil, Plus, RefreshCw, Save, Search, Sparkles, Upload as UploadIcon, Workflow, X, ZoomIn, ZoomOut } from "lucide-react"
import type { Director2Asset } from "../api"
import { assetDefinitionText, assetNodeId, assetSlotBlocker, assetSlotPrompt, buildAssetCanvas, type AssetCanvasNode, type AssetCanvasTarget } from "../asset-canvas-model"
import { sourceReferencesOf } from "../asset-source-references"
import { useMediaPreview } from "../media-preview"
import { assetReadiness } from "../project-flow"
import { getAssetDisplayAvatar, getKindIcon, kindLabel } from "./assets/shared"
import AssetPickerModal from "../../tools/AssetPickerModal"
import "@xyflow/react/dist/style.css"
import "./asset-creation-canvas.css"

export type AssetCanvasActions = {
  select: (id: string) => void
  showList: () => void | Promise<void>
  create: (kind: string, position?: XYPosition) => void
  addLook: (id: string) => void
  saveDefinition: (id: string, name: string, role: string, description: string) => Promise<void>
  saveMetadata: (id: string, target: AssetCanvasTarget, name: string) => Promise<void>
  prompt: (id: string, target: AssetCanvasTarget, prompt: string) => void
  position: (id: string, key: string, position: XYPosition) => void
  generate: (id: string, target: AssetCanvasTarget) => Promise<void>
  upload: (id: string, target: AssetCanvasTarget | null, files: File[]) => Promise<void>
  removeReference: (id: string, refId: string) => Promise<void>
  connect: (sourceId: string, targetId: string) => void
  voice: (id: string) => void
  save: () => Promise<void>
  continue?: () => void | Promise<void>
}

type Props = {
  projectId: string
  assets: Director2Asset[]
  selectedId?: string
  selectedNode?: string | null
  saveStatus: string
  saveError: boolean
  loading: boolean
  working: string | null
  errors?: Record<string, string>
  actions: AssetCanvasActions
}
type CanvasContext = { actions: AssetCanvasActions; working: string | null; choose: (id: string) => void; editDefinition: (id: string) => void; editMetadata: (id: string) => void; chooseFile: (id: string, library: boolean) => void; preview: (url: string, title: string) => void }
const Context = createContext<CanvasContext | null>(null)
const nodeTypes = { assetGroup: AssetGroupNode, assetCreation: AssetCreationNode }

function AssetGroupNode({ data }: NodeProps<AssetCanvasNode>) {
  const context = useContext(Context)!
  const Icon = getKindIcon(data.asset.kind)
  return <section className="ac-asset-group" aria-label={`${data.asset.name}节点组`}>
    <div className="ac-group-heading"><Icon size={15}/><span>{data.asset.name}</span><Tag variant="filled">{kindLabel(data.asset.kind)}</Tag></div>
    {data.asset.kind === "character" && <Button className="ac-add-look nodrag" type="text" icon={<Plus size={14}/>} onClick={() => context.actions.addLook(data.asset.id)}>新增造型</Button>}
  </section>
}

function AssetCreationNode({ id, data, selected }: NodeProps<AssetCanvasNode>) {
  const context = useContext(Context)!
  const { asset, role, title, image, target } = data
  const busy = context.working === id
  const refs = sourceReferencesOf(asset)
  return <article className={`ac-node ac-node-${role}${selected ? " is-selected" : ""}${busy ? " is-working" : ""}`} aria-label={`${asset.name} · ${title}`}>
    {role !== "definition" && <Handle type="target" position={Position.Left} isConnectable={role === "references"} aria-label="参考图输入"/>}
    <header className="ac-node-heading"><span>{role === "definition" ? <FileText size={13}/> : <ImageIcon size={13}/>}<span>{title}</span></span>{role !== "references" && <Tooltip title={role === "definition" ? "编辑设定" : "编辑名称"}><Button className="nodrag" type="text" size="small" aria-label={`编辑${asset.name}${title}`} icon={<Pencil size={12}/>} onClick={event => { event.stopPropagation(); if (role === "definition") context.editDefinition(id); else if (role === "image") context.editMetadata(id) }}/></Tooltip>}</header>
    {role === "definition" ? <>
      <div className="ac-definition-body"><strong>{asset.name}</strong>{asset.role && <span className="ac-definition-role">{asset.role}</span>}<p>{assetDefinitionText(asset) || `描述${kindLabel(asset.kind)}的外观、风格与不可变细节，供后续图片创作使用。`}</p></div>
      <Button className="ac-node-quiet nodrag" type="text" icon={<Pencil size={12}/>} onClick={event => { event.stopPropagation(); context.editDefinition(id) }}>编辑{kindLabel(asset.kind)}档案</Button>
    </> : role === "references" ? <>
      <div className="ac-reference-body nodrag" onClick={event => event.stopPropagation()}>
        {refs.length ? <div className="ac-reference-grid">{refs.map(ref => <div key={ref.id}><button type="button" aria-label={`预览${ref.filename || "参考图"}`} onClick={() => context.preview(ref.url, ref.filename || "参考图")}><img src={ref.url} alt={ref.filename || "参考图"}/></button><Button type="text" size="small" aria-label={`移除${ref.filename || "参考图"}`} icon={<X size={11}/>} disabled={!!context.working} onClick={() => void context.actions.removeReference(asset.id, ref.id)}/></div>)}</div> : <ImageIcon size={30}/>}
        <div className="ac-upload-options"><Button size="small" icon={<UploadIcon size={13}/>} disabled={!!context.working} onClick={() => context.chooseFile(id, false)}>上传参考图</Button><Button size="small" icon={<FolderOpen size={13}/>} disabled={!!context.working} onClick={() => context.chooseFile(id, true)}>素材库</Button></div>
        <p>{refs.length} / 9 张 · 连接或上传参考图</p>
      </div>
    </> : <>
      <div className="ac-image-body nodrag" onClick={event => event.stopPropagation()}>
        {image ? <button className="ac-image-preview" type="button" aria-label={`预览${asset.name}${title}`} onClick={() => context.preview(image, `${asset.name} · ${title}`)}><img src={image} alt={`${asset.name} · ${title}`}/><span><Maximize2 size={16}/>预览</span></button> : <div className="ac-empty-image"><ImageIcon size={28}/><div className="ac-upload-options"><Button size="small" icon={<UploadIcon size={13}/>} onClick={() => context.chooseFile(id, false)} disabled={!!context.working}>上传</Button><Button size="small" icon={<FolderOpen size={13}/>} onClick={() => context.chooseFile(id, true)} disabled={!!context.working}>素材库</Button></div><span>也可以描述画面，AI 创作</span></div>}
        {busy && <div className="ac-node-working"><Spin/><span>正在处理此节点…</span></div>}
      </div>
      <div className="ac-image-tools nodrag" onClick={event => event.stopPropagation()}>{asset.kind === "character" && <Tooltip title="角色音色"><Button type="text" aria-label={`${asset.name}角色音色`} icon={<Mic size={16}/>} onClick={() => context.actions.voice(asset.id)}/></Tooltip>}<Button type="text" aria-label={`创作${asset.name}${title}`} icon={<Sparkles size={15}/>} onClick={() => context.choose(id)}>创作</Button><Dropdown trigger={["click"]} menu={{ items: [{ key: "edit", label: "编辑名称", onClick: () => context.editMetadata(id) }, { key: "replace", label: "上传替换图片", disabled: !!context.working, onClick: () => context.chooseFile(id, false) }, { key: "library", label: "从素材库选择", disabled: !!context.working, onClick: () => context.chooseFile(id, true) }] }}><Button type="text" aria-label={`${asset.name}${title}更多操作`} icon={<MoreHorizontal size={16}/>}/></Dropdown></div>
      <footer><strong>{title}</strong><span className={image ? "ac-ready" : "ac-missing"}>{image ? <><Check size={10}/>已就绪</> : "待完善"}</span><p>{target?.type === "scene_pano" ? "360° 全景 · 可用于空间预览" : asset.kind === "character" ? "角色设定板 · 全剧复用" : "图片资产 · 分镜可直接引用"}</p></footer>
    </>}
    <Handle type="source" position={Position.Right} isConnectable={role === "image" && !!image} aria-label="图片输出"/>
  </article>
}

export default function AssetCreationCanvas(props: Props) {
  return <ReactFlowProvider><AssetCreationCanvasInner {...props}/></ReactFlowProvider>
}

function AssetCreationCanvasInner(props: Props) {
  const { assets, actions, selectedId, selectedNode, working } = props
  const { openMediaPreview } = useMediaPreview()
  const flow = useReactFlow<AssetCanvasNode>()
  const graph = useMemo(() => buildAssetCanvas(assets), [assets])
  const [nodes, setNodes] = useState(graph.nodes)
  const [currentNode, setCurrentNode] = useState<string | null>(selectedNode || null)
  const [composerOpen, setComposerOpen] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [libraryKind, setLibraryKind] = useState("all")
  const [search, setSearch] = useState("")
  const [miniMap, setMiniMap] = useState(false)
  const [contextMenuOpen, setContextMenuOpen] = useState(false)
  const contextOrigin = useRef<XYPosition | null>(null)
  const [zoom, setZoom] = useState(1)
  const [editNode, setEditNode] = useState<string | null>(null)
  const [editKind, setEditKind] = useState<"definition" | "metadata">("definition")
  const [editName, setEditName] = useState("")
  const [editRole, setEditRole] = useState("")
  const [editText, setEditText] = useState("")
  const [editing, setEditing] = useState(false)
  const [fileTarget, setFileTarget] = useState<string | null>(null)
  const [mediaPicker, setMediaPicker] = useState(false)
  const uploadRef = useRef<HTMLInputElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const focusedAsset = useRef<string | null>(null)
  const composerWasOpen = useRef(false)
  const viewportKey = `director2-asset-canvas:${props.projectId}:viewport`

  useEffect(() => { setNodes(previous => graph.nodes.map(node => ({ ...node, selected: node.id === currentNode, position: previous.find(item => item.id === node.id && item.dragging)?.position || node.position }))) }, [graph, currentNode])

  useEffect(() => {
    if (!selectedId || !graph.nodes.length || focusedAsset.current === selectedId) return
    focusedAsset.current = selectedId
    const key = selectedNode || graph.nodes.find(node => node.data.asset.id === selectedId && node.data.role === "image")?.id || assetNodeId(selectedId, "definition")
    setCurrentNode(key)
    requestAnimationFrame(() => { void flow.fitView({ nodes: [{ id: assetNodeId(selectedId, "group") }], padding: .16, maxZoom: .95, duration: 250 }) })
  }, [selectedId, selectedNode, graph.nodes, flow])

  const chosen = graph.nodes.find(node => node.id === currentNode)
  const imageNode = chosen?.data.role === "image" ? chosen : undefined
  const currentAsset = chosen?.data.asset
  const blocker = imageNode?.data.target ? assetSlotBlocker(imageNode.data.asset, imageNode.data.target) : ""

  useEffect(() => {
    const wasOpen = composerWasOpen.current
    composerWasOpen.current = composerOpen
    if (!composerOpen) {
      if (wasOpen && currentAsset) void flow.fitView({ nodes: [{ id: assetNodeId(currentAsset.id, "group") }], padding: .16, maxZoom: .95, duration: 220 })
      return
    }
    if (!imageNode || !stageRef.current) return
    const frame = requestAnimationFrame(() => {
      const stage = stageRef.current
      if (!stage) return
      const parent = graph.nodes.find(node => node.id === imageNode.parentId)
      const x = imageNode.position.x + (parent?.position.x || 0) + 170
      const y = imageNode.position.y + (parent?.position.y || 0) + 242.5
      const nextZoom = Math.min(.95, Math.max(.3, (stage.clientHeight - 300) / 485))
      void flow.setViewport({ x: stage.clientWidth / 2 - x * nextZoom, y: (stage.clientHeight - 260) / 2 - y * nextZoom, zoom: nextZoom }, { duration: 220 })
    })
    return () => cancelAnimationFrame(frame)
    // Keep typing and generation updates from moving the selected node again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [composerOpen, currentNode])

  const choose = (id: string, edit = true) => {
    const node = graph.nodes.find(item => item.id === id)
    if (!node) return
    setCurrentNode(id)
    if (node.data.role === "image") setComposerOpen(edit)
    else setComposerOpen(false)
    actions.select(node.data.asset.id)
  }
  const openEditor = (id: string, kind: "definition" | "metadata") => {
    const node = graph.nodes.find(item => item.id === id)
    if (!node) return
    choose(id, false); setEditKind(kind); setEditNode(id)
    setEditName(kind === "definition" ? node.data.asset.name : node.data.title)
    setEditRole(node.data.asset.role || "")
    setEditText(assetDefinitionText(node.data.asset))
  }
  const saveEditor = async () => {
    const node = graph.nodes.find(item => item.id === editNode)
    if (!node || !editName.trim()) { message.warning("名称不能为空"); return }
    setEditing(true)
    try {
      if (editKind === "definition") await actions.saveDefinition(node.data.asset.id, editName.trim(), editRole.trim(), editText)
      else if (node.data.target) await actions.saveMetadata(node.data.asset.id, node.data.target, editName.trim())
      setEditNode(null)
    } catch (err) { message.error(err instanceof Error ? err.message : "保存失败，修改已保留") }
    finally { setEditing(false) }
  }
  const chooseFile = (id: string, library: boolean) => {
    choose(id, false); setFileTarget(id)
    if (library) setMediaPicker(true)
    else requestAnimationFrame(() => uploadRef.current?.click())
  }
  const uploadFiles = async (files: File[]) => {
    const node = graph.nodes.find(item => item.id === fileTarget)
    if (node) await actions.upload(node.data.asset.id, node.data.target || null, files)
  }
  const context: CanvasContext = { actions, working, choose, editDefinition: id => openEditor(id, "definition"), editMetadata: id => openEditor(id, "metadata"), chooseFile, preview: (url, title) => openMediaPreview({ src: url, title }) }
  const filtered = assets.filter(asset => (libraryKind === "all" || asset.kind === libraryKind) && (!search.trim() || `${asset.name} ${asset.description || ""}`.toLowerCase().includes(search.trim().toLowerCase())))

  return <div className="asset-creation-canvas">
    <header className="ac-header"><div className="ac-header-start"><strong>制作资产库</strong><Segmented aria-label="资产视图" value="canvas" options={[{ value: "list", label: "列表", icon: <LayoutGrid size={13}/> }, { value: "canvas", label: "画布", icon: <Workflow size={13}/> }]} onChange={value => { if (value === "list") void actions.showList() }}/><span className="ac-node-count">节点 {graph.nodes.filter(node => node.data.role !== "group").length}</span></div><div className="ac-header-end"><Button type="text" size="small" icon={props.saveError ? <RefreshCw size={13}/> : <Save size={13}/>} danger={props.saveError} onClick={() => void actions.save().catch(err => message.error(err instanceof Error ? err.message : "保存失败，修改仍保留在画布"))}>{props.saveStatus}</Button><Dropdown trigger={["click"]} menu={{ items: ["character", "scene", "prop"].map(kind => ({ key: kind, label: `新增${kindLabel(kind)}`, onClick: () => actions.create(kind) })) }}><Button size="small" icon={<Plus size={14}/>}>新增节点<ChevronDown size={12}/></Button></Dropdown></div></header>
    <div className="ac-stage" ref={stageRef}>
      <Context.Provider value={context}>
        <Dropdown trigger={["contextMenu"]} open={contextMenuOpen} onOpenChange={setContextMenuOpen} autoFocus destroyOnHidden disabled={props.loading} classNames={{ root: "ac-context-menu" }} menu={{
          "aria-label": "画布右键菜单",
          triggerSubMenuAction: "click",
          items: [
            { key: "add", label: "添加节点", icon: <Plus size={15}/>, children: ["character", "scene", "prop"].map(kind => { const Icon = getKindIcon(kind); return { key: kind, label: kindLabel(kind), icon: <Icon size={15}/> } }) },
            { type: "divider" },
            { key: "assets", label: "打开资产库", icon: <Boxes size={15}/> },
            { key: "fit", label: "适应全部节点", icon: <Maximize2 size={15}/> },
          ],
          onClick: ({ key }) => {
            setContextMenuOpen(false)
            if (["character", "scene", "prop"].includes(key)) actions.create(key, contextOrigin.current || undefined)
            else if (key === "assets") setDrawerOpen(true)
            else if (key === "fit") void flow.fitView({ padding: .15, maxZoom: 1 })
          },
          onKeyDown: event => { if (event.key === "Escape") setContextMenuOpen(false) },
        }}>
          <div className="ac-flow-surface" onPointerDownCapture={event => { if (event.button === 0) setContextMenuOpen(false) }} onContextMenuCapture={event => {
            if (event.target instanceof Element && event.target.closest(".ac-node, .react-flow__panel, .react-flow__minimap, .react-flow__attribution, button, a, input, textarea, [contenteditable='true']")) { event.stopPropagation(); return }
            contextOrigin.current = flow.screenToFlowPosition({ x: event.clientX, y: event.clientY })
          }}>
        <ReactFlow<AssetCanvasNode> nodes={nodes} edges={graph.edges} nodeTypes={nodeTypes} deleteKeyCode={null} minZoom={.15} maxZoom={1.6} nodesConnectable onConnect={(connection: Connection) => { if (connection.source && connection.target) actions.connect(connection.source, connection.target) }} onNodesChange={changes => setNodes(previous => applyNodeChanges(changes.filter(change => change.type !== "remove"), previous))} onNodeClick={(_event, node) => choose(node.id)} onNodeDoubleClick={(_event, node) => node.data.role === "definition" ? openEditor(node.id, "definition") : node.data.role === "image" ? choose(node.id) : undefined} onPaneClick={() => { setContextMenuOpen(false); setComposerOpen(false) }} onNodeDragStop={(_event, node) => actions.position(node.data.asset.id, node.data.key, node.position)} onMoveStart={() => setContextMenuOpen(false)} onMoveEnd={(_event, viewport) => { setZoom(viewport.zoom); try { localStorage.setItem(viewportKey, JSON.stringify(viewport)) } catch { /* optional viewport preference */ } }} onInit={instance => { if (selectedId) return; try { const raw = JSON.parse(localStorage.getItem(viewportKey) || "null"); if (raw && [raw.x, raw.y, raw.zoom].every(Number.isFinite)) { void instance.setViewport(raw); return } } catch { /* fall through to fit */ } void instance.fitView({ padding: .2, maxZoom: .8 }) }}>
          <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="var(--studio-border)"/>
          <Panel position="top-left"><Button size="small" icon={<Boxes size={13}/>} onClick={() => setDrawerOpen(true)}>资产库</Button></Panel>
          <Panel position="bottom-left"><div className="ac-viewport-tools"><Tooltip title="缩小"><Button type="text" aria-label="缩小画布" icon={<ZoomOut size={15}/>} onClick={() => void flow.zoomOut()}/></Tooltip><Tooltip title="放大"><Button type="text" aria-label="放大画布" icon={<ZoomIn size={15}/>} onClick={() => void flow.zoomIn()}/></Tooltip><Tooltip title="适应全部节点"><Button type="text" aria-label="适应全部节点" icon={<Maximize2 size={15}/>} onClick={() => void flow.fitView({ padding: .15, maxZoom: 1 })}/></Tooltip><Tooltip title="画布小地图"><Button type="text" aria-label="画布小地图" aria-pressed={miniMap} icon={<Map size={15}/>} onClick={() => setMiniMap(!miniMap)}/></Tooltip><span>{Math.round(zoom * 100)}%</span></div></Panel>
          {miniMap && <MiniMap position="bottom-right" pannable zoomable nodeColor="var(--studio-surface-raised)" maskColor="var(--studio-canvas)"/>}
        </ReactFlow>
          </div>
        </Dropdown>
      </Context.Provider>
      {props.loading && <div className="ac-loading"><Spin/><span>正在读取项目资产</span></div>}
      {!props.loading && !assets.length && <div className="ac-empty-canvas"><Empty description="从一个角色、场景或道具开始"/><Button type="primary" icon={<Plus size={15}/>} onClick={() => actions.create("character")}>创建角色节点</Button></div>}
      {composerOpen && imageNode?.data.target && <section className="ac-composer" aria-label={`${imageNode.data.asset.name} · ${imageNode.data.title}创作面板`}>
        <header><span><Sparkles size={14}/>{imageNode.data.asset.name} · {imageNode.data.title}</span><Button type="text" size="small" aria-label="收起创作面板" icon={<X size={14}/>} onClick={() => setComposerOpen(false)}/></header>
        <Input.TextArea aria-label="节点创作提示词" value={assetSlotPrompt(imageNode.data.asset, imageNode.data.target)} onChange={event => actions.prompt(imageNode.data.asset.id, imageNode.data.target!, event.target.value)} placeholder="描述你想要的画面，参考图与角色档案会一起用于生成" autoSize={{ minRows: 3, maxRows: 7 }} variant="borderless" onKeyDown={event => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !working && !blocker) { event.preventDefault(); void actions.generate(imageNode.data.asset.id, imageNode.data.target!) } }}/>
        {props.errors?.[imageNode.id] && working === null && <Alert type="error" title={props.errors[imageNode.id]} showIcon/>}
        {blocker && <p className="ac-composer-hint">{blocker}</p>}
        <footer><div><Button type="text" size="small" icon={<ImageIcon size={14}/>} onClick={() => chooseFile(assetNodeId(imageNode.data.asset.id, "references"), false)}>参考图 {sourceReferencesOf(imageNode.data.asset).length}/9</Button><span>{imageNode.data.target.type === "scene_pano" ? "2:1" : "16:9"}</span><span>默认图片模型</span></div><Button type="primary" icon={<Sparkles size={14}/>} loading={working === imageNode.id} disabled={props.loading || !!working || !!blocker} onClick={() => void actions.generate(imageNode.data.asset.id, imageNode.data.target!)}>{imageNode.data.image ? "重新生成" : "生成图片"}</Button></footer>
      </section>}
      {!composerOpen && actions.continue && <div className="ac-next-step"><span>角色和场景设定会应用到后续分镜</span><Button type="primary" icon={<ArrowRight size={14}/>} iconPlacement="end" onClick={() => void actions.continue?.()}>进入分镜</Button></div>}
    </div>
    <Drawer title="资产库" open={drawerOpen} placement="left" size={320} onClose={() => setDrawerOpen(false)} rootClassName="ac-library-drawer"><Input aria-label="搜索画布资产" placeholder="搜索角色、场景、道具" prefix={<Search size={13}/>} value={search} onChange={event => setSearch(event.target.value)}/><Segmented value={libraryKind} aria-label="画布资产分类" options={[{ value: "all", label: "全部" }, ...["character", "scene", "prop"].map(kind => ({ value: kind, label: kindLabel(kind) }))]} onChange={value => setLibraryKind(String(value))}/><div className="ac-library-items">{filtered.map(asset => { const image = getAssetDisplayAvatar(asset); const Icon = getKindIcon(asset.kind); return <Button type="text" key={asset.id} className={asset.id === selectedId ? "is-selected" : ""} onClick={() => { actions.select(asset.id); setDrawerOpen(false); setComposerOpen(false) }}>{image ? <img src={image} alt=""/> : <Icon size={22}/>}<span><strong>{asset.name}</strong><small>{kindLabel(asset.kind)} · {assetReadiness(asset).label}</small></span><ArrowRight size={13}/></Button> })}</div></Drawer>
    <Modal title={editKind === "definition" ? `编辑${currentAsset ? kindLabel(currentAsset.kind) : "资产"}档案` : "编辑图片节点名称"} open={!!editNode} onCancel={() => setEditNode(null)} onOk={() => void saveEditor()} confirmLoading={editing} okText="保存" cancelText="取消" width={600} destroyOnHidden>
      <Form layout="vertical"><Form.Item label={editKind === "definition" ? "名称" : "形象 / 视角名称"} required><Input aria-label="画布节点名称" value={editName} onChange={event => setEditName(event.target.value)} maxLength={120}/></Form.Item>{editKind === "definition" && <><Form.Item label="定位"><Input value={editRole} onChange={event => setEditRole(event.target.value)} placeholder="例如：女主角、咖啡店外景、随身道具"/></Form.Item><Form.Item label="创作设定"><Input.TextArea aria-label="画布资产设定" value={editText} onChange={event => setEditText(event.target.value)} autoSize={{ minRows: 7, maxRows: 16 }} placeholder="描述外观、材质、环境与不可变细节"/></Form.Item></>}</Form>
    </Modal>
    <input className="ac-file-input" type="file" accept="image/jpeg,image/png,image/webp,image/gif" multiple={graph.nodes.find(node => node.id === fileTarget)?.data.role === "references"} ref={uploadRef} onChange={event => { const files = Array.from(event.target.files || []); event.target.value = ""; void uploadFiles(files) }}/>
    <AssetPickerModal open={mediaPicker} onClose={() => setMediaPicker(false)} onPick={file => void uploadFiles([file])}/>
  </div>
}

export function AssetCanvasCreateModal({ open, kind, busy, onCancel, onSubmit }: { open: boolean; kind: string; busy: boolean; onCancel: () => void; onSubmit: (name: string, description: string) => void }) {
  const [name, setName] = useState(""), [description, setDescription] = useState("")
  useEffect(() => { if (open) { setName(""); setDescription("") } }, [open])
  return <Modal title={`新增${kindLabel(kind)}节点`} open={open} onCancel={onCancel} okText="创建并进入画布" cancelText="取消" confirmLoading={busy} onOk={() => { if (!name.trim()) message.warning("请输入名称"); else onSubmit(name.trim(), description) }} destroyOnHidden width={480}><Form layout="vertical"><Form.Item label={`${kindLabel(kind)}名称`} required><Input aria-label="新资产名称" value={name} onChange={event => setName(event.target.value)} maxLength={120}/></Form.Item><Form.Item label="初始设定（选填）"><Input.TextArea aria-label="新资产设定" value={description} onChange={event => setDescription(event.target.value)} autoSize={{ minRows: 3, maxRows: 6 }} placeholder="可以先创建节点，再在画布上完善"/></Form.Item></Form></Modal>
}
