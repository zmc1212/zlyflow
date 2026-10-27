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


if __name__ == "__main__":
    unittest.main()
