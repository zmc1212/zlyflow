import { useState } from "react"
import { Button, Empty, Input, Modal, Popover, Radio, Tabs, Tooltip } from "antd"
import { Ban, Check, ChevronDown, PenLine, Search, Shapes } from "lucide-react"
import { creativeStyleText, CUSTOM_STYLE_LIMIT, filterStylePresets, STYLE_CATEGORIES, STYLE_PRESETS, type CreativeStyle } from "./creative-presets"
import "./creative-presets.css"

/** 首页与画布共用的业务风格库；选中值由各自上下文保存。 */
export default function CreativeStylePicker({ value, onChange, disabled = false, placement = "bottomLeft", compact = false }: {
  value: CreativeStyle; onChange: (value: CreativeStyle) => void; disabled?: boolean
  placement?: "bottomLeft" | "topLeft"; compact?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [category, setCategory] = useState("all")
  const [query, setQuery] = useState("")
  const [customOpen, setCustomOpen] = useState(false)
  const [draft, setDraft] = useState("")
  const preset = STYLE_PRESETS.find(item => item.id === value.presetId)
  const selected = creativeStyleText(value)
  const visible = filterStylePresets(category, query)
  const editCustom = () => { setDraft(value.custom); setOpen(false); setCustomOpen(true) }
  return <>
    <Popover open={!disabled && open} onOpenChange={setOpen} trigger="click" placement={placement} arrow={false} classNames={{ root: "dh-presets-popover dh-style-popover" }} content={<section className="dh-style-library" role="dialog" aria-label="风格库" onKeyDown={event => { if (event.key === "Escape") setOpen(false) }}>
      <div className="dh-preset-search-row"><Input aria-label="搜索风格" placeholder="搜索风格" prefix={<Search size={14}/>} variant="borderless" value={query} onChange={event => setQuery(event.target.value)} allowClear/><Button type="text" onClick={editCustom} icon={<PenLine size={13}/>}>自定义风格</Button></div>
      <Tabs activeKey={category} onChange={setCategory} tabBarGutter={20} items={STYLE_CATEGORIES.map(item => ({ key: item.id, label: item.label }))}/>
      <div className="dh-style-scroll"><Radio.Group aria-label="短剧视觉风格" className="dh-style-grid" value={value.presetId} onChange={event => { onChange({ ...value, presetId: event.target.value }); setOpen(false) }}>
        {visible.map(item => <Radio className="dh-style-card" key={item.id} value={item.id} title={item.label} onClick={() => { if (item.id === value.presetId) setOpen(false) }}><span className={`dh-style-cover${item.id === "none" ? " is-none" : ""}`}>{item.cover ? <img src={item.cover} alt="" loading="lazy" width={230} height={130}/> : <Ban size={18} strokeWidth={1.5}/>}<span className="dh-style-check" aria-hidden="true"><Check size={12}/></span></span><span className="dh-style-title">{item.label}</span></Radio>)}
      </Radio.Group>{!visible.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有找到相关风格"/>}{value.presetId === "custom" && !query && category === "all" && <Button type="text" className="dh-custom-style-current" onClick={editCustom}>当前自定义：{value.custom}</Button>}</div>
    </section>}>
      <Tooltip title={open ? null : selected || "选择视觉风格"}><Button type="text" className={compact ? "ac-style-trigger" : "dh-create-tool"} aria-label={selected ? `风格：${value.presetId === "custom" ? "自定义风格" : selected}` : "风格"} aria-haspopup="dialog" aria-expanded={open} disabled={disabled} icon={preset?.cover ? <img className="dh-style-trigger-cover" src={preset.cover} alt=""/> : compact ? undefined : <Shapes size={16} strokeWidth={1.6}/>}>风格{compact && <ChevronDown size={12}/>}</Button></Tooltip>
    </Popover>
    <Modal title="自定义风格" open={customOpen} onCancel={() => setCustomOpen(false)} onOk={() => { onChange({ presetId: "custom", custom: draft.trim() }); setCustomOpen(false) }} okButtonProps={{ disabled: disabled || !draft.trim() }} cancelText="取消" okText="确认" width={440} classNames={{ root: "dh-style-modal" }} destroyOnHidden><Input.TextArea aria-label="自定义风格描述" placeholder="在此输入风格描述" value={draft} onChange={event => setDraft(event.target.value)} maxLength={CUSTOM_STYLE_LIMIT} showCount autoSize={false}/></Modal>
  </>
}
