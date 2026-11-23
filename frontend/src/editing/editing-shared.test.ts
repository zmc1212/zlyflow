import { describe, expect, it } from "vitest"
import {
  acquireEditSession,
  canvasTimelineAssets,
  editorSessionKey,
  isEditSessionActive,
  mergeEditAssetPool,
} from "./editing-shared"
import { createTimelineNode, canvasNodeTypeLabel, canvasNodeSize, CANVAS_NODE_TYPES } from "../canvas/canvas-model"

describe("mergeEditAssetPool", () => {
  it("按 url 去重并保留文档素材在前", () => {
    const doc = [{ id: "a", name: "已导入", kind: "video" as const, url: "https://m/a.mp4", duration: 4 }]
    const pool = [
      { id: "a", name: "重复", kind: "video" as const, url: "https://m/a.mp4", duration: 4 },
      { id: "b", name: "画布图片", kind: "image" as const, url: "https://m/b.png", duration: 5 },
    ]
    const merged = mergeEditAssetPool(doc, pool)
    expect(merged.map((asset) => asset.id)).toEqual(["a", "b"])
  })

  it("无新增时不重建数组", () => {
    const doc = [{ id: "a", name: "已导入", kind: "video" as const, url: "https://m/a.mp4", duration: 4 }]
    expect(mergeEditAssetPool(doc, [{ id: "a", name: "重复", kind: "video" as const, url: "https://m/a.mp4", duration: 4 }])).toBe(doc)
  })
})

describe("canvasTimelineAssets", () => {
  it("从图片 / 视频 / 音频 / 生成节点派生素材，忽略空地址", () => {
    const assets = canvasTimelineAssets([
      { type: "image", data: { url: "/api/media/x.png", label: "分镜图" } },
      { type: "video", data: { url: "https://m/a.mp4", label: "成片", duration: 12 } },
      { type: "audio", data: { resultUrl: "https://m/tts.mp3", durationSeconds: 30 } },
      { type: "generator", data: { resultUrl: "https://m/gen.mp4", resultKind: "video", label: "视频生成" } },
      { type: "image", data: {} },
      { type: "text", data: { text: "文字节点" } },
    ])
    expect(assets).toHaveLength(4)
    expect(assets[0]).toMatchObject({ kind: "image", url: "/api/media/x.png", thumbnail: "/api/media/x.png" })
    expect(assets[1]).toMatchObject({ kind: "video", duration: 12 })
    expect(assets[2]).toMatchObject({ kind: "audio", duration: 30 })
    expect(assets[3]).toMatchObject({ kind: "video", url: "https://m/gen.mp4" })
  })
})

describe("edit session registry", () => {
  it("全屏编辑会话互斥：占用/释放通知订阅者", () => {
    const key = editorSessionKey("canvas:c1", "tl-1")
    expect(isEditSessionActive(key)).toBe(false)
    const seen: boolean[] = []
    const release = acquireEditSession(key)
    expect(isEditSessionActive(key)).toBe(true)
    release()
    expect(isEditSessionActive(key)).toBe(false)
    expect(seen).toEqual([])
  })
})

describe("timeline canvas node", () => {
  it("注册为通用节点类型并可序列化尺寸", () => {
    expect(CANVAS_NODE_TYPES).toContain("timeline")
    expect(canvasNodeTypeLabel("timeline")).toBe("时间线")
    const node = createTimelineNode({ x: 10, y: 20 }, "时间线 2")
    expect(node.type).toBe("timeline")
    expect(node.data.label).toBe("时间线 2")
    expect(canvasNodeSize(node)).toEqual({ width: 880, height: 240 })
  })
})
