"""
Run this inside an already-open Isaac Sim GUI through Window > Script Editor.

It opens the target USD world, creates/updates a UsdGeom.Points prim, and
refreshes /home/nvidia/DAP/data/point/latest.pcd every 5 seconds.
"""

from __future__ import annotations

import asyncio
import builtins
import io
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import omni.kit.app
import omni.usd
from pxr import Gf, Sdf, UsdGeom, Vt


WORLD_PATH = "/home/nvidia/isaacsim_realworld/assets/sim_world.usd"
PCD_PATH = "/home/nvidia/DAP/data/point/latest.pcd"
PRIM_PATH = "/World/DynamicPCDBackgroundInstancer"
REFRESH_SECONDS = 5.0
SPHERE_RADIUS = 0.006
COLOR_LEVELS = 6
MAX_POINTS = 0  # Set to e.g. 200000 if the point cloud becomes too heavy.
FALLBACK_COLOR = (0.55, 0.75, 1.0)


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
    print(f"[PCD Background {time.strftime('%H:%M:%S')}] {message}", flush=True)


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
        meta[key] = parts[1:]
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
        points = int(meta.get("WIDTH", ["0"])[0]) * int(meta.get("HEIGHT", ["1"])[0])

    data_values = meta.get("DATA", [])
    if not data_values:
        raise ValueError("PCD DATA line is missing a storage type.")

    return PCDHeader(fields, sizes, types, counts, points, data_values[0].lower(), offset)


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
                raise ValueError(f"Unsupported float size {size} for field {field}.")
        elif type_code == "I":
            dtype = np.dtype(f"<i{size}")
        elif type_code == "U":
            dtype = np.dtype(f"<u{size}")
        else:
            raise ValueError(f"Unsupported PCD field type {type_code} for field {field}.")

        dtype_fields.append((field, dtype) if count == 1 else (field, dtype, (count,)))
    return np.dtype(dtype_fields)


def unpack_rgb(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values).reshape(-1)
    if np.issubdtype(values.dtype, np.floating):
        finite = values[np.isfinite(values)]
        if finite.size > 0 and np.nanmax(np.abs(finite)) > 1.0 and np.allclose(finite, np.rint(finite), atol=0.01):
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


def colors_from_ascii(table: np.ndarray, header: PCDHeader) -> Optional[np.ndarray]:
    columns = field_columns(header)
    for field in ("rgb", "rgba"):
        if field in columns and isinstance(columns[field], int):
            return unpack_rgb(table[:, columns[field]])
    return None


def colors_from_binary(records: np.ndarray) -> Optional[np.ndarray]:
    names = set(records.dtype.names or [])
    for field in ("rgb", "rgba"):
        if field in names:
            return unpack_rgb(records[field])
    return None


def read_pcd(path: str) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    with open(path, "rb") as stream:
        blob = stream.read()

    header = parse_pcd_header(blob)
    payload = blob[header.payload_offset:]

    if not {"x", "y", "z"}.issubset(set(header.fields)):
        raise ValueError("PCD must contain x, y, and z fields.")

    if header.data == "ascii":
        table = np.loadtxt(io.BytesIO(payload), dtype=np.float64, ndmin=2)
        columns = field_columns(header)
        xyz = table[:, [columns["x"], columns["y"], columns["z"]]].astype(np.float32)
        colors = colors_from_ascii(table, header)
    elif header.data == "binary":
        dtype = pcd_numpy_dtype(header)
        expected_bytes = header.points * dtype.itemsize
        if len(payload) < expected_bytes:
            raise ValueError(f"Incomplete binary PCD payload: got {len(payload)}, expected {expected_bytes}.")
        records = np.frombuffer(payload[:expected_bytes], dtype=dtype, count=header.points)
        xyz = np.column_stack((records["x"], records["y"], records["z"])).astype(np.float32)
        colors = colors_from_binary(records)
    else:
        raise ValueError(f"Unsupported PCD DATA type: {header.data}. Use ascii or binary.")

    finite_mask = np.isfinite(xyz).all(axis=1)
    xyz = xyz[finite_mask]
    if colors is not None and colors.shape[0] == finite_mask.shape[0]:
        colors = colors[finite_mask].astype(np.float32, copy=False)

    if MAX_POINTS > 0 and xyz.shape[0] > MAX_POINTS:
        indices = np.linspace(0, xyz.shape[0] - 1, MAX_POINTS, dtype=np.int64)
        xyz = xyz[indices]
        colors = colors[indices] if colors is not None else None

    return xyz, colors


def to_vt_vec3f_array(array: np.ndarray):
    array = np.ascontiguousarray(array, dtype=np.float32)
    try:
        return Vt.Vec3fArray.FromNumpy(array)
    except Exception:
        return [Gf.Vec3f(float(x), float(y), float(z)) for x, y, z in array]


def to_vt_float_array(array: np.ndarray):
    array = np.ascontiguousarray(array, dtype=np.float32)
    try:
        return Vt.FloatArray.FromNumpy(array)
    except Exception:
        return [float(value) for value in array]


async def open_world_if_needed() -> None:
    context = omni.usd.get_context()
    stage = context.get_stage()
    current_identifier = stage.GetRootLayer().identifier if stage else ""

    if WORLD_PATH not in current_identifier:
        log(f"Opening world: {WORLD_PATH}")
        if not context.open_stage(WORLD_PATH):
            raise RuntimeError(f"Failed to open USD world: {WORLD_PATH}")

        while context.get_stage() is None:
            await omni.kit.app.get_app().next_update_async()

        try:
            while context.is_loading():
                await omni.kit.app.get_app().next_update_async()
        except Exception:
            for _ in range(5):
                await omni.kit.app.get_app().next_update_async()


