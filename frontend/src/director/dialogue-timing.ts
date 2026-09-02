const HAN_RE = /[\u4e00-\u9fff]/g

export function countHanCharacters(text: string): number {
  return (text.match(HAN_RE) || []).length
}

function countLatinWords(text: string): number {
  return (text.match(/[A-Za-z]+(?:'[A-Za-z]+)?/g) || []).length
}

export function estimateDialogueDurationSec(dialogue: string, emotional = false): number {
  const text = (dialogue || "").trim()
  if (!text) return 0
  const han = countHanCharacters(text)
  const words = countLatinWords(text)
  if (han && !words) return han / (emotional ? 3 : 4)
  if (words && !han) return words / 2.5
  if (han && words) return Math.max(han / (emotional ? 3 : 4), words / 2.5)
  return Math.max(1, text.length / 6)
}

export function estimateShotDurationSec(dialogue: string, actionBeats = 1, emotional = false): number {
  const speech = estimateDialogueDurationSec(dialogue, emotional)
  const beats = Math.max(1, actionBeats)
  let action = 2 + Math.max(0, beats - 1) * 2.5
  if (speech) action += 1
  return Math.max(2, Math.min(15, Math.ceil(Math.max(speech, action))))
}

export function dialogueTimingWarning(dialogue: string, durationSec: number, actionBeats = 1): string | null {
  const duration = Math.max(2, Math.min(15, Math.round(durationSec)))
  const text = (dialogue || "").trim()
  if (!text) return null
  const recommended = estimateShotDurationSec(text, actionBeats)
  if (recommended <= duration) return null
  const han = countHanCharacters(text)
  if (han) return `对白约 ${han} 字，建议时长 ≥ ${recommended}s（当前 ${duration}s）`
  return `对白偏长，建议时长 ≥ ${recommended}s（当前 ${duration}s）`
}
