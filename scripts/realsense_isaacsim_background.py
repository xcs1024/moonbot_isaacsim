"""
Run inside an already-open Isaac Sim GUI through Window > Script Editor:

    exec(open("/home/nvidia/isaacsim_realworld/scripts/realsense_isaacsim_background.py").read())

This creates a textured background plane in the USD stage and refreshes the
texture from the RealSense color stream. It does not start another Isaac Sim
process.
"""

from __future__ import annotations

import asyncio
import builtins
import os
import time
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
import omni.kit.app
import omni.usd
from pxr import Gf, Sdf, UsdGeom, UsdShade, Vt


WORLD_PATH = "/home/nvidia/isaacsim_realworld/assets/sim_world.usd"

# RealSense D435 color node on the current machine, confirmed by v4l2-ctl.
VIDEO_DEVICE = "/dev/video4"
CAPTURE_WIDTH = 640
CAPTURE_HEIGHT = 480
CAPTURE_FPS = 30

# Texture update rate. 0.1 = 10 FPS, 0.2 = 5 FPS.
UPDATE_INTERVAL_SECONDS = 0.12
JPEG_QUALITY = 85
FRAME_DIR = "/tmp/isaacsim_realsense_live"
KEEP_FRAME_FILES = 40

# A vertical 4:3 screen behind the table area. Select and move this prim if needed.
PLANE_PATH = "/World/RealSenseLiveBackground"
MATERIAL_PATH = "/World/RealSenseLiveBackground_Material"
PLANE_CENTER = (1.5, -2.8, 0.9)
PLANE_WIDTH = 3.2

# Frame post-processing. Use ROTATE_90_CLOCKWISE if your physical mount needs it.
ROTATE: Optional[int] = None
FLIP_CODE: Optional[int] = None  # 0 vertical, 1 horizontal, -1 both.
AUTO_CONTRAST = False


def log(message: str) -> None:
    print(f"[RealSense BG {time.strftime('%H:%M:%S')}] {message}", flush=True)


async def open_world_if_needed() -> None:
    context = omni.usd.get_context()
    stage = context.get_stage()
    current_identifier = stage.GetRootLayer().identifier if stage else ""

    if stage is not None and WORLD_PATH in current_identifier:
        return

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


def make_plane_points(width: float, image_shape: Tuple[int, int, int]):
    height_px, width_px = image_shape[:2]
    aspect = height_px / float(width_px)
    height = width * aspect
    cx, cy, cz = PLANE_CENTER
    half_w = width * 0.5
    half_h = height * 0.5
    return [
        Gf.Vec3f(cx - half_w, cy, cz - half_h),
        Gf.Vec3f(cx + half_w, cy, cz - half_h),
        Gf.Vec3f(cx + half_w, cy, cz + half_h),
        Gf.Vec3f(cx - half_w, cy, cz + half_h),
    ]


def create_or_update_plane(stage, image_shape: Tuple[int, int, int]):
    if stage.GetPrimAtPath(PLANE_PATH).IsValid():
        stage.RemovePrim(PLANE_PATH)

    mesh = UsdGeom.Mesh.Define(stage, PLANE_PATH)
    mesh.CreatePointsAttr().Set(make_plane_points(PLANE_WIDTH, image_shape))
    mesh.CreateFaceVertexCountsAttr().Set([4])
    mesh.CreateFaceVertexIndicesAttr().Set([0, 1, 2, 3])
    mesh.CreateDoubleSidedAttr().Set(True)
    mesh.CreateExtentAttr().Set(
        [
            Gf.Vec3f(PLANE_CENTER[0] - PLANE_WIDTH * 0.5, PLANE_CENTER[1], PLANE_CENTER[2] - PLANE_WIDTH * 0.5),
            Gf.Vec3f(PLANE_CENTER[0] + PLANE_WIDTH * 0.5, PLANE_CENTER[1], PLANE_CENTER[2] + PLANE_WIDTH * 0.5),
        ]
    )

    st = UsdGeom.PrimvarsAPI(mesh.GetPrim()).CreatePrimvar(
        "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.varying
    )
    # Flip V so the OpenCV image is upright on the plane.
    st.Set(Vt.Vec2fArray([Gf.Vec2f(0, 1), Gf.Vec2f(1, 1), Gf.Vec2f(1, 0), Gf.Vec2f(0, 0)]))
    st.SetInterpolation(UsdGeom.Tokens.varying)
    return mesh


