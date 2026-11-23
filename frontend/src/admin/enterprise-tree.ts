import type { User } from "../api"
import type { Enterprise } from "../credits/credits"

// 企业层级（集团-子公司）在前端的统一建模：树构建、范围过滤与下拉选项。
// 后端 enterprises.parent_id 可为空；脏数据形成环时在此降级为多个顶级企业，保证界面不递归死循环。

export const ACCOUNT_SCOPE_ALL = "all"
export const ACCOUNT_SCOPE_UNASSIGNED = "unassigned"
const ENTERPRISE_SCOPE_PREFIX = "ent:"
const ENTERPRISE_GROUP_KEY = "group:enterprises"

export type AccountScope =
  | { kind: "all" }
  | { kind: "unassigned" }
  | { kind: "enterprise"; id: string }

export type EnterpriseTreeNode = {
  enterprise: Enterprise
  children: EnterpriseTreeNode[]
}

export type TreeSelectNode = {
  value: string
  title: string
  disabled?: boolean
  children?: TreeSelectNode[]
}

export function enterpriseScopeKey(id: string): string {
  return `${ENTERPRISE_SCOPE_PREFIX}${id}`
}

export function accountScopeKey(scope: AccountScope): string {
  if (scope.kind === "enterprise") return enterpriseScopeKey(scope.id)
  return scope.kind
}

export function parseAccountScopeKey(key: string): AccountScope {
  if (key.startsWith(ENTERPRISE_SCOPE_PREFIX)) {
    return { kind: "enterprise", id: key.slice(ENTERPRISE_SCOPE_PREFIX.length) }
  }
  return key === ACCOUNT_SCOPE_UNASSIGNED ? { kind: "unassigned" } : { kind: "all" }
}

export const ENTERPRISE_GROUP_NODE_KEY = ENTERPRISE_GROUP_KEY

function compareName(a: Enterprise, b: Enterprise): number {
  return a.name.localeCompare(b.name, "zh-Hans-CN", { numeric: true })
}

/**
 * 构建企业树。`parent_id` 仅当上级存在且整条祖先链无环时才生效，
 * 否则该企业按顶级企业处理，避免脏数据把树渲染成死循环。
 */
export function buildEnterpriseTree(enterprises: Enterprise[]): EnterpriseTreeNode[] {
  const byId = new Map(enterprises.map((enterprise) => [enterprise.id, enterprise]))
  const declaredParent = (id: string): string | null => {
    const parentId = byId.get(id)?.parent_id
    return parentId && parentId !== id && byId.has(parentId) ? parentId : null
  }
  const safeParent = (id: string): string | null => {
    const parentId = declaredParent(id)
    let cursor = parentId
    const seen = new Set<string>([id])
    while (cursor) {
      if (seen.has(cursor)) return null
      seen.add(cursor)
      cursor = declaredParent(cursor)
    }
    return parentId
  }

  const nodes = new Map<string, EnterpriseTreeNode>()
  for (const enterprise of enterprises) nodes.set(enterprise.id, { enterprise, children: [] })
  const roots: EnterpriseTreeNode[] = []
  for (const node of nodes.values()) {
    const parentId = safeParent(node.enterprise.id)
    const parent = parentId ? nodes.get(parentId) : undefined
    if (parent) parent.children.push(node)
    else roots.push(node)
  }
  const sortLevel = (level: EnterpriseTreeNode[]) => {
    level.sort((a, b) => compareName(a.enterprise, b.enterprise))
    for (const node of level) sortLevel(node.children)
  }
  sortLevel(roots)
  return roots
}

/** 选中企业（含所有下级企业）的 ID 集合；用于账号/企业列表按层级过滤。 */
export function collectSubtreeIds(enterprises: Enterprise[], rootId: string): Set<string> {
  const ids = new Set<string>([rootId])
  let changed = true
  while (changed) {
    changed = false
    for (const enterprise of enterprises) {
      if (enterprise.parent_id && ids.has(enterprise.parent_id) && !ids.has(enterprise.id)) {
        ids.add(enterprise.id)
        changed = true
      }
    }
  }
  return ids
}

/** 每个企业的直属成员数与含下级成员数。 */
export function rollupMemberCounts(enterprises: Enterprise[]): { direct: Map<string, number>; total: Map<string, number> } {
  const direct = new Map(enterprises.map((enterprise) => [enterprise.id, enterprise.member_count ?? 0]))
  const total = new Map(direct)
  const byId = new Map(enterprises.map((enterprise) => [enterprise.id, enterprise]))
  for (const enterprise of enterprises) {
    const own = direct.get(enterprise.id) ?? 0
    if (!own) continue
    let cursor = enterprise.parent_id ?? null
    const seen = new Set<string>([enterprise.id])
    while (cursor && !seen.has(cursor)) {
      seen.add(cursor)
      total.set(cursor, (total.get(cursor) ?? 0) + own)
      cursor = byId.get(cursor)?.parent_id ?? null
    }
  }
  return { direct, total }
}

