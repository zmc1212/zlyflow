// Asset selection is resolved exclusively by the backend.
export function summarizeWorkshopBlocks(blocked: Array<{reason: string}>) {
  const counts = new Map<string, number>()
  for (const item of blocked) counts.set(item.reason, (counts.get(item.reason) || 0) + 1)
  return [...counts].map(([reason, count]) => `${count} 组：${reason}`).join("；")
}
