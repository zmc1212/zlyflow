import { useState } from "react"
import { Button, Checkbox, Empty, Input, Popover, Tabs } from "antd"
import { PenLine, Search } from "lucide-react"
import { changeStoryAudience, changeVisibleStoryTopics, selectedStoryTopics, TOPIC_GROUPS, topicOptions, type CreativeStyle, type StoryTopics, type TopicGroup } from "./creative-presets"
import "./creative-presets.css"
import CreativeStylePicker from "./CreativeStylePicker"

type Props = {
  style: CreativeStyle
  topics: StoryTopics
  onStyleChange: (style: CreativeStyle) => void
  onTopicsChange: (topics: StoryTopics) => void
  disabled: boolean
}

export default function HomeCreativeOptions({ style, topics, onStyleChange, onTopicsChange, disabled }: Props) {
  const [open, setOpen] = useState<"style" | "topic" | null>(null)
  const [topicGroup, setTopicGroup] = useState<TopicGroup>("audience")
  const [topicQuery, setTopicQuery] = useState("")
  const visibleTopics = topicOptions(topics, topicGroup).filter(label => label.includes(topicQuery.trim()))
  const topicCount = selectedStoryTopics(topics).length

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
    <CreativeStylePicker value={style} onChange={onStyleChange} disabled={disabled}/>
    <Popover open={!disabled && open === "topic"} onOpenChange={value => setOpen(current => value ? "topic" : current === "topic" ? null : current)} trigger="click" placement="bottomLeft" arrow={false} classNames={{ root: "dh-presets-popover dh-topic-popover" }} content={topicPanel}>
      <Button type="text" className="dh-create-tool" aria-label={topicCount ? `选题，已选 ${topicCount} 项` : "选题"} aria-haspopup="dialog" aria-expanded={open === "topic"} disabled={disabled} icon={<PenLine size={16} strokeWidth={1.6} />}>选题{topicCount > 0 && <span className="dh-option-dot" />}</Button>
    </Popover>
  </>
}
