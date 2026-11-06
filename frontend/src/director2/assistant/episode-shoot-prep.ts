import { director2ErrorDetail, type Director2Asset, type Director2Beat } from "../api"
import { episodeShootPrepLines, evaluateEpisodeShootPreflight, type EpisodeShootPreflight } from "./episode-shoot-preflight"

export type ShootPrepPhase = "scene" | "look"

export type ShootPrepProgress = {
  phase: ShootPrepPhase
  label: string
  index: number
  total: number
}

export type ShootPrepApi = {
  createAsset: (projectId: string, data: Record<string, unknown>) => Promise<{ id: string }>
  updateAsset: (projectId: string, assetId: string, data: Record<string, unknown>) => Promise<unknown>
  updateEpisodeBeat: (projectId: string, episodeId: string, beatId: string, patch: Record<string, unknown>) => Promise<unknown>
  generateAssetImage: (projectId: string, assetId: string, data: Record<string, unknown>) => Promise<unknown>
  getEpisodeDetail: (projectId: string, episodeId: string) => Promise<{ beats?: Director2Beat[] }>
  listAssets: (projectId: string) => Promise<Director2Asset[]>
}

export type ShootPrepResult = {
  ok: boolean
  generated: number
  message?: string
  failures: string[]
}

const MAX_ROUNDS = 3
const GENERATION_CONCURRENCY = 2

export function formatShootPrepElapsed(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds || 0))
  const minutes = Math.floor(total / 60)
  const rest = total % 60
  return minutes ? `${minutes} 分 ${String(rest).padStart(2, "0")} 秒` : `${rest} 秒`
}

async function runLimited<T>(items: T[], task: (item: T, index: number) => Promise<void>): Promise<void> {
  let cursor = 0
  const workerCount = Math.min(GENERATION_CONCURRENCY, items.length)
  await Promise.all(Array.from({ length: workerCount }, async () => {
    while (true) {
      const index = cursor
      cursor += 1
      if (index >= items.length) return
      await task(items[index], index)
    }
  }))
}

