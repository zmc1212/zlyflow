import { describe, expect, it } from "vitest"
import type { User } from "../api"
import type { Enterprise } from "../credits/credits"
import {
  accountScopeKey,
  buildEnterpriseSelectTree,
  buildEnterpriseTree,
  collectSubtreeIds,
  enterprisePath,
  filterAccounts,
  filterEnterprises,
  parseAccountScopeKey,
  rollupMemberCounts,
} from "./enterprise-tree"

function enterprise(overrides: Partial<Enterprise> & Pick<Enterprise, "id" | "name">): Enterprise {
  return {
    status: "active",
    member_count: 0,
    balance: 0,
    total_recharged: 0,
    total_consumed: 0,
    created_at: "2026-11-01T00:00:00",
    updated_at: "2026-11-01T00:00:00",
    ...overrides,
  }
}

function account(overrides: Partial<User> & Pick<User, "id" | "username" | "display_name">): User {
  return {
    role: "employee",
    is_active: true,
    must_change_password: false,
    created_at: "2026-11-01T00:00:00",
    updated_at: "2026-11-01T00:00:00",
    ...overrides,
  }
}

const enterprises: Enterprise[] = [
  enterprise({ id: "group", name: "星河集团", member_count: 1 }),
  enterprise({ id: "film", name: "星河影业", parent_id: "group", member_count: 2 }),
  enterprise({ id: "ads", name: "星河广告", parent_id: "group", member_count: 3 }),
  enterprise({ id: "studio", name: "影业制作部", parent_id: "film", member_count: 4 }),
  enterprise({ id: "solo", name: "独立工作室", member_count: 5 }),
]

describe("buildEnterpriseTree", () => {
  it("nests children under their parent and sorts each level by name", () => {
    const tree = buildEnterpriseTree(enterprises)
    expect(tree.map((node) => node.enterprise.id)).toEqual(["solo", "group"])
    expect(tree[1].children.map((node) => node.enterprise.id)).toEqual(["ads", "film"])
    expect(tree[1].children[1].children.map((node) => node.enterprise.id)).toEqual(["studio"])
  })

  it("treats orphans and cyclic parents as top-level instead of recursing forever", () => {
    const broken: Enterprise[] = [
      enterprise({ id: "a", name: "甲", parent_id: "b" }),
      enterprise({ id: "b", name: "乙", parent_id: "a" }),
      enterprise({ id: "c", name: "丙", parent_id: "missing" }),
    ]
    const tree = buildEnterpriseTree(broken)
    expect(tree.map((node) => node.enterprise.id).sort()).toEqual(["a", "b", "c"])
    expect(tree.every((node) => node.children.length === 0)).toBe(true)
  })
})

describe("collectSubtreeIds", () => {
  it("includes the selected enterprise and every descendant", () => {
    expect([...collectSubtreeIds(enterprises, "group")].sort()).toEqual(["ads", "film", "group", "studio"])
    expect([...collectSubtreeIds(enterprises, "film")].sort()).toEqual(["film", "studio"])
  })
})

describe("rollupMemberCounts", () => {
  it("adds descendant members to every ancestor", () => {
    const { direct, total } = rollupMemberCounts(enterprises)
    expect(direct.get("film")).toBe(2)
    expect(total.get("film")).toBe(6)
    expect(total.get("group")).toBe(10)
    expect(total.get("solo")).toBe(5)
  })
})

describe("enterprisePath", () => {
  it("returns the readable path for a deep enterprise", () => {
    expect(enterprisePath(enterprises, "studio")).toBe("星河集团 / 星河影业 / 影业制作部")
    expect(enterprisePath(enterprises, "solo")).toBe("独立工作室")
  })
})

describe("filterAccounts", () => {
  const accounts = [
    account({ id: "u1", username: "zhang", display_name: "张三", enterprise_id: "studio", enterprise_name: "影业制作部" }),
    account({ id: "u2", username: "li", display_name: "李四", enterprise_id: "ads", enterprise_name: "星河广告" }),
    account({ id: "u3", username: "wang", display_name: "王五" }),
  ]

  it("filters through the whole subtree of the selected enterprise", () => {
    expect(filterAccounts(accounts, enterprises, { kind: "enterprise", id: "group" }).map((item) => item.id))
      .toEqual(["u1", "u2"])
    expect(filterAccounts(accounts, enterprises, { kind: "enterprise", id: "film" }).map((item) => item.id))
      .toEqual(["u1"])
  })

  it("separates unassigned platform accounts and matches keywords", () => {
    expect(filterAccounts(accounts, enterprises, { kind: "unassigned" }).map((item) => item.id)).toEqual(["u3"])
    expect(filterAccounts(accounts, enterprises, { kind: "all" }, "星河").map((item) => item.id)).toEqual(["u1", "u2"])
    expect(filterAccounts(accounts, enterprises, { kind: "all" }, "wang").map((item) => item.id)).toEqual(["u3"])
    expect(filterAccounts(accounts, enterprises, { kind: "all" }, "平台内部").map((item) => item.id)).toEqual(["u3"])
  })
})

describe("filterEnterprises", () => {
  it("keeps the subtree and matches name or code", () => {
    expect(filterEnterprises(enterprises, { kind: "enterprise", id: "film" }).map((item) => item.id))
      .toEqual(["film", "studio"])
    expect(filterEnterprises(enterprises, { kind: "all" }, "广告").map((item) => item.id)).toEqual(["ads"])
  })

  it("orders rows depth-first so a parent always precedes its children", () => {
    expect(filterEnterprises(enterprises, { kind: "all" }).map((item) => item.id))
      .toEqual(["solo", "group", "ads", "film", "studio"])
  })
})

describe("buildEnterpriseSelectTree", () => {
  it("disables inactive enterprises and excluded ids", () => {
    const withDisabled = [
      ...enterprises,
      enterprise({ id: "old", name: "停用公司", status: "disabled" }),
    ]
    const tree = buildEnterpriseSelectTree(withDisabled, { excludeIds: new Set(["film"]) })
    const group = tree.find((node) => node.value === "group")
    const film = group?.children?.find((node) => node.value === "film")
    expect(film?.disabled).toBe(true)
    expect(tree.find((node) => node.value === "old")?.disabled).toBe(true)
  })
})

describe("scope keys", () => {
  it("round-trips enterprise keys and falls back to all", () => {
    expect(parseAccountScopeKey(accountScopeKey({ kind: "enterprise", id: "group" }))).toEqual({ kind: "enterprise", id: "group" })
    expect(parseAccountScopeKey(accountScopeKey({ kind: "unassigned" }))).toEqual({ kind: "unassigned" })
    expect(parseAccountScopeKey("unknown")).toEqual({ kind: "all" })
  })
})
