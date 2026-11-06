from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.media_studio.services.script_parser import StandardScriptParser

TWO_EPISODE_SCRIPT = """# 花甲短剧

## 视频定位
- 类型：都市喜剧

# 第1集 电梯误会
**剧情：** 吴耐在电梯里遇见沙丽丽。

### 镜头1｜电梯开口
- 人物：吴耐、沙丽丽
- 场景：单元楼电梯
- 动作：轿厢内已站定
- 台词：沙丽丽：“大爷，我什么都可以做。”

# 第2集 走廊对峙
**剧情：** 两人走出电梯。

### 镜头1｜走廊
- 人物：吴耐
- 场景：九楼走廊
- 动作：吴耐看手机
- 台词：吴耐：“几点了。”

# 三、固定场景库
## 单元楼电梯
铁门、按键、灯管。
"""

SHOTS_ONLY_SCRIPT = """# 无集头台本

### 镜头1｜开场
- 动作：醒来
- 台词：「几点了」

### 镜头2｜出门
- 动作：下楼
"""


BOLD_LABEL_SCRIPT = """# 明天的照片

## 主要人物
**林夏**：20多岁，年轻修复师，性格细腻内敛。
**父亲**：林夏已故或多年未见的长辈，温和可靠。

# 第1集 未至的快门

### 镜头1（0-8秒）
- **场景**：旧照相馆内。
- **动作**：林夏戴着白手套，轻轻调整相框。
- **运镜**：特写缓慢推进。
- **音效**：细微的灰尘摩擦声。
- **旁白**：在旧照相馆里，时间总是走得特别慢。

### 镜头2（8-16秒）
- **动作**：照片里写着“明天”，林夏抬头。
- **运镜**：特写，照片微微抖动。
- **音效**：轻微的纸张摩擦声。
- **旁白**：她盯着那张照片。

### 镜头3（16-24秒）
- **动作**：父亲站在门口。
- **对白**：
父亲：（轻声）明天，也可以从今天开始。
- **旁白**：明天，也可以从今天开始。
"""


BARE_SHOT_HEADING_SCRIPT = """# 夜班守则

# 第1集 午夜禁地

### 镜头 1
**场景**：开放式办公区 - 夜
**人物**：李明
**时长**：15秒
**画面**：
办公室异常安静。

### 镜头 2
**场景**：诡异洗手间 - 夜
**人物**：李明
**时长**：20秒
**画面**：
感应灯忽明忽暗。
"""


class StandardScriptParserEpisodeBoundaryTests(unittest.TestCase):
    def test_keeps_hash_episode_boundaries_and_adds_body(self) -> None:
        result = StandardScriptParser.parse(TWO_EPISODE_SCRIPT)
        episodes = result["episodes"]
        self.assertEqual([1, 2], [item["episode_num"] for item in episodes])
        self.assertEqual(["电梯误会", "走廊对峙"], [item["title"] for item in episodes])
        self.assertEqual(1, episodes[0]["shots_count"])
        self.assertEqual(1, episodes[1]["shots_count"])
        self.assertEqual("电梯开口", episodes[0]["shots"][0]["title"])
        self.assertIn("什么都可以做", episodes[0]["shots"][0]["dialogue"])
        self.assertNotIn("shots_source", episodes[0])
        self.assertIn("# 第1集", episodes[0]["body"])
        self.assertIn("电梯误会", episodes[0]["body"])
        self.assertIn("什么都可以做", episodes[0]["body"])
        self.assertNotIn("# 第2集", episodes[0]["body"])
        self.assertNotIn("固定场景库", episodes[0]["body"])
        self.assertIn("# 第2集", episodes[1]["body"])
        self.assertIn("走廊对峙", episodes[1]["body"])
        self.assertNotIn("什么都可以做", episodes[1]["body"])
        self.assertNotIn("固定场景库", episodes[1]["body"])

    def test_shots_only_script_stays_episode_one_with_body(self) -> None:
        result = StandardScriptParser.parse(SHOTS_ONLY_SCRIPT)
        self.assertEqual(1, len(result["episodes"]))
        episode = result["episodes"][0]
        self.assertEqual(1, episode["episode_num"])
        self.assertEqual(2, episode["shots_count"])
        self.assertIn("### 镜头1", episode["body"])
        self.assertIn("### 镜头2", episode["body"])


