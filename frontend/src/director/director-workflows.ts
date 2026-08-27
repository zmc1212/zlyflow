export const DEFAULT_DIRECTOR_WORKFLOW_FAMILY = "official_h3"

export type DirectorRoute = "t2v" | "i2v" | "r2v"

export type DirectorWorkflowFamily = {
  id: string
  label: string
  order: number
  routes: Partial<Record<DirectorRoute, string>>
}

export type DirectorModeSummary = {
  id: string
  name: string
  media_type?: string
  reference_mode?: string
  min_references?: number
  max_references?: number
  catalog_group?: string
  catalog_group_label?: string
  catalog_group_order?: number
}

export const FALLBACK_DIRECTOR_WORKFLOW_FAMILIES: DirectorWorkflowFamily[] = [
  {
    id: "lightx2v",
    label: "LightX2V",
    order: 10,
    routes: {
      t2v: "minimax-h3-lightx2v-t2v",
      i2v: "minimax-h3-lightx2v-i2v",
      r2v: "minimax-h3-lightx2v-r2v",
    },
  },
  {
    id: "dual_accel",
    label: "八步双加速",
    order: 15,
    routes: {
      t2v: "minimax-h3-dual-accel-t2v",
      i2v: "minimax-h3-dual-accel-i2v",
      r2v: "minimax-h3-dual-accel-r2v",
    },
  },
  {
    id: "official_h3",
    label: "MiniMax H3",
    order: 20,
    routes: {
      t2v: "minimax-h3-t2v",
      i2v: "minimax-h3-i2v",
      r2v: "minimax-h3-r2v",
    },
  },
]

export function directorRouteKind(subjectCount: number, hasFirst: boolean, hasLast: boolean): DirectorRoute {
  if (subjectCount > 0) return "r2v"
  if (hasFirst || hasLast) return "i2v"
  return "t2v"
}

export function directorRouteKey(mode: DirectorModeSummary): DirectorRoute | "standalone" | null {
  if (mode.media_type && mode.media_type !== "video") return null
  if (mode.reference_mode === "none") return "t2v"
  if (mode.reference_mode === "keyframes") return "i2v"
  if (mode.reference_mode === "collection") {
    if ((mode.min_references ?? 0) === 0) return "standalone"
    if ((mode.max_references ?? 0) >= 3) return "r2v"
  }
  return null
}

export function directorWorkflowFamilies(modes: DirectorModeSummary[]): DirectorWorkflowFamily[] {
  const grouped = new Map<string, DirectorWorkflowFamily>()
  const standalones: DirectorWorkflowFamily[] = []
  for (const mode of modes) {
    const route = directorRouteKey(mode)
    if (!route) continue
    if (route === "standalone") {
      standalones.push({
        id: mode.id,
        label: mode.name,
        order: mode.catalog_group_order ?? 100,
        routes: { t2v: mode.id, i2v: mode.id, r2v: mode.id },
      })
      continue
    }
    const groupId = mode.catalog_group || mode.id
    const existing = grouped.get(groupId) || {
      id: groupId,
      label: mode.catalog_group_label || mode.name,
      order: mode.catalog_group_order ?? 100,
      routes: {},
    }
    existing.routes[route] = mode.id
    grouped.set(groupId, existing)
  }
  const families = [...grouped.values(), ...standalones]
  if (!families.length) return FALLBACK_DIRECTOR_WORKFLOW_FAMILIES
  return families.sort((left, right) => left.order - right.order || left.label.localeCompare(right.label, "zh-CN"))
}

export function resolveDirectorWorkflow(
  family: string | null | undefined,
  route: DirectorRoute,
  families: DirectorWorkflowFamily[] = FALLBACK_DIRECTOR_WORKFLOW_FAMILIES,
): string {
  const chosen = families.find((item) => item.id === family) || families.find((item) => item.id === DEFAULT_DIRECTOR_WORKFLOW_FAMILY)
  const routes = chosen?.routes || {}
  return routes[route] || routes.t2v || "minimax-h3-t2v"
}

export function isDirectorR2V(workflowId: string, route?: string | null): boolean {
  return route === "r2v" || workflowId.endsWith("-r2v")
}
