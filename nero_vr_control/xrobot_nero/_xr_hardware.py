from __future__ import annotations

import os
import time
import threading
import dataclasses
from pathlib import Path
from typing import Any, Dict, Sequence

import numpy as np

from .config import TeleopConfig
from .dataset_capture import DatasetSample, create_dataset_recorder, state_vector
from .dry_run import DryRunNeroArm
from .nero_arm import NeroArmInterface
from .safety import StepLimiter, apply_translation_sign, apply_vector_deadband, clamp, trigger_to_width


try:
    from xrobotoolkit_teleop.common.base_hardware_teleop_controller import HardwareTeleopController
    from xrobotoolkit_teleop.utils.geometry import R_HEADSET_TO_WORLD
    from xrobotoolkit_teleop.utils.geometry import apply_delta_pose
    import meshcat.transformations as tf
except ImportError as exc:  # pragma: no cover - depends on upstream install
    raise ImportError(
        "XRoboToolkit teleop sample is not importable. Run scripts/setup_third_party.sh "
        "and install third_party/XRoboToolkit-Teleop-Sample-Python first."
    ) from exc

try:
    from xrobotoolkit_teleop.hardware.interface.realsense import RealSenseCameraInterface
except ImportError:  # pragma: no cover - optional camera dependency
    RealSenseCameraInterface = None


def _ensure_agx_ros_package(root: Path) -> None:
    package_dir = root / "third_party" / "agx_arm_description"
    package_dir.mkdir(parents=True, exist_ok=True)
    package_xml = package_dir / "package.xml"
    if not package_xml.exists():
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
    if not link.exists() and not link.is_symlink():
        link.symlink_to(target, target_is_directory=True)


def _prepend_ros_package_path(path: Path) -> None:
    current = os.environ.get("ROS_PACKAGE_PATH", "")
    paths = [value for value in current.split(":") if value]
    path_str = str(path)
    if path_str not in paths:
        os.environ["ROS_PACKAGE_PATH"] = ":".join([path_str, *paths])


