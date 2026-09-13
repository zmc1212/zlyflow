import { ChevronDown, ChevronRight } from "lucide-react"
import { useState } from "react"
import { SCRIPT_TASK_ROWS_TITLE } from "../action-copy"

export type TaskRow = {
  id: string
  label: string
  status: string
  message: string
}

/** 已完成环节的产出预览（镜头视频/静帧、画风封面等），仅使用产品数据模型里已有的 URL。 */
export type TaskRowPreview = {
  src: string
  kind: "video" | "image"
  durationLabel?: string
  ratioLabel?: string
}

type Props = {
  rows: TaskRow[]
  running: boolean
  elapsedSec: number
  /** Force the panel open (e.g. the transcript is still streaming). */
  pinnedOpen?: boolean
  /** Retry a failed step (e.g. rerun a single agent); absent hides the affordance. */
  onRetry?: (id: string) => void
  /** Regenerate a completed step; absent hides the affordance. */
  onRegenerate?: (id: string) => void
  /** Open a settled step's full output (drawer); absent keeps rows inert. */
  onOpen?: (id: string) => void
  /** "panel"（默认，可折叠面板）| "rail"（左侧任务栏：常开、无折叠、行内不显示消息） */
  variant?: "panel" | "rail"
  /** 环节产出预览（按环节 id 索引），completed 行内嵌展示。 */
  previews?: Record<string, TaskRowPreview>
}

function formatElapsed(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return minutes > 0 ? `${minutes} 分 ${String(seconds).padStart(2, "0")} 秒` : `${seconds} 秒`
}

/* 官方 Task Rows 的 SVG 圆环序号徽章：灰底环 + 旋转弧（运行中）+ 中心序号。 */
function SpinnerRing({ active, order }: { active?: boolean; order: number }) {
  const size = 22
  const stroke = 2
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  return (
    <span className="director-ring" style={{ width: size, height: size }}>
      <svg width={size} height={size} className={active ? "is-spin" : undefined}>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--director-line)" strokeWidth={stroke} />
        {active ? (
          <circle
            cx={size / 2} cy={size / 2} r={radius} fill="none"
            stroke="var(--director-accent)" strokeWidth={stroke} strokeLinecap="round"
            strokeDasharray={`${circumference * 0.28} ${circumference * 0.72}`}
          />
        ) : null}
      </svg>
      <span className="director-ring-num">{order}</span>
    </span>
  )
}

/** 官方式实心圆状态徽章（完成绿勾 / 失败红叉，pop-in 弹出）。 */
function StatusBadge({ tone, children }: { tone: "green" | "red"; children: React.ReactNode }) {
  return (
    <span className={`director-badge is-${tone}`}>{children}</span>
  )
}

function CheckIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6L9 17l-5-5" /></svg>
  )
}

function XIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round"><path d="M18 6L6 18M6 6l12 12" /></svg>
  )
}

/* 官方失败 pill 内的重试图标（官方 task-rows.tsx RetryIcon 原路径）。 */
function RetryIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" /></svg>
  )
}

function PreviewPlayIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M8 5.5v13l11-6.5-11-6.5z" /></svg>
  )
}

/** 已完成环节的产出缩略图（视频首帧自动预览 / 静帧图片），数据来自镜头与画风字段。 */
function TaskRowPreviewMedia({ preview }: { preview: TaskRowPreview }) {
  return (
    <span className="director-task-preview" aria-hidden>
      {preview.kind === "video" ? (
        <video src={preview.src} muted playsInline preload="metadata" />
      ) : (
        <img src={preview.src} alt="" loading="lazy" />
      )}
      <span className="director-task-preview-play">{preview.kind === "video" ? <PreviewPlayIcon /> : null}</span>
      {(preview.durationLabel || preview.ratioLabel) ? (
        <span className="director-task-preview-meta">
          {preview.durationLabel ? <b>{preview.durationLabel}</b> : null}
          {preview.ratioLabel ? <i>{preview.ratioLabel}</i> : null}
        </span>
      ) : null}
    </span>
  )
}

/**
 * Vertical Task Rows panel following the official beautifului capsule grammar:
 * ring-sequence badges, solid status badges, tint status pills, per-row capsule
 * cards with hairline shadows, and a collapsed summary once everything settles.
 */
