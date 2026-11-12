import { beforeEach, describe, expect, it, vi } from "vitest"
import {
  applyLiveBeatStatus,
  assetStatusLamp,
  attentionBeats,
  beatStatusLamp,
  buildWorkbenchGraph,
  collectWorkbenchPositions,
  loadWorkbenchLayout,
  overviewEpisodeBadge,
  retryableFailedJobIds,
  saveWorkbenchLayout,
  stageChips,
  stageChipLabel,
  type WorkbenchBeat,
  type WorkbenchPayload,
} from "./workbench-graph"

function makeBeat(sequence: number, overrides: Partial<WorkbenchBeat> = {}): WorkbenchBeat {
  return {
    id: `beat-${sequence}`,
    sequence,
    kind: "action",
    heading: `第${sequence}镜`,
    title: `第${sequence}镜`,
    text: `动作 ${sequence}`,
    speaker: "",
    dialogue: "",
    character_ids: ["char-1"],
    scene_id: "scene-1",
    prop_ids: [],
    has_prompt: false,
    has_video: false,
    video_url: "",
    video_duration: "8",
    awaiting_refine: false,
    task_status: "idle",
    ...overrides,
  }
}

function makePayload(overrides: Partial<WorkbenchPayload> = {}): WorkbenchPayload {
  const beats = [makeBeat(1), makeBeat(2, { has_prompt: true, has_video: true, video_url: "https://cdn/2.mp4" })]
  return {
    project: { id: "p1", name: "测试短剧", cover_url: "" },
    episode: { id: "ep-1", number: 1, title: "第一集", status: "draft", script_text: "正文", summary: "摘要", episode_video_url: "", episode_video_job_id: "" },
    assets: [
      { id: "char-1", kind: "character", name: "李云", image_url: "https://cdn/c.png", ready: true, ready_label: "1 套造型已就绪", looks_total: 1, looks_ready: 1, ref_beats: 2 },
      { id: "scene-1", kind: "scene", name: "山道", image_url: "", ready: false, ready_label: "缺场景设定图", looks_total: 1, looks_ready: 0, ref_beats: 2 },
    ],
    beats,
    edges: [
      { id: "e-ref-char-1-beat-1", source: "asset-char-1", target: "beat-beat-1", kind: "reference" },
      { id: "e-seq-beat-1-beat-2", source: "beat-beat-1", target: "beat-beat-2", kind: "sequence" },
      { id: "e-out-beat-2", source: "beat-beat-2", target: "episode-video", kind: "output" },
    ],
    progress: {
      stages: {
        script: { done: 1, total: 1, ratio: 1, status: "done" },
        assets: { done: 1, total: 2, ratio: 0.5, status: "active" },
        prompts: { done: 2, total: 2, ratio: 1, status: "done" },
        shots: { done: 1, total: 2, ratio: 0.5, status: "active" },
      },
      overall_pct: 75,
      beats_total: 2,
      prompts_done: 2,
      shots_done: 1,
      assets_total: 2,
      assets_ready: 1,
    },
    next_action: { kind: "fix-assets", label: "「山道」还缺出片素材，先补齐", target: "assets" },
    ...overrides,
  }
}

describe("buildWorkbenchGraph", () => {
  it("derives script, asset, beat and episode nodes in three columns", () => {
    const { nodes } = buildWorkbenchGraph(makePayload())
    const types = nodes.map(node => node.type)
    expect(types).toContain("wb-script")
    expect(types.filter(type => type === "wb-asset")).toHaveLength(2)
    expect(types.filter(type => type === "wb-beat")).toHaveLength(2)
    expect(types).toContain("wb-episode")
    const script = nodes.find(node => node.id === "script-node")
    const firstBeat = nodes.find(node => node.id === "beat-beat-1")
    const episode = nodes.find(node => node.id === "episode-video")
    expect(script!.position.x).toBeLessThan(firstBeat!.position.x)
    expect(episode!.position.x).toBeGreaterThan(firstBeat!.position.x)
  })

  it("wraps beats into columns of four rows", () => {
    const beats = Array.from({ length: 5 }, (_, index) => makeBeat(index + 1, { has_prompt: true }))
    const { nodes } = buildWorkbenchGraph(makePayload({ beats }))
    const beatNodes = nodes.filter(node => node.type === "wb-beat")
    const positions = beatNodes.map(node => node.position)
    expect(new Set(positions.map(position => position.x)).size).toBe(2)
    expect(new Set(positions.slice(0, 4).map(position => position.y)).size).toBe(4)
  })

  it("keeps saved positions and rebuilds reference/sequence/output edges", () => {
    const saved = { "beat-beat-1": { x: 999, y: -50 } }
    const { nodes, edges } = buildWorkbenchGraph(makePayload(), saved)
    expect(nodes.find(node => node.id === "beat-beat-1")!.position).toEqual({ x: 999, y: -50 })
    const kinds = edges.map(edge => edge.kind)
    expect(kinds).toContain("reference")
    expect(kinds).toContain("sequence")
    expect(kinds).toContain("output")
    expect(edges.every(edge => edge.type === "smoothstep")).toBe(true)
  })
})

