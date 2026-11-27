"""Create the EEVEE path tracing regression scenes.

Run with:
  blender --background --factory-startup --python tools/create_pt_test_scenes.py

The script writes three .blend files next to the existing test scene:
  scenes/pt_test_room.blend
  scenes/pt_test_motion.blend
  scenes/pt_test_material.blend
"""

import math
import os

import bpy
from mathutils import Vector


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENES_DIR = os.path.join(ROOT, "scenes")


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.use_raytracing = True
    scene.eevee.ray_tracing_method = "PATH_TRACING"
    scene.eevee.taa_render_samples = 64
    scene.render.resolution_x = 640
    scene.render.resolution_y = 480
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    return scene


def make_material(name, base_color, roughness=0.5, metallic=0.0,
                  transmission=0.0, ior=1.5):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*base_color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Transmission Weight"].default_value = transmission
    bsdf.inputs["IOR"].default_value = ior
    mat.diffuse_color = (*base_color, 1.0)
    return mat


def add_plane(name, size, location, rotation, material):
    bpy.ops.mesh.primitive_plane_add(size=size, location=location, rotation=rotation)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(material)
    return obj


def add_uv_sphere(name, location, radius, material):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32,
                                         radius=radius, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(material)
    bpy.ops.object.shade_smooth()
    return obj


def add_camera(scene, location, look_at, lens=50.0):
    camera_data = bpy.data.cameras.new("PT_Camera")
    camera = bpy.data.objects.new("PT_Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = location
    direction = Vector(look_at) - Vector(location)
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera_data.lens = lens
    scene.camera = camera
    return camera


def add_area_light(name, location, size, energy, color=(1.0, 1.0, 1.0)):
    light_data = bpy.data.lights.new(name, type="AREA")
    light_data.size = size
    light_data.energy = energy
    light_data.color = color
    light = bpy.data.objects.new(name, light_data)
    bpy.context.collection.objects.link(light)
    light.location = location
    return light


def make_room():
    scene = reset_scene()

    floor_mat = make_material("PT_Floor", (0.45, 0.45, 0.45), roughness=0.7)
    wall_mat = make_material("PT_Wall", (0.8, 0.8, 0.8), roughness=0.8)
    ceiling_mat = make_material("PT_Ceiling", (0.75, 0.75, 0.75), roughness=0.8)

    add_plane("Floor", 10.0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), floor_mat)
    add_plane("Ceiling", 10.0, (0.0, 0.0, 4.0), (math.pi, 0.0, 0.0), ceiling_mat)
    add_plane("Wall_XNeg", 10.0, (-5.0, 0.0, 2.0), (0.0, -math.pi / 2.0, 0.0), wall_mat)
    add_plane("Wall_XPos", 10.0, (5.0, 0.0, 2.0), (0.0, math.pi / 2.0, 0.0), wall_mat)
    add_plane("Wall_YNeg", 10.0, (0.0, -5.0, 2.0), (math.pi / 2.0, 0.0, 0.0), wall_mat)
    add_plane("Wall_YPos", 10.0, (0.0, 5.0, 2.0), (-math.pi / 2.0, 0.0, 0.0), wall_mat)

    metal = make_material("PT_RedMetal", (0.85, 0.05, 0.05), roughness=0.15, metallic=1.0)
    glass = make_material("PT_Glass", (1.0, 1.0, 1.0), roughness=0.05,
                          transmission=1.0, ior=1.45)
    rough = make_material("PT_RoughGray", (0.55, 0.55, 0.55), roughness=0.8)

    add_uv_sphere("MetalSphere", (-1.4, -0.2, 1.0), 1.0, metal)
    add_uv_sphere("GlassSphere", (1.4, -0.2, 1.0), 1.0, glass)
    add_uv_sphere("RoughSphere", (0.0, -1.8, 0.7), 0.7, rough)

    add_area_light("KeyLight", (0.0, 0.0, 3.9), 3.0, 500.0, (1.0, 0.95, 0.9))
    add_area_light("FillLight", (-3.0, 2.5, 3.2), 2.0, 180.0, (0.8, 0.9, 1.0))

    add_camera(scene, (4.0, -4.0, 2.6), (0.0, 0.0, 1.2), lens=35.0)
    scene.render.filepath = os.path.join(SCENES_DIR, "pt_test_room.blend")
    bpy.ops.wm.save_as_mainfile(filepath=scene.render.filepath)


