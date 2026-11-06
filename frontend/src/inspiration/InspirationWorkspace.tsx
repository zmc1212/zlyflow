import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { Empty, Modal, Spin, message } from "antd"
import { ChevronLeft, ChevronRight, Images, Sparkles, X } from "lucide-react"
import { requestJson } from "../api"
import "./inspiration.css"

export type ShowcaseItem = {
  id: string
  slug: string
  category: string
  title: string
  blurb: string
  origin: string
  mode: string
  prompt: string
  display_prompt: string
  negative_prompt: string
  image_size: string
  options: Record<string, string | boolean>
  references: { url: string; name: string }[]
  tags: string[]
  cover_url: string
  media_url: string
  media_type: "image" | "video"
  duration_seconds: number
  source_job_id: string
  sort_order: number
}

type ShowcaseResponse = {
  items: ShowcaseItem[]
  categories: { category: string; total: number }[]
}

const ALL = "全部"
const BRAND = "ZLY AI Studio"
const GRID_GAP = 16
/** 卡片正文（标题 + 两行简介 + 标签 + 内边距）的实测典型高度，用于首帧分列估算。 */
const CARD_BODY_HEIGHT = 128

/** 从示例的 aspect_ratio / image_size 取画面宽高比，取不到按横屏 16:9 兜底。 */
function mediaAspect(item: ShowcaseItem): number {
  const candidates = [String(item.options?.aspect_ratio ?? ""), item.image_size ?? ""]
  for (const value of candidates) {
    const match = value.match(/(\d+(?:\.\d+)?)\s*[:xX×]\s*(\d+(?:\.\d+)?)/)
    if (match) {
      const w = Number(match[1])
      const h = Number(match[2])
      if (w > 0 && h > 0 && w / h <= 4) return w / h
    }
  }
  return 16 / 9
}

/** 瀑布流分列：依次把卡片放进当前总高最矮的一列（同高取靠左）。
   列尾最平整；阅读顺序为列内从上到下、列间从左到右，不保证全局行序（瀑布流固有特性）。 */
function splitMasonry<T>(items: T[], columns: number, heightOf: (item: T) => number): T[][] {
  const buckets: T[][] = Array.from({ length: columns }, () => [])
  const heights = new Array<number>(columns).fill(0)
  for (const item of items) {
    const target = heights.indexOf(Math.min(...heights))
    buckets[target].push(item)
    heights[target] += heightOf(item) + GRID_GAP
  }
  return buckets
}

/** 容器宽度 → 列数，沿用原网格断点（>1100 三列、>768 两列、其余单列）。 */
function columnCountFor(width: number): number {
  if (width > 1100) return 3
  if (width > 768) return 2
  return 1
}

function useContainerWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    setWidth(el.clientWidth)
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  return [ref, width] as const
}

/** 卡片缩略：有封面用封面，否则让 <video> 只取 metadata，用 0.5 秒处当海报，省掉抽帧流水线。 */
export function ShowcaseThumb({ item }: { item: ShowcaseItem }) {
  if (item.cover_url) return <img className="inspiration-thumb" src={item.cover_url} alt={item.title} loading="lazy" />
  if (item.media_type === "image" && item.media_url) return <img className="inspiration-thumb" src={item.media_url} alt={item.title} loading="lazy" />
  if (item.media_url) {
    return (
      <video
        className="inspiration-thumb"
        src={`${item.media_url}#t=0.5`}
        muted
        playsInline
        preload="metadata"
        aria-hidden="true"
      />
    )
  }
  return <div className="inspiration-thumb inspiration-thumb-empty"><Images size={22} /></div>
}

