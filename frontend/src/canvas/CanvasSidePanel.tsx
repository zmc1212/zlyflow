import { useReactFlow } from "@xyflow/react"
import {
  Button, Collapse, Empty, Input, InputNumber, List, Popconfirm, Segmented, Spin, Switch, Tabs, Tag, Tooltip, Typography,
} from "antd"
import {
  ChevronRight, CircleHelp, CopyPlus, Crosshair, FolderOpen, Frame, History, Image as ImageIcon, Images, Layers, Redo2, RefreshCw,
  Scan, Search, Sparkles, Trash2, Type, Undo2, Video, X,
} from "lucide-react"
import { memo, useMemo, useState, type ReactNode } from "react"
import type { CanvasMediaPreview } from "./CanvasNodes"
import {
  canvasNodeTypeLabel,
  formatCanvasTime,
  type CanvasBranchDirection,
  type CanvasConnectionMode,
  type CanvasCoverPatch,
  type CanvasGenerationDisplayMode,
  type CanvasMediaKind,
  type CanvasNode,
  type CanvasSettings,
  type CanvasVersion,
} from "./canvas-model"
import { CANVAS_CONNECTION_MODE_OPTIONS, CANVAS_GENERATION_MODE_OPTIONS } from "./canvas-view-modes"
import { formatCanvasBytes } from "./canvas-save"
import type { CanvasGeneratorLive, CanvasWorkflowMode } from "./canvas-generation"
import { CanvasGeneratorInspector } from "./CanvasGeneratorInspector"
import { CanvasNodeInspector } from "./CanvasInspector"

export type CanvasPanelTab = "properties" | "layers" | "history"

export type CanvasSidePanelProps = {
  tab: CanvasPanelTab
  onTabChange: (tab: CanvasPanelTab) => void
  onClose: () => void
  nodes: CanvasNode[]
  edgeCount: number
  selectedNode: CanvasNode | null
  settings: CanvasSettings
  onSettingsChange: (patch: Partial<CanvasSettings>) => void
  onSelectNode: (nodeId: string) => void
  onFocusNode: (nodeId: string) => void
  onDeleteNode: (nodeId: string) => void
  onDuplicateNode: (nodeId: string) => void
  onOpenAssetLibrary: () => void
  onPreview: (preview: CanvasMediaPreview) => void
  onReplaceAsset: (nodeId: string, kind: CanvasMediaKind) => void
  onUpdateCover: (nodeId: string, patch: CanvasCoverPatch) => void
  modes: CanvasWorkflowMode[]
  modesLoading: boolean
  modesError: string | null
  onReloadModes: () => void
  references: CanvasNode[]
  promptNodes: CanvasNode[]
  live: CanvasGeneratorLive | null
  submitting: boolean
  onSubmit: (nodeId: string) => void
  onCancel: (nodeId: string) => void
  onRefine: (nodeId: string, action: "confirm" | "skip") => void
  onInsertResult: (nodeId: string, direction: CanvasBranchDirection) => void
  onOpenJob: (jobId: string, kind?: CanvasMediaKind) => void
  historyState: { canUndo: boolean; canRedo: boolean }
  onUndo: () => void
  onRedo: () => void
  versions: CanvasVersion[]
  versionsLoading: boolean
  onRefreshVersions: () => void
  onRestoreVersion: (version: number) => void
  projectTitle: string
  contentBytes: number
  savedAt?: string | null
}

function nodeIcon(type: string | undefined): ReactNode {
  if (type === "text") return <Type size={14} />
  if (type === "image") return <ImageIcon size={14} />
  if (type === "video") return <Video size={14} />
  if (type === "artboard") return <Frame size={14} />
  if (type === "generator") return <Sparkles size={14} />
  return <CircleHelp size={14} />
}

function nodeTitle(node: CanvasNode): string {
  return String(node.data.label ?? "").trim()
    || String(node.data.text ?? "").trim().slice(0, 36)
    || String(node.data.prompt ?? "").trim().slice(0, 36)
    || `${canvasNodeTypeLabel(node.type)}节点`
}

