import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import ContentLibraryShotCard, { contentLibraryTextNeedsClamp } from "./content-library-shot-card"

const LONG_CAMERA =
  "竖屏 9:16，中近景双人。机位稳定，只允许一次缓慢小幅推进或固定；不要手持晃动，不要突然变焦。焦点先说话人眼睛与上半身，后景环境仍要能认。"
const LONG_ACTION =
  "竖屏短剧单镜，时长约 8 秒，一镜到底、中间不切、不要时间跳跃。空间：老旧开放式小区单元楼不锈钢廊桥，镜面金属壁反青白灯，楼层红砖，空间逼仄。光线：惨白顶灯，不锈钢壁反射青白冷光，皮肤偏青，几乎没有轮廓光。出场人物必须可辨认——吴耐：60岁清瘦花甲男人，秃顶灰白稀疏头发，褶襞黝黑皮肤，花白胡茬，脏污发黄白色背心、深色旧裤、黑布鞋，裤袋口垂着旧钥匙串；沙丽丽：二十出头浓妆艳丽，波浪棕长发，石狮小说，红唇，红色缎面吊带，黑色包臀短裙、黑丝、红底高跟鞋、黑色铃铛项圈，黑色铃铛项链。"

describe("content library shot cards", () => {
  it("clamps long copy and leaves short labels intact", () => {
    expect(contentLibraryTextNeedsClamp("单元楼电梯", 3)).toBe(false)
    expect(contentLibraryTextNeedsClamp(LONG_CAMERA, 3)).toBe(true)
    expect(contentLibraryTextNeedsClamp(LONG_ACTION, 6)).toBe(true)
  })

  it("keeps long camera copy out of the header so the title stays on one line", () => {
    const html = renderToStaticMarkup(
      <ContentLibraryShotCard
        shot={{
          shot_num: 1,
          title: "电梯里的误会",
          camera: LONG_CAMERA,
          scene: "单元楼电梯",
          characters: ["吴耐", "沙丽丽"],
          action: LONG_ACTION,
          dialogue: "沙丽丽：“该不会想让我那啥吧。”",
        }}
        onCopyPrompt={() => undefined}
      />,
    )
    expect(html).toContain("shot-card-header")
    expect(html).toContain("shot-title")
    expect(html).toContain("电梯里的误会")
    expect(html).toContain("镜头 1")
    expect(html).toContain("机位：")
    expect(html).toContain("展开全部")
    expect((html.match(/展开全部/g) || []).length).toBe(2)
    const header = html.slice(html.indexOf("shot-card-header"), html.indexOf("shot-meta-rows"))
    expect(header).toContain("电梯里的误会")
    expect(header).not.toContain("ant-tag")
    expect(header).not.toContain(LONG_CAMERA)
    expect(html.indexOf("shot-card-header")).toBeLessThan(html.indexOf("机位："))
    expect(html).toContain("shot-clamp")
  })

  it("does not add an expand control for short camera notes", () => {
    const html = renderToStaticMarkup(
      <ContentLibraryShotCard
        shot={{ shot_num: 2, title: "房租", camera: "中近景", scene: "9楼老旧走廊" }}
        onCopyPrompt={() => undefined}
      />,
    )
    expect(html).toContain("中近景")
    expect(html).not.toContain("展开全部")
  })

  it("shows planned duration on the card", () => {
    const html = renderToStaticMarkup(
      <ContentLibraryShotCard
        shot={{ shot_num: 3, title: "开口", duration_sec: 8 }}
        assembling
        onCopyPrompt={() => undefined}
      />,
    )
    expect(html).toContain("8 秒")
    expect(html).toContain("is-assembling")
  })

  it("shows a numeric duration even when the live JSON still has a string", () => {
    const html = renderToStaticMarkup(
      <ContentLibraryShotCard
        shot={{ shot_num: 4, title: "迈步", duration_sec: "10秒" }}
        onCopyPrompt={() => undefined}
      />,
    )
    expect(html).toContain("10 秒")
    expect(html).toContain("shot-duration")
  })
})
