import { afterEach, describe, expect, it, vi } from "vitest"
import {
  appendCanvasRunSnapshot,
  buildCanvasJobForm,
  buildCanvasRunSnapshot,
  canvasImageNodeFile,
  canvasImageReferenceUrl,
  canvasJobOutputsExpired,
  canvasJobResult,
  canvasJobStatusLabel,
  canvasJobStatusTone,
  canvasPendingResultFill,
  canvasRunHistory,
  canvasRunSnapshotForJob,
  canvasModeOptionDefinitions,
  canvasOptionVisible,
  canvasPictureToken,
  canvasPromptEligible,
  canvasReferenceEligible,
  canvasResultHistory,
  canvasResultVersionIndex,
  canvasResultVersionPatch,
  canvasWorkflowList,
  canvasWorkflowChangePatch,
  defaultGeneratorOptionValues,
  generatorOptionValues,
  generatorParameterFields,
  generatorParameterSummary,
  generatorPromptInfo,
  generatorPromptIssue,
  generatorReferenceIssue,
  generatorResultFromNodeData,
  displayedGeneratorResult,
  incomingGeneratorPromptNodes,
  incomingGeneratorReferenceNodes,
  isCanvasJobActive,
  pickCanvasGenerationMode,
  readCanvasRunSnapshot,
  resolveGeneratorPrompt,
  refineCanvasJob,
  selectCanvasResultVersion,
  serializeGeneratorOptionValues,
  validateGeneratorInput,
  type CanvasJob,
  type CanvasWorkflowMode,
} from "./canvas-generation"
import type { CanvasEdge, CanvasNode } from "./canvas-model"

describe("canvas refine preview lifecycle", () => {
  it("shows the selected older version after a newer live result has completed", () => {
    const data = { resultHistory: [
      { url: "/old.mp4", kind: "video" as const }, { url: "/new.mp4", kind: "video" as const },
    ], resultIndex: 0 }
    const live = { jobId: "new", status: "succeeded", updatedAt: 1, result: { url: "/new.mp4", kind: "video" as const } }
    expect(displayedGeneratorResult(data, live)?.url).toBe("/old.mp4")
    expect(displayedGeneratorResult(data, { ...live, status: "awaiting_refine" })?.url).toBe("/new.mp4")
  })
  it("keeps awaiting previews active and gives them a readable label", () => {
    expect(isCanvasJobActive("awaiting_refine")).toBe(true)
    expect(canvasJobStatusLabel("awaiting_refine")).toBe("一采预览待确认")
    expect(canvasJobStatusTone("awaiting_refine")).toBe("active")
  })

  it("submits confirm and skip against the existing task with CSRF protection", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ id: "job/a", status: "queued", media_type: "video" }), { headers: { "Content-Type": "application/json" } })))
    vi.stubGlobal("fetch", fetchMock)
    await refineCanvasJob("csrf", "job/a", "confirm")
    await refineCanvasJob("csrf", "job/a", "skip")
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/jobs/job%2Fa/refine/confirm", expect.objectContaining({ method: "POST", headers: { "X-CSRF-Token": "csrf" } }))
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/jobs/job%2Fa/refine/skip", expect.objectContaining({ method: "POST", headers: { "X-CSRF-Token": "csrf" } }))
    vi.unstubAllGlobals()
  })

  it("uses a later available output when an older output has expired", () => {
    expect(canvasJobResult({ id: "job", media_type: "image", status: "succeeded", outputs: [
      { path: "expired.png", delivery_status: "expired", cloud_url: "https://cdn.example.com/expired.png" },
      { path: "ok.png", delivery_status: "cloud", cloud_url: "https://cdn.example.com/ok.png" },
    ] })?.url).toBe("https://cdn.example.com/ok.png")
  })

  it("switches from the first pass preview to the refined final output", () => {
    const preview = { kind: "video", render_pass: "preview" as const, download_url: "/preview.mp4" }
    const final = { kind: "video", render_pass: "final" as const, download_url: "/final.mp4" }
    expect(canvasJobResult({ id: "job", media_type: "video", status: "awaiting_refine", outputs: [preview] })?.url).toBe("/preview.mp4")
    expect(canvasJobResult({ id: "job", media_type: "video", status: "succeeded", outputs: [preview, final] })?.url).toBe("/final.mp4")
  })
})

