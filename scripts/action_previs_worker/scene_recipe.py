"""Static Blender recipe. PLAN, ASSET_PATH and OUTPUT_DIR are injected by worker.py.

The FBX must be a MakeHuman CC0 export with a skinned human armature. Bone
aliases below cover MakeHuman game/standard and common Blender naming.
"""

import bpy
import json
import math
import subprocess
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
output = __import__("pathlib").Path(OUTPUT_DIR)
output.mkdir(parents=True, exist_ok=True)
try:
    bpy.ops.import_scene.fbx(filepath=ASSET_PATH)
except (AttributeError, RuntimeError):
    bpy.ops.wm.fbx_import(filepath=ASSET_PATH)
rig = next((obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"), None)
if rig is None:
    raise RuntimeError("MakeHuman FBX 中没有 Armature；请导出带骨骼的人形 FBX")
meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and
          any(mod.type == "ARMATURE" and mod.object == rig for mod in obj.modifiers)]
if not meshes:
    raise RuntimeError("MakeHuman FBX 中没有蒙皮到骨骼的网格")

ALIASES = {
    "pelvis": ["pelvis", "hips", "hip", "root", "spine", "spine01"],
    "spine": ["spine02", "spine01", "spine_02", "spine_01", "spine", "chest", "spine.001"],
    "head": ["head", "head.001"],
    "upper_arm.L": ["upperarm01.L", "upper_arm.L", "upperarm_l", "LeftArm", "upper_arm_l"],
    "upper_arm.R": ["upperarm01.R", "upper_arm.R", "upperarm_r", "RightArm", "upper_arm_r"],
    "forearm.L": ["lowerarm01.L", "lowerarm_l", "forearm.L", "lower_arm.L", "LeftForeArm", "forearm_l"],
    "forearm.R": ["lowerarm01.R", "lowerarm_r", "forearm.R", "lower_arm.R", "RightForeArm", "forearm_r"],
    "hand.L": ["wrist.L", "hand.L", "LeftHand", "hand_l"],
    "hand.R": ["wrist.R", "hand.R", "RightHand", "hand_r"],
    "thigh.L": ["upperleg01.L", "thigh.L", "LeftUpLeg", "thigh_l"],
    "thigh.R": ["upperleg01.R", "thigh.R", "RightUpLeg", "thigh_r"],
    "shin.L": ["lowerleg01.L", "lowerleg_l", "calf_l", "shin.L", "LeftLeg", "shin_l"],
    "shin.R": ["lowerleg01.R", "lowerleg_r", "calf_r", "shin.R", "RightLeg", "shin_r"],
    "foot.L": ["foot.L", "LeftFoot", "foot_l"],
    "foot.R": ["foot.R", "RightFoot", "foot_r"],
}

def bone_map(armature):
    names = {bone.name.lower(): bone for bone in armature.pose.bones}
    mapped = {}
    for key, candidates in ALIASES.items():
        mapped[key] = next((names[name.lower()] for name in candidates if name.lower() in names), None)
    required = ("pelvis", "spine", "head", "upper_arm.L", "upper_arm.R", "hand.L", "hand.R", "thigh.L", "thigh.R", "shin.L", "shin.R", "foot.L", "foot.R")
    missing = [key for key in required if mapped[key] is None]
    if missing:
        raise RuntimeError("人形骨骼不兼容，缺少：" + ", ".join(missing) + "。实际骨骼：" + ", ".join(names)[:500])
    for bone in mapped.values():
        if bone:
            bone.rotation_mode = "XYZ"
    return mapped

mapping_a = bone_map(rig)
rig.name = "ActionActor_A_Rig"
actors = {"A": (rig, mapping_a)}
if len(PLAN["actors"]) == 2:
    duplicate = rig.copy()
    duplicate.data = rig.data.copy()
    bpy.context.collection.objects.link(duplicate)
    duplicate.name = "ActionActor_B_Rig"
    for mesh in meshes:
        copy = mesh.copy()
        copy.data = mesh.data.copy()
        bpy.context.collection.objects.link(copy)
        if copy.parent == rig:
            copy.parent = duplicate
        for modifier in copy.modifiers:
            if modifier.type == "ARMATURE" and modifier.object == rig:
                modifier.object = duplicate
    actors["B"] = (duplicate, bone_map(duplicate))

for obj in list(bpy.context.scene.objects):
    if obj.type == "MESH" and obj not in meshes and not any(mod.type == "ARMATURE" for mod in obj.modifiers):
        bpy.data.objects.remove(obj, do_unlink=True)

def material(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    mat.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value = (*color, 1)
    mat.node_tree.nodes.get("Principled BSDF").inputs["Roughness"].default_value = 0.84
    return mat

clay = {"A": material("Clay_A", (0.58, 0.65, 0.78)), "B": material("Clay_B", (0.78, 0.56, 0.52))}
for actor_id, (armature, bones) in actors.items():
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH" and any(mod.type == "ARMATURE" and mod.object == armature for mod in obj.modifiers):
            obj.data.materials.clear()
            obj.data.materials.append(clay[actor_id])

ground_mat = material("Ground", (0.34, 0.37, 0.39))
bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, -0.04))
ground = bpy.context.object
ground.name = "Ground"
ground.data.materials.append(ground_mat)

