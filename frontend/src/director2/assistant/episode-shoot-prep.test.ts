import { describe, expect, it } from "vitest"
import type { Director2Asset, Director2Beat } from "../api"
import { evaluateEpisodeShootPreflight } from "./episode-shoot-preflight"
import {
  formatShootPrepElapsed,
  prepareEpisodeShootAssets,
  type ShootPrepApi,
  type ShootPrepProgress,
} from "./episode-shoot-prep"

const PROJECT_ID = "proj-1"
const EPISODE_ID = "ep-1"

type Store = { beats: Director2Beat[]; assets: Director2Asset[] }

function asset(partial: Partial<Director2Asset> & { id: string; kind: string; name: string }): Director2Asset {
  return {
    project_id: PROJECT_ID,
    role: null,
    description: null,
    visual_prompt: null,
    image_url: null,
    voice_id: null,
    extra: {},
    created_at: "",
    updated_at: "",
    ...partial,
  }
}

function beat(partial: Partial<Director2Beat> & { sequence: number }): Director2Beat {
  return {
    id: `beat-${partial.sequence}`,
    action: "推门进入办公室，环顾四周",
    camera: "中景推近",
    ...partial,
  }
}

function character(id: string, name: string, identities: Array<Record<string, any>> = []): Director2Asset {
  return asset({ id, kind: "character", name, extra: { identities } })
}

function noImageLook(id: string, description: string): Record<string, any> {
  return { id, name: `${id} (日常造型)`, description, image_url: "" }
}

function createHarness(
  store: Store,
  options: { delayMs?: number; failOnce?: string[]; failAlways?: string[] } = {},
) {
  const failOnce = new Set(options.failOnce || [])
  const failAlways = new Set(options.failAlways || [])
  const attempts = new Map<string, number>()
  const created: Array<Record<string, unknown>> = []
  const generated: Array<{ assetId: string; data: Record<string, any> }> = []
  let active = 0
  let maxActive = 0

  const api: ShootPrepApi = {
    async createAsset(_projectId, data) {
      const id = `scene-new-${created.length + 1}`
      created.push({ id, ...data })
      store.assets.push(asset({
        id,
        kind: String(data.kind || "scene"),
        name: String(data.name || ""),
        description: String(data.description || ""),
        visual_prompt: String(data.visual_prompt || ""),
      }))
      return { id }
    },
    async updateAsset(_projectId, assetId, data) {
      const target = store.assets.find((item) => item.id === assetId)
      if (target) target.extra = { ...(data.extra as Record<string, any>) }
      return target
    },
    async updateEpisodeBeat(_projectId, _episodeId, beatId, patch) {
      const target = store.beats.find((item) => item.id === beatId)
      if (target) Object.assign(target, patch)
      return target
    },
    async generateAssetImage(_projectId, assetId, data) {
      const key = String(data.identity_id || assetId)
      attempts.set(key, (attempts.get(key) || 0) + 1)
      active += 1
      maxActive = Math.max(maxActive, active)
      try {
        if (options.delayMs) await new Promise((resolve) => setTimeout(resolve, options.delayMs))
        if (failAlways.has(key)) throw new Error("模型审核未通过")
        if (failOnce.delete(key)) throw new Error("模型审核未通过")
        generated.push({ assetId, data })
        if (data.target_type === "scene_master") {
          const scene = store.assets.find((item) => item.id === assetId)
          if (scene) scene.extra = { ...scene.extra, master_url: `https://cdn.example.com/${assetId}.png` }
        } else {
          const target = store.assets.find((item) => item.id === assetId)
          if (target) {
            const identities = ((target.extra.identities || []) as Array<Record<string, any>>).map((identity) =>
              identity.id === data.identity_id
                ? { ...identity, image_url: `https://cdn.example.com/${identity.id}.png` }
                : identity,
            )
            target.extra = { ...target.extra, identities }
          }
        }
        return { ok: true }
      } finally {
        active -= 1
      }
    },
    async getEpisodeDetail() {
      return { beats: store.beats }
    },
    async listAssets() {
      return store.assets
    },
  }

  return {
    api,
    created,
    generated,
    attempts,
    get maxActive() { return maxActive },
  }
}

function planOf(store: Store) {
  return evaluateEpisodeShootPreflight({ beats: store.beats, assets: store.assets })
}

function runShootPrep(store: Store, harness: ReturnType<typeof createHarness>, progress?: ShootPrepProgress[]) {
  return prepareEpisodeShootAssets({
    projectId: PROJECT_ID,
    episodeId: EPISODE_ID,
    beats: store.beats,
    assets: store.assets,
    plan: planOf(store),
    api: harness.api,
    onProgress: (item) => progress?.push(item),
  })
}

function officeStore(): Store {
  const store: Store = {
    assets: [
      asset({ id: "scene-office", kind: "scene", name: "开放式办公区", extra: { environment_prompt: "开放式办公区，夜" } }),
      character("char-li", "李明", [noImageLook("ident-li", "白衬衫")]),
      character("char-boss", "王主管", [noImageLook("ident-boss", "深色西装")]),
      character("char-staff", "老员工A", [noImageLook("ident-staff", "灰色工装")]),
    ],
    beats: [
      beat({ sequence: 1, scene: "开放式办公区 - 夜", scene_id: "scene-office", character_ids: ["char-li", "char-boss", "char-staff"] }),
    ],
  }
  return store
}

