import { REFERENCE_MAX_BYTES } from "./motion-transfer"

/** 「打斗镜头」工具卡固定走多参考路由：一张角色图也能开打，最多 9 张有序参考。 */
export const ACTION_SHOT_WORKFLOW = "minimax-h3-action-r2v"
export const ACTION_SHOT_MIN_REFERENCES = 1
export const ACTION_SHOT_MAX_REFERENCES = 9
export const ACTION_SHOT_MAX_BYTES = REFERENCE_MAX_BYTES

export type ActionShotAsset = {
  id: string
  file: File
  preview: string
}

export function actionShotReferenceError(file: Pick<File, "type" | "name" | "size">, index: number): string {
  const label = `参考图 ${index + 1}`
  if (!file.size) return `${label} 不能为空文件`
  if (file.size > ACTION_SHOT_MAX_BYTES) return `${label} 不能超过 50 MB`
  const extensionMatches = /\.(png|jpe?g|webp|bmp)$/i.test(file.name)
  const typeMatches = !file.type || file.type === "application/octet-stream" || file.type.startsWith("image/")
  return extensionMatches && typeMatches ? "" : `${label} 必须是 PNG / JPG / WebP 图片`
}

/** 后端 R2V 按上传顺序解析 <Picture n>；下标从 0 开始，编号从 1 开始。 */
export function actionShotPictureToken(index: number): string {
  return `<Picture ${index + 1}>`
}

/** 在提示词光标处插入 <Picture n>，与生成页的快捷标签保持一致的空格处理。 */
export function insertActionShotPicture(prompt: string, index: number, cursor?: number | null): { prompt: string; cursor: number } {
  const token = actionShotPictureToken(index)
  const at = typeof cursor === "number" && Number.isFinite(cursor) ? Math.max(0, Math.min(cursor, prompt.length)) : prompt.length
  const before = prompt.slice(0, at)
  const after = prompt.slice(at)
  const padded = `${before && !/\s$/.test(before) ? " " : ""}${token}${after && !/^\s/.test(after) ? " " : ""}`
  return { prompt: `${before}${padded}${after}`, cursor: at + padded.length }
}

/** 提示词必须引用参考图，否则远端构图阶段会以 missing <Picture n> 整单失败。 */
export function missingActionShotPicture(prompt: string, referenceCount: number): string {
  if (!referenceCount) return "请先添加至少 1 张参考图"
  const referenced = [...prompt.matchAll(/<Picture\s+(\d+)>/gi)].some((match) => {
    const index = Number(match[1])
    return index >= 1 && index <= referenceCount
  })
  return referenced ? "" : "提示词里需要引用参考图，例如 <Picture 1>"
}

/** 「开始生成」按钮的禁用原因；为空表示可以提交，与 ready 判定保持同源。 */
export function actionShotSubmitBlockReason(input: {
  referenceCount: number
  prompt: string
  pictureHint: string
  workflowLoaded: boolean
  submitting: boolean
}): string {
  if (input.submitting) return "正在提交…"
  if (!input.workflowLoaded) return "正在读取打斗镜头能力"
  if (input.referenceCount < ACTION_SHOT_MIN_REFERENCES) return "先添加参考图（至少 1 张），才能开始生成"
  if (!input.prompt.trim()) return "写一句打斗动作提示词，才能开始生成"
  return input.pictureHint
}

/** 一键填入的打斗结构模板：主体关系 → 动作节拍 → 镜头与打击感。 */
export function actionShotPromptTemplate(referenceCount: number): string {
  const count = Math.max(ACTION_SHOT_MIN_REFERENCES, referenceCount)
  const fighters = count === 1
    ? "<Picture 1> 中的角色独自练习连招"
    : "<Picture 1> 与 <Picture 2> 近身格斗"
  const scene = count >= 3 ? "，场景与光线参考 <Picture 3>" : ""
  return `${fighters}${scene}：先出拳压制，再侧身闪避反击，最后以重击收势。`
    + "镜头跟随主体，短促推拉，火光与碎屑飞溅，打击感强；动作连贯，不要慢动作。"
}