def light(name, loc, power, size):
    data = bpy.data.lights.new(name, "AREA")
    data.energy = power
    data.shape = "DISK"
    data.size = size
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = loc
    obj.rotation_euler = (Vector((0, 0, 1)) - obj.location).to_track_quat("-Z", "Y").to_euler()

light("Key", (4, -5, 8), 1700, 6)
light("Fill", (-5, 0, 5), 700, 5)
light("Rim", (2, 5, 6), 1300, 4)

for spec in PLAN["actors"]:
    armature, _ = actors[spec["id"]]
    armature.location = spec["start"]
    armature.rotation_mode = "XYZ"
    armature.rotation_euler.z = math.radians(spec["facing_deg"])
    armature.keyframe_insert(data_path="location", frame=1)
    armature.keyframe_insert(data_path="rotation_euler", frame=1)

ACTOR_START = {spec["id"]: Vector(spec["start"]) for spec in PLAN["actors"]}
ACTOR_SPEC = {spec["id"]: spec for spec in PLAN["actors"]}
TRAVEL_DISTANCE = {"step": 0.7, "walk": 2.8, "run": 4.8}

def facing_vector(actor_id):
    radians = math.radians(float(ACTOR_SPEC[actor_id].get("facing_deg") or 0))
    return Vector((math.cos(radians), math.sin(radians), 0))

def action_distance(action_type):
    return float(TRAVEL_DISTANCE.get(action_type, 0.0))

# Preserve semantic movement between beats. The previous recipe only nudged a
# walking rig by 0.1m and reset it at the next beat, so a walk-to-table request
# rendered as a mostly static person.
ACTOR_FINAL_TRAVEL = {actor_id: 0.0 for actor_id in ACTOR_START}
ACTOR_STANCE_AFTER = {actor_id: 0.0 for actor_id in ACTOR_START}
BEAT_ACTOR_STATE = {}
for beat in PLAN["beats"]:
    for action in beat["actions"]:
        actor_id = action["actor"]
        BEAT_ACTOR_STATE[(beat["id"], actor_id)] = (
            ACTOR_FINAL_TRAVEL[actor_id], ACTOR_STANCE_AFTER[actor_id]
        )
        ACTOR_FINAL_TRAVEL[actor_id] += action_distance(action["type"])
        if action["type"] == "crouch":
            ACTOR_STANCE_AFTER[actor_id] = 1.0

PLAN_TEXT = " ".join(str(beat.get("description") or "") for beat in PLAN["beats"]).lower()
NEEDS_TABLE = any(token in PLAN_TEXT for token in ("table", "desk", "chair", "sit", "sitting", "桌", "椅", "坐"))

def cube_prop(name, location, dimensions, mat, rotation_z=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location, rotation=(0, 0, rotation_z))
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    return obj

# Give sit/walk-to-table requests a visible destination and seating surface. A
# plan can describe the right action while still looking wrong if the compiled
# scene has no object for the actor to approach.
if NEEDS_TABLE:
    prop_mat = material("LibraryWood", (0.24, 0.16, 0.10))
    table_actor = next(iter(ACTOR_START))
    table_center = ACTOR_START[table_actor] + facing_vector(table_actor) * (ACTOR_FINAL_TRAVEL[table_actor] + 0.55)
    cube_prop("LibraryTableTop", table_center + Vector((0, 0, 1.15)), (1.8, 1.0, 0.12), prop_mat)
    for dx in (-0.72, 0.72):
        for dy in (-0.38, 0.38):
            cube_prop("LibraryTableLeg", table_center + Vector((dx, dy, 0.55)), (0.12, 0.12, 1.1), prop_mat)
    chair_center = table_center - facing_vector(table_actor) * 0.78
    cube_prop("LibraryChairSeat", chair_center + Vector((0, 0, 0.55)), (0.78, 0.78, 0.12), prop_mat)
    cube_prop("LibraryChairBack", chair_center + Vector((0, 0.32, 1.0)), (0.78, 0.12, 0.9), prop_mat)

