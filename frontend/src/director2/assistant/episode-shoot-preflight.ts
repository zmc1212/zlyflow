import { hasSourceReferences } from "../asset-source-references"
import type { Director2Asset, Director2Beat } from "../api"

const MODERN_CONTEXT_PATTERN = /现代|大学|图书馆|电脑|西装|衬衫|研究生|26岁/
const ANCIENT_CONTEXT_PATTERN = /古代|茅屋|长衫|粗布|发髻|陶碗|木床|土墙|米缸|17岁/
const MODERN_LOOK_PATTERN = /现代|西装|衬衫|研究生|26岁/
const ANCIENT_LOOK_PATTERN = /古代|长衫|粗布|发髻|17岁/
const SCENE_QUALIFIERS = ["门口", "门前", "里面", "内部", "区域", "隔间", "内景", "外景", "夜景", "日景", "内", "外", "里"]
const SCENE_SEPARATOR = /\s*[-—–·]\s*/

type IdentityLike = {
  id?: string
  name?: string
  description?: string
  appearance_details?: string
  visual_prompt?: string
  image_url?: string
}

export type ShootLookStyle = {
  ethnicity: string
  visual_style: string
  art_style_id: string
  body_type: string
  gender: string
}

export type ShootSceneBinding = {
  beatId: string
  sequence: number
  assetId: string
  assetName: string
}

export type ShootSceneCreate = {
  key: string
  name: string
  prompt: string
  beats: Array<{ beatId: string; sequence: number }>
}

export type ShootSceneMaster = {
  assetId: string
  name: string
  prompt: string
  style: Pick<ShootLookStyle, "visual_style" | "art_style_id">
  sequences: number[]
}

export type ShootLookBinding = {
  beatId: string
  characterId: string
  identityId: string
}

export type ShootLookCreate = {
  assetId: string
  characterName: string
  identityName: string
  description: string
}

export type ShootLookGeneration = {
  assetId: string
  characterName: string
  identityId: string
  identityName: string
  costume: string
  style: ShootLookStyle
  sequences: number[]
}

export type EpisodeShootPreflight = {
  ready: boolean
  canFix: boolean
  blocking: string[]
  sceneBindings: ShootSceneBinding[]
  sceneCreates: ShootSceneCreate[]
  sceneMasters: ShootSceneMaster[]
  lookBindings: ShootLookBinding[]
  lookCreates: ShootLookCreate[]
  lookGenerations: ShootLookGeneration[]
}

