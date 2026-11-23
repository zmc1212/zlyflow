import { Empty, Segmented } from "antd"
import { AudioLines, Image as ImageIcon, Type, Video } from "lucide-react"
import { useEffect, useState } from "react"
import {
  canvasProgressActiveCount,
  canvasProgressClock,
  canvasProgressEmptyText,
  canvasProgressStatusText,
  canvasProgressSummary,
  canvasProgressTabs,
  canvasProgressTone,
  filterCanvasProgress,
  type CanvasProgressEntry,
  type CanvasProgressFilter,
} from "./canvas-progress"

/**
 * 生成进度弹层内容（挂在页头「进度」按钮下，对齐即梦的生成历史浮层）。
 * 定位、点外部收起都由外层 Ant Design Popover 负责；这里只渲染内容。
 */
export function CanvasGenerationProgressPanel({
  entries, onSelect,
}: {
  entries: CanvasProgressEntry[]
  onSelect: (nodeId: string) => void
}) {
  const [filter, setFilter] = useState<CanvasProgressFilter>("all")
  const tabs = canvasProgressTabs(entries)
  const available = tabs.some((tab) => tab.key === filter)

  // 切换筛选后若该类型已没有任务，回到「全部」，避免空列表看起来像功能坏了。
  useEffect(() => {
    if (!available) setFilter("all")
  }, [available])

  const activeCount = canvasProgressActiveCount(entries)
  const visible = filterCanvasProgress(entries, filter)

  return (
    <div className="canvas-progress-panel" aria-label="生成进度">
      <div className="canvas-progress-head">
        <span className="canvas-progress-heading">生成进度</span>
        <span className={`canvas-progress-head-meta${activeCount ? " is-live" : ""}`}>{canvasProgressSummary(entries)}</span>
      </div>
      {tabs.length > 1 ? (
        <Segmented
          className="canvas-progress-tabs"
          size="small"
          value={filter}
          onChange={(value) => setFilter(value as CanvasProgressFilter)}
          options={tabs.map((tab) => ({ value: tab.key, label: tab.count ? `${tab.label} ${tab.count}` : tab.label }))}
        />
      ) : null}
      {visible.length ? (
        <div className="canvas-progress-list" role="list">
          {visible.map((entry) => {
            const tone = canvasProgressTone(entry)
            return (
              <button
                type="button"
                role="listitem"
                key={entry.jobId}
                className={`canvas-progress-row is-${tone}${entry.active ? " is-active" : ""}`}
                onClick={() => onSelect(entry.nodeId)}
                title={entry.error || `${entry.title} · ${entry.workflowName || "生成"}`}
              >
                <span className={`canvas-progress-thumb is-${entry.kind}`}>
                  {entry.previewUrl
                    ? <img src={entry.previewUrl} alt="" loading="lazy" draggable={false} />
                    : entry.kind === "video" ? <Video size={14} />
                      : entry.kind === "audio" ? <AudioLines size={14} />
                        : entry.kind === "text" ? <Type size={14} />
                          : <ImageIcon size={14} />}
                </span>
                <span className="canvas-progress-body">
                  <span className="canvas-progress-line">
                    <strong>{entry.title}</strong>
                    <time>{canvasProgressClock(entry.updatedAt)}</time>
                  </span>
                  <span className="canvas-progress-line is-meta">
                    <span className="canvas-progress-state">{canvasProgressStatusText(entry)}</span>
                    {entry.active && typeof entry.progress === "number" ? <span>{Math.round(entry.progress)}%</span> : null}
                  </span>
                  {entry.active ? (
                    <span
                      className="canvas-generator-progress"
                      role="progressbar"
                      aria-label={`${entry.title} 生成进度`}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={entry.progress ?? undefined}
                    >
                      <span
                        className={entry.progress === null ? "is-indeterminate" : undefined}
                        style={{ width: `${entry.progress ?? 12}%` }}
                      />
                    </span>
                  ) : null}
                </span>
              </button>
            )
          })}
        </div>
      ) : (
        <Empty className="canvas-progress-empty" image={Empty.PRESENTED_IMAGE_SIMPLE} description={canvasProgressEmptyText(filter)} />
      )}
    </div>
  )
}