export default function DirectorTaskRows({ rows, running, elapsedSec, pinnedOpen = false, onRetry, onRegenerate, onOpen, variant = "panel", previews }: Props) {
  const relevant = rows.filter((row) => row.status !== "pending" || running)
  const finished = relevant.filter((row) => row.status === "completed" || row.status === "failed").length
  const percent = relevant.length ? Math.round((finished / relevant.length) * 100) : 0
  const [userExpanded, setUserExpanded] = useState<boolean | null>(null)
  const open = variant === "rail" ? true : (userExpanded ?? (pinnedOpen || running))

  const railHead = (
    <div className="director-task-rail-head">
      <div className="director-task-rail-title">
        <strong>{SCRIPT_TASK_ROWS_TITLE}</strong>
        <span>{finished}/{relevant.length}</span>
      </div>
      <span className="director-task-rows-track" aria-hidden>
        <span className="director-task-rows-fill" style={{ width: `${percent}%` }} />
      </span>
      <div className="director-task-rail-meta">
        <em>{percent}%</em>
        {elapsedSec >= 0 && running ? <span>已进行 {formatElapsed(elapsedSec)}</span> : null}
      </div>
    </div>
  )

  if (variant === "rail") {
    return (
      <section className="director-task-rows is-rail is-open" aria-label={SCRIPT_TASK_ROWS_TITLE}>
        {railHead}
        <ol className="director-task-rows-list">
          {relevant.map((row, index) => {
            const canOpen = Boolean(onOpen) && (row.status === "completed" || row.status === "failed")
            const preview = row.status === "completed" ? previews?.[row.id] : undefined
            return (
              <li
                key={row.id}
                className={`director-task-row is-${row.status}${canOpen ? " is-clickable" : ""}${preview ? " has-preview" : ""}`}
                style={{ animation: `director-fade-up 450ms cubic-bezier(0.23,1,0.32,1) ${index * 80}ms both` }}
                {...(canOpen ? { onClick: () => onOpen?.(row.id), title: "查看这一步的产出" } : {})}
              >
                <span className="director-task-row-icon" aria-hidden>
                  {row.status === "completed" ? <StatusBadge tone="green"><CheckIcon /></StatusBadge>
                    : row.status === "failed" ? <StatusBadge tone="red"><XIcon /></StatusBadge>
                      : <SpinnerRing active={row.status === "running"} order={index + 1} />}
                </span>
                <span className="director-task-row-label">{row.label}</span>
                {row.status === "completed" ? <span className="director-task-pill is-green">已完成</span> : null}
                {row.status === "completed" && onRegenerate ? (
                  <button
                    type="button"
                    className="director-task-regen"
                    title="重新生成这一环节"
                    disabled={running}
                    onClick={(event) => {
                      event.stopPropagation()
                      onRegenerate(row.id)
                    }}
                  >
                    <span className="director-task-regen-icon" aria-hidden><RetryIcon /></span>
                  </button>
                ) : null}
                {row.status === "failed" ? (
                  onRetry ? (
                    <button
                      type="button"
                      className="director-task-pill is-red director-task-retry"
                      title="重跑这一步"
                      disabled={running}
                      onClick={(event) => {
                        event.stopPropagation()
                        onRetry(row.id)
                      }}
                    >
                      失败
                      <span className="director-task-retry-icon" aria-hidden><RetryIcon /></span>
                    </button>
                  ) : (
                    <span className="director-task-pill is-red">失败</span>
                  )
                ) : null}
                {preview ? <TaskRowPreviewMedia preview={preview} /> : null}
              </li>
            )
          })}
        </ol>
      </section>
    )
  }

  return (
    <section className={`director-task-rows${open ? " is-open" : " is-collapsed"}`} aria-label={SCRIPT_TASK_ROWS_TITLE}>
      <button
        type="button"
        className="director-task-rows-head"
        onClick={() => setUserExpanded(!open)}
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <strong>{SCRIPT_TASK_ROWS_TITLE}</strong>
        <span className="director-task-rows-meta">
          {finished}/{relevant.length}
          {elapsedSec >= 0 ? ` · 已进行 ${formatElapsed(elapsedSec)}` : ""}
        </span>
        <span className="director-task-rows-track" aria-hidden>
          <span className="director-task-rows-fill" style={{ width: `${percent}%` }} />
        </span>
        <em className="director-task-rows-percent">{percent}%</em>
      </button>
      {open ? (
        <ol className="director-task-rows-list">
          {relevant.map((row, index) => {
            const canOpen = Boolean(onOpen) && (row.status === "completed" || row.status === "failed")
            const preview = row.status === "completed" ? previews?.[row.id] : undefined
            return (
              <li
                key={row.id}
                className={`director-task-row is-${row.status}${canOpen ? " is-clickable" : ""}${preview ? " has-preview" : ""}`}
                style={{ animation: `director-fade-up 450ms cubic-bezier(0.23,1,0.32,1) ${index * 80}ms both` }}
                {...(canOpen ? { onClick: () => onOpen?.(row.id), title: "查看这一步的产出" } : {})}
              >
                <span className="director-task-row-icon" aria-hidden>
                  {row.status === "completed" ? <StatusBadge tone="green"><CheckIcon /></StatusBadge>
                    : row.status === "failed" ? <StatusBadge tone="red"><XIcon /></StatusBadge>
                      : <SpinnerRing active={row.status === "running"} order={index + 1} />}
                </span>
                <span className="director-task-row-label">{row.label}</span>
                {row.status === "running" && row.message ? (
                  <span className="director-task-row-message">{row.message}</span>
                ) : null}
                {row.status === "completed" ? <span className="director-task-pill is-green">已完成</span> : null}
                {row.status === "completed" && onRegenerate ? (
                  <button
                    type="button"
                    className="director-task-regen"
                    title="重新生成这一环节"
                    disabled={running}
                    onClick={(event) => {
                      event.stopPropagation()
                      onRegenerate(row.id)
                    }}
                  >
                    <span className="director-task-regen-icon" aria-hidden><RetryIcon /></span>
                  </button>
                ) : null}
                {row.status === "failed" ? (
                  onRetry ? (
                    <button
                      type="button"
                      className="director-task-pill is-red director-task-retry"
                      title="重跑这一步"
                      disabled={running}
                      onClick={(event) => {
                        event.stopPropagation()
                        onRetry(row.id)
                      }}
                    >
                      失败
                      <span className="director-task-retry-icon" aria-hidden><RetryIcon /></span>
                    </button>
                  ) : (
                    <span className="director-task-pill is-red">失败</span>
                  )
                ) : null}
                {preview ? <TaskRowPreviewMedia preview={preview} /> : null}
              </li>
            )
          })}
        </ol>
      ) : null}
    </section>
  )
}
