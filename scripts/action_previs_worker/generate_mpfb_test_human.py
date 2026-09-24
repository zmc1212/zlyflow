"""Create a CC0 skinned test human with MPFB inside Blender.

Run with ``blender --background --python generate_mpfb_test_human.py -- FILE.fbx``.
MPFB must already be installed and enabled in this Blender profile.
"""

import importlib
import sys
from pathlib import Path

import bpy


def human_service():
    for name in tuple(sys.modules):
        if name.endswith("mpfb.services.humanservice"):
            return getattr(importlib.import_module(name), "HumanService")
    raise RuntimeError("MPFB 未加载；请先安装并启用 MPFB 扩展")


if "--" not in sys.argv or len(sys.argv) <= sys.argv.index("--") + 1:
    raise SystemExit("用法：blender --background --python generate_mpfb_test_human.py -- OUTPUT.fbx")
destination = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
destination.parent.mkdir(parents=True, exist_ok=True)

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
human = human_service().create_human()
rig = human_service().add_builtin_rig(human, "game_engine")
if rig is None or rig.type != "ARMATURE":
    raise RuntimeError("MPFB 没有生成骨骼")
skinned = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and
           any(mod.type == "ARMATURE" and mod.object == rig for mod in obj.modifiers)]
if not skinned:
    raise RuntimeError("MPFB 人物没有蒙皮到生成的骨骼")
bone_names = {bone.name.lower() for bone in rig.data.bones}
if not {"head", "pelvis"}.issubset(bone_names):
    raise RuntimeError("生成骨骼缺少 head/pelvis：" + ", ".join(sorted(bone_names))[:500])

bpy.ops.export_scene.fbx(filepath=str(destination), use_selection=False,
                         add_leaf_bones=False, bake_anim=False)
if not destination.is_file() or destination.stat().st_size < 100_000:
    raise RuntimeError("FBX 未成功导出")
print(f"MPFB_TEST_HUMAN={destination}; meshes={len(skinned)}; bones={len(bone_names)}; bytes={destination.stat().st_size}")
