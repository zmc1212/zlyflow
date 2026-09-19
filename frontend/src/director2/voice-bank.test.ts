import { describe, expect, it } from "vitest"
import { groupedVoicePresetOptions, type VoicePreset } from "./voice-bank"

const sample: VoicePreset[] = [
  { id: "specialist", file: "voice_04.wav", label: "沉稳男主", gender: "male", role: "主角", group: "男声", group_order: 0, default_emotion: "calm", description: "", audio_url: "/api/voice-bank/specialist/audio" },
  { id: "sweet-heroine", file: "voice_09.wav", label: "甜妹女主", gender: "female", role: "主角", group: "女声", group_order: 1, default_emotion: "happy", description: "", audio_url: "/api/voice-bank/sweet-heroine/audio" },
  { id: "narrator", file: "voice_05.wav", label: "解说旁白", gender: "male", role: "旁白", group: "旁白", group_order: 2, default_emotion: "calm", description: "", audio_url: "/api/voice-bank/narrator/audio" },
]

describe("voice bank options", () => {
  it("groups built-in short-drama voices for Ant Design Select", () => {
    const options = groupedVoicePresetOptions(sample)
    expect(options.map((item) => item.label)).toEqual(["男声", "女声", "旁白"])
    expect(options[0].options[0]).toEqual({ value: "specialist", label: "沉稳男主 · 主角" })
  })
})
