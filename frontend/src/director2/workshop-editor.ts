import type { Director2Asset, Director2Beat } from "./api"
import { beatDurationSec } from "./workshop-beat-duration"
import { beatPlaybackUrl } from "./director2-video-settings"

export type WorkshopAsset = { key: string; id: string; lookId: string | null; kind: string; name: string; variant: string; title: string; image: string }
export type PromptNode = { type: string; text?: string; attrs?: Record<string, any>; content?: PromptNode[] }
export type PromptDocument = PromptNode & { type: "doc"; content: PromptNode[] }
export type WorkshopPromptPatch = Pick<Director2Beat, "video_prompt_zh" | "workshop_prompt_document" | "action" | "dialogue" | "dialogue_turns" | "camera" | "character_ids" | "characters" | "character_look_ids" | "character_look_id" | "scene_id" | "scene" | "prop_ids" | "props">
export const assetKindLabel = (kind: string) => ({ character: "角色", scene: "场景", prop: "道具" })[kind] || "资产"

export function workshopAssets(assets: Director2Asset[]): WorkshopAsset[] {
  return assets.flatMap(asset => {
    const base = { id: asset.id, kind: asset.kind, name: asset.name }
    if (asset.kind === "character") {
      const looks = Array.isArray(asset.extra?.identities) ? asset.extra.identities : []
      const entries: WorkshopAsset[] = looks.filter((look: any) => look?.id).map((look: any) => {
        const raw = String(look.name || look.description || "未命名造型").trim()
        const variant = raw.startsWith(asset.name) ? raw.slice(asset.name.length).replace(/^[\s·（(]+|[）)]+$/g, "").trim() : raw
        return { ...base, key: asset.id + ":" + look.id, lookId: String(look.id), variant, title: variant ? asset.name + "·" + variant : asset.name, image: String(look.image_url || "") }
      })
      if (entries.length === 1) return entries
      return [{ ...base, key: asset.id + ":", lookId: null, variant: "", title: asset.name, image: String(asset.extra?.avatar_url || asset.image_url || "") }, ...entries]
    }
    const variant = asset.kind === "scene" ? "主视角" : ""
    return [{ ...base, key: asset.id + ":", lookId: null, variant, title: asset.name + (variant ? "·" + variant : ""), image: String(asset.kind === "scene" ? asset.extra?.master_url || asset.image_url || "" : asset.image_url || asset.extra?.reference_url || asset.extra?.master_url || "") }]
  })
}

export function beatAssetEntry(beat: Director2Beat, entries: WorkshopAsset[], id: string): WorkshopAsset | undefined {
  const candidates = entries.filter(a => a.id === id)
  const lookId = beat.character_look_ids?.[id] || beat.character_look_id
  return candidates.find(a => a.lookId === lookId) || candidates.find(a => !a.lookId) || (candidates.length === 1 ? candidates[0] : undefined)
}

export function referenceNode(asset: WorkshopAsset): PromptNode & { attrs: { id: string; label: string; lookId: string | null; kind: string } } {
  return { type: "assetReference", attrs: { id: asset.id, lookId: asset.lookId, label: asset.name, kind: asset.kind } }
}

export function promptText(doc: PromptNode): string {
  if (doc.type === "text") return doc.text || ""
  if (doc.type === "hardBreak") return "\n"
  if (doc.type === "assetReference") return String(doc.attrs?.label || "")
  return (doc.content || []).map(promptText).join(doc.type === "doc" ? "\n\n" : "")
}

export function promptReferences(doc: PromptNode, entries: WorkshopAsset[]): WorkshopAsset[] {
  const found = new Map<string, WorkshopAsset>()
  const visit = (node: PromptNode) => {
    if (node.type === "assetReference") {
      const asset = entries.find(a => a.id === node.attrs?.id && (a.lookId || null) === (node.attrs?.lookId || null))
      if (asset) found.set(asset.key, asset)
    }
    node.content?.forEach(visit)
  }
  visit(doc)
  return Array.from(found.values())
}

export function initialPromptText(beat: Director2Beat): string {
  // Legacy generated H3 drafts contain model contracts and Picture-slot instructions.
  // Start the editable page from the real shot action/dialogue; keep those drafts in 制作详情.
  const authored = !String(beat.action || "").trim() || beat.workshop_prompt_document
    ? String(beat.video_prompt_zh || beat.timestamped_zh_prompt || "").trim() : ""
  const action = String(beat.action || "").split(/\n\n+/).filter(paragraph => !/^(本片段场景设定在|出场人物|出场道具)[：:][^。\n]*。?$/.test(paragraph)).join("\n\n")
  const body = authored || [
    beat.scene ? "本片段场景设定在：" + beat.scene + "。" : "",
    beat.characters?.length ? "出场人物：" + beat.characters.join("、") + "。" : "",
    beat.props?.length ? "出场道具：" + beat.props.join("、") + "。" : "",
    action.replace(/\[(中景|特写|近景|全景|远景|跟拍)\]/g, "\n\n$1，").trim(),
  ].filter(Boolean).join("\n\n")
  return [body, beat.dialogue && !/(?:^|\n\n)对白[：:]/.test(body) ? "对白：\n" + beat.dialogue : "", beat.camera && !/(?:^|\n\n)镜头[：:]/.test(body) ? "镜头：" + beat.camera : ""].filter(Boolean).join("\n\n")
}

