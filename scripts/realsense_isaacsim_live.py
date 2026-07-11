#!/usr/bin/env python3
"""
Standalone Isaac Sim 6.0.1 script that opens a USD world and displays the
RealSense D435 color stream on a live textured plane.

Run on the Isaac Sim machine:
  conda activate env_isaacsim
  python /home/nvidia/isaacsim_realworld/scripts/realsense_isaacsim_live.py
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np


DEFAULT_WORLD = "/home/nvidia/isaacsim_realworld/assets/sim_world.usd"
DEFAULT_VIDEO_DEVICE = "/dev/video4"
DEFAULT_PLANE_PATH = "/World/RealSenseLiveBackground"
DEFAULT_MATERIAL_PATH = "/World/RealSenseLiveBackground_Material"
DEFAULT_TEXTURE_DIR = "/tmp/isaacsim_realsense_live"
JETSON_LIBGOMP = "/lib/aarch64-linux-gnu/libgomp.so.1"


def log(message: str) -> None:
    print(f"[RealSense Live {time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def reexec_with_jetson_libgomp_if_needed() -> None:
    if not os.path.exists(JETSON_LIBGOMP):
        return

    ld_preload = os.environ.get("LD_PRELOAD", "")
    entries = [entry for entry in ld_preload.split(":") if entry]
    if JETSON_LIBGOMP in entries:
        return

    entries.append(JETSON_LIBGOMP)
    os.environ["LD_PRELOAD"] = ":".join(entries)
    log(f"Restarting with LD_PRELOAD={os.environ['LD_PRELOAD']}")
    os.execv(sys.executable, [sys.executable] + sys.argv)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show RealSense D435 live video in Isaac Sim.")
    parser.add_argument("--world", default=DEFAULT_WORLD, help="USD world to open.")
    parser.add_argument("--video-device", default=DEFAULT_VIDEO_DEVICE, help="V4L2 color video device.")
    parser.add_argument("--width", type=int, default=640, help="Capture width.")
    parser.add_argument("--height", type=int, default=480, help="Capture height.")
    parser.add_argument("--fps", type=int, default=30, help="Capture FPS request.")
    parser.add_argument("--update-interval", type=float, default=0.12, help="Texture update interval in seconds.")
    parser.add_argument("--jpeg-quality", type=int, default=85, help="JPEG texture quality 1-100.")
    parser.add_argument("--texture-dir", default=DEFAULT_TEXTURE_DIR, help="Directory for live texture frames.")
    parser.add_argument("--keep-frame-files", type=int, default=40, help="How many old texture frame files to keep.")
    parser.add_argument("--plane-path", default=DEFAULT_PLANE_PATH, help="USD mesh prim path for the screen.")
    parser.add_argument("--material-path", default=DEFAULT_MATERIAL_PATH, help="USD material prim path.")
    parser.add_argument(
        "--plane-center",
        type=float,
        nargs=3,
        default=(1.5, -2.8, 0.9),
        metavar=("X", "Y", "Z"),
        help="Center of the vertical video plane in stage coordinates.",
    )
    parser.add_argument("--plane-width", type=float, default=3.2, help="Width of the video plane in stage units.")
    parser.add_argument(
        "--rotate",
        choices=("none", "cw", "ccw", "180"),
        default="none",
        help="Rotate the camera image before writing it as a texture.",
    )
    parser.add_argument(
        "--flip",
        choices=("none", "h", "v", "both"),
        default="none",
        help="Flip the camera image before writing it as a texture.",
    )
    parser.add_argument("--auto-contrast", action="store_true", help="Apply a small contrast/brightness boost.")
    parser.add_argument("--headless", action="store_true", help="Run Isaac Sim without a UI.")
    parser.add_argument(
        "--exit-after-frames",
        type=int,
        default=0,
        help="If > 0, exit after writing this many texture frames. Useful for testing.",
    )
    return parser.parse_args()


def open_capture(args: argparse.Namespace):
    cap = cv2.VideoCapture(args.video_device, cv2.CAP_V4L2)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open RealSense video device: {args.video_device}")

    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUYV"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(args.width))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(args.height))
    cap.set(cv2.CAP_PROP_FPS, int(args.fps))
    cap.set(cv2.CAP_PROP_AUTO_WB, 1)
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3)
    return cap


def process_frame(frame: np.ndarray, args: argparse.Namespace) -> np.ndarray:
    if args.rotate == "cw":
        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    elif args.rotate == "ccw":
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    elif args.rotate == "180":
        frame = cv2.rotate(frame, cv2.ROTATE_180)

    if args.flip == "h":
        frame = cv2.flip(frame, 1)
    elif args.flip == "v":
        frame = cv2.flip(frame, 0)
    elif args.flip == "both":
        frame = cv2.flip(frame, -1)

    if args.auto_contrast:
        frame = cv2.convertScaleAbs(frame, alpha=1.15, beta=4)
    return frame


def read_frame(cap, args: argparse.Namespace) -> np.ndarray:
    last_error = "no frame"
    for _ in range(30):
        ok, frame = cap.read()
        if ok and frame is not None and frame.size:
            return process_frame(frame, args)
        time.sleep(0.03)
    raise RuntimeError(f"Could not read RealSense frame from {args.video_device}: {last_error}")


def write_frame(frame: np.ndarray, sequence: int, args: argparse.Namespace) -> str:
    texture_dir = Path(args.texture_dir)
    texture_dir.mkdir(parents=True, exist_ok=True)
    path = texture_dir / f"realsense_{sequence:06d}.jpg"

    ok = cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(args.jpeg_quality)])
    if not ok:
        raise RuntimeError(f"Failed to write texture frame: {path}")

    old_sequence = sequence - int(args.keep_frame_files)
    if old_sequence >= 0:
        old_path = texture_dir / f"realsense_{old_sequence:06d}.jpg"
        try:
            old_path.unlink()
        except FileNotFoundError:
            pass
    return str(path)


def open_usd_stage(simulation_app, usd_path: str, timeout_s: float = 120.0):
    import omni.usd

    context = omni.usd.get_context()
    if not context.open_stage(usd_path):
        raise RuntimeError(f"Failed to request opening USD stage: {usd_path}")

    start = time.monotonic()
    while time.monotonic() - start < timeout_s:
        simulation_app.update()
        stage = context.get_stage()
        try:
            loading = bool(context.is_loading())
        except Exception:
            loading = False
        if stage is not None and not loading:
            return stage
        time.sleep(0.03)

    raise TimeoutError(f"Timed out opening USD stage after {timeout_s:.1f}s: {usd_path}")


def make_plane_points(args: argparse.Namespace, image_shape: Tuple[int, int, int]):
    from pxr import Gf

    height_px, width_px = image_shape[:2]
    aspect = height_px / float(width_px)
    width = float(args.plane_width)
    height = width * aspect
    cx, cy, cz = [float(value) for value in args.plane_center]
    half_w = width * 0.5
    half_h = height * 0.5
    return [
        Gf.Vec3f(cx - half_w, cy, cz - half_h),
        Gf.Vec3f(cx + half_w, cy, cz - half_h),
        Gf.Vec3f(cx + half_w, cy, cz + half_h),
        Gf.Vec3f(cx - half_w, cy, cz + half_h),
    ]


def create_or_update_plane(stage, args: argparse.Namespace, image_shape: Tuple[int, int, int]):
    from pxr import Gf, Sdf, UsdGeom, Vt

    if stage.GetPrimAtPath(args.plane_path).IsValid():
        stage.RemovePrim(args.plane_path)

    mesh = UsdGeom.Mesh.Define(stage, args.plane_path)
    mesh.CreatePointsAttr().Set(make_plane_points(args, image_shape))
    mesh.CreateFaceVertexCountsAttr().Set([4])
    mesh.CreateFaceVertexIndicesAttr().Set([0, 1, 2, 3])
    mesh.CreateDoubleSidedAttr().Set(True)

    points = make_plane_points(args, image_shape)
    min_xyz = (
        min(point[0] for point in points),
        min(point[1] for point in points),
        min(point[2] for point in points),
    )
    max_xyz = (
        max(point[0] for point in points),
        max(point[1] for point in points),
        max(point[2] for point in points),
    )
    mesh.CreateExtentAttr().Set([Gf.Vec3f(*min_xyz), Gf.Vec3f(*max_xyz)])

    st = UsdGeom.PrimvarsAPI(mesh.GetPrim()).CreatePrimvar(
        "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.varying
    )
    st.Set(Vt.Vec2fArray([Gf.Vec2f(0, 1), Gf.Vec2f(1, 1), Gf.Vec2f(1, 0), Gf.Vec2f(0, 0)]))
    st.SetInterpolation(UsdGeom.Tokens.varying)
    return mesh


def create_texture_material(stage, args: argparse.Namespace, first_texture_path: str):
    from pxr import Sdf, UsdShade

    if stage.GetPrimAtPath(args.material_path).IsValid():
        stage.RemovePrim(args.material_path)

    material = UsdShade.Material.Define(stage, args.material_path)

    st_reader = UsdShade.Shader.Define(stage, args.material_path + "/PrimvarReader_st")
    st_reader.CreateIdAttr("UsdPrimvarReader_float2")
    st_reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
    st_reader.CreateOutput("result", Sdf.ValueTypeNames.Float2)

    texture = UsdShade.Shader.Define(stage, args.material_path + "/Texture")
    texture.CreateIdAttr("UsdUVTexture")
    texture_file_input = texture.CreateInput("file", Sdf.ValueTypeNames.Asset)
    texture_file_input.Set(Sdf.AssetPath(first_texture_path))
    texture.CreateInput("sourceColorSpace", Sdf.ValueTypeNames.Token).Set("sRGB")
    texture.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(st_reader.ConnectableAPI(), "result")
    texture.CreateOutput("rgb", Sdf.ValueTypeNames.Color3f)

    shader = UsdShade.Shader.Define(stage, args.material_path + "/PreviewSurface")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(texture.ConnectableAPI(), "rgb")
    shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(texture.ConnectableAPI(), "rgb")
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.75)
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
    shader.CreateOutput("surface", Sdf.ValueTypeNames.Token)
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")

    return material, texture_file_input


def bind_material(mesh, material) -> None:
    from pxr import UsdShade

    UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(
        material, UsdShade.Tokens.strongerThanDescendants
    )


def select_prim(prim_path: str) -> None:
    import omni.usd

    omni.usd.get_context().get_selection().set_selected_prim_paths([prim_path], True)


def main() -> int:
    args = parse_args()
    if args.update_interval <= 0:
        raise ValueError("--update-interval must be greater than 0.")

    reexec_with_jetson_libgomp_if_needed()

    from isaacsim import SimulationApp

    simulation_app = SimulationApp({"headless": bool(args.headless)})
    cap = None

    try:
        from pxr import Sdf

        log(f"Opening RealSense stream: {args.video_device}")
        cap = open_capture(args)
        first_frame = read_frame(cap, args)
        first_path = write_frame(first_frame, 0, args)
        log(f"First frame: shape={first_frame.shape}, texture={first_path}")

        log(f"Opening world: {args.world}")
        stage = open_usd_stage(simulation_app, args.world)

        mesh = create_or_update_plane(stage, args, first_frame.shape)
        material, texture_file_input = create_texture_material(stage, args, first_path)
        bind_material(mesh, material)
        select_prim(args.plane_path)
        log(f"Live video plane created: {args.plane_path}")

        frame_count = 1
        next_update = 0.0
        last_log = time.monotonic()
        while simulation_app.is_running():
            now = time.monotonic()
            if now >= next_update:
                frame = read_frame(cap, args)
                frame_path = write_frame(frame, frame_count, args)
                texture_file_input.Set(Sdf.AssetPath(frame_path))
                frame_count += 1
                next_update = now + args.update_interval

                if now - last_log >= 5.0 or args.exit_after_frames:
                    log(f"Updated texture frame {frame_count - 1}: {frame_path}")
                    last_log = now

                if args.exit_after_frames > 0 and frame_count >= args.exit_after_frames:
                    log(f"Exiting after {frame_count} frame(s).")
                    break

            simulation_app.update()

    finally:
        if cap is not None:
            cap.release()
        simulation_app.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
