#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


OFFICIAL_PACKAGE_PREFIX = "package://agx_arm_description/agx_arm_urdf/"
SKIP_LINKS = {"world"}
SKIP_JOINTS = {"world_to_base_link"}


def _git_commit(repo: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _rename_link(name: str, prefix: str) -> str:
    if name == "base_link":
        return f"{prefix}_base_link"
    return f"{prefix}_{name}"


def _rename_joint(name: str, prefix: str) -> str:
    return f"{prefix}_{name}"


def ensure_local_ros_package(root: Path) -> None:
    package_dir = root / "third_party" / "agx_arm_description"
    package_dir.mkdir(parents=True, exist_ok=True)
    package_xml = package_dir / "package.xml"
    package_xml.write_text(
        """<package format="3">
  <name>agx_arm_description</name>
  <version>0.0.0</version>
  <description>Local ROS package wrapper for AgileX arm URDF assets.</description>
  <maintainer email="local@example.com">local</maintainer>
  <license>MIT</license>
</package>
""",
        encoding="utf-8",
    )
    link = package_dir / "agx_arm_urdf"
    target = Path("..") / "agx_arm_urdf"
    if link.is_symlink() and os.readlink(link) == str(target):
        return
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(target, target_is_directory=True)


def _rewrite_meshes(element: ET.Element, official_root: Path, mesh_path_mode: str) -> None:
    for mesh in element.findall(".//mesh"):
        filename = mesh.attrib.get("filename", "")
        if mesh_path_mode == "absolute" and filename.startswith(OFFICIAL_PACKAGE_PREFIX):
            rel = filename.removeprefix(OFFICIAL_PACKAGE_PREFIX)
            mesh.set("filename", str((official_root / rel).resolve()))


def _prefixed_arm_elements(
    source_root: ET.Element,
    prefix: str,
    official_root: Path,
    mesh_path_mode: str,
) -> list[ET.Element]:
    elements: list[ET.Element] = []
    for child in source_root:
        if child.tag == "link":
            name = child.attrib.get("name")
            if name in SKIP_LINKS:
                continue
            element = copy.deepcopy(child)
            element.set("name", _rename_link(name, prefix))
            _rewrite_meshes(element, official_root, mesh_path_mode)
            elements.append(element)
        elif child.tag == "joint":
            name = child.attrib.get("name")
            if name in SKIP_JOINTS:
                continue
            element = copy.deepcopy(child)
            element.set("name", _rename_joint(name, prefix))
            parent = element.find("parent")
            child_link = element.find("child")
            if parent is not None:
                parent.set("link", _rename_link(parent.attrib["link"], prefix))
            if child_link is not None:
                child_link.set("link", _rename_link(child_link.attrib["link"], prefix))
            elements.append(element)
    return elements


def generate(source: Path, output: Path, official_root: Path, mesh_path_mode: str) -> None:
    source_root = ET.parse(source).getroot()
    robot = ET.Element("robot", {"name": "dual_nero_official"})
    robot.append(ET.Comment("Generated from AgileX official Nero URDF: nero/urdf/nero_description.urdf"))
    robot.append(ET.Comment(f"agx_arm_urdf commit: {_git_commit(official_root)}"))
    robot.append(ET.Comment("Only the dual-arm mounting wrapper and left/right prefixes are project-specific."))
    if mesh_path_mode == "package":
        robot.append(ET.Comment("Mesh paths keep AgileX package:// URIs; set ROS_PACKAGE_PATH to the project third_party directory."))

    ET.SubElement(robot, "link", {"name": "world"})
    ET.SubElement(robot, "link", {"name": "base_link"})
    world_joint = ET.SubElement(robot, "joint", {"name": "world_to_base_link", "type": "fixed"})
    ET.SubElement(world_joint, "parent", {"link": "world"})
    ET.SubElement(world_joint, "child", {"link": "base_link"})
    ET.SubElement(world_joint, "origin", {"xyz": "0 0 0", "rpy": "0 0 0"})

    for prefix, mount_y in (("left", "0.32"), ("right", "-0.32")):
        for element in _prefixed_arm_elements(source_root, prefix, official_root, mesh_path_mode):
            robot.append(element)

        mount = ET.SubElement(robot, "joint", {"name": f"{prefix}_mount_joint", "type": "fixed"})
        ET.SubElement(mount, "parent", {"link": "base_link"})
        ET.SubElement(mount, "child", {"link": f"{prefix}_base_link"})
        ET.SubElement(mount, "origin", {"xyz": f"0 {mount_y} 0", "rpy": "0 0 0"})

    ET.indent(robot, space="  ")
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(robot).write(output, encoding="utf-8", xml_declaration=True)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Generate the dual Nero URDF from AgileX official Nero URDF.")
    parser.add_argument(
        "--source",
        default=root / "third_party" / "agx_arm_urdf" / "nero" / "urdf" / "nero_description.urdf",
        type=Path,
    )
    parser.add_argument(
        "--official-root",
        default=root / "third_party" / "agx_arm_urdf",
        type=Path,
    )
    parser.add_argument(
        "--output",
        default=root / "assets" / "urdf" / "dual_nero_official.urdf",
        type=Path,
    )
    parser.add_argument(
        "--mesh-path-mode",
        choices=("package", "absolute"),
        default="package",
        help="Use official package:// mesh URIs by default; absolute mode is only for debugging.",
    )
    args = parser.parse_args()
    ensure_local_ros_package(root)
    generate(args.source.resolve(), args.output.resolve(), args.official_root.resolve(), args.mesh_path_mode)
    print(f"Generated {args.output}")


if __name__ == "__main__":
    main()
