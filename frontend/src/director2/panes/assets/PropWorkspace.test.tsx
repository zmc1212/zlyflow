import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { MediaPreviewProvider } from "../../media-preview"
import type { Director2Asset } from "../../api"
import PropWorkspace from "./PropWorkspace"

const asset: Director2Asset = {
  id: "prop-1",
  project_id: "proj-1",
  kind: "prop",
  name: "旧木书箱",
  role: null,
  description: "沈砚的信物",
  visual_prompt: null,
  image_url: null,
  voice_id: null,
  extra: {
    visual_prompt: "开裂红木箱",
    prop_type: "artifact",
  },
  created_at: "",
  updated_at: "",
}

describe("PropWorkspace sheet UI", () => {
  it("shows a single design sheet and hides turnaround/detail generation", () => {
    const html = renderToStaticMarkup(
      <MediaPreviewProvider>
        <PropWorkspace
          asset={asset}
          onFieldChange={() => undefined}
          onExtraChange={() => undefined}
          generatingProp={false}
          onGenerateReference={() => undefined}
          onDeletePropImage={() => undefined}
          onManualUrl={() => undefined}
          onOpenEditProp={() => undefined}
          uploadingSourceRef={false}
          onUploadSourceRefs={() => undefined}
          onRemoveSourceRef={() => undefined}
        />
      </MediaPreviewProvider>,
    )
    expect(html).toContain("生成设定板")
    expect(html).toContain("设定板: 缺失")
    expect(html).not.toContain("生成三视图")
    expect(html).not.toContain("生成细节特写")
    expect(html).not.toContain("一键生成所有三视图")
    expect(html).not.toContain("一键生成所有细节图")
    expect(html).not.toContain("一键生成所有参考图")
  })
})