function mode(overrides: Partial<CanvasWorkflowMode> = {}): CanvasWorkflowMode {
  return {
    id: "minimax-h3-r2v",
    name: "MiniMax H3 多参考视频",
    media_type: "video",
    reference_mode: "collection",
    min_references: 1,
    max_references: 9,
    available: true,
    catalog_group_order: 20,
    parameters: [{
      name: "options",
      schema: {
        properties: {
          aspect_ratio: {
            label: "画面比例", type: "string", default: "16:9", ui_group: "primary",
            enum: ["16:9", "9:16"], ui_options: [{ value: "16:9", label: "横屏" }, { value: "9:16", label: "竖屏" }],
          },
          duration: { label: "时长", type: "number", default: 5, ui_group: "primary", minimum: 2, maximum: 15 },
          quality: { label: "画质", type: "string", default: "0.4", ui_group: "advanced", enum: ["0.2", "0.4"] },
          custom_width: {
            label: "自定义宽度", type: "integer", default: 1024, ui_group: "advanced",
            ui_visible_when: { quality: "CUSTOM" },
          },
          steps: { label: "采样步数", type: "integer", default: 20, ui_group: "internal" },
        },
      },
    }],
    ...overrides,
  }
}

function node(id: string, type: string, data: CanvasNode["data"] = {}): CanvasNode {
  return { id, type, position: { x: 0, y: 0 }, data }
}

function edge(source: string, target: string): CanvasEdge {
  return { id: `${source}->${target}`, source, target, type: "smoothstep" }
}