def pose(armature, bones, frame, kind, phase, actor_id, contact=None,
         travel_before=0.0, stance_before=0.0):
    """Anticipation → strike → recoil with body weight and a planted support leg."""
    t = phase
    strike = math.sin(math.pi * max(0, min(1, t)))
    strike = max(0, strike)
    weight = 0.09 * math.sin(math.pi * t)
    values = {key: [0.0, 0.0, 0.0] for key in bones}
    crouch_level = max(stance_before, phase if kind == "crouch" else stance_before)
    values["spine"][1] = (0.08 if kind in {"guard", "block"} else -0.12) * strike
    values["pelvis"][2] = 0.13 * strike
    if kind in {"jab", "cross", "hook", "push", "reach", "grab"}:
        side = "L" if kind == "jab" else "R"
        values[f"upper_arm.{side}"] = [-0.45 - 0.95 * strike, 0.22 * strike, (0.5 if kind == "hook" else 0.05) * strike]
        if bones[f"forearm.{side}"]:
            values[f"forearm.{side}"][0] = -0.45 + 0.75 * strike
        values["spine"][2] = (0.18 if side == "L" else -0.25) * strike
    elif kind in {"low_kick", "side_kick", "knee"}:
        side = "R" if kind != "low_kick" else "L"
        values[f"thigh.{side}"][0] = -1.15 * strike
        values[f"thigh.{side}"][1] = (0.35 if kind == "side_kick" else 0.06) * strike
        values[f"shin.{side}"][0] = (0.9 if kind == "knee" else -0.6) * strike
        values["spine"][1] = 0.2 * strike
    elif kind in {"dodge", "recoil"}:
        values["spine"][1] = 0.4 * strike
        values["spine"][2] = (-0.38 if actor_id == "A" else 0.38) * strike
    elif kind == "crouch":
        values["thigh.L"][0] = 0.95 * crouch_level
        values["thigh.R"][0] = 0.95 * crouch_level
        values["shin.L"][0] = -1.25 * crouch_level
        values["shin.R"][0] = -1.25 * crouch_level
        values["spine"][1] = -0.2 * crouch_level
    elif kind == "block":
        values["thigh.L"][0] = 0.32 * strike
        values["thigh.R"][0] = 0.32 * strike
        values["shin.L"][0] = -0.48 * strike
        values["shin.R"][0] = -0.48 * strike
    elif kind in {"step", "walk", "run", "turn"}:
        values["thigh.L"][0] = -0.38 * strike
        values["thigh.R"][0] = 0.3 * strike
    if kind in {"guard", "jab", "cross", "hook", "low_kick", "side_kick", "knee", "block", "dodge"}:
        for side in ("L", "R"):
            if values[f"upper_arm.{side}"] == [0.0, 0.0, 0.0]:
                values[f"upper_arm.{side}"] = [-0.42, 0.16 if side == "L" else -0.16, 0.0]
    for key, angles in values.items():
        bone = bones[key]
        if bone:
            bone.rotation_euler = angles
            bone.keyframe_insert(data_path="rotation_euler", frame=frame)
    # Keep a crouched/sitting stance through following idle beats.
    if crouch_level and kind in {"idle", "crouch"}:
        values["thigh.L"][0] = 0.95 * crouch_level
        values["thigh.R"][0] = 0.95 * crouch_level
        values["shin.L"][0] = -1.25 * crouch_level
        values["shin.R"][0] = -1.25 * crouch_level
        values["spine"][1] = -0.2 * crouch_level
        for key in ("thigh.L", "thigh.R", "shin.L", "shin.R", "spine"):
            bone = bones[key]
            if bone:
                bone.rotation_euler = values[key]
                bone.keyframe_insert(data_path="rotation_euler", frame=frame)
    progress = phase * phase * (3 - 2 * phase)
    travel = travel_before + action_distance(kind) * progress
    armature.location = ACTOR_START[actor_id] + facing_vector(actor_id) * travel
    armature.location.z += max(0, weight if kind in {"step", "walk", "run", "jump"} else 0)
    armature.location.z -= 0.45 * crouch_level
    if contact and contact["actor"] == actor_id and kind in {"jab", "cross", "hook", "push", "reach", "grab", "low_kick", "side_kick", "knee"}:
        direction = ACTOR_START[contact["target_actor"]] - ACTOR_START[actor_id]
        direction.z = 0
        if direction.length > 0.01:
            armature.location += direction.normalized() * min(0.4, max(0, direction.length - 0.55) * 0.75) * strike
    armature.keyframe_insert(data_path="location", frame=frame)

