import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react"
import MediaPreviewModal, { type MediaPreviewNavigation, type PreviewMediaKind } from "../components/MediaPreviewModal"

export type MediaPreviewTarget = {
  kind: PreviewMediaKind
  src: string
  title: string
  description?: string
  aspectRatio?: string
}

export type OpenMediaPreviewInput = {
  src?: string | null
  title?: string
  description?: string
  kind?: PreviewMediaKind
  aspectRatio?: string
  /** 可选：同列表上下切换的完整序列与当前位置；list 有效条目 > 1 时弹窗显示上一个 / 下一个。 */
  list?: OpenMediaPreviewInput[]
  listIndex?: number
}

export function asMediaPreviewTarget(input: OpenMediaPreviewInput): MediaPreviewTarget | null {
  const src = typeof input.src === "string" ? input.src.trim() : ""
  if (!src) return null
  const kind = input.kind || "image"
  const title = (input.title || "").trim() || (kind === "video" ? "视频预览" : "图片预览")
  const description = input.description?.trim() || undefined
  const aspectRatio = input.aspectRatio?.trim() || undefined
  return { kind, src, title, description, aspectRatio }
}

type MediaPreviewState = { items: MediaPreviewTarget[]; index: number } | null

type MediaPreviewContextValue = {
  openMediaPreview: (input: OpenMediaPreviewInput) => void
  /** 打开一组可上下切换的预览（同列表内的上一个 / 下一个）。 */
  openMediaPreviewList: (inputs: OpenMediaPreviewInput[], startIndex?: number) => void
}

const MediaPreviewContext = createContext<MediaPreviewContextValue>({
  openMediaPreview: () => {
    throw new Error("useMediaPreview must be used within MediaPreviewProvider")
  },
  openMediaPreviewList: () => {
    throw new Error("useMediaPreview must be used within MediaPreviewProvider")
  },
})

export function MediaPreviewProvider({ children }: { children: ReactNode }) {
  const [preview, setPreview] = useState<MediaPreviewState>(null)
  const openMediaPreview = useCallback((input: OpenMediaPreviewInput) => {
    const current = asMediaPreviewTarget(input)
    if (!current) return
    const listed = (input.list || [])
      .map(asMediaPreviewTarget)
      .filter((item): item is MediaPreviewTarget => Boolean(item))
    if (listed.length > 1) {
      const rawIndex = input.listIndex
      const index = Math.min(Math.max(0, Math.floor(rawIndex ?? 0)), listed.length - 1)
      // 仅当 listIndex 指向列表内有效位置时，才用当前打开条目替换该位置（例如一采预览替换本镜成片）
      const replaceable = typeof rawIndex === "number" && Number.isInteger(rawIndex) && rawIndex >= 0 && rawIndex < listed.length
      setPreview({ items: replaceable ? listed.map((item, i) => (i === index ? current : item)) : listed, index })
      return
    }
    setPreview({ items: [current], index: 0 })
  }, [])
  const openMediaPreviewList = useCallback((inputs: OpenMediaPreviewInput[], startIndex = 0) => {
    const items = (inputs || []).map(asMediaPreviewTarget).filter((item): item is MediaPreviewTarget => Boolean(item))
    if (!items.length) return
    const index = Math.min(Math.max(0, Math.floor(startIndex)), items.length - 1)
    setPreview({ items, index })
  }, [])
  const stepPreview = useCallback((delta: number) => {
    setPreview((prev) => {
      if (!prev) return prev
      const next = prev.index + delta
      if (next < 0 || next >= prev.items.length) return prev
      return { items: prev.items, index: next }
    })
  }, [])
  const value = useMemo(() => ({ openMediaPreview, openMediaPreviewList }), [openMediaPreview, openMediaPreviewList])

  const navigation: MediaPreviewNavigation | undefined = preview && preview.items.length > 1
    ? {
        hasPrev: preview.index > 0,
        hasNext: preview.index < preview.items.length - 1,
        onPrev: () => stepPreview(-1),
        onNext: () => stepPreview(1),
      }
    : undefined
  const current = preview ? preview.items[preview.index] : null

  return (
    <MediaPreviewContext.Provider value={value}>
      {children}
      {current ? (
        <MediaPreviewModal
          open
          kind={current.kind}
          src={current.src}
          title={current.title}
          description={current.description}
          aspectRatio={current.aspectRatio}
          navigation={navigation}
          onClose={() => setPreview(null)}
        />
      ) : null}
    </MediaPreviewContext.Provider>
  )
}

export function useMediaPreview() {
  return useContext(MediaPreviewContext)
}
