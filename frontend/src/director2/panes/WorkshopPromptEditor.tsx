import { createContext, forwardRef, useContext, useEffect, useImperativeHandle, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { Alert, Button, Empty, Image, Menu, Popover } from "antd"
import { Box, ChevronDown, UserRound } from "lucide-react"
import { EditorContent, NodeViewWrapper, ReactNodeViewRenderer, useEditor, type NodeViewProps } from "@tiptap/react"
import StarterKit from "@tiptap/starter-kit"
import Mention, { type MentionNodeAttrs } from "@tiptap/extension-mention"
import { exitSuggestion, type SuggestionProps } from "@tiptap/suggestion"
import { assetKindLabel, promptText, referenceNode, type PromptDocument, type WorkshopAsset } from "../workshop-editor"

const AssetContext = createContext<WorkshopAsset[]>([])
export type WorkshopPromptEditorHandle = { insert: (asset: WorkshopAsset) => void }

export function WorkshopAssetThumbnail({ asset }: { asset: WorkshopAsset }) {
  return asset.image ? <img src={asset.image} alt="" loading="lazy"/> : <span className="ws-asset-fallback">{asset.kind === "character" ? <UserRound size={14}/> : <Box size={14}/>}</span>
}

export function WorkshopAssetCard({ asset, onInsert }: { asset: WorkshopAsset; onInsert?: () => void }) {
  return <div className="ws-asset-card">
    <div className="ws-asset-card-image" data-kind={asset.kind}>{asset.image ? <Image src={asset.image} alt={asset.title} preview={{ cover: "放大查看" }}/> : <div className="ws-missing-image"><Box size={28}/><span>暂无参考图</span></div>}</div>
    <div className="ws-asset-card-name"><strong>{asset.name}</strong><span>{assetKindLabel(asset.kind)}</span></div>
    {asset.variant && <p>{asset.variant}</p>}
    {onInsert && <Button block onClick={onInsert}>引用到光标位置</Button>}
  </div>
}

function ReferenceView({ node, editor, updateAttributes, getPos }: NodeViewProps) {
  const entries = useContext(AssetContext)
  const [open, setOpen] = useState(false)
  const asset = entries.find(a => a.id === node.attrs.id && a.lookId === (node.attrs.lookId || null))
  const replace = (next: WorkshopAsset) => {
    updateAttributes(referenceNode(next).attrs!)
    setOpen(false)
    editor.commands.focus()
  }
  const convert = () => {
    const pos = getPos()
    if (typeof pos === "number") editor.chain().focus().insertContentAt({ from: pos, to: pos + node.nodeSize }, { type: "text", text: String(node.attrs.label || "") }).run()
    setOpen(false)
  }
  const content = <div className="ws-reference-popover" onMouseDown={event => event.preventDefault()}>
    {asset ? <WorkshopAssetCard asset={asset}/> : <Alert type="warning" title="引用资产已不可用" description="请替换引用，或将它转为普通文字。" showIcon/>}
    <div className="ws-reference-section">替换本处引用</div>
    <Menu selectable selectedKeys={asset ? [asset.key] : []} items={entries.filter(a => a.kind === (asset?.kind || node.attrs.kind)).map(a => ({ key: a.key, label: <span className="ws-reference-choice"><WorkshopAssetThumbnail asset={a}/><span>{a.title}</span></span>, onClick: () => replace(a) }))}/>
    <Button type="text" block className="ws-reference-convert" onClick={convert}>转为普通文字</Button>
  </div>
  return <NodeViewWrapper as="span" className="ws-reference-node" contentEditable={false}>
    <Popover open={open} onOpenChange={setOpen} trigger="click" placement="bottomLeft" arrow={false} content={content}>
      <Button disabled={!editor.isEditable} className={"ws-mention" + (!asset ? " is-unavailable" : "")} data-asset-id={node.attrs.id} data-look-id={node.attrs.lookId || ""} aria-label={"资产引用 " + (asset?.title || node.attrs.label)} onMouseDown={event => event.preventDefault()}>
        {asset ? <WorkshopAssetThumbnail asset={asset}/> : <Box size={12}/>}
        <span>{asset?.title || node.attrs.label || "已删除资产"}</span>
        {(asset?.kind || node.attrs.kind) === "character" && <ChevronDown size={8}/>}
      </Button>
    </Popover>
  </NodeViewWrapper>
}

const AssetMention = Mention.extend({
  name: "assetReference",
  addAttributes() { return { ...this.parent?.(), lookId: { default: null }, kind: { default: "" } } },
  addNodeView() { return ReactNodeViewRenderer(ReferenceView) },
})

type AssetSuggestion = SuggestionProps<WorkshopAsset, MentionNodeAttrs>
type SuggestionState = { props: AssetSuggestion; selected: number; rect: DOMRect }

export const WorkshopPromptEditor = forwardRef<WorkshopPromptEditorHandle, {
  document: PromptDocument; assets: WorkshopAsset[]; label: string; disabled?: boolean
  onChange: (doc: PromptDocument) => void; onSave: (force?: boolean) => void
}>(function WorkshopPromptEditor({ document, assets, label, disabled, onChange, onSave }, ref) {
  const callbacks = useRef({ assets, onChange, onSave })
  callbacks.current = { assets, onChange, onSave }
  const [suggestion, setSuggestion] = useState<SuggestionState | null>(null)
  const suggestionRef = useRef<SuggestionState | null>(null)
  const editor = useEditor({
    extensions: [
      StarterKit.configure({ blockquote: false, bold: false, bulletList: false, code: false, codeBlock: false, heading: false, horizontalRule: false, italic: false, listItem: false, listKeymap: false, orderedList: false, strike: false, underline: false, link: false, trailingNode: false }),
      AssetMention.configure({
        renderText: ({ node }) => String(node.attrs.label || ""),
        deleteTriggerWithBackspace: true,
        suggestion: {
          char: "@", allowedPrefixes: null,
          items: ({ query }) => callbacks.current.assets.filter(a => (a.name + a.variant).toLowerCase().includes(query.toLowerCase())),
          render: () => {
            const update = (props: AssetSuggestion) => {
              const rect = props.clientRect?.()
              if (!rect) return
              const next = { props, selected: 0, rect }
              suggestionRef.current = next; setSuggestion(next)
            }
            const choose = (state: SuggestionState) => {
              const asset = state.props.items[state.selected]
              if (asset) state.props.command(referenceNode(asset).attrs!)
            }
            return {
              onStart: update, onUpdate: update,
              onKeyDown: ({ event, view }) => {
                if (event.key === "Escape") { exitSuggestion(view); return true }
                const state = suggestionRef.current
                if (!state || !state.props.items.length) return false
                if (event.key === "ArrowUp" || event.key === "ArrowDown") {
                  const next = { ...state, selected: (state.selected + (event.key === "ArrowDown" ? 1 : -1) + state.props.items.length) % state.props.items.length }
                  suggestionRef.current = next; setSuggestion(next); return true
                }
                if (event.key === "Enter") { choose(state); return true }
                return false
              },
              onExit: () => { suggestionRef.current = null; setSuggestion(null) },
            }
          },
        },
      }),
    ],
    content: document,
    editable: !disabled,
    editorProps: {
      attributes: { class: "ws-prompt-editable", role: "textbox", "aria-label": label, "aria-multiline": "true" },
      handleKeyDown: (_view, event) => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); callbacks.current.onSave(true); return true }
        return false
      },
    },
    onUpdate: ({ editor }) => callbacks.current.onChange(editor.getJSON() as PromptDocument),
    onBlur: () => callbacks.current.onSave(),
  })
  // Keep the editor instance and its caret/undo stack when save status or asset metadata changes.
  useEffect(() => { editor?.setEditable(!disabled, false) }, [editor, disabled])
  useEffect(() => {
    if (editor && !editor.isFocused && promptText(editor.getJSON()) !== promptText(document)) editor.commands.setContent(document, { emitUpdate: false })
  }, [editor, document])
  useImperativeHandle(ref, () => ({ insert: asset => { editor?.chain().focus().insertContent([referenceNode(asset), { type: "text", text: " " }]).run() } }), [editor])
  return <AssetContext.Provider value={assets}>
    <EditorContent editor={editor}/>
    {suggestion && createPortal(<Popover open arrow={false} placement="bottomLeft" trigger={[]} content={<div className="ws-asset-suggestions" onMouseDown={event => event.preventDefault()}>
      <div className="ws-suggestion-heading">引用资产<span>↑↓ 选择 · Enter 插入</span></div>
      {suggestion.props.items.length ? <Menu selectable selectedKeys={[suggestion.props.items[suggestion.selected]?.key]} items={suggestion.props.items.map(asset => ({ key: asset.key, label: <span className="ws-suggestion-row"><WorkshopAssetThumbnail asset={asset}/><span>{asset.title}</span><small>{assetKindLabel(asset.kind)}</small></span>, onClick: () => suggestion.props.command(referenceNode(asset).attrs!) }))}/> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有找到相关资产"/>}
    </div>}><span className="ws-suggestion-anchor" style={{ left: suggestion.rect.left, top: suggestion.rect.bottom }}/></Popover>, window.document.body)}
  </AssetContext.Provider>
})