for beat in PLAN["beats"]:
    span = beat["end"] - beat["start"]
    for action in beat["actions"]:
        actor_id = action["actor"]
        armature, bones = actors[actor_id]
        travel_before, stance_before = BEAT_ACTOR_STATE[(beat["id"], actor_id)]
        for fraction in (0, 0.2, 0.55, 0.8, 1):
            frame = 1 + beat["start"] + round(span * fraction)
            pose(armature, bones, frame, action["type"], fraction, actor_id, beat.get("contact"),
                 travel_before, stance_before)

# A short IK pulse aligns the striking limb to the opponent's sampled contact
# point. It does not replace full hand-authored combat motion or footwork.
for beat in PLAN["beats"]:
    contact = beat.get("contact")
    if not contact:
        continue
    source_rig, source_bones = actors[contact["actor"]]
    target_rig, target_bones = actors[contact["target_actor"]]
    source_bone = source_bones.get(contact["bone"])
    target_bone = target_bones.get(contact["target_bone"])
    if not source_bone or not target_bone or not contact["bone"].startswith(("hand", "foot", "forearm")):
        continue
    hit_frame = contact["frame"] + 1
    bpy.context.scene.frame_set(hit_frame)
    target_point = target_rig.matrix_world @ target_bone.tail
    empty = bpy.data.objects.new(f"IK_Contact_{hit_frame}", None)
    bpy.context.collection.objects.link(empty)
    empty.location = target_point
    constraint = source_bone.constraints.new("IK")
    constraint.name = f"Hit_{hit_frame}"
    constraint.target = empty
    constraint.chain_count = 3 if contact["bone"].startswith(("hand", "foot")) else 2
    constraint.use_stretch = False
    for frame, influence in ((max(1, 1 + beat["start"]), 0), (hit_frame, 1), (min(PLAN["frame_count"], 1 + beat["end"]), 0)):
        constraint.influence = influence
        constraint.keyframe_insert(data_path="influence", frame=frame)

# Keep planted feet in world space while the torso advances for a strike.
# Stepping and kicking beats release the corresponding foot targets.
bpy.context.scene.frame_set(1)
for actor_id, (armature, bones) in actors.items():
    for side in ("L", "R"):
        foot = bones[f"foot.{side}"]
        target = bpy.data.objects.new(f"FootPlant_{actor_id}_{side}", None)
        bpy.context.collection.objects.link(target)
        target.location = armature.matrix_world @ foot.tail
        planted = foot.constraints.new("IK")
        planted.name = f"Planted_{side}"
        planted.target = target
        planted.chain_count = 3
        planted.use_stretch = False
        for beat in PLAN["beats"]:
            action = next((item["type"] for item in beat["actions"] if item["actor"] == actor_id), "idle")
            influence = 0 if action in {"step", "walk", "run", "jump", "low_kick", "side_kick", "knee"} else 1
            for frame in (1 + beat["start"], min(PLAN["frame_count"], beat["end"])):
                planted.influence = influence
                planted.keyframe_insert(data_path="influence", frame=frame)

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 960
scene.render.resolution_y = 540
scene.render.resolution_percentage = 100
scene.render.film_transparent = False
scene.render.image_settings.color_mode = "RGB"
scene.render.fps = 24
scene.frame_start = 1
scene.frame_end = PLAN["frame_count"]
scene.world.color = (0.42, 0.44, 0.45)

start_positions = {item["id"]: Vector(item["start"]) for item in PLAN["actors"]}
def final_position(actor_id):
    return start_positions[actor_id] + facing_vector(actor_id) * ACTOR_FINAL_TRAVEL[actor_id]

