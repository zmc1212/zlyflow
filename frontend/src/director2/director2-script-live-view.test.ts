import { describe, expect, it } from "vitest"
import {
  groupScriptLiveView,
  parseScriptLiveView,
  resolveDirector2ScriptLiveSource,
  visibleShotFields,
  type ScriptLiveBlock,
} from "./director2-script-live-view"

const STANDARD_MARKDOWN = `# 《寒门硕士：穿越古代逆袭记》第一季——AI视频详细分镜版

## 视频定位
- 类型：古装 / 穿越 / 寒门逆袭
- 单集：约30秒
- 主线：现代硕士 → 穿越寒门

## 一、主要人物固定设定

### 沈砚——男主
17岁古代少年；清瘦高挑。

# 第1集：硕士穿越，醒来成了穷小子

**剧情：** 现代硕士沈砚意外穿越，醒来成为贫苦农家少年。

### 镜头1｜现代图书馆
- 人物：现代26岁沈砚
- 场景：现代大学图书馆深夜
- 道具：古籍、电脑、台灯
- 动作：整理古籍、揉眼
- 镜头：中近景缓慢推进
- 台词：“这篇古文，到底是谁写的……”
- 提示词：modern library night, cinematic.

### 镜头2｜穿越
- 场景：图书馆
- 动作：古书掉落，沈砚伸手接，突然白光
`

const BEAT_LEDGER = `【暗巷】
视觉锚点：雨夜霓虹。
Beat 1：他跑进巷口。
Beat 2：他停步拔枪。
对白：别动。`

const GLUED_WALL = "Beat 1：保安A拦住门口。对白：保安A：站住！Beat 2：主角出示证件。对白：主角：我是来办事的。"

function blocksOf<T extends ScriptLiveBlock["type"]>(type: T, blocks: ScriptLiveBlock[]) {
  return blocks.filter((block): block is Extract<ScriptLiveBlock, { type: T }> => block.type === type)
}

describe("parseScriptLiveView", () => {
  it("parses standard content-library Markdown into title, episode and shot cards", () => {
    const blocks = parseScriptLiveView(STANDARD_MARKDOWN)
    expect(blocksOf("title", blocks)[0]).toEqual({
      type: "title",
      text: "《寒门硕士：穿越古代逆袭记》第一季——AI视频详细分镜版",
    })
    expect(blocksOf("heading", blocks).map((block) => block.text)).toEqual([
      "视频定位",
      "一、主要人物固定设定",
      "沈砚——男主",
    ])
    expect(blocksOf("episode", blocks)[0]).toEqual({
      type: "episode",
      text: "第1集：硕士穿越，醒来成了穷小子",
    })
    expect(blocksOf("plot", blocks)[0]).toEqual({
      type: "plot",
      text: "剧情：现代硕士沈砚意外穿越，醒来成为贫苦农家少年。",
    })
    const shots = blocksOf("shot", blocks)
    expect(shots).toHaveLength(2)
    expect(shots[0]).toMatchObject({
      type: "shot",
      heading: "镜头1｜现代图书馆",
    })
    expect(shots[0].type === "shot" && shots[0].fields).toEqual([
      { label: "人物", value: "现代26岁沈砚" },
      { label: "场景", value: "现代大学图书馆深夜" },
      { label: "道具", value: "古籍、电脑、台灯" },
      { label: "动作", value: "整理古籍、揉眼" },
      { label: "镜头", value: "中近景缓慢推进" },
      { label: "台词", value: "“这篇古文，到底是谁写的……”" },
      { label: "提示词", value: "modern library night, cinematic." },
    ])
    expect(visibleShotFields(shots[0].type === "shot" ? shots[0].fields : [])).not.toContainEqual(
      expect.objectContaining({ label: "提示词" }),
    )
    expect(shots[1]).toMatchObject({ heading: "镜头2｜穿越" })
    expect(JSON.stringify(blocks)).not.toMatch(/director-episode-row/)
  })

  it("parses 运镜 as a shot field and still hides 提示词 on live cards", () => {
    const blocks = parseScriptLiveView(`### 镜头1｜单元楼电梯
- 时长：8秒
- 动作：竖屏短剧单镜，时长约 8 秒。空间：不锈钢轿厢。调度：她护着手机。收束：定格睁大的眼睛。
- 运镜：竖屏 9:16，中近景双人，一次缓慢小幅推近
- 音效：电梯低频嗡鸣
- 提示词：Photorealistic vertical 9:16 eight-second take, lighting and camera locked.
`)
    const shots = blocksOf("shot", blocks)
    expect(shots[0]?.fields).toEqual([
      { label: "时长", value: "8秒" },
      { label: "动作", value: "竖屏短剧单镜，时长约 8 秒。空间：不锈钢轿厢。调度：她护着手机。收束：定格睁大的眼睛。" },
      { label: "运镜", value: "竖屏 9:16，中近景双人，一次缓慢小幅推近" },
      { label: "音效", value: "电梯低频嗡鸣" },
      { label: "提示词", value: "Photorealistic vertical 9:16 eight-second take, lighting and camera locked." },
    ])
    expect(visibleShotFields(shots[0]?.fields || []).map((field) => field.label)).toEqual([
      "时长",
      "动作",
      "运镜",
      "音效",
    ])
  })

  it("turns a Beat ledger into shot blocks with action and dialogue", () => {
    const blocks = parseScriptLiveView(BEAT_LEDGER)
    const shots = blocksOf("shot", blocks)
    expect(shots).toHaveLength(2)
    expect(shots[0]).toEqual({
      type: "shot",
      heading: "镜头1｜暗巷",
      fields: [
        { label: "场景", value: "暗巷。雨夜霓虹。" },
        { label: "动作", value: "他跑进巷口。" },
      ],
    })
    expect(shots[1]).toEqual({
      type: "shot",
      heading: "镜头2｜暗巷",
      fields: [
        { label: "场景", value: "暗巷" },
        { label: "动作", value: "他停步拔枪。" },
        { label: "台词", value: "别动。" },
      ],
    })
    expect(JSON.stringify(blocks)).not.toMatch(/Beat /)
  })

  it("splits glued wall text like Beat 1：…对白：保安A：… into two readable shots", () => {
    const blocks = parseScriptLiveView(GLUED_WALL)
    const shots = blocksOf("shot", blocks)
    expect(shots).toHaveLength(2)
    expect(shots[0]).toEqual({
      type: "shot",
      heading: "镜头1｜场景",
      fields: [
        { label: "动作", value: "保安A拦住门口。" },
        { label: "台词", value: "保安A：站住！" },
      ],
    })
    expect(shots[1]).toEqual({
      type: "shot",
      heading: "镜头2｜场景",
      fields: [
        { label: "动作", value: "主角出示证件。" },
        { label: "台词", value: "主角：我是来办事的。" },
      ],
    })
  })

  it("skips a duplicate manuscript title when the article already shows it", () => {
    const blocks = parseScriptLiveView("# 《寒门硕士》\n# 第1集：穿越\n### 镜头1｜破屋\n- 动作：睁眼", {
      skipTitle: "寒门硕士",
    })
    expect(blocksOf("title", blocks)).toHaveLength(0)
    expect(blocksOf("episode", blocks)[0]?.text).toContain("第1集")
  })
})

