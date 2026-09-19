import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react"
import MediaPreviewModal, { type PreviewMediaKind } from "../components/MediaPreviewModal"

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

type MediaPreviewContextValue = {
  openMediaPreview: (input: OpenMediaPreviewInput) => void
}

const MediaPreviewContext = createContext<MediaPreviewContextValue>({
  openMediaPreview: () => {
    throw new Error("useMediaPreview must be used within MediaPreviewProvider")
  },
})

export function MediaPreviewProvider({ children }: { children: ReactNode }) {
  const [preview, setPreview] = useState<MediaPreviewTarget | null>(null)
  const openMediaPreview = useCallback((input: OpenMediaPreviewInput) => {
    const next = asMediaPreviewTarget(input)
    if (next) setPreview(next)
  }, [])
  const value = useMemo(() => ({ openMediaPreview }), [openMediaPreview])

  return (
    <MediaPreviewContext.Provider value={value}>
      {children}
      {preview ? (
        <MediaPreviewModal
          open
          kind={preview.kind}
          src={preview.src}
          title={preview.title}
          description={preview.description}
          aspectRatio={preview.aspectRatio}
          onClose={() => setPreview(null)}
        />
      ) : null}
    </MediaPreviewContext.Provider>
  )
}

export function useMediaPreview() {
  return useContext(MediaPreviewContext)
}
