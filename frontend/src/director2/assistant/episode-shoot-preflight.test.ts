import { describe, expect, it } from "vitest"
import type { Director2Asset, Director2Beat } from "../api"
import {
  episodeShootPrepLines,
  episodeShootPrepSummary,
  evaluateEpisodeShootPreflight,
  hasPaidShootPrep,
} from "./episode-shoot-preflight"

function asset(partial: Partial<Director2Asset> & { id: string; kind: string; name: string }): Director2Asset {
  return {
    project_id: "proj-1",
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

const look = (id: string, name = "日常造型", image = "https://cdn.example.com/look.png", description = "白衬衫") => ({
  id,
  name,
  description,
  image_url: image,
})

describe("evaluateEpisodeShootPreflight", () => {
  it("reports ready when every beat resolves a scene master and a look image", () => {
    const scene = asset({
      id: "scene-1",
      kind: "scene",
      name: "开放式办公区",
      extra: { master_url: "https://cdn.example.com/scene.png", environment_prompt: "开放式办公区" },
    })
    const li = character("char-1", "李明", [look("ident-1")])
    const result = evaluateEpisodeShootPreflight({
      assets: [scene, li],
      beats: [beat({ sequence: 1, scene: "开放式办公区 - 夜", scene_id: "scene-1", character_ids: ["char-1"] })],
    })
    expect(result.ready).toBe(true)
    expect(result.canFix).toBe(false)
    expect(result.blocking).toEqual([])
    expect(result.sceneBindings).toEqual([])
    expect(result.sceneMasters).toEqual([])
    expect(result.lookGenerations).toEqual([])
  })

  it("matches office and bathroom beats to existing scene cards and requests masters", () => {
    const office = asset({ id: "scene-office", kind: "scene", name: "开放式办公区", extra: { environment_prompt: "开放式办公区，夜" } })
    const bathroom = asset({ id: "scene-bath", kind: "scene", name: "诡异洗手间", extra: { environment_prompt: "诡异洗手间" } })
    const li = character("char-li", "李明", [{ id: "ident-li", name: "李明 (日常/初始造型)", description: "白衬衫", image_url: "" }])
    const boss = character("char-boss", "王主管", [{ id: "ident-boss", name: "王主管 (日常/初始造型)", description: "深色西装", image_url: "" }])
    const staff = character("char-staff", "老员工A", [{ id: "ident-staff", name: "老员工A (日常/初始造型)", description: "灰色工装", image_url: "" }])
    const beats = [
      beat({ sequence: 1, scene: "开放式办公区 - 夜", scene_id: "scene-office", character_ids: ["char-li", "char-boss"] }),
      beat({ sequence: 2, scene: "办公区 - 夜", character_ids: ["char-boss", "char-li"] }),
      beat({ sequence: 6, scene: "洗手间门口 - 夜", character_ids: ["char-li"] }),
      beat({ sequence: 7, scene: "洗手间内 - 夜", character_ids: ["char-li"] }),
      beat({ sequence: 9, scene: "洗手间隔间内 - 夜", character_ids: ["char-li"] }),
      beat({ sequence: 11, scene: "办公区 - 夜", character_ids: ["char-boss", "char-staff"] }),
    ]
    const result = evaluateEpisodeShootPreflight({ beats, assets: [office, bathroom, li, boss, staff] })
    expect(result.ready).toBe(false)
    expect(result.canFix).toBe(true)
    expect(result.blocking).toEqual([])
    expect(result.sceneCreates).toEqual([])
    expect(result.sceneBindings).toHaveLength(5)
    expect(result.sceneBindings.every((item) => item.assetId === "scene-office" || item.assetId === "scene-bath")).toBe(true)
    expect(result.sceneMasters.map((item) => item.assetId).sort()).toEqual(["scene-bath", "scene-office"])
    expect(result.lookGenerations.map((item) => item.identityId).sort()).toEqual(["ident-boss", "ident-li", "ident-staff"])
    expect(result.lookGenerations.find((item) => item.identityId === "ident-li")?.sequences).toEqual([1, 2, 6, 7, 9])
    expect(result.lookBindings).toEqual([])
  })

  it("creates one scene card per normalized location and binds all matching beats", () => {
    const li = character("char-li", "李明", [look("ident-li")])
    const result = evaluateEpisodeShootPreflight({
      assets: [li],
      beats: [
        beat({ sequence: 1, scene: "天台 - 夜", character_ids: ["char-li"] }),
        beat({ sequence: 2, scene: "天台 - 日", character_ids: ["char-li"], action: "清晨独自坐在天台边缘" }),
      ],
    })
    expect(result.sceneCreates).toHaveLength(1)
    expect(result.sceneCreates[0]).toMatchObject({
      key: "天台",
      name: "天台",
      beats: [{ beatId: "beat-1", sequence: 1 }, { beatId: "beat-2", sequence: 2 }],
    })
    expect(result.sceneCreates[0].prompt).toContain("天台")
    expect(result.sceneMasters).toEqual([])
    expect(hasPaidShootPrep(result)).toBe(true)
  })

  it("blocks missing action, camera, speaker and unknown protagonist", () => {
    const result = evaluateEpisodeShootPreflight({
      assets: [],
      beats: [beat({ sequence: 1, action: "", camera: "", dialogue: "你来了", speaker: "" })],
    })
    expect(result.ready).toBe(false)
    expect(result.canFix).toBe(false)
    expect(result.blocking).toEqual(expect.arrayContaining([
      "Beat 1 缺少动作或视频提示词",
      "Beat 1 缺少运镜描述",
      "Beat 1 有对白但缺少说话人",
      "无法确定分集主角，请为镜头关联主角资产",
    ]))
  })

  it("honours a selected look and regenerates only when its image is missing", () => {
    const li = character("char-li", "李明", [
      look("ident-a", "日常造型"),
      look("ident-b", "雨夜造型", "https://cdn.example.com/rain.png"),
    ])
    const ready = evaluateEpisodeShootPreflight({
      assets: [asset({ id: "scene-1", kind: "scene", name: "办公区", extra: { master_url: "https://cdn.example.com/s.png" } }), li],
      beats: [beat({ sequence: 1, scene: "办公区", scene_id: "scene-1", character_ids: ["char-li"], character_look_ids: { "char-li": "ident-a" } })],
    })
    expect(ready.ready).toBe(true)

    const missing = evaluateEpisodeShootPreflight({
      assets: [
        asset({ id: "scene-1", kind: "scene", name: "办公区", extra: { master_url: "https://cdn.example.com/s.png" } }),
        character("char-li", "李明", [look("ident-a", "日常造型", ""), look("ident-b", "雨夜造型", "https://cdn.example.com/rain.png")]),
      ],
      beats: [beat({ sequence: 1, scene: "办公区", scene_id: "scene-1", character_ids: ["char-li"], character_look_ids: { "char-li": "ident-a" } })],
    })
    expect(missing.lookGenerations.map((item) => item.identityId)).toEqual(["ident-a"])

    const invalid = evaluateEpisodeShootPreflight({
      assets: [
        asset({ id: "scene-1", kind: "scene", name: "办公区", extra: { master_url: "https://cdn.example.com/s.png" } }),
        li,
      ],
      beats: [beat({ sequence: 1, scene: "办公区", scene_id: "scene-1", character_ids: ["char-li"], character_look_ids: { "char-li": "ident-gone" } })],
    })
    expect(invalid.blocking[0]).toContain("选择的造型无效")
  })

  it("locks a preferred look when multiple images exist and no style context matches", () => {
    const li = character("char-li", "李明", [
      look("ident-daily", "李明 (日常/初始造型)"),
      look("ident-work", "李明 (工作造型)", "https://cdn.example.com/work.png"),
    ])
    const result = evaluateEpisodeShootPreflight({
      assets: [
        asset({ id: "scene-1", kind: "scene", name: "办公区", extra: { master_url: "https://cdn.example.com/s.png" } }),
        li,
      ],
      beats: [beat({ sequence: 1, scene: "办公区", scene_id: "scene-1", character_ids: ["char-li"] })],
    })
    expect(result.lookBindings).toEqual([{ beatId: "beat-1", characterId: "char-li", identityId: "ident-daily" }])
    expect(result.lookGenerations).toEqual([])
    expect(result.ready).toBe(false)
    expect(result.canFix).toBe(true)
  })

  it("creates a default identity when the character has none, and blocks without a description", () => {
    const li = character("char-li", "李明")
    li.description = "26 岁程序员，短发，白衬衫"
    const derived = evaluateEpisodeShootPreflight({
      assets: [asset({ id: "scene-1", kind: "scene", name: "办公区", extra: { master_url: "https://cdn.example.com/s.png" } }), li],
      beats: [beat({ sequence: 1, scene: "办公区", scene_id: "scene-1", character_ids: ["char-li"] })],
    })
    expect(derived.lookCreates).toEqual([{
      assetId: "char-li",
      characterName: "李明",
      identityName: "李明 (日常造型)",
      description: "26 岁程序员，短发，白衬衫",
    }])

    const blocked = evaluateEpisodeShootPreflight({
      assets: [asset({ id: "scene-1", kind: "scene", name: "办公区", extra: { master_url: "https://cdn.example.com/s.png" } }), character("char-li", "李明")],
      beats: [beat({ sequence: 1, scene: "办公区", scene_id: "scene-1", character_ids: ["char-li"] })],
    })
    expect(blocked.canFix).toBe(false)
    expect(blocked.blocking[0]).toContain("还没有造型")
  })

  it("binds an available look when modern context has no era-matching look", () => {
    const li = character("char-li", "李明", [
      { id: "ident-work", name: "工作造型", description: "深色夹克", image_url: "https://cdn.example.com/work.png" },
    ])
    const result = evaluateEpisodeShootPreflight({
      assets: [
        asset({ id: "scene-1", kind: "scene", name: "办公区", extra: { master_url: "https://cdn.example.com/s.png" } }),
        li,
      ],
      beats: [beat({ sequence: 1, scene: "办公区", scene_id: "scene-1", character_ids: ["char-li"], action: "在现代办公室敲代码" })],
    })
    expect(result.blocking).toEqual([])
    expect(result.lookBindings).toEqual([{ beatId: "beat-1", characterId: "char-li", identityId: "ident-work" }])
    expect(result.lookGenerations).toEqual([])
    expect(result.ready).toBe(false)
    expect(result.canFix).toBe(true)
  })

  it("generates the era-matching identity instead of locking an unrelated look", () => {
    const li = character("char-li", "李明", [
      { id: "ident-modern", name: "现代办公室造型", description: "白衬衫", image_url: "" },
      look("ident-daily", "日常造型", "https://cdn.example.com/daily.png", "深色夹克"),
    ])
    const result = evaluateEpisodeShootPreflight({
      assets: [
        asset({ id: "scene-1", kind: "scene", name: "办公区", extra: { master_url: "https://cdn.example.com/s.png" } }),
        li,
      ],
      beats: [beat({ sequence: 1, scene: "办公区", scene_id: "scene-1", character_ids: ["char-li"], action: "在现代办公室敲代码" })],
    })
    expect(result.lookGenerations.map((item) => item.identityId)).toEqual(["ident-modern"])
    expect(result.lookBindings).toEqual([])
  })

  it("ignores a stale legacy look id and accepts the single valid look", () => {
    const li = character("char-li", "李明", [look("ident-1")])
    const result = evaluateEpisodeShootPreflight({
      assets: [
        asset({ id: "scene-1", kind: "scene", name: "办公区", extra: { master_url: "https://cdn.example.com/s.png" } }),
        li,
      ],
      beats: [beat({ sequence: 1, scene: "办公区", scene_id: "scene-1", character_ids: ["char-li"], character_look_id: "ident-gone" })],
    })
    expect(result.ready).toBe(true)
    expect(result.blocking).toEqual([])
  })

  it("summarises the work needed for the confirmation and the card", () => {
    const result = evaluateEpisodeShootPreflight({
      assets: [
        asset({ id: "scene-1", kind: "scene", name: "开放式办公区" }),
        character("char-li", "李明", [{ ...look("ident-li", "日常造型", ""), description: "白衬衫" }]),
      ],
      beats: [beat({ sequence: 1, scene: "开放式办公区 - 夜", character_ids: ["char-li"] })],
    })
    expect(episodeShootPrepLines(result)).toEqual([
      "自动匹配 1 个镜头的场景绑定。",
      "生成 1 张场景主视图：开放式办公区。",
      "生成 1 张角色造型图：李明。",
    ])
    expect(episodeShootPrepSummary(result)).toContain("还差 1 个镜头场景绑定、1 张场景主视图、1 张角色造型图")
    expect(hasPaidShootPrep(result)).toBe(true)
  })
})
