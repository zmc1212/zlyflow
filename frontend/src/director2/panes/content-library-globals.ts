export type PositioningSection = {
  genre?: string
  worldview?: string
  duration_per_episode?: string
  shots_per_episode?: string | number
  main_storyline?: string
  items?: string[]
}

export type VisualStyleSection = {
  description?: string
  prohibited?: string
}

export type PositioningEntry = {
  key: string
  /** 为 null 表示剧本里是一整段没有字段名的定位散文，直接按段落排。 */
  label: string | null
  text: string
}

const POSITIONING_FIELDS: ReadonlyArray<readonly [string, keyof PositioningSection]> = [
  ["作品类型", "genre"],
  ["世界观设定", "worldview"],
  ["单集时长", "duration_per_episode"],
  ["镜头规划", "shots_per_episode"],
  ["主线剧情", "main_storyline"],
]

/** 定位卡先按固定顺序排带字段的条目，再接没有字段的段落；解析器已保证两者不重复。 */
export function positioningEntries(positioning?: PositioningSection | null): PositioningEntry[] {
  if (!positioning) return []
  const entries: PositioningEntry[] = []
  for (const [label, field] of POSITIONING_FIELDS) {
    const text = String(positioning[field] ?? "").trim()
    if (text) entries.push({ key: field, label, text })
  }
  ;(positioning.items || []).forEach((item, index) => {
    const text = String(item ?? "").trim()
    if (text) entries.push({ key: `item-${index}`, label: null, text })
  })
  return entries
}

export function hasVisualStyleContent(style?: VisualStyleSection | null): boolean {
  return Boolean(String(style?.description || "").trim() || String(style?.prohibited || "").trim())
}