export const CanvasSidePanel = memo(function CanvasSidePanel(props: CanvasSidePanelProps) {
  const {
    tab, onTabChange, onClose, nodes, selectedNode,
  } = props
  return (
    <aside className="canvas-side-panel" aria-label="画布属性面板">
      <div className="canvas-side-panel-head">
        <Tabs
          activeKey={tab}
          onChange={(key) => onTabChange(key as CanvasPanelTab)}
          items={[
            { key: "properties", label: <span className="canvas-panel-tab"><ImageIcon size={20} />属性</span> },
            { key: "layers", label: <span className="canvas-panel-tab"><Layers size={16} /><span className="canvas-panel-tab-copy">图层<span className="canvas-tab-count">{nodes.length}</span></span></span> },
            { key: "history", label: <span className="canvas-panel-tab"><History size={14} />历史</span> },
          ]}
        />
        <Tooltip title="收起面板"><Button size="small" type="text" icon={<X size={15} />} aria-label="关闭属性面板" onClick={onClose} /></Tooltip>
      </div>
      <div className="canvas-side-panel-body">
        {tab === "properties" ? (
          selectedNode
            ? <NodeProperties {...props} node={selectedNode} />
            : <CanvasProperties {...props} />
        ) : null}
        {tab === "layers" ? <CanvasLayers {...props} /> : null}
        {tab === "history" ? <CanvasHistory {...props} /> : null}
      </div>
      {tab === "properties" && !selectedNode ? <div className="canvas-side-panel-footer"><Button block className="canvas-library-entry" aria-label="从作品库插入素材" icon={<FolderOpen size={18} />} onClick={props.onOpenAssetLibrary}>从作品库插入<ChevronRight size={16} /></Button></div> : null}
    </aside>
  )
})

function NodeProperties(props: CanvasSidePanelProps & { node: CanvasNode }) {
  const {
    node, onPreview, onReplaceAsset, modes, modesLoading, modesError, onReloadModes,
    references, promptNodes, live, submitting, onSubmit, onCancel, onInsertResult, onOpenJob,
  } = props
  return (
    <div className="canvas-panel-node">
      <div className="canvas-panel-node-head">
        <span className={`canvas-panel-symbol is-${node.type}`}>{nodeIcon(node.type)}</span>
        <div><strong title={nodeTitle(node)}>{nodeTitle(node)}</strong><span className="canvas-panel-node-kind">{canvasNodeTypeLabel(node.type)}节点</span></div>
      </div>
      {node.type === "generator" ? (
        <CanvasGeneratorInspector
          node={node}
          modes={modes}
          modesLoading={modesLoading}
          modesError={modesError}
          onReloadModes={onReloadModes}
          references={references}
          promptNodes={promptNodes}
          live={live}
          submitting={submitting}
          onPreview={onPreview}
          onSubmit={onSubmit}
          onCancel={onCancel}
          onRefine={props.onRefine}
          onInsertResult={onInsertResult}
          onOpenJob={onOpenJob}
        />
      ) : (
        <CanvasNodeInspector
          node={node}
          onPreview={onPreview}
          onReplaceAsset={onReplaceAsset}
          onUpdateCover={props.onUpdateCover}
          onOpenJob={props.onOpenJob}
        />
      )}
      <Collapse
        className="canvas-detail-collapse"
        ghost
        items={[{ key: "geometry", label: "位置与节点信息", children: <><CanvasGeometrySection node={node} /><div className="canvas-node-id"><span>节点 ID</span><Typography.Text code copyable={{ text: node.id }} ellipsis>{node.id}</Typography.Text></div></> }]}
      />
    </div>
  )
}