def ensure_instancer_prim():
    stage = omni.usd.get_context().get_stage()
    if stage is None:
        raise RuntimeError("No USD stage is open.")

    prim = stage.GetPrimAtPath(PRIM_PATH)
    if prim.IsValid() and prim.GetTypeName() != "PointInstancer":
        stage.RemovePrim(PRIM_PATH)

    instancer = UsdGeom.PointInstancer.Define(stage, PRIM_PATH)
    instancer.CreatePurposeAttr().Set(UsdGeom.Tokens.render)
    instancer.CreatePositionsAttr()
    instancer.CreateProtoIndicesAttr()
    instancer.CreateIdsAttr()
    omni.usd.get_context().get_selection().set_selected_prim_paths([PRIM_PATH], True)
    return instancer


def to_vt_int_array(array: np.ndarray):
    array = np.ascontiguousarray(array, dtype=np.int32)
    try:
        return Vt.IntArray.FromNumpy(array)
    except Exception:
        return [int(value) for value in array]


def to_vt_int64_array(array: np.ndarray):
    array = np.ascontiguousarray(array, dtype=np.int64)
    try:
        return Vt.Int64Array.FromNumpy(array)
    except Exception:
        return [int(value) for value in array]


def quantize_colors(colors: Optional[np.ndarray]) -> Tuple[np.ndarray, np.ndarray]:
    if colors is None or colors.shape[0] == 0:
        return np.asarray([FALLBACK_COLOR], dtype=np.float32), np.zeros((0,), dtype=np.int32)

    levels = int(np.clip(COLOR_LEVELS, 2, 16))
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
    from pxr import UsdShade

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


def rebuild_instancer_prototypes(instancer, palette: np.ndarray) -> None:
    from pxr import UsdShade

    stage = instancer.GetPrim().GetStage()
    proto_scope_path = f"{PRIM_PATH}/Prototypes"
    material_scope_path = f"{PRIM_PATH}/Materials"

    stage.RemovePrim(proto_scope_path)
    stage.RemovePrim(material_scope_path)
    UsdGeom.Scope.Define(stage, proto_scope_path)
    UsdGeom.Scope.Define(stage, material_scope_path)

    targets = []
    for index, color in enumerate(palette):
        proto_path = f"{proto_scope_path}/PointSphere_{index:03d}"
        material_path = f"{material_scope_path}/PointMaterial_{index:03d}"
        sphere = UsdGeom.Sphere.Define(stage, proto_path)
        sphere.CreateRadiusAttr().Set(float(SPHERE_RADIUS))
        sphere.CreateDisplayColorPrimvar(UsdGeom.Tokens.constant).Set(
            [Gf.Vec3f(float(color[0]), float(color[1]), float(color[2]))]
        )
        material = create_preview_material(stage, material_path, color)
        UsdShade.MaterialBindingAPI(sphere.GetPrim()).Bind(material)
        targets.append(Sdf.Path(proto_path))

    instancer.GetPrototypesRel().SetTargets(targets)


def update_instancer(instancer, xyz: np.ndarray, colors: Optional[np.ndarray]) -> int:
    count = int(xyz.shape[0])
    if colors is not None and colors.shape[0] != count:
        colors = None

    palette, proto_indices = quantize_colors(colors)
    if count > 0 and proto_indices.shape[0] == 0:
        proto_indices = np.zeros((count,), dtype=np.int32)

    rebuild_instancer_prototypes(instancer, palette)
    instancer.GetPositionsAttr().Set(to_vt_vec3f_array(xyz))
    instancer.GetProtoIndicesAttr().Set(to_vt_int_array(proto_indices))
    instancer.GetIdsAttr().Set(to_vt_int64_array(np.arange(count, dtype=np.int64)))

    if xyz.shape[0] > 0:
        min_xyz = xyz.min(axis=0)
        max_xyz = xyz.max(axis=0)
        instancer.CreateExtentAttr().Set(
            [
                Gf.Vec3f(float(min_xyz[0]), float(min_xyz[1]), float(min_xyz[2])),
                Gf.Vec3f(float(max_xyz[0]), float(max_xyz[1]), float(max_xyz[2])),
            ]
        )
    return int(palette.shape[0])


class PCDBackgroundRefresher:
    def __init__(self):
        self.running = True
        self.task = None

    def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()

    async def run(self):
        await open_world_if_needed()
        instancer = ensure_instancer_prim()
        log(f"Using point cloud instancer prim: {PRIM_PATH}")

        while self.running:
            started = time.monotonic()
            try:
                xyz, colors = read_pcd(PCD_PATH)
                color_bins = update_instancer(instancer, xyz, colors)
                log(
                    "Updated "
                    f"{xyz.shape[0]} points, color_bins={color_bins}, radius={SPHERE_RADIUS}, "
                    f"min={xyz.min(axis=0).round(3).tolist()}, "
                    f"max={xyz.max(axis=0).round(3).tolist()}"
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log(f"Refresh failed: {exc}")

            while self.running and time.monotonic() - started < REFRESH_SECONDS:
                await omni.kit.app.get_app().next_update_async()


def start():
    previous = getattr(builtins, "_pcd_background_refresher", None)
    if previous is not None:
        previous.stop()

    refresher = PCDBackgroundRefresher()
    builtins._pcd_background_refresher = refresher
    refresher.task = asyncio.ensure_future(refresher.run())
    log("Started. To stop it, run: builtins._pcd_background_refresher.stop()")


start()
