#!/usr/bin/env python3
"""
Load a USD world in Isaac Sim and refresh a PCD point cloud as a dynamic
background every few seconds.

Default target paths:
  world: /home/nvidia/isaacsim_realworld/assets/sim_world.usd
  pcd:   /home/nvidia/DAP/data/point/latest.pcd

Run on the Isaac Sim machine:
  conda activate env_isaacsim
  python realtime_pcd_background.py
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

import numpy as np


DEFAULT_WORLD = "/home/nvidia/isaacsim_realworld/assets/sim_world.usd"
DEFAULT_PCD = "/home/nvidia/DAP/data/point/latest.pcd"
DEFAULT_PRIM_PATH = "/World/DynamicPointCloudBackground"
DEFAULT_INSTANCER_PATH = "/World/DynamicPCDBackgroundInstancer"
JETSON_LIBGOMP = "/lib/aarch64-linux-gnu/libgomp.so.1"


@dataclass
class PCDHeader:
    fields: List[str]
    sizes: List[int]
    types: List[str]
    counts: List[int]
    points: int
    data: str
    payload_offset: int


def log(message: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh a PCD file into an Isaac Sim USD stage as UsdGeom.Points."
    )
    parser.add_argument("--world", default=DEFAULT_WORLD, help="USD world/stage to open.")
    parser.add_argument("--pcd", default=DEFAULT_PCD, help="PCD file to refresh.")
    parser.add_argument("--prim-path", default=DEFAULT_PRIM_PATH, help="USD prim path for the point cloud.")
    parser.add_argument(
        "--render-mode",
        choices=("instancer", "points"),
        default="instancer",
        help="Use PointInstancer spheres for reliable viewport visibility, or raw UsdGeom.Points.",
    )
    parser.add_argument(
        "--instancer-path",
        default=DEFAULT_INSTANCER_PATH,
        help="USD prim path used when --render-mode instancer is active.",
    )
    parser.add_argument("--refresh", type=float, default=5.0, help="Refresh interval in seconds.")
    parser.add_argument("--point-size", type=float, default=0.08, help="Rendered point width in stage units.")
    parser.add_argument("--sphere-radius", type=float, default=0.006, help="Instanced sphere radius in stage units.")
    parser.add_argument(
        "--color-levels",
        type=int,
        default=6,
        help="Per-channel color quantization levels for instancer mode. 6 gives up to 216 color prototypes.",
    )
    parser.add_argument(
        "--color",
        type=float,
        nargs=3,
        default=(0.55, 0.75, 1.0),
        metavar=("R", "G", "B"),
        help="Fallback constant RGB color, each component in [0, 1].",
    )
    parser.add_argument("--no-pcd-colors", action="store_true", help="Ignore rgb/rgba/intensity fields in the PCD.")
    parser.add_argument(
        "--max-points",
        type=int,
        default=0,
        help="If > 0, evenly downsample to at most this many points before rendering.",
    )
    parser.add_argument("--scale", type=float, default=1.0, help="Uniform scale applied to xyz points.")
    parser.add_argument(
        "--offset",
        type=float,
        nargs=3,
        default=(0.0, 0.0, 0.0),
        metavar=("X", "Y", "Z"),
        help="XYZ offset applied after scale.",
    )
    parser.add_argument("--headless", action="store_true", help="Run Isaac Sim without a UI.")
    parser.add_argument(
        "--renderer",
        default=None,
        help="Optional Isaac Sim renderer name. Leave unset to use the environment default.",
    )
    parser.add_argument("--no-play", action="store_true", help="Do not start the Isaac Sim timeline.")
    parser.add_argument(
        "--exit-after-refreshes",
        type=int,
        default=0,
        help="If > 0, exit after this many successful PCD refreshes. Default runs continuously.",
    )
    return parser.parse_args()


def reexec_with_jetson_libgomp_if_needed() -> None:
    if not os.path.exists(JETSON_LIBGOMP):
        return

    ld_preload = os.environ.get("LD_PRELOAD", "")
    preload_entries = [entry for entry in ld_preload.split(":") if entry]
    if JETSON_LIBGOMP in preload_entries:
        return

    preload_entries.append(JETSON_LIBGOMP)
    os.environ["LD_PRELOAD"] = ":".join(preload_entries)
    log(f"Restarting with LD_PRELOAD={os.environ['LD_PRELOAD']}")
    os.execv(sys.executable, [sys.executable] + sys.argv)


def parse_pcd_header(blob: bytes) -> PCDHeader:
    meta: Dict[str, List[str]] = {}
    offset = 0

    for raw_line in blob.splitlines(keepends=True):
        offset += len(raw_line)
        line = raw_line.decode("ascii", errors="replace").strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        key = parts[0].upper()
        values = parts[1:]
        meta[key] = values

        if key == "DATA":
            break
    else:
        raise ValueError("PCD header does not contain a DATA line.")

    fields = meta.get("FIELDS") or meta.get("COLUMNS")
    if not fields:
        raise ValueError("PCD header is missing FIELDS.")

    sizes = [int(v) for v in meta.get("SIZE", ["4"] * len(fields))]
    types = [v.upper() for v in meta.get("TYPE", ["F"] * len(fields))]
    counts = [int(v) for v in meta.get("COUNT", ["1"] * len(fields))]

    if not (len(fields) == len(sizes) == len(types) == len(counts)):
        raise ValueError("PCD FIELDS, SIZE, TYPE, and COUNT lengths do not match.")

    if "POINTS" in meta:
        points = int(meta["POINTS"][0])
    else:
        width = int(meta.get("WIDTH", ["0"])[0])
        height = int(meta.get("HEIGHT", ["1"])[0])
        points = width * height

    data_values = meta.get("DATA", [])
    if not data_values:
        raise ValueError("PCD DATA line is missing a storage type.")

    return PCDHeader(
        fields=fields,
        sizes=sizes,
        types=types,
        counts=counts,
        points=points,
        data=data_values[0].lower(),
        payload_offset=offset,
    )


def field_columns(header: PCDHeader) -> Dict[str, Union[int, slice]]:
    columns: Dict[str, Union[int, slice]] = {}
    index = 0
    for field, count in zip(header.fields, header.counts):
        columns[field] = index if count == 1 else slice(index, index + count)
        index += count
    return columns


def pcd_numpy_dtype(header: PCDHeader) -> np.dtype:
    dtype_fields = []
    for field, size, type_code, count in zip(header.fields, header.sizes, header.types, header.counts):
        if type_code == "F":
            if size == 4:
                dtype = np.dtype("<f4")
            elif size == 8:
                dtype = np.dtype("<f8")
            else:
                raise ValueError(f"Unsupported PCD float size {size} for field {field}.")
        elif type_code == "I":
            dtype = np.dtype(f"<i{size}")
        elif type_code == "U":
            dtype = np.dtype(f"<u{size}")
        else:
            raise ValueError(f"Unsupported PCD field type {type_code} for field {field}.")

        if count == 1:
            dtype_fields.append((field, dtype))
        else:
            dtype_fields.append((field, dtype, (count,)))

    return np.dtype(dtype_fields)


def unpack_rgb(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values).reshape(-1)

    if np.issubdtype(values.dtype, np.floating):
        finite_values = values[np.isfinite(values)]
        looks_like_integer_rgb = (
            finite_values.size > 0
            and np.nanmax(np.abs(finite_values)) > 1.0
            and np.allclose(finite_values, np.rint(finite_values), atol=0.01)
        )
        if looks_like_integer_rgb:
            packed = values.astype(np.uint32, copy=False)
        else:
            packed = values.astype(np.float32, copy=False).view(np.uint32)
    else:
        packed = values.astype(np.uint32, copy=False)

    rgb = np.empty((packed.shape[0], 3), dtype=np.float32)
    rgb[:, 0] = ((packed >> 16) & 255) / 255.0
    rgb[:, 1] = ((packed >> 8) & 255) / 255.0
    rgb[:, 2] = (packed & 255) / 255.0
    return rgb


def normalize_intensity(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32).reshape(-1)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        gray = np.full(values.shape, 0.7, dtype=np.float32)
    else:
        lo, hi = np.percentile(finite, [1.0, 99.0])
        if hi <= lo:
            gray = np.full(values.shape, 0.7, dtype=np.float32)
        else:
            gray = np.clip((values - lo) / (hi - lo), 0.0, 1.0).astype(np.float32)
    return np.repeat(gray[:, None], 3, axis=1)


def colors_from_ascii(table: np.ndarray, header: PCDHeader) -> Optional[np.ndarray]:
    columns = field_columns(header)

    for field in ("rgb", "rgba"):
        if field in columns:
            column = columns[field]
            if isinstance(column, int):
                return unpack_rgb(table[:, column])

    if all(field in columns for field in ("r", "g", "b")):
        indices = [columns["r"], columns["g"], columns["b"]]
        if all(isinstance(index, int) for index in indices):
            rgb = table[:, indices].astype(np.float32)
            if np.nanmax(rgb) > 1.0:
                rgb /= 255.0
            return np.clip(rgb, 0.0, 1.0)

    if "intensity" in columns and isinstance(columns["intensity"], int):
        return normalize_intensity(table[:, columns["intensity"]])

    return None


def colors_from_binary(records: np.ndarray) -> Optional[np.ndarray]:
    names = set(records.dtype.names or [])

    for field in ("rgb", "rgba"):
        if field in names:
            return unpack_rgb(records[field])

    if {"r", "g", "b"}.issubset(names):
        rgb = np.column_stack((records["r"], records["g"], records["b"])).astype(np.float32)
        if np.nanmax(rgb) > 1.0:
            rgb /= 255.0
        return np.clip(rgb, 0.0, 1.0)

    if "intensity" in names:
        return normalize_intensity(records["intensity"])

    return None


def read_pcd(path: str, use_pcd_colors: bool) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    with open(path, "rb") as stream:
        blob = stream.read()

    header = parse_pcd_header(blob)
    payload = blob[header.payload_offset :]

    if not {"x", "y", "z"}.issubset(set(header.fields)):
        raise ValueError("PCD must contain x, y, and z fields.")

    if header.data == "ascii":
        table = np.loadtxt(io.BytesIO(payload), dtype=np.float64, ndmin=2)
        columns = field_columns(header)
        xyz_indices = [columns["x"], columns["y"], columns["z"]]
        if not all(isinstance(index, int) for index in xyz_indices):
            raise ValueError("x, y, and z fields must have COUNT 1.")
        xyz = table[:, xyz_indices].astype(np.float32)
        colors = colors_from_ascii(table, header) if use_pcd_colors else None

    elif header.data == "binary":
        dtype = pcd_numpy_dtype(header)
        expected_bytes = header.points * dtype.itemsize
        if len(payload) < expected_bytes:
            raise ValueError(
                f"PCD binary payload is incomplete: got {len(payload)} bytes, expected {expected_bytes}."
            )
        records = np.frombuffer(payload[:expected_bytes], dtype=dtype, count=header.points)
        xyz = np.column_stack((records["x"], records["y"], records["z"])).astype(np.float32)
        colors = colors_from_binary(records) if use_pcd_colors else None

    elif header.data == "binary_compressed":
        raise ValueError("binary_compressed PCD is not supported by this script. Save latest.pcd as ascii or binary.")
    else:
        raise ValueError(f"Unsupported PCD DATA storage type: {header.data}")

    finite_mask = np.isfinite(xyz).all(axis=1)
    xyz = xyz[finite_mask]
    if colors is not None and colors.shape[0] == finite_mask.shape[0]:
        colors = colors[finite_mask].astype(np.float32, copy=False)

    return xyz, colors


def downsample_evenly(xyz: np.ndarray, colors: Optional[np.ndarray], max_points: int) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    if max_points <= 0 or xyz.shape[0] <= max_points:
        return xyz, colors

    indices = np.linspace(0, xyz.shape[0] - 1, max_points, dtype=np.int64)
    return xyz[indices], colors[indices] if colors is not None else None


def to_vt_vec3f_array(array: np.ndarray):
    from pxr import Gf, Vt

    array = np.ascontiguousarray(array, dtype=np.float32)
    try:
        return Vt.Vec3fArray.FromNumpy(array)
    except Exception:
        return [Gf.Vec3f(float(x), float(y), float(z)) for x, y, z in array]


def to_vt_float_array(array: np.ndarray):
    from pxr import Vt

    array = np.ascontiguousarray(array, dtype=np.float32)
    try:
        return Vt.FloatArray.FromNumpy(array)
    except Exception:
        return [float(value) for value in array]


def open_usd_stage(simulation_app, usd_path: str, timeout_s: float = 120.0):
    import omni.usd

    usd_context = omni.usd.get_context()
    if not usd_context.open_stage(usd_path):
        raise RuntimeError(f"Failed to request opening USD stage: {usd_path}")

    start_time = time.monotonic()
    while time.monotonic() - start_time < timeout_s:
        simulation_app.update()
        stage = usd_context.get_stage()
        is_loading = False
        try:
            is_loading = bool(usd_context.is_loading())
        except Exception:
            is_loading = False
        if stage is not None and not is_loading:
            return stage
        time.sleep(0.05)

    raise TimeoutError(f"Timed out opening USD stage after {timeout_s:.1f}s: {usd_path}")


def ensure_points_prim(stage, prim_path: str):
    from pxr import UsdGeom
    import omni.usd

    prim = stage.GetPrimAtPath(prim_path)
    if prim.IsValid() and prim.GetTypeName() != "Points":
        raise RuntimeError(f"Prim already exists and is not a Points prim: {prim_path}")

    points = UsdGeom.Points.Define(stage, prim_path)
    points.CreatePurposeAttr().Set(UsdGeom.Tokens.render)
    points.CreatePointsAttr()
    points.CreateWidthsAttr()
    omni.usd.get_context().get_selection().set_selected_prim_paths([prim_path], True)
    return points


def ensure_instancer_prim(stage, instancer_path: str):
    from pxr import UsdGeom
    import omni.usd

    prim = stage.GetPrimAtPath(instancer_path)
    if prim.IsValid() and prim.GetTypeName() != "PointInstancer":
        stage.RemovePrim(instancer_path)

    instancer = UsdGeom.PointInstancer.Define(stage, instancer_path)
    instancer.CreatePurposeAttr().Set(UsdGeom.Tokens.render)
    instancer.CreatePositionsAttr()
    instancer.CreateProtoIndicesAttr()
    instancer.CreateIdsAttr()
    omni.usd.get_context().get_selection().set_selected_prim_paths([instancer_path], True)
    return instancer


def update_usd_points(points_prim, xyz: np.ndarray, colors: Optional[np.ndarray], point_size: float, fallback_color) -> None:
    from pxr import Gf, UsdGeom

    points_prim.GetPointsAttr().Set(to_vt_vec3f_array(xyz))
    widths = np.full((xyz.shape[0],), point_size, dtype=np.float32)
    points_prim.GetWidthsAttr().Set(to_vt_float_array(widths))

    if xyz.shape[0] > 0:
        min_xyz = xyz.min(axis=0)
        max_xyz = xyz.max(axis=0)
        points_prim.CreateExtentAttr().Set(
            [
                Gf.Vec3f(float(min_xyz[0]), float(min_xyz[1]), float(min_xyz[2])),
                Gf.Vec3f(float(max_xyz[0]), float(max_xyz[1]), float(max_xyz[2])),
            ]
        )

    if colors is not None and colors.shape[0] == xyz.shape[0]:
        color_primvar = points_prim.CreateDisplayColorPrimvar(UsdGeom.Tokens.vertex)
        color_primvar.Set(to_vt_vec3f_array(colors))
    else:
        color_primvar = points_prim.CreateDisplayColorPrimvar(UsdGeom.Tokens.constant)
        color_primvar.Set(
            [
                Gf.Vec3f(
                    float(fallback_color[0]),
                    float(fallback_color[1]),
                    float(fallback_color[2]),
                )
            ]
        )


def to_vt_int_array(array: np.ndarray):
    from pxr import Vt

    array = np.ascontiguousarray(array, dtype=np.int32)
    try:
        return Vt.IntArray.FromNumpy(array)
    except Exception:
        return [int(value) for value in array]


def to_vt_int64_array(array: np.ndarray):
    from pxr import Vt

    array = np.ascontiguousarray(array, dtype=np.int64)
    try:
        return Vt.Int64Array.FromNumpy(array)
    except Exception:
        return [int(value) for value in array]


def quantize_colors(
    colors: Optional[np.ndarray],
    color_levels: int,
    fallback_color,
) -> Tuple[np.ndarray, np.ndarray]:
    if colors is None or colors.shape[0] == 0:
        return np.asarray([fallback_color], dtype=np.float32), np.zeros((0,), dtype=np.int32)

    levels = int(np.clip(color_levels, 2, 16))
    rgb = np.nan_to_num(np.clip(colors.astype(np.float32, copy=False), 0.0, 1.0), nan=0.0)
    bins = np.clip(np.floor(rgb * levels), 0, levels - 1).astype(np.int32)
    keys = bins[:, 0] * levels * levels + bins[:, 1] * levels + bins[:, 2]
    unique_keys, proto_indices = np.unique(keys, return_inverse=True)
    palette_bins = np.column_stack(
        (
            unique_keys // (levels * levels),
            (unique_keys // levels) % levels,
            unique_keys % levels,
        )
    ).astype(np.float32)
    palette = (palette_bins + 0.5) / float(levels)
    return palette.astype(np.float32), proto_indices.astype(np.int32)


def create_preview_material(stage, material_path: str, color):
    from pxr import Gf, Sdf, UsdShade

    material = UsdShade.Material.Define(stage, material_path)
    shader = UsdShade.Shader.Define(stage, f"{material_path}/PreviewSurface")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(
        Gf.Vec3f(float(color[0]), float(color[1]), float(color[2]))
    )
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.7)
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return material


def rebuild_instancer_prototypes(instancer, palette: np.ndarray, radius: float) -> None:
    from pxr import Gf, Sdf, UsdGeom, UsdShade

    stage = instancer.GetPrim().GetStage()
    instancer_path = str(instancer.GetPrim().GetPath())
    proto_scope_path = f"{instancer_path}/Prototypes"
    material_scope_path = f"{instancer_path}/Materials"

    stage.RemovePrim(proto_scope_path)
    stage.RemovePrim(material_scope_path)
    UsdGeom.Scope.Define(stage, proto_scope_path)
    UsdGeom.Scope.Define(stage, material_scope_path)

    targets = []
    for index, color in enumerate(palette):
        proto_path = f"{proto_scope_path}/PointSphere_{index:03d}"
        material_path = f"{material_scope_path}/PointMaterial_{index:03d}"
        sphere = UsdGeom.Sphere.Define(stage, proto_path)
        sphere.CreateRadiusAttr().Set(float(radius))
        sphere.CreateDisplayColorPrimvar(UsdGeom.Tokens.constant).Set(
            [Gf.Vec3f(float(color[0]), float(color[1]), float(color[2]))]
        )
        material = create_preview_material(stage, material_path, color)
        UsdShade.MaterialBindingAPI(sphere.GetPrim()).Bind(material)
        targets.append(Sdf.Path(proto_path))

    instancer.GetPrototypesRel().SetTargets(targets)


def update_instancer_points(
    instancer,
    xyz: np.ndarray,
    colors: Optional[np.ndarray],
    radius: float,
    color_levels: int,
    fallback_color,
) -> int:
    from pxr import Gf

    count = int(xyz.shape[0])
    if colors is not None and colors.shape[0] != count:
        colors = None

    palette, proto_indices = quantize_colors(colors, color_levels, fallback_color)
    if count > 0 and proto_indices.shape[0] == 0:
        proto_indices = np.zeros((count,), dtype=np.int32)

    rebuild_instancer_prototypes(instancer, palette, radius)
    instancer.GetPositionsAttr().Set(to_vt_vec3f_array(xyz))
    instancer.GetProtoIndicesAttr().Set(to_vt_int_array(proto_indices))
    instancer.GetIdsAttr().Set(to_vt_int64_array(np.arange(count, dtype=np.int64)))

    if count > 0:
        min_xyz = xyz.min(axis=0)
        max_xyz = xyz.max(axis=0)
        instancer.CreateExtentAttr().Set(
            [
                Gf.Vec3f(float(min_xyz[0]), float(min_xyz[1]), float(min_xyz[2])),
                Gf.Vec3f(float(max_xyz[0]), float(max_xyz[1]), float(max_xyz[2])),
            ]
        )
    return int(palette.shape[0])


def load_pcd_for_stage(args: argparse.Namespace) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    xyz, colors = read_pcd(args.pcd, use_pcd_colors=not args.no_pcd_colors)
    xyz, colors = downsample_evenly(xyz, colors, args.max_points)

    if args.scale != 1.0:
        xyz = xyz * np.float32(args.scale)

    offset = np.asarray(args.offset, dtype=np.float32)
    if np.any(offset != 0.0):
        xyz = xyz + offset

    return xyz, colors


def load_and_update_points(args: argparse.Namespace, target_prim) -> int:
    xyz, colors = load_pcd_for_stage(args)
    if args.render_mode == "instancer":
        update_instancer_points(target_prim, xyz, colors, args.sphere_radius, args.color_levels, args.color)
    else:
        update_usd_points(target_prim, xyz, colors, args.point_size, args.color)
    return int(xyz.shape[0])


def main() -> int:
    args = parse_args()

    if args.refresh <= 0.0:
        raise ValueError("--refresh must be greater than 0.")

    launch_config = {"headless": bool(args.headless)}
    if args.renderer:
        launch_config["renderer"] = args.renderer

    reexec_with_jetson_libgomp_if_needed()

    from isaacsim import SimulationApp

    simulation_app = SimulationApp(launch_config)

    try:
        import omni.timeline

        log(f"Opening world: {args.world}")
        stage = open_usd_stage(simulation_app, args.world)
        if args.render_mode == "instancer":
            target_prim = ensure_instancer_prim(stage, args.instancer_path)
            log(f"Point cloud instancer prim: {args.instancer_path}")
        else:
            target_prim = ensure_points_prim(stage, args.prim_path)
            log(f"Point cloud points prim: {args.prim_path}")

        if not args.no_play:
            omni.timeline.get_timeline_interface().play()

        next_refresh = 0.0
        refresh_count = 0
        while simulation_app.is_running():
            now = time.monotonic()
            if now >= next_refresh:
                start = time.monotonic()
                try:
                    point_count = load_and_update_points(args, target_prim)
                    elapsed_ms = (time.monotonic() - start) * 1000.0
                    log(f"Refreshed {point_count} points from {args.pcd} in {elapsed_ms:.1f} ms.")
                    refresh_count += 1
                    if args.exit_after_refreshes > 0 and refresh_count >= args.exit_after_refreshes:
                        log(f"Exiting after {refresh_count} successful refresh(es).")
                        break
                except Exception as exc:
                    log(f"Refresh skipped: {exc}")
                next_refresh = now + args.refresh

            simulation_app.update()

    finally:
        simulation_app.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