function CanvasGeometrySection({ node }: { node: CanvasNode }) {
  const { setNodes } = useReactFlow()
  const measuredWidth = Number(node.measured?.width ?? node.style?.width ?? node.width ?? 0)
  const measuredHeight = Number(node.measured?.height ?? node.style?.height ?? node.height ?? 0)

  const moveNode = (axis: "x" | "y", value: number | null) => {
    if (value === null || !Number.isFinite(value)) return
    setNodes((current) => current.map((item) => (
      item.id === node.id
        ? { ...item, position: { ...item.position, [axis]: value } }
        : item
    )))
  }

  const resizeNode = (dimension: "width" | "height", value: number | null) => {
    if (value === null || !Number.isFinite(value)) return
    setNodes((current) => current.map((item) => {
      if (item.id !== node.id) return item
      return {
        ...item,
        style: { ...item.style, [dimension]: value },
        [dimension]: value,
      } as CanvasNode
    }))
  }

  return (
    <section className="canvas-inspector-section canvas-geometry-section">
      <h4 className="canvas-inspector-section-title">位置与尺寸</h4>
      <div className="canvas-geometry-grid">
        <label>
          <span>X</span>
          <InputNumber
            aria-label="节点 X 坐标"
            size="small"
            value={Math.round(node.position.x)}
            step={1}
            onChange={(value) => moveNode("x", value)}
          />
        </label>
        <label>
          <span>Y</span>
          <InputNumber
            aria-label="节点 Y 坐标"
            size="small"
            value={Math.round(node.position.y)}
            step={1}
            onChange={(value) => moveNode("y", value)}
          />
        </label>
        <label>
          <span>宽</span>
          <InputNumber
            aria-label="节点宽度"
            size="small"
            min={40}
            value={Math.round(measuredWidth)}
            step={10}
            onChange={(value) => resizeNode("width", value)}
          />
        </label>
        <label>
          <span>高</span>
          <InputNumber
            aria-label="节点高度"
            size="small"
            min={40}
            value={Math.round(measuredHeight)}
            step={10}
            onChange={(value) => resizeNode("height", value)}
          />
        </label>
      </div>
    </section>
  )
}

