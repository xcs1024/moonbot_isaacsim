#!/usr/bin/env python3
"""
Open the Isaac Sim world and live-update one prim from the realtime detection
JSON produced by Grounded-SAM-2.

This script does not open the RealSense camera. Run the detection process in a
separate terminal and let this script consume its latest_positions.json file.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from realsense_depth_masked_texture_isaacsim import (
    DEFAULT_ARTICULATION_CONTROLLER_PATH,
    DEFAULT_DETECTION_OFFSET_FILE,
    DEFAULT_DETECTION_POSITION_JSON,
    DEFAULT_INSTA360_PANORAMA_SCRIPT,
    DEFAULT_ROBOT_PATH,
    DEFAULT_WORLD,
    DetectionObjectSync,
    enable_ros2_bridge_extensions,
    log,
    open_usd_stage,
    repair_joint_control_graph,
    reexec_with_jetson_libgomp_if_needed,
    setup_isaac_ros2_environment,
    start_insta360_live_panorama,
    start_timeline,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync detected object pose into Isaac Sim.")
    parser.add_argument("--world", default=DEFAULT_WORLD, help="USD world to open.")
    parser.add_argument("--headless", action="store_true", help="Run without Isaac UI.")
    parser.add_argument(
        "--enable-ros2-bridge",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable ROS2 bridge so existing arm sync graphs keep working.",
    )
    parser.add_argument(
        "--play-timeline",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Start the Isaac timeline after opening the stage.",
    )
    parser.add_argument(
        "--ros-distro",
        choices=("humble", "jazzy"),
        default=os.environ.get("ROS_DISTRO", "jazzy"),
    )
    parser.add_argument(
        "--articulation-controller-path",
        default=DEFAULT_ARTICULATION_CONTROLLER_PATH,
        help="OmniGraph articulation controller node to repair for Isaac Sim 6.0.1.",
    )
    parser.add_argument("--robot-path", default=DEFAULT_ROBOT_PATH)
    parser.add_argument(
        "--enable-insta360-panorama",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run the Insta360 live panorama script automatically after opening the stage.",
    )
    parser.add_argument("--insta360-panorama-script", default=DEFAULT_INSTA360_PANORAMA_SCRIPT)
    parser.add_argument("--detection-position-json", default=DEFAULT_DETECTION_POSITION_JSON)
    parser.add_argument("--detection-object-prim", default="/World/redBull")
    parser.add_argument("--detection-offset-file", default=DEFAULT_DETECTION_OFFSET_FILE)
    parser.add_argument(
        "--detection-object-label",
        default="",
        help="Optional label filter. Empty uses the highest-score detected object.",
    )
    parser.add_argument(
        "--detection-offset",
        type=float,
        nargs=3,
        default=(0.0, 0.0, 0.0),
        metavar=("X", "Y", "Z"),
        help="XYZ offset added to detected position before updating the prim.",
    )
    parser.add_argument(
        "--detection-position-scale",
        type=float,
        nargs=3,
        default=(1.0, 1.0, 1.0),
        metavar=("SX", "SY", "SZ"),
        help="XYZ scale applied to detected position before offset.",
    )
    parser.add_argument("--detection-sync-min-interval", type=float, default=0.03)
    parser.add_argument("--detection-set-kinematic", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--loop-sleep", type=float, default=0.005, help="Sleep between Isaac updates.")
    parser.add_argument("--status-interval", type=float, default=10.0, help="Seconds between alive logs. 0 disables.")
    parser.add_argument("--exit-after-seconds", type=float, default=0.0, help="Testing only. 0 runs until closed.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.detection_sync_min_interval < 0:
        raise ValueError("--detection-sync-min-interval must be >= 0.")

    if args.enable_ros2_bridge:
        distro = setup_isaac_ros2_environment(args)
        log(f"Configured Isaac Sim ROS2 bridge environment: ROS_DISTRO={distro}")

    reexec_with_jetson_libgomp_if_needed()
    sys.argv = [sys.argv[0]]

    log("Importing Isaac Sim SimulationApp.")
    from isaacsim import SimulationApp

    log(f"Creating SimulationApp: headless={bool(args.headless)}")
    simulation_app = SimulationApp({"headless": bool(args.headless)})
    log("SimulationApp created.")

    try:
        if args.enable_ros2_bridge:
            enable_ros2_bridge_extensions(simulation_app)
            log("ROS2 bridge extensions enabled.")

        log(f"Opening world: {args.world}")
        stage = open_usd_stage(simulation_app, args.world)
        repair_joint_control_graph(stage, args)
        if args.enable_insta360_panorama:
            start_insta360_live_panorama(simulation_app, args)

        detection_object_sync = DetectionObjectSync(stage, args)
        if args.play_timeline:
            start_timeline(simulation_app)

        started_at = time.monotonic()
        last_status = started_at
        log("Detection pose sync loop started.")
        while simulation_app.is_running():
            now = time.monotonic()
            detection_object_sync.update()
            simulation_app.update()
            if args.status_interval > 0 and now - last_status >= args.status_interval:
                log(f"Detection pose sync alive: json={args.detection_position_json}")
                last_status = now
            if args.exit_after_seconds > 0 and now - started_at >= args.exit_after_seconds:
                log(f"Exiting after {args.exit_after_seconds:.1f}s.")
                break
            if args.loop_sleep > 0:
                time.sleep(args.loop_sleep)
    except KeyboardInterrupt:
        log("Interrupted by user.")
    finally:
        simulation_app.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
