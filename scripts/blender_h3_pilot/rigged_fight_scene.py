"""Build a fight previs with two genuinely skinned, bone-driven humanoids.

The underlying CesiumMan.glb is Khronos/Cesium's CC BY 4.0 sample model.
All motion is keyed on its imported armatures, never on mesh shape keys.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
from mathutils import Euler, Vector

OUT = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
MODEL = OUT / "CesiumMan.glb"
if not MODEL.is_file():
    raise FileNotFoundError(MODEL)
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "frames").mkdir(exist_ok=True)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)


def clay(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*color, 1)
    mat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = .86
    return mat


blue = clay("fighter blue gray", (.46,.49,.60))
peach = clay("fighter warm clay", (.72,.50,.45))
floor_mat = clay("floor", (.40,.41,.41))


def import_fighter(name, x, facing, material):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(MODEL))
    added = set(bpy.data.objects) - before
    arm = next(o for o in added if o.type == "ARMATURE")
    body = next(o for o in added if o.type == "MESH" and o.name.startswith("Cesium_Man"))
    root = arm.parent
    for obj in added:
        if obj not in (arm, body, root):
            bpy.data.objects.remove(obj, do_unlink=True)
    root.name = f"{name} root"
    arm.name = f"{name} humanoid armature"
    body.name = f"{name} skinned human mesh"
    arm.animation_data_clear()
    body.animation_data_clear()
    root.animation_data_clear()
    for slot in body.material_slots:
        slot.material = material
    root.location = (x, 0, 0)
    root.rotation_euler.z = 0 if facing == 1 else math.pi
    root.scale = (1.23, 1.23, 1.23)
    return arm, body, root


man_arm, man_mesh, man_root = import_fighter("LEFT", -1.17, 1, blue)
woman_arm, woman_mesh, woman_root = import_fighter("RIGHT", 1.17, -1, peach)

bpy.ops.mesh.primitive_cube_add(size=1, location=(0,0,-.15))
floor = bpy.context.object
floor.name = "neutral floor"
floor.dimensions = (20,20,.3)
floor.data.materials.append(floor_mat)
bpy.ops.object.light_add(type="AREA", location=(-2.5,-3.5,6))
bpy.context.object.data.energy = 1200
bpy.context.object.data.size = 5
bpy.ops.object.camera_add(location=(0,-5.1,1.5))
cam = bpy.context.object
cam.data.lens = 39
bpy.context.scene.camera = cam
for frame, xyz, target in (
    (1, (-.38,-5.5,1.46), (0,0,1.02)),
    (43,(-.12,-5.0,1.45),(0,0,1.04)),
    (87,(.38,-4.6,1.43),(0,0,1.04)),
    (124,(.55,-4.85,1.48),(0,0,1.06)),
):
    cam.location = xyz
    cam.rotation_euler = (Vector(target)-cam.location).to_track_quat("-Z","Y").to_euler()
    cam.keyframe_insert(data_path="location",frame=frame)
    cam.keyframe_insert(data_path="rotation_euler",frame=frame)

scene=bpy.context.scene
scene.frame_start,scene.frame_end=1,124
scene.render.fps=24
scene.render.resolution_x,scene.render.resolution_y=608,352
scene.render.resolution_percentage=100
scene.render.engine="BLENDER_EEVEE"
scene.render.image_settings.file_format="PNG"
scene.world.color=(.45,.45,.45)
scene.view_settings.view_transform="Standard"
scene.frame_set(1)
scene.render.filepath=str(OUT/"rigged-static.png")
bpy.ops.render.render(write_still=True)
print("ARMATURE_BONES",[b.name for b in man_arm.pose.bones])
if "--probe" in sys.argv:
    for bone_name in ("arm_joint_R_1", "arm_joint_R_2", "leg_joint_R_1"):
        bone=man_arm.pose.bones[bone_name]
        bone.rotation_mode="XYZ"
        for axis in range(3):
            angles=[0,0,0]
            angles[axis]=.9
            bone.rotation_euler=angles
            bpy.context.view_layer.update()
            scene.render.filepath=str(OUT/f"probe-{bone_name}-{axis}.png")
            bpy.ops.render.render(write_still=True)
            bone.rotation_euler=(0,0,0)
            bpy.context.view_layer.update()
    sys.exit(0)

# Rotations are on the imported humanoid skeleton. Bones remain parented in
# the original torso -> shoulder/elbow/hand and hip/knee/ankle hierarchies.
MG = {"arm_joint_L_1":(0,1.02,-.18), "arm_joint_L_2":(0,0,-1.05),
      "arm_joint_R_1":(0,-.48,.18), "arm_joint_R_2":(0,0,.95)}
WG = {"arm_joint_R_1":(0,-1.02,.18), "arm_joint_R_2":(0,0,.95),
      "arm_joint_L_1":(0,.50,-.16), "arm_joint_L_2":(0,0,-.90)}


def pose(arm, frame, base, updates=None):
    values={**base, **(updates or {})}
    for bone in arm.pose.bones:
        bone.rotation_mode="XYZ"
        bone.rotation_euler=values.get(bone.name,(0,0,0))
        bone.keyframe_insert(data_path="rotation_euler",frame=frame)


for frame, man, woman in (
    (1, {}, {}),
    (16, {"arm_joint_L_1":(0,1.45,-.14), "arm_joint_L_2":(0,0,-.10)},
         {"arm_joint_R_1":(0,-1.15,.15), "arm_joint_R_2":(0,0,.75)}),
    (29, {}, {}),
    (43, {"arm_joint_R_1":(0,-1.15,2.10), "arm_joint_R_2":(0,0,.15)},
         {"torso_joint_2":(.24,0,0), "arm_joint_R_1":(0,-.80,.22)}),
    (56, {"torso_joint_2":(-.24,0,0)},
         {"arm_joint_R_1":(0,-1.45,.10), "arm_joint_R_2":(0,0,.05)}),
    (72, {}, {"leg_joint_R_1":(1.15,0,.18), "leg_joint_R_2":(-.88,0,0)}),
    (87, {"arm_joint_L_1":(0,1.1,-.10), "arm_joint_R_1":(0,-.90,1.25)},
         {"leg_joint_R_1":(1.85,0,.25), "leg_joint_R_2":(-.18,0,0)}),
    (100, {"torso_joint_2":(-.16,0,0)},
          {"leg_joint_R_1":(.55,0,.12), "leg_joint_R_2":(-.55,0,0)}),
    (124, {}, {}),
):
    pose(man_arm,frame,MG,man)
    pose(woman_arm,frame,WG,woman)

for root, path in ((man_root,[(1,-1.17),(16,-1.02),(43,-.93),(56,-1.04),
                            (87,-1.10),(100,-1.29),(124,-1.25)]),
                   (woman_root,[(1,1.17),(16,1.17),(43,1.04),(56,1.00),
                                (87,1.03),(100,1.05),(124,1.09)])):
    for frame,x in path:
        root.location.x=x
        root.keyframe_insert(data_path="location",frame=frame)

# Direct the actual bone chains toward choreographed joint targets. The
# imported mesh is weighted to these bones, so elbows, knees and skin move by
# skeletal deformation. Targets control direction; original limb lengths are
# retained, as on a production humanoid rig.
from mathutils import Matrix  # noqa: E402


ALIASES={
    "torso_joint_2":"Skeleton_torso_joint_2",
    "arm_joint_L_1":"Skeleton_arm_joint_L__4_",
    "arm_joint_L_2":"Skeleton_arm_joint_L__3_",
    "arm_joint_L_3":"Skeleton_arm_joint_L__2_",
    "arm_joint_R_1":"Skeleton_arm_joint_R",
    "arm_joint_R_2":"Skeleton_arm_joint_R__2_",
    "arm_joint_R_3":"Skeleton_arm_joint_R__3_",
}


def aim(arm, bone_name, child_name, target_world):
    bone=arm.pose.bones[ALIASES.get(bone_name,bone_name)]
    child=arm.pose.bones[ALIASES.get(child_name,child_name)]
    current=child.head-bone.head
    target=arm.matrix_world.inverted()@Vector(target_world)-bone.head
    if current.length < 1e-5 or target.length < 1e-5:
        return
    rotation=current.rotation_difference(target)
    pivot=bone.head.copy()
    bone.matrix=(Matrix.Translation(pivot) @ rotation.to_matrix().to_4x4()
                 @ Matrix.Translation(-pivot) @ bone.matrix)
    bpy.context.view_layer.update()


def bone_pose(arm, frame, root_x, facing, punch, duck, kick):
    scene.frame_set(frame)
    for bone in arm.pose.bones:
        bone.rotation_mode="QUATERNION"
        bone.rotation_quaternion=(1,0,0,0)
        bone.location=(0,0,0)
        bone.scale=(1,1,1)
    bpy.context.view_layer.update()

    def point(x,z,depth=0):
        return (root_x+facing*x, depth, z)

    # Move the torso before aiming the limbs, keeping the hierarchy intact.
    if duck:
        bone=arm.pose.bones[ALIASES["torso_joint_2"]]
        bone.rotation_mode="XYZ"
        bone.rotation_euler=(0, -.28*facing, 0)
        bpy.context.view_layer.update()

    front_elbow=(.38,1.27)
    front_wrist=(.46,1.43)
    back_elbow=(-.04,1.22)
    back_wrist=(.16,1.41)
    if punch == "front":
        front_elbow=(.58,1.25)
        front_wrist=(1.10,1.30)
    elif punch == "back":
        back_elbow=(.48,1.22)
        back_wrist=(1.05,1.28)
    elif punch == "counter":
        front_elbow=(.62,1.24)
        front_wrist=(1.12,1.29)
    aim(arm,"arm_joint_L_1","arm_joint_L_2",point(*front_elbow,-.13))
    aim(arm,"arm_joint_L_2","arm_joint_L_3",point(*front_wrist,-.17))
    aim(arm,"arm_joint_R_1","arm_joint_R_2",point(*back_elbow,.14))
    aim(arm,"arm_joint_R_2","arm_joint_R_3",point(*back_wrist,.17))

    front_knee=(.17,.61)
    front_ankle=(.23,.07)
    if kick == "chamber":
        front_knee=(.48,.91)
        front_ankle=(.35,.55)
    elif kick == "extend":
        front_knee=(.45,1.07)
        front_ankle=(1.06,1.13)
    elif kick == "retract":
        front_knee=(.38,.77)
        front_ankle=(.32,.33)
    aim(arm,"leg_joint_L_1","leg_joint_L_2",point(*front_knee,-.10))
    aim(arm,"leg_joint_L_2","leg_joint_L_3",point(*front_ankle,-.10))
    aim(arm,"leg_joint_R_1","leg_joint_R_2",point(-.18,.59,.10))
    aim(arm,"leg_joint_R_2","leg_joint_R_3",point(-.27,.06,.10))
    for bone in arm.pose.bones:
        bone.keyframe_insert(data_path="location",frame=frame)
        bone.keyframe_insert(data_path="rotation_quaternion",frame=frame)
        bone.keyframe_insert(data_path="scale",frame=frame)


for frame,mx,wx,mp,wp,md,wd,kick in (
    (1,-.78,.78,None,None,False,False,None),
    (16,-.73,.78,"front",None,False,False,None),
    (29,-.73,.76,None,None,False,False,None),
    (43,-.71,.73,"back",None,False,True,None),
    (56,-.77,.71,None,"counter",True,False,None),
    (72,-.76,.66,None,None,False,False,"chamber"),
    (87,-.67,.55,None,None,False,False,"extend"),
    (100,-.88,.70,None,None,False,False,"retract"),
    (124,-.88,.77,None,None,False,False,None),
):
    man_root.location.x=mx
    man_root.keyframe_insert(data_path="location",frame=frame)
    woman_root.location.x=wx
    woman_root.keyframe_insert(data_path="location",frame=frame)
    bone_pose(man_arm,frame,mx,1,mp,md,None)
    bone_pose(woman_arm,frame,wx,-1,wp,wd,kick)

for frame in (1,16,43,56,72,87,100,124):
    scene.frame_set(frame)
    scene.render.filepath=str(OUT/f"rigged-pose-{frame:03d}.png")
    bpy.ops.render.render(write_still=True)
scene.frame_set(1)
scene.render.filepath=str(OUT/"frames"/"frame-")
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/"fight-rigged.blend"))
print(f"RIGGED_FIGHT_READY {OUT}")