export function evaluateEpisodeShootPreflight(input: {
  beats: Director2Beat[]
  assets: Director2Asset[]
}): EpisodeShootPreflight {
  const beats = [...(input.beats || [])].sort((a, b) => Number(a.sequence || 0) - Number(b.sequence || 0))
  const assets = input.assets || []
  const byId = new Map(assets.map((asset) => [String(asset.id || ""), asset]))
  const scenes = assets.filter((asset) => asset.kind === "scene")
  const characters = assets.filter((asset) => asset.kind === "character")
  const protagonist = episodeProtagonist(beats, characters)
  const blocking = new Set<string>()
  const sceneBindings: ShootSceneBinding[] = []
  const sceneCreates = new Map<string, ShootSceneCreate>()
  const sceneMasters = new Map<string, ShootSceneMaster>()
  const lookBindings: ShootLookBinding[] = []
  const lookCreates = new Map<string, ShootLookCreate>()
  const lookGenerations = new Map<string, ShootLookGeneration>()

  for (const beat of beats) {
    const sequence = Number(beat.sequence || 0) || 1
    const action = String(beat.video_prompt_zh || beat.action || "").trim()
    if (!action) blocking.add(`Beat ${sequence} 缺少动作或视频提示词`)
    if (!String(beat.camera || "").trim()) blocking.add(`Beat ${sequence} 缺少运镜描述`)
    if (String(beat.dialogue || "").trim() && !String(beat.speaker || "").trim()) {
      blocking.add(`Beat ${sequence} 有对白但缺少说话人`)
    }

    const sceneText = String(beat.scene || "").trim()
    const resolved = resolveBeatScene(beat, scenes, byId)
    if (!resolved.asset) {
      if (!sceneText) {
        blocking.add(`Beat ${sequence} 未绑定场景，请在镜头检视器选择场景`)
      } else {
        const key = sceneKey(sceneText) || normalizeSceneText(sceneText)
        const group = sceneCreates.get(key) || {
          key,
          name: sceneLocationName(sceneText),
          prompt: sceneCreatePrompt(beat, sceneLocationName(sceneText)),
          beats: [],
        }
        group.beats.push({ beatId: String(beat.id || ""), sequence })
        sceneCreates.set(key, group)
      }
    } else {
      if (resolved.shouldBind) {
        sceneBindings.push({
          beatId: String(beat.id || ""),
          sequence,
          assetId: String(resolved.asset.id || ""),
          assetName: String(resolved.asset.name || ""),
        })
      }
      if (!assetMasterUrl(resolved.asset)) {
        const assetId = String(resolved.asset.id || "")
        const existing = sceneMasters.get(assetId)
        if (existing) existing.sequences.push(sequence)
        else {
          sceneMasters.set(assetId, {
            assetId,
            name: String(resolved.asset.name || sceneText || ""),
            prompt: sceneMasterPrompt(resolved.asset),
            style: assetStyle(resolved.asset),
            sequences: [sequence],
          })
        }
      }
    }

    const beatCharacters = (beat.character_ids || [])
      .map((id) => byId.get(String(id)))
      .filter((asset): asset is Director2Asset => !!asset && asset.kind === "character")
    const cast = beatCharacters.length ? beatCharacters : protagonist ? [protagonist] : []
    if (!cast.length) {
      blocking.add("无法确定分集主角，请为镜头关联主角资产")
      continue
    }
    for (const character of cast) {
      applyLookDecision({
        character,
        beat,
        sequence,
        blocking,
        lookBindings,
        lookCreates,
        lookGenerations,
      })
    }
  }

  const sceneBindingList = sceneBindings.filter((item) => !!item.beatId)
  const sceneCreateList = [...sceneCreates.values()].filter((item) => item.beats.length > 0)
  const sceneMasterList = [...sceneMasters.values()]
  const lookBindingList = lookBindings.filter((item) => !!item.beatId && !!item.characterId && !!item.identityId)
  const lookCreateList = [...lookCreates.values()]
  const lookGenerationList = [...lookGenerations.values()]
  const blockingList = [...blocking]
  const fixes = sceneBindingList.length + sceneCreateList.length + sceneMasterList.length
    + lookBindingList.length + lookCreateList.length + lookGenerationList.length
  return {
    ready: !blockingList.length && fixes === 0,
    canFix: !blockingList.length && fixes > 0,
    blocking: blockingList,
    sceneBindings: sceneBindingList,
    sceneCreates: sceneCreateList,
    sceneMasters: sceneMasterList,
    lookBindings: lookBindingList,
    lookCreates: lookCreateList,
    lookGenerations: lookGenerationList,
  }
}

export function episodeShootPrepLines(preflight: EpisodeShootPreflight): string[] {
  const lines: string[] = []
  if (preflight.sceneBindings.length) {
    lines.push(`自动匹配 ${preflight.sceneBindings.length} 个镜头的场景绑定。`)
  }
  if (preflight.sceneCreates.length) {
    lines.push(`新增 ${preflight.sceneCreates.length} 个场景卡：${preflight.sceneCreates.map((item) => item.name).join("、")}。`)
  }
  const masterCount = preflight.sceneMasters.length + preflight.sceneCreates.length
  if (masterCount) {
    const names = uniqueNames([
      ...preflight.sceneMasters.map((item) => item.name),
      ...preflight.sceneCreates.map((item) => item.name),
    ])
    lines.push(`生成 ${masterCount} 张场景主视图：${names.join("、")}。`)
  }
  if (preflight.lookCreates.length) {
    lines.push(`为 ${preflight.lookCreates.map((item) => item.characterName).join("、")} 新增日常造型。`)
  }
  if (preflight.lookGenerations.length) {
    const names = uniqueNames(preflight.lookGenerations.map((item) => item.characterName))
    lines.push(`生成 ${preflight.lookGenerations.length} 张角色造型图：${names.join("、")}。`)
  }
  if (preflight.lookBindings.length) {
    lines.push(`为 ${preflight.lookBindings.length} 个镜头锁定角色造型。`)
  }
  return lines
}

