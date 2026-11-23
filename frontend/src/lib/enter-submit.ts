/**
 * 提示词输入框的回车提交判定。
 *
 * 「点击生成」的输入区统一约定：Enter 直接生成，Shift / Alt + Enter 换行，
 * Ctrl / ⌘ + Enter 同样生成。输入法组合期间不触发——部分浏览器确认拼音的
 * 回车 keydown 已结束组合（isComposing 为 false），需再以 keyCode 229 兜底，
 * 避免选字时误提交。
 */
export function isSubmitEnter(event: {
  key: string
  shiftKey: boolean
  altKey: boolean
  nativeEvent: KeyboardEvent
}): boolean {
  return event.key === "Enter" && !event.shiftKey && !event.altKey
    && !event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229
}