describe("applyLiveBeatStatus", () => {
  it("stamps running/queued and shot urls from workshop polling", () => {
    const beats = [makeBeat(1), makeBeat(2, { has_video: true, video_url: "https://cdn/2.mp4" })]
    const stamped = applyLiveBeatStatus(beats, {
      "beat-1": { status: "running", shotStage: "running" },
      "beat-2": { status: "running", shotStage: "succeeded", shotUrl: "https://cdn/2-hd.mp4" },
    })
    expect(stamped[0].task_status).toBe("running")
    expect(stamped[1].has_video).toBe(true)
    expect(stamped[1].video_url).toBe("https://cdn/2.mp4")
  })

  it("flags awaiting_refine beats", () => {
    const beats = [makeBeat(1)]
    const stamped = applyLiveBeatStatus(beats, { "beat-1": { status: "running", shotStage: "awaiting_refine" } })
    expect(stamped[0].awaiting_refine).toBe(true)
  })

  it("carries live progress percent for running and queued beats", () => {
    const beats = [makeBeat(1), makeBeat(2), makeBeat(3)]
    const stamped = applyLiveBeatStatus(beats, {
      "beat-1": { status: "running", shotStage: "running", progress: 41.6 },
      "beat-2": { status: "queued", shotStage: "queued", progress: 0 },
      "beat-3": { status: "running", shotStage: "running" },
    })
    expect(stamped[0].live_progress).toBeCloseTo(41.6)
    expect(stamped[1].live_progress).toBe(0)
    expect(stamped[2].live_progress).toBeNull()
    expect(beatStatusLamp(stamped[0]).label).toBe("生成中 42%")
    expect(beatStatusLamp(stamped[1]).label).toBe("排队中 0%")
    expect(beatStatusLamp(stamped[2]).label).toBe("生成中")
  })
})

describe("overviewEpisodeBadge", () => {
  const base = { beats_total: 10, shots_done: 9, overall_pct: 95 }
  it("priority: running > awaiting > failed > done > partial", () => {
    expect(overviewEpisodeBadge({ ...base, running: true, awaiting_refine: true, failed: true }).label).toBe("出片中")
    expect(overviewEpisodeBadge({ ...base, running: false, awaiting_refine: true, failed: true }).label).toBe("有待确认镜头")
    expect(overviewEpisodeBadge({ ...base, running: false, awaiting_refine: false, failed: true }).tone).toBe("bad")
    expect(overviewEpisodeBadge({ ...base, running: false, awaiting_refine: false, failed: false }).label).toBe("9/10 镜已出片")
    expect(overviewEpisodeBadge({ ...base, shots_done: 10, overall_pct: 100, running: false, awaiting_refine: false, failed: false }).label).toBe("镜头已全部出片")
    expect(overviewEpisodeBadge({ ...base, beats_total: 0, shots_done: 0, overall_pct: 0, running: false, awaiting_refine: false, failed: false }).label).toBe("还没有分镜")
  })
})

