from __future__ import annotations

from dataclasses import dataclass
from math import radians
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import yaml


@dataclass(frozen=True)
class ArmConfig:
    name: str
    channel: str
    link_name: str
    joint_names: List[str]
    pose_source: str
    control_trigger: str
    gripper_trigger: str


@dataclass(frozen=True)
class GripperConfig:
    enabled: bool
    open_width_m: float
    close_width_m: float
    max_delta_m_per_cycle: float
    command_deadband_m: float


@dataclass(frozen=True)
class CameraConfig:
    enabled: bool
    serials: Dict[str, str]
    width: int
    height: int
    fps: int
    enable_depth: bool
    enable_compression: bool
    jpg_quality: int


@dataclass(frozen=True)
class DatasetCaptureConfig:
    enabled: bool
    format: str
    root_dir: Path
    repo_id: str
    fps: int
    robot_type: str
    task: str
    start_button: str
    discard_button: str
    min_episode_frames: int
    image_streams: List[str]
    image_writer_threads: int | None
    image_writer_processes: int | None


@dataclass(frozen=True)
class ReturnToStartConfig:
    enabled: bool
    button: str
    hold_s: float


@dataclass(frozen=True)
class SafetyConfig:
    deadman_threshold: float
    xr_timeout_s: float
    max_joint_delta_rad_per_cycle: float
    hold_on_inactive: bool
    go_home_on_shutdown: bool
    disable_on_shutdown: bool


@dataclass(frozen=True)
class StartupConfig:
    enabled: bool
    joint_positions: Dict[str, List[float]]
    max_delta_rad_per_cycle: float
    tolerance_rad: float
    control_rate_hz: int
    timeout_s: float
    settle_s: float
    speed_percent: int


@dataclass(frozen=True)
class ShutdownConfig:
    enabled: bool
    joint_positions: Dict[str, List[float]]
    max_delta_rad_per_cycle: float
    tolerance_rad: float
    control_rate_hz: int
    timeout_s: float
    settle_s: float
    speed_percent: int


@dataclass(frozen=True)
class XrMappingConfig:
    translation_sign: List[float]
    rotation_sign: List[float]
    position_deadband_m: float
    rotation_deadband_rad: float
    rotation_scale: float
    position_weight: float
    orientation_weight: float
    posture_regularization_weight: float
    control_mode: str


@dataclass(frozen=True)
class HeadsetProfile:
    name: str
    display_name: str
    apk_version: str
    apk_url: str
    apk_sha256: str
    apk_path: Path
    install_args: List[str]
    adb_label: str


@dataclass(frozen=True)
class HeadsetConfig:
    default: str
    profiles: Dict[str, HeadsetProfile]

    def require(self, name: str) -> HeadsetProfile:
        if name not in self.profiles:
            available = ", ".join(sorted(self.profiles))
            raise KeyError(f"unknown headset profile: {name}. Available profiles: {available}")
        return self.profiles[name]


@dataclass(frozen=True)
class TeleopConfig:
    root: Path
    name: str
    urdf_path: Path
    firmware: str
    interface: str
    bitrate: int
    control_rate_hz: int
    teleop_speed_percent: int
    log_dir: Path
    scale_factor: float
    command_mode: str
    teleop_command_mode: str
    allow_move_js: bool
    arms: Dict[str, ArmConfig]
    gripper: GripperConfig
    camera: CameraConfig
    safety: SafetyConfig
    startup: StartupConfig
    shutdown: ShutdownConfig
    xr_mapping: XrMappingConfig
    dataset_capture: DatasetCaptureConfig
    return_to_start: ReturnToStartConfig
    headsets: HeadsetConfig
    pc_service_run_script: Path

    @property
    def quest(self) -> HeadsetProfile:
        return self.headsets.require("quest3")

    @property
    def manipulator_config(self) -> Dict[str, Dict[str, Any]]:
        config: Dict[str, Dict[str, Any]] = {}
        for arm_name, arm in self.arms.items():
            config[arm_name] = {
                "link_name": arm.link_name,
                "pose_source": arm.pose_source,
                "control_trigger": arm.control_trigger,
                "control_mode": self.xr_mapping.control_mode,
                "position_weight": self.xr_mapping.position_weight,
                "orientation_weight": self.xr_mapping.orientation_weight,
                "gripper_config": {
                    "type": "parallel",
                    "gripper_trigger": arm.gripper_trigger,
                    "joint_names": [f"{arm_name}_gripper_width"],
                    "open_pos": [self.gripper.open_width_m],
                    "close_pos": [self.gripper.close_width_m],
                },
            }
        return config


