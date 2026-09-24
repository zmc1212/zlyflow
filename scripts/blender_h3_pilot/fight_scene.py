"""Build a five-second two-person martial-arts graybox in Blender.

Run with blender -b --python fight_scene.py -- <output directory>. The two
mannequins and camera are keyed together; the scene is a motion reference,
not an appearance reference.
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy
from mathutils import Vector


OUT = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
CONTINUOUS = "--continuous" in sys.argv
FILM_CUTS = "--film-cuts" in sys.argv
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "frames").mkdir(exist_ok=True)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)


def mat(name: str, rgb: tuple[float, float, float]):
    material = bpy.data.materials.new(name)
    material.diffuse_color = (*rgb, 1)
    material.use_nodes = True
    material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*rgb, 1)
    material.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.82
    return material


blue = mat("blue-gray clay / left fighter", (0.43, 0.47, 0.59))
peach = mat("warm clay / right fighter", (0.72, 0.48, 0.42))
floor_mat = mat("neutral training floor", (0.38, 0.39, 0.39))
line_mat = mat("floor perspective marks", (0.58, 0.59, 0.57))


def sphere(name: str, radius: float, material):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=14, ring_count=8, radius=radius)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(material)
    return obj


def segment(name: str, material):
    obj = sphere(name, 1.0, material)
    return obj


def place_segment(obj, start: Vector, end: Vector, width: float, frame: int):
    delta = end - start
    obj.location = (start + end) / 2
    obj.rotation_euler = delta.to_track_quat("Z", "Y").to_euler()
    obj.scale = (width, width, delta.length / 2 + width * 0.1)
    for field in ("location", "rotation_euler", "scale"):
        obj.keyframe_insert(data_path=field, frame=frame)


def place_joint(obj, point: Vector, scale: tuple[float, float, float], frame: int):
    obj.location = point
    obj.scale = scale
    obj.keyframe_insert(data_path="location", frame=frame)
    obj.keyframe_insert(data_path="scale", frame=frame)


def fighter(prefix: str, material):
    parts = {name: segment(prefix + "-" + name, material) for name in (
        "torso", "pelvis", "neck", "head", "left-upper-arm", "left-forearm", "left-fist",
        "right-upper-arm", "right-forearm", "right-fist", "left-thigh", "left-shin",
        "left-foot", "right-thigh", "right-shin", "right-foot",
    )}
    return parts


left = fighter("LEFT", blue)
right = fighter("RIGHT", peach)

# Each pose uses local coordinates: +X is toward the opponent, -Y is toward
# camera. Both shoulders, fists and feet are explicit to keep the action legible.
# Tuple: frame, root X, torso lean X, front fist (x,z), back fist (x,z),
# front foot (x,z), back foot (x,z), front knee (x,z), back knee (x,z), squat.
LEFT = [
    (1, -1.18, 0.00, (.43, 1.53), (.14, 1.35), (.28, .10), (-.38, .10), (.25, .56), (-.31, .56), 0),
    (16, -1.00, .10, (1.31, 1.48), (.16, 1.40), (.40, .10), (-.35, .10), (.29, .55), (-.31, .53), 0),
    (29, -.96, .03, (.32, 1.50), (.15, 1.42), (.39, .10), (-.34, .10), (.28, .55), (-.30, .53), 0),
    (43, -.89, .13, (.40, 1.55), (1.31, 1.43), (.40, .10), (-.36, .10), (.31, .55), (-.31, .53), 0),
    (56, -.98, -.20, (.36, 1.24), (.21, 1.17), (.32, .10), (-.35, .10), (.27, .49), (-.30, .49), .24),
    (72, -1.05, -.06, (.45, 1.54), (.31, 1.43), (.32, .10), (-.35, .10), (.27, .54), (-.30, .53), 0),
    (87, -1.08, -.12, (.52, 1.50), (.45, 1.34), (.28, .10), (-.39, .10), (.24, .55), (-.32, .53), 0),
    (100, -1.29, -.20, (.46, 1.46), (.34, 1.35), (.28, .10), (-.38, .10), (.21, .54), (-.31, .53), 0),
    (124, -1.25, -.02, (.38, 1.52), (.17, 1.37), (.28, .10), (-.38, .10), (.24, .56), (-.31, .54), 0),
]
RIGHT = [
    (1, 1.13, .00, (.41, 1.48), (.16, 1.37), (.25, .10), (-.32, .10), (.23, .56), (-.27, .55), 0),
    (16, 1.13, -.08, (.56, 1.51), (.19, 1.41), (.27, .10), (-.33, .10), (.23, .54), (-.27, .53), 0),
    (29, 1.08, -.05, (.47, 1.54), (.26, 1.39), (.29, .10), (-.31, .10), (.25, .55), (-.28, .54), 0),
    (43, 1.03, -.16, (.32, 1.26), (.20, 1.15), (.27, .10), (-.31, .10), (.24, .48), (-.27, .48), .23),
    (56, .98, .08, (1.47, 1.44), (.21, 1.42), (.33, .10), (-.31, .10), (.28, .54), (-.27, .54), 0),
    (72, 1.02, .02, (.41, 1.46), (.21, 1.41), (.30, .10), (-.32, .10), (.57, .65), (-.28, .55), 0),
    (87, 1.02, -.10, (.39, 1.52), (.17, 1.41), (1.65, 1.17), (-.34, .10), (.76, 1.15), (-.30, .55), 0),
    (100, 1.04, -.04, (.38, 1.52), (.18, 1.38), (.46, .38), (-.34, .10), (.59, .77), (-.30, .54), 0),
    (124, 1.08, .00, (.38, 1.52), (.19, 1.39), (.29, .10), (-.33, .10), (.25, .55), (-.28, .54), 0),
]


def animate(parts, poses, facing: int, camera_y: float):
    def point(root: float, x: float, z: float, y: float = 0) -> Vector:
        return Vector((root + facing * x, camera_y + y, z))

    for frame, root, lean, front_hand, back_hand, front_foot, back_foot, front_knee, back_knee, squat in poses:
        hip = point(root, 0, .94 - squat)
        chest = point(root, lean, 1.43 - squat)
        neck = point(root, lean * 1.15, 1.66 - squat)
        head = point(root, lean * 1.2, 1.83 - squat)
        place_segment(parts["torso"], hip, chest, .24, frame)
        place_joint(parts["pelvis"], hip, (.24, .19, .16), frame)
        place_segment(parts["neck"], neck, head - Vector((0, 0, .12)), .065, frame)
        place_joint(parts["head"], head, (.16, .15, .21), frame)
        place_segment(parts["left-upper-arm"], point(root, lean, 1.52-squat, -.17),
                      point(root, (front_hand[0] + .05)/2, (front_hand[1] + 1.46-squat)/2-.11, -.22), .095, frame)
        front_elbow = point(root, (front_hand[0] + .05)/2, (front_hand[1] + 1.46-squat)/2-.11, -.22)
        place_segment(parts["left-forearm"], front_elbow, point(root, *front_hand, -.25), .078, frame)
        place_joint(parts["left-fist"], point(root, *front_hand, -.25), (.11, .09, .11), frame)
        back_elbow = point(root, (back_hand[0] - .06)/2, (back_hand[1] + 1.46-squat)/2-.13, .19)
        place_segment(parts["right-upper-arm"], point(root, lean, 1.52-squat, .17), back_elbow, .095, frame)
        place_segment(parts["right-forearm"], back_elbow, point(root, *back_hand, .23), .078, frame)
        place_joint(parts["right-fist"], point(root, *back_hand, .23), (.11, .09, .11), frame)
        for label, foot, knee, depth in (("left", front_foot, front_knee, -.12),
                                         ("right", back_foot, back_knee, .12)):
            hip_joint = point(root, .02 if label == "left" else -.04, .91-squat, depth)
            knee_joint = point(root, *knee, depth)
            ankle = point(root, *foot, depth)
            place_segment(parts[f"{label}-thigh"], hip_joint, knee_joint, .13, frame)
            place_segment(parts[f"{label}-shin"], knee_joint, ankle, .105, frame)
            place_joint(parts[f"{label}-foot"], ankle + Vector((facing * .08, -.015, -.045)),
                        (.19, .12, .09), frame)


animate(left, LEFT, +1, -.08)
animate(right, RIGHT, -1, .08)


def continuous_points(pose, facing: int, depth: float) -> list[tuple[float, float, float]]:
    _, root, lean, front_hand, back_hand, front_foot, back_foot, front_knee, back_knee, squat = pose

    def p(x, z, y=0):
        return (root + facing*x, depth+y, z)

    return [
        p(0, .94-squat), p(lean*.5, 1.20-squat), p(lean, 1.47-squat),
        p(lean*1.1, 1.66-squat), p(lean*1.2, 1.84-squat), p(lean*1.2, 2.00-squat),
        p(lean, 1.51-squat, -.17),
        p((front_hand[0]+.05)/2, (front_hand[1]+1.46-squat)/2-.11, -.22),
        p(*front_hand, -.25), p(front_hand[0]+.08, front_hand[1], -.25),
        p(lean, 1.51-squat, .17),
        p((back_hand[0]-.06)/2, (back_hand[1]+1.46-squat)/2-.13, .19),
        p(*back_hand, .23), p(back_hand[0]+.08, back_hand[1], .23),
        p(.08, .90-squat, -.11), p(*front_knee, -.12), p(*front_foot, -.12),
        p(front_foot[0]+.18, front_foot[1]-.04, -.12),
        p(-.08, .90-squat, .11), p(*back_knee, .12), p(*back_foot, .12),
        p(back_foot[0]+.18, back_foot[1]-.04, .12),
    ]


def continuous_fighter(name, material, poses, facing, depth, old_parts):
    # One Skin-modified branching mesh per person. Shape keys move the same
    # connected surface through every keyed pose; no detached body pieces.
    edges = [(0,1),(1,2),(2,3),(3,4),(4,5), (2,6),(6,7),(7,8),(8,9),
             (2,10),(10,11),(11,12),(12,13), (0,14),(14,15),(15,16),(16,17),
             (0,18),(18,19),(19,20),(20,21)]
    mesh = bpy.data.meshes.new(name + " connected body")
    mesh.from_pydata(continuous_points(poses[0], facing, depth), edges, [])
    mesh.update()
    obj = bpy.data.objects.new(name + " continuous human mannequin", mesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    skin = obj.modifiers.new("single connected human surface", "SKIN")
    bpy.context.view_layer.update()
    widths = [.19,.20,.22,.095,.155,.06,.12,.095,.07,.09,
              .12,.095,.07,.09,.13,.11,.075,.12,.13,.11,.075,.12]
    for i, width in enumerate(widths):
        obj.data.skin_vertices[0].data[i].radius = (width, width)
    obj.data.skin_vertices[0].data[0].use_root = True
    skin.use_smooth_shade = True
    sub = obj.modifiers.new("smoothed silhouette", "SUBSURF")
    sub.levels = 1
    sub.render_levels = 1
    obj.shape_key_add(name="guard start")
    for pose in poses[1:]:
        key = obj.shape_key_add(name=f"pose {pose[0]}")
        for vertex, coordinate in zip(key.data, continuous_points(pose, facing, depth)):
            vertex.co = coordinate
    keys = obj.data.shape_keys
    keys.use_relative = False
    for index, pose in enumerate(poses):
        keys.eval_time = index * 10
        keys.keyframe_insert(data_path="eval_time", frame=pose[0])
    for part in old_parts.values():
        part.hide_render = True
        part.hide_viewport = True


if CONTINUOUS:
    continuous_fighter("LEFT", blue, LEFT, +1, -.08, left)
    continuous_fighter("RIGHT", peach, RIGHT, -1, .08, right)

bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, -.15))
ground = bpy.context.object
ground.name = "simple neutral ground"
ground.dimensions = (20, 20, .3)
ground.data.materials.append(floor_mat)
for y in (-.8, .8, 2.4):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, y, .005))
    mark = bpy.context.object
    mark.name = "ground depth guide"
    mark.dimensions = (12, .018, .006)
    mark.data.materials.append(line_mat)

bpy.ops.object.light_add(type="AREA", location=(-2.5, -3.5, 6))
bpy.context.object.data.energy = 1200
bpy.context.object.data.size = 5
bpy.ops.object.camera_add(location=(0, -5.1, 1.7))
cam = bpy.context.object
cam.name = "single continuous orbit-and-dolly camera"
cam.data.lens = 39
bpy.context.scene.camera = cam
for frame, xyz, target in (
    (1, (-.38, -5.5, 1.67), (0, 0, 1.20)),
    (43, (-.12, -5.0, 1.66), (0, 0, 1.22)),
    (87, (.38, -4.6, 1.62), (0, 0, 1.22)),
    (124, (.55, -4.85, 1.70), (0, 0, 1.24)),
):
    cam.location = xyz
    cam.rotation_euler = (Vector(target) - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam.keyframe_insert(data_path="location", frame=frame)
    cam.keyframe_insert(data_path="rotation_euler", frame=frame)

if FILM_CUTS:
    # Keep the original paired choreography intact. Only edit the coverage at
    # action beats, unlike stitching unrelated one-person attack clips.
    def shot(name, first_frame, keys, lens):
        bpy.ops.object.camera_add()
        camera = bpy.context.object
        camera.name = name
        camera.data.lens = lens
        for frame, position, target in keys:
            camera.location = position
            camera.rotation_euler = (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()
            camera.keyframe_insert(data_path="location", frame=frame)
            camera.keyframe_insert(data_path="rotation_euler", frame=frame)
        bpy.context.scene.timeline_markers.new(name, frame=first_frame).camera = camera
        return camera

    bpy.context.scene.camera = shot(
        "01 close diagonal jab and parry", 1,
        ((1, (-.46, -4.90, 1.62), (0, 0, 1.19)),
         (43, (-.13, -4.47, 1.59), (0, 0, 1.22))), 42,
    )
    shot(
        "02 over shoulder counter and slip", 44,
        ((44, (1.27, -4.20, 1.54), (-.16, 0, 1.18)),
         (72, (.73, -3.92, 1.45), (-.14, 0, 1.18))), 39,
    )
    shot(
        "03 low side kick and reset", 73,
        ((73, (-.40, -4.30, .98), (0, 0, 1.05)),
         (93, (.10, -4.00, .87), (0, 0, 1.02)),
         (124, (.25, -4.20, 1.08), (0, 0, 1.14))), 35,
    )

scene = bpy.context.scene
scene.frame_start, scene.frame_end = 1, 124
scene.render.fps = 24
scene.render.resolution_x, scene.render.resolution_y = 608, 352
scene.render.resolution_percentage = 100
scene.render.engine = "BLENDER_EEVEE"
scene.render.image_settings.file_format = "PNG"
scene.world.color = (.45, .45, .45)
scene.view_settings.view_transform = "Standard"
scene.frame_set(1)
scene.render.filepath = str(OUT / "frames" / "frame-")
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "fight-previs.blend"))
for frame in (1, 16, 43, 56, 72, 87, 100, 124):
    scene.frame_set(frame)
    scene.render.filepath = str(OUT / f"pose-{frame:03d}.png")
    bpy.ops.render.render(write_still=True)
scene.render.filepath = str(OUT / "frames" / "frame-")
bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "fight-previs.blend"))
print(f"FIGHT_SCENE_READY {OUT}")