function job(overrides: Partial<CanvasJob> = {}): CanvasJob {
  return {
    id: "job-1",
    media_type: "video",
    status: "succeeded",
    rounds: [{
      generation_items: [{
        outputs: [{
          kind: "video",
          path: "out.mp4",
          download_url: "/api/jobs/job-1/outputs/0/download",
          cloud_url: "https://cdn.example.com/out.mp4",
        }],
      }],
    }],
    ...overrides,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("canvas generation modes", () => {
  it("keeps available image/video workflows sorted by catalog order", () => {
    const modes = canvasWorkflowList([
      mode({ id: "b", name: "B", catalog_group_order: 20 }),
      mode({ id: "a", name: "A", catalog_group_order: 10, media_type: "image" }),
      mode({ id: "off", name: "停用", available: false }),
    ])
    expect(modes.map((item) => item.id)).toEqual(["a", "b"])
  })

  it("picks a workflow that matches the available reference count", () => {
    const modes = [
      mode({ id: "t2v", name: "文生", reference_mode: "none", min_references: 0, max_references: 0 }),
      mode({ id: "i2v", name: "首尾帧", reference_mode: "keyframes", min_references: 1, max_references: 2 }),
      mode({ id: "r2v", name: "多参考", reference_mode: "collection", min_references: 1, max_references: 9 }),
    ]
    expect(pickCanvasGenerationMode(modes, 0)?.id).toBe("t2v")
    expect(pickCanvasGenerationMode(modes, 1)?.id).toBe("i2v")
    expect(pickCanvasGenerationMode(modes, 2)?.id).toBe("i2v")
    expect(pickCanvasGenerationMode(modes, 4)?.id).toBe("r2v")
    expect(pickCanvasGenerationMode([], 0)).toBeNull()
    expect(pickCanvasGenerationMode([mode({ id: "off", available: false })], 0)).toBeNull()
  })

  it("falls back to the first available workflow when none accepts the reference count", () => {
    const modes = [
      mode({ id: "r2v", name: "多参考", reference_mode: "collection", min_references: 3, max_references: 9 }),
      mode({ id: "t2v", name: "文生", reference_mode: "none", min_references: 0, max_references: 0 }),
    ]
    expect(pickCanvasGenerationMode(modes, 1)?.id).toBe("r2v")
  })

  it("splits primary and advanced fields and hides internal or invisible ones", () => {
    const definition = mode()
    expect(Object.keys(canvasModeOptionDefinitions(definition))).toContain("steps")
    expect(canvasOptionVisible(definition.parameters![0].schema!.properties!.custom_width, { quality: "0.4" })).toBe(false)
    const fields = generatorParameterFields(definition, { quality: "0.4" })
    expect(fields.primary.map(([name]) => name)).toEqual(["aspect_ratio", "duration"])
    expect(fields.advanced.map(([name]) => name)).toEqual(["quality"])
    const custom = generatorParameterFields(definition, { quality: "CUSTOM" })
    expect(custom.advanced.map(([name]) => name)).toEqual(["quality", "custom_width"])
  })

  it("uses schema defaults and only serializes visible non-internal options", () => {
    const definition = mode()
    expect(defaultGeneratorOptionValues(definition)).toEqual({
      aspect_ratio: "16:9", duration: 5, quality: "0.4", custom_width: 1024,
    })
    expect(generatorOptionValues(definition, { duration: 8, steps: 30, unknown: "x" })).toMatchObject({
      duration: 8, quality: "0.4",
    })
    expect(generatorOptionValues(definition, { duration: 8, steps: 30 })).not.toHaveProperty("steps")
    expect(serializeGeneratorOptionValues(definition, { duration: 8, quality: "CUSTOM", custom_width: 1280 })).toEqual({
      aspect_ratio: "16:9", duration: 8, quality: "CUSTOM", custom_width: 1280,
    })
    expect(serializeGeneratorOptionValues(definition, { duration: "12" })).toMatchObject({ duration: 12 })
  })
})

describe("canvas generation references", () => {
  it("collects connected image nodes in edge order and ignores text nodes", () => {
    const nodes = [
      node("gen", "generator"),
      node("img1", "image", { url: "/api/media/a.png" }),
      node("text", "text", { text: "提示词" }),
      node("img2", "image", { url: "/api/media/b.png" }),
    ]
    const edges = [edge("img2", "gen"), edge("text", "gen"), edge("img1", "gen"), edge("img1", "gen")]
    expect(incomingGeneratorReferenceNodes(nodes, edges, "gen").map((item) => item.id)).toEqual(["img2", "img1"])
  })

  it("accepts generator image results as references but not video results", () => {
    const imageResult = node("gen-img", "generator", { resultUrl: "/api/media/a.png", resultKind: "image" })
    const videoResult = node("gen-vid", "generator", { resultUrl: "/api/media/a.mp4", resultKind: "video" })
    expect(canvasReferenceEligible(imageResult)).toBe(true)
    expect(canvasReferenceEligible(videoResult)).toBe(false)
    expect(canvasReferenceEligible(node("text", "text", { text: "x" }))).toBe(false)
    expect(canvasReferenceEligible(node("gen-pending-image", "generator", { resultKind: "image" }))).toBe(true)
    expect(canvasReferenceEligible(node("gen-pending-video", "generator", { resultKind: "video" }))).toBe(false)
    const targets = incomingGeneratorReferenceNodes(
      [node("target", "generator"), imageResult, videoResult],
      [edge("gen-vid", "target"), edge("gen-img", "target")],
      "target",
    )
    expect(targets.map((item) => item.id)).toEqual(["gen-img"])
  })

  it("prefers the same-origin asset path over a cloud URL", () => {
    expect(canvasImageReferenceUrl({
      assetPath: "user/demo.png",
      url: "https://cdn.example.com/demo.png",
    })).toBe("/api/media/user%2Fdemo.png")
    expect(canvasImageReferenceUrl({ url: "data:image/png;base64,AAA" })).toBe("data:image/png;base64,AAA")
    expect(canvasImageReferenceUrl({ url: "https://cdn.example.com/demo.png" })).toBe("https://cdn.example.com/demo.png")
    expect(canvasImageReferenceUrl({ resultPath: "user/out.png" })).toBe("/api/media/user%2Fout.png")
    expect(canvasImageReferenceUrl({ resultUrl: "https://cdn.example.com/out.png" })).toBe("https://cdn.example.com/out.png")
    expect(canvasImageReferenceUrl({ resultUrl: "javascript:alert(1)" })).toBeNull()
    expect(canvasImageReferenceUrl({ url: "javascript:alert(1)" })).toBeNull()
    expect(canvasImageReferenceUrl({})).toBeNull()
  })

  it("fills a reserved result node when its generator completes", () => {
    const pending = node("img", "image", { mediaKind: "image", label: "等待生成", pendingGeneratorId: "gen" })
    const result = { url: "/api/files/out.png", kind: "image" as const, path: "user/out.png", label: "猫" }
    expect(canvasPendingResultFill(pending, result, "job-1")).toEqual({
      url: "/api/files/out.png",
      label: "猫",
      assetPath: "user/out.png",
      sourceJobId: "job-1",
      mediaKind: "image",
      pendingGeneratorId: undefined,
    })
    expect(canvasPendingResultFill(
      node("vid", "video", { mediaKind: "video", pendingGeneratorId: "gen" }),
      { url: "/api/files/out.mp4", kind: "video" },
      null,
    )).toMatchObject({ url: "/api/files/out.mp4", label: "生成视频", sourceJobId: null })
  })

  it("keeps reserved nodes that are already filled or reserved for another media kind", () => {
    const result = { url: "/api/files/out.png", kind: "image" as const }
    expect(canvasPendingResultFill(
      node("filled", "image", { url: "/existing.png", mediaKind: "image", pendingGeneratorId: "gen" }),
      result,
      null,
    )).toBeNull()
    expect(canvasPendingResultFill(
      node("video", "video", { mediaKind: "video", pendingGeneratorId: "gen" }),
      result,
      null,
    )).toBeNull()
    expect(canvasPendingResultFill(node("manual", "image", { mediaKind: "image" }), result, null)).toBeNull()
    expect(canvasPendingResultFill(
      node("generator", "generator", { mediaKind: "image", pendingGeneratorId: "gen" }),
      result,
      null,
    )).toBeNull()
  })

  it("validates prompt, workflow and reference count", () => {
    const definition = mode()
    expect(validateGeneratorInput(null, "x", [])).toBe("请先选择生成工作流")
    expect(validateGeneratorInput(definition, "  ", [])).toBe("请填写创作提示词")
    expect(validateGeneratorInput(definition, "x", [])).toContain("支持 1-9 张参考图")
    expect(validateGeneratorInput(definition, "x", [node("a", "image", {})])).toContain("没有可用地址")
    expect(validateGeneratorInput(definition, "x", [node("a", "image", { url: "/api/media/a.png" })])).toBeNull()
    expect(validateGeneratorInput(mode({ min_references: 2, max_references: 2 }), "x", [node("a", "image", { url: "/x" })]))
      .toBe("MiniMax H3 多参考视频 需要 2 张参考图，当前 1 张")
  })

  it("collects connected text nodes as prompt sources in edge order", () => {
    const nodes = [
      node("gen", "generator"),
      node("text1", "text", { text: "雨夜街道" }),
      node("img", "image", { url: "/api/media/a.png" }),
      node("text2", "text", { text: "霓虹反光" }),
    ]
    const edges = [edge("text2", "gen"), edge("img", "gen"), edge("text1", "gen"), edge("text1", "gen")]
    expect(incomingGeneratorPromptNodes(nodes, edges, "gen").map((item) => item.id)).toEqual(["text2", "text1"])
    expect(canvasPromptEligible(nodes[1])).toBe(true)
    expect(canvasPromptEligible(nodes[2])).toBe(false)
  })

  it("joins multiple text sources with blank lines and falls back to the manual prompt", () => {
    const manual = resolveGeneratorPrompt([], "  手动提示词  ")
    expect(manual).toEqual({ nodes: [], text: "手动提示词", emptyCount: 0, fromTextNodes: false })

    const source = resolveGeneratorPrompt([
      node("t1", "text", { text: " 雨夜街道 " }),
      node("t2", "text", { text: "   " }),
      node("t3", "text", { text: "霓虹反光" }),
    ], "手动提示词")
    expect(source.text).toBe("雨夜街道\n\n霓虹反光")
    expect(source.emptyCount).toBe(1)
    expect(source.fromTextNodes).toBe(true)
    expect(generatorPromptInfo(source)).toEqual({ connectedTextNodes: 3, emptyTextNodes: 1 })
  })

  it("explains blocking prompt and reference issues without submitting", () => {
    expect(generatorPromptIssue("", { connectedTextNodes: 2, emptyTextNodes: 2 }))
      .toBe("已连接的文字节点内容为空，请补充文字或断开连线")
    expect(generatorPromptIssue("", { connectedTextNodes: 2, emptyTextNodes: 1 }))
      .toBe("连接的文字节点内容为空，请补充文字")
    expect(generatorPromptIssue("已有一段文字", { connectedTextNodes: 2, emptyTextNodes: 1 }))
      .toBe("连接的文字节点内容为空，请补充文字")
    expect(generatorPromptIssue("  ", null)).toBe("请填写创作提示词")
    expect(generatorPromptIssue("雨夜", { connectedTextNodes: 1, emptyTextNodes: 0 })).toBeNull()
    expect(canvasPictureToken(1)).toBe("<Picture 1>")
    expect(canvasPictureToken(9)).toBe("<Picture 9>")
  })

  it("reports reference count issues live as connections change", () => {
    const definition = mode()
    expect(generatorReferenceIssue(definition, [])).toBe("MiniMax H3 多参考视频 支持 1-9 张参考图，当前 0 张")
    expect(generatorReferenceIssue(definition, [node("a", "image", { url: "/api/media/a.png" })])).toBeNull()
    expect(generatorReferenceIssue(null, [])).toBeNull()
    expect(generatorReferenceIssue(mode({ min_references: 2, max_references: 2 }), [node("a", "image", { url: "/x" })]))
      .toBe("MiniMax H3 多参考视频 需要 2 张参考图，当前 1 张")
  })

  it("reads image bytes from a same-origin URL into an ordered File", async () => {
    const png = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0])
    vi.stubGlobal("fetch", vi.fn(async () => new Response(png, { headers: { "content-type": "image/png" } })))
    const file = await canvasImageNodeFile(node("img", "image", { assetPath: "demo.png" }), 2)
    expect(file.name).toBe("reference-2.png")
    expect(file.type).toBe("image/png")
    expect(file.size).toBe(png.length)
    expect(fetch).toHaveBeenCalledWith("/api/media/demo.png", { credentials: "include" })
  })

  it("reports unreadable references without throwing raw fetch errors", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch") }))
    await expect(canvasImageNodeFile(node("img", "image", { url: "https://cdn.example.com/a.png" }), 1))
      .rejects.toThrow("可能受跨域限制")
  })
})