export function isPromptDocument(value: unknown): value is PromptDocument {
  if (!value || typeof value !== "object") return false
  const root = value as PromptNode
  let count = 0
  const valid = (n: PromptNode, depth: number): boolean => {
    if (!n || typeof n !== "object" || ++count > 12000 || depth > 4) return false
    if (n.type === "text") return typeof n.text === "string" && !n.content
    if (n.type === "hardBreak") return !n.content
    if (n.type === "assetReference") return typeof n.attrs?.id === "string" && typeof n.attrs?.label === "string" && !n.content
    return (n.type === "doc" || n.type === "paragraph") && (n.content === undefined || Array.isArray(n.content) && n.content.every(c => valid(c, depth + 1)))
  }
  return root.type === "doc" && valid(root, 0)
}

export function promptDocument(beat: Director2Beat, entries: WorkshopAsset[]): PromptDocument {
  const saved = beat.workshop_prompt_document
  if (isPromptDocument(saved) && promptText(saved) === String(beat.video_prompt_zh || "")) return saved
  const namesFor = (ids: string[] | undefined, fallback: string[] | undefined) => ids?.length
    ? ids.map(id => entries.find(a => a.id === id)?.name).filter((name): name is string => !!name) : fallback
  const text = initialPromptText({ ...beat,
    characters: namesFor(beat.character_ids, beat.characters), props: namesFor(beat.prop_ids, beat.props),
    scene: beat.scene_id ? entries.find(a => a.id === beat.scene_id)?.name || beat.scene : beat.scene,
  })
  const names = Array.from(new Set(entries.map(a => a.name))).filter(Boolean).sort((a, b) => b.length - a.length)
  const pattern = names.length ? new RegExp(names.map(name => name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"), "g") : null
  return { type: "doc", content: text.split(/\n\n+/).map(paragraph => {
    const content: PromptNode[] = []
    const append = (str: string) => str.split("\n").forEach((line, index) => { if (index) content.push({ type: "hardBreak" }); if (line) content.push({ type: "text", text: line }) })
    let last = 0
    if (pattern) for (const match of paragraph.matchAll(pattern)) {
      append(paragraph.slice(last, match.index))
      const candidates = entries.filter(a => a.name === match[0])
      const linked = candidates.find(a => beat.character_ids?.includes(a.id) || beat.scene_id === a.id || beat.prop_ids?.includes(a.id)
        || a.kind === "character" && !beat.character_ids?.length && beat.characters?.includes(a.name)
        || a.kind === "scene" && !beat.scene_id && beat.scene === a.name
        || a.kind === "prop" && !beat.prop_ids?.length && beat.props?.includes(a.name))
      const asset = linked && beatAssetEntry(beat, entries, linked.id)
      if (asset) content.push(referenceNode(asset)); else append(match[0])
      last = match.index! + match[0].length
    }
    append(paragraph.slice(last))
    return { type: "paragraph", content }
  }) }
}

export function promptPatch(doc: PromptDocument, entries: WorkshopAsset[]): WorkshopPromptPatch {
  const refs = promptReferences(doc, entries)
  const characters = refs.filter(a => a.kind === "character")
  const scenes = refs.filter(a => a.kind === "scene")
  const props = refs.filter(a => a.kind === "prop")
  for (const asset of characters) {
    if (characters.some(other => other.id === asset.id && other.lookId !== asset.lookId)) throw new Error("同一片段中的“" + asset.name + "”请使用同一造型。")
  }
  if (new Set(scenes.map(a => a.id)).size > 1) throw new Error("一个片段只能绑定一个场景，请拆成多个片段或把其他场景转为普通文字。")
  const uniqueCharacters = [...new Map(characters.map(a => [a.id, a])).values()]
  const text = promptText(doc)
  const sections = text.split(/\n\n+/)
  const field = (label: string) => sections.filter(s => new RegExp("^" + label + "[：:]").test(s)).map(s => s.replace(new RegExp("^" + label + "[：:]\\s*"), "")).join("\n")
  return {
    video_prompt_zh: text, workshop_prompt_document: doc,
    action: sections.filter(s => !/^(对白|镜头)[：:]/.test(s)).join("\n\n"), dialogue: field("对白"), camera: field("镜头"), dialogue_turns: [],
    character_ids: uniqueCharacters.map(a => a.id), characters: uniqueCharacters.map(a => a.name),
    character_look_ids: Object.fromEntries(characters.filter(a => a.lookId).map(a => [a.id, a.lookId!])), character_look_id: uniqueCharacters[0]?.lookId || null,
    scene_id: scenes[0]?.id || null, scene: scenes[0]?.name || "",
    prop_ids: props.map(a => a.id), props: props.map(a => a.name),
  }
}

export type WorkshopSegment = { id: string; index: number; start: number; end: number; duration: number; src: string }
export function workshopSegments(beats: Director2Beat[], measured: Record<string, number> = {}): WorkshopSegment[] {
  let start = 0
  return beats.map((beat, index) => {
    const src = beatPlaybackUrl(beat)
    const known = measured[src]
    const duration = Number.isFinite(known) && known > 0 ? known : beatDurationSec(beat.video_duration) || 1
    const segment = { id: beat.id, index, start, end: start + duration, duration, src }
    start = segment.end
    return segment
  })
}

export function segmentAt(segments: WorkshopSegment[], time: number): { segment: WorkshopSegment; offset: number } | null {
  if (!segments.length) return null
  const total = segments[segments.length - 1].end
  const safe = Math.min(Math.max(Number.isFinite(time) ? time : 0, 0), total)
  const segment = segments.find(s => safe < s.end) || segments[segments.length - 1]
  return { segment, offset: Math.min(Math.max(safe - segment.start, 0), segment.duration) }
}

export function workshopTime(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds || 0))
  return String(Math.floor(total / 60)).padStart(2, "0") + ":" + String(total % 60).padStart(2, "0")
}