/** 企业全路径（集团 / 子公司 / 孙公司）；上级缺失时只返回自身名称。 */
export function enterprisePath(enterprises: Enterprise[], enterpriseId: string): string {
  const byId = new Map(enterprises.map((enterprise) => [enterprise.id, enterprise]))
  const names: string[] = []
  const seen = new Set<string>()
  let cursor: string | null = enterpriseId
  while (cursor && !seen.has(cursor)) {
    seen.add(cursor)
    const enterprise = byId.get(cursor)
    if (!enterprise) break
    names.unshift(enterprise.name)
    cursor = enterprise.parent_id ?? null
  }
  return names.join(" / ")
}

/** 账号列表按「企业范围 + 关键词」过滤；企业范围包含所有下级企业。 */
export function filterAccounts(
  accounts: User[],
  enterprises: Enterprise[],
  scope: AccountScope,
  keyword = "",
): User[] {
  const scopedIds = scope.kind === "enterprise" ? collectSubtreeIds(enterprises, scope.id) : null
  const needle = keyword.trim().toLocaleLowerCase("zh-CN")
  return accounts.filter((account) => {
    if (scope.kind === "unassigned" && account.enterprise_id) return false
    if (scopedIds && (!account.enterprise_id || !scopedIds.has(account.enterprise_id))) return false
    if (!needle) return true
    const path = account.enterprise_id ? enterprisePath(enterprises, account.enterprise_id) : "平台内部"
    return [account.display_name, account.username, account.email, account.enterprise_name, path]
      .some((field) => (field ?? "").toLocaleLowerCase("zh-CN").includes(needle))
  })
}

/** 企业树选中范围内的企业（用于企业管理列表过滤）；结果按层级先序排列，上级在子级之前。 */
export function filterEnterprises(
  enterprises: Enterprise[],
  scope: AccountScope,
  keyword = "",
): Enterprise[] {
  if (scope.kind === "unassigned") return []
  const scopedIds = scope.kind === "enterprise" ? collectSubtreeIds(enterprises, scope.id) : null
  const needle = keyword.trim().toLocaleLowerCase("zh-CN")
  const matches = (enterprise: Enterprise) => {
    if (scopedIds && !scopedIds.has(enterprise.id)) return false
    if (!needle) return true
    return [enterprise.name, enterprise.code, enterprise.contact_name]
      .some((field) => (field ?? "").toLocaleLowerCase("zh-CN").includes(needle))
  }
  const ordered: Enterprise[] = []
  const visited = new Set<string>()
  const walk = (nodes: EnterpriseTreeNode[]) => {
    for (const node of nodes) {
      if (visited.has(node.enterprise.id)) continue
      visited.add(node.enterprise.id)
      if (matches(node.enterprise)) ordered.push(node.enterprise)
      walk(node.children)
    }
  }
  walk(buildEnterpriseTree(enterprises))
  // 脏数据导致未进入树的节点也要显示，避免企业列表静默丢行。
  for (const enterprise of enterprises) {
    if (!visited.has(enterprise.id) && matches(enterprise)) ordered.push(enterprise)
  }
  return ordered
}

/**
 * 树形选择器数据：保留层级，停用企业禁止选择；
 * `excludeIds` 用于编辑企业时排除自身与下级，避免形成循环。
 */export function buildEnterpriseSelectTree(
  enterprises: Enterprise[],
  options: { excludeIds?: Set<string> } = {},
): TreeSelectNode[] {
  const excluded = options.excludeIds ?? new Set<string>()
  const convert = (node: EnterpriseTreeNode): TreeSelectNode => ({
    value: node.enterprise.id,
    title: node.enterprise.status === "active"
      ? node.enterprise.name
      : `${node.enterprise.name}（已停用）`,
    disabled: excluded.has(node.enterprise.id) || node.enterprise.status !== "active",
    children: node.children.length ? node.children.map(convert) : undefined,
  })
  return buildEnterpriseTree(enterprises).map(convert)
}

/**
 * 企业选择器下拉的弹层类名：收起叶子节点前的空箭头占位，
 * 避免选项文字被推离下拉面板左缘（见 index.css 中的 `.studio-enterprise-tree-popup`）。
 */
export const ENTERPRISE_SELECT_POPUP_CLASS = { popup: { root: "studio-enterprise-tree-popup" } }