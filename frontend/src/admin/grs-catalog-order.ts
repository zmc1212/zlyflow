export type CatalogOrderRow = { workflow_id: string; sort_order: number }

/** 把 fromId 行移到 toId 行位置，并按新顺序重新编号 sort_order（步长 10，给后续导入留空隙）。 */
export function reorderCatalogRows<T extends CatalogOrderRow>(rows: T[], fromId: string, toId: string): T[] {
  const from = rows.findIndex((item) => item.workflow_id === fromId)
  const to = rows.findIndex((item) => item.workflow_id === toId)
  if (from < 0 || to < 0 || from === to) return rows
  const next = [...rows]
  const [moved] = next.splice(from, 1)
  next.splice(to, 0, moved)
  return next.map((item, index) => ({ ...item, sort_order: (index + 1) * 10 }))
}
