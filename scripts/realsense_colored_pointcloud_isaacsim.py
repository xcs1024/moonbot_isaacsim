#!/usr/bin/env python3
"""
Standalone Isaac Sim 6.0.1 script that displays a RealSense D435 textured
depth point cloud, similar to the RealSense Viewer point-cloud view.

Run on the Isaac Sim machine:
  conda activate env_isaacsim
  python /home/nvidia/isaacsim_realworld/scripts/realsense_colored_pointcloud_isaacsim.py
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Optional, Tuple

import numpy as np


DEFAULT_WORLD = "/home/nvidia/isaacsim_realworld/assets/sim_world.usd"
JETSON_LIBGOMP = "/lib/aarch64-linux-gnu/libgomp.so.1"


def log(message: str) -> None:
    print(f"[RealSense PointCloud {time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


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
    parser = argparse.ArgumentParser(description="Show a colored RealSense D435 point cloud in Isaac Sim.")
    parser.add_argument("--world", default=DEFAULT_WORLD, help="USD world to open.")
    parser.add_argument("--depth-width", type=int, default=640, help="Depth stream width.")
    parser.add_argument("--depth-height", type=int, default=480, help="Depth stream height.")
    parser.add_argument("--color-width", type=int, default=640, help="Color stream width.")
    parser.add_argument("--color-height", type=int, default=480, help="Color stream height.")
    parser.add_argument("--fps", type=int, default=30, help="Depth/color stream FPS.")
    parser.add_argument("--min-distance", type=float, default=3.0, help="Minimum depth distance in meters.")
    parser.add_argument("--max-distance", type=float, default=10.0, help="Maximum depth distance in meters.")
    parser.add_argument("--max-points", type=int, default=60000, help="Maximum drawn points per frame.")
    parser.add_argument("--point-size", type=float, default=3.0, help="DebugDraw point size in screen pixels.")
    parser.add_argument("--update-interval", type=float, default=0.08, help="Minimum seconds between redraws.")
    parser.add_argument(
        "--origin",
        type=float,
        nargs=3,
        default=(0.0, 0.0, 1.0),
        metavar=("X", "Y", "Z"),
        help="Isaac world-space origin for the RealSense camera frame.",
    )
    parser.add_argument("--scale", type=float, default=1.0, help="Scale applied to point positions.")
    parser.add_argument(
        "--coordinate-mode",
        choices=("isaac", "camera"),
        default="isaac",
        help="isaac maps camera +Z to world +X and image down to world -Z; camera keeps raw RealSense axes.",
    )
    parser.add_argument("--headless", action="store_true", help="Run Isaac Sim without UI.")
    parser.add_argument(
        "--exit-after-frames",
        type=int,
        default=0,
        help="If > 0, exit after drawing this many point-cloud frames. Useful for testing.",
    )
    return parser.parse_args()


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


def enable_debug_draw():
    import omni.kit.app

    extension_manager = omni.kit.app.get_app().get_extension_manager()
    try:
        extension_manager.set_extension_enabled_immediate("isaacsim.util.debug_draw", True)
    except Exception as exc:
        log(f"DebugDraw extension enable warning: {exc}")

    from isaacsim.util.debug_draw import _debug_draw

    return _debug_draw.acquire_debug_draw_interface()


def start_realsense(args: argparse.Namespace):
    import pyrealsense2 as rs

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.depth, args.depth_width, args.depth_height, rs.format.z16, args.fps)
    config.enable_stream(rs.stream.color, args.color_width, args.color_height, rs.format.rgb8, args.fps)
    profile = pipeline.start(config)

    device = profile.get_device()
    depth_sensor = device.first_depth_sensor()
    depth_scale = float(depth_sensor.get_depth_scale())
    log(f"RealSense started: depth_scale={depth_scale}, device={device.get_info(rs.camera_info.name)}")

    # Match RealSense Viewer point-cloud texturing: calculate from depth and map texture from color.
    pointcloud = rs.pointcloud()
    return pipeline, pointcloud


def wait_for_pointcloud_frame(pipeline, pointcloud, timeout_ms: int = 5000):
    frames = pipeline.wait_for_frames(timeout_ms)
    depth_frame = frames.get_depth_frame()
    color_frame = frames.get_color_frame()
    if not depth_frame or not color_frame:
        raise RuntimeError("Missing depth or color frame from RealSense.")

    pointcloud.map_to(color_frame)
    rs_points = pointcloud.calculate(depth_frame)

    vertices = np.asanyarray(rs_points.get_vertices()).view(np.float32).reshape(-1, 3)
    texcoords = np.asanyarray(rs_points.get_texture_coordinates()).view(np.float32).reshape(-1, 2)
    color_image = np.asanyarray(color_frame.get_data())
    return vertices, texcoords, color_image


def sample_point_colors(texcoords: np.ndarray, color_image: np.ndarray) -> np.ndarray:
    height, width = color_image.shape[:2]
    u = np.clip((texcoords[:, 0] * width).astype(np.int32), 0, width - 1)
    v = np.clip((texcoords[:, 1] * height).astype(np.int32), 0, height - 1)
    rgb = color_image[v, u].astype(np.float32) / 255.0
    alpha = np.ones((rgb.shape[0], 1), dtype=np.float32)
    return np.concatenate((rgb, alpha), axis=1)


def transform_points(vertices: np.ndarray, args: argparse.Namespace) -> np.ndarray:
    scale = np.float32(args.scale)
    origin = np.asarray(args.origin, dtype=np.float32)

    if args.coordinate_mode == "camera":
        transformed = vertices.astype(np.float32, copy=True) * scale
    else:
        # RealSense camera frame: +X right, +Y down, +Z forward.
        # Isaac world default: +X forward, +Y left, +Z up.
        transformed = np.empty_like(vertices, dtype=np.float32)
        transformed[:, 0] = vertices[:, 2] * scale
        transformed[:, 1] = -vertices[:, 0] * scale
        transformed[:, 2] = -vertices[:, 1] * scale

    transformed += origin
    return transformed


def build_draw_buffers(
    vertices: np.ndarray,
    texcoords: np.ndarray,
    color_image: np.ndarray,
    args: argparse.Namespace,
) -> Tuple[list, list, list, int]:
    z = vertices[:, 2]
    valid = (
        np.isfinite(vertices).all(axis=1)
        & (z >= args.min_distance)
        & (z <= args.max_distance)
        & np.isfinite(texcoords).all(axis=1)
        & (texcoords[:, 0] >= 0.0)
        & (texcoords[:, 0] <= 1.0)
        & (texcoords[:, 1] >= 0.0)
        & (texcoords[:, 1] <= 1.0)
    )

    valid_indices = np.flatnonzero(valid)
    valid_count = int(valid_indices.size)
    if valid_count == 0:
        return [], [], [], 0

    if args.max_points > 0 and valid_count > args.max_points:
        pick = np.linspace(0, valid_count - 1, args.max_points, dtype=np.int64)
        valid_indices = valid_indices[pick]

    selected_vertices = vertices[valid_indices]
    selected_texcoords = texcoords[valid_indices]

    draw_points = transform_points(selected_vertices, args)
    draw_colors = sample_point_colors(selected_texcoords, color_image)
    sizes = np.full((draw_points.shape[0],), float(args.point_size), dtype=np.float32)

    return draw_points.tolist(), draw_colors.tolist(), sizes.tolist(), valid_count


def main() -> int:
    args = parse_args()
    if args.min_distance <= 0 or args.max_distance <= args.min_distance:
        raise ValueError("--max-distance must be greater than --min-distance.")
    if args.update_interval <= 0:
        raise ValueError("--update-interval must be greater than 0.")

    reexec_with_jetson_libgomp_if_needed()

    from isaacsim import SimulationApp

    simulation_app = SimulationApp({"headless": bool(args.headless)})
    pipeline = None
    draw = None

    try:
        log(f"Opening world: {args.world}")
        open_usd_stage(simulation_app, args.world)

        draw = enable_debug_draw()
        pipeline, pointcloud = start_realsense(args)

        # Drop startup frames while auto exposure settles.
        for _ in range(10):
            pipeline.wait_for_frames(5000)

        next_draw = 0.0
        drawn_frames = 0
        last_log = time.monotonic()

        while simulation_app.is_running():
            now = time.monotonic()
            if now >= next_draw:
                vertices, texcoords, color_image = wait_for_pointcloud_frame(pipeline, pointcloud)
                points, colors, sizes, valid_count = build_draw_buffers(vertices, texcoords, color_image, args)
                draw.clear_points()
                if points:
                    draw.draw_points(points, colors, sizes)
                drawn_frames += 1
                next_draw = now + args.update_interval

                if now - last_log >= 5.0 or args.exit_after_frames:
                    log(
                        f"Draw frame {drawn_frames}: drawn={len(points)}, valid={valid_count}, "
                        f"distance={args.min_distance}-{args.max_distance}m"
                    )
                    last_log = now

                if args.exit_after_frames > 0 and drawn_frames >= args.exit_after_frames:
                    log(f"Exiting after {drawn_frames} drawn frame(s).")
                    break

            simulation_app.update()

    except KeyboardInterrupt:
        log("Interrupted by user.")
    finally:
        if pipeline is not None:
            pipeline.stop()
        if draw is not None:
            try:
                draw.clear_points()
            except Exception:
                pass
        simulation_app.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