describe("resolveDirector2ScriptLiveSource", () => {
  it("prefers live shownTexts fields over recipe.script", () => {
    expect(resolveDirector2ScriptLiveSource({
      shownTexts: {
        "script|script|title|": "直播片名",
        "script|script|summary|": "直播梗概",
        "script|script|fullStory|": "### 镜头1｜巷口\n- 动作：停步",
      },
      recipe: { script: { title: "旧片名", summary: "旧梗概", fullStory: "旧正文" } },
    })).toEqual({
      title: "直播片名",
      summary: "直播梗概",
      fullStory: "### 镜头1｜巷口\n- 动作：停步",
    })
  })

  it("fills empty live text from recipe.script after refresh", () => {
    expect(resolveDirector2ScriptLiveSource({
      shownTexts: {},
      recipe: {
        script: {
          title: "门岗",
          summary: "拦门",
          fullStory: "### 镜头1｜门口\n- 台词：站住！",
        },
      },
    })).toEqual({
      title: "门岗",
      summary: "拦门",
      fullStory: "### 镜头1｜门口\n- 台词：站住！",
    })
  })
})

describe("groupScriptLiveView", () => {
  it("splits standard Markdown into preamble and episode groups with shot counts", () => {
    const grouped = groupScriptLiveView(parseScriptLiveView(STANDARD_MARKDOWN))
    expect(grouped.preamble.some((block) => block.type === "heading" && block.text === "视频定位")).toBe(true)
    expect(grouped.preamble.some((block) => block.type === "heading" && block.text.includes("主要人物"))).toBe(true)
    expect(grouped.preamble.some((block) => block.type === "episode")).toBe(false)
    expect(grouped.preamble.some((block) => block.type === "shot")).toBe(false)
    expect(grouped.episodes).toHaveLength(1)
    expect(grouped.episodes[0]).toMatchObject({
      title: "第1集：硕士穿越，醒来成了穷小子",
      shotCount: 2,
      number: 1,
    })
    expect(grouped.episodes[0].blocks[0]).toEqual({
      type: "plot",
      text: "剧情：现代硕士沈砚意外穿越，醒来成为贫苦农家少年。",
    })
    expect(grouped.episodes[0].blocks.filter((block) => block.type === "shot")).toHaveLength(2)
  })

  it("returns empty episodes for Beat ledgers without episode headings", () => {
    const grouped = groupScriptLiveView(parseScriptLiveView(BEAT_LEDGER))
    expect(grouped.episodes).toHaveLength(0)
    expect(grouped.preamble.filter((block) => block.type === "shot")).toHaveLength(2)
  })

  it("keeps multiple episodes as separate capsules", () => {
    const text = `# 第1集：开场
### 镜头1｜门
- 动作：推门
# 第2集：收尾
### 镜头1｜窗
- 动作：关窗
### 镜头2｜街
- 动作：离开
`
    const grouped = groupScriptLiveView(parseScriptLiveView(text))
    expect(grouped.preamble).toHaveLength(0)
    expect(grouped.episodes.map((item) => ({ title: item.title, shotCount: item.shotCount, number: item.number }))).toEqual([
      { title: "第1集：开场", shotCount: 1, number: 1 },
      { title: "第2集：收尾", shotCount: 2, number: 2 },
    ])
  })
})
