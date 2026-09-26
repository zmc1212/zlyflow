"""Ground review findings in renderable contradictions, not mandatory continuous takes."""
import re

REVIEW_POLICY_VERSION = 2
REVIEW_POLICY = """
审稿边界（优先于通用连续性偏好）：
1. 这是可剪辑的分镜，不是一镜到底。continuity_from_prev=false 或 transition_type=cut 表示允许切镜，
   不是错误标志。允许换主体、反打、切到新出场人物、来源已写明的时间省略。
   不得要求每个进场者提前出现在上一镜，也不得要求展示每个放碗、转身或走路的中间动作。
2. start_state 是动作开始时的状态，正文可以从该状态开始推进。站在屋内后走向门口、
   在门口后走出院子、走在土路后继续行走均不是矛盾。正文明确从另一地点/姿势开始才可能矛盾。
3. 只有来源要求连续且存在互斥事实（例如同一瞬间同一物品在不同人手中），或改变来源因果、
   漏失必要动作/对白，才能报连续性 blocking。必须同时引用两个真实冲突，说明为何不能合理切镜。
   不能仅凭未写明、未出现在上一镜、缺过渡、状态措辞不同或 continuity_from_prev=false 报错。
4. 逐句对白中明确的说话人标签优先于来源旧 speaker 默认值。实际提交正文正确时，
   不得把未使用的旧 speaker 元数据差异当作剧情错误或重复建议。
5. 参考图是可选的视觉辅助，数量/槽位由注册表和结构校验负责。不能要求每个人物、每个场景、
   每个机位都新增独立参考图；只有实际引用不存在的 Picture 编号或明确引用错人物才报问题。
6. 只报告可定位、可执行的实际问题。advisory 不阻断出片，不罗列泛泛的加强表演、
   补参考图或增加过渡镜头建议。不确定且没有证据的问题不要升级 blocking。
7. 来源本身明确要求的起止状态与时间省略应被尊重。修改实际扩写正文就能解决的问题为 creative；
   只有来源事实本身矛盾，必须用户改原镜头/对白/时长才能解决时才为 planning。
"""


def explicit_dialogue_speaker(dialogue: str, fallback: str = "") -> str:
    names = re.findall(r"(?m)^\s*([^\n：:（(]{1,24})(?:[（(][^\n）)]*[）)])?\s*[：:]", dialogue or "")
    names = list(dict.fromkeys(n.strip() for n in names if n.strip()))
    return names[0] if len(names) == 1 else ("" if names else fallback)
