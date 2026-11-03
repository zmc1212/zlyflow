import { useState } from "react"
import { Button, Checkbox, Empty, Input, Modal, Popover, Radio, Tabs, Tooltip } from "antd"
import { Ban, Check, PenLine, Search, Shapes } from "lucide-react"
import { changeStoryAudience, changeVisibleStoryTopics, creativeStyleText, CUSTOM_STYLE_LIMIT, filterStylePresets, selectedStoryTopics, STYLE_CATEGORIES, STYLE_PRESETS, TOPIC_GROUPS, topicOptions, type CreativeStyle, type StoryTopics, type TopicGroup } from "./creative-presets"
import "./creative-presets.css"

type Props = {
  style: CreativeStyle
  topics: StoryTopics
  onStyleChange: (style: CreativeStyle) => void
  onTopicsChange: (topics: StoryTopics) => void
  disabled: boolean
}

export default function HomeCreativeOptions({ style, topics, onStyleChange, onTopicsChange, disabled }: Props) {
  const [open, setOpen] = useState<"style" | "topic" | null>(null)
  const [styleCategory, setStyleCategory] = useState("all")
  const [styleQuery, setStyleQuery] = useState("")
  const [topicGroup, setTopicGroup] = useState<TopicGroup>("audience")
  const [topicQuery, setTopicQuery] = useState("")
  const [customOpen, setCustomOpen] = useState(false)
  const [customDraft, setCustomDraft] = useState("")
  const chosenStyle = creativeStyleText(style)
  const chosenPreset = STYLE_PRESETS.find(item => item.id === style.presetId)
  const visibleStyles = filterStylePresets(styleCategory, styleQuery)
  const visibleTopics = topicOptions(topics, topicGroup).filter(label => label.includes(topicQuery.trim()))
  const topicCount = selectedStoryTopics(topics).length

  function editCustomStyle() {
    setCustomDraft(style.custom)
    setOpen(null)
    setCustomOpen(true)
  }

  const stylePanel = <section className="dh-style-library" role="dialog" aria-label="风格库" onKeyDown={event => { if (event.key === "Escape") setOpen(null) }}>
    <div className="dh-preset-search-row">
      <Input aria-label="搜索风格" placeholder="搜索风格" prefix={<Search size={14} />} variant="borderless" value={styleQuery} onChange={event => setStyleQuery(event.target.value)} allowClear />
      <Button type="text" onClick={editCustomStyle} icon={<PenLine size={13} />}>自定义风格</Button>
    </div>
    <Tabs activeKey={styleCategory} onChange={setStyleCategory} tabBarGutter={20} items={STYLE_CATEGORIES.map(item => ({ key: item.id, label: item.label }))} />
    <div className="dh-style-scroll">
      <Radio.Group aria-label="短剧视觉风格" className="dh-style-grid" value={style.presetId} onChange={event => { onStyleChange({ ...style, presetId: event.target.value }); setOpen(null) }}>
        {visibleStyles.map(item => <Radio className="dh-style-card" key={item.id} value={item.id} title={item.label} onClick={() => { if (item.id === style.presetId) setOpen(null) }}>
          <span className={`dh-style-cover${item.id === "none" ? " is-none" : ""}`}>
            {item.cover ? <img src={item.cover} alt="" loading="lazy" width={230} height={130} /> : <Ban size={18} strokeWidth={1.5} />}
            <span className="dh-style-check" aria-hidden="true"><Check size={12} /></span>
          </span>
          <span className="dh-style-title">{item.label}</span>
        </Radio>)}
      </Radio.Group>
      {visibleStyles.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有找到相关风格" />}
      {style.presetId === "custom" && !styleQuery && styleCategory === "all" && <Button type="text" className="dh-custom-style-current" onClick={editCustomStyle}>当前自定义：{style.custom}</Button>}
    </div>
  </section>

  const topicPanel = <section className="dh-topic-library" role="dialog" aria-label="选择故事选题" onKeyDown={event => { if (event.key === "Escape") setOpen(null) }}>
    <div className="dh-preset-search-row"><Input aria-label="搜索选题" placeholder="搜索选题" prefix={<Search size={14} />} variant="borderless" value={topicQuery} onChange={event => setTopicQuery(event.target.value)} allowClear /></div>
    <Tabs activeKey={topicGroup} onChange={value => { setTopicGroup(value as TopicGroup); setTopicQuery("") }} tabBarGutter={20} items={TOPIC_GROUPS.map(item => ({ key: item.id, label: item.label }))} />
    <div className="dh-topic-scroll">
      {topicGroup === "audience"
        ? <Checkbox.Group className="dh-topic-grid" aria-label="受众偏好" value={topics.audience ? [topics.audience] : []} onChange={values => onTopicsChange(changeStoryAudience(topics, values))}>{visibleTopics.map(label => <Checkbox key={label} value={label}>{label}</Checkbox>)}</Checkbox.Group>
        : <Checkbox.Group className="dh-topic-grid" aria-label={TOPIC_GROUPS.find(item => item.id === topicGroup)?.label} value={topics[topicGroup]} onChange={values => onTopicsChange(changeVisibleStoryTopics(topics, topicGroup, visibleTopics, values))}>{visibleTopics.map(label => <Checkbox key={label} value={label}>{label}</Checkbox>)}</Checkbox.Group>}
      {visibleTopics.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有找到相关选题" />}
    </div>
  </section>

  return <>
    <Popover open={!disabled && open === "style"} onOpenChange={value => setOpen(current => value ? "style" : current === "style" ? null : current)} trigger="click" placement="bottomLeft" arrow={false} classNames={{ root: "dh-presets-popover dh-style-popover" }} content={stylePanel}>
      <Tooltip title={open === "style" ? null : chosenStyle || "选择视觉风格"}><Button type="text" className="dh-create-tool" aria-label={chosenStyle ? `风格：${style.presetId === "custom" ? "自定义风格" : chosenStyle}` : "风格"} aria-haspopup="dialog" aria-expanded={open === "style"} disabled={disabled} icon={chosenPreset?.cover ? <img className="dh-style-trigger-cover" src={chosenPreset.cover} alt="" /> : <Shapes size={16} strokeWidth={1.6} />}>风格{style.presetId === "custom" && <span className="dh-option-dot" />}</Button></Tooltip>
    </Popover>
    <Popover open={!disabled && open === "topic"} onOpenChange={value => setOpen(current => value ? "topic" : current === "topic" ? null : current)} trigger="click" placement="bottomLeft" arrow={false} classNames={{ root: "dh-presets-popover dh-topic-popover" }} content={topicPanel}>
      <Button type="text" className="dh-create-tool" aria-label={topicCount ? `选题，已选 ${topicCount} 项` : "选题"} aria-haspopup="dialog" aria-expanded={open === "topic"} disabled={disabled} icon={<PenLine size={16} strokeWidth={1.6} />}>选题{topicCount > 0 && <span className="dh-option-dot" />}</Button>
    </Popover>
    <Modal title="自定义风格" open={customOpen} onCancel={() => setCustomOpen(false)} onOk={() => { onStyleChange({ presetId: "custom", custom: customDraft.trim() }); setCustomOpen(false) }} okButtonProps={{ disabled: disabled || !customDraft.trim() }} cancelText="取消" okText="确认" width={440} classNames={{ root: "dh-style-modal" }} destroyOnHidden>
      <Input.TextArea aria-label="自定义风格描述" placeholder="在此输入风格描述" value={customDraft} onChange={event => setCustomDraft(event.target.value)} maxLength={CUSTOM_STYLE_LIMIT} showCount autoSize={false} />
    </Modal>
  </>
}
