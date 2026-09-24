"""Stage the UE 5.7 Manny/Quinn FBX characters and native attack clips.

The FBX files are exported from the user's UE template into test-results.
This script builds only an isolated preview .blend and never edits UE assets.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

OUT = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "frames").mkdir(exist_ok=True)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)


def material(name, rgb):
    item=bpy.data.materials.new(name)
    item.diffuse_color=(*rgb,1)
    item.use_nodes=True
    item.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value=(*rgb,1)
    item.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value=.78
    return item


blue=material("Manny clay blue gray",(.42,.46,.58))
peach=material("Quinn clay peach",(.70,.48,.44))
ground=material("neutral training floor",(.40,.41,.41))


def import_character(name, material, location, heading):
    before=set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(OUT/f"{name}.fbx"))
    added=set(bpy.data.objects)-before
    rig=next(obj for obj in added if obj.type=="ARMATURE")
    anchor=bpy.data.objects.new(name+" placement",None)
    bpy.context.collection.objects.link(anchor)
    for obj in added:
        if obj.parent is None:
            obj.parent=anchor
        if obj.type=="MESH":
            obj.hide_render=not obj.name.endswith("LOD0")
            if not obj.hide_render:
                for slot in obj.material_slots:
                    slot.material=material
    anchor.location=location
    anchor.rotation_euler.z=heading
    rig.name=name+" UE humanoid rig"
    return rig,anchor


man,man_anchor=import_character("Manny",blue,(-.88,0,0),math.pi/2)
woman,woman_anchor=import_character("Quinn",peach,(.88,0,0),-math.pi/2)


def load_action(filename):
    old_objects=set(bpy.data.objects)
    old_actions=set(bpy.data.actions)
    bpy.ops.import_scene.fbx(filepath=str(OUT/f"{filename}.fbx"))
    new_actions=list(set(bpy.data.actions)-old_actions)
    if len(new_actions)!=1:
        raise RuntimeError(f"{filename}: expected one animation, got {len(new_actions)}")
    action=new_actions[0]
    action.name="UE "+filename
    source_rig=next(obj for obj in set(bpy.data.objects)-old_objects if obj.type=="ARMATURE")
    for obj in set(bpy.data.objects)-old_objects:
        if obj is not source_rig:
            bpy.data.objects.remove(obj,do_unlink=True)
    source_rig.hide_render=True
    return action,source_rig


attacks={name:load_action(name) for name in ("Attack_01","Attack_02","Attack_03","ChargedAttack","Idle")}


def copy_pose(target, source):
    for bone in target.pose.bones:
        bone.matrix_basis=source.pose.bones[bone.name].matrix_basis.copy()
    bpy.context.view_layer.update()

bpy.ops.mesh.primitive_cube_add(size=1,location=(0,0,-.15))
floor=bpy.context.object
floor.dimensions=(20,20,.3)
floor.data.materials.append(ground)
bpy.ops.object.light_add(type="AREA",location=(-2.5,-3.5,6))
bpy.context.object.data.energy=1200
bpy.context.object.data.size=5
scene=bpy.context.scene
scene.frame_start,scene.frame_end=1,124
scene.render.fps=24
scene.render.resolution_x,scene.render.resolution_y=608,352
scene.render.resolution_percentage=100
scene.render.engine="BLENDER_EEVEE"
scene.render.image_settings.file_format="PNG"
scene.world.color=(.45,.45,.45)
scene.view_settings.view_transform="Standard"


def sample_action(name, source_frame):
    action,source=attacks[name]
    scene.frame_set(min(source_frame,int(action.frame_range[1])))
    return {bone.name:bone.matrix_basis.copy() for bone in source.pose.bones}


def apply_pose(target,snapshot):
    for bone in target.pose.bones:
        bone.matrix_basis=snapshot[bone.name]
    bpy.context.view_layer.update()


def rotate_bone_world(rig,bone_name,axis_world,angle):
    bone=rig.pose.bones[bone_name]
    axis=rig.matrix_world.inverted().to_quaternion() @ Vector(axis_world)
    pivot=bone.head.copy()
    transform=(Matrix.Translation(pivot) @
               Matrix.Rotation(angle,4,axis) @
               Matrix.Translation(-pivot))
    bone.matrix=transform @ bone.matrix
    bpy.context.view_layer.update()


def kick_angles(frame):
    # The final shot begins with a chamber, holds the extended side kick for
    # five frames at contact, then retracts. Values are armature-space poses.
    keys=((75,0,0),(85,.10,-.05),(93,.92,-.72),
          (99,1.68,.48),(104,1.68,.48),(112,.54,-.58),(122,0,0))
    for (f0,a0,b0),(f1,a1,b1) in zip(keys,keys[1:]):
        if f0<=frame<=f1:
            t=(frame-f0)/(f1-f0)
            t=t*t*(3-2*t)
            return a0+(a1-a0)*t,b0+(b1-b0)*t
    return 0,0


def key_pose(rig,frame):
    for bone in rig.pose.bones:
        bone.keyframe_insert(data_path="location",frame=frame)
        bone.keyframe_insert(data_path="rotation_quaternion",frame=frame)
        bone.keyframe_insert(data_path="scale",frame=frame)


for frame in range(1,125):
    if frame<=32:
        man_pose=sample_action("Attack_01",frame)
        woman_pose=sample_action("Attack_02",frame)
    elif frame<=74:
        man_pose=sample_action("Attack_03",frame-32)
        woman_pose=sample_action("Attack_01",min(frame-32,32))
    else:
        man_pose=sample_action("Attack_02",min(frame-74,32))
        woman_pose=sample_action("Attack_02",32)
    scene.frame_set(frame)
    apply_pose(man,man_pose)
    apply_pose(woman,woman_pose)
    if frame>74:
        if 85<=frame<=122:
            # Work on the imported UE thigh/calf bones, preserving the skinned
            # mesh and the 88-bone rig rather than substituting primitive parts.
            hip,knee=kick_angles(frame)
            rotate_bone_world(woman,"thigh_l",(0,1,0),hip)
            rotate_bone_world(woman,"calf_l",(0,1,0),knee)
    key_pose(man,frame)
    key_pose(woman,frame)

# Footwork is independent of the attack clips and gives each exchange space.
for frame,man_x,woman_x in ((1,-.94,.94),(18,-.73,.88),(32,-.82,.82),
                            (33,-.80,.82),(55,-.61,.70),(74,-.83,.83),
                            (75,-.84,.84),(98,-.74,.69),(109,-.98,.75),
                            (124,-1.03,.83)):
    man_anchor.location.x=man_x
    woman_anchor.location.x=woman_x
    man_anchor.keyframe_insert(data_path="location",frame=frame)
    woman_anchor.keyframe_insert(data_path="location",frame=frame)


def make_shot(name,start,poses,lens):
    bpy.ops.object.camera_add()
    camera=bpy.context.object
    camera.name=name
    camera.data.lens=lens
    for frame,position,target in poses:
        camera.location=position
        camera.rotation_euler=(Vector(target)-camera.location).to_track_quat("-Z","Y").to_euler()
        camera.keyframe_insert(data_path="location",frame=frame)
        camera.keyframe_insert(data_path="rotation_euler",frame=frame)
    scene.timeline_markers.new(name,frame=start).camera=camera
    return camera


opening=make_shot("01 diagonal tracking close two shot",1,
                  ((1,(-.48,-4.48,1.57),(0,0,1.12)),
                   (32,(-.05,-4.18,1.55),(0,0,1.14))),43)
make_shot("02 Quinn shoulder counter punch",33,
          ((33,(2.35,-3.55,1.60),(-.19,0,1.18)),
           (74,(1.70,-3.20,1.47),(-.12,0,1.17))),39)
make_shot("03 low side impact and recovery",75,
          ((75,(-1.1,-3.8,.92),(.03,0,1.04)),
           (100,(-.24,-3.30,.78),(.01,0,.99)),
           (124,(.34,-3.65,1.02),(0,0,1.11))),38)
scene.camera=opening
scene.frame_set(1)
scene.render.filepath=str(OUT/"frames"/"frame-")
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/"ue-mannequin-fight.blend"))
for frame in (1,16,32,42,56,73,83,94,101,112,124):
    scene.frame_set(frame)
    scene.render.filepath=str(OUT/f"pose-{frame:03d}.png")
    bpy.ops.render.render(write_still=True)
scene.render.filepath=str(OUT/"frames"/"frame-")
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/"ue-mannequin-fight.blend"))
print("UE_FIGHT_READY",str(OUT))
