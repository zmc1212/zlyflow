export type VoicePreset = {
  id: string
  file: string
  label: string
  gender: string
  role: string
  group: string
  group_order: number
  default_emotion: string
  description: string
  audio_url: string
}

export function groupedVoicePresetOptions(voices: VoicePreset[]) {
  const groups = new Map<string, VoicePreset[]>()
  const order: string[] = []
  const sorted = [...voices].sort((left, right) => (left.group_order ?? 99) - (right.group_order ?? 99))
  for (const voice of sorted) {
    const group = voice.group || "其他"
    if (!groups.has(group)) {
      groups.set(group, [])
      order.push(group)
    }
    groups.get(group)?.push(voice)
  }
  return order.map((label) => ({
    label,
    options: (groups.get(label) || []).map((voice) => ({
      value: voice.id,
      label: `${voice.label} · ${voice.role}`,
    })),
  }))
}