class StandardScriptParserMarkdownLabelTests(unittest.TestCase):
    def test_bare_shot_heading_keeps_scene_label_on_next_line(self) -> None:
        result = StandardScriptParser.parse(BARE_SHOT_HEADING_SCRIPT)
        shots = result["episodes"][0]["shots"]
        self.assertEqual(["镜头 1", "镜头 2"], [shot["title"] for shot in shots])
        self.assertEqual(["开放式办公区 - 夜", "诡异洗手间 - 夜"], [shot["scene"] for shot in shots])
        self.assertEqual(["开放式办公区 - 夜", "诡异洗手间 - 夜"], [scene["name"] for scene in result["scenes"]])

    def test_scene_references_reuse_previous_scene_and_descriptions_do_not_duplicate_assets(self) -> None:
        text = """# 剧本
# 第1集
### 镜头1（0-8秒）
- **场景**：旧照相馆，灯光昏暗。
- **动作**：林夏整理照片。
### 镜头2（8-16秒）
- **场景**：同上。
- **动作**：林夏抬头。
### 镜头3（16-24秒）
- **场景**：旧照相馆，窗外透进阳光。
- **动作**：林夏转身。
### 镜头4（24-36秒）
- **场景**：照相馆门口，光线昏暗。
- **动作**：门铃响起。
### 镜头5（36-48秒）
- **场景**：照相馆门口。
- **动作**：父亲微笑。
### 镜头6（48-60秒）
- **场景**：同前。
- **动作**：林夏走向父亲。
"""
        result = StandardScriptParser.parse(text)
        shots = result["episodes"][0]["shots"]
        self.assertEqual(shots[0]["scene"], shots[1]["scene"])
        self.assertEqual(shots[4]["scene"], shots[5]["scene"])
        self.assertEqual(["旧照相馆", "照相馆门口"], [scene["name"] for scene in result["scenes"]])
        self.assertEqual([3, 3], [scene["shots_count"] for scene in result["scenes"]])
        self.assertIn("灯光昏暗", result["scenes"][0]["description"])
        self.assertEqual([8, 8, 8, 12, 12, 12], [shot["duration_sec"] for shot in shots])

    def test_scene_reference_does_not_leak_between_episodes_and_explicit_duration_wins(self) -> None:
        text = """# 剧本
# 第1集
### 镜头1（0-8秒）
- 场景：旧照相馆
- 时长：6秒
# 第2集
### 镜头1（0-8秒）
- 场景：同上
"""
        result = StandardScriptParser.parse(text)
        self.assertEqual(6, result["episodes"][0]["shots"][0]["duration_sec"])
        self.assertEqual("", result["episodes"][1]["shots"][0]["scene"])
        self.assertEqual(["旧照相馆"], [scene["name"] for scene in result["scenes"]])

    def test_parses_bold_labels_characters_narration_and_dialogue(self) -> None:
        result = StandardScriptParser.parse(BOLD_LABEL_SCRIPT)

        self.assertEqual(["林夏", "父亲"], [item["name"] for item in result["characters"]])
        self.assertEqual(1, len(result["episodes"]))
        shots = result["episodes"][0]["shots"]
        self.assertEqual(3, len(shots))

        first = shots[0]
        self.assertEqual("林夏戴着白手套，轻轻调整相框。", first["action"])
        self.assertEqual("特写缓慢推进。", first["camera"])
        self.assertEqual("细微的灰尘摩擦声。", first["audio"])
        self.assertEqual("在旧照相馆里，时间总是走得特别慢。", first["subtitle"])
        self.assertEqual("", first["dialogue"])

        # 动作中的照片文字不是说话人台词，不能被引号兜底误识别。
        self.assertEqual("", shots[1]["dialogue"])
        self.assertIn("照片里写着“明天”", shots[1]["action"])

        self.assertEqual("父亲：（轻声）明天，也可以从今天开始。", shots[2]["dialogue"])
        self.assertEqual("明天，也可以从今天开始。", shots[2]["subtitle"])


class StandardScriptParserFallbackCharacterTests(unittest.TestCase):
    def test_extracts_characters_from_shot_labels_when_heading_missing(self) -> None:
        script = """# 逆光之城

### 镜头1｜天台
- 场景：CBD 写字楼顶层露台 / 日 / 外 人物：林远 动作：凭栏远望
- 台词：林远（内心独白）：“三年，我亲手搭建的商业帝国崩塌了。”

### 镜头2｜服务中心
- 场景：公共就业服务中心 / 日 / 内
- 人物：林远、HR经理
- 动作：林远坐在拥挤的等候区
"""
        result = StandardScriptParser.parse(script)
        names = [c["name"] for c in result["characters"]]
        # 频次排序：林远出现两镜排第一；内联值在「动作：」处截断，动作文本不会变成姓名。
        self.assertEqual("林远", names[0])
        self.assertIn("HR经理", names)
        hero = result["characters"][0]
        self.assertEqual("分镜出场角色", hero["role"])
        self.assertGreaterEqual(hero["shots_count"], 2)
        self.assertFalse(any("动作" in name or "场景" in name for name in names))

    def test_heading_characters_still_take_precedence(self) -> None:
        script = """# 剧目

## 一、主要人物设定
### 吴耐——主角
中年快递员，风雨无阻。

## 三、固定场景库
## 街道
路灯。

### 镜头1｜街道
- 人物：路人甲
- 场景：街道
- 动作：吴耐低头看手机
"""
        result = StandardScriptParser.parse(script)
        names = [c["name"] for c in result["characters"]]
        self.assertEqual(["吴耐"], names)

    def test_loose_main_characters_block_without_hash_heading(self) -> None:
        script = """剧名：《闪婚蜜爱》

故事定位
现代都市情感短剧。

主要人物
- 苏念（女，24岁）：插画师，性格倔强独立。
- 厉景深（男，28岁）：厉氏集团总裁，外表高冷禁欲。

第一集：冤家路窄，冲动领证

### 镜头1
- 场景：民政局门口 / 日 / 内
- 人物：苏念、厉景深
- 动作：两人对峙，递上户口本。
"""
        result = StandardScriptParser.parse(script)
        names = [c["name"] for c in result["characters"]]
        self.assertEqual(["苏念", "厉景深"], names)
        su = result["characters"][0]
        self.assertEqual("女", su["gender"])
        self.assertEqual("24岁", su["age"])
        self.assertIn("插画师", su["description"])
        self.assertEqual("主要角色", su["role"])
        self.assertEqual(1, su["shots_count"])
        li = result["characters"][1]
        self.assertEqual("男", li["gender"])
        self.assertEqual("28岁", li["age"])


