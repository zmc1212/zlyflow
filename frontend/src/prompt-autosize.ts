// 提示词输入框统一的自适应高度：从各页面需要的起始行数起步，随内容增长；
// 到 PROMPT_INPUT_MAX_ROWS 封顶后改为框内滚动，避免长提示词把面板顶满、把提交按钮挤出视口。
// 生成工作台的输入面板（App.tsx）也用同一个封顶行数，保证全站手感一致。
export const PROMPT_INPUT_MAX_ROWS = 10

export function promptAutoSize(minRows: number): { minRows: number; maxRows: number } {
  return { minRows, maxRows: Math.max(minRows, PROMPT_INPUT_MAX_ROWS) }
}
