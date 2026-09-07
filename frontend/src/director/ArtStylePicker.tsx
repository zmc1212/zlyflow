import { Button, Drawer, Empty, Input, Select } from "antd"
import { useMemo, useState, type ReactNode } from "react"
import { featuredArtStyles } from "./types"
import { artStylePreviewUrl, type DirectorArtStyle, type DirectorArtStyleCategory } from "./recipe-model"

export function ArtStyleCover({
  style,
  className = "director-style-cover",
  showPlaceholder = true,
}: {
  style: { id: string; name_zh?: string; name?: string; imageUrl?: string | null }
  className?: string
  showPlaceholder?: boolean
}) {
  const [failed, setFailed] = useState(false)
  if (failed) {
    return showPlaceholder ? <div className={`${className} is-empty`.trim()}>无预览</div> : null
  }
  return (
    <img
      src={artStylePreviewUrl(style)}
      alt={style.name_zh || style.name || ""}
      className={className}
      onError={() => setFailed(true)}
    />
  )
}

export function ArtStyleCard({
  style,
  active,
  disabled,
  onSelect,
}: {
  style: DirectorArtStyle
  active?: boolean
  disabled?: boolean
  onSelect: (style: DirectorArtStyle) => void
}) {
  return (
    <button
      key={style.id}
      type="button"
      disabled={disabled}
      className={`director-style-card${active ? " is-active" : ""}`}
      onClick={() => onSelect(style)}
    >
      <ArtStyleCover style={style} />
      <span className="director-style-copy">
        <strong>{style.name_zh}</strong>
        <span>{style.category_name_zh} · {style.name_en}</span>
        <em>{style.description}</em>
      </span>
    </button>
  )
}

export function ArtStyleCatalogPicker({
  styles,
  categories,
  value,
  disabled,
  onChange,
}: {
  styles: DirectorArtStyle[]
  categories: DirectorArtStyleCategory[]
  value?: string
  disabled?: boolean
  onChange: (style: DirectorArtStyle) => void
}) {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [category, setCategory] = useState<string | undefined>()
  const [keyword, setKeyword] = useState("")
  const recommended = useMemo(() => featuredArtStyles(styles), [styles])
  const filtered = useMemo(() => {
    const needle = keyword.trim().toLowerCase()
    return styles.filter((style) => {
      if (category && style.category !== category) return false
      if (!needle) return true
      return [style.name_zh, style.name_en, style.description, style.category_name_zh, ...(style.keywords || [])]
        .join(" ")
        .toLowerCase()
        .includes(needle)
    })
  }, [styles, category, keyword])
  const current = styles.find((item) => item.id === value)

  return (
    <div className="director-recipe-form">
      <div className="director-style-toolbar">
        <p>推荐 6 种常用画风。其余可按分类搜索，或浏览全部 {styles.length || 34} 条。</p>
        <Button disabled={disabled} onClick={() => setDrawerOpen(true)}>浏览全部</Button>
      </div>
      <div className="director-style-grid">
        {recommended.map((style) => (
          <ArtStyleCard
            key={style.id}
            style={style}
            active={value === style.id}
            disabled={disabled}
            onSelect={onChange}
          />
        ))}
      </div>
      {current && !recommended.some((item) => item.id === current.id) ? (
        <p className="director-output-hint">当前画风：{current.name_zh}</p>
      ) : null}
      <Drawer title="全部画风" open={drawerOpen} onClose={() => setDrawerOpen(false)} size="560">
        <div className="director-style-filters">
          <Select
            allowClear
            placeholder="分类"
            value={category}
            options={categories.map((item) => ({ value: item.id, label: item.name_zh }))}
            onChange={(next?: string) => setCategory(next)}
          />
          <Input
            allowClear
            placeholder="搜索画风"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
          />
        </div>
        <div className="director-style-grid">
          {filtered.map((style) => (
            <ArtStyleCard
              key={style.id}
              style={style}
              active={value === style.id}
              disabled={disabled}
              onSelect={(next) => {
                onChange(next)
                setDrawerOpen(false)
              }}
            />
          ))}
          {!filtered.length && <Empty description="没有匹配的画风" />}
        </div>
      </Drawer>
    </div>
  )
}

export function ArtStyleCompactField({
  styles,
  categories,
  value,
  disabled,
  onChange,
  placeholder = "选择画风",
  size = "middle",
}: {
  styles: DirectorArtStyle[]
  categories: DirectorArtStyleCategory[]
  value?: string
  disabled?: boolean
  onChange: (styleId: string) => void
  placeholder?: string
  size?: "small" | "middle" | "large"
}) {
  const grouped = useMemo(() => {
    const leaves = (items: DirectorArtStyle[]) =>
      items.map((style) => ({
        value: style.id,
        label: `${style.name_zh} / ${style.name_en}`,
      }))
    if (!categories.length) {
      return [{ label: "画风", options: leaves(styles) }]
    }
    return categories
      .map((category) => ({
        label: category.name_zh,
        options: leaves(styles.filter((style) => style.category === category.id)),
      }))
      .filter((group) => group.options.length)
  }, [categories, styles])

  const renderOption = (styleId: string | undefined, label: ReactNode, thumbClass: string) => {
    const style = styles.find((item) => item.id === styleId)
    return (
      <span className="director-style-option">
        {style ? (
          <img
            className={thumbClass}
            src={artStylePreviewUrl(style)}
            alt=""
            onError={(event) => { event.currentTarget.style.display = "none" }}
          />
        ) : null}
        <span>{style?.name_zh || label}</span>
      </span>
    )
  }

  return (
    <div className="xiaji-art-style-compact">
      <Select
        allowClear
        showSearch
        size={size}
        disabled={disabled}
        className="xiaji-art-style-select"
        popupClassName="xiaji-art-style-dropdown"
        popupMatchSelectWidth={320}
        placeholder={placeholder}
        value={value || undefined}
        options={grouped}
        optionFilterProp="label"
        optionRender={(option) => renderOption(String(option.value), option.label, "xiaji-art-style-thumb")}
        labelRender={(props) => renderOption(String(props.value), props.label, "xiaji-art-style-thumb-sm")}
        onChange={(next?: string) => onChange(next || "")}
      />
    </div>
  )
}
