import { useRef, useState, type ReactNode } from "react"
import { Button, Empty, Select, message } from "antd"
import { ChevronLeft, ChevronRight, Copy } from "lucide-react"
import type { Director2Document } from "../api"

export type ContentLibraryEpisode = { episode_num: number; title: string; summary?: string; script_text?: string; body?: string }

export function contentLibraryEpisodes(doc?: Director2Document): ContentLibraryEpisode[] {
  if (!Array.isArray(doc?.analysis?.episodes)) return []
  return doc.analysis.episodes.filter((episode): episode is ContentLibraryEpisode => Boolean(episode && typeof episode === "object" && Number.isFinite(episode.episode_num)))
}

export function contentLibraryEpisodeText(episode: ContentLibraryEpisode) {
  const text = [episode.script_text, episode.body].find(value => typeof value === "string" && value.trim())
  return { text: text || episode.summary || "", summaryOnly: !text && Boolean(episode.summary) }
}

function inlineText(text: string): ReactNode {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, index) => part.startsWith("**") && part.endsWith("**") ? <strong key={index}>{part.slice(2, -2)}</strong> : part)
}

/** Readable script typography; imported HTML always stays escaped text. */
export function ContentLibraryText({ text }: { text: string }) {
  return <div className="ucl-script-text">{text.split(/\r?\n/).map((line, index) => {
    if (!line.trim()) return null
    const heading = /^(#{1,6})\s+(.+)$/.exec(line.trim())
    if (heading) return heading[1].length <= 2
      ? <h4 key={index}>{inlineText(heading[2])}</h4>
      : <h5 key={index}>{inlineText(heading[2])}</h5>
    if (/^\s*([-*_])(?:\s*\1){2,}\s*$/.test(line)) return <hr key={index} />
    return <p key={index}>{inlineText(line)}</p>
  })}</div>
}

export default function ContentLibraryReader({ episodes, accepted }: { episodes: ContentLibraryEpisode[]; accepted: boolean }) {
  const [selectedNumber, setSelectedNumber] = useState(episodes[0]?.episode_num)
  const scrollRef = useRef<HTMLDivElement>(null)
  const currentIndex = Math.max(0, episodes.findIndex(episode => episode.episode_num === selectedNumber))
  const episode = episodes[currentIndex]
  if (!episode) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无分集内容" />
  const { text, summaryOnly } = contentLibraryEpisodeText(episode)
  function selectEpisode(number: number) {
    setSelectedNumber(number)
    scrollRef.current?.scrollTo({ top: 0 })
  }
  async function copyEpisode() {
    try { await navigator.clipboard.writeText(text); message.success("已复制第 " + episode.episode_num + " 集" + (summaryOnly ? "梗概" : "剧本")) }
    catch { message.error("复制失败，请选中正文后手动复制") }
  }
  return <section className="ucl-reader" aria-label="分集阅读器">
    <div className="ucl-reader-toolbar">
      <div className="ucl-episode-picker"><label htmlFor="ucl-episode-select">分集</label><Select id="ucl-episode-select" aria-label="选择分集" value={episode.episode_num} onChange={selectEpisode} showSearch={{ optionFilterProp: "label" }} options={episodes.map(item => ({ value: item.episode_num, label: "第 " + item.episode_num + " 集 · " + (item.title || "未命名分集") }))} /></div>
      <div className="ucl-reader-actions">
        <span className="ucl-page-count" aria-live="polite">{currentIndex + 1} / {episodes.length}</span>
        <Button aria-label="上一集" icon={<ChevronLeft size={16} />} disabled={currentIndex === 0} onClick={() => selectEpisode(episodes[currentIndex - 1].episode_num)} />
        <Button aria-label="下一集" icon={<ChevronRight size={16} />} disabled={currentIndex === episodes.length - 1} onClick={() => selectEpisode(episodes[currentIndex + 1].episode_num)} />
        <Button className="ucl-copy-button" icon={<Copy size={14} />} disabled={!text.trim()} onClick={() => void copyEpisode()}>复制本集</Button>
      </div>
    </div>
    <div className="ucl-reading-context"><span>{summaryOnly ? "剧情梗概 · 完整稿可在剧本发展中查看" : accepted ? "已采纳剧本 · 只读预览" : "分集内容 · 尚未采纳"}</span><span>{text.length.toLocaleString()} 字符</span></div>
    <div ref={scrollRef} className="ucl-reading-scroll" tabIndex={0} role="region" aria-label={"第 " + episode.episode_num + " 集正文"}>
      <article className="ucl-reading-page">
        {!/^\s*#{1,2}\s/m.test(text) ? <h4 className="ucl-episode-title">第 {episode.episode_num} 集 · {episode.title}</h4> : null}
        {text.trim() ? <ContentLibraryText text={text} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="本集暂无正文，请在剧本发展中查看完整稿" />}
      </article>
    </div>
  </section>
}
