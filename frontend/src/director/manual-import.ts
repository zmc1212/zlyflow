import { CameraDirection, createEmptyRecipeShot, RecipeScene, RecipeShot, defaultCameraDirection } from "./types"

export interface ManualImportResult { scenes: RecipeScene[]; warnings: string[] }

function field(block: string, label: string): string {
  const match = block.match(new RegExp(`(?:^|\\n)\\s*[-*]?\\s*${label}\\s*[：:]\\s*([^\\n]+)`, "i"))
  return match?.[1]?.trim() || ""
}

function normalizeDialogue(value: string): string {
  if (!value) return ""
  const parts: string[] = []
  const re = /(?:男主|女主|男|女|旁白|画外音)\s*[：:]\s*([^\n]+?)(?=(?:男主|女主|男|女|旁白|画外音)\s*[：:]|$)/g
  let match: RegExpExecArray | null
  while ((match = re.exec(value))) parts.push(match[1].trim())
  if (parts.length) return parts.join("\n")
  return value.replace(/(?:男主|女主|男|女|旁白|画外音)\s*[：:]\s*/g, "").trim()
}
function parseDialogueLines(value: string): Array<{ speaker: string; text: string }> {
  const lines: Array<{ speaker: string; text: string }> = []
  const re = /(?:男主|女主|男|女|旁白|画外音)\s*[：:]\s*([^\n]+?)(?=(?:男主|女主|男|女|旁白|画外音)\s*[：:]|$)/g
  let m: RegExpExecArray | null
  while ((m = re.exec(value))) { const raw = m[0]; const speaker = raw.split(/[：:]/, 1)[0].trim(); lines.push({ speaker, text: m[1].trim() }) }
  return lines
}

/** Parse the intentionally small Markdown format used by the manual director workflow. */
export function parseManualStoryboard(markdown: string): ManualImportResult {
  const warnings: string[] = []
  const scenes: RecipeScene[] = []
  const sceneBlocks = markdown.split(/^#\s+/m).slice(1)
  let shotNumber = 1
  for (const sceneBlock of sceneBlocks) {
    const lines = sceneBlock.split(/\r?\n/)
    const sceneTitle = lines.shift()?.trim() || `场景 ${scenes.length + 1}`
    const shots = sceneBlock.split(/^##\s+/m).slice(1).map((block) => {
      const header = block.split(/\r?\n/, 1)[0] || ""
      const timecode = header.match(/(\d+):(\d{2})\s*[–—-]\s*(\d+):(\d{2})/)
      const durationMatch = header.match(/(\d+(?:\.\d+)?)\s*[–—-]\s*(\d+(?:\.\d+)?)\s*秒/)
      const seconds = timecode ? Number(timecode[3]) * 60 + Number(timecode[4]) - Number(timecode[1]) * 60 - Number(timecode[2])
        : durationMatch ? Number(durationMatch[2]) - Number(durationMatch[1]) : 5
      const durationSec = Math.min(15, Math.max(2, Math.round(seconds)))
      if (!timecode && !durationMatch) warnings.push(`${header} 未识别到时长，暂用 5 秒`)
      if (seconds < 2 || seconds > 15) warnings.push(`${header} 超出单镜 2–15 秒范围，请重新拆镜`)
      const shot: RecipeShot = createEmptyRecipeShot(shotNumber++, durationSec)
      shot.title = header.replace(/\|.*$/, "").trim() || shot.title
      shot.description = field(block, "画面")
      shot.promptText = field(block, "提示词") || shot.description
      const dialogueRaw = field(block, "对白")
      shot.dialogueLines = parseDialogueLines(dialogueRaw)
      shot.dialogue = normalizeDialogue(dialogueRaw)
      shot.locationName = field(block, "场景")
      shot.soundscape = field(block, "声音")
      const scales: Record<string, CameraDirection["scale"]> = { "近景": "CU", "特写": "ECU", "中景": "MS", "全景": "WS", "远景": "ELS" }
      const scale = field(block, "景别")
      shot.camera = { ...defaultCameraDirection(), scale: scales[scale] || scale as CameraDirection["scale"] || "MS", movement: field(block, "运镜") as CameraDirection["movement"] || "static" }
      if (shot.dialogue.replace(/\s/g, "").length > durationSec * 4) warnings.push(`${shot.title} 对白较密，请增加时长或拆镜以保留表演停顿`)
      if (!shot.description && !shot.dialogue) warnings.push(`${shot.title} 缺少画面或对白`)
      return shot
    })
    if (shots.length) scenes.push({ id: `scene-${scenes.length + 1}`, sceneNumber: scenes.length + 1, title: sceneTitle, description: "", locationName: field(sceneBlock, "场景"), shots })
  }
  if (!scenes.length) warnings.push("未识别到 # 场景和 ## 镜头结构")
  return { scenes, warnings }
}
