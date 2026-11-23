import { describe, expect, it } from "vitest"
import {
  canvasGeneratorTitle,
  canvasProgressActiveCount,
  canvasProgressClock,
  canvasProgressEmptyText,
  canvasProgressEntries,
  canvasProgressKind,
  canvasProgressStatusText,
  canvasProgressSummary,
  canvasProgressTabs,
  filterCanvasProgress,
} from "./canvas-progress"
import type { CanvasGeneratorLive } from "./canvas-generation"
import { createAudioNode, createGeneratorNode, type CanvasNode } from "./canvas-model"

function node(id: string, data: Partial<CanvasNode["data"]> = {}): CanvasNode {
  const base = createGeneratorNode({ x: 0, y: 0 })
  return { ...base, id, data: { ...base.data, ...data } }
}

function live(jobId: string, patch: Partial<CanvasGeneratorLive> = {}): CanvasGeneratorLive {
  return { jobId, status: "running", updatedAt: 1_000, ...patch }
}

const nameOf = (workflowId: string | undefined) => (workflowId === "h3-image" ? "H3 图像 文生图" : "")

describe("生成进度条目", () => {
  it("合并节点与实时状态，进行中优先、同状态按时间倒序", () => {
    const entries = canvasProgressEntries(
      [
        node("n1", { jobId: "job-a", jobStatus: "succeeded", label: "镜头 1", resultKind: "image", resultUrl: "/a.png", workflowId: "h3-image" }),
        node("n2", { jobId: "job-b", jobStatus: "running", label: "镜头 2", resultKind: "video", workflowId: "h3-video" }),
        node("n3", { jobId: "job-c", jobStatus: "succeeded", label: "镜头 3", resultKind: "image" }),
      ],
      {
        "job-a": live("job-a", { status: "succeeded", updatedAt: 3_000 }),
        "job-b": live("job-b", { status: "running", progress: 43.6, stage: "正在生成", updatedAt: 2_000 }),
      },
      nameOf,
    )
    expect(entries.map((entry) => entry.jobId)).toEqual(["job-b", "job-a", "job-c"])
    expect(entries[0]).toMatchObject({
      nodeId: "n2", kind: "video", title: "镜头 2", status: "running", progress: 43.6, active: true, stage: "正在生成",
    })
    expect(entries[1]).toMatchObject({ workflowName: "H3 图像 文生图", previewUrl: "/a.png", active: false })
  })

  it("音频节点与音频生成节点都进入面板并归到音频类型", () => {
    const music: CanvasNode = {
      ...createAudioNode({ x: 0, y: 0 }),
      id: "audio-1",
      data: { audioMode: "music", text: "钢琴", jobId: "music-1", jobStatus: "running", jobProgress: 42 },
    }
    const tts: CanvasNode = {
      ...createAudioNode({ x: 0, y: 0 }),
      id: "audio-2",
      data: { audioMode: "tts", text: "你好", jobStatus: "succeeded", resultUrl: "/api/canvas/audio/files/a.mp3" },
    }
    const entries = canvasProgressEntries([music, tts], {}, nameOf)
    expect(entries).toHaveLength(2)
    expect(entries[0]).toMatchObject({ nodeId: "audio-1", kind: "audio", title: "音乐生成", status: "running", progress: 42, active: true })
    expect(entries[1]).toMatchObject({ nodeId: "audio-2", jobId: "audio-2:tts", previewUrl: "/api/canvas/audio/files/a.mp3", active: false })
    expect(canvasProgressTabs(entries).find((tab) => tab.key === "audio")?.count).toBe(2)
  })

  it("没有 jobId 的生成节点与其它类型节点不进入面板", () => {
    const entries = canvasProgressEntries(
      [
        node("draft", { jobStatus: "running" }),
        { ...node("text"), id: "t1", type: "text" } as CanvasNode,
        node("live", { jobId: "job-x", jobStatus: "running" }),
      ],
      {},
      nameOf,
    )
    expect(entries.map((entry) => entry.nodeId)).toEqual(["live"])
  })

  it("进度夹在 0-100，缺失时按 null 交给面板做不确定态", () => {
    const entries = canvasProgressEntries(
      [node("n1", { jobId: "a" }), node("n2", { jobId: "b" })],
      { a: live("a", { progress: 180 }), b: live("b") },
      nameOf,
    )
    expect(entries.find((entry) => entry.jobId === "a")?.progress).toBe(100)
    expect(entries.find((entry) => entry.jobId === "b")?.progress).toBeNull()
  })

  it("按 limit 截断，避免超长画布把面板撑爆", () => {
    const nodes = Array.from({ length: 6 }, (_, index) => node(`n${index}`, { jobId: `job-${index}`, jobStatus: "succeeded" }))
    expect(canvasProgressEntries(nodes, {}, nameOf, 3)).toHaveLength(3)
  })
})