export async function prepareEpisodeShootAssets({
  projectId,
  episodeId,
  beats,
  assets,
  plan,
  scopeBeatIds,
  api,
  onProgress,
}: {
  projectId: string
  episodeId: string
  beats: Director2Beat[]
  assets: Director2Asset[]
  plan: EpisodeShootPreflight
  scopeBeatIds?: string[] | null
  api: ShootPrepApi
  onProgress?: (progress: ShootPrepProgress) => void
}): Promise<ShootPrepResult> {
  let generated = 0
  const failures: string[] = []
  const scope = scopeBeatIds && scopeBeatIds.length ? new Set(scopeBeatIds.map(String)) : null
  const inScope = (item: Director2Beat) => !scope || scope.has(String(item.id || ""))
  const createdScenes = new Map<string, string>()
  const createdLooks = new Set<string>()
  const generatedScenes = new Set<string>()
  const generatedLooks = new Set<string>()
  let currentPlan = plan
  let currentBeats = beats
  let currentAssets = assets

  const result = (ok: boolean, message?: string): ShootPrepResult => ({
    ok,
    generated,
    message,
    failures,
  })

  try {
    for (let round = 0; round < MAX_ROUNDS; round += 1) {
      for (const scene of currentPlan.sceneCreates) {
        if (createdScenes.has(scene.key)) continue
        const created = await api.createAsset(projectId, {
          kind: "scene",
          name: scene.name,
          description: scene.prompt,
          visual_prompt: scene.prompt,
        })
        createdScenes.set(scene.key, created.id)
      }
      for (const look of currentPlan.lookCreates) {
        if (createdLooks.has(look.assetId)) continue
        const target = currentAssets.find((asset) => asset.id === look.assetId)
        if (!target) {
          failures.push(`找不到角色「${look.characterName}」`)
          continue
        }
        const identities = [...((target.extra?.identities as Array<Record<string, unknown>>) || [])]
        identities.push({
          id: `ident-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
          name: look.identityName,
          description: look.description,
          visual_prompt: `${look.characterName} 全身立绘，${look.description}`,
          image_url: "",
        })
        await api.updateAsset(projectId, target.id, {
          extra: { ...(target.extra || {}), identities },
        })
        createdLooks.add(look.assetId)
      }
      const updates = new Map<string, Record<string, unknown>>()
      const merge = (beatId: string, patch: Record<string, unknown>) => {
        if (!beatId) return
        updates.set(beatId, { ...(updates.get(beatId) || {}), ...patch })
      }
      for (const binding of currentPlan.sceneBindings) merge(binding.beatId, { scene_id: binding.assetId })
      for (const scene of currentPlan.sceneCreates) {
        const assetId = createdScenes.get(scene.key)
        if (!assetId) continue
        for (const item of scene.beats) merge(item.beatId, { scene_id: assetId })
      }
      const beatsById = new Map(currentBeats.map((beat) => [String(beat.id || ""), beat]))
      for (const binding of currentPlan.lookBindings) {
        const beat = beatsById.get(binding.beatId)
        const pending = updates.get(binding.beatId)?.character_look_ids as Record<string, string> | undefined
        const current = pending
          || (beat?.character_look_ids && typeof beat.character_look_ids === "object" ? beat.character_look_ids : {})
        merge(binding.beatId, { character_look_ids: { ...current, [binding.characterId]: binding.identityId } })
      }
      for (const [beatId, patch] of updates) {
        await api.updateEpisodeBeat(projectId, episodeId, beatId, patch)
      }
      if (failures.length) return result(false, failures.join("\n"))

      const [detail, nextAssets] = await Promise.all([
        api.getEpisodeDetail(projectId, episodeId),
        api.listAssets(projectId),
      ])
      currentBeats = (detail.beats || []).filter(inScope)
      currentAssets = nextAssets
      const next = evaluateEpisodeShootPreflight({ beats: currentBeats, assets: currentAssets })
      if (next.ready) return result(true)
      if (!next.canFix) {
        return result(false, next.blocking.length ? next.blocking.join("\n") : episodeShootPrepLines(next).join("\n"))
      }
      currentPlan = next

      const pendingMasters = next.sceneMasters.filter((item) => !generatedScenes.has(item.assetId))
      const pendingLooks = next.lookGenerations.filter((item) => !generatedLooks.has(`${item.assetId}:${item.identityId}`))
      if (!pendingMasters.length && !pendingLooks.length) continue

      await runLimited(pendingMasters, async (item, index) => {
        onProgress?.({ phase: "scene", label: item.name, index: index + 1, total: pendingMasters.length })
        try {
          await api.generateAssetImage(projectId, item.assetId, {
            target_type: "scene_master",
            prompt: item.prompt,
            model: "gpt-image-2.5",
            aspect_ratio: "16:9",
            visual_style: item.style.visual_style,
            art_style_id: item.style.art_style_id,
          })
          generatedScenes.add(item.assetId)
          generated += 1
        } catch (e) {
          failures.push(`场景「${item.name}」：${director2ErrorDetail(e, "生成失败")}`)
        }
      })
      await runLimited(pendingLooks, async (item, index) => {
        onProgress?.({ phase: "look", label: `${item.characterName} · ${item.identityName}`, index: index + 1, total: pendingLooks.length })
        try {
          await api.generateAssetImage(projectId, item.assetId, {
            target_type: "identity",
            identity_id: item.identityId,
            prompt: item.costume,
            model: "gpt-image-2.5",
            aspect_ratio: "16:9",
            ...item.style,
          })
          generatedLooks.add(`${item.assetId}:${item.identityId}`)
          generated += 1
        } catch (e) {
          failures.push(`造型「${item.characterName} · ${item.identityName}」：${director2ErrorDetail(e, "生成失败")}`)
        }
      })
      if (failures.length) return result(false, failures.join("\n"))
    }

    const [finalDetail, finalAssets] = await Promise.all([
      api.getEpisodeDetail(projectId, episodeId),
      api.listAssets(projectId),
    ])
    const final = evaluateEpisodeShootPreflight({ beats: (finalDetail.beats || []).filter(inScope), assets: finalAssets })
    if (!final.ready) {
      const remaining = [...final.blocking, ...episodeShootPrepLines(final)].join("\n")
      return result(false, remaining)
    }
    return result(true)
  } catch (e) {
    return result(false, director2ErrorDetail(e, "补齐出片素材失败"))
  }
}