function CanvasProperties(props: CanvasSidePanelProps) {
  const {
    nodes, edgeCount, settings, onSettingsChange, projectTitle, contentBytes, savedAt,
  } = props
  const counts = useMemo(() => ({
    image: nodes.filter((node) => node.type === "image").length,
    video: nodes.filter((node) => node.type === "video").length,
    text: nodes.filter((node) => node.type === "text").length,
    generator: nodes.filter((node) => node.type === "generator").length,
  }), [nodes])
  const connectionDescription = CANVAS_CONNECTION_MODE_OPTIONS.find((option) => option.value === settings.connectionMode)?.description
  const generationDescription = CANVAS_GENERATION_MODE_OPTIONS.find((option) => option.value === settings.generationDisplayMode)?.description

  return (
    <div className="canvas-panel-canvas">
      <section className="canvas-inspector-section canvas-overview">
        <div className="canvas-panel-intro"><span className="canvas-panel-symbol"><Scan size={25} /></span><div><h3>画布设置</h3><p title={projectTitle}>{projectTitle}</p></div></div>
        <div className="canvas-overview-stats">
          <Tooltip title={`${counts.image} 张图片 · ${counts.video} 个视频 · ${counts.text} 个文字 · ${counts.generator} 个生成节点`}><div><strong>{nodes.length}</strong><span>节点</span></div></Tooltip>
          <div><strong>{edgeCount}</strong><span>连线</span></div>
          <Tooltip title={`最近保存：${formatCanvasTime(savedAt)}`}><div><strong>{formatCanvasBytes(contentBytes)}</strong><span>画布大小</span></div></Tooltip>
        </div>
      </section>

      <section className="canvas-inspector-section canvas-view-settings">
        <h4 className="canvas-inspector-section-title">视图显示</h4>
        <div className="canvas-setting-row">
          <span>点阵网格</span>
          <Switch
            size="small"
            aria-label="点阵网格"
            checked={settings.gridVisible}
            onChange={(checked) => onSettingsChange({ gridVisible: checked })}
          />
        </div>
        <div className="canvas-setting-row">
          <span>小地图</span>
          <Switch
            size="small"
            aria-label="显示小地图"
            checked={settings.minimapVisible}
            onChange={(checked) => onSettingsChange({ minimapVisible: checked })}
          />
        </div>
        <div className="canvas-setting-row">
          <span>对齐参考线</span>
          <Switch
            size="small"
            aria-label="对齐参考线"
            checked={settings.guidesVisible}
            onChange={(checked) => onSettingsChange({ guidesVisible: checked })}
          />
        </div>
      </section>

      <section className="canvas-inspector-section canvas-connection-settings">
        <div className="canvas-setting-block">
          <span className="canvas-inspector-field-label">连线</span>
          <Segmented
            block
            value={settings.connectionMode}
            onChange={(value) => onSettingsChange({ connectionMode: value as CanvasConnectionMode })}
            options={CANVAS_CONNECTION_MODE_OPTIONS.map((option) => ({ label: option.label, value: option.value }))}
          />
          <p className="canvas-inspector-hint">{connectionDescription}</p>
        </div>
      </section>
      <section className="canvas-inspector-section canvas-generation-settings">
        <div className="canvas-setting-block">
          <span className="canvas-inspector-field-label">生成节点展示方式</span>
          <Segmented
            block
            value={settings.generationDisplayMode}
            onChange={(value) => onSettingsChange({ generationDisplayMode: value as CanvasGenerationDisplayMode })}
            options={CANVAS_GENERATION_MODE_OPTIONS.map((option) => ({ label: option.label, value: option.value }))}
          />
          <p className="canvas-inspector-hint">{generationDescription}</p>
        </div>
      </section>

      <section className="canvas-inspector-section canvas-global-settings">
        <Tooltip title="只作为新生成节点的初始提示词，不会覆盖已有节点。"><h4 className="canvas-inspector-section-title">全局提示词</h4></Tooltip>
        <div className="canvas-inspector-field">
          <Input.TextArea
            id="canvas-global-prompt"
            name="canvas-global-prompt"
            aria-label="全局提示词"
            className="canvas-global-prompt"
            value={settings.globalPrompt}
            rows={3}
            maxLength={2000}
            showCount
            placeholder="新建生成节点时自动填入的画风、角色或项目约定…"
            onChange={(event) => onSettingsChange({ globalPrompt: event.target.value })}
          />
        </div>
      </section>

    </div>
  )
}

function CanvasLayers({ nodes, selectedNode, onSelectNode, onFocusNode, onDeleteNode, onDuplicateNode }: CanvasSidePanelProps) {
  const [query, setQuery] = useState("")
  const ordered = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    return [...nodes]
      .filter((node) => {
        if (!keyword) return true
        const haystack = `${nodeTitle(node)} ${canvasNodeTypeLabel(node.type)} ${node.data.label ?? ""}`.toLowerCase()
        return haystack.includes(keyword)
      })
      .sort((left, right) => (
        (left.zIndex ?? 1) - (right.zIndex ?? 1)
        || left.position.y - right.position.y
        || left.position.x - right.position.x
      ))
  }, [nodes, query])

  return (
    <div className="canvas-panel-layers">
      <Input
        id="canvas-layer-search"
        name="canvas-layer-search"
        allowClear
        prefix={<Search size={14} />}
        aria-label="搜索图层"
        value={query}
        placeholder="搜索节点…"
        onChange={(event) => setQuery(event.target.value)}
      />
      {ordered.length ? (
        <div className="canvas-layer-list">
          {ordered.map((node) => (
            <div
              key={node.id}
              className={`canvas-layer-row${selectedNode?.id === node.id ? " is-active" : ""}`}
            >
              <button
                type="button"
                className="canvas-layer-main"
                onClick={() => onSelectNode(node.id)}
              >
                <span className="canvas-layer-icon">{nodeIcon(node.type)}</span>
                <span className="canvas-layer-text">
                  <strong>{nodeTitle(node)}</strong>
                  <small>
                    {canvasNodeTypeLabel(node.type)}
                  </small>
                </span>
              </button>
              <span className="canvas-layer-actions" onClick={(event) => event.stopPropagation()}>
                <Tooltip title="定位节点">
                  <Button size="small" type="text" aria-label={`定位 ${nodeTitle(node)}`} icon={<Crosshair size={13} />} onClick={() => onFocusNode(node.id)} />
                </Tooltip>
                <Tooltip title="复制节点">
                  <Button size="small" type="text" aria-label={`复制 ${nodeTitle(node)}`} icon={<CopyPlus size={13} />} onClick={() => onDuplicateNode(node.id)} />
                </Tooltip>
                <Popconfirm
                  classNames={{ root: "canvas-popover canvas-confirm-popover" }}
                  title="删除这个节点？"
                  description="与它相连的连线也会一并删除。"
                  okText="删除"
                  okButtonProps={{ danger: true }}
                  cancelText="取消"
                  onConfirm={() => onDeleteNode(node.id)}
                >
                  <Button size="small" type="text" danger aria-label={`删除 ${nodeTitle(node)}`} icon={<Trash2 size={13} />} />
                </Popconfirm>
              </span>
            </div>
          ))}
        </div>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={nodes.length ? "没有匹配的节点，试试其他关键词" : "画布上还没有节点，从左侧添加一个吧"} />
      )}
    </div>
  )
}