def create_texture_material(stage, first_texture_path: str):
    if stage.GetPrimAtPath(MATERIAL_PATH).IsValid():
        stage.RemovePrim(MATERIAL_PATH)

    material = UsdShade.Material.Define(stage, MATERIAL_PATH)

    st_reader = UsdShade.Shader.Define(stage, MATERIAL_PATH + "/PrimvarReader_st")
    st_reader.CreateIdAttr("UsdPrimvarReader_float2")
    st_reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
    st_reader.CreateOutput("result", Sdf.ValueTypeNames.Float2)

    texture = UsdShade.Shader.Define(stage, MATERIAL_PATH + "/Texture")
    texture.CreateIdAttr("UsdUVTexture")
    texture_file_input = texture.CreateInput("file", Sdf.ValueTypeNames.Asset)
    texture_file_input.Set(Sdf.AssetPath(first_texture_path))
    texture.CreateInput("sourceColorSpace", Sdf.ValueTypeNames.Token).Set("sRGB")
    texture.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(st_reader.ConnectableAPI(), "result")
    texture.CreateOutput("rgb", Sdf.ValueTypeNames.Color3f)

    shader = UsdShade.Shader.Define(stage, MATERIAL_PATH + "/PreviewSurface")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(texture.ConnectableAPI(), "rgb")
    shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(texture.ConnectableAPI(), "rgb")
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.75)
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
    shader.CreateOutput("surface", Sdf.ValueTypeNames.Token)
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")

    return material, texture_file_input


def bind_material(mesh, material) -> None:
    UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(material, UsdShade.Tokens.strongerThanDescendants)


def open_capture():
    cap = cv2.VideoCapture(VIDEO_DEVICE, cv2.CAP_V4L2)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open RealSense video device: {VIDEO_DEVICE}")

    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUYV"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, CAPTURE_FPS)
    cap.set(cv2.CAP_PROP_AUTO_WB, 1)
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3)
    return cap


def process_frame(frame: np.ndarray) -> np.ndarray:
    if ROTATE is not None:
        frame = cv2.rotate(frame, ROTATE)
    if FLIP_CODE is not None:
        frame = cv2.flip(frame, FLIP_CODE)
    if AUTO_CONTRAST:
        frame = cv2.convertScaleAbs(frame, alpha=1.15, beta=4)
    return frame


def write_frame(frame: np.ndarray, sequence: int) -> str:
    Path(FRAME_DIR).mkdir(parents=True, exist_ok=True)
    path = os.path.join(FRAME_DIR, f"realsense_{sequence:06d}.jpg")
    ok = cv2.imwrite(path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(JPEG_QUALITY)])
    if not ok:
        raise RuntimeError(f"Failed to write texture frame: {path}")

    old_sequence = sequence - KEEP_FRAME_FILES
    if old_sequence >= 0:
        old_path = os.path.join(FRAME_DIR, f"realsense_{old_sequence:06d}.jpg")
        try:
            os.remove(old_path)
        except FileNotFoundError:
            pass
    return path


def read_first_frame(cap) -> np.ndarray:
    last_error = None
    for _ in range(30):
        ok, frame = cap.read()
        if ok and frame is not None and frame.size:
            return process_frame(frame)
        last_error = "empty frame"
        time.sleep(0.03)
    raise RuntimeError(f"Could not read first RealSense frame from {VIDEO_DEVICE}: {last_error}")


class RealSenseBackground:
    def __init__(self):
        self.running = True
        self.task = None
        self.cap = None

    def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        log("Stopped.")

    async def run(self):
        await open_world_if_needed()
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            raise RuntimeError("No USD stage is open.")

        self.cap = open_capture()
        first_frame = read_first_frame(self.cap)
        first_path = write_frame(first_frame, 0)

        mesh = create_or_update_plane(stage, first_frame.shape)
        material, texture_file_input = create_texture_material(stage, first_path)
        bind_material(mesh, material)
        omni.usd.get_context().get_selection().set_selected_prim_paths([PLANE_PATH], True)

        log(f"Started RealSense background: {VIDEO_DEVICE}, plane={PLANE_PATH}, first_texture={first_path}")

        sequence = 1
        last_log = time.monotonic()
        while self.running:
            started = time.monotonic()
            try:
                ok, frame = self.cap.read()
                if not ok or frame is None or not frame.size:
                    log("Skipped empty RealSense frame.")
                else:
                    frame = process_frame(frame)
                    frame_path = write_frame(frame, sequence)
                    texture_file_input.Set(Sdf.AssetPath(frame_path))
                    sequence += 1
                    if time.monotonic() - last_log > 5.0:
                        log(f"Updated {sequence} texture frames, latest={frame_path}")
                        last_log = time.monotonic()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log(f"Update failed: {exc}")

            while self.running and time.monotonic() - started < UPDATE_INTERVAL_SECONDS:
                await omni.kit.app.get_app().next_update_async()

        if self.cap is not None:
            self.cap.release()
            self.cap = None


def start():
    previous = getattr(builtins, "_realsense_background", None)
    if previous is not None:
        previous.stop()

    background = RealSenseBackground()
    builtins._realsense_background = background
    background.task = asyncio.ensure_future(background.run())
    log("Starting. To stop: builtins._realsense_background.stop()")


start()