describe("canvas job form and result", () => {
  it("builds multipart fields with references in order", () => {
    const files = [
      new File([new Uint8Array([1])], "first.png", { type: "image/png" }),
      new File([new Uint8Array([2])], "second.png", { type: "image/png" }),
    ]
    const form = buildCanvasJobForm({
      mode: "minimax-h3-r2v",
      prompt: "雨夜街道",
      options: { aspect_ratio: "9:16", duration: 5 },
      references: files,
      title: "画布生成",
    })
    expect(form.get("mode")).toBe("minimax-h3-r2v")
    expect(form.get("prompt")).toBe("雨夜街道")
    expect(form.get("options")).toBe(JSON.stringify({ aspect_ratio: "9:16", duration: 5 }))
    expect(form.get("title")).toBe("画布生成")
    expect(form.getAll("references").map((item) => (item as File).name)).toEqual(["first.png", "second.png"])
  })

  it("extracts the first output and prefers the stable same-origin download URL", () => {
    expect(canvasJobResult(job())).toEqual({
      url: "/api/jobs/job-1/outputs/0/download",
      kind: "video",
      path: "out.mp4",
      label: undefined,
    })
    expect(canvasJobResult(job({ rounds: [], outputs: [{ kind: "image", cloud_url: "https://cdn.example.com/a.png" }] })))
      .toMatchObject({ url: "https://cdn.example.com/a.png", kind: "image" })
    expect(canvasJobResult(job({ rounds: [], outputs: [] }))).toBeNull()
  })

  it("labels job states and identifies active jobs", () => {
    expect(canvasJobStatusLabel("running")).toBe("生成中")
    expect(canvasJobStatusLabel("cancelled")).toBe("已停止")
    expect(canvasJobStatusLabel(null)).toBe("待提交")
    expect(isCanvasJobActive("queued")).toBe(true)
    expect(isCanvasJobActive("succeeded")).toBe(false)
    expect(canvasJobStatusTone("queued")).toBe("active")
    expect(canvasJobStatusTone("partial")).toBe("success")
    expect(canvasJobStatusTone("interrupted")).toBe("warning")
    expect(canvasJobStatusTone("failed")).toBe("error")
    expect(canvasJobStatusTone(null)).toBe("idle")
  })

  it("restores a persisted generator result for the canvas node", () => {
    expect(generatorResultFromNodeData({})).toBeNull()
    expect(generatorResultFromNodeData({
      resultUrl: "/api/media/out.png",
      resultKind: "image",
      resultPath: "user/out.png",
      label: "分镜",
    })).toEqual({
      url: "/api/media/out.png",
      kind: "image",
      path: "user/out.png",
      label: "分镜",
    })
    expect(generatorResultFromNodeData({ resultUrl: "/api/media/out.mp4", resultKind: "video" }))
      .toMatchObject({ kind: "video" })
  })

  it("appends result versions, dedupes identical outputs and caps history", () => {
    let data: CanvasNode["data"] = {}
    data = { ...data, ...canvasResultVersionPatch(data, { url: "/api/media/a.png", kind: "image", path: "a.png" }, "job-a", 1000) }
    expect(canvasResultHistory(data)).toHaveLength(1)
    expect(canvasResultVersionIndex(data)).toBe(0)

    data = { ...data, ...canvasResultVersionPatch(data, { url: "/api/media/b.png", kind: "image", path: "b.png" }, "job-b", 2000) }
    expect(canvasResultHistory(data).map((item) => item.url)).toEqual(["/api/media/a.png", "/api/media/b.png"])
    expect(canvasResultVersionIndex(data)).toBe(1)

    const duplicate = canvasResultVersionPatch(data, { url: "/api/media/b.png", kind: "image", path: "b.png" }, "job-b", 3000)
    expect(duplicate.resultHistory).toHaveLength(2)
    expect(duplicate.resultIndex).toBe(1)

    for (let index = 0; index < 15; index += 1) {
      data = {
        ...data,
        ...canvasResultVersionPatch(data, { url: `/api/media/r${index}.png`, kind: "image" }, `job-${index}`, 4000 + index),
      }
    }
    expect(canvasResultHistory(data)).toHaveLength(12)
    expect(canvasResultHistory(data).at(-1)?.url).toBe("/api/media/r14.png")
    expect(canvasResultVersionIndex(data)).toBe(11)
  })

  it("switches versions and clamps an out-of-range result index", () => {
    const data: CanvasNode["data"] = {
      resultHistory: [
        { url: "/api/media/a.png", kind: "image", path: "a.png" },
        { url: "/api/media/b.png", kind: "image", path: "b.png" },
      ],
      resultIndex: 99,
      resultUrl: "/api/media/b.png",
      resultKind: "image",
    }
    expect(canvasResultVersionIndex(data)).toBe(1)
    expect(generatorResultFromNodeData(data)).toMatchObject({ url: "/api/media/b.png", kind: "image" })
    const patch = selectCanvasResultVersion(data, 0)
    expect(patch).toMatchObject({ resultUrl: "/api/media/a.png", resultIndex: 0 })
    expect(selectCanvasResultVersion(data, 5)).toBeNull()

    expect(canvasResultVersionIndex({ resultIndex: -3, resultHistory: data.resultHistory })).toBe(0)
    expect(canvasResultVersionIndex({})).toBe(-1)
  })

  it("summarizes the primary generation parameters", () => {
    const definition = mode()
    expect(generatorParameterSummary(definition, { aspect_ratio: "9:16", duration: 8, quality: "0.4" }))
      .toEqual(["画面比例 竖屏", "时长 8"])
    expect(generatorParameterSummary(null, {})).toEqual([])
  })
})

