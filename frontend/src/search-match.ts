// 下拉搜索的共享模糊匹配层 —— 供模型、工作流、声线、画布/工程等选择器复用。
// 只负责“查询词是否命中某个选项”，不绑定任何组件或数据源。

export type SearchableOption = {
  /** 选项值；antd 的分组标题没有 value，过滤时会被单独跳过。 */
  value?: string
  /** 选项标签；ReactNode 标签取不到文本时回退到 value。 */
  label?: unknown
  /** 分组选项（antd 的 options 嵌套结构）。 */
  options?: unknown
}

// 模型 ID 里的 - . _ / 空格等只是排版差异，搜索时按边界处理：glm-5.3、glm5.3、GLM 5.3 视为同一个词。
const SEARCH_BOUNDARY = /[\s\-_./\\:·|,;+()（）[\]【】]+/

function labelText(label: unknown): string {
  return typeof label === "string" || typeof label === "number" ? String(label) : ""
}

function flattenSearchText(value: string): string {
  return (value || "").toLowerCase().split(SEARCH_BOUNDARY).join("")
}

function searchTokens(value: string): string[] {
  return (value || "").toLowerCase().split(SEARCH_BOUNDARY).filter(Boolean)
}

function isSubsequence(needle: string, haystack: string): boolean {
  if (!needle) return true
  let cursor = 0
  for (const char of haystack) {
    if (char === needle[cursor]) cursor += 1
    if (cursor >= needle.length) return true
  }
  return false
}

// 查询词按分隔符切成多段后，能否在候选名的词序列里连续命中（3.1 命中 ling-3.1-flash，但不从 0731 中间切）。
function boundaryScore(tokens: string[], name: string): number {
  if (!tokens.length) return 0
  const nameTokens = searchTokens(name)
  for (let start = 0; start < nameTokens.length; start += 1) {
    let matched = 0
    while (
      matched < tokens.length
      && start + matched < nameTokens.length
      && nameTokens[start + matched].startsWith(tokens[matched])
    ) {
      matched += 1
    }
    if (matched === tokens.length) return start === 0 ? 90 - tokens.length : 86 - tokens.length
  }
  return 0
}

/**
 * 模糊匹配打分：0 表示不命中，分数越高越相关。
 * 依次比较完整值、名称（去掉“· 价格/角色”之类后缀）、完整标签；忽略分隔符与大小写。
 */
export function scoreSearchMatch(query: string, option: SearchableOption): number {
  const text = (query || "").trim()
  if (!text) return 1
  const id = option.value || ""
  const label = labelText(option.label)
  const labelName = label.split("·")[0].trim()
  const loweredQuery = text.toLowerCase()
  if (id.toLowerCase() === loweredQuery) return 100

  const names = [id, labelName, label].filter(Boolean)
  if (!names.length) return 0

  for (let index = 0; index < names.length; index += 1) {
    const loweredName = names[index].toLowerCase()
    if (loweredName === loweredQuery) return 96 - index
    if (loweredName.startsWith(loweredQuery)) return 92 - index
    const hit = loweredName.indexOf(loweredQuery)
    if (hit >= 0) return 88 - index - Math.min(hit, 20) / 100
  }

  const flattenedQuery = flattenSearchText(text)
  const flattenedNames = names.map(flattenSearchText)
  for (let index = 0; index < flattenedNames.length; index += 1) {
    const name = flattenedNames[index]
    if (!name || !flattenedQuery) continue
    if (name === flattenedQuery) return 84 - index
    if (name.startsWith(flattenedQuery)) return 80 - index
    const hit = name.indexOf(flattenedQuery)
    if (hit >= 0) return 76 - index - Math.min(hit, 20) / 100
  }

  const tokens = searchTokens(text)
  if (tokens.length > 1) {
    for (let index = 0; index < names.length; index += 1) {
      const aligned = boundaryScore(tokens, names[index])
      if (aligned > 0) return aligned - index
    }
    // 分词逐项命中（deepseek pro → deepseek-v4-pro），允许跳过中间段，但不接受“数字随便出现”的假阳性
    const tokensHit = names.some(name => {
      const nameTokens = searchTokens(name)
      return tokens.every(token => nameTokens.some(nameToken => nameToken.startsWith(token)))
    })
    if (tokensHit) return 58
  }

  // 缩写子序列：dsv4 → deepseek-v4
  if (flattenedQuery.length >= 3 && flattenedNames.some(name => isSubsequence(flattenedQuery, name))) return 50
  return 0
}

export function matchesSearchQuery(query: string, option: SearchableOption): boolean {
  return scoreSearchMatch(query, option) > 0
}

/**
 * 直接作为 antd Select / AutoComplete 的 `filterOption` 使用。
 * 分组标题不参与匹配：命中与否交给组内子项决定，避免“组名命中就放行整组”。
 */
export function searchFilterOption(input: string, option?: SearchableOption): boolean {
  if (!option || Array.isArray(option.options)) return false
  return matchesSearchQuery(input, option)
}

/** 按相关度过滤并排序；查询为空时保持原有顺序（展开即全部，输入才搜索）。 */
export function filterSearchOptions<T extends SearchableOption>(options: T[], query: string): T[] {
  if (!(query || "").trim()) return options
  return options
    .map((option, index) => ({ option, index, score: scoreSearchMatch(query, option) }))
    .filter(row => row.score > 0)
    .sort((left, right) => right.score - left.score || left.index - right.index)
    .map(row => row.option)
}

export type SearchableGroup<T extends SearchableOption> = { label?: unknown; options: T[] }

/**
 * 分组选项过滤：组内按相关度排序，删掉没有命中的组；组顺序与组标题保持不变。
 * 用于工作流、声线、图片模型这类 antd 分组下拉。
 */
export function filterGroupedOptions<T extends SearchableOption>(
  options: (T | SearchableGroup<T>)[],
  query: string,
): (T | SearchableGroup<T>)[] {
  const text = (query || "").trim()
  if (!text) return options
  const filtered: (T | SearchableGroup<T>)[] = []
  for (const entry of options) {
    const group = entry as SearchableGroup<T>
    if (Array.isArray(group.options)) {
      const matched = filterSearchOptions(group.options, text)
      if (matched.length) filtered.push({ ...group, options: matched })
      continue
    }
    const option = entry as T
    if (scoreSearchMatch(text, option) > 0) filtered.push(option)
  }
  return filtered
}
