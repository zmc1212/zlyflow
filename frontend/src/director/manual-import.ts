import { CameraDirection, createEmptyRecipeShot, RecipeScene, RecipeShot, defaultCameraDirection } from "./types"

export interface ManualImportResult { scenes: RecipeScene[]; warnings: string[]; title?: string; fullStory?: string }

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
  let title = ""
  
  const firstLine = markdown.trim().split(/\r?\n/)[0] || ""
  if (firstLine.startsWith("# ")) {
    const t = firstLine.substring(2).trim()
    const match = t.match(/^《(.*?)》/)
    title = match ? match[1] : t
  }

  const blocks = markdown.split(/(?=^#\s+)/m)
  const scriptContentBlocks: string[] = []
  let shotNumber = 1

  for (const block of blocks) {
    if (!block.trim()) continue
    
    const shotSplit = block.split(/^(?:##|###)\s+(?=镜头|shot|scene|\d+[:：]|\d+(?:\.\d+)?\s*[–—-]|第.*?镜|画面[：:])/im)
    
    if (shotSplit.length > 1) {
      const sceneHeader = shotSplit[0].trim()
      const sceneTitleMatch = sceneHeader.match(/^#\s+(.*)/)
      const sceneTitle = sceneTitleMatch ? sceneTitleMatch[1].split(/\r?\n/)[0].trim() : `场景 ${scenes.length + 1}`
      
      const shots = shotSplit.slice(1).map((shotBlock) => {
        const header = shotBlock.split(/\r?\n/, 1)[0] || ""
        const timecode = header.match(/(\d+):(\d{2})\s*[–—-]\s*(\d+):(\d{2})/)
        const durationMatch = header.match(/(\d+(?:\.\d+)?)\s*[–—-]\s*(\d+(?:\.\d+)?)\s*秒/)
        const seconds = timecode ? Number(timecode[3]) * 60 + Number(timecode[4]) - Number(timecode[1]) * 60 - Number(timecode[2])
          : durationMatch ? Number(durationMatch[2]) - Number(durationMatch[1]) : 5
        const durationSec = Math.min(15, Math.max(2, Math.round(seconds)))
        
        if (!timecode && !durationMatch && !header.includes("秒")) warnings.push(`${header} 未识别到时长，暂用 5 秒`)
        if (seconds < 2 || seconds > 15) warnings.push(`${header} 超出单镜 2–15 秒范围，请重新拆镜`)
        
        const shot: RecipeShot = createEmptyRecipeShot(shotNumber++, durationSec)
        shot.title = header.replace(/\|.*$/, "").trim() || shot.title
        
        let description = field(shotBlock, "画面")
        const charRaw = field(shotBlock, "人物")
        if (charRaw) {
          shot.characterNames = charRaw.split(/[、，, ]+/).map((n) => n.trim()).filter(Boolean)
        }
        
        if (!description) {
          const action = field(shotBlock, "动作")
          const env = field(shotBlock, "场景")
          if (action || charRaw || env) description = [env, charRaw, action].filter(Boolean).join("，")
        }
        shot.description = description
        shot.promptText = field(shotBlock, "提示词") || description
        
        const dialogueRaw = field(shotBlock, "对白") || field(shotBlock, "台词")
        shot.dialogueLines = parseDialogueLines(dialogueRaw)
        shot.dialogue = normalizeDialogue(dialogueRaw) || dialogueRaw
        
        shot.locationName = field(shotBlock, "场景")
        shot.soundscape = field(shotBlock, "声音")
        
        const shotType = field(shotBlock, "景别") || field(shotBlock, "镜头") || ""
        let scale: CameraDirection["scale"] = "MS"
        if (shotType.includes("远景") || shotType.includes("大远景")) scale = "ELS"
        else if (shotType.includes("全景")) scale = "WS"
        else if (shotType.includes("近景")) scale = "CU"
        else if (shotType.includes("特写")) scale = "ECU"
        else if (shotType.includes("中景") || shotType.includes("中近景")) scale = "MS"

        let movement: CameraDirection["movement"] = "static"
        if (shotType.includes("推进") || shotType.includes("前推") || shotType.includes("推")) movement = "zoom_in"
        else if (shotType.includes("拉远") || shotType.includes("后拉") || shotType.includes("拉")) movement = "zoom_out"
        else if (shotType.includes("平移") || shotType.includes("左移") || shotType.includes("右移") || shotType.includes("移")) movement = "pan_right"
        else if (shotType.includes("环绕")) movement = "orbit"
        else if (shotType.includes("跟随") || shotType.includes("跟拍")) movement = "tracking"
        else if (field(shotBlock, "运镜")) movement = field(shotBlock, "运镜") as CameraDirection["movement"] || "static"
        
        shot.camera = { ...defaultCameraDirection(), scale, movement }
        if (shot.dialogue.replace(/\s/g, "").length > durationSec * 4) warnings.push(`${shot.title} 对白较密，请增加时长或拆镜以保留表演停顿`)
        if (!shot.description && !shot.dialogue) warnings.push(`${shot.title} 缺少画面或对白`)
        return shot
      })
      if (shots.length) scenes.push({ id: `scene-${scenes.length + 1}`, sceneNumber: scenes.length + 1, title: sceneTitle, description: "", locationName: field(sceneHeader, "场景"), shots })
    } else {
      scriptContentBlocks.push(block.trim())
    }
  }

  if (!scenes.length) warnings.push("未识别到 # 场景和 ## 镜头结构")
  return { scenes, warnings, title, fullStory: scriptContentBlocks.join("\n\n").trim() }
}