describe("canvas run trace", () => {
  it("freezes the submitted workflow, prompt and visible options into a snapshot", () => {
    const definition = mode()
    const snapshot = buildCanvasRunSnapshot({
      jobId: "job-9",
      mode: definition,
      prompt: "雨夜街道",
      optionValues: { aspect_ratio: "9:16", duration: 8, quality: "0.4", steps: 20 },
      referenceCount: 2,
      submittedAt: 1234,
    })
    expect(snapshot).toEqual({
      jobId: "job-9",
      workflowId: definition.id,
      workflowName: definition.name,
      prompt: "雨夜街道",
      optionValues: { aspect_ratio: "9:16", duration: 8, quality: "0.4" },
      parameterSummary: ["画面比例 竖屏", "时长 8"],
      referenceCount: 2,
      mediaKind: "video",
      submittedAt: 1234,
    })
  })

  it("keeps one snapshot per job, looks up history versions and caps the list", () => {
    const definition = mode()
    let data: CanvasNode["data"] = {}
    for (let index = 0; index < 14; index += 1) {
      const snapshot = buildCanvasRunSnapshot({
        jobId: `job-${index}`,
        mode: definition,
        prompt: `第 ${index} 次`,
        optionValues: {},
        referenceCount: index,
        submittedAt: 1000 + index,
      })
      data = { ...data, ...appendCanvasRunSnapshot(data, snapshot) }
    }
    expect(canvasRunHistory(data)).toHaveLength(12)
    expect(canvasRunHistory(data)[0].jobId).toBe("job-2")
    expect(data.lastRun?.jobId).toBe("job-13")
    expect(canvasRunSnapshotForJob(data, "job-5")?.prompt).toBe("第 5 次")
    expect(canvasRunSnapshotForJob(data, "job-missing")).toBeNull()
    expect(canvasRunSnapshotForJob(data, null)).toBeNull()

    const updated = buildCanvasRunSnapshot({
      jobId: "job-13",
      mode: definition,
      prompt: "同任务重试",
      optionValues: {},
      referenceCount: 0,
      submittedAt: 2000,
    })
    data = { ...data, ...appendCanvasRunSnapshot(data, updated) }
    expect(canvasRunHistory(data)).toHaveLength(12)
    expect(canvasRunSnapshotForJob(data, "job-13")?.prompt).toBe("同任务重试")
  })

  it("sanitizes persisted snapshots and falls back to workflowId names", () => {
    expect(readCanvasRunSnapshot(null)).toBeNull()
    expect(readCanvasRunSnapshot({ jobId: "  ", workflowId: "w" })).toBeNull()
    const snapshot = readCanvasRunSnapshot({
      jobId: " job-1 ",
      workflowId: " workflow-1 ",
      workflowName: "  ",
      prompt: 123,
      optionValues: { ratio: "16:9", steps: 20, fast: true, bad: null, huge: "x".repeat(400) },
      parameterSummary: ["时长 5", 42, "", "画质 高清"],
      referenceCount: 200,
      mediaKind: "audio",
      submittedAt: -1,
    })
    expect(snapshot).toMatchObject({
      jobId: "job-1",
      workflowId: "workflow-1",
      workflowName: "workflow-1",
      prompt: "",
      optionValues: { ratio: "16:9", steps: 20, fast: true },
      parameterSummary: ["时长 5", "画质 高清"],
      referenceCount: 99,
      mediaKind: "image",
      submittedAt: 0,
    })
    expect(snapshot?.optionValues.huge).toHaveLength(200)
  })

  it("marks succeeded jobs whose outputs are gone as expired", () => {
    expect(canvasJobOutputsExpired(job())).toBe(false)
    expect(canvasJobOutputsExpired(job({ rounds: [], outputs: [] }))).toBe(true)
    expect(canvasJobOutputsExpired(job({ status: "running", rounds: [], outputs: [] }))).toBe(false)
    expect(canvasJobOutputsExpired(job({
      rounds: [],
      outputs: [{ kind: "video", path: "out.mp4", delivery_status: "expired", download_url: null }],
    }))).toBe(true)
    expect(canvasJobOutputsExpired(job({
      rounds: [],
      outputs: [{ kind: "video", path: "out.mp4", delivery_status: "local" }],
    }))).toBe(false)
  })
})


it("keeps card and inspector workflow changes consistent without erasing the prompt or frozen run history", () => {
  const next = mode({ id: "next-mode", media_type: "image" })
  const patch = canvasWorkflowChangePatch(next.id, next)
  expect(patch).toMatchObject({ workflowId: next.id, jobId: null, jobStatus: null, jobError: null, resultUrl: null, resultKind: "image", resultPath: null, resultHistory: [], resultIndex: -1 })
  expect(patch.optionValues).toEqual(defaultGeneratorOptionValues(next))
  expect(patch).not.toHaveProperty("prompt")
  expect(patch).not.toHaveProperty("runHistory")
  expect(patch).not.toHaveProperty("lastRun")
})
