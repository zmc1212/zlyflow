export type EditTrack = "video" | "audio" | "text"
export type EditAsset = {
  id: string
  name: string
  kind: "video" | "image" | "audio"
  url: string
  duration: number
  thumbnail?: string | null
  width?: number
  height?: number
  has_audio?: boolean
  beat_id?: string
  local_path?: string
}
export type EditClip = {
  id: string
  track: EditTrack
  asset_id?: string
  start: number
  duration: number
  in_point: number
  speed: number
  volume: number
  muted: boolean
  opacity: number
  scale: number
  x: number
  y: number
  rotation: number
  effect: string
  fade_in: number
  fade_out: number
  text: string
  color: string
  font_size: number
}
export type EditDocument = {
  version: 1
  name: string
  settings: { ratio: string; fps: number; background: string }
  assets: EditAsset[]
  clips: EditClip[]
}
export const RATIOS: Record<string, [number, number]> = {
  "16:9": [1920, 1080],
  "9:16": [1080, 1920],
  "1:1": [1080, 1080],
  "4:3": [1440, 1080],
  "3:4": [1080, 1440]
}
export const EFFECTS = [
  { id: "none", name: "原画", css: "none" },
  { id: "vivid", name: "鲜明", css: "saturate(1.35) contrast(1.08)" },
  { id: "warm", name: "暖调", css: "sepia(.16) saturate(1.1)" },
  { id: "cool", name: "冷调", css: "sepia(.12) hue-rotate(165deg)" },
  { id: "mono", name: "黑白", css: "grayscale(1)" },
  { id: "sepia", name: "复古", css: "sepia(1)" },
  { id: "soft", name: "柔焦", css: "blur(2px)" },
  {
    id: "fade",
    name: "褪色",
    css: "contrast(.85) brightness(1.04) saturate(.8)"
  }
]
export const uid = () => crypto.randomUUID()
export function wrapText(text: string, fontSize: number): string {
  const limit = (1920 * 0.86) / fontSize
  const output: string[] = []
  let line = "",
    used = 0
  for (const char of text.replace(/\r\n?/g, "\n")) {
    if (char === "\n") {
      output.push(line)
      line = ""
      used = 0
      continue
    }
    const weight =
      char.codePointAt(0)! > 127
        ? 1
        : " il.,'`:;!|".includes(char)
          ? 0.35
          : "MWmw@#%&".includes(char)
            ? 0.95
            : 0.65
    if (line && used + weight > limit) {
      output.push(line)
      line = ""
      used = 0
    }
    line += char
    used += weight
  }
  output.push(line)
  return output.join("\n")
}
export const frame = (time: number, fps: number) =>
  Math.round(Math.max(0, time) * fps) / fps
export const endOf = (doc: EditDocument) =>
  Math.max(0, ...doc.clips.map((c) => c.start + c.duration))
export const laneClips = (doc: EditDocument, track: EditTrack) =>
  doc.clips.filter((c) => c.track === track).sort((a, b) => a.start - b.start)