class StandardScriptParserSectionHeadingTests(unittest.TestCase):
    """模型直出的剧本章节名很少按「标准剧本规范」写，整节内容不能因为标题换个说法就丢。"""

    def test_story_positioning_alias_keeps_prose_paragraph(self) -> None:
        script = """# 闪婚蜜爱

## 故事定位
现代都市情感短剧。讲述苏念在民政局门口偶遇厉景深，两人闪婚。

## 第一集：冤家路窄

### 镜头 1
- 场景：民政局门口 / 日 / 外
- 人物：苏念
"""
        positioning = StandardScriptParser.parse(script)["positioning"]
        self.assertEqual(1, len(positioning["items"]))
        self.assertIn("现代都市情感短剧", positioning["items"][0])
        self.assertEqual("", positioning["genre"])

    def test_labelled_positioning_lines_do_not_duplicate_into_items(self) -> None:
        script = """# 花甲短剧

## 视频定位
- 类型：都市喜剧
- 世界观：当代小区
- 主线：大爷逆袭
- 这一行没有字段名

## 第1集 电梯误会

### 镜头 1
- 场景：电梯
"""
        positioning = StandardScriptParser.parse(script)["positioning"]
        self.assertEqual("都市喜剧", positioning["genre"])
        self.assertEqual("当代小区", positioning["worldview"])
        self.assertEqual("大爷逆袭", positioning["main_storyline"])
        self.assertEqual(["这一行没有字段名"], positioning["items"])

    def test_visual_style_and_advice_aliases(self) -> None:
        script = """# 闪婚蜜爱

## 视觉风格
- 暖色实拍质感，浅景深。
- 禁止：画面内出现任何文字

## 拍摄建议
优先固定机位，减少运镜。
"""
        result = StandardScriptParser.parse(script)
        self.assertIn("暖色实拍质感", result["visual_style"]["description"])
        self.assertEqual("画面内出现任何文字", result["visual_style"]["prohibited"])
        self.assertIn("优先固定机位", result["production_advice"])

    def test_numbered_section_headings_still_match(self) -> None:
        script = """# 花甲短剧

## 二、统一视觉风格
- 冷调夜景。
"""
        self.assertEqual("冷调夜景。", StandardScriptParser.parse(script)["visual_style"]["description"])

    def test_plain_text_episode_headings_are_promoted(self) -> None:
        script = """星尘信使

第一集 深夜邮局
雨夜，实习邮差苏晓抱着发光的包裹冲进老城邮局。
第一集就要上线了，这句不是集标题。

第2集：钟楼送信
苏晓把发光的信封举向天空。
"""
        result = StandardScriptParser.parse(script)
        episodes = result["episodes"]
        self.assertEqual([1, 2], [item["episode_num"] for item in episodes])
        self.assertEqual(["深夜邮局", "钟楼送信"], [item["title"] for item in episodes])
        # 伪集行不产生新集，留在第一集正文里
        self.assertNotIn("# 第一集就要上线了", episodes[0]["body"])
        self.assertIn("第一集就要上线了", episodes[0]["body"])

    def test_markdown_episode_scripts_skip_plain_promotion(self) -> None:
        # 已有 markdown 集标题时不做提升，正文里的纯文本「第X集」句子保持原样
        script = """# 星尘信使

# 第1集 深夜邮局
台词：苏晓：第一集就要上线了。
"""
        result = StandardScriptParser.parse(script)
        episodes = result["episodes"]
        self.assertEqual([1], [item["episode_num"] for item in episodes])
        self.assertIn("第一集就要上线了", episodes[0]["body"])

    def test_plain_episode_promotion_supports_bold_and_full_width_punctuation(self) -> None:
        script = """**第一集** 雨夜
苏晓冲进邮局。

【第二集】雨停
苏晓爬上钟楼。
"""
        episodes = StandardScriptParser.parse(script)["episodes"]
        self.assertEqual([1, 2], [item["episode_num"] for item in episodes])
        self.assertEqual(["雨夜", "雨停"], [item["title"] for item in episodes])


if __name__ == "__main__":
    unittest.main()
