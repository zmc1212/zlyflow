import { useEffect, useRef, useState } from "react"

/**
 * 画布文本框的本地草稿。
 *
 * 节点的 `data` 经 @xyflow/react 的批处理队列回写，比 DOM 的 input 事件晚一步。
 * 如果把 `value` 直接绑到节点数据，输入法组合期间会先以旧值重渲染并重置
 * textarea，浏览器随即结束组合输入，拼音就被当成普通字母提交。
 *
 * 因此输入框用本地草稿即时回显，节点数据仍按每次输入同步；只有不在编辑中时
 * 才接受外部值（切换节点、工作流换默认提示词、撤销/重做、插入参考图标记）。
 */
export function useCanvasTextDraft(externalValue: string, commit: (value: string) => void) {
  const [draft, setDraft] = useState(externalValue)
  const draftRef = useRef(externalValue)
  const editingRef = useRef(false)
  const composingRef = useRef(false)

  useEffect(() => {
    if (editingRef.current || composingRef.current) return
    if (externalValue === draftRef.current) return
    draftRef.current = externalValue
    setDraft(externalValue)
  }, [externalValue])

  const change = (value: string) => {
    draftRef.current = value
    setDraft(value)
    commit(value)
  }

  return {
    value: draft,
    onChange: change,
    onFocus: () => { editingRef.current = true },
    onBlur: () => { editingRef.current = false },
    onCompositionStart: () => { composingRef.current = true },
    onCompositionEnd: (value: string) => {
      composingRef.current = false
      change(value)
    },
  }
}