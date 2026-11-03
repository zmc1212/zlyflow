import catalog from "./creative-presets.json"

export const STYLE_CATEGORIES = catalog.styleCategories
export const STYLE_PRESETS = catalog.styles
export const TOPIC_GROUPS = catalog.topicGroups as { id: TopicGroup; label: string }[]
export const TOPIC_AUDIENCES = catalog.audiences as Audience[]
export const CUSTOM_STYLE_LIMIT = 1000
export type Audience = "男频" | "女频" | "泛人群"
export type TopicGroup = "audience" | "background" | "character" | "relationship" | "trope" | "mood"
export type TopicDetailGroup = Exclude<TopicGroup, "audience">
export type StoryTopics = { audience: Audience | "" } & Record<TopicDetailGroup, string[]>
export type CreativeStyle = { presetId: string; custom: string }

export function emptyStoryTopics(): StoryTopics {
  return { audience: "", background: [], character: [], relationship: [], trope: [], mood: [] }
}

export function creativeStyleText(choice: CreativeStyle): string {
  if (choice.presetId === "custom") return choice.custom.trim()
  return choice.presetId === "none" ? "" : STYLE_PRESETS.find(item => item.id === choice.presetId)?.label || ""
}

export function filterStylePresets(category: string, query: string) {
  const search = query.trim().toLocaleLowerCase()
  return STYLE_PRESETS.filter(item => (category === "all" || item.category === category) && item.label.toLocaleLowerCase().includes(search))
}

export function topicOptions(topics: StoryTopics, group: TopicGroup): readonly string[] {
  return group === "audience" ? TOPIC_AUDIENCES : catalog.topics[topics.audience || "泛人群"][group]
}

export function selectedStoryTopics(topics?: StoryTopics): { group: TopicGroup; label: string }[] {
  return topics ? TOPIC_GROUPS.flatMap(({ id }) => (id === "audience" ? topics.audience ? [topics.audience] : [] : topics[id]).map(label => ({ group: id, label }))) : []
}

export function removeStoryTopic(topics: StoryTopics, group: TopicGroup, label: string): StoryTopics {
  return group === "audience" ? { ...topics, audience: "" } : { ...topics, [group]: topics[group].filter(item => item !== label) }
}

export function changeVisibleStoryTopics(topics: StoryTopics, group: TopicDetailGroup, visible: readonly string[], checked: readonly string[]): StoryTopics {
  return { ...topics, [group]: [...topics[group].filter(label => !visible.includes(label)), ...checked] }
}

export function changeStoryAudience(topics: StoryTopics, checked: readonly string[]): StoryTopics {
  const valid = checked.filter((label): label is Audience => TOPIC_AUDIENCES.includes(label as Audience))
  return { ...topics, audience: valid.find(label => label !== topics.audience) || valid[0] || "" }
}

export function storyTopicsText(topics?: StoryTopics): string {
  if (!topics) return ""
  return TOPIC_GROUPS.flatMap(({ id, label }) => {
    const value = id === "audience" ? topics.audience : topics[id].join("、")
    return value ? [`${label}：${value}`] : []
  }).join("；")
}