export function blankDocument(): EditDocument {
  return {
    version: 1,
    name: "未命名剪辑",
    settings: { ratio: "16:9", fps: 24, background: "#000000" },
    assets: [],
    clips: []
  }
}
export function timecode(seconds: number, fps = 24): string {
  const total = Math.max(0, Math.round(seconds * fps))
  return [
    Math.floor(total / fps / 60),
    Math.floor(total / fps) % 60,
    total % fps
  ]
    .map((v) => String(v).padStart(2, "0"))
    .join(":")
}
export function gapAt(
  doc: EditDocument,
  track: EditTrack,
  start: number,
  duration: number,
  excluding = ""
): number {
  let cursor = frame(start, doc.settings.fps)
  for (const c of laneClips(doc, track).filter((c) => c.id !== excluding)) {
    if (cursor + duration <= c.start + 0.001) break
    if (cursor < c.start + c.duration - 0.001)
      cursor = frame(c.start + c.duration, doc.settings.fps)
  }
  return cursor
}
export function makeClip(
  doc: EditDocument,
  asset?: EditAsset,
  at = 0
): EditClip {
  const track = asset?.kind === "audio" ? "audio" : asset ? "video" : "text"
  const fps = doc.settings.fps
  const duration = Math.max(
    1 / fps,
    Math.floor((asset?.duration || 3) * fps) / fps
  )
  return {
    id: uid(),
    track,
    asset_id: asset?.id,
    start: gapAt(doc, track, at, duration),
    duration,
    in_point: 0,
    speed: 1,
    volume: 1,
    muted: false,
    opacity: 1,
    scale: 1,
    x: 0,
    y: track === "text" ? 35 : 0,
    rotation: 0,
    effect: "none",
    fade_in: 0,
    fade_out: 0,
    text: asset ? "" : "在这里写下你的故事",
    color: "#ffffff",
    font_size: 64
  }
}
export function patchClip(
  doc: EditDocument,
  id: string,
  patch: Partial<EditClip>
): EditDocument {
  const old = doc.clips.find((c) => c.id === id)
  if (!old) return doc
  const fps = doc.settings.fps
  const next = { ...old, ...patch }
  if (patch.speed !== undefined)
    next.duration = Math.max(
      1 / fps,
      Math.floor(((old.duration * old.speed) / next.speed) * fps) / fps
    )
  next.duration = Math.max(1 / fps, frame(next.duration, fps))
  next.start = frame(next.start, fps)
  const asset = doc.assets.find((a) => a.id === next.asset_id)
  if (
    asset &&
    asset.kind !== "image" &&
    next.in_point + next.duration * next.speed > asset.duration + 0.001
  )
    throw new Error("片段超出原始素材时长，请先缩短片段")
  if (next.fade_in + next.fade_out > next.duration) {
    next.fade_in = Math.min(next.fade_in, next.duration / 2)
    next.fade_out = Math.min(next.fade_out, next.duration / 2)
  }
  if (next.start + next.duration > 1800) throw new Error("时间线最长为 30 分钟")
  if (
    doc.clips.some(
      (c) =>
        c.id !== id &&
        c.track === next.track &&
        next.start < c.start + c.duration - 0.001 &&
        next.start + next.duration > c.start + 0.001
    )
  )
    throw new Error("此位置与同轨片段重叠，请先移动后续片段")
  return { ...doc, clips: doc.clips.map((c) => (c.id === id ? next : c)) }
}
export function splitClip(
  doc: EditDocument,
  id: string,
  at: number
): EditDocument {
  const clip = doc.clips.find((c) => c.id === id)
  if (!clip) return doc
  const cut = frame(at, doc.settings.fps)
  if (cut <= clip.start + 0.001 || cut >= clip.start + clip.duration - 0.001)
    return doc
  const left = cut - clip.start
  return {
    ...doc,
    clips: doc.clips.flatMap((c) =>
      c.id === id
        ? [
            {
              ...c,
              duration: left,
              fade_out: 0,
              fade_in: Math.min(c.fade_in, left / 2)
            },
            {
              ...c,
              id: uid(),
              start: cut,
              duration: frame(c.duration - left, doc.settings.fps),
              in_point: c.in_point + left * c.speed,
              fade_in: 0,
              fade_out: Math.min(c.fade_out, (c.duration - left) / 2)
            }
          ]
        : [c]
    )
  }
}
export function packLane(
  doc: EditDocument,
  track: EditTrack,
  ordered?: EditClip[]
): EditDocument {
  let cursor = 0
  const moved = new Map(
    (ordered || laneClips(doc, track)).map((c) => {
      const value = { ...c, start: cursor }
      cursor = frame(cursor + c.duration, doc.settings.fps)
      return [c.id, value]
    })
  )
  return { ...doc, clips: doc.clips.map((c) => moved.get(c.id) || c) }
}
export function moveClip(
  doc: EditDocument,
  id: string,
  at: number,
  snap = true
): EditDocument {
  const clip = doc.clips.find((c) => c.id === id)
  if (!clip) return doc
  let target = frame(at, doc.settings.fps)
  if (snap) {
    const edges = [
      0,
      ...doc.clips
        .filter((c) => c.id !== id)
        .flatMap((c) => [c.start, c.start + c.duration])
    ]
    for (const edge of edges) {
      if (Math.abs(target - edge) < 0.18) target = edge
      else if (Math.abs(target + clip.duration - edge) < 0.18)
        target = edge - clip.duration
    }
  }
  return patchClip(doc, id, { start: Math.max(0, target) })
}
export function reorderClip(
  doc: EditDocument,
  id: string,
  direction: -1 | 1
): EditDocument {
  const clip = doc.clips.find((c) => c.id === id)
  if (!clip) return doc
  const ordered = laneClips(doc, clip.track),
    index = ordered.findIndex((c) => c.id === id),
    other = index + direction
  if (!ordered[other]) return doc
  ;[ordered[index], ordered[other]] = [ordered[other], ordered[index]]
  return packLane(doc, clip.track, ordered)
}
export function duplicateClip(doc: EditDocument, id: string): EditDocument {
  const source = doc.clips.find((c) => c.id === id)
  if (!source) return doc
  const copy = {
    ...source,
    id: uid(),
    start: gapAt(
      doc,
      source.track,
      source.start + source.duration,
      source.duration
    )
  }
  return { ...doc, clips: [...doc.clips, copy] }
}
export function roughCut(doc: EditDocument): EditDocument {
  const next = { ...doc, clips: [] as EditClip[] }
  // Prefer ordered adopted shot videos; use storyboards only if a shot has no video.
  const pictures = [
    ...new Map(
      doc.assets
        .filter((a) => a.beat_id && a.kind !== "audio")
        .map((a) => [a.beat_id, a])
    ).values()
  ]
  for (const asset of pictures.length
    ? pictures
    : doc.assets.filter((a) => a.kind !== "audio")) {
    const clip = makeClip(next, asset, endOf(next))
    next.clips.push(clip)
  }
  for (const asset of doc.assets.filter(
    (a) => a.kind === "audio" && a.beat_id
  )) {
    const picture = next.clips.find(
      (c) =>
        doc.assets.find((a) => a.id === c.asset_id)?.beat_id === asset.beat_id
    )
    next.clips.push(makeClip(next, asset, picture?.start || 0))
  }
  return next
}
export function parseDocument(text: string): EditDocument {
  const doc = JSON.parse(text) as EditDocument
  if (
    doc?.version !== 1 ||
    typeof doc.name !== "string" ||
    !doc.settings ||
    !RATIOS[doc.settings.ratio] ||
    ![24, 25, 30, 60].includes(doc.settings.fps) ||
    !/^#[0-9a-f]{6}$/i.test(doc.settings.background) ||
    !Array.isArray(doc.assets) ||
    !Array.isArray(doc.clips) ||
    doc.assets.length > 300 ||
    doc.clips.length > 200
  )
    throw new Error("这不是有效的 ZLY 剪辑工程")
  const ids = new Set<string>()
  for (const asset of doc.assets) {
    if (
      !asset.id ||
      ids.has(asset.id) ||
      !["image", "video", "audio"].includes(asset.kind) ||
      !Number.isFinite(asset.duration) ||
      asset.duration <= 0 ||
      typeof asset.name !== "string" ||
      !(
        /^https?:\/\//.test(asset.url) ||
        /^\/api\/local-media\/[A-Za-z0-9_-]{4,2048}\.[0-9a-f]{32}$/.test(asset.url)
      )
    )
      throw new Error("工程中的素材无效")
    ids.add(asset.id)
  }
  const clipIds = new Set<string>()
  for (const c of doc.clips) {
    if (
      !c.id ||
      clipIds.has(c.id) ||
      !["video", "audio", "text"].includes(c.track) ||
      ![
        c.start,
        c.duration,
        c.speed,
        c.in_point,
        c.volume,
        c.opacity,
        c.scale,
        c.x,
        c.y,
        c.rotation,
        c.fade_in,
        c.fade_out,
        c.font_size
      ].every(Number.isFinite) ||
      c.start < 0 ||
      c.duration < 1 / doc.settings.fps - 0.001 ||
      c.speed < 0.25 ||
      c.speed > 4 ||
      c.in_point < 0 ||
      c.opacity < 0 ||
      c.opacity > 1 ||
      c.volume < 0 ||
      c.volume > 2 ||
      c.scale < 0.25 ||
      c.scale > 3 ||
      Math.abs(c.x) > 100 ||
      Math.abs(c.y) > 100 ||
      Math.abs(c.rotation) > 180 ||
      c.fade_in < 0 ||
      c.fade_out < 0 ||
      c.font_size < 16 ||
      c.font_size > 200 ||
      Math.abs(
        c.start * doc.settings.fps - Math.round(c.start * doc.settings.fps)
      ) > 0.001 ||
      Math.abs(
        c.duration * doc.settings.fps -
          Math.round(c.duration * doc.settings.fps)
      ) > 0.001 ||
      c.fade_in + c.fade_out > c.duration + 0.001 ||
      !EFFECTS.some((e) => e.id === c.effect) ||
      (c.track === "text" &&
        (typeof c.text !== "string" || !/^#[0-9a-f]{6}$/i.test(c.color)))
    )
      throw new Error("工程中的片段参数无效")
    clipIds.add(c.id)
    if (c.track !== "text") {
      const asset = doc.assets.find((a) => a.id === c.asset_id)
      if (!asset || (c.track === "audio") !== (asset.kind === "audio"))
        throw new Error("工程缺少片段使用的素材")
    }
    const others = {
      ...doc,
      clips: doc.clips.filter((item) => item.id !== c.id)
    }
    patchClip({ ...others, clips: [...others.clips, c] }, c.id, {})
  }
  return doc
}
