import { describe, expect, it } from "vitest"
import type { Director2Asset, Director2Beat } from "../api"
import {
  ensureWorkshopShootReady,
  workshopShootPrepConfirmLines,
  type WorkshopShootGuardResult,
} from "./workshop-shoot-guard"
import { evaluateEpisodeShootPreflight } from "./episode-shoot-preflight"
import type { ShootPrepApi, ShootPrepProgress } from "./episode-shoot-prep"

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
  } as Director2Asset
}

function beat(partial: Partial<Director2Beat> & { id: string; sequence: number }): Director2Beat {
  return {
    action: "推门进入办公室，环顾四周",
    camera: "中景推近",
    ...partial,
  } as Director2Beat
}

function createHarness(store: Store, options: { failGenerate?: boolean } = {}) {
  const created: Array<Record<string, unknown>> = []
  const generated: Array<{ assetId: string; data: Record<string, any> }> = []
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
      return { id } as Director2Asset
    },
    async updateAsset(_projectId, assetId, data) {
      const target = store.assets.find((item) => item.id === assetId)
      if (target) target.extra = { ...(data.extra as Record<string, any>) }
      return target as Director2Asset
    },
    async updateEpisodeBeat(_projectId, _episodeId, beatId, patch) {
      const target = store.beats.find((item) => item.id === beatId)
      if (target) Object.assign(target, patch)
      return target
    },
    async generateAssetImage(_projectId, assetId, data) {
      if (options.failGenerate) throw new Error("模型审核未通过")
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
    },
    async getEpisodeDetail() {
      return { beats: store.beats.map((item) => ({ ...item })) } as any
    },
    async listAssets() {
      return store.assets
    },
  }
  return { api, created, generated }
}

function runGuard(input: {
  store: Store
  scopeBeatIds?: string[] | null
  confirmResult?: boolean
  confirmCalls?: Array<{ paid: boolean; lines: string[] }>
  progress?: ShootPrepProgress[]
}): Promise<WorkshopShootGuardResult> {
  const harness = createHarness(input.store)
  return ensureWorkshopShootReady({
    projectId: PROJECT_ID,
    episodeId: EPISODE_ID,
    beats: input.store.beats,
    assets: input.store.assets,
    scopeBeatIds: input.scopeBeatIds ?? null,
    api: harness.api,
    confirm: async (plan, paid) => {
      input.confirmCalls?.push({ paid, lines: workshopShootPrepConfirmLines(plan, paid) })
      return input.confirmResult ?? true
    },
    onProgress: (item) => input.progress?.push(item),
  })
}

function twoBeatStore(): Store {
  const li = asset({ id: "char-li", kind: "character", name: "李明" })
  ;(li as Record<string, any>).description = "26 岁程序员，短发，白衬衫"
  return {
    assets: [li],
    beats: [
      beat({ id: "beat-1", sequence: 1, scene: "天台 - 夜", character_ids: ["char-li"] }),
      beat({ id: "beat-2", sequence: 2, scene: "走廊 - 日", character_ids: ["char-li"] }),
    ],
  }
}

describe("ensureWorkshopShootReady", () => {
  it("passes straight through when the scoped beats are already ready", async () => {
    const store: Store = {
      assets: [
        asset({ id: "scene-roof", kind: "scene", name: "天台", extra: { master_url: "https://cdn.example.com/roof.png" } }),
        asset({
          id: "char-li", kind: "character", name: "李明",
          extra: { identities: [{ id: "ident-li", name: "日常造型", description: "白衬衫", image_url: "https://cdn.example.com/li.png" }] },
        }),
      ],
      beats: [beat({ id: "beat-1", sequence: 1, scene: "天台 - 夜", scene_id: "scene-roof", character_ids: ["char-li"] })],
    }
    const confirmCalls: Array<{ paid: boolean; lines: string[] }> = []
    const result = await runGuard({ store, scopeBeatIds: ["beat-1"], confirmCalls })
    expect(result.status).toBe("ready")
    expect(confirmCalls).toHaveLength(0)
  })

  it("auto-fixes only the scoped beat and leaves other beats untouched", async () => {
    const store = twoBeatStore()
    const progress: ShootPrepProgress[] = []
    const result = await runGuard({ store, scopeBeatIds: ["beat-1"], progress })
    expect(result.status).toBe("ready")
    if (result.status !== "ready") return
    expect(result.generated).toBeGreaterThan(0)
    // 目标镜头被补齐：绑定了新建场景与造型锁定
    expect(store.beats[0].scene_id).toBe("scene-new-1")
    expect(evaluateEpisodeShootPreflight({ beats: [store.beats[0]], assets: store.assets }).ready).toBe(true)
    // 未选中的镜头不被处理
    expect(store.beats[1].scene_id).toBeUndefined()
    const createdNames = store.assets.filter((item) => item.kind === "scene").map((item) => item.name)
    expect(createdNames).toContain("天台")
    expect(createdNames).not.toContain("走廊")
    expect(progress.every((item) => item.total >= 1)).toBe(true)
  })

  it("returns blocking reasons without asking for confirmation when nothing can be auto-fixed", async () => {
    const store: Store = {
      assets: [],
      beats: [beat({ id: "beat-1", sequence: 1, action: "", camera: "" })],
    }
    const confirmCalls: Array<{ paid: boolean; lines: string[] }> = []
    const result = await runGuard({ store, scopeBeatIds: ["beat-1"], confirmCalls })
    expect(result.status).toBe("blocked")
    if (result.status !== "blocked") return
    expect(result.message).toContain("缺少动作或视频提示词")
    expect(result.needsWorkshop).toBe(true)
    expect(confirmCalls).toHaveLength(0)
  })

  it("respects cancellation and performs no mutations", async () => {
    const store = twoBeatStore()
    const result = await runGuard({ store, scopeBeatIds: ["beat-1"], confirmResult: false })
    expect(result.status).toBe("cancelled")
    expect(store.beats[0].scene_id).toBeUndefined()
    expect(store.assets.filter((item) => item.kind === "scene")).toHaveLength(0)
  })

  it("reports failure when the paid prep cannot complete", async () => {
    const store = twoBeatStore()
    const harness = createHarness(store, { failGenerate: true })
    const result = await ensureWorkshopShootReady({
      projectId: PROJECT_ID,
      episodeId: EPISODE_ID,
      beats: store.beats,
      assets: store.assets,
      scopeBeatIds: ["beat-1"],
      api: harness.api,
      confirm: async () => true,
    })
    expect(result.status).toBe("blocked")
    if (result.status !== "blocked") return
    expect(result.message).toContain("模型审核未通过")
  })
})

describe("workshopShootPrepConfirmLines", () => {
  it("includes the prep plan and the paid notice", () => {
    const store = twoBeatStore()
    const plan = evaluateEpisodeShootPreflight({ beats: [store.beats[0]], assets: store.assets })
    const lines = workshopShootPrepConfirmLines(plan, true)
    expect(lines[0]).toBe("提交前将自动补齐：")
    expect(lines.some((line) => line.includes("场景卡"))).toBe(true)
    expect(lines[lines.length - 1]).toContain("1-3 分钟")
    expect(workshopShootPrepConfirmLines(plan, false)).not.toContainEqual(expect.stringContaining("1-3 分钟"))
  })
})
