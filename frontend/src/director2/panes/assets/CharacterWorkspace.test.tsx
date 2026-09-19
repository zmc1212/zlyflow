import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { MediaPreviewProvider } from "../../media-preview"
import type { Director2Asset } from "../../api"
import CharacterWorkspace from "./CharacterWorkspace"

const asset: Director2Asset = {
  id: "ast-1",
  project_id: "proj-1",
  kind: "character",
  name: "吴耐",
  role: "主角",
  description: null,
  visual_prompt: null,
  image_url: null,
  voice_id: null,
  extra: {
    identities: [{ id: "look-1", name: "日常", description: "脏白背心" }],
  },
  created_at: "",
  updated_at: "",
}

describe("CharacterWorkspace portrait UI", () => {
  it("does not show avatar generation and still allows generating a look sheet", () => {
    const html = renderToStaticMarkup(
      <MediaPreviewProvider>
        <CharacterWorkspace
          asset={asset}
          onFieldChange={() => undefined}
          onExtraChange={() => undefined}
          onIdentityChange={() => undefined}
          generatingIdentityId={null}
          onGenerateIdentity={() => undefined}
          onRemoveIdentity={() => undefined}
          onOpenAddIdentity={() => undefined}
          uploadingSourceRef={false}
          onUploadSourceRefs={() => undefined}
          onRemoveSourceRef={() => undefined}
        />
      </MediaPreviewProvider>,
    )
    expect(html).not.toContain("生成头像")
    expect(html).not.toContain("角色基础头像")
    expect(html).not.toContain("一键生成所有头像")
    expect(html).not.toContain("avatar_prompt")
    expect(html).toContain("生成设定板")
    expect(html).toContain("身份与造型设定")
  })
})
