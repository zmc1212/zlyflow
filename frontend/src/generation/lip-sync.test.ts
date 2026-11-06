import { describe, expect, it } from "vitest"
import {
  LIPSYNC_AUDIO_MAX_SECONDS,
  LIPSYNC_SOURCE_MAX_SECONDS,
  LIPSYNC_SOURCE_MIN_SECONDS,
  LIP_SYNC_WORKFLOW,
  lipsyncSourceDurationError,
  lipsyncVideoError,
} from "./lip-sync"

describe("lip-sync helpers", () => {
  it("pins the lip sync workflow id and source bounds", () => {
    expect(LIP_SYNC_WORKFLOW).toBe("minimax-h3-lip-sync")
    expect(LIPSYNC_SOURCE_MIN_SECONDS).toBe(2)
    expect(LIPSYNC_SOURCE_MAX_SECONDS).toBe(15)
    expect(LIPSYNC_AUDIO_MAX_SECONDS).toBe(5)
  })

  it("validates the source video by extension and type", () => {
    expect(lipsyncVideoError({ name: "take.mp4", size: 1024 })).toBe("")
    expect(lipsyncVideoError({ name: "take.MOV", size: 1024 })).toBe("")
    expect(lipsyncVideoError({ name: "take", size: 1024 })).toBe("请上传 MP4 / MOV / WebM 等视频文件")
    expect(lipsyncVideoError({ name: "song.wav", size: 1024 })).toBe("请上传 MP4 / MOV / WebM 等视频文件")
    expect(lipsyncVideoError({ name: "take.mp4", size: 0 })).toBe("原视频不能为空文件")
    expect(lipsyncVideoError({ name: "take.mp4", size: 51 * 1024 * 1024 })).toBe("原视频不能超过 50 MB")
  })

  it("bounds the source video duration", () => {
    expect(lipsyncSourceDurationError(undefined)).toContain("无法读取原视频时长")
    expect(lipsyncSourceDurationError(1.2)).toContain("至少 2 秒")
    expect(lipsyncSourceDurationError(18)).toContain("超出 15 秒上限")
    expect(lipsyncSourceDurationError(6)).toBe("")
  })
})
