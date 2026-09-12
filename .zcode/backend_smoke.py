# -*- coding: utf-8 -*-
import sys

sys.path.insert(0, r"D:\zlyun\Toonflow\本地视频工作台")
sys.path.insert(0, r"D:\zlyun\Toonflow\本地视频工作台\backend")

import app.main  # noqa: E402

print("main.py 导入 OK")

from app.workflow_registry import WORKFLOW_BY_ID, normalize_options, validate_references  # noqa: E402
from app.models import JobMode  # noqa: E402

definition = WORKFLOW_BY_ID[JobMode.WAN_VACE_DEPTH_V2V.value]
print("注册:", definition.id, "| 隐藏:", definition.hidden_from_catalog, "| refs:", definition.min_references, "-", definition.max_references)
options = normalize_options(JobMode.WAN_VACE_DEPTH_V2V, {
    "width": 832, "height": 480, "length": 17, "vace_strength": 0.8,
    "steps": 20, "seed": 0, "keep_first_frame": True,
})
print("options 归一化 OK:", len(options), "个字段")

from app.director_recipe import payload_kind  # noqa: E402
from app.director_replication import empty_replication_payload, normalize_replication_payload  # noqa: E402

payload = normalize_replication_payload(empty_replication_payload(title="测试"))
print("payload 归一化 OK, kind =", payload["kind"], "| payload_kind():", payload_kind(payload))

from app.video_depth_workflow import build_depth_video_workflow  # noqa: E402
from app.wan_vace_depth_workflow import build_vace_depth_workflow  # noqa: E402

depth_graph = build_depth_video_workflow("a.mp4", frame_cap=33)
replicate_graph = build_vace_depth_workflow("d.mp4", ["f.png"], "test", width=832, height=480, length=17, seed=1)
replicate_no_ref = build_vace_depth_workflow("d.mp4", [], "test", width=832, height=480, length=17, seed=1)
print("深度图:", len(depth_graph), "节点 | 复刻图:", len(replicate_graph), "节点，条件节点:", replicate_graph["25"]["class_type"], "| 无参考回退:", replicate_no_ref["25"]["class_type"])

validate_references(JobMode.WAN_VACE_DEPTH_V2V, ["depth.mp4", "first.png"])
print("引用校验 OK")

from app.director_operations import DirectorOperationService  # noqa: E402

print("director_operations 导入 OK")