def make_motion():
    scene = reset_scene()
    scene.frame_start = 1
    scene.frame_end = 10
    bpy.context.preferences.edit.keyframe_new_interpolation_type = "LINEAR"

    floor_mat = make_material("PT_MotionFloor", (0.4, 0.4, 0.4), roughness=0.6)
    wall_mat = make_material("PT_MotionWall", (0.75, 0.1, 0.1), roughness=0.7)
    sphere_mat = make_material("PT_MotionSphere", (0.9, 0.5, 0.05),
                               roughness=0.2, metallic=0.8)

    add_plane("Floor", 12.0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), floor_mat)
    add_plane("BackWall", 12.0, (0.0, 4.0, 3.0), (math.pi / 2.0, 0.0, 0.0), wall_mat)

    sphere = add_uv_sphere("MovingSphere", (-1.5, 0.0, 1.0), 1.0, sphere_mat)
    sphere.keyframe_insert("location", frame=1)
    sphere.location.x = 1.5
    sphere.keyframe_insert("location", frame=10)

    add_area_light("KeyLight", (0.0, -1.0, 4.0), 3.0, 600.0)

    camera = add_camera(scene, (0.0, -8.0, 3.0), (0.0, 0.0, 1.5))
    camera.rotation_euler.z = -0.18
    camera.keyframe_insert("rotation_euler", frame=1)
    camera.rotation_euler.z = 0.18
    camera.keyframe_insert("rotation_euler", frame=10)

    scene.render.filepath = os.path.join(SCENES_DIR, "pt_test_motion.blend")
    bpy.ops.wm.save_as_mainfile(filepath=scene.render.filepath)


def make_checker_image():
    size = 64
    image = bpy.data.images.new("PT_Checker", width=size, height=size, alpha=False)
    pixels = []
    for y in range(size):
        for x in range(size):
            checker = ((x // 8) + (y // 8)) % 2
            value = 0.85 if checker == 0 else 0.08
            pixels.extend((value, value, value, 1.0))
    image.pixels = pixels
    image.pack()
    return image


def make_material_scene():
    scene = reset_scene()

    floor_mat = make_material("PT_MaterialFloor", (0.4, 0.4, 0.4), roughness=0.5)
    wall_mat = make_material("PT_MaterialWall", (0.7, 0.7, 0.7), roughness=0.8)

    add_plane("Floor", 12.0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), floor_mat)
    add_plane("BackWall", 12.0, (0.0, 4.0, 3.0), (math.pi / 2.0, 0.0, 0.0), wall_mat)

    checker = make_checker_image()
    image_mat = make_material("PT_ImageTexture", (0.45, 0.45, 0.45), roughness=0.4)
    bsdf = image_mat.node_tree.nodes.get("Principled BSDF")
    tex = image_mat.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = checker
    tex.location = (-400, 200)
    image_mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])

    procedural_mat = make_material("PT_Procedural", (0.2, 0.45, 0.8),
                                   roughness=0.3, metallic=0.5)
    bsdf = procedural_mat.node_tree.nodes.get("Principled BSDF")
    noise = procedural_mat.node_tree.nodes.new("ShaderNodeTexNoise")
    noise.location = (-600, 200)
    noise.inputs["Scale"].default_value = 6.0
    ramp = procedural_mat.node_tree.nodes.new("ShaderNodeValToRGB")
    ramp.location = (-400, 200)
    ramp.color_ramp.elements[0].position = 0.35
    ramp.color_ramp.elements[0].color = (0.05, 0.1, 0.3, 1.0)
    ramp.color_ramp.elements[1].position = 0.65
    ramp.color_ramp.elements[1].color = (0.9, 0.6, 0.1, 1.0)
    procedural_mat.node_tree.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    procedural_mat.node_tree.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    bpy.ops.mesh.primitive_cube_add(size=1.8, location=(-1.4, 0.0, 0.9))
    cube = bpy.context.object
    cube.name = "ImageCube"
    cube.data.materials.append(image_mat)

    add_uv_sphere("ProceduralSphere", (1.4, 0.0, 1.0), 1.0, procedural_mat)

    add_area_light("KeyLight", (0.0, -1.0, 4.0), 3.0, 500.0)
    add_camera(scene, (0.0, -7.0, 3.0), (0.0, 0.0, 1.2))

    scene.render.filepath = os.path.join(SCENES_DIR, "pt_test_material.blend")
    bpy.ops.wm.save_as_mainfile(filepath=scene.render.filepath)


def main():
    os.makedirs(SCENES_DIR, exist_ok=True)
    make_room()
    make_motion()
    make_material_scene()
    print("Created pt_test_room.blend, pt_test_motion.blend, pt_test_material.blend")


if __name__ == "__main__":
    main()