function CanvasHistory(props: CanvasSidePanelProps) {
  const {
    historyState, onUndo, onRedo, versions, versionsLoading, onRefreshVersions, onRestoreVersion,
  } = props
  return (
    <div className="canvas-panel-history">
      <section className="canvas-inspector-section">
        <h4 className="canvas-inspector-section-title">本次编辑</h4>
        <div className="canvas-inspector-actions">
          <Button icon={<Undo2 size={15} />} disabled={!historyState.canUndo} onClick={onUndo}>撤销</Button>
          <Button icon={<Redo2 size={15} />} disabled={!historyState.canRedo} onClick={onRedo}>重做</Button>
        </div>
        <p className="canvas-inspector-hint">最多保留最近 50 步画布改动，相机位置和面板开关不进入撤销栈。</p>
      </section>

      <section className="canvas-inspector-section">
        <div className="canvas-panel-section-head">
          <h4 className="canvas-inspector-section-title">服务器版本</h4>
          <Button
            size="small"
            type="text"
            icon={<RefreshCw size={13} />}
            loading={versionsLoading}
            onClick={onRefreshVersions}
          >
            刷新
          </Button>
        </div>
        {versionsLoading ? (
          <div className="canvas-panel-loading"><Spin size="small" /><span>正在加载版本…</span></div>
        ) : versions.length ? (
          <List
            size="small"
            dataSource={versions}
            className="canvas-version-list"
            renderItem={(row) => (
              <List.Item
                actions={[
                  <Popconfirm
                    classNames={{ root: "canvas-popover canvas-confirm-popover" }}
                    key="restore"
                    title={`恢复到 v${row.version}？`}
                    description="当前内容会作为新版本保留。"
                    okText="恢复"
                    cancelText="取消"
                    onConfirm={() => onRestoreVersion(row.version)}
                  >
                    <Button size="small" type="link">恢复</Button>
                  </Popconfirm>,
                ]}
              >
                <List.Item.Meta
                  avatar={<History size={15} />}
                  title={`v${row.version} · ${row.node_count} 个节点`}
                  description={formatCanvasTime(row.created_at)}
                />
              </List.Item>
            )}
          />
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="保存后，你可以在这里找回历史版本" />
        )}
      </section>

      <section className="canvas-inspector-section">
        <h4 className="canvas-inspector-section-title">节点层级</h4>
        <div className="canvas-info-grid">
          <div><span>图层</span><strong>{props.nodes.length}</strong></div>
          <div><span>连线</span><strong>{props.edgeCount}</strong></div>
        </div>
        <Button icon={<Layers size={15} />} onClick={() => props.onTabChange("layers")}>打开图层列表</Button>
      </section>
    </div>
  )
}