describe("prepareEpisodeShootAssets", () => {
  it("generates the missing scene master and looks, reports progress and finishes ready", async () => {
    const store = officeStore()
    const harness = createHarness(store, { delayMs: 5 })
    const progress: ShootPrepProgress[] = []

    const plan = planOf(store)
    expect(plan.canFix).toBe(true)
    expect(plan.sceneMasters).toHaveLength(1)
    expect(plan.lookGenerations).toHaveLength(3)

    const result = await runShootPrep(store, harness, progress)

    expect(result).toMatchObject({ ok: true, generated: 4, failures: [] })
    expect(harness.generated).toHaveLength(4)
    expect(harness.maxActive).toBe(2)
    expect(harness.generated.map((item) => item.data.target_type).sort()).toEqual(["identity", "identity", "identity", "scene_master"])
    expect(planOf(store).ready).toBe(true)

    const sceneProgress = progress.filter((item) => item.phase === "scene")
    expect(sceneProgress).toEqual([{ phase: "scene", label: "开放式办公区", index: 1, total: 1 }])
    const lookProgress = progress.filter((item) => item.phase === "look")
    expect(lookProgress).toHaveLength(3)
    expect(lookProgress.map((item) => item.index).sort()).toEqual([1, 2, 3])
    expect(lookProgress.every((item) => item.total === 3)).toBe(true)
  })

  it("returns a failure right away when one generation is rejected and retries only the missing look", async () => {
    const store = officeStore()
    const harness = createHarness(store, { failOnce: ["ident-boss"] })

    const first = await runShootPrep(store, harness)

    expect(first.ok).toBe(false)
    expect(first.failures).toHaveLength(1)
    expect(first.message).toContain("王主管")
    expect(first.message).toContain("模型审核未通过")
    expect(first.generated).toBe(3)
    expect(harness.attempts.get("ident-li")).toBe(1)
    expect(harness.attempts.get("ident-boss")).toBe(1)
    expect(harness.attempts.get("ident-staff")).toBe(1)
    expect(harness.generated).toHaveLength(3)
    expect(planOf(store).ready).toBe(false)

    const second = await runShootPrep(store, harness)

    expect(second).toMatchObject({ ok: true, generated: 1, failures: [] })
    expect(harness.attempts.get("ident-boss")).toBe(2)
    expect(harness.attempts.get("ident-li")).toBe(1)
    expect(harness.generated).toHaveLength(4)
    expect(planOf(store).ready).toBe(true)
  })

  it("creates the missing scene card and identity, binds the beat and generates both images", async () => {
    const store: Store = {
      assets: [
        (() => {
          const li = character("char-li", "李明")
          li.description = "26 岁程序员，短发，白衬衫"
          return li
        })(),
      ],
      beats: [beat({ sequence: 1, scene: "天台 - 夜", character_ids: ["char-li"] })],
    }
    const harness = createHarness(store)

    const plan = planOf(store)
    expect(plan.sceneCreates).toHaveLength(1)
    expect(plan.lookCreates).toHaveLength(1)

    const result = await runShootPrep(store, harness)

    expect(result).toMatchObject({ ok: true, generated: 2, failures: [] })
    expect(harness.created).toHaveLength(1)
    expect(harness.created[0]).toMatchObject({ kind: "scene", name: "天台" })
    expect(harness.created[0].description).toContain("天台")
    expect(store.beats[0].scene_id).toBe("scene-new-1")
    const li = store.assets.find((item) => item.id === "char-li")!
    const identities = li.extra.identities as Array<Record<string, any>>
    expect(identities).toHaveLength(1)
    expect(identities[0].name).toBe("李明 (日常造型)")
    expect(harness.generated.map((item) => item.data.target_type).sort()).toEqual(["identity", "scene_master"])
    expect(planOf(store).ready).toBe(true)
  })

  it("does not call any generation when the plan is already ready", async () => {
    const store = officeStore()
    for (const item of store.assets) {
      if (item.kind === "scene") item.extra = { ...item.extra, master_url: "https://cdn.example.com/scene.png" }
      if (item.kind === "character") {
        item.extra = {
          ...item.extra,
          identities: (item.extra.identities as Array<Record<string, any>>).map((identity) => ({
            ...identity,
            image_url: `https://cdn.example.com/${identity.id}.png`,
          })),
        }
      }
    }
    const harness = createHarness(store)
    const result = await runShootPrep(store, harness)
    expect(result).toMatchObject({ ok: true, generated: 0 })
    expect(harness.generated).toHaveLength(0)
    expect(harness.created).toHaveLength(0)
  })

  it("returns blocking reasons without generating when the episode cannot be auto-fixed", async () => {
    const store: Store = {
      assets: [character("char-li", "李明", [noImageLook("ident-li", "白衬衫")])],
      beats: [beat({ sequence: 1, action: "", camera: "", character_ids: ["char-li"] })],
    }
    const harness = createHarness(store)
    const result = await runShootPrep(store, harness)
    expect(result.ok).toBe(false)
    expect(result.message).toContain("缺少动作或视频提示词")
    expect(harness.generated).toHaveLength(0)
    expect(harness.created).toHaveLength(0)
  })
})

describe("formatShootPrepElapsed", () => {
  it("formats seconds and minutes for the progress line", () => {
    expect(formatShootPrepElapsed(0)).toBe("0 秒")
    expect(formatShootPrepElapsed(-5)).toBe("0 秒")
    expect(formatShootPrepElapsed(59)).toBe("59 秒")
    expect(formatShootPrepElapsed(60)).toBe("1 分 00 秒")
    expect(formatShootPrepElapsed(125)).toBe("2 分 05 秒")
  })
})