export function episodeShootPrepSummary(preflight: EpisodeShootPreflight): string {
  if (preflight.ready) return ""
  if (!preflight.canFix) {
    return `还有 ${preflight.blocking.length} 项出片前置需要处理，点击查看清单并前往工坊。`
  }
  const parts: string[] = []
  if (preflight.sceneBindings.length) parts.push(`${preflight.sceneBindings.length} 个镜头场景绑定`)
  if (preflight.sceneCreates.length) parts.push(`${preflight.sceneCreates.length} 个场景卡`)
  const masters = preflight.sceneMasters.length + preflight.sceneCreates.length
  if (masters) parts.push(`${masters} 张场景主视图`)
  if (preflight.lookCreates.length) parts.push(`${preflight.lookCreates.length} 个角色造型`)
  if (preflight.lookGenerations.length) parts.push(`${preflight.lookGenerations.length} 张角色造型图`)
  if (preflight.lookBindings.length) parts.push(`${preflight.lookBindings.length} 个镜头造型锁定`)
  return parts.length
    ? `还差 ${parts.join("、")}，点击后自动补齐并提交出片。`
    : "点击后自动补齐出片前置并提交。"
}

export function hasPaidShootPrep(preflight: EpisodeShootPreflight): boolean {
  return Boolean(
    preflight.sceneCreates.length
    || preflight.sceneMasters.length
    || preflight.lookCreates.length
    || preflight.lookGenerations.length,
  )
}

function applyLookDecision(input: {
  character: Director2Asset
  beat: Director2Beat
  sequence: number
  blocking: Set<string>
  lookBindings: ShootLookBinding[]
  lookCreates: Map<string, ShootLookCreate>
  lookGenerations: Map<string, ShootLookGeneration>
}) {
  const { character, beat, sequence, blocking, lookBindings, lookCreates, lookGenerations } = input
  const decision = decideCharacterLook(character, beat, sequence)
  const characterId = String(character.id || "")
  const characterName = String(character.name || "角色")
  if (decision.kind === "ready") return
  if (decision.kind === "block") {
    blocking.add(decision.message)
    return
  }
  if (decision.kind === "create") {
    const assetId = characterId
    if (!assetId) {
      blocking.add(`「${characterName}」缺少资产 ID，请到资产库检查`)
      return
    }
    if (lookCreates.has(assetId)) return
    lookCreates.set(assetId, {
      assetId,
      characterName,
      identityName: `${characterName} (日常造型)`,
      description: decision.description,
    })
    return
  }

  const identity = decision.identity
  const identityId = String(identity.id || "")
  if (!identityId) {
    blocking.add(`「${characterName}」的造型缺少 ID，请到资产库重新生成造型`)
    return
  }
  if (decision.kind === "bind" || decision.kind === "bind-generate") {
    if (!lookBindings.some((item) => item.beatId === beat.id && item.characterId === characterId)) {
      lookBindings.push({ beatId: String(beat.id || ""), characterId, identityId })
    }
  }
  if (decision.kind === "generate" || decision.kind === "bind-generate") {
    const costume = String(identity.description || identity.appearance_details || "").trim()
    if (!costume && !hasSourceReferences(character)) {
      blocking.add(`「${characterName}」的造型「${identity.name || identityId}」缺少外观描述，请到资产库补充或上传原片截图`)
      return
    }
    const key = `${characterId}:${identityId}`
    const existing = lookGenerations.get(key)
    if (existing) existing.sequences.push(sequence)
    else {
      lookGenerations.set(key, {
        assetId: characterId,
        characterName,
        identityId,
        identityName: String(identity.name || "造型"),
        costume,
        style: characterStyle(character),
        sequences: [sequence],
      })
    }
  }
}

type LookDecision =
  | { kind: "ready" }
  | { kind: "bind"; identity: IdentityLike }
  | { kind: "generate"; identity: IdentityLike }
  | { kind: "bind-generate"; identity: IdentityLike }
  | { kind: "create"; description: string }
  | { kind: "block"; message: string }