def _require(mapping: Dict[str, Any], key: str) -> Any:
    if key not in mapping:
        raise KeyError(f"missing required config key: {key}")
    return mapping[key]


def _resolve(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def _filename_from_url(url: str) -> str:
    filename = Path(urlparse(url).path).name
    if not filename:
        raise ValueError(f"cannot derive APK filename from URL: {url}")
    return filename


def _default_headsets_from_quest(root: Path, quest_raw: Dict[str, Any]) -> HeadsetConfig:
    profile = _parse_headset_profile(root, "quest3", quest_raw)
    return HeadsetConfig(default="quest3", profiles={"quest3": profile})


def _parse_headset_profile(root: Path, name: str, raw: Dict[str, Any]) -> HeadsetProfile:
    apk_url = str(_require(raw, "apk_url"))
    default_path = f"assets/apk/{name}/{_filename_from_url(apk_url)}"
    install_args_raw = raw.get("install_args", ["-g"])
    if isinstance(install_args_raw, str):
        install_args = [install_args_raw]
    else:
        install_args = [str(value) for value in install_args_raw]
    return HeadsetProfile(
        name=name,
        display_name=str(raw.get("display_name", name)),
        apk_version=str(_require(raw, "apk_version")),
        apk_url=apk_url,
        apk_sha256=str(_require(raw, "apk_sha256")),
        apk_path=_resolve(root, str(raw.get("apk_path", default_path))),
        install_args=install_args,
        adb_label=str(raw.get("adb_label", raw.get("display_name", name))),
    )


def _parse_headsets(root: Path, raw: Dict[str, Any]) -> HeadsetConfig:
    if "headsets" not in raw:
        return _default_headsets_from_quest(root, _require(raw, "quest"))

    headsets_raw = _require(raw, "headsets")
    default = str(headsets_raw.get("default", "quest3"))
    profiles_raw = headsets_raw.get("profiles")
    if profiles_raw is None:
        profiles_raw = {key: value for key, value in headsets_raw.items() if key != "default"}
    if not isinstance(profiles_raw, dict) or not profiles_raw:
        raise ValueError("headsets.profiles must define at least one headset profile")

    profiles = {
        str(name): _parse_headset_profile(root, str(name), profile_raw)
        for name, profile_raw in profiles_raw.items()
    }
    config = HeadsetConfig(default=default, profiles=profiles)
    config.require(default)
    return config


def _pose_map_from_degrees(
    raw_positions: Dict[str, Any],
    arms: Dict[str, ArmConfig],
    *,
    config_key: str,
    required: bool,
) -> Dict[str, List[float]]:
    positions: Dict[str, List[float]] = {}
    for arm_name in arms:
        values = raw_positions.get(arm_name, [])
        if required and len(values) != 7:
            raise ValueError(f"{config_key}.{arm_name} must define exactly 7 joint values")
        positions[arm_name] = [radians(float(value)) for value in values]
    return positions


def load_config(path: str | Path) -> TeleopConfig:
    config_path = Path(path).expanduser().resolve()
    root = config_path.parents[1]
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    robot = _require(raw, "robot")
    arms_raw = _require(raw, "arms")
    arms = {
        name: ArmConfig(
            name=name,
            channel=str(_require(arm_raw, "channel")),
            link_name=str(_require(arm_raw, "link_name")),
            joint_names=list(_require(arm_raw, "joint_names")),
            pose_source=str(_require(arm_raw, "pose_source")),
            control_trigger=str(_require(arm_raw, "control_trigger")),
            gripper_trigger=str(_require(arm_raw, "gripper_trigger")),
        )
        for name, arm_raw in arms_raw.items()
    }
    for arm in arms.values():
        if len(arm.joint_names) != 7:
            raise ValueError(f"{arm.name} must define exactly 7 joint names for Nero")

    gripper_raw = _require(raw, "gripper")
    camera_raw = raw.get("camera", {})
    camera_config = CameraConfig(
        enabled=bool(camera_raw.get("enabled", False)),
        serials={str(name): str(serial) for name, serial in camera_raw.get("serials", {}).items()},
        width=int(camera_raw.get("width", 640)),
        height=int(camera_raw.get("height", 480)),
        fps=int(camera_raw.get("fps", 30)),
        enable_depth=bool(camera_raw.get("enable_depth", False)),
        enable_compression=bool(camera_raw.get("enable_compression", True)),
        jpg_quality=int(camera_raw.get("jpg_quality", 85)),
    )
    dataset_capture_raw = raw.get("dataset_capture", {})
    return_to_start_raw = raw.get("return_to_start", {})
    safety_raw = _require(raw, "safety")
    startup_raw = raw.get("startup", {})
    shutdown_raw = raw.get("shutdown", {})
    xr_mapping_raw = raw.get("xr_mapping", {})
    pc_service_raw = _require(raw, "pc_service")
    headsets = _parse_headsets(root, raw)

    command_mode = str(robot.get("command_mode", "move_j"))
    if command_mode not in {"move_j", "move_js"}:
        raise ValueError("robot.command_mode must be either move_j or move_js")
    teleop_command_mode = str(robot.get("teleop_command_mode", command_mode))
    if teleop_command_mode not in {"move_j", "move_js"}:
        raise ValueError("robot.teleop_command_mode must be either move_j or move_js")
    allow_move_js = bool(robot.get("allow_move_js", False))
    if "move_js" in {command_mode, teleop_command_mode} and not allow_move_js:
        raise ValueError("robot.allow_move_js must be true when command_mode or teleop_command_mode uses move_js")

    startup_enabled = bool(startup_raw.get("enabled", False))
    startup_positions = _pose_map_from_degrees(
        startup_raw.get("joint_positions_deg", startup_raw.get("joint_positions", {})),
        arms,
        config_key="startup.joint_positions_deg",
        required=startup_enabled,
    )
    shutdown_enabled = bool(shutdown_raw.get("enabled", True))
    shutdown_positions = _pose_map_from_degrees(
        shutdown_raw.get("joint_positions_deg", {}),
        arms,
        config_key="shutdown.joint_positions_deg",
        required=shutdown_enabled,
    )
    translation_sign = [float(value) for value in xr_mapping_raw.get("translation_sign", [1.0, 1.0, 1.0])]
    if len(translation_sign) != 3:
        raise ValueError("xr_mapping.translation_sign must define exactly 3 values")
    rotation_sign = [float(value) for value in xr_mapping_raw.get("rotation_sign", translation_sign)]
    if len(rotation_sign) != 3:
        raise ValueError("xr_mapping.rotation_sign must define exactly 3 values")
    if any(value not in {-1.0, 1.0} for value in rotation_sign):
        raise ValueError("xr_mapping.rotation_sign values must be either -1.0 or 1.0")
    if rotation_sign[0] * rotation_sign[1] * rotation_sign[2] < 0.0:
        raise ValueError("xr_mapping.rotation_sign must be a proper rotation, not a mirror transform")
    control_mode = str(xr_mapping_raw.get("control_mode", "position"))
    if control_mode not in {"position", "pose"}:
        raise ValueError("xr_mapping.control_mode must be either position or pose")
    return_to_start_hold_s = float(return_to_start_raw.get("hold_s", 1.0))
    if return_to_start_hold_s <= 0.0:
        raise ValueError("return_to_start.hold_s must be positive")

    return TeleopConfig(
        root=root,
        name=str(robot.get("name", "nero_dual_agx")),
        urdf_path=_resolve(root, str(_require(robot, "urdf_path"))),
        firmware=str(robot.get("firmware", "default")),
        interface=str(robot.get("interface", "socketcan")),
        bitrate=int(robot.get("bitrate", 1000000)),
        control_rate_hz=int(robot.get("control_rate_hz", 30)),
        teleop_speed_percent=int(robot.get("teleop_speed_percent", 25)),
        log_dir=_resolve(root, str(robot.get("log_dir", "logs/nero_dual_agx"))),
        scale_factor=float(robot.get("scale_factor", 1.0)),
        command_mode=command_mode,
        teleop_command_mode=teleop_command_mode,
        allow_move_js=allow_move_js,
        arms=arms,
        gripper=GripperConfig(
            enabled=bool(gripper_raw.get("enabled", True)),
            open_width_m=float(gripper_raw.get("open_width_m", 0.07)),
            close_width_m=float(gripper_raw.get("close_width_m", 0.0)),
            max_delta_m_per_cycle=float(gripper_raw.get("max_delta_m_per_cycle", 0.003)),
            command_deadband_m=float(gripper_raw.get("command_deadband_m", 0.0005)),
        ),
        camera=camera_config,
        safety=SafetyConfig(
            deadman_threshold=float(safety_raw.get("deadman_threshold", 0.5)),
            xr_timeout_s=float(safety_raw.get("xr_timeout_s", 0.25)),
            max_joint_delta_rad_per_cycle=float(safety_raw.get("max_joint_delta_rad_per_cycle", 0.035)),
            hold_on_inactive=bool(safety_raw.get("hold_on_inactive", True)),
            go_home_on_shutdown=bool(safety_raw.get("go_home_on_shutdown", False)),
            disable_on_shutdown=bool(safety_raw.get("disable_on_shutdown", False)),
        ),
        startup=StartupConfig(
            enabled=startup_enabled,
            joint_positions=startup_positions,
            max_delta_rad_per_cycle=float(startup_raw.get("max_delta_rad_per_cycle", 0.005)),
            tolerance_rad=float(startup_raw.get("tolerance_rad", 0.02)),
            control_rate_hz=int(startup_raw.get("control_rate_hz", 20)),
            timeout_s=float(startup_raw.get("timeout_s", 60.0)),
            settle_s=float(startup_raw.get("settle_s", 1.0)),
            speed_percent=int(startup_raw.get("speed_percent", 10)),
        ),
        shutdown=ShutdownConfig(
            enabled=shutdown_enabled,
            joint_positions=shutdown_positions,
            max_delta_rad_per_cycle=float(shutdown_raw.get("max_delta_rad_per_cycle", 0.005)),
            tolerance_rad=float(shutdown_raw.get("tolerance_rad", 0.02)),
            control_rate_hz=int(shutdown_raw.get("control_rate_hz", 20)),
            timeout_s=float(shutdown_raw.get("timeout_s", 60.0)),
            settle_s=float(shutdown_raw.get("settle_s", 1.0)),
            speed_percent=int(shutdown_raw.get("speed_percent", 10)),
        ),
        xr_mapping=XrMappingConfig(
            translation_sign=translation_sign,
            rotation_sign=rotation_sign,
            position_deadband_m=float(xr_mapping_raw.get("position_deadband_m", 0.006)),
            rotation_deadband_rad=float(xr_mapping_raw.get("rotation_deadband_rad", 0.035)),
            rotation_scale=float(xr_mapping_raw.get("rotation_scale", 0.85)),
            position_weight=float(xr_mapping_raw.get("position_weight", 1.0)),
            orientation_weight=float(xr_mapping_raw.get("orientation_weight", 0.35)),
            posture_regularization_weight=float(xr_mapping_raw.get("posture_regularization_weight", 0.0)),
            control_mode=control_mode,
        ),
        dataset_capture=DatasetCaptureConfig(
            enabled=bool(dataset_capture_raw.get("enabled", False)),
            format=str(dataset_capture_raw.get("format", "lerobot_v3")),
            root_dir=_resolve(root, str(dataset_capture_raw.get("root_dir", "datasets/lerobot"))),
            repo_id=str(dataset_capture_raw.get("repo_id", "local/nero_tube_pick_place")),
            fps=int(dataset_capture_raw.get("fps", min(camera_config.fps, 10) if camera_config.fps else 10)),
            robot_type=str(dataset_capture_raw.get("robot_type", "agilex_nero_dual")),
            task=str(dataset_capture_raw.get("task", "")),
            start_button=str(dataset_capture_raw.get("start_button", "X")),
            discard_button=str(dataset_capture_raw.get("discard_button", "Y")),
            min_episode_frames=int(dataset_capture_raw.get("min_episode_frames", 5)),
            image_streams=[
                str(name)
                for name in dataset_capture_raw.get("image_streams", list(camera_config.serials.keys()))
            ],
            image_writer_threads=(
                int(dataset_capture_raw["image_writer_threads"])
                if dataset_capture_raw.get("image_writer_threads") is not None
                else None
            ),
            image_writer_processes=(
                int(dataset_capture_raw["image_writer_processes"])
                if dataset_capture_raw.get("image_writer_processes") is not None
                else None
            ),
        ),
        return_to_start=ReturnToStartConfig(
            enabled=bool(return_to_start_raw.get("enabled", True)),
            button=str(return_to_start_raw.get("button", "A")),
            hold_s=return_to_start_hold_s,
        ),
        headsets=headsets,
        pc_service_run_script=Path(str(_require(pc_service_raw, "linux_run_script"))),
    )
