import type { NodeTypes } from "@xyflow/react"
import { describe, expect, it } from "vitest"
import { baseNodeTypes, buildNodeTypes } from "./node-registry"

describe("canvas node registry", () => {
  it("登记全部通用节点类型", () => {
    expect(Object.keys(baseNodeTypes).sort()).toEqual([
      "artboard", "generator", "image", "text", "unknown", "video",
    ])
  })

  it("不传域节点时返回同一批通用节点", () => {
    const types = buildNodeTypes()
    for (const key of Object.keys(baseNodeTypes)) {
      expect(types[key]).toBe(baseNodeTypes[key])
    }
  })

  it("以通用节点为底叠加宿主域专属节点", () => {
    const domain: NodeTypes = { assetGroup: () => null, audio: () => null }
    const types = buildNodeTypes(domain)
    expect(types.image).toBe(baseNodeTypes.image)
    expect(types.assetGroup).toBe(domain.assetGroup)
    expect(types.audio).toBe(domain.audio)
  })

  it("同名域节点可覆盖通用节点", () => {
    const override = () => null
    const types = buildNodeTypes({ image: override })
    expect(types.image).toBe(override)
    expect(types.text).toBe(baseNodeTypes.text)
  })
})
