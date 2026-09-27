import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import type { Director2Document } from "../api"
import ContentLibraryReader, { ContentLibraryText, contentLibraryEpisodes, contentLibraryEpisodeText } from "./ContentLibraryReader"

describe("content library reading workspace", () => {
  it("renders the first episode immediately instead of a closed accordion", () => {
    const html = renderToStaticMarkup(<ContentLibraryReader accepted episodes={[
      { episode_num: 2, title: "第一桶金", body: "# 第2集：第一桶金\n### 场景1｜村口\n**人物：** 沈砚\n动作：修好水渠。" },
      { episode_num: 6, title: "写诗成名", body: "第六集正文" },
    ]} />)
    expect(html).toContain("第一桶金")
    expect(html).toContain("<h5>场景1｜村口</h5>")
    expect(html).toContain("<strong>人物：</strong>")
    expect(html).toContain("修好水渠。")
    expect(html).not.toContain("第六集正文")
    expect(html).toContain('aria-label="上一集"')
    expect(html).toMatch(/aria-label="上一集"[^>]*disabled/)
    expect(html).not.toMatch(/aria-label="下一集"[^>]*disabled/)
    expect(html).toContain("已采纳剧本 · 只读预览")
  })
  it("disables both navigation controls for a single episode", () => {
    const html = renderToStaticMarkup(<ContentLibraryReader accepted={false} episodes={[{ episode_num: 9, title: "单集", script_text: "正文" }]} />)
    expect(html).toMatch(/aria-label="上一集"[^>]*disabled/)
    expect(html).toMatch(/aria-label="下一集"[^>]*disabled/)
    expect(html).toContain("尚未采纳")
    expect(html).toContain("第 9 集正文")
  })
  it("keeps full text ahead of summaries and preserves exact text for copying", () => {
    const episode = { episode_num: 1, title: "测试", script_text: "原文\n\n下一段\r\n", body: "备用正文", summary: "梗概" }
    expect(contentLibraryEpisodeText(episode)).toEqual({ text: episode.script_text, summaryOnly: false })
    expect(contentLibraryEpisodeText({ ...episode, script_text: "  " })).toEqual({ text: "备用正文", summaryOnly: false })
    expect(contentLibraryEpisodeText({ ...episode, script_text: "", body: "" })).toEqual({ text: "梗概", summaryOnly: true })
  })
  it("labels a summary honestly instead of presenting it as a complete script", () => {
    const html = renderToStaticMarkup(<ContentLibraryReader accepted episodes={[{ episode_num: 1, title: "梗概", summary: "只有剧情梗概" }]} />)
    expect(html).toContain("剧情梗概 · 完整稿可在剧本发展中查看")
    expect(html).not.toContain("已采纳剧本 · 只读预览")
  })
  it("handles empty and invalid episode data without crashing or inventing episodes", () => {
    expect(contentLibraryEpisodes()).toEqual([])
    expect(contentLibraryEpisodes({ analysis: { episodes: [null, "bad", {}, { episode_num: 7, title: "保留" }] } } as unknown as Director2Document)).toEqual([{ episode_num: 7, title: "保留" }])
    expect(renderToStaticMarkup(<ContentLibraryReader episodes={[]} accepted={false} />)).toContain("暂无分集内容")
    expect(contentLibraryEpisodeText({ episode_num: 1, title: "空" })).toEqual({ text: "", summaryOnly: false })
  })
  it("formats script headings but keeps dialogue, prompts and unsafe HTML as text", () => {
    const html = renderToStaticMarkup(<ContentLibraryText text={'# 第1集\n\n### 场景1\n沈砚：“你好。”\n提示词：keep every word\n<script>alert(1)</script>\n---'} />)
    expect(html).toContain("<h4>第1集</h4>")
    expect(html).toContain("<h5>场景1</h5>")
    expect(html).toContain("沈砚：“你好。”")
    expect(html).toContain("提示词：keep every word")
    expect(html).toContain("&lt;script&gt;")
    expect(html).not.toContain("<script>")
    expect(html).toContain("<hr/>")
  })
})
