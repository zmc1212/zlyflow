import { describe, expect, it } from "vitest"
import type { Director2Asset } from "../../api"
import {
  firstCharacterLookImageUrl,
  getAssetDisplayAvatar,
  identityLookEnqueueBlocker,
  type AssetIdentity,
} from "./shared"

function character(extra: Record<string, unknown>, imageUrl: string | null = null): Director2Asset {
  return {
    id: "ast-1",
    project_id: "proj-1",
    kind: "character",
    name: "吴耐",
    role: "主角",
    description: null,
    visual_prompt: null,
    image_url: imageUrl,
    voice_id: null,
    extra,
    created_at: "",
    updated_at: "",
  }
}

describe("character display avatar", () => {
  it("prefers the first look sheet over an old avatar", () => {
    const ast = character({
      avatar_url: "https://cdn.example/avatar.jpg",
      identities: [
        { id: "look-1", image_url: "https://cdn.example/sheet.png" },
        { id: "look-2", image_url: "https://cdn.example/sheet-2.png" },
      ],
    })
    expect(firstCharacterLookImageUrl(ast)).toBe("https://cdn.example/sheet.png")
    expect(getAssetDisplayAvatar(ast)).toBe("https://cdn.example/sheet.png")
  })

  it("falls back to avatar when no look sheet exists", () => {
    const ast = character({ avatar_url: "https://cdn.example/avatar.jpg", identities: [] })
    expect(getAssetDisplayAvatar(ast)).toBe("https://cdn.example/avatar.jpg")
  })
})

describe("identity look enqueue", () => {
  it("allows generating a look without an avatar when costume is filled", () => {
    const ident: AssetIdentity = { id: "look-1", name: "日常", description: "脏白背心" }
    expect(identityLookEnqueueBlocker(character({}), ident)).toBe("")
    expect(identityLookEnqueueBlocker(character({}), ident)).not.toContain("头像")
  })

  it("blocks when there is no costume and no source photos", () => {
    const ident: AssetIdentity = { id: "look-1", name: "日常" }
    expect(identityLookEnqueueBlocker(character({}), ident)).toContain("外观描述")
  })

  it("allows empty costume when source photos exist", () => {
    const ident: AssetIdentity = { id: "look-1", name: "日常" }
    expect(
      identityLookEnqueueBlocker(
        character({ source_references: [{ id: "ref-1", url: "https://cdn.example/face.jpg" }] }),
        ident,
      ),
    ).toBe("")
  })
})
