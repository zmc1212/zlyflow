import { Empty, Input, Tree } from "antd"
import { Search } from "lucide-react"
import { useEffect, useMemo, useState, type ReactNode } from "react"

export type EnterpriseTreePanelNode = {
  key: string
  /** 用于关键词检索与辅助描述，不直接渲染。 */
  label: string
  title: ReactNode
  children?: EnterpriseTreePanelNode[]
  selectable?: boolean
}

type Props = {
  nodes: EnterpriseTreePanelNode[]
  selectedKey: string
  onSelect: (key: string) => void
  title: string
  subtitle?: string
  searchPlaceholder?: string
  /** 受控搜索词（不传则由面板内部维护）；企业页用它同时过滤右侧列表。 */
  searchValue?: string
  onSearchChange?: (value: string) => void
  headerExtra?: ReactNode
  loading?: boolean
}

function filterNodes(nodes: EnterpriseTreePanelNode[], needle: string): EnterpriseTreePanelNode[] {
  const result: EnterpriseTreePanelNode[] = []
  for (const node of nodes) {
    const matched = node.label.toLocaleLowerCase("zh-CN").includes(needle)
    const children = node.children ? filterNodes(node.children, needle) : []
    if (!matched && children.length === 0) continue
    result.push({
      ...node,
      title: node.title,
      children: matched ? node.children : children.length ? children : undefined,
    })
  }
  return result
}

function collectExpandedKeys(nodes: EnterpriseTreePanelNode[], acc: string[] = []): string[] {
  for (const node of nodes) {
    if (node.children?.length) {
      acc.push(node.key)
      collectExpandedKeys(node.children, acc)
    }
  }
  return acc
}

/**
 * 管理后台的企业组织树面板：账号管理用它按企业（含下级）筛选账号，
 * 企业管理用它按层级浏览企业。视觉沿用管理设置的浅色卡片基线。
 */
export default function EnterpriseTreePanel({
  nodes,
  selectedKey,
  onSelect,
  title,
  subtitle,
  searchPlaceholder = "搜索企业",
  searchValue,
  onSearchChange,
  headerExtra,
  loading = false,
}: Props) {
  const [innerKeyword, setInnerKeyword] = useState("")
  const keyword = searchValue ?? innerKeyword
  const setKeyword = (value: string) => {
    if (searchValue === undefined) setInnerKeyword(value)
    onSearchChange?.(value)
  }
  const needle = keyword.trim().toLocaleLowerCase("zh-CN")
  const visibleNodes = useMemo(() => (needle ? filterNodes(nodes, needle) : nodes), [nodes, needle])
  const allExpandableKeys = useMemo(() => collectExpandedKeys(nodes), [nodes])
  const searchExpandableKeys = useMemo(() => collectExpandedKeys(visibleNodes), [visibleNodes])
  const [expandedKeys, setExpandedKeys] = useState<string[]>(allExpandableKeys)

  useEffect(() => {
    setExpandedKeys(needle ? searchExpandableKeys : allExpandableKeys)
  }, [needle, searchExpandableKeys, allExpandableKeys])

  return (
    <section className="rounded-2xl border border-black/[0.06] bg-white p-6 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold leading-6 text-[#111827]">{title}</h2>
          {subtitle ? <p className="mt-1 text-xs leading-5 text-[#6b7280]">{subtitle}</p> : null}
        </div>
        {headerExtra}
      </div>
      <Input
        allowClear
        value={keyword}
        onChange={(event) => setKeyword(event.target.value)}
        prefix={<Search size={13} className="text-[#9ca3af]" />}
        placeholder={searchPlaceholder}
        aria-label={searchPlaceholder}
      />
      <div className="mt-2 max-h-[420px] overflow-y-auto">
        {visibleNodes.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={<span className="text-xs text-[#9ca3af]">{needle ? "没有匹配的企业" : "暂无企业"}</span>}
            className="!my-6"
          />
        ) : (
          <Tree
            blockNode
            showLine={{ showLeafIcon: false }}
            treeData={visibleNodes}
            selectedKeys={[selectedKey]}
            expandedKeys={expandedKeys}
            onExpand={(keys) => setExpandedKeys(keys.map(String))}
            onSelect={(keys) => {
              const next = keys.map(String)[0]
              if (next) onSelect(next)
            }}
            className={[
              "[&_.ant-tree-treenode]:!items-center",
              "[&_.ant-tree-switcher]:!flex [&_.ant-tree-switcher]:!items-center",
              "[&_.ant-tree-node-content-wrapper]:!flex [&_.ant-tree-node-content-wrapper]:!min-h-[26px] [&_.ant-tree-node-content-wrapper]:!items-center",
              "[&_.ant-tree-title]:!flex [&_.ant-tree-title]:!min-w-0 [&_.ant-tree-title]:!items-center [&_.ant-tree-title]:!text-[13px]",
            ].join(" ")}
          />
        )}
        {loading ? <p className="py-2 text-center text-[11px] text-[#9ca3af]">正在读取企业架构…</p> : null}
      </div>
    </section>
  )
}
