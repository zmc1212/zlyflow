import { afterEach, describe, expect, it, vi } from "vitest"
import {
  canvasAudioModeLabel,
  canvasAudioProviderLabel,
  canvasAudioTitle,
  canvasMusicDurationLabel,
  fetchCanvasAudioOptions,
  fetchCanvasMusicJob,
  submitCanvasMusic,
  submitCanvasTts,
} from "./canvas-audio"

const fetchMock = vi.fn()

afterEach(() => {
  fetchMock.mockReset()
  vi.unstubAllGlobals()
})

function stubFetch(response: Response) {
  vi.stubGlobal("fetch", fetchMock)
  fetchMock.mockResolvedValue(response)
}

describe("音频节点文案", () => {
  it("模式与标题跟随当前选择", () => {
    expect(canvasAudioModeLabel("tts")).toBe("音频生成")
    expect(canvasAudioModeLabel("music")).toBe("音乐生成")
    expect(canvasAudioTitle(undefined, "tts")).toBe("音频生成")
    expect(canvasAudioTitle("  片尾旁白 ", "music")).toBe("片尾旁白")
  })

  it("缺失的 Provider 回落为 TTS", () => {
    expect(canvasAudioProviderLabel("mimo")).toBe("MiMo TTS")
    expect(canvasAudioProviderLabel("indextts")).toBe("IndexTTS")
    expect(canvasAudioProviderLabel("")).toBe("TTS")
  })

  it("音乐时长按分钟显示", () => {
    expect(canvasMusicDurationLabel(30)).toBe("30 秒")
    expect(canvasMusicDurationLabel(60)).toBe("1 分钟")
    expect(canvasMusicDurationLabel(120)).toBe("2 分钟")
    expect(canvasMusicDurationLabel(null)).toBe("")
  })
})

describe("音频节点请求", () => {
  it("TTS 合成带 CSRF 与音色", async () => {
    stubFetch(new Response(JSON.stringify({ url: "/api/canvas/audio/files/a.mp3", bytes: 10 }), { status: 200 }))
    await expect(submitCanvasTts("csrf", { text: "你好", voice: "苏打" })).resolves.toMatchObject({ url: "/api/canvas/audio/files/a.mp3" })
    expect(fetchMock).toHaveBeenCalledWith("/api/canvas/audio/tts", expect.objectContaining({
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": "csrf" },
      body: JSON.stringify({ text: "你好", voice: "苏打" }),
    }))
  })

  it("音乐走本地音乐服务的 vibe 接口", async () => {
    stubFetch(new Response(JSON.stringify({ id: "m1", status: "queued", progress: 0, result_url: null, error_message: null, duration_seconds: 60 }), { status: 200 }))
    const job = await submitCanvasMusic("csrf", { description: "温暖的钢琴", durationSeconds: 60, instrumental: true })
    expect(job.id).toBe("m1")
    expect(fetchMock).toHaveBeenCalledWith("/api/music/vibe", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ description: "温暖的钢琴", duration_seconds: 60, instrumental: true }),
    }))
  })

  it("轮询按任务号转义，错误信息优先取 detail", async () => {
    stubFetch(new Response(JSON.stringify({ detail: "音乐服务未配置" }), { status: 503 }))
    await expect(fetchCanvasMusicJob("job/a")).rejects.toThrow("音乐服务未配置")
    expect(fetchMock).toHaveBeenCalledWith("/api/music/jobs/job%2Fa", expect.anything())

    fetchMock.mockResolvedValue(new Response(JSON.stringify({ detail: "TTS 未配置" }), { status: 502 }))
    await expect(submitCanvasTts("csrf", { text: "你好" })).rejects.toThrow("TTS 未配置")
  })

  it("音色目录读取失败给出可读提示", async () => {
    stubFetch(new Response("oops", { status: 500 }))
    await expect(fetchCanvasAudioOptions()).rejects.toThrow("音色目录读取失败")
  })
})
