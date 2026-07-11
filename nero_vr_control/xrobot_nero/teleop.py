from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from .config import load_config
from .isaac_joint_sync import DEFAULT_JOINT_NAMES
from .teleop_controller import NeroDualTeleopController


def _parse_joint_names(value: str) -> list[str]:
    names = [name.strip() for name in value.split(",") if name.strip()]
    if not names:
        raise argparse.ArgumentTypeError("joint name list must not be empty")
    return names


def _check_environment(config_path: Path, headset_name: str) -> int:
    config = load_config(config_path)
    headset = config.headsets.require(headset_name)
    print(f"config: {config_path}")
    print(f"project root: {config.root}")
    print(f"robot: {config.name}")
    print(f"headset: {headset.display_name} ({headset.name})")
    print(f"headset apk: {headset.apk_path}")
    print(f"headset apk status: {'downloaded' if headset.apk_path.exists() else 'missing'}")
    print(f"urdf: {config.urdf_path}")
    print(f"arms: {', '.join(f'{name}={arm.channel}' for name, arm in config.arms.items())}")
    camera_status = "enabled" if config.camera.enabled else "disabled"
    print(
        f"camera: {camera_status} "
        f"{config.camera.width}x{config.camera.height}@{config.camera.fps} "
        f"depth={'on' if config.camera.enable_depth else 'off'}"
    )
    if config.camera.serials:
        print("camera serials: " + ", ".join(f"{name}={serial}" for name, serial in config.camera.serials.items()))
    for tool in ["wget", "sha256sum", "ip", "adb"]:
        status = shutil.which(tool) or "missing"
        print(f"{tool}: {status}")
    try:
        import pyAgxArm  # noqa: F401
        print("pyAgxArm: import OK")
    except ImportError:
        print("pyAgxArm: missing")
    try:
        import xrobotoolkit_teleop  # noqa: F401
        print("xrobotoolkit_teleop: import OK")
    except ImportError:
        print("xrobotoolkit_teleop: missing")
    try:
        import pyrealsense2 as rs

        devices = list(rs.context().query_devices())
        found_serials = {dev.get_info(rs.camera_info.serial_number) for dev in devices}
        print(f"pyrealsense2: import OK, devices={len(devices)}")
        for dev in devices:
            serial = dev.get_info(rs.camera_info.serial_number)
            usb = dev.get_info(rs.camera_info.usb_type_descriptor)
            print(f"  RealSense {serial} usb={usb}")
        missing = set(config.camera.serials.values()) - found_serials
        if config.camera.enabled and missing:
            print("camera serials missing: " + ", ".join(sorted(missing)))
    except ImportError:
        print("pyrealsense2: missing")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run XR headset teleoperation for dual AgileX Nero arms.")
    parser.add_argument("--config", default="configs/nero_dual_agx.yml", help="Path to YAML config.")
    parser.add_argument("--headset", default=None, help="Headset profile name, e.g. quest3 or pico4ultra.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Run with fake Nero arms.")
    mode.add_argument("--real", action="store_true", help="Run against real Nero hardware.")
    parser.add_argument("--check", action="store_true", help="Validate config and report local dependencies.")
    parser.add_argument("--visualize-placo", action="store_true", help="Show Placo visualization.")
    parser.add_argument("--disable-log", action="store_true", help="Disable teleop data logging.")
    parser.add_argument("--dataset-capture", action="store_true", help="Record LeRobot v3 pi0.5 dataset episodes.")
    parser.add_argument("--dataset-format", default=None, help="Override dataset_capture.format.")
    parser.add_argument("--dataset-root", default=None, help="Override dataset_capture.root_dir.")
    parser.add_argument("--dataset-repo-id", default=None, help="Override dataset_capture.repo_id.")
    parser.add_argument("--dataset-task", default=None, help="Task prompt stored with captured episodes.")
    parser.add_argument("--dataset-fps", type=int, default=None, help="Override dataset_capture.fps.")
    parser.add_argument("--dataset-image-writer-threads", type=int, default=None)
    parser.add_argument("--dataset-image-writer-processes", type=int, default=None)
    parser.add_argument(
        "--isaac-sync",
        action="store_true",
        help="Publish real/commanded arm joints to Isaac Sim as sensor_msgs/JointState.",
    )
    parser.add_argument("--isaac-sync-topic", default="isaac_joint_commands", help="Isaac Sim joint command topic.")
    parser.add_argument(
        "--isaac-sync-joint-names",
        type=_parse_joint_names,
        default=",".join(DEFAULT_JOINT_NAMES),
        help="Comma-separated Isaac Sim joint names, in real arm joint order.",
    )
    parser.add_argument("--isaac-sync-rate", type=float, default=30.0, help="Maximum joint sync publish rate.")
    parser.add_argument(
        "--isaac-sync-gripper",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include simulated gripper_joint1/2 in Isaac Sim joint sync.",
    )
    parser.add_argument(
        "--isaac-sync-ros-distro",
        choices=("humble", "jazzy"),
        default=None,
        help="Isaac Sim bundled ROS2 distro to use. Defaults to ROS_DISTRO, then jazzy.",
    )
    parser.add_argument("--isaac-sync-frame-id", default="", help="Optional JointState header frame_id.")
    args = parser.parse_args(argv)

    config_path = Path(args.config).expanduser()
    config = load_config(config_path)
    headset_name = args.headset or config.headsets.default
    try:
        headset = config.headsets.require(headset_name)
    except KeyError as exc:
        parser.error(str(exc))
    if args.check:
        return _check_environment(config_path, headset_name)
    if not args.dry_run and not args.real:
        parser.error("choose exactly one runtime mode: --dry-run or --real")

    enable_log_data = not args.disable_log
    if args.dataset_capture and enable_log_data:
        print("Dataset capture uses the logging buttons; disabling upstream pickle logging for this run.")
        enable_log_data = False

    print(f"Using XR headset profile: {headset.display_name} ({headset.name})")
    controller = NeroDualTeleopController(
        config,
        dry_run=args.dry_run,
        visualize_placo=args.visualize_placo,
        enable_log_data=enable_log_data,
        dataset_capture=args.dataset_capture,
        dataset_format=args.dataset_format,
        dataset_root=args.dataset_root,
        dataset_repo_id=args.dataset_repo_id,
        dataset_task=args.dataset_task,
        dataset_fps=args.dataset_fps,
        dataset_image_writer_threads=args.dataset_image_writer_threads,
        dataset_image_writer_processes=args.dataset_image_writer_processes,
        isaac_sync=args.isaac_sync,
        isaac_sync_topic=args.isaac_sync_topic,
        isaac_sync_joint_names=args.isaac_sync_joint_names,
        isaac_sync_rate=args.isaac_sync_rate,
        isaac_sync_gripper=args.isaac_sync_gripper,
        isaac_sync_ros_distro=args.isaac_sync_ros_distro,
        isaac_sync_frame_id=args.isaac_sync_frame_id,
    )
    controller.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
