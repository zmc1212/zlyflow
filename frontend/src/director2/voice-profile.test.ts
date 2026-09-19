import { describe, expect, it } from "vitest"
import {
  emotionLabel,
  hasRefAudio,
  isVoiceAudioFile,
  voiceOf,
} from "./voice-profile"

describe("voice profile", () => {
  it("hydrates extra.voice with clone defaults", () => {
    expect(voiceOf(undefined)).toEqual({
      preset_id: "",
      ref_audio_url: "",
      preview_url: "",
      default_emotion: "calm",
      emo_alpha: 0.8,
      duration_factor: 1,
      source: null,
    })
    expect(voiceOf({
      voice: {
        ref_audio_url: " https://cdn.example/a.wav ",
        default_emotion: "开心",
        emo_alpha: 1.4,
        duration_factor: 0.2,
      },
    }).ref_audio_url).toBe("https://cdn.example/a.wav")
    expect(voiceOf({ voice: { default_emotion: "happy", emo_alpha: 0.5, duration_factor: 1.2 } })).toMatchObject({
      default_emotion: "happy",
      emo_alpha: 0.5,
      duration_factor: 1.2,
    })
  })

  it("detects bound reference audio and labels emotions", () => {
    expect(hasRefAudio({ voice: { ref_audio_url: "https://cdn.example/a.wav" } })).toBe(true)
    expect(hasRefAudio({ voice: { preset_id: "specialist" } })).toBe(true)
    expect(hasRefAudio({})).toBe(false)
    expect(voiceOf({
      voice: {
        ref_audio_url: "https://cdn.example/a.wav",
        source: { kind: "shot", episode_id: "ep-1", beat_id: "beat-1", start_sec: 4, end_sec: 7 },
      },
    }).source).toEqual({
      kind: "shot",
      episode_id: "ep-1",
      beat_id: "beat-1",
      start_sec: 4,
      end_sec: 7,
    })
    expect(emotionLabel("sad")).toBe("悲伤")
    expect(emotionLabel("unknown")).toBe("平静")
  })

  it("accepts common voice audio filenames", () => {
    expect(isVoiceAudioFile({ name: "ref.wav", type: "" })).toBe(true)
    expect(isVoiceAudioFile({ name: "clip.mp3", type: "audio/mpeg" })).toBe(true)
    expect(isVoiceAudioFile({ name: "face.png", type: "image/png" })).toBe(false)
  })
})