/** 瀑布流卡片：媒体高度由成品比例决定，竖屏不再被裁成 16:9，也不撑坏其他行。 */
function ShowcaseCard({ item, aspectRatio, onOpen }: {
  item: ShowcaseItem
  aspectRatio: number
  onOpen: (id: string) => void
}) {
  return (
    <article
      data-item-id={item.id}
      className="inspiration-card"
      role="button"
      tabIndex={0}
      onClick={() => onOpen(item.id)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault()
          onOpen(item.id)
        }
      }}
    >
      <div className="inspiration-card-media" style={{ aspectRatio: String(aspectRatio) }}>
        <ShowcaseThumb item={item} />
      </div>
      <div className="inspiration-card-body">
        <h2>{item.title}</h2>
        <p>{item.blurb || item.display_prompt || item.category}</p>
        <div className="inspiration-card-footer">
          <span className="inspiration-card-tag">{item.category}</span>
        </div>
      </div>
    </article>
  )
}

export default function InspirationWorkspace({ onUseInComposer }: {
  onUseInComposer: (item: ShowcaseItem) => void | Promise<void>
}) {
  const [items, setItems] = useState<ShowcaseItem[]>([])
  const [categories, setCategories] = useState<{ category: string; total: number }[]>([])
  const [category, setCategory] = useState<string>(ALL)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState("")
  const [activeId, setActiveId] = useState<string | null>(null)
  const [promptExpanded, setPromptExpanded] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [messageApi, contextHolder] = message.useMessage()
  const videoRef = useRef<HTMLVideoElement>(null)
  const autoPlayedRef = useRef<string | null>(null)

  useEffect(() => {
    let cancelled = false
    requestJson<ShowcaseResponse>("/api/showcase")
      .then((data) => {
        if (cancelled) return
        setItems(data.items ?? [])
        setCategories(data.categories ?? [])
      })
      .catch((error: unknown) => {
        if (cancelled) return
        setFailed(error instanceof Error ? error.message : "示例库加载失败")
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const filtered = useMemo(
    () => (category === ALL ? items : items.filter((item) => item.category === category)),
    [items, category],
  )

  const activeIndex = useMemo(
    () => filtered.findIndex((item) => item.id === activeId),
    [filtered, activeId],
  )
  const active = activeIndex >= 0 ? filtered[activeIndex] : null

  const openItem = useCallback((id: string) => {
    setActiveId(id)
    setPlaying(false)
    setPromptExpanded(false)
  }, [])

  const step = useCallback((delta: number) => {
    setActiveId((current) => {
      if (!filtered.length) return current
      const index = filtered.findIndex((item) => item.id === current)
      if (index < 0) return current
      return filtered[(index + delta + filtered.length) % filtered.length].id
    })
    setPlaying(false)
  }, [filtered])

  useEffect(() => {
    if (!active) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "ArrowRight") step(1)
      if (event.key === "ArrowLeft") step(-1)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [active, step])

  // 不依赖 effect 挂载时机（Modal destroyOnHidden + portal 动画会使首开时 videoRef 仍为 null）：
  // 改在 <video> 自身源加载就绪的 canplay 事件里触发自动播放，并用 url 去重避免重复抢播。
  const handleStageCanPlay = (el: HTMLVideoElement, url: string) => {
    if (autoPlayedRef.current === url) return
    autoPlayedRef.current = url
    // 带声自动播放被浏览器策略拦截时回退为静音播放，保证「点开直接播」，用户仍可手动取消静音。
    el.play().catch(() => {
      el.muted = true
      el.play().catch(() => {})
    })
  }

  const copyPrompt = async (item: ShowcaseItem) => {
    try {
      await navigator.clipboard.writeText(item.prompt)
      messageApi.success("已复制提示词")
    } catch {
      messageApi.error("浏览器拒绝了剪贴板访问，请手动选择文本复制")
    }
  }

  const categoryOptions = useMemo(
    () => [ALL, ...categories.map((entry) => entry.category)],
    [categories],
  )

  const [gridRef, gridWidth] = useContainerWidth<HTMLDivElement>()
  const columns = columnCountFor(gridWidth || 1200)
  const columnWidth = gridWidth ? (gridWidth - GRID_GAP * (columns - 1)) / columns : 0
  // 迭代收敛布局：首帧按「比例高度 + 正文估算」分列，挂载后回读真实卡高重排，
  // 直到本轮测量与上轮一致（同一 layoutKey 最多重排 4 次），消除估算误差且不会测量↔重排死循环。
  const MAX_LAYOUT_PASSES = 4
  const [measured, setMeasured] = useState<{ key: string; heights: Record<string, number> } | null>(null)
  const relayoutCountRef = useRef(0)
  const layoutKey = `${category}|${columns}|${filtered.map((item) => item.id).join(",")}`
  const masonryHeights = useMemo(() => {
    const map: Record<string, number> = {}
    for (const item of filtered) {
      map[item.id] = measured?.heights[item.id]
        ?? ((columnWidth || 360) / mediaAspect(item) + CARD_BODY_HEIGHT)
    }
    return map
  }, [filtered, measured, columnWidth])
  useLayoutEffect(() => {
    if (!filtered.length) return
    if (measured?.key === layoutKey && (relayoutCountRef.current >= MAX_LAYOUT_PASSES
      || Object.entries(measured.heights).every(([id, h]) => Math.abs((masonryHeights[id] ?? 0) - h) < 1))) return
    const el = gridRef.current
    if (!el) return
    const heights: Record<string, number> = {}
    el.querySelectorAll<HTMLElement>(".inspiration-card[data-item-id]").forEach((card) => {
      heights[card.dataset.itemId as string] = card.offsetHeight
    })
    if (measured?.key === layoutKey) relayoutCountRef.current += 1
    else relayoutCountRef.current = 0
    setMeasured({ key: layoutKey, heights })
  }, [layoutKey, measured, masonryHeights, gridRef, filtered, columns])
  const masonry = useMemo(
    () => splitMasonry(filtered, columns, (item) => masonryHeights[item.id]),
    [filtered, columns, masonryHeights],
  )

  return (
    <section className="inspiration-workspace" aria-label="灵感示例库">
      {contextHolder}
      <header className="inspiration-header">
        <div>
          <h1>灵感示例库</h1>
          <p>每条示例都是本工作台真实跑出的一条成品，点开可以看到完整提示词，并一键带回创作台复现。</p>
        </div>
      </header>

      <div className="inspiration-gallery">
        <div className="inspiration-categories" aria-label="按分类筛选">
          {categoryOptions.map((option) => (
            <button
              key={option}
              type="button"
              className={`inspiration-chip${category === option ? " is-active" : ""}`}
              aria-pressed={category === option}
              onClick={() => setCategory(option)}
            >
              {option}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="inspiration-state"><Spin tip="正在读取示例库" ><div className="min-h-[240px] w-[240px]" /></Spin></div>
        ) : failed ? (
          <div className="inspiration-state"><Empty description={failed} /></div>
        ) : !filtered.length ? (
          <div className="inspiration-state"><Empty description="这个分类还没有已发布的示例" /></div>
        ) : (
          <div className="inspiration-grid" ref={gridRef}>
            {masonry.map((column, index) => (
              <div className="inspiration-column" key={index}>
                {column.map((item) => (
                  <ShowcaseCard
                    key={item.id}
                    item={item}
                    aspectRatio={mediaAspect(item)}
                    onOpen={openItem}
                  />
                ))}
              </div>
            ))}
          </div>
        )}
      </div>

      <Modal
        className="inspiration-modal"
        classNames={{ mask: "inspiration-modal-mask" }}
        open={Boolean(active)}
        onCancel={() => { setActiveId(null); setPlaying(false); autoPlayedRef.current = null }}
        footer={null}
        destroyOnHidden
        width="calc(100vw - 24px)"
        style={{ top: 12 }}
        title={null}
        closeIcon={null}
      >
        {active ? (
          <div className="inspiration-preview">
            <div className="inspiration-stage">
              <div className="inspiration-canvas">
                {active.media_type === "image" ? (
                  <img
                    className="inspiration-stage-media"
                    src={active.media_url || active.cover_url}
                    alt={active.title}
                  />
                ) : active.media_url ? (
                  <video
                    ref={videoRef}
                    className="inspiration-stage-media"
                    src={active.media_url}
                    poster={active.cover_url || undefined}
                    controls
                    playsInline
                    onCanPlay={(event) => handleStageCanPlay(event.currentTarget, active.media_url)}
                    onPlay={() => setPlaying(true)}
                    onPause={() => setPlaying(false)}
                  />
                ) : (
                  <div className="inspiration-stage-empty">这条示例还没有可播放的成品</div>
                )}
              </div>
              <button
                type="button"
                className="inspiration-arrow inspiration-arrow-prev"
                aria-label="上一条示例"
                onClick={() => step(-1)}
              >
                <ChevronLeft size={18} />
              </button>
              <button
                type="button"
                className="inspiration-arrow inspiration-arrow-next"
                aria-label="下一条示例"
                onClick={() => step(1)}
              >
                <ChevronRight size={18} />
              </button>
              <div className="inspiration-strip">
                {filtered.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={`inspiration-strip-item${item.id === active.id ? " is-active" : ""}`}
                    aria-label={`查看 ${item.title}`}
                    onClick={() => openItem(item.id)}
                  >
                    <ShowcaseThumb item={item} />
                  </button>
                ))}
              </div>
            </div>

            <aside className="inspiration-chat">
              <div className="inspiration-chat-head">
                <div className="inspiration-chat-meta">
                  <h2 className="inspiration-chat-title">{active.title}</h2>
                  {active.blurb ? <p className="inspiration-chat-desc">{active.blurb}</p> : null}
                </div>
                <button
                  type="button"
                  className="inspiration-chat-close"
                  aria-label="关闭"
                  onClick={() => { setActiveId(null); setPlaying(false); autoPlayedRef.current = null }}
                >
                  <X size={18} />
                </button>
              </div>

              <div className="inspiration-thread">
                {active.references.length ? (
                  <div className="inspiration-msg-images">
                    {active.references.map((reference) => (
                      <img key={reference.url} src={reference.url} alt={reference.name} loading="lazy" />
                    ))}
                  </div>
                ) : null}
                <div className="inspiration-msg-user">请用 {BRAND} 生成：{active.title}</div>
                <p className="inspiration-msg-reply">
                  {active.media_type === "image"
                    ? "按提示词生成图片，画面风格与主体保持不变。"
                    : "按提示词生成视频，镜头、风格和文案保持不变。"}
                </p>
                <div className="inspiration-msg-tool">
                  <span className="inspiration-msg-tool-icon"><Sparkles size={13} /></span>
                  {BRAND}
                </div>
                <div className="inspiration-msg-result">
                  <p className={`inspiration-msg-prompt${promptExpanded ? "" : " is-clamped"}`}>{active.prompt}</p>
                  <button
                    type="button"
                    className="inspiration-msg-expand"
                    onClick={() => setPromptExpanded((value) => !value)}
                  >
                    {promptExpanded ? "收起" : "展开"}
                  </button>
                </div>
                <div className="inspiration-msg-tags">
                  <span className="inspiration-msg-tag">{active.media_type === "image" ? "图片" : "视频"}</span>
                  {active.duration_seconds ? <span className="inspiration-msg-tag">{active.duration_seconds}秒</span> : null}
                  {active.image_size ? <span className="inspiration-msg-tag">{active.image_size}</span> : null}
                  <span className="inspiration-msg-tag">{active.category}</span>
                  {active.tags.map((tag) => <span key={tag} className="inspiration-msg-tag">{tag}</span>)}
                </div>
              </div>

              <div className="inspiration-chat-foot">
                <button
                  type="button"
                  className="inspiration-use-btn"
                  onClick={() => { onUseInComposer(active); setActiveId(null) }}
                >
                  <Sparkles size={16} />
                  在工作台使用
                </button>
                <button type="button" className="inspiration-copy-btn" onClick={() => copyPrompt(active)}>
                  复制 prompt
                </button>
              </div>
            </aside>
          </div>
        ) : null}
      </Modal>
    </section>
  )
}