function decideCharacterLook(character: Director2Asset, beat: Director2Beat, sequence: number): LookDecision {
  const characterName = String(character.name || "角色")
  const identities = identitiesOf(character)
  const looks = identities.filter((item) => Boolean(item.image_url))
  const selectedIds = beat.character_look_ids && typeof beat.character_look_ids === "object"
    ? beat.character_look_ids
    : {}
  const selectedId = String(selectedIds[String(character.id || "")] || "").trim()
  if (selectedId) {
    const selected = identities.find((item) => String(item.id || "") === selectedId)
    if (!selected) {
      return {
        kind: "block",
        message: `Beat ${sequence} 为「${characterName}」选择的造型无效，请在镜头检视器重新选择`,
      }
    }
    return validLookImage(selected) ? { kind: "ready" } : { kind: "generate", identity: selected }
  }

  const legacyId = String(beat.character_look_id || "").trim()
  if (legacyId) {
    const legacy = identities.find((item) => String(item.id || "") === legacyId)
    if (legacy) {
      return validLookImage(legacy) ? { kind: "ready" } : { kind: "generate", identity: legacy }
    }
  }

  const context = [
    beat.heading,
    beat.action,
    beat.visual_prompt,
    beat.video_prompt_zh,
    beat.scene,
    beat.speaker,
  ].map((value) => String(value || "")).join(" ")
  const modern = MODERN_CONTEXT_PATTERN.test(context)
  const ancient = !modern && ANCIENT_CONTEXT_PATTERN.test(context)
  if (modern || ancient) {
    const pattern = modern ? MODERN_LOOK_PATTERN : ANCIENT_LOOK_PATTERN
    const contextLook = looks.find((item) => pattern.test(identityText(item)))
    if (contextLook) {
      return validLookImage(contextLook) ? { kind: "ready" } : { kind: "generate", identity: contextLook }
    }
    const matched = identities.find((item) => pattern.test(identityText(item)))
    if (matched) return { kind: "generate", identity: matched }
    if (!identities.length) return createLookDecision(character, characterName)
    return fallbackLookDecision(identities, looks)
  }

  if (looks.length === 1) {
    return validLookImage(looks[0]) ? { kind: "ready" } : { kind: "generate", identity: looks[0] }
  }
  if (looks.length > 1) return fallbackLookDecision(identities, looks)
  if (identities.length === 1) return { kind: "generate", identity: identities[0] }
  if (identities.length > 1) return fallbackLookDecision(identities, looks)
  return createLookDecision(character, characterName)
}

function createLookDecision(character: Director2Asset, characterName: string): LookDecision {
  const description = String(character.description || character.visual_prompt || "").trim()
  if (!description) {
    return {
      kind: "block",
      message: `「${characterName}」还没有造型，请先到资产库补充外观描述或新增造型`,
    }
  }
  return { kind: "create", description }
}

function fallbackLookDecision(identities: IdentityLike[], looks: IdentityLike[]): LookDecision {
  if (!identities.length) {
    return { kind: "block", message: "角色还没有造型，请先到资产库补充外观描述或新增造型" }
  }
  const preferred = preferredIdentity(identities)
  const chosen = validLookImage(preferred)
    ? preferred
    : looks.find(validLookImage) || preferred
  return validLookImage(chosen)
    ? { kind: "bind", identity: chosen }
    : { kind: "bind-generate", identity: chosen }
}

function episodeProtagonist(beats: Director2Beat[], characters: Director2Asset[]): Director2Asset | null {
  const byId = new Map(characters.map((character) => [String(character.id || ""), character]))
  for (const beat of beats) {
    for (const assetId of beat.character_ids || []) {
      const character = byId.get(String(assetId))
      if (character) return character
    }
  }
  const searchable = beats
    .map((beat) => [beat.heading, beat.speaker, beat.action, beat.dialogue].map((value) => String(value || "")).join(" "))
    .join(" ")
  return characters.find((character) => searchable.includes(String(character.name || ""))) || null
}

function resolveBeatScene(
  beat: Director2Beat,
  scenes: Director2Asset[],
  byId: Map<string, Director2Asset>,
): { asset: Director2Asset | null; shouldBind: boolean } {
  const bound = byId.get(String(beat.scene_id || ""))
  const boundScene = bound && bound.kind === "scene" ? bound : null
  if (boundScene && assetMasterUrl(boundScene)) return { asset: boundScene, shouldBind: false }
  const match = bestSceneMatch(String(beat.scene || ""), scenes)
  if (match && assetMasterUrl(match)) {
    return { asset: match, shouldBind: match !== boundScene }
  }
  if (boundScene) return { asset: boundScene, shouldBind: false }
  if (match) return { asset: match, shouldBind: true }
  return { asset: null, shouldBind: false }
}

