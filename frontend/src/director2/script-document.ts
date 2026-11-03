import type { Director2Document } from "./api"

export type ScriptEpisode = { episode_num: number; title?: string; summary?: string; body?: string; shots?: unknown[] }

const EPISODE_HEADING = /^[ \t]{0,3}#{1,6}[ \t]*(?:\*\*[ \t]*)?[【\[]?[ \t]*第[ \t]*[0-9一二三四五六七八九十百零〇两]+[ \t]*集[^\r\n]*/m

export function primaryScript(documents: Director2Document[]) {
  return documents.filter(doc => doc.status !== "merged").slice().sort((a, b) =>
    Number(!!b.analysis?.primary_script) - Number(!!a.analysis?.primary_script)
    || a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id))[0]
}

export function scriptEpisodes(analysis: Director2Document["analysis"]): ScriptEpisode[] {
  return (Array.isArray(analysis?.episodes) ? analysis.episodes as ScriptEpisode[] : []).slice().sort((a, b) => a.episode_num - b.episode_num)
}

export function scriptOutlines(analysis: Director2Document["analysis"]): ScriptEpisode[] {
  const result = new Map(scriptEpisodes(analysis).map(ep => [ep.episode_num, ep]))
  for (const ep of (Array.isArray(analysis?.episode_outlines) ? analysis.episode_outlines as ScriptEpisode[] : [])) {
    result.set(ep.episode_num, { ...result.get(ep.episode_num), ...ep })
  }
  return [...result.values()].sort((a, b) => a.episode_num - b.episode_num)
}

export function episodeDraftText(episode: ScriptEpisode): string {
  const body = episode.body || ""
  return EPISODE_HEADING.test(body)
    ? body : `# 第${episode.episode_num}集：${episode.title || ""}\n\n${body}`
}

export function scriptBodyEpisodes(analysis: Director2Document["analysis"]): ScriptEpisode[] {
  const bodies = new Map(scriptEpisodes(analysis).map(ep => [ep.episode_num, ep]))
  return scriptOutlines(analysis).map(outline => bodies.get(outline.episode_num) || outline)
}

export function episodeReadingText(episode: ScriptEpisode): string {
  return (episode.body || "").replace(EPISODE_HEADING, "").trimStart()
}

export function scriptBodyText(doc: Director2Document): string {
  return scriptEpisodes(doc.analysis).map(ep => ep.body || "").filter(Boolean).join("\n\n") || doc.raw_text || ""
}

export type StorySettingField = { key: string; label: string; value: string; multiline?: boolean; wide?: boolean }

export function storySettingFields(doc: Director2Document): StorySettingField[] {
  const analysis = doc.analysis || {}
  const positioning = (analysis.positioning || {}) as Record<string, unknown>
  const structured = (analysis.story_setting_fields || {}) as Record<string, unknown>
  const raw = typeof analysis.story_setting_text === "string" ? analysis.story_setting_text : (doc.raw_text || "").split(EPISODE_HEADING)[0]
  const names: Record<string, string> = { 目标受众: "audience", 目标用户: "audience", 受众: "audience", 核心梗: "hook", 核心卖点: "hook", 核心钩子: "hook", 故事类型: "genre", 作品类型: "genre", 题材类型: "genre", 一句话故事: "logline", 一句话概括: "logline", 主线剧情: "logline", 故事主线: "logline", 故事梗概: "synopsis", 全剧梗概: "synopsis", 故事简介: "synopsis", 故事定位: "synopsis", 故事设定: "synopsis" }
  const parsed: Record<string, string> = {}
  let field: string | undefined
  for (const line of raw.split(/\r?\n/)) {
    const clean = line.replace(/^\s*#{1,6}\s*/, "").replace(/^\s*[-*]\s+/, "").replace(/\*\*/g, "").trim()
    const match = clean.match(/^([^：:]{2,12})(?:[：:]\s*(.*))?$/)
    const key = match && names[match[1]]
    if (key) { field = key; parsed[key] = match?.[2] || "" }
    else if (/^\s*#{1,6}\s/.test(line)) field = undefined
    else if (field) parsed[field] += (parsed[field] ? "\n" : "") + line
  }
  const value = (...items: unknown[]) => (items.find(item => typeof item === "string" && item.trim()) as string | undefined)?.trim()
  const prose = Array.isArray(positioning.items) ? positioning.items.filter(item => typeof item === "string").join("\n\n") : ""
  const settingProse = typeof analysis.story_setting_text === "string" ? analysis.story_setting_text.replace(/^\s*#{1,6}\s*/gm, "").replace(/^\s*[-*+]\s+/gm, "").replace(/\*\*/g, "").trim() : ""
  const synopsis = value(structured.synopsis, parsed.synopsis, prose, settingProse) || ""
  return [
    { key: "episodes", label: "集数", value: String(scriptOutlines(analysis).length) },
    { key: "audience", label: "目标受众", value: value(structured.audience, structured.target_audience, parsed.audience, positioning.target_audience, positioning.audience) || "未提供" },
    { key: "hook", label: "核心梗", value: value(structured.hook, structured.core_hook, parsed.hook, positioning.core_hook) || "未提供", multiline: true },
    { key: "genre", label: "故事类型", value: value(structured.genre, parsed.genre, positioning.genre) || "未提供", multiline: true },
    { key: "logline", label: "一句话故事", value: value(structured.logline, parsed.logline, positioning.main_storyline) || "未提供", multiline: true, wide: true },
    { key: "synopsis", label: "故事梗概", value: synopsis.trim() || "未提供", multiline: true, wide: true },
    ...(value(positioning.worldview) ? [{ key: "worldview", label: "世界观设定", value: String(positioning.worldview), multiline: true, wide: true }] : []),
    ...(value(positioning.duration_per_episode) ? [{ key: "duration", label: "单集时长", value: String(positioning.duration_per_episode) }] : []),
  ]
}

export function scriptDownloadText(doc: Director2Document): string {
  const analysis = doc.analysis || {}
  if (!analysis.story_setting_text && !Array.isArray(analysis.episode_outlines)) return doc.raw_text || ""
  const setting = storySettingFields(doc).filter(field => field.value !== "未提供").map(field => `### ${field.label}\n\n${field.value}`).join("\n\n")
  const outline = scriptOutlines(analysis).map(ep => `### 第${ep.episode_num}集：${ep.title || "未命名"}\n\n${ep.summary || "大纲待完善"}`).join("\n\n")
  const body = doc.raw_text || scriptEpisodes(analysis).map(episodeDraftText).join("\n\n")
  return `# ${String(analysis.title || doc.filename).replace(/^#+\s*/, "")}\n\n## 故事设定\n\n${setting}\n\n## 分集大纲\n\n${outline}\n\n## 剧本正文\n\n${body}`
}