def aim(cam, center):
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()

for index, shot in enumerate(PLAN["shots"]):
    data = bpy.data.cameras.new(f"Camera_{index + 1}")
    cam = bpy.data.objects.new(data.name, data)
    bpy.context.collection.objects.link(cam)
    data.lens = shot["lens_mm"]
    if shot["subject"] == "both":
        points = list(start_positions.values()) + [final_position(actor_id) for actor_id in start_positions]
    else:
        points = [start_positions[shot["subject"]], final_position(shot["subject"])]
    center = sum(points, Vector()) / len(points) + Vector((0, 0, 1.25))
    target = bpy.data.objects.new(f"CameraTarget_{index + 1}", None)
    bpy.context.collection.objects.link(target)
    target.location = center
    tracking = cam.constraints.new("TRACK_TO")
    tracking.target = target
    tracking.track_axis = "TRACK_NEGATIVE_Z"
    tracking.up_axis = "UP_Y"
    radius = {"wide": 7.2, "medium": 4.7, "close": 3.1, "detail": 2.2}[shot["size"]] * shot["lens_mm"] / 50
    azimuth = {"front": -math.pi / 2, "side": 0, "three_quarter": -math.pi / 4,
               "over_shoulder": math.pi / 4, "low": -math.pi / 3, "high": -2 * math.pi / 3}[shot["angle"]]
    height = 0.4 if shot["angle"] == "low" else (3.3 if shot["angle"] == "high" else 1.5)
    start = 1 + shot["start"]
    end = shot["end"]
    sample_frames = sorted(set([start, end, (start + end) // 2] + [
        1 + beat["start"] for beat in PLAN["beats"] if start <= 1 + beat["start"] <= end
    ]))
    for frame in sample_frames:
        fraction = (frame - start) / max(1, end - start)
        camera_radius = radius * (1 - 0.18 * fraction) if shot["move"] == "dolly_in" else radius * (1 + 0.18 * fraction) if shot["move"] == "dolly_out" else radius
        turn = 0.32 * fraction if shot["move"] == "orbit_left" else -0.32 * fraction if shot["move"] == "orbit_right" else 0
        truck = 0.6 * fraction if shot["move"] == "truck_right" else -0.6 * fraction if shot["move"] == "truck_left" else 0
        scene.frame_set(frame)
        follow_center = center
        if shot["move"] == "follow" and shot["subject"] != "both":
            follow_center = actors[shot["subject"]][0].location + Vector((0, 0, 1.25))
        cam.location = follow_center + Vector((camera_radius * math.cos(azimuth + turn) + truck,
                                        camera_radius * math.sin(azimuth + turn), height))
        cam.keyframe_insert(data_path="location", frame=frame)
        target.location = follow_center
        target.keyframe_insert(data_path="location", frame=frame)
    marker = scene.timeline_markers.new(f"Cut {index + 1}", frame=start)
    marker.camera = cam
    if index == 0:
        scene.camera = cam

issues = []
if len(actors) == 2 and len(PLAN["shots"]) < 2:
    issues.append("双人场面只有一个机位，请增加切换")
if len({shot["angle"] for shot in PLAN["shots"]}) == 1 and len(PLAN["shots"]) > 1:
    issues.append("多个镜头使用同一机位角度")