function bestSceneMatch(sceneText: string, scenes: Director2Asset[]): Director2Asset | null {
  const scored = scenes
    .map((asset) => ({ asset, score: sceneMatchScore(String(asset.name || ""), sceneText) }))
    .filter((item) => item.score > 0)
  if (!scored.length) return null
  scored.sort((a, b) => {
    const masterDelta = Number(!!assetMasterUrl(b.asset)) - Number(!!assetMasterUrl(a.asset))
    return masterDelta || b.score - a.score
  })
  return scored[0].asset
}

function sceneMatchScore(assetName: string, sceneText: string): number {
  const target = sceneKey(sceneText)
  if (!target) return 0
  const raw = normalizeSceneText(assetName)
  const key = sceneKey(assetName)
  if (raw === target || key === target) return 1000 + target.length
  if (raw.includes(target) || target.includes(raw)) return 500 + Math.min(raw.length, target.length)
  if (key.includes(target) || target.includes(key)) return 300 + Math.min(key.length, target.length)
  return 0
}

function normalizeSceneText(value: string): string {
  let text = String(value || "").trim()
  text = text.replace(/[（(][^)）]*[)）]/g, "")
  text = text.split(SCENE_SEPARATOR)[0] || text
  return text.replace(/[\s,，。.:：;；!！?？"'“”‘’]/g, "")
}

function sceneKey(value: string): string {
  let text = normalizeSceneText(value)
  let changed = true
  while (changed && text.length > 2) {
    changed = false
    for (const qualifier of SCENE_QUALIFIERS) {
      if (text.endsWith(qualifier) && text.length - qualifier.length >= 2) {
        text = text.slice(0, -qualifier.length)
        changed = true
      }
    }
  }
  return text
}

function sceneLocationName(value: string): string {
  const text = String(value || "").trim().replace(/[（(][^)）]*[)）]/g, "")
  return (text.split(SCENE_SEPARATOR)[0] || text).trim() || String(value || "").trim()
}

function sceneCreatePrompt(beat: Director2Beat, name: string): string {
  const visual = String(beat.visual_prompt || "").trim()
  if (visual) return visual
  const context = [beat.heading, beat.action].map((value) => String(value || "").trim()).filter(Boolean).join("，")
  return context ? `${name}，${context}` : name
}

function sceneMasterPrompt(asset: Director2Asset): string {
  const extra = asset.extra || {}
  return String(extra.environment_prompt || asset.visual_prompt || asset.name || "").trim()
}

function assetMasterUrl(asset: Director2Asset | null | undefined): string {
  if (!asset) return ""
  const extra = asset.extra || {}
  const url = String(extra.master_url || asset.image_url || "").trim()
  return /^https?:\/\//i.test(url) ? url : ""
}

function identitiesOf(asset: Director2Asset): IdentityLike[] {
  const raw = asset.extra?.identities
  return Array.isArray(raw)
    ? raw.filter((item): item is IdentityLike => !!item && typeof item === "object")
    : []
}

function validLookImage(identity: IdentityLike): boolean {
  return /^https?:\/\//i.test(String(identity.image_url || "").trim())
}

function identityText(identity: IdentityLike): string {
  return [identity.name, identity.description, identity.appearance_details]
    .map((value) => String(value || ""))
    .join(" ")
}

function preferredIdentity(identities: IdentityLike[]): IdentityLike {
  return identities.find((identity) => /日常|初始/.test(String(identity.name || ""))) || identities[0]
}

function characterStyle(asset: Director2Asset): ShootLookStyle {
  const extra = asset.extra || {}
  return {
    ethnicity: String(extra.ethnicity || "Chinese"),
    visual_style: String(extra.visual_style || ""),
    art_style_id: String(extra.art_style_id || ""),
    body_type: String(extra.body_type || ""),
    gender: String(extra.gender || ""),
  }
}

function assetStyle(asset: Director2Asset): Pick<ShootLookStyle, "visual_style" | "art_style_id"> {
  const extra = asset.extra || {}
  return {
    visual_style: String(extra.visual_style || ""),
    art_style_id: String(extra.art_style_id || ""),
  }
}

function uniqueNames(names: string[]): string[] {
  return [...new Set(names.map((name) => name.trim()).filter(Boolean))]
}
