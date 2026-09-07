import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button, Empty, Spin, Typography, message } from "antd"
import { ArrowLeft } from "lucide-react"
import { useNavigate } from "react-router-dom"
import ThemeToggle from "../components/ThemeToggle"
import { ArtStyleCatalogPicker } from "../director/ArtStylePicker"
import { listDirectorArtStyles } from "../director/director-api"
import { PATHS } from "../paths"
import { getXiajiUserArtStyle, saveXiajiUserArtStyle } from "./xiaji-api"

export default function XiajiArtStylesPage({ csrfToken }: { csrfToken: string }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const stylesQuery = useQuery({ queryKey: ["director-art-styles"], queryFn: listDirectorArtStyles })
  const currentQuery = useQuery({ queryKey: ["xiaji-user-art-style"], queryFn: getXiajiUserArtStyle })
  const saveMutation = useMutation({
    mutationFn: (artStyleId: string) => saveXiajiUserArtStyle(csrfToken, artStyleId),
    onSuccess: (payload) => {
      void queryClient.invalidateQueries({ queryKey: ["xiaji-user-art-style"] })
      void queryClient.invalidateQueries({ queryKey: ["xiaji-projects"] })
      message.success(payload.art_style ? `已设为默认画风：${payload.art_style.name}` : "已清除默认画风")
    },
    onError: (error: Error) => message.error(error.message),
  })
  const styles = stylesQuery.data?.styles || []
  const categories = stylesQuery.data?.categories || []
  const selectedId = currentQuery.data?.art_style_id || ""

  return (
    <div className="director-library xiaji-art-styles-page">
      <header className="director-mobile-header">
        <button type="button" aria-label="返回项目列表" onClick={() => navigate(PATHS.director2)}>
          <ArrowLeft size={20} />
        </button>
        <strong>画风</strong>
        <div className="director-mobile-header-actions">
          <ThemeToggle />
        </div>
      </header>
      <header className="director-library-header">
        <div>
          <h1>导台2 画风</h1>
          <p>浏览导演台同一套 34 条画风。点选后作为新项目和内容库的默认画风；每个项目仍可再改。</p>
        </div>
        <Button onClick={() => navigate(PATHS.director2)}>返回项目</Button>
      </header>
      {stylesQuery.isLoading || currentQuery.isLoading ? (
        <div className="director-library-loading">
          <Spin />
          <span>正在加载画风</span>
        </div>
      ) : !styles.length ? (
        <Empty description="没有可用画风目录" />
      ) : (
        <>
          {selectedId ? (
            <Typography.Paragraph type="secondary">
              当前默认：{currentQuery.data?.art_style?.name || selectedId}
            </Typography.Paragraph>
          ) : (
            <Typography.Paragraph type="secondary">尚未设置默认画风。</Typography.Paragraph>
          )}
          <ArtStyleCatalogPicker
            styles={styles}
            categories={categories}
            value={selectedId}
            disabled={saveMutation.isPending}
            onChange={(style) => saveMutation.mutate(style.id)}
          />
        </>
      )}
    </div>
  )
}
