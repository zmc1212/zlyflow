import { describe, expect, it } from "vitest"
import type { Director2Document } from "./api"
import { episodeDraftText, episodeReadingText, primaryScript, scriptBodyEpisodes, scriptBodyText, scriptDownloadText, scriptEpisodes, scriptOutlines, storySettingFields } from "./script-document"

const document = (id: string, created: string, analysis: Record<string, unknown> = {}, status = "ready") => ({ id, created_at: created, analysis, status }) as Director2Document

describe("one script with ordered episodes", () => {
  it("keeps the original script selected when a later episode is imported", () => {
    expect(primaryScript([document("second", "2026-11-03"), document("original", "2026-11-01")])?.id).toBe("original")
  })
  it("uses a marked primary and omits archived sources", () => {
    expect(primaryScript([document("old", "2026-11-01", {}, "merged"), document("main", "2026-11-02", { primary_script: true }), document("other", "2026-10-01")])?.id).toBe("main")
  })
  it("shows an outline-only second episode without manufacturing its body", () => {
    const analysis = { episodes: [{ episode_num: 1, body: "第一集原文", summary: "第一集梗概" }], episode_outlines: [{ episode_num: 2, title: "续集", summary: "第二集大纲" }] }
    expect(scriptEpisodes(analysis)).toHaveLength(1)
    expect(scriptOutlines(analysis).map(ep => ep.episode_num)).toEqual([1, 2])
    expect(scriptOutlines(analysis)[1].body).toBeUndefined()
  })
  it("updates the outline while preserving the matching saved body", () => {
    const analysis = { episodes: [{ episode_num: 2, title: "正文标题", body: "第二集原文" }], episode_outlines: [{ episode_num: 2, summary: "更新梗概" }] }
    expect(scriptOutlines(analysis)[0]).toMatchObject({ episode_num: 2, body: "第二集原文", summary: "更新梗概" })
  })
  it("provides an explicit episode heading when editing a legacy unnumbered body", () => {
    expect(episodeDraftText({ episode_num: 2, title: "续集", body: "场一" })).toBe("# 第2集：续集\n\n场一")
    expect(episodeDraftText({ episode_num: 2, body: "## 第二集：续集\n正文" })).toBe("## 第二集：续集\n正文")
  })
  it("keeps bracketed headings editable without adding a second episode heading", () => {
    const episode = { episode_num: 2, title: "线索", body: "## 【第2集：线索】\n\n【特写】李然看向镜子。" }
    expect(episodeDraftText(episode)).toBe(episode.body)
    expect(episodeReadingText(episode)).toBe("【特写】李然看向镜子。")
  })
  it("shows the saved original when a primary script has no parsed episode bodies", () => {
    const doc = { ...document("main", "now", { primary_script: true, episodes: [] }), raw_text: "# 原剧本\n\n已采纳的正文。" }
    expect(scriptBodyText(doc)).toBe(doc.raw_text)
    expect(scriptBodyText({ ...doc, analysis: { primary_script: true, episode_outlines: [{ episode_num: 1 }] } })).toBe(doc.raw_text)
    expect(scriptBodyText({ ...doc, analysis: { primary_script: true, episode_outlines: [{ episode_num: 1 }] }, raw_text: "" })).toBe("")
  })
  it("keeps the saved body title distinct from a newer outline title", () => {
    const analysis = { episodes: [{ episode_num: 2, title: "正文标题", body: "# 第2集：正文标题\n\n### 镜头 1\n正文" }], episode_outlines: [{ episode_num: 2, title: "大纲标题" }] }
    expect(scriptBodyEpisodes(analysis)[0].title).toBe("正文标题")
    expect(scriptOutlines(analysis)[0].title).toBe("大纲标题")
    expect(episodeReadingText(scriptBodyEpisodes(analysis)[0])).toBe("### 镜头 1\n正文")
  })
  it("reads labelled settings into fields and counts body plus planned episodes", () => {
    const doc = document("main", "now", { episodes: [{ episode_num: 1, body: "正文" }], episode_outlines: [{ episode_num: 2 }], story_setting_text: "## 故事设定\n\n- **目标受众**：大众\n- **核心梗**：煎饼上作画\n- **故事类型**：都市经营喜剧\n### 一句话故事\n阿文靠煎饼重拾画笔。\n### 故事梗概\n阿文摆摊。\n\n他重新找到了方向。" })
    const fields = Object.fromEntries(storySettingFields(doc).map(field => [field.key, field.value]))
    expect(fields).toMatchObject({ episodes: "2", audience: "大众", hook: "煎饼上作画", genre: "都市经营喜剧", logline: "阿文靠煎饼重拾画笔。", synopsis: "阿文摆摊。\n\n他重新找到了方向。" })
  })
  it("preserves existing prose without inventing missing setting values", () => {
    const doc = document("main", "now", { positioning: { items: ["都市青年突然失业。", "他在夜市摆摊。"] } })
    const fields = Object.fromEntries(storySettingFields(doc).map(field => [field.key, field.value]))
    expect(fields.synopsis).toBe("都市青年突然失业。\n\n他在夜市摆摊。")
    expect(fields).toMatchObject({ audience: "未提供", hook: "未提供", genre: "未提供", logline: "未提供" })
  })
  it("renders recovered setup and stops fallback metadata before bracketed episode bodies", () => {
    const doc = { ...document("main", "now", { episodes: [{ episode_num: 1, body: "正文" }], story_setting_fields: { genre: "悬疑", hook: "镜子里的线索" }, story_setting_text: "* **主角**：李然\n* **循环机制**：回到入宅时刻" }), raw_text: "# 回声\n\n## 【第1集：推门】\n故事梗概：这是集内对白。" }
    const fields = Object.fromEntries(storySettingFields(doc).map(field => [field.key, field.value]))
    expect(fields).toMatchObject({ episodes: "1", genre: "悬疑", hook: "镜子里的线索", synopsis: "主角：李然\n循环机制：回到入宅时刻", audience: "未提供" })
    const fallback = Object.fromEntries(storySettingFields({ ...doc, analysis: {} }).map(field => [field.key, field.value]))
    expect(fallback.synopsis).toBe("未提供")
  })
  it("downloads the authoritative original text together with newer setting and outline metadata", () => {
    const doc = { ...document("main", "now", { story_setting_text: "### 核心梗\n新设定", episode_outlines: [{ episode_num: 2, title: "新集", summary: "谈判" }], episodes: [{ episode_num: 1, body: "解析后的正文" }] }), filename: "主剧本", raw_text: "# 原稿\n\n  保留作者的空格与正文。\n" }
    const text = scriptDownloadText(doc)
    expect(text).toContain(doc.raw_text)
    expect(text).toContain("新设定")
    expect(text).toContain("第2集：新集")
    expect(scriptDownloadText({ ...doc, analysis: {} })).toBe(doc.raw_text)
  })
})
