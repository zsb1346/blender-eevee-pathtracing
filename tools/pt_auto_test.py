"""Reusable EEVEE Path Tracing regression renderer.

Run inside Blender:
  blender -b scene.blend --python pt_auto_test.py -- [options]

Examples:
  blender -b scene.blend --python pt_auto_test.py -- --out results --percent 50
  blender -b scene.blend --python pt_auto_test.py -- --list-cases
  blender -b scene.blend --python pt_auto_test.py -- --cases normal,no_history,raw
  blender -b scene.blend --python pt_auto_test.py -- --case "mycase=EEVEE_PT_DEBUG_VIEW=3;EEVEE_PT_NO_TAA=1"

The renderer runs all cases in one Blender process by changing the EEVEE_PT_* environment
variables between renders, which the path tracing module reads every frame. Each case is a
fresh still render, so NRD/TAA history is reset through the normal sampling reset path.
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime

import bpy
import numpy as np

PT_ENV_KEYS = (
    "EEVEE_PT_NO_TAA",
    "EEVEE_PT_NO_NRD",
    "EEVEE_PT_NO_NRD_HISTORY",
    "EEVEE_PT_DEBUG_VIEW",
    "EEVEE_PT_DEBUG_FLAGS",
    "EEVEE_PT_NRD_VALIDATE",
    "EEVEE_PT_USE_RR",
    "EEVEE_PT_DUMP_MATERIALS",
)

CASES = {
    "normal": {},
    "no_history": {"EEVEE_PT_NO_NRD_HISTORY": "1"},
    "raw": {"EEVEE_PT_NO_NRD": "1", "EEVEE_PT_NO_TAA": "1"},
    "nrd_only": {"EEVEE_PT_NO_TAA": "1"},
    "taa_only": {"EEVEE_PT_NO_NRD": "1"},
    "diffuse": {"EEVEE_PT_DEBUG_VIEW": "1"},
    "diffuse_nrd_only": {"EEVEE_PT_DEBUG_VIEW": "1", "EEVEE_PT_NO_TAA": "1"},
    "diffuse_raw": {"EEVEE_PT_DEBUG_VIEW": "3", "EEVEE_PT_NO_TAA": "1"},
    "specular": {"EEVEE_PT_DEBUG_VIEW": "2"},
    "specular_nrd_only": {"EEVEE_PT_DEBUG_VIEW": "2", "EEVEE_PT_NO_TAA": "1"},
    "specular_raw": {"EEVEE_PT_DEBUG_VIEW": "4", "EEVEE_PT_NO_TAA": "1"},
    "diff_hitdist": {"EEVEE_PT_DEBUG_VIEW": "5", "EEVEE_PT_NO_TAA": "1"},
    "spec_hitdist": {"EEVEE_PT_DEBUG_VIEW": "6", "EEVEE_PT_NO_TAA": "1"},
    "indirect": {"EEVEE_PT_DEBUG_VIEW": "7"},
    "direct": {"EEVEE_PT_DEBUG_VIEW": "8"},
    "no_direct_1spp": {"EEVEE_PT_DEBUG_FLAGS": "2"},
    "no_bsdf_spec": {"EEVEE_PT_DEBUG_FLAGS": "4"},
    "validation": {"EEVEE_PT_NRD_VALIDATE": "1"},
    "rr": {"EEVEE_PT_USE_RR": "1"},
}

DEFAULT_CASES = (
    "normal",
    "no_history",
    "raw",
    "nrd_only",
    "diffuse_nrd_only",
    "diffuse_raw",
    "specular_nrd_only",
    "specular_raw",
)


def script_dir():
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        return os.path.dirname(os.path.abspath(bpy.data.filepath))


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="", help="Output directory.")
    parser.add_argument("--scene", default="", help="Optional .blend to open.")
    parser.add_argument("--cases", default="", help="Comma-separated case names.")
    parser.add_argument("--case", action="append", default=[], metavar="NAME=ENV=VAL;...",
                        help="Add or override a case. May be repeated.")
    parser.add_argument("--list-cases", action="store_true")
    parser.add_argument("--percent", type=int, default=50, help="Resolution percentage.")
    parser.add_argument("--samples", type=int, default=64, help="EEVEE render samples.")
    parser.add_argument("--cycles-samples", type=int, default=64)
    parser.add_argument("--cycles-device", default="CPU", choices=("CPU", "GPU"))
    parser.add_argument("--no-cycles-ref", action="store_true")
    parser.add_argument("--save-diff", action="store_true",
                        help="Save amplified diff images at 5x.")
    parser.add_argument("--gui-case", default="", help="Apply a case and leave Blender open.")
    return parser.parse_args(argv)


def add_custom_cases(specs):
    for spec in specs:
        if "=" not in spec:
            raise ValueError(f"Invalid --case '{spec}': expected NAME=ENV=VAL;...")
        name, rest = spec.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError(f"Invalid --case '{spec}': empty name")
        env = {}
        for pair in re.split(r"[;,]", rest):
            pair = pair.strip()
            if not pair:
                continue
            if "=" not in pair:
                raise ValueError(f"Invalid --case '{spec}': '{pair}' is not KEY=VAL")
            key, value = pair.split("=", 1)
            env[key.strip()] = value.strip()
        CASES[name] = env


def clear_pt_env():
    for key in PT_ENV_KEYS:
        os.environ.pop(key, None)


def apply_env(env):
    clear_pt_env()
    for key, value in env.items():
        os.environ[str(key)] = str(value)


def configure_scene(scene, percent, samples):
    scene.render.engine = "BLENDER_EEVEE"
    if hasattr(scene, "eevee"):
        if hasattr(scene.eevee, "use_raytracing"):
            scene.eevee.use_raytracing = True
        if hasattr(scene.eevee, "ray_tracing_method"):
            scene.eevee.ray_tracing_method = "PATH_TRACING"
        if samples > 0 and hasattr(scene.eevee, "taa_render_samples"):
            scene.eevee.taa_render_samples = samples
    scene.render.resolution_percentage = percent
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"


def load_rgb(path):
    img = bpy.data.images.load(path, check_existing=False)
    try:
        width, height = img.size
        pixels = np.empty(width * height * 4, dtype=np.float32)
        img.pixels.foreach_get(pixels)
        return pixels.reshape(height, width, 4)[::-1, :, :3]
    finally:
        bpy.data.images.remove(img)


def compare(a, b):
    if a.shape != b.shape:
        return {"error": f"size mismatch {a.shape} != {b.shape}"}
    diff = np.abs(a - b)
    return {
        "mean_abs": float(diff.mean()),
        "p95": float(np.percentile(diff, 95)),
        "max": float(diff.max()),
    }


def red_ratio(rgb):
    r = rgb[..., 0]
    g = rgb[..., 1]
    b = rgb[..., 2]
    mask = (r > 0.05) & (r > 1.3 * g) & (r > 1.3 * b)
    return float(mask.mean())


def save_diff(path, a, b):
    diff = np.abs(a - b).mean(axis=2)
    rgba = np.ones((*diff.shape, 4), dtype=np.float32)
    rgba[..., 0] = np.clip(diff * 5.0, 0.0, 1.0)
    img = bpy.data.images.new("pt_diff", width=diff.shape[1], height=diff.shape[0])
    try:
        img.pixels.foreach_set(rgba[::-1].ravel())
        img.filepath_raw = path
        img.file_format = "PNG"
        img.save()
    finally:
        bpy.data.images.remove(img)


def render_case(scene, case_name, env, out_dir, percent, samples, index):
    configure_scene(scene, percent, samples)
    apply_env(env)
    filepath = os.path.join(out_dir, f"{index:02d}_{case_name}.png")
    scene.render.filepath = filepath
    started = time.perf_counter()
    error = None
    try:
        bpy.ops.render.render(write_still=True)
    except Exception as exc:  # keep going so one bad case does not kill the suite
        error = str(exc)
    elapsed = time.perf_counter() - started
    return {
        "name": case_name,
        "env": dict(env),
        "file": filepath,
        "seconds": elapsed,
        "error": error,
    }


def render_cycles(scene, out_dir, percent, samples, device):
    clear_pt_env()
    scene.render.engine = "CYCLES"
    if hasattr(scene, "cycles"):
        scene.cycles.samples = samples
        scene.cycles.use_denoising = True
        try:
            scene.cycles.device = device
        except Exception:
            pass
    scene.render.resolution_percentage = percent
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    filepath = os.path.join(out_dir, "cycles.png")
    scene.render.filepath = filepath
    started = time.perf_counter()
    error = None
    try:
        bpy.ops.render.render(write_still=True)
    except Exception as exc:
        error = str(exc)
    return {
        "name": "cycles",
        "file": filepath,
        "seconds": time.perf_counter() - started,
        "error": error,
    }


def write_report(out_dir, report):
    json_path = os.path.join(out_dir, "report.json")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)

    lines = [
        "# EEVEE Path Tracing Test Report",
        "",
        f"- Scene: `{report['scene']}`",
        f"- Blender: {report['blender']}",
        f"- Resolution: {report['resolution'][0]}x{report['resolution'][1]} "
        f"({report['percent']}%)",
        f"- Samples: {report['samples']}",
        f"- Cycles reference: `{report['cycles']['file'] if report['cycles'] else 'none'}`",
        "",
        "| Case | Env | Time (s) | vs normal mean | vs normal p95 | vs cycles mean | "
        "vs cycles p95 | Red % | Error |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for case in report["cases"]:
        env = "; ".join(f"{k}={v}" for k, v in case["env"].items()) or "-"
        vs_normal = case.get("vs_normal", {})
        vs_cycles = case.get("vs_cycles", {})
        lines.append(
            "| {name} | `{env}` | {sec:.2f} | {nm} | {np95} | {cm} | {cp95} | "
            "{red:.4f} | {error} |".format(
                name=case["name"],
                env=env,
                sec=case["seconds"],
                nm=vs_normal.get("mean_abs", "-"),
                np95=vs_normal.get("p95", "-"),
                cm=vs_cycles.get("mean_abs", "-"),
                cp95=vs_cycles.get("p95", "-"),
                red=case.get("red_ratio", 0.0),
                error=case.get("error") or "",
            )
        )
    md_path = os.path.join(out_dir, "report.md")
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return json_path, md_path


def main():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    args = parse_args(argv)

    add_custom_cases(args.case)

    if args.list_cases:
        for name in sorted(CASES):
            env = "; ".join(f"{k}={v}" for k, v in CASES[name].items()) or "-"
            print(f"{name:20s} {env}")
        return

    if args.scene:
        bpy.ops.wm.open_mainfile(filepath=args.scene)

    scene = bpy.context.scene
    if args.gui_case:
        if args.gui_case not in CASES:
            raise SystemExit(f"Unknown case '{args.gui_case}'. Use --list-cases.")
        apply_env(CASES[args.gui_case])
        configure_scene(scene, args.percent, args.samples)
        print(f"EEVEE PT GUI case: {args.gui_case} "
              f"env={CASES[args.gui_case]} scene={bpy.data.filepath}")
        return

    out_dir = args.out or os.path.join(script_dir(), "test_results",
                                       datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(out_dir, exist_ok=True)

    selected = [name.strip() for name in args.cases.split(",") if name.strip()]
    if not selected:
        selected = list(DEFAULT_CASES) + [name for name in CASES if name not in DEFAULT_CASES]

    unknown = [name for name in selected if name not in CASES]
    if unknown:
        raise SystemExit(f"Unknown cases: {', '.join(unknown)}. Use --list-cases.")

    original = {
        "engine": scene.render.engine,
        "percent": scene.render.resolution_percentage,
        "filepath": scene.render.filepath,
        "samples": getattr(scene.eevee, "taa_render_samples", None),
    }

    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "scene": bpy.data.filepath,
        "blender": bpy.app.version_string,
        "out": out_dir,
        "percent": args.percent,
        "samples": args.samples,
        "resolution": [int(scene.render.resolution_x * args.percent / 100),
                       int(scene.render.resolution_y * args.percent / 100)],
        "cases": [],
        "cycles": None,
    }

    configure_scene(scene, args.percent, args.samples)

    print(f"EEVEE PT test: {len(selected)} cases -> {out_dir}")
    for index, name in enumerate(selected):
        print(f"  render {name} ...", end="", flush=True)
        case = render_case(scene, name, CASES[name], out_dir, args.percent, args.samples, index)
        report["cases"].append(case)
        if case["error"]:
            print(f" ERROR: {case['error']}")
        else:
            print(f" {case['seconds']:.2f}s")

    if not args.no_cycles_ref:
        print("  render cycles reference ...", end="", flush=True)
        cycles = render_cycles(scene, out_dir, args.percent, args.cycles_samples,
                               args.cycles_device)
        report["cycles"] = cycles
        if cycles["error"]:
            print(f" ERROR: {cycles['error']}")
        else:
            print(f" {cycles['seconds']:.2f}s")

    normal = next((case for case in report["cases"] if case["name"] == "normal"), None)
    normal_rgb = load_rgb(normal["file"]) if normal and not normal["error"] else None
    cycles_rgb = None
    if report["cycles"] and not report["cycles"]["error"]:
        cycles_rgb = load_rgb(report["cycles"]["file"])

    for case in report["cases"]:
        if case["error"]:
            continue
        rgb = load_rgb(case["file"])
        case["red_ratio"] = red_ratio(rgb)
        if normal_rgb is not None and case["name"] != "normal":
            case["vs_normal"] = compare(rgb, normal_rgb)
        if cycles_rgb is not None:
            case["vs_cycles"] = compare(rgb, cycles_rgb)
            if args.save_diff:
                save_diff(os.path.join(out_dir, f"diff_{case['name']}_vs_cycles.png"),
                          rgb, cycles_rgb)

    json_path, md_path = write_report(out_dir, report)

    print("")
    print(f"{'case':20s} {'time':>7s} {'vs normal':>18s} {'vs cycles':>18s} {'red%':>7s}")
    for case in report["cases"]:
        if case["error"]:
            print(f"{case['name']:20s} {case['seconds']:6.2f}s  ERROR: {case['error']}")
            continue
        vn = case.get("vs_normal", {})
        vc = case.get("vs_cycles", {})
        vn_text = f"{vn['mean_abs']:.5f}/{vn['p95']:.5f}" if "mean_abs" in vn else "-"
        vc_text = f"{vc['mean_abs']:.5f}/{vc['p95']:.5f}" if "mean_abs" in vc else "-"
        print(f"{case['name']:20s} {case['seconds']:6.2f}s {vn_text:>18s} "
              f"{vc_text:>18s} {case.get('red_ratio', 0.0):7.4f}")
    print("")
    print(f"report: {json_path}")
    print(f"report: {md_path}")

    scene.render.engine = original["engine"]
    scene.render.resolution_percentage = original["percent"]
    scene.render.filepath = original["filepath"]
    if original["samples"] is not None and hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = original["samples"]
    clear_pt_env()

    if any(case["error"] for case in report["cases"]) or (
            report["cycles"] and report["cycles"]["error"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
