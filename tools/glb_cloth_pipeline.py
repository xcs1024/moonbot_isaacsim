#!/usr/bin/env python3
"""
Build an Isaac Sim cloth USD from a GLB garment.

Default behavior preserves the original visual mesh, UVs, and base-color texture,
and creates a separate low-cost hidden simulation mesh. This is the same pattern
Isaac/PhysX uses for deformable surface hierarchy:

    /World/clothes                  deformable root
    /World/clothes/model            visual mesh
    /World/clothes/simulationMesh   hidden cloth simulation mesh

Run inside the Isaac Sim Python environment so pxr and trimesh are available.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh
from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics, UsdShade, Vt


@dataclass
class MeshData:
    vertices: np.ndarray
    faces: np.ndarray
    uv: np.ndarray | None = None
    vertex_colors: np.ndarray | None = None
    base_color_texture: Path | None = None


def _as_mesh(glb_path: Path) -> trimesh.Trimesh:
    loaded = trimesh.load(str(glb_path), force="scene")
    if isinstance(loaded, trimesh.Scene):
        mesh = loaded.to_geometry()
    else:
        mesh = loaded
    if not isinstance(mesh, trimesh.Trimesh):
        raise TypeError(f"Unsupported GLB content: {type(mesh)!r}")
    mesh.remove_unreferenced_vertices()
    return mesh


def _extract_base_color_texture(mesh: trimesh.Trimesh, out_dir: Path) -> Path | None:
    material = getattr(mesh.visual, "material", None)
    image = getattr(material, "baseColorTexture", None) if material is not None else None
    if image is None:
        image = getattr(material, "image", None) if material is not None else None
    if image is None:
        return None

    out_dir.mkdir(parents=True, exist_ok=True)
    texture_path = out_dir / "clothes_base_color.png"
    image.save(texture_path)
    return texture_path


def _mesh_to_data(mesh: trimesh.Trimesh, texture_path: Path | None = None) -> MeshData:
    vertices = np.asarray(mesh.vertices, dtype=np.float32)
    faces = np.asarray(mesh.faces, dtype=np.int32)

    uv = None
    if hasattr(mesh.visual, "uv") and mesh.visual.uv is not None:
        uv = np.asarray(mesh.visual.uv, dtype=np.float32)
        if len(uv) != len(vertices):
            uv = None

    vertex_colors = None
    if hasattr(mesh.visual, "vertex_colors") and mesh.visual.vertex_colors is not None:
        colors = np.asarray(mesh.visual.vertex_colors, dtype=np.float32)
        if len(colors) == len(vertices):
            if colors.max(initial=0.0) > 1.0:
                colors = colors / 255.0
            vertex_colors = colors[:, :3].astype(np.float32)

    return MeshData(vertices=vertices, faces=faces, uv=uv, vertex_colors=vertex_colors, base_color_texture=texture_path)


def _simplified_data(mesh: trimesh.Trimesh, face_count: int, aggression: int) -> MeshData:
    simplified = mesh.simplify_quadric_decimation(face_count=face_count, aggression=aggression)
    simplified.remove_unreferenced_vertices()
    return _mesh_to_data(simplified)


def _grid_proxy(bounds: np.ndarray, nx: int, ny: int) -> MeshData:
    mins, maxs = bounds
    xmin, ymin, zmin = mins
    xmax, ymax, zmax = maxs
    zmid = (zmin + zmax) * 0.5

    xs = np.linspace(xmin, xmax, nx, dtype=np.float32)
    ys = np.linspace(ymin, ymax, ny, dtype=np.float32)
    vertices = []
    for y in ys:
        for x in xs:
            xn = (x - (xmin + xmax) * 0.5) / max((xmax - xmin) * 0.5, 1e-6)
            z = zmid + np.float32(0.035 * np.cos(xn * np.pi * 0.5))
            vertices.append((x, y, z))
    vertices = np.asarray(vertices, dtype=np.float32)

    faces = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = j * nx + i
            b = a + 1
            c = a + nx
            d = c + 1
            faces.append((a, c, b))
            faces.append((b, c, d))
    return MeshData(vertices=vertices, faces=np.asarray(faces, dtype=np.int32))


def _vec3_array(values: np.ndarray) -> Vt.Vec3fArray:
    return Vt.Vec3fArray.FromNumpy(np.asarray(values, dtype=np.float32))


def _int_array(values: np.ndarray) -> Vt.IntArray:
    return Vt.IntArray.FromNumpy(np.asarray(values, dtype=np.int32))


def _define_mesh(stage: Usd.Stage, path: str, data: MeshData) -> UsdGeom.Mesh:
    mesh = UsdGeom.Mesh.Define(stage, path)
    mesh.CreatePointsAttr(_vec3_array(data.vertices))
    mesh.CreateFaceVertexCountsAttr([3] * len(data.faces))
    mesh.CreateFaceVertexIndicesAttr(_int_array(data.faces.reshape(-1)))
    mesh.CreateSubdivisionSchemeAttr("none")
    mesh.CreateDoubleSidedAttr(True)
    return mesh


def _bind_visual_material(stage: Usd.Stage, mesh_prim, data: MeshData, texture_dir: Path) -> None:
    material = UsdShade.Material.Define(stage, "/World/clothes/Looks/model")

    if data.uv is not None and data.base_color_texture is not None:
        uv_face_varying = data.uv[data.faces.reshape(-1)].astype(np.float32)
        st = UsdGeom.PrimvarsAPI(mesh_prim).CreatePrimvar(
            "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying
        )
        st.Set(Vt.Vec2fArray.FromNumpy(uv_face_varying))

        reader = UsdShade.Shader.Define(stage, "/World/clothes/Looks/model/stReader")
        reader.CreateIdAttr("UsdPrimvarReader_float2")
        reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")

        texture = UsdShade.Shader.Define(stage, "/World/clothes/Looks/model/baseColorTexture")
        texture.CreateIdAttr("UsdUVTexture")
        texture_asset = "./" + data.base_color_texture.relative_to(texture_dir).as_posix()
        texture.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(texture_asset)
        texture.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(
            reader.CreateOutput("result", Sdf.ValueTypeNames.Float2)
        )

        shader = UsdShade.Shader.Define(stage, "/World/clothes/Looks/model/PreviewSurface")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.65)
        shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(
            texture.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)
        )
    else:
        colors = data.vertex_colors
        if colors is None:
            colors = np.full((len(data.vertices), 3), 0.72, dtype=np.float32)
        UsdGeom.PrimvarsAPI(mesh_prim).CreatePrimvar(
            "displayColor", Sdf.ValueTypeNames.Color3fArray, UsdGeom.Tokens.vertex
        ).Set(_vec3_array(colors))

        reader = UsdShade.Shader.Define(stage, "/World/clothes/Looks/model/displayColorReader")
        reader.CreateIdAttr("UsdPrimvarReader_float3")
        reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("displayColor")

        shader = UsdShade.Shader.Define(stage, "/World/clothes/Looks/model/PreviewSurface")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.65)
        shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(
            reader.CreateOutput("result", Sdf.ValueTypeNames.Float3)
        )

    material.CreateSurfaceOutput().ConnectToSource(shader.CreateOutput("surface", Sdf.ValueTypeNames.Token))
    UsdShade.MaterialBindingAPI.Apply(mesh_prim).Bind(material)


def _apply_deformable_root(root_prim, args: argparse.Namespace) -> None:
    root_prim.SetMetadata(
        "apiSchemas",
        Sdf.TokenListOp.CreateExplicit(
            [
                "PhysxAutoDeformableBodyAPI",
                "PhysxAutoDeformableMeshSimplificationAPI",
                "OmniPhysicsDeformableBodyAPI",
                "OmniPhysicsBodyAPI",
                "MaterialBindingAPI",
            ]
        ),
    )
    attrs = {
        "omniphysics:deformableBodyEnabled": (Sdf.ValueTypeNames.Bool, True),
        "physxDeformableBody:cookingSourceMesh": None,
        "physxDeformableBody:autoDeformableMeshSimplificationEnabled": (Sdf.ValueTypeNames.Bool, False),
        "physxDeformableBody:remeshingEnabled": (Sdf.ValueTypeNames.Bool, False),
        "physxDeformableBody:targetTriangleCount": (Sdf.ValueTypeNames.UInt, int(args.sim_target_faces)),
        "physxDeformableBody:solverPositionIterationCount": (Sdf.ValueTypeNames.Int, int(args.solver_iterations)),
        "physxDeformableBody:selfCollision": (Sdf.ValueTypeNames.Bool, bool(args.self_collision)),
        "physxDeformableBody:linearDamping": (Sdf.ValueTypeNames.Float, float(args.linear_damping)),
        "physxDeformableBody:settlingDamping": (Sdf.ValueTypeNames.Float, float(args.settling_damping)),
        "physxDeformableBody:maxLinearVelocity": (Sdf.ValueTypeNames.Float, float(args.max_linear_velocity)),
        "physxDeformableBody:maxDepenetrationVelocity": (
            Sdf.ValueTypeNames.Float,
            float(args.max_depenetration_velocity),
        ),
    }
    for name, spec in attrs.items():
        if spec is None:
            continue
        value_type, value = spec
        root_prim.CreateAttribute(name, value_type).Set(value)
    root_prim.CreateRelationship("physxDeformableBody:cookingSourceMesh").SetTargets(
        [Sdf.Path("/World/clothes/model")]
    )


def _apply_deformable_pose(prim, points: np.ndarray) -> None:
    existing_op = prim.GetMetadata("apiSchemas")
    existing = []
    if existing_op is not None:
        try:
            existing = list(existing_op.GetExplicitItems())
        except Exception:
            existing = list(getattr(existing_op, "explicitItems", []) or [])
    if not existing:
        existing = list(prim.GetAppliedSchemas())
    if "OmniPhysicsDeformablePoseAPI:default" not in existing:
        existing.append("OmniPhysicsDeformablePoseAPI:default")
    prim.SetMetadata("apiSchemas", Sdf.TokenListOp.CreateExplicit(existing))
    prim.CreateAttribute("deformablePose:default:omniphysics:purposes", Sdf.ValueTypeNames.TokenArray).Set(["bindPose"])
    prim.CreateAttribute("deformablePose:default:omniphysics:points", Sdf.ValueTypeNames.Point3fArray).Set(
        _vec3_array(points)
    )


def _apply_surface_sim(sim_prim, sim_data: MeshData) -> None:
    sim_prim.SetMetadata(
        "apiSchemas",
        Sdf.TokenListOp.CreateExplicit(
            ["OmniPhysicsSurfaceDeformableSimAPI", "PhysicsCollisionAPI", "OmniPhysicsDeformablePoseAPI:default"]
        ),
    )
    UsdGeom.Imageable(sim_prim).CreatePurposeAttr(UsdGeom.Tokens.guide)
    sim_prim.CreateAttribute("omniphysics:restShapePoints", Sdf.ValueTypeNames.Point3fArray).Set(
        _vec3_array(sim_data.vertices)
    )
    rest_tri = [Gf.Vec3i(int(a), int(b), int(c)) for a, b, c in sim_data.faces]
    sim_prim.CreateAttribute("omniphysics:restTriVtxIndices", Sdf.ValueTypeNames.Int3Array).Set(rest_tri)
    sim_prim.CreateAttribute("omniphysics:restBendAnglesDefault", Sdf.ValueTypeNames.Token).Set("restShapeDefault")
    sim_prim.CreateAttribute("physics:collisionEnabled", Sdf.ValueTypeNames.Bool).Set(True)
    _apply_deformable_pose(sim_prim, sim_data.vertices)


def _define_physics_material(stage: Usd.Stage, args: argparse.Namespace) -> None:
    material = UsdShade.Material.Define(stage, "/World/clothes/Looks/cloth_physics_material")
    material_prim = material.GetPrim()
    material_prim.SetMetadata(
        "apiSchemas",
        Sdf.TokenListOp.CreateExplicit(
            [
                "OmniPhysicsBaseMaterialAPI",
                "OmniPhysicsDeformableMaterialAPI",
                "OmniPhysicsSurfaceDeformableMaterialAPI",
            ]
        ),
    )
    values = {
        "omniphysics:density": args.density,
        "omniphysics:youngsModulus": args.youngs_modulus,
        "omniphysics:poissonsRatio": args.poissons_ratio,
        "omniphysics:surfaceThickness": args.surface_thickness,
        "omniphysics:surfaceStretchStiffness": args.surface_stretch_stiffness,
        "omniphysics:surfaceShearStiffness": args.surface_shear_stiffness,
        "omniphysics:surfaceBendStiffness": args.surface_bend_stiffness,
        "omniphysics:staticFriction": args.static_friction,
        "omniphysics:dynamicFriction": args.dynamic_friction,
        "omniphysics:restitution": 0.0,
    }
    for name, value in values.items():
        material_prim.CreateAttribute(name, Sdf.ValueTypeNames.Float).Set(float(value))
    UsdShade.MaterialBindingAPI.Apply(stage.GetPrimAtPath("/World/clothes")).Bind(material)


def _define_physics_scene(stage: Usd.Stage) -> None:
    scene = UsdPhysics.Scene.Define(stage, "/PhysicsScene").GetPrim()
    scene.SetMetadata("apiSchemas", Sdf.TokenListOp.CreateExplicit(["PhysxSceneAPI"]))
    scene.CreateAttribute("physics:gravityDirection", Sdf.ValueTypeNames.Vector3f).Set(Gf.Vec3f(0, 0, -1))
    scene.CreateAttribute("physics:gravityMagnitude", Sdf.ValueTypeNames.Float).Set(9.81)
    scene.CreateAttribute("physxScene:enableGPUDynamics", Sdf.ValueTypeNames.Bool).Set(True)
    scene.CreateAttribute("physxScene:broadphaseType", Sdf.ValueTypeNames.Token).Set("GPU")
    scene.CreateAttribute("physxScene:solverType", Sdf.ValueTypeNames.Token).Set("TGS")


def build_stage(args: argparse.Namespace) -> None:
    glb_path = Path(args.input).expanduser().resolve()
    out_path = Path(args.output).expanduser().resolve()
    asset_dir = out_path.parent
    asset_dir.mkdir(parents=True, exist_ok=True)

    source_mesh = _as_mesh(glb_path)
    texture_path = _extract_base_color_texture(source_mesh, asset_dir)

    if args.visual_target_faces > 0:
        visual_data = _simplified_data(source_mesh, args.visual_target_faces, args.visual_aggression)
        visual_data.base_color_texture = None
    else:
        visual_data = _mesh_to_data(source_mesh, texture_path)

    if args.sim_mode == "grid":
        sim_data = _grid_proxy(np.asarray(source_mesh.bounds, dtype=np.float32), args.grid_x, args.grid_y)
    else:
        sim_data = _simplified_data(source_mesh, args.sim_target_faces, args.sim_aggression)

    stage = Usd.Stage.CreateNew(str(out_path))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    root = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(root.GetPrim())
    clothes = UsdGeom.Xform.Define(stage, "/World/clothes").GetPrim()

    stage.DefinePrim("/World/clothes/Looks")
    visual_mesh = _define_mesh(stage, "/World/clothes/model", visual_data)
    _bind_visual_material(stage, visual_mesh.GetPrim(), visual_data, asset_dir)
    _apply_deformable_pose(visual_mesh.GetPrim(), visual_data.vertices)

    sim_mesh = _define_mesh(stage, "/World/clothes/simulationMesh", sim_data)
    _apply_surface_sim(sim_mesh.GetPrim(), sim_data)

    _apply_deformable_root(clothes, args)
    _define_physics_material(stage, args)
    _define_physics_scene(stage)

    stage.GetRootLayer().Save()

    print(f"Wrote: {out_path}")
    print(f"Visual mesh: {len(visual_data.vertices)} vertices, {len(visual_data.faces)} triangles")
    print(f"Simulation mesh: {len(sim_data.vertices)} vertices, {len(sim_data.faces)} triangles")
    if visual_data.base_color_texture:
        print(f"Texture: {visual_data.base_color_texture}")
    elif visual_data.vertex_colors is not None:
        print("Visual material: baked vertex colors")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a cloth-ready USD from a GLB garment.")
    parser.add_argument("--input", required=True, help="Input GLB garment path.")
    parser.add_argument("--output", required=True, help="Output USD path.")
    parser.add_argument(
        "--visual-target-faces",
        type=int,
        default=0,
        help="0 keeps original visual mesh/UV/texture. >0 simplifies visual mesh and uses baked vertex colors.",
    )
    parser.add_argument("--visual-aggression", type=int, default=6)
    parser.add_argument("--sim-mode", choices=["grid", "decimate"], default="grid")
    parser.add_argument("--sim-target-faces", type=int, default=3000)
    parser.add_argument("--sim-aggression", type=int, default=10)
    parser.add_argument("--grid-x", type=int, default=33)
    parser.add_argument("--grid-y", type=int, default=45)
    parser.add_argument("--solver-iterations", type=int, default=3)
    parser.add_argument("--self-collision", action="store_true")
    parser.add_argument("--linear-damping", type=float, default=8.0)
    parser.add_argument("--settling-damping", type=float, default=12.0)
    parser.add_argument("--max-linear-velocity", type=float, default=0.8)
    parser.add_argument("--max-depenetration-velocity", type=float, default=0.25)
    parser.add_argument("--density", type=float, default=120.0)
    parser.add_argument("--youngs-modulus", type=float, default=5000.0)
    parser.add_argument("--poissons-ratio", type=float, default=0.30)
    parser.add_argument("--surface-thickness", type=float, default=0.0025)
    parser.add_argument("--surface-stretch-stiffness", type=float, default=120.0)
    parser.add_argument("--surface-shear-stiffness", type=float, default=50.0)
    parser.add_argument("--surface-bend-stiffness", type=float, default=0.01)
    parser.add_argument("--static-friction", type=float, default=0.75)
    parser.add_argument("--dynamic-friction", type=float, default=0.55)
    return parser.parse_args()


if __name__ == "__main__":
    build_stage(parse_args())
