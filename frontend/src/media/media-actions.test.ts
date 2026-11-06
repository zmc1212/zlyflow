import { describe, expect, it } from "vitest"
import { MEDIA_ACTION_BAR_LIMIT, mediaActionMenu, mediaActions, mediaActionBar, type MediaActionInput } from "./media-actions"
import { IMAGE_BACKGROUND_REMOVE_WORKFLOW, IMAGE_ERASER_WORKFLOW, IMAGE_INPAINT_WORKFLOW, IMAGE_LAYER_SPLIT_WORKFLOW, IMAGE_OUTPAINT_WORKFLOW } from "../generation/image-edit"
import { FACE_RESTORE_WORKFLOW } from "../generation/face-restore"
import { INPAINT_WORKFLOW } from "../generation/inpaint"
import { LIP_SYNC_WORKFLOW } from "../generation/lip-sync"
import { UPSCALE_ENGINE_RTX, UPSCALE_ENGINE_SEEDVR2 } from "../generation/upscale"

const ALL_MODES = [
  { id: "grs-gpt-image-2.5", name: "GRS 改图", media_type: "image", available: true },
  { id: IMAGE_INPAINT_WORKFLOW, media_type: "image", available: true },
  { id: IMAGE_ERASER_WORKFLOW, media_type: "image", available: true },
  { id: IMAGE_BACKGROUND_REMOVE_WORKFLOW, media_type: "image", available: true },
  { id: IMAGE_OUTPAINT_WORKFLOW, media_type: "image", available: true },
  { id: IMAGE_LAYER_SPLIT_WORKFLOW, media_type: "image", available: true },
  { id: UPSCALE_ENGINE_RTX, media_type: "video", available: true },
  { id: INPAINT_WORKFLOW, media_type: "video", available: true },
  { id: FACE_RESTORE_WORKFLOW, media_type: "video", available: true },
  { id: LIP_SYNC_WORKFLOW, media_type: "video", available: true },
]

const IMAGE_SOURCE = { jobId: "job-1", generationItemId: "item-1", outputIndex: 0, kind: "image" as const }
const VIDEO_SOURCE = { jobId: "job-1", generationItemId: "item-1", outputIndex: 2, kind: "video" as const }

const FULL_HOST = {
  reference: true, canvas: true, jianying: true, params: true, remove: true,
  reEdit: true, regenerate: true, createVideo: true,
}

function items(overrides: Partial<MediaActionInput>) {
  return mediaActions({ kind: "image", source: IMAGE_SOURCE, modes: ALL_MODES, host: FULL_HOST, ...overrides })
}

describe("media action registry", () => {
  it("keeps the image hover bar at five icons and demotes the rest into 更多", () => {
    const bar = mediaActionBar(items({}))
    expect(bar.map((item) => item.id)).toEqual(["reference", "photo-edit", "inpaint", "cutout", "to-video"])
    expect(bar).toHaveLength(MEDIA_ACTION_BAR_LIMIT)
    expect(mediaActionMenu(items({})).map((item) => item.id)).toContain("erase")
  })

  it("builds tool links from the handoff contract so the target page can read the media back", () => {
    const outpaint = items({}).find((item) => item.id === "outpaint")
    expect(outpaint?.href).toBe(`/tools/image-outpaint?sourceJob=job-1&generation=item-1&output=0&kind=image`)
    expect(items({}).filter((item) => item.href === null).map((item) => item.id)).toContain("reference")
  })

  it("hides a capability the registry marks unavailable instead of sending the user to a dead page", () => {
    const modes = ALL_MODES.map((mode) => (mode.id === IMAGE_OUTPAINT_WORKFLOW ? { ...mode, available: false } : mode))
    const ids = items({ modes }).map((item) => item.id)
    expect(ids).not.toContain("outpaint")
    expect(ids).toContain("inpaint")
  })

  it("drops a listed workflow that disappears from the catalog entirely", () => {
    const modes = ALL_MODES.filter((mode) => mode.id !== IMAGE_LAYER_SPLIT_WORKFLOW)
    expect(items({ modes }).map((item) => item.id)).not.toContain("layer-split")
  })

  it("keeps video tool actions although /api/modes hides those tool workflows", () => {
    // 真实后端把超清双引擎、修脸和口型标成 hidden_from_catalog，目录接口不返回它们；局部重拍仍在目录里。
    const hidden = new Set([UPSCALE_ENGINE_RTX, UPSCALE_ENGINE_SEEDVR2, FACE_RESTORE_WORKFLOW, LIP_SYNC_WORKFLOW])
    const catalog = ALL_MODES.filter((mode) => !hidden.has(mode.id))
    const video = mediaActions({ kind: "video", source: VIDEO_SOURCE, modes: catalog, host: FULL_HOST })
    expect(mediaActionBar(video).map((item) => item.id)).toEqual(["reference", "upscale", "retake", "face-restore", "lip-sync"])
    expect(video.find((item) => item.id === "upscale")?.href).toBe(`/tools/video-upscale?sourceJob=job-1&generation=item-1&output=2&kind=video`)
  })

  it("drops every tool action when the output cannot be located, but keeps in-page actions", () => {
    const ids = items({ source: null }).map((item) => item.id)
    expect(ids).toEqual(["reference", "to-video", "canvas", "re-edit", "regenerate", "params", "remove"])
  })

  it("offers the video bar in 即梦 order and hides owner-only repair when viewing someone else", () => {
    const video = { kind: "video" as const, source: VIDEO_SOURCE, modes: ALL_MODES, host: FULL_HOST }
    expect(mediaActionBar(items(video))).toHaveLength(MEDIA_ACTION_BAR_LIMIT)
    expect(mediaActions(video).map((item) => item.id)).toEqual([
      "reference", "upscale", "retake", "face-restore", "lip-sync",
      "canvas", "jianying", "re-edit", "regenerate", "params", "remove",
    ])
    const inspecting = mediaActions({ ...video, inspectingOtherUser: true }).map((item) => item.id)
    expect(inspecting).not.toContain("face-restore")
    expect(inspecting).toContain("retake")
  })

  it("treats either upscale engine as the same 视频超清 entry", () => {
    const modes = ALL_MODES.map((mode) => (mode.id === UPSCALE_ENGINE_RTX
      ? { ...mode, id: UPSCALE_ENGINE_SEEDVR2, available: true }
      : mode.id === UPSCALE_ENGINE_SEEDVR2 ? { ...mode, available: false } : mode))
    const upscale = mediaActions({ kind: "video", source: VIDEO_SOURCE, modes, host: FULL_HOST }).find((item) => item.id === "upscale")
    expect(upscale?.href).toBe(`/tools/video-upscale?sourceJob=job-1&generation=item-1&output=2&kind=video`)
  })

  it("marks destructive actions so hosts can separate them in the menu", () => {
    expect(items({}).find((item) => item.id === "remove")?.danger).toBe(true)
    expect(items({}).find((item) => item.id === "erase")?.danger).toBeUndefined()
  })
})
