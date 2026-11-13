import { describe, expect, it } from "vitest"
import { cloudVideoShortLabel, resolveCloudVideoProvider } from "./cloud-video-switch"

const providers = [
  { provider_key: "kling", label: "可灵 Kling", enabled: false },
  { provider_key: "jimeng", label: "即梦 / Seedance（火山方舟）", enabled: true },
  { provider_key: "hailuo", label: "海螺 Hailuo（MiniMax）", enabled: false },
  { provider_key: "scnet", label: "超算互联网（SCNet）", enabled: false },
]

describe("云端视频厂商切换", () => {
  it("标签使用去掉括号说明的短名称", () => {
    expect(cloudVideoShortLabel("即梦 / Seedance（火山方舟）")).toBe("即梦 / Seedance")
    expect(cloudVideoShortLabel("海螺 Hailuo（MiniMax）")).toBe("海螺 Hailuo")
    expect(cloudVideoShortLabel("可灵 Kling")).toBe("可灵 Kling")
    expect(cloudVideoShortLabel("（仅括号）")).toBe("（仅括号）")
  })

  it("保持用户已选中的厂商，不会因配置刷新跳回第一家", () => {
    expect(resolveCloudVideoProvider(providers, "hailuo")).toBe("hailuo")
  })

  it("首次进入优先展示已启用的厂商，全部停用时回退到第一家", () => {
    expect(resolveCloudVideoProvider(providers, "")).toBe("jimeng")
    expect(resolveCloudVideoProvider(providers.map((item) => ({ ...item, enabled: false })), "")).toBe("kling")
    expect(resolveCloudVideoProvider([], "kling")).toBe("")
  })
})
