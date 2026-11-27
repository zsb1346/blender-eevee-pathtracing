"""Render a deterministic EEVEE path tracing baseline sequence.

Run with:
  blender --background --factory-startup --gpu-backend vulkan scene.blend \
    --python tools/render_pt_baseline.py -- \
    --out baseline/pt_test_motion --frames 1-10 --samples 16 --percent 50
"""

import argparse
import json
import os
import sys

import bpy


def parse_frames(value):
    if "-" in value:
        start, end = value.split("-", 1)
        return int(start), int(end)
    frame = int(value)
    return frame, frame


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--frames", default="1-10")
    parser.add_argument("--samples", type=int, default=16)
    parser.add_argument("--percent", type=int, default=50)
    args = parser.parse_args(argv)

    start, end = parse_frames(args.frames)
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    if hasattr(scene, "eevee"):
        if hasattr(scene.eevee, "use_raytracing"):
            scene.eevee.use_raytracing = True
        if hasattr(scene.eevee, "ray_tracing_method"):
            scene.eevee.ray_tracing_method = "PATH_TRACING"
        scene.eevee.taa_render_samples = args.samples
    scene.render.resolution_percentage = args.percent
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False

    for frame in range(start, end + 1):
        scene.frame_set(frame)
        scene.render.filepath = os.path.join(out_dir, f"frame_{frame:04d}.png")
        print(f"[baseline] rendering frame {frame} -> {scene.render.filepath}")
        bpy.ops.render.render(write_still=True)

    report = {
        "blender": bpy.app.version_string,
        "scene": bpy.data.filepath,
        "out": out_dir,
        "frames": [start, end],
        "samples": args.samples,
        "percent": args.percent,
        "resolution": [
            int(scene.render.resolution_x * args.percent / 100),
            int(scene.render.resolution_y * args.percent / 100),
        ],
    }
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(f"[baseline] wrote {out_dir}")


if __name__ == "__main__":
    main()