describe("进度面板展示", () => {
  const entries = canvasProgressEntries(
    [
      node("n1", { jobId: "a", resultKind: "image", jobStatus: "running" }),
      node("n2", { jobId: "b", resultKind: "image", jobStatus: "partial" }),
      node("n3", { jobId: "c", resultKind: "video", jobStatus: "failed" }),
    ],
    { a: live("a", { progress: 43 }) },
    nameOf,
  )

  it("页签固定列出图片/视频/音频，文本有任务时才补上", () => {
    expect(canvasProgressTabs(entries)).toEqual([
      { key: "all", label: "全部", count: 3 },
      { key: "image", label: "图片", count: 2 },
      { key: "video", label: "视频", count: 1 },
      { key: "audio", label: "音频", count: 0 },
    ])
    const withText = [...entries, { ...entries[0], jobId: "text-1", kind: "text" as const }]
    expect(canvasProgressTabs(withText).map((tab) => tab.key)).toEqual(["all", "image", "video", "audio", "text"])
    expect(filterCanvasProgress(entries, "video").map((entry) => entry.jobId)).toEqual(["c"])
    expect(canvasProgressActiveCount(entries)).toBe(1)
  })

  it("音频任务归到音频页签，未知类型不影响其他任务的展示", () => {
    expect(canvasProgressKind("audio")).toBe("audio")
    expect(canvasProgressKind("text")).toBe("text")
    expect(canvasProgressKind(undefined)).toBe("image")
    expect(canvasProgressKind("gif")).toBe("image")
    const withAudio = [...entries, { ...entries[0], jobId: "audio-1", kind: "audio" as const }]
    expect(filterCanvasProgress(withAudio, "audio").map((entry) => entry.jobId)).toEqual(["audio-1"])
    expect(canvasProgressTabs(withAudio).find((tab) => tab.key === "audio")?.count).toBe(1)
  })

  it("空页签给出对应类型的提示文案", () => {
    expect(canvasProgressEmptyText("all")).toBe("暂无生成任务")
    expect(canvasProgressEmptyText("audio")).toBe("暂无音频任务")
    expect(canvasProgressEmptyText("text")).toBe("暂无文本任务")
  })

  it("头部摘要优先显示进行中的数量与百分比", () => {
    expect(canvasProgressSummary(entries)).toBe("1 个进行中 · 43%")
    const finished = entries.filter((entry) => !entry.active)
    expect(canvasProgressSummary(finished)).toBe("部分完成")
  })

  it("部分完成补数量，进行中优先展示后端阶段", () => {
    const partial = entries.find((entry) => entry.jobId === "b")
    expect(partial && canvasProgressStatusText({ ...partial, completedCount: 2, requestedCount: 4 })).toBe("部分完成 2/4")
    const running = entries.find((entry) => entry.jobId === "a")
    expect(running && canvasProgressStatusText({ ...running, stage: "正在提交" })).toBe("正在提交")
    expect(running && canvasProgressStatusText({ ...running, stage: undefined })).toBe("生成中")
  })

  it("时间戳只到分钟", () => {
    const at = new Date(2026, 10, 19, 15, 52, 30).getTime()
    expect(canvasProgressClock(at)).toBe("15:52")
    expect(canvasProgressClock(0)).toBe("")
  })

  it("节点标题与画布上的叫法一致", () => {
    expect(canvasGeneratorTitle(undefined, "image")).toBe("图片生成")
    expect(canvasGeneratorTitle("生成", "video")).toBe("视频生成")
    expect(canvasGeneratorTitle(undefined, "audio")).toBe("音频生成")
    expect(canvasGeneratorTitle("镜头 7", "video")).toBe("镜头 7")
  })
})