class XRNeroDualTeleopController(HardwareTeleopController):
    def __init__(
        self,
        config: TeleopConfig,
        *,
        dry_run: bool,
        visualize_placo: bool = False,
        enable_log_data: bool = True,
        dataset_capture: bool = False,
        dataset_format: str | None = None,
        dataset_root: str | None = None,
        dataset_repo_id: str | None = None,
        dataset_task: str | None = None,
        dataset_fps: int | None = None,
        dataset_image_writer_threads: int | None = None,
        dataset_image_writer_processes: int | None = None,
        isaac_sync: bool = False,
        isaac_sync_topic: str = "isaac_joint_commands",
        isaac_sync_joint_names: Sequence[str] | None = None,
        isaac_sync_rate: float = 30.0,
        isaac_sync_gripper: bool = True,
        isaac_sync_ros_distro: str | None = None,
        isaac_sync_frame_id: str = "",
    ):
        self.config = config
        self.dry_run = dry_run
        self.isaac_joint_sync = None
        self._isaac_sync_arm_order = list(config.arms)
        self._isaac_sync_last_error_report = 0.0
        self.arm_joint_slices: Dict[str, slice] = {}
        self.joint_limiters = {
            name: StepLimiter(config.safety.max_joint_delta_rad_per_cycle)
            for name in config.arms
        }
        self.gripper_limiters = {
            name: StepLimiter(config.gripper.max_delta_m_per_cycle)
            for name in config.arms
        }
        self._last_commanded_joints = {name: None for name in config.arms}
        self._last_gripper_width = {name: None for name in config.arms}
        self._robot_initialized = False
        self._last_xr_timestamp_ns = None
        self._last_xr_timestamp_change = time.monotonic()
        self._xr_stale = False
        self._program_start_joint_positions: Dict[str, list[float]] = {}
        self._return_to_start_in_progress = threading.Event()
        self._return_button_pressed_since: float | None = None
        self._return_button_triggered = False
        self._translation_sign = np.array(config.xr_mapping.translation_sign, dtype=float)
        self._rotation_sign = np.array(config.xr_mapping.rotation_sign, dtype=float)
        self._position_deadband_m = config.xr_mapping.position_deadband_m
        self._rotation_deadband_rad = config.xr_mapping.rotation_deadband_rad
        self._rotation_scale = config.xr_mapping.rotation_scale
        self.camera_serial_dict = config.camera.serials
        self.camera_serial_to_name = {serial: name for name, serial in self.camera_serial_dict.items()}
        self.joint_posture_task = None
        capture_config = config.dataset_capture
        if dataset_format is not None:
            capture_config = dataclasses.replace(capture_config, format=dataset_format)
        if dataset_root is not None:
            capture_config = dataclasses.replace(capture_config, root_dir=Path(dataset_root).expanduser())
        if dataset_repo_id is not None:
            capture_config = dataclasses.replace(capture_config, repo_id=dataset_repo_id)
        if dataset_task is not None:
            capture_config = dataclasses.replace(capture_config, task=dataset_task)
        if dataset_fps is not None:
            capture_config = dataclasses.replace(capture_config, fps=dataset_fps)
        if dataset_image_writer_threads is not None:
            capture_config = dataclasses.replace(capture_config, image_writer_threads=dataset_image_writer_threads)
        if dataset_image_writer_processes is not None:
            capture_config = dataclasses.replace(capture_config, image_writer_processes=dataset_image_writer_processes)
        if dataset_capture:
            capture_config = dataclasses.replace(capture_config, enabled=True)
        self.dataset_capture_config = capture_config
        self.dataset_recorder = (
            create_dataset_recorder(config, capture_config) if capture_config.enabled else None
        )
        self._prev_dataset_button_state = False
        self._prev_dataset_discard_button_state = False
        _ensure_agx_ros_package(config.root)
        _prepend_ros_package_path(config.root / "third_party")
        if isaac_sync:
            self._initialize_isaac_joint_sync(
                topic=isaac_sync_topic,
                joint_names=isaac_sync_joint_names,
                rate_hz=isaac_sync_rate,
                include_gripper=isaac_sync_gripper,
                ros_distro=isaac_sync_ros_distro,
                frame_id=isaac_sync_frame_id,
            )
        try:
            super().__init__(
                robot_urdf_path=str(config.urdf_path),
                manipulator_config=config.manipulator_config,
                R_headset_world=R_HEADSET_TO_WORLD,
                floating_base=False,
                scale_factor=config.scale_factor,
                visualize_placo=visualize_placo,
                control_rate_hz=config.control_rate_hz,
                enable_log_data=enable_log_data,
                log_dir=str(config.log_dir),
                log_freq=config.control_rate_hz,
                enable_camera=config.camera.enabled,
                camera_fps=config.camera.fps,
            )
        except Exception:
            self._cleanup_partial_initialization()
            raise

    def _initialize_isaac_joint_sync(
        self,
        *,
        topic: str,
        joint_names: Sequence[str] | None,
        rate_hz: float,
        include_gripper: bool,
        ros_distro: str | None,
        frame_id: str,
    ) -> None:
        from .isaac_joint_sync import DEFAULT_ARM_JOINT_NAMES, DEFAULT_JOINT_NAMES, IsaacJointStatePublisher

        self._isaac_sync_include_gripper = bool(include_gripper and self.config.gripper.enabled)
        source_joint_count = sum(len(arm.joint_names) for arm in self.config.arms.values())
        if self._isaac_sync_include_gripper:
            source_joint_count += 2 * len(self.config.arms)
        if joint_names is None:
            names = list(DEFAULT_JOINT_NAMES if self._isaac_sync_include_gripper else DEFAULT_ARM_JOINT_NAMES)
        else:
            names = [str(name) for name in joint_names]
        if len(names) != source_joint_count:
            raise ValueError(
                f"Isaac sync joint name count ({len(names)}) must match source joint count ({source_joint_count})"
            )

        self.isaac_joint_sync = IsaacJointStatePublisher(
            joint_names=names,
            topic=topic,
            rate_hz=rate_hz,
            ros_distro=ros_distro,
            frame_id=frame_id,
        )
        print(
            "Isaac Sim joint sync enabled: "
            f"topic={topic}, ros_distro={self.isaac_joint_sync.ros_distro}, joints={','.join(names)}"
        )

    def _close_isaac_joint_sync(self) -> None:
        sync = getattr(self, "isaac_joint_sync", None)
        if sync is None:
            return
        try:
            sync.close()
        except Exception as exc:
            print(f"Isaac Sim joint sync shutdown failed: {exc}")
        finally:
            self.isaac_joint_sync = None

    def _cleanup_partial_initialization(self) -> None:
        self._close_isaac_joint_sync()
        for controller in getattr(self, "arm_controllers", {}).values():
            try:
                controller.disconnect()
            except Exception:
                pass
        xr_client = getattr(self, "xr_client", None)
        if xr_client is not None:
            try:
                xr_client.close()
            except Exception:
                pass

    def run(self):
        try:
            return self._run_with_shutdown_return()
        finally:
            try:
                self.xr_client.close()
            except Exception as exc:
                print(f"XR client shutdown failed: {exc}")

    def _run_with_shutdown_return(self):
        self._robot_setup()
        self._initialize_camera()

        self._start_time = time.time()
        self._stop_event = threading.Event()
        threads = []
        for name, target in {
            "_ik_thread": self._ik_thread,
            "_control_thread": self._control_thread,
        }.items():
            threads.append(threading.Thread(name=name, target=target, args=(self._stop_event,)))
        if self.config.return_to_start.enabled:
            threads.append(
                threading.Thread(
                    name="_return_to_start_button_thread",
                    target=self._return_to_start_button_thread,
                    args=(self._stop_event,),
                )
            )
        threads.append(
            threading.Thread(
                name="_exit_button_thread",
                target=self._exit_button_thread,
                args=(self._stop_event,),
            )
        )

        if self.enable_log_data:
            threads.append(
                threading.Thread(
                    name="_data_logging_thread",
                    target=self._data_logging_thread,
                    args=(self._stop_event,),
                )
            )
        if self.dataset_recorder is not None:
            threads.append(
                threading.Thread(
                    name="_dataset_capture_thread",
                    target=self._dataset_capture_thread,
                    args=(self._stop_event,),
                )
            )
        if self.enable_camera and self.camera_interface:
            threads.append(
                threading.Thread(
                    name="_camera_thread",
                    target=self._camera_thread,
                    args=(self._stop_event,),
                )
            )

        for thread in threads:
            thread.daemon = True
            thread.start()

        print("Teleoperation running. Hold B for 0.5s to exit and hold current arm position. Ctrl+C also exits.")
        shutdown_requested = False
        try:
            while self._should_keep_running():
                if not all(thread.is_alive() for thread in threads):
                    print("A thread has died. Shutting down.")
                    break
                time.sleep(0.1)
        except KeyboardInterrupt:
            shutdown_requested = True
            print("\nKeyboard interrupt received. Returning Nero arms to zero before exit.")
        finally:
            print("Stopping teleoperation threads...")
            self._stop_event.set()
            for thread in threads:
                thread.join(timeout=2.0)
            print("Teleoperation threads have been shut down.")

        if shutdown_requested and self.config.shutdown.enabled and not self.dry_run:
            try:
                self._move_to_joint_positions(self.config.shutdown, "shutdown")
            except KeyboardInterrupt:
                print("Second keyboard interrupt received during return-to-zero; leaving arms enabled.")
        return None

    def _placo_setup(self):
        super()._placo_setup()
        for arm_name, arm_config in self.config.arms.items():
            start = self.placo_robot.get_joint_offset(arm_config.joint_names[0])
            end = self.placo_robot.get_joint_offset(arm_config.joint_names[-1]) + 1
            self.arm_joint_slices[arm_name] = slice(start, end)
            if self.effector_control_mode.get(arm_name) == "pose":
                task = self.effector_task[arm_name]
                task.position().configure(f"{arm_name}_position", "soft", self.config.xr_mapping.position_weight)
                task.orientation().configure(
                    f"{arm_name}_orientation",
                    "soft",
                    self.config.xr_mapping.orientation_weight,
                )
        if self.config.xr_mapping.posture_regularization_weight > 0.0:
            self.joint_posture_task = self.solver.add_joints_task()
            self.joint_posture_task.set_joints(self._current_solver_arm_joints())
            self.joint_posture_task.configure(
                "joint_posture_regularization",
                "soft",
                self.config.xr_mapping.posture_regularization_weight,
            )

    def _robot_setup(self):
        if self._robot_initialized:
            return
        self.arm_controllers = {}
        for arm_name, arm_config in self.config.arms.items():
            if self.dry_run:
                arm = DryRunNeroArm(name=arm_name, channel=arm_config.channel)
            else:
                arm = NeroArmInterface(
                    name=arm_name,
                    channel=arm_config.channel,
                    firmware=self.config.firmware,
                    interface=self.config.interface,
                    bitrate=self.config.bitrate,
                    command_mode=self.config.command_mode,
                    allow_move_js=self.config.allow_move_js,
                    enable_gripper=self.config.gripper.enabled,
                )
            arm.connect(auto_enable=not self.dry_run)
            self.arm_controllers[arm_name] = arm
            current_joints = arm.get_joint_positions()
            self.joint_limiters[arm_name].reset(current_joints)
            self._last_commanded_joints[arm_name] = current_joints
            self.gripper_limiters[arm_name].reset([self.config.gripper.open_width_m])
        if not self.dry_run and self.config.startup.enabled:
            self._move_to_joint_positions(self.config.startup, "startup")
            for arm_name, arm in self.arm_controllers.items():
                current_joints = arm.get_joint_positions()
                self.joint_limiters[arm_name].reset(current_joints)
                self._last_commanded_joints[arm_name] = current_joints
        self._program_start_joint_positions = {
            arm_name: list(arm.get_joint_positions())
            for arm_name, arm in self.arm_controllers.items()
        }
        if not self.dry_run:
            for arm in self.arm_controllers.values():
                if hasattr(arm, "set_speed_percent"):
                    arm.set_speed_percent(self.config.teleop_speed_percent)
        self._robot_initialized = True

    def _clear_xr_activation_refs(self) -> None:
        for arm_name in self.config.arms:
            self.active[arm_name] = False
            self.ref_ee_xyz[arm_name] = None
            self.ref_controller_xyz[arm_name] = None

    def _exit_button_thread(self, stop_event: threading.Event):
        button = "B"
        pressed_since: float | None = None
        hold_s = 0.5
        print(f"Exit ready. Hold {button} for {hold_s:.1f}s to stop teleop and keep arms enabled.")
        while not stop_event.is_set():
            try:
                pressed = self.xr_client.get_button_state_by_name(button)
                now = time.monotonic()
                if pressed:
                    if pressed_since is None:
                        pressed_since = now
                    elif now - pressed_since >= hold_s:
                        print("B exit requested. Holding current robot command and stopping teleop.")
                        self._clear_xr_activation_refs()
                        stop_event.set()
                        return
                else:
                    pressed_since = None
            except Exception as exc:
                print(f"Exit button polling failed: {exc}")
                time.sleep(0.5)
                continue
            time.sleep(0.05)

    def _return_to_start_button_thread(self, stop_event: threading.Event):
        if not self.config.return_to_start.enabled:
            return
        button = self.config.return_to_start.button
        hold_s = self.config.return_to_start.hold_s
        print(f"Return-to-start ready. Hold {button} for {hold_s:.1f}s to move both arms to program start.")
        while not stop_event.is_set():
            try:
                pressed = self.xr_client.get_button_state_by_name(button)
                now = time.monotonic()
                if pressed:
                    if self._return_button_pressed_since is None:
                        self._return_button_pressed_since = now
                    elif (
                        not self._return_button_triggered
                        and now - self._return_button_pressed_since >= hold_s
                    ):
                        self._return_button_triggered = True
                        self._return_to_program_start()
                else:
                    self._return_button_pressed_since = None
                    self._return_button_triggered = False
            except Exception as exc:
                print(f"Return-to-start button polling failed: {exc}")
                time.sleep(0.5)
                continue
            time.sleep(0.05)

    def _return_to_program_start(self) -> None:
        if self._return_to_start_in_progress.is_set():
            return
        if not self._program_start_joint_positions:
            print("Program-start joint positions are not available; return-to-start ignored.")
            return

        self._return_to_start_in_progress.set()
        try:
            print("Return-to-start requested. Pausing teleop commands and moving to program start.")
            self._clear_xr_activation_refs()
            motion_config = dataclasses.replace(
                self.config.startup,
                enabled=True,
                joint_positions={
                    arm_name: list(joints)
                    for arm_name, joints in self._program_start_joint_positions.items()
                },
            )
            self._move_to_joint_positions(motion_config, "program start")
            for arm_name, arm in self.arm_controllers.items():
                current_joints = arm.get_joint_positions()
                self.joint_limiters[arm_name].reset(current_joints)
                self._last_commanded_joints[arm_name] = current_joints
                q_slice = self.arm_joint_slices.get(arm_name)
                if q_slice is not None:
                    self.placo_robot.state.q[q_slice] = np.array(current_joints, dtype=float)
            if not self.dry_run:
                for arm in self.arm_controllers.values():
                    if hasattr(arm, "set_speed_percent"):
                        arm.set_speed_percent(self.config.teleop_speed_percent)
            print("Return-to-start complete.")
        except Exception as exc:
            print(f"Return-to-start failed: {exc}")
        finally:
            self._return_to_start_in_progress.clear()

    def _current_solver_arm_joints(self) -> Dict[str, float]:
        joints: Dict[str, float] = {}
        for arm_config in self.config.arms.values():
            for joint_name in arm_config.joint_names:
                joints[joint_name] = float(
                    self.placo_robot.state.q[self.placo_robot.get_joint_offset(joint_name)]
                )
        return joints

    def _move_to_joint_positions(self, motion_config, label: str):
        print(f"Moving Nero arms to {label} joint positions.")
        for arm_name, controller in self.arm_controllers.items():
            if hasattr(controller, "set_speed_percent"):
                controller.set_speed_percent(motion_config.speed_percent)
            target = motion_config.joint_positions[arm_name]
            current = controller.get_joint_positions()
            max_abs_error = max(abs(t - c) for t, c in zip(target, current))
            print(f"{arm_name}: {label} max joint error {max_abs_error:.4f} rad")

        deadline = time.monotonic() + motion_config.timeout_s
        period_s = 1.0 / motion_config.control_rate_hz
        next_report = 0.0
        while True:
            all_reached = True
            max_errors: Dict[str, float] = {}
            for arm_name, controller in self.arm_controllers.items():
                target = motion_config.joint_positions[arm_name]
                current = controller.get_joint_positions()
                errors = [t - c for t, c in zip(target, current)]
                max_error = max(abs(error) for error in errors)
                max_errors[arm_name] = max_error
                if max_error <= motion_config.tolerance_rad:
                    continue
                all_reached = False
                command = [
                    c + clamp(error, -motion_config.max_delta_rad_per_cycle, motion_config.max_delta_rad_per_cycle)
                    for c, error in zip(current, errors)
                ]
                controller.send_joint_positions(command, command_mode=self.config.command_mode)

            if all_reached:
                print(f"{label.capitalize()} joint positions reached.")
                time.sleep(motion_config.settle_s)
                return
            now = time.monotonic()
            if now >= next_report:
                details = ", ".join(f"{name}={error:.4f} rad" for name, error in max_errors.items())
                print(f"{label.capitalize()} moving... max errors: {details}")
                next_report = now + 2.0
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out moving Nero arms to {label} joint positions")
            time.sleep(period_s)

    def _initialize_camera(self):
        self.camera_interface = None
        if not self.enable_camera:
            return
        if not self.camera_serial_dict:
            print("Camera is enabled, but camera.serials is empty; disabling camera logging.")
            self.enable_camera = False
            return

        print("Initializing RealSense cameras...")
        if RealSenseCameraInterface is None:
            print("pyrealsense2 is not available; disabling camera logging.")
            self.enable_camera = False
            return
        try:
            self.camera_interface = RealSenseCameraInterface(
                width=self.config.camera.width,
                height=self.config.camera.height,
                fps=self.config.camera.fps,
                serial_numbers=list(self.camera_serial_dict.values()),
                enable_depth=self.config.camera.enable_depth,
                enable_compression=self.config.camera.enable_compression,
                jpg_quality=self.config.camera.jpg_quality,
            )
            self.camera_interface.start()
            print("RealSense cameras initialized successfully.")
        except Exception as exc:
            print(f"Error initializing RealSense cameras: {exc}")
            self.camera_interface = None
            self.enable_camera = False
        if self.dataset_recorder is not None and not self.enable_camera:
            if self.dataset_capture_config.image_streams:
                print("Dataset capture is enabled, but cameras are unavailable; image frames will be dropped.")
            else:
                print("Dataset capture is enabled without image streams; recording state/action only.")

    def _update_robot_state(self):
        for arm_name, controller in self.arm_controllers.items():
            q_slice = self.arm_joint_slices[arm_name]
            commanded = self._last_commanded_joints.get(arm_name)
            if self.active.get(arm_name, False) and commanded is not None:
                joints = commanded
            else:
                joints = controller.get_joint_positions()
                self._last_commanded_joints[arm_name] = joints
            self.placo_robot.state.q[q_slice] = np.array(joints, dtype=float)

    def _update_ik(self):
        self.placo_robot.update_kinematics()

        timestamp_ns = self.xr_client.get_timestamp_ns()
        now = time.monotonic()
        if timestamp_ns != self._last_xr_timestamp_ns:
            self._last_xr_timestamp_ns = timestamp_ns
            self._last_xr_timestamp_change = now
            if self._xr_stale:
                print("XR input stream recovered.")
            self._xr_stale = False
        elif now - self._last_xr_timestamp_change > self.config.safety.xr_timeout_s:
            if not self._xr_stale:
                print("XR input stream timed out; holding robot commands.")
            self._xr_stale = True

        if self._xr_stale:
            self._clear_xr_activation_refs()
            return

        if self._return_to_start_in_progress.is_set():
            self._clear_xr_activation_refs()
            return

        for src_name, config in self.manipulator_config.items():
            xr_grip_val = self.xr_client.get_key_value_by_name(config["control_trigger"])
            self.active[src_name] = xr_grip_val >= self.config.safety.deadman_threshold

            if self.active[src_name]:
                if self.ref_ee_xyz[src_name] is None:
                    print(f"{src_name} is activated.")
                    self.ref_ee_xyz[src_name], self.ref_ee_quat[src_name] = self._get_link_pose(config["link_name"])
                    if src_name in self.arm_controllers:
                        current_joints = self.arm_controllers[src_name].get_joint_positions()
                        self.joint_limiters[src_name].reset(current_joints)
                        self._last_commanded_joints[src_name] = current_joints

                xr_pose = self.xr_client.get_pose_by_name(config["pose_source"])
                delta_xyz, delta_rot = self._process_xr_pose(xr_pose, src_name)
                delta_xyz = np.array(
                    apply_vector_deadband(
                        apply_translation_sign(delta_xyz, self._translation_sign),
                        self._position_deadband_m,
                    ),
                    dtype=float,
                )
                delta_rot = np.array(
                    apply_vector_deadband(
                        apply_translation_sign(delta_rot, self._rotation_sign),
                        self._rotation_deadband_rad,
                    ),
                    dtype=float,
                )
                delta_rot *= self._rotation_scale

                if self.effector_control_mode[src_name] == "position":
                    self.effector_task[src_name].target_world = self.ref_ee_xyz[src_name] + delta_xyz
                else:
                    target_xyz, target_quat = apply_delta_pose(
                        self.ref_ee_xyz[src_name],
                        self.ref_ee_quat[src_name],
                        delta_xyz,
                        delta_rot,
                    )
                    target_pose = tf.quaternion_matrix(target_quat)
                    target_pose[:3, 3] = target_xyz
                    self.effector_task[src_name].T_world_frame = target_pose
            else:
                if self.ref_ee_xyz[src_name] is not None:
                    print(f"{src_name} is deactivated.")
                    self.ref_ee_xyz[src_name] = None
                    self.ref_controller_xyz[src_name] = None

        try:
            if self.joint_posture_task is not None:
                self.joint_posture_task.set_joints(self._current_solver_arm_joints())
            self.solver.solve(True)
        except RuntimeError as exc:
            print(f"IK solver failed: {exc}")

    def _publish_isaac_joint_sync(self) -> None:
        if self.isaac_joint_sync is None:
            return

        positions = []
        for arm_name in self._isaac_sync_arm_order:
            joints = self._last_commanded_joints.get(arm_name)
            if joints is None:
                return
            positions.extend(float(value) for value in joints)
            if getattr(self, "_isaac_sync_include_gripper", False):
                width = self._last_gripper_width.get(arm_name)
                if width is None:
                    width = self.config.gripper.open_width_m
                positions.extend(self._isaac_gripper_width_to_joint_positions(width))

        try:
            self.isaac_joint_sync.publish(positions)
        except Exception as exc:
            now = time.monotonic()
            if now - self._isaac_sync_last_error_report >= 1.0:
                print(f"Isaac Sim joint sync publish failed: {exc}")
                self._isaac_sync_last_error_report = now

    def _isaac_gripper_width_to_joint_positions(self, width: float) -> list[float]:
        lower = min(self.config.gripper.close_width_m, self.config.gripper.open_width_m)
        upper = max(self.config.gripper.close_width_m, self.config.gripper.open_width_m)
        clamped_width = clamp(float(width), lower, upper)
        half_width = 0.5 * clamped_width
        return [half_width, -half_width]

    def _send_command(self):
        if self._return_to_start_in_progress.is_set():
            return

        for arm_name, controller in self.arm_controllers.items():
            if not controller.is_ok():
                print(f"{arm_name}: communication not OK; holding commands")
                continue
            if self._xr_stale:
                continue

            if self.active.get(arm_name, False):
                q_des = self.placo_robot.state.q[self.arm_joint_slices[arm_name]].copy().tolist()
                q_cmd = self.joint_limiters[arm_name].limit(q_des)
                controller.send_joint_positions(q_cmd, command_mode=self.config.teleop_command_mode)
                self._last_commanded_joints[arm_name] = q_cmd
            elif not self.config.safety.hold_on_inactive:
                current_joints = controller.get_joint_positions()
                self.joint_limiters[arm_name].reset(current_joints)
                self._last_commanded_joints[arm_name] = current_joints

            if self.config.gripper.enabled:
                grip_name = self.config.arms[arm_name].gripper_trigger
                trigger_value = self.xr_client.get_key_value_by_name(grip_name)
                target = trigger_to_width(
                    trigger_value,
                    self.config.gripper.open_width_m,
                    self.config.gripper.close_width_m,
                )
                width = self.gripper_limiters[arm_name].limit([target])[0]
                last_width = self._last_gripper_width.get(arm_name)
                if last_width is None or abs(width - last_width) >= self.config.gripper.command_deadband_m:
                    controller.send_gripper_width(width)
                    self._last_gripper_width[arm_name] = width

        self._publish_isaac_joint_sync()

    def _dataset_capture_thread(self, stop_event: threading.Event):
        if self.dataset_recorder is None:
            return
        period_s = 1.0 / max(1, self.dataset_capture_config.fps)
        print(
            "Dataset capture ready. "
            f"Press {self.dataset_capture_config.start_button} to start/stop an episode; "
            f"press {self.dataset_capture_config.discard_button} to discard the active episode."
        )
        try:
            while not stop_event.is_set():
                start_time = time.time()
                self._check_dataset_capture_buttons()
                if self.dataset_recorder.is_recording:
                    self.dataset_recorder.record(self._get_dataset_sample())
                elapsed_time = time.time() - start_time
                sleep_time = period_s - elapsed_time
                if sleep_time > 0:
                    time.sleep(sleep_time)
        finally:
            if self.dataset_recorder.is_recording:
                episode_dir = self.dataset_recorder.finish_episode()
                if episode_dir is not None:
                    print(f"Dataset episode saved on shutdown: {episode_dir}")
            self.dataset_recorder.finalize()
            print("Dataset capture thread has stopped.")

    def _check_dataset_capture_buttons(self):
        if self.dataset_recorder is None:
            return
        start_button_state = self.xr_client.get_button_state_by_name(
            self.dataset_capture_config.start_button
        )
        discard_button_state = self.xr_client.get_button_state_by_name(
            self.dataset_capture_config.discard_button
        )

        if start_button_state and not self._prev_dataset_button_state:
            if self.dataset_recorder.is_recording:
                episode_dir = self.dataset_recorder.finish_episode()
                print(f"--- Stopped dataset episode. Saved to {episode_dir} ---")
            else:
                self.dataset_recorder.start_episode()
                print("--- Started dataset episode ---")

        if discard_button_state and not self._prev_dataset_discard_button_state:
            if self.dataset_recorder.is_recording:
                self.dataset_recorder.discard_episode()
                print("--- Discarded active dataset episode ---")

        self._prev_dataset_button_state = start_button_state
        self._prev_dataset_discard_button_state = discard_button_state

    def _get_dataset_sample(self) -> DatasetSample:
        robot_state = self._get_robot_state_for_logging()
        gripper_widths = {
            name: self._last_gripper_width.get(name)
            for name in self.config.arms
        }
        qpos = robot_state.get("qpos", {})
        state = state_vector(self.config, qpos, gripper_widths)
        action_qpos = {
            name: self._last_commanded_joints.get(name) or qpos.get(name, [0.0] * 7)
            for name in self.config.arms
        }
        action = state_vector(self.config, action_qpos, gripper_widths)
        frames: Dict[str, Dict[str, Any]] = {}
        if self.enable_camera and self.camera_interface:
            frames = self._get_camera_frame_for_logging()
        return DatasetSample(
            timestamp_s=time.time() - self._start_time,
            wall_time_ns=time.time_ns(),
            state=state,
            action=action,
            robot_state=robot_state,
            gripper_widths=gripper_widths,
            active={name: bool(value) for name, value in self.active.items()},
            xr_stale=bool(self._xr_stale),
            images=frames,
        )

    def _get_robot_state_for_logging(self) -> Dict:
        return {
            "qpos": {name: arm.get_joint_positions() for name, arm in self.arm_controllers.items()},
            "qvel": {name: arm.get_joint_velocities() for name, arm in self.arm_controllers.items()},
            "qpos_des": {
                name: self.placo_robot.state.q[self.arm_joint_slices[name]].copy()
                for name in self.arm_controllers
            },
        }

    def _get_camera_frame_for_logging(self) -> Dict:
        if not self.camera_interface:
            return {}

        if self.camera_interface.enable_compression:
            frames_by_serial = self.camera_interface.get_compressed_frames()
        else:
            frames_by_serial = self.camera_interface.get_frames()

        frames_by_name = {}
        for serial, frames in frames_by_serial.items():
            camera_name = self.camera_serial_to_name.get(serial, serial)
            frames_by_name[camera_name] = frames
        return frames_by_name

    def _shutdown_robot(self):
        for name, controller in self.arm_controllers.items():
            try:
                if self.config.safety.go_home_on_shutdown and hasattr(controller, "go_home"):
                    controller.go_home()
                    time.sleep(0.5)
                if self.config.safety.disable_on_shutdown:
                    controller.disable()
                    controller.disconnect()
                else:
                    print(f"{name}: leaving arm enabled on shutdown; not disconnecting CAN driver.")
            except Exception as exc:
                print(f"{name}: shutdown failed: {exc}")
        self._close_isaac_joint_sync()
        self._robot_initialized = False
