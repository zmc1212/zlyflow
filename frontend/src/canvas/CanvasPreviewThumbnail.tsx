import { AudioLines, Frame } from "lucide-react"
import { useMemo, useState } from "react"
import { canvasProjectCoverSources } from "./canvas-home"
import type { CanvasPreview } from "./canvas-model"

export default function CanvasPreviewThumbnail({ preview, eager = false }: { preview?: CanvasPreview | null; eager?: boolean }) {
  const sources = useMemo(() => canvasProjectCoverSources(preview), [preview])
  const [failed, setFailed] = useState<string[]>([])
  const [loaded, setLoaded] = useState<string | null>(null)
  const source = sources.find((url) => !failed.includes(url))
  const PlaceholderIcon = preview?.items.some((item) => item.type === "audio") ? AudioLines : Frame

  return (
    <span className="canvas-home-cover" aria-hidden="true">
      <span className="canvas-home-cover-mark"><PlaceholderIcon size={22} strokeWidth={1.5} /></span>
      {source && (
        <img
          key={source}
          className="canvas-home-cover-image"
          src={source}
          alt=""
          data-loaded={source === loaded}
          loading={eager ? "eager" : "lazy"}
          decoding="async"
          onLoad={() => setLoaded(source)}
          onError={() => setFailed((previous) => [...previous, source])}
        />
      )}
    </span>
  )
}