describe("retryableFailedJobIds", () => {
  const jobs = [
    { id: "job-run", job_type: "video_generation", status: "running", payload: { beat_ids: ["beat-1"] } },
    { id: "job-fail-1", job_type: "video_generation", status: "failed", payload: { beat_ids: ["beat-2", "beat-3"] } },
    { id: "job-fail-2", job_type: "video_generation", status: "failed", payload: { beat_id: "beat-4" } },
    { id: "job-fail-other", job_type: "video_generation", status: "failed", payload: { beat_ids: ["beat-9"] } },
    { id: "job-h3", job_type: "h3_prompt", status: "failed", payload: { beat_ids: ["beat-2"] } },
  ]
  it("collects distinct failed video jobs covering the failed beats", () => {
    expect(retryableFailedJobIds(jobs, ["beat-2", "beat-4"])).toEqual(["job-fail-1", "job-fail-2"])
  })
  it("ignores active jobs, other types and unrelated failures", () => {
    expect(retryableFailedJobIds(jobs, ["beat-1"])).toEqual([])
    expect(retryableFailedJobIds(jobs, [])).toEqual([])
  })
})

describe("attentionBeats", () => {
  it("collects awaiting_refine and failed beats in sequence order", () => {
    const beats = [
      makeBeat(3, { task_status: "failed" }),
      makeBeat(1, { task_status: "awaiting_refine" }),
      makeBeat(2, { has_video: true, task_status: "succeeded" }),
      makeBeat(4),
    ]
    const attention = attentionBeats(beats)
    expect(attention.map(item => item.beat.sequence)).toEqual([1, 3])
    expect(attention.map(item => item.reason)).toEqual(["awaiting_refine", "failed"])
  })

  it("returns empty when everything is healthy", () => {
    expect(attentionBeats([makeBeat(1, { has_video: true, task_status: "succeeded" })])).toEqual([])
  })
})

describe("stageChips", () => {
  it("builds display chips with fallback for missing progress", () => {
    expect(stageChips(undefined)).toHaveLength(4)
    const chips = stageChips(makePayload().progress)
    expect(chips[0]).toMatchObject({ key: "script", status: "done", label: "剧本成型" })
    expect(chips[1]).toMatchObject({ key: "assets", done: 1, total: 2 })
    expect(stageChipLabel(chips[1])).toBe("出片素材 1/2")
    expect(stageChipLabel({ ...chips[1], status: "locked" as const })).toContain("未开始")
  })
})

describe("status lamps", () => {
  it("maps beat states to lamps", () => {
    expect(beatStatusLamp({ has_video: true, task_status: "succeeded", awaiting_refine: false, has_prompt: true }).label).toBe("已出片")
    expect(beatStatusLamp({ has_video: false, task_status: "running", awaiting_refine: false, has_prompt: true }).label).toBe("生成中")
    expect(beatStatusLamp({ has_video: false, task_status: "awaiting_refine", awaiting_refine: true, has_prompt: true }).tone).toBe("warn")
    expect(beatStatusLamp({ has_video: false, task_status: "failed", awaiting_refine: false, has_prompt: true }).tone).toBe("bad")
    expect(beatStatusLamp({ has_video: false, task_status: "idle", awaiting_refine: false, has_prompt: false }).label).toBe("缺指令")
  })

  it("maps asset readiness", () => {
    expect(assetStatusLamp({ ready: true, looks_ready: 2, looks_total: 2 }).tone).toBe("ok")
    expect(assetStatusLamp({ ready: false, looks_ready: 1, looks_total: 2 }).label).toBe("1/2 造型")
  })
})

describe("layout persistence", () => {
  const storage = new Map<string, string>()
  beforeEach(() => {
    storage.clear()
    vi.stubGlobal("window", { localStorage: { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => { storage.set(key, value) } } })
  })

  it("collects, saves and reloads node positions", () => {
    const nodes = [
      { id: "script-node", type: "wb-script" as const, position: { x: 10, y: 20 }, data: {} },
      { id: "beat-beat-1", type: "wb-beat" as const, position: { x: -3.5, y: 80 }, data: {} },
    ]
    const positions = collectWorkbenchPositions(nodes)
    saveWorkbenchLayout("p1", "ep-1", positions)
    expect(loadWorkbenchLayout("p1", "ep-1")).toEqual({ "script-node": { x: 10, y: 20 }, "beat-beat-1": { x: -3.5, y: 80 } })
    expect(loadWorkbenchLayout("p1", "ep-other")).toEqual({})
  })
})