for beat in PLAN["beats"]:
    for action in beat["actions"]:
        if action["type"] not in {"idle", "guard", "block", "jab", "cross", "hook", "reach", "point", "wave"}:
            continue
        actor_id = action["actor"]
        armature, bones = actors[actor_id]
        samples = []
        for frame in (beat["start"], (beat["start"] + beat["end"]) // 2, beat["end"] - 1):
            scene.frame_set(frame + 1)
            samples.append([armature.matrix_world @ bones[f"foot.{side}"].head for side in ("L", "R")])
        for index, side in enumerate(("L", "R")):
            drift = max((samples[i][index] - samples[0][index]).length for i in range(1, len(samples)))
            if drift > 0.18:
                issues.append(f"角色 {actor_id} 第 {beat['start']}–{beat['end']} 帧{side}脚滑动 {drift:.2f} 米")
for beat in PLAN["beats"]:
    contact = beat.get("contact")
    if not contact:
        continue
    scene.frame_set(contact["frame"] + 1)
    a_rig, a_bones = actors[contact["actor"]]
    b_rig, b_bones = actors[contact["target_actor"]]
    a_key = contact["bone"] if contact["bone"] in a_bones else "spine"
    b_key = contact["target_bone"] if contact["target_bone"] in b_bones else "spine"
    a_bone = a_bones.get(a_key) or a_bones["spine"]
    b_bone = b_bones.get(b_key) or b_bones["spine"]
    distance = (a_rig.matrix_world @ a_bone.tail - b_rig.matrix_world @ b_bone.tail).length
    if distance > 0.55:
        issues.append(f"第 {contact['frame']} 帧接触点相距 {distance:.2f} 米；需要手工修正距离/IK")
    active_camera = scene.camera
    for marker in scene.timeline_markers:
        if marker.frame <= scene.frame_current:
            active_camera = marker.camera
    strike_point = a_rig.matrix_world @ a_bone.tail
    projected = world_to_camera_view(scene, active_camera, strike_point)
    if projected.z <= 0 or not (0.08 <= projected.x <= 0.92 and 0.08 <= projected.y <= 0.92):
        issues.append(f"第 {contact['frame']} 帧关键打击点出画或贴边")
    else:
        vector = strike_point - active_camera.location
        hit, location, _normal, _face, hit_object, _matrix = scene.ray_cast(
            bpy.context.evaluated_depsgraph_get(), active_camera.location, vector.normalized(), distance=vector.length)
        if hit and hit_object and (location - strike_point).length > 0.45:
            issues.append(f"第 {contact['frame']} 帧关键打击被 {hit_object.name} 遮挡")

for shot in PLAN["shots"]:
    scene.frame_set(1 + (shot["start"] + shot["end"]) // 2)
    cam = scene.camera
    for marker in scene.timeline_markers:
        if marker.frame <= scene.frame_current:
            cam = marker.camera
    for actor_id, (armature, bones) in actors.items():
        head = armature.matrix_world @ bones["head"].head
        point = world_to_camera_view(scene, cam, head)
        if point.z <= 0 or point.x < -0.05 or point.x > 1.05 or point.y < -0.05 or point.y > 1.05:
            issues.append(f"镜头 {shot['id']} 的角色 {actor_id} 头部出画")

scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(output / "scene.blend"))
ffmpeg = FFMPEG_PATH or __import__("shutil").which("ffmpeg")
if not ffmpeg:
    raise RuntimeError("未找到 ffmpeg，无法生成 MP4 和关键帧联系表")
frames = output / "frames"
frames.mkdir(exist_ok=True)
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = str(frames / "frame_")
bpy.ops.render.render(animation=True)
video = output / "preview.mp4"
encoders = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True,
                          text=True, check=True, timeout=30).stdout
encoder_candidates = ("libx264", "h264_nvenc", "h264_amf", "h264_qsv", "h264_mf", "h264_videotoolbox")
h264_encoder = next((name for name in encoder_candidates if f" {name} " in encoders), None)
if h264_encoder:
    codec_args = ["-c:v", h264_encoder, "-profile:v", "high", "-level:v", "4.0",
                  "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
else:
    # Keep a last-resort fallback for machines without an H.264 encoder. The
    # report still completes, but browsers may not decode MPEG-4 Part 2.
    codec_args = ["-c:v", "mpeg4", "-q:v", "3", "-pix_fmt", "yuv420p"]
subprocess.run([ffmpeg, "-y", "-v", "error", "-framerate", str(scene.render.fps),
                "-i", str(frames / "frame_%04d.png"), *codec_args,
                str(video)], check=True, timeout=180)
if not video.is_file():
    raise RuntimeError("Blender 没有生成 MP4")
sheet_fps = 12 * scene.render.fps / PLAN["frame_count"]
subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(video), "-vf",
                f"fps={sheet_fps:.6f},scale=320:180,tile=3x4:padding=4:margin=4:color=white",
                "-frames:v", "1", str(output / "contact_sheet.jpg")], check=True, timeout=120)
report = {"schema_version": 1, "passed": not issues, "issues": issues[:20],
          "frame_count": PLAN["frame_count"], "fps": 24,
          "actors": len(actors), "shots": len(PLAN["shots"]), "rigged_asset": ASSET_PATH}
(output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("Action previs finished", report)
