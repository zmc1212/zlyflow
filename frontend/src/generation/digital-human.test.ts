import { describe, expect, it } from "vitest"
import {
  AUDIO_MAX_SECONDS,
  DIGITAL_HUMAN_WORKFLOW,
  digitalHumanAudioError,
  digitalHumanImageError,
} from "./digital-human"

describe("digital-human helpers", () => {
  it("pins the avatar workflow id", () => {
    expect(DIGITAL_HUMAN_WORKFLOW).toBe("minimax-h3-avatar")
    expect(AUDIO_MAX_SECONDS).toBe(5)
  })

  it("validates the portrait image", () => {
    expect(digitalHumanImageError({ type: "image/png", size: 1024 })).toBe("")
    expect(digitalHumanImageError({ type: "audio/wav", size: 1024 })).toBe("人物形象图必须是图片文件")
    expect(digitalHumanImageError({ type: "image/png", size: 0 })).toBe("人物形象图不能为空文件")
    expect(digitalHumanImageError({ type: "image/png", size: 51 * 1024 * 1024 })).toBe("人物形象图不能超过 50 MB")
  })

  it("validates the speech audio by extension and type", () => {
    expect(digitalHumanAudioError({ name: "speech.wav", size: 1024 })).toBe("")
    expect(digitalHumanAudioError({ name: "speech.MP3", size: 1024 })).toBe("")
    expect(digitalHumanAudioError({ name: "speech", size: 1024 })).toBe("请上传 WAV / MP3 等音频")
    expect(digitalHumanAudioError({ name: "note.txt", size: 1024 })).toBe("请上传 WAV / MP3 等音频")
    expect(digitalHumanAudioError({ name: "note.txt", size: 1024 }, "目标音频")).toBe("请上传 WAV / MP3 等音频")
    expect(digitalHumanAudioError({ name: "speech.wav", size: 0 })).toBe("口播音频不能为空文件")
    expect(digitalHumanAudioError({ name: "speech.wav", size: 51 * 1024 * 1024 })).toBe("口播音频不能超过 50 MB")
  })
})
