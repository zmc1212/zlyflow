"""Create the reproducible gray-box shot inside Blender via MCP execute_blender_code.

The MCP client injects OUTPUT_DIR before sending this source to Blender. Keep
geometry deliberately simple: the trial measures camera and occlusion control.
"""

from pathlib import Path

import bpy
from mathutils import Vector

output_dir = Path(OUTPUT_DIR)
output_dir.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)


def material(name, color):
    item = bpy.data.materials.new(name)
    item.diffuse_color = (*color, 1.0)
    item.use_nodes = True
    item.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*color, 1.0)
    return item


def box(name, location, scale, surface):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(surface)
    return obj


stone = material("corridor-stone", (0.47, 0.48, 0.49))
dark = material("depth-walls", (0.23, 0.25, 0.28))
occluder = material("foreground-pillar-ochre", (0.68, 0.37, 0.15))
subject = material("subject-proxy-blue", (0.05, 0.48, 0.59))
stripe = material("floor-guide-white", (0.85, 0.83, 0.73))

box("floor", (0, 2.3, -0.12), (4.6, 14, 0.2), stone)
box("left-wall", (-2.3, 2.3, 1.4), (0.18, 14, 2.8), dark)
box("right-wall", (2.3, 2.3, 1.4), (0.18, 14, 2.8), dark)
box("ceiling", (0, 2.3, 2.85), (4.6, 14, 0.12), dark)
box("left-floor-guide", (-1.35, 2.3, 0.004), (0.055, 13.5, 0.008), stripe)
box("right-floor-guide", (1.35, 2.3, 0.004), (0.055, 13.5, 0.008), stripe)
box("occluding-pillar", (0.13, -0.45, 1.38), (0.40, 0.42, 2.76), occluder)
for index, distance in enumerate((2.0, 5.0, 8.0), start=1):
    for side in (-1, 1):
        box(f"depth-pillar-{index}-{side}", (side * 1.88, distance, 1.4), (0.26, 0.35, 2.8), stone)

box("person-torso", (0.0, 5.8, 1.07), (0.53, 0.32, 0.78), subject)
bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=12, radius=0.23, location=(0, 5.8, 1.72))
bpy.context.object.name = "person-head-proxy"
bpy.context.object.data.materials.append(subject)
for side in (-1, 1):
    box(f"person-leg-{side}", (side * 0.16, 5.8, 0.40), (0.17, 0.23, 0.8), subject)

bpy.ops.object.light_add(type="AREA", location=(0, 1.2, 2.5))
bpy.context.object.name = "soft-corridor-light"
bpy.context.object.data.energy = 900
bpy.context.object.data.shape = "RECTANGLE"
bpy.context.object.data.size = 3
bpy.context.object.data.size_y = 7

bpy.ops.object.camera_add(location=(-0.85, -4.2, 1.55))
camera = bpy.context.object
camera.name = "dolly-right-with-foreground-occlusion"
camera.data.lens = 34
bpy.context.scene.camera = camera
for frame, location in (
    (1, (-0.85, -4.2, 1.55)),
    (48, (-0.40, -2.65, 1.55)),
    (87, (0.34, -1.0, 1.55)),
    (124, (0.58, 0.55, 1.55)),
):
    camera.location = location
    direction = Vector((0, 5.8, 1.20)) - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera.keyframe_insert(data_path="location", frame=frame)
    camera.keyframe_insert(data_path="rotation_euler", frame=frame)

scene = bpy.context.scene
scene.frame_start = 1
scene.frame_end = 124
scene.render.fps = 24
scene.render.resolution_x = 608
scene.render.resolution_y = 352
scene.render.resolution_percentage = 100
engine_choices = {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}
for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
    if engine in engine_choices:
        scene.render.engine = engine
        break
scene.world.color = (0.38, 0.38, 0.38)
scene.view_settings.view_transform = "Standard"
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = str(output_dir / "frames" / "frame-")
(output_dir / "frames").mkdir(exist_ok=True)
scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(output_dir / "corridor-previs.blend"))
scene.render.filepath = str(output_dir / "first-frame.png")
bpy.ops.render.render(write_still=True)
scene.render.filepath = str(output_dir / "frames" / "frame-")
bpy.ops.wm.save_as_mainfile(filepath=str(output_dir / "corridor-previs.blend"))
print(f"MCP_SCENE_READY {output_dir}")
