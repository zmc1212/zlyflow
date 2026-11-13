export type CloudVideoSwitchItem = {
  provider_key: string
  label: string
  enabled: boolean
}

/**
 * 切换标签用的短名称：去掉“（火山方舟）”这类括号补充，避免分段控件被长名称撑开。
 * 去掉后为空时回退到原始名称。
 */
export function cloudVideoShortLabel(label: string) {
  const short = (label || "").split(/[（(]/)[0]?.trim() ?? ""
  return short || label
}

/**
 * 解析当前应展示的厂商：
 * 1. 用户已选中的厂商仍存在时保持选中，避免保存后刷新跳回第一家；
 * 2. 首次进入优先落在已启用的厂商；
 * 3. 都未启用时回退到清单第一家。
 */
export function resolveCloudVideoProvider(items: CloudVideoSwitchItem[], activeKey: string) {
  if (activeKey && items.some((item) => item.provider_key === activeKey)) return activeKey
  return items.find((item) => item.enabled)?.provider_key ?? items[0]?.provider_key ?? ""
}
