from pathlib import Path
from math import pi

import pytest
import yaml

from xrobot_nero.config import load_config


def test_load_default_config():
    cfg = load_config(Path(__file__).parents[1] / "configs" / "nero_dual_agx.yml")
    assert cfg.name == "nero_dual_agx"
    assert cfg.bitrate == 1000000
    assert cfg.urdf_path.name == "dual_nero_official.urdf"
    assert cfg.control_rate_hz == 75
    assert cfg.scale_factor == 0.75
    assert cfg.teleop_speed_percent == 30
    assert cfg.arms["left_arm"].channel == "can0"
    assert cfg.arms["right_arm"].channel == "can1"
    assert cfg.arms["left_arm"].pose_source == "right_controller"
    assert cfg.arms["left_arm"].control_trigger == "right_grip"
    assert cfg.arms["left_arm"].gripper_trigger == "right_trigger"
    assert cfg.arms["right_arm"].pose_source == "left_controller"
    assert cfg.arms["right_arm"].control_trigger == "left_grip"
    assert cfg.arms["right_arm"].gripper_trigger == "left_trigger"
    assert cfg.gripper.open_width_m == 0.10
    assert cfg.gripper.max_delta_m_per_cycle == 0.003
    assert cfg.gripper.command_deadband_m == 0.0003
    assert cfg.camera.enabled
    assert cfg.camera.width == 640
    assert cfg.camera.height == 480
    assert cfg.camera.fps == 30
    assert not cfg.camera.enable_depth
    assert cfg.camera.enable_compression
    assert cfg.camera.serials == {
        "left_wrist": "254522076246",
        "right_wrist": "254622075046",
        "head": "254322076225",
    }
    assert not cfg.dataset_capture.enabled
    assert cfg.dataset_capture.format == "lerobot_v3"
    assert cfg.dataset_capture.root_dir.as_posix().endswith("datasets/lerobot")
    assert cfg.dataset_capture.repo_id == "local/nero_tube_pick_place"
    assert cfg.dataset_capture.fps == 10
    assert cfg.dataset_capture.robot_type == "agilex_nero_dual"
    assert cfg.dataset_capture.task == "pick up the test tube and place it into the tube rack"
    assert cfg.dataset_capture.start_button == "X"
    assert cfg.dataset_capture.discard_button == "Y"
    assert cfg.dataset_capture.image_streams == ["head", "left_wrist", "right_wrist"]
    assert cfg.return_to_start.enabled
    assert cfg.return_to_start.button == "A"
    assert cfg.return_to_start.hold_s == 1.0
    assert cfg.command_mode == "move_j"
    assert cfg.teleop_command_mode == "move_js"
    assert cfg.allow_move_js
    assert cfg.startup.joint_positions["left_arm"] == [0.0, pi / 4, 0.0, pi / 4, 0.0, 0.0, 0.0]
    assert cfg.startup.joint_positions["right_arm"] == [0.0, pi / 4, 0.0, pi / 4, 0.0, 0.0, 0.0]
    assert cfg.shutdown.joint_positions["left_arm"] == [0.0] * 7
    assert cfg.shutdown.joint_positions["right_arm"] == [0.0] * 7
    assert cfg.safety.max_joint_delta_rad_per_cycle == 0.014
    assert cfg.startup.speed_percent == 40
    assert cfg.startup.control_rate_hz == 40
    assert cfg.startup.max_delta_rad_per_cycle == 0.022
    assert cfg.shutdown.speed_percent == 40
    assert cfg.shutdown.control_rate_hz == 40
    assert cfg.shutdown.max_delta_rad_per_cycle == 0.022
    assert cfg.xr_mapping.control_mode == "pose"
    assert cfg.xr_mapping.position_deadband_m == 0.004
    assert cfg.xr_mapping.rotation_deadband_rad == 0.035
    assert cfg.xr_mapping.rotation_scale == 0.95
    assert cfg.xr_mapping.position_weight == 1.0
    assert cfg.xr_mapping.orientation_weight == 0.45
    assert cfg.xr_mapping.posture_regularization_weight == 0.001
    assert cfg.xr_mapping.translation_sign == [-1.0, -1.0, 1.0]
    assert cfg.xr_mapping.rotation_sign == [-1.0, -1.0, 1.0]
    assert not cfg.safety.disable_on_shutdown
    assert cfg.headsets.default == "quest3"
    assert set(cfg.headsets.profiles) == {"quest3", "pico4ultra"}
    assert cfg.headsets.require("quest3").display_name == "Meta Quest 3"
    assert cfg.headsets.require("quest3").apk_path.as_posix().endswith(
        "assets/apk/quest3/XRoboToolkit-Quest-1.0.1.apk"
    )
    assert cfg.headsets.require("pico4ultra").display_name == "Pico 4 Ultra"
    assert cfg.headsets.require("pico4ultra").apk_sha256 == (
        "6b2bb282405673d24abcb1980e3478b8f1052e90f7207b1f24cc56a59f8d8261"
    )
    assert cfg.quest is cfg.headsets.require("quest3")


def test_headset_profiles_share_robot_control_config():
    cfg = load_config(Path(__file__).parents[1] / "configs" / "nero_dual_agx.yml")
    quest = cfg.headsets.require("quest3")
    pico = cfg.headsets.require("pico4ultra")

    assert quest.name == "quest3"
    assert pico.name == "pico4ultra"
    assert cfg.teleop_command_mode == "move_js"
    assert cfg.allow_move_js
    assert cfg.arms["left_arm"].pose_source == "right_controller"
    assert cfg.arms["right_arm"].pose_source == "left_controller"
    assert cfg.xr_mapping.translation_sign == [-1.0, -1.0, 1.0]
    assert cfg.xr_mapping.rotation_sign == [-1.0, -1.0, 1.0]
    assert cfg.safety.max_joint_delta_rad_per_cycle == 0.014


def test_legacy_quest_config_is_supported(tmp_path):
    src = Path(__file__).parents[1] / "configs" / "nero_dual_agx.yml"
    raw = yaml.safe_load(src.read_text(encoding="utf-8"))
    quest = raw["headsets"]["profiles"]["quest3"]
    raw.pop("headsets")
    raw["quest"] = {
        "apk_version": quest["apk_version"],
        "apk_url": quest["apk_url"],
        "apk_sha256": quest["apk_sha256"],
    }
    path = tmp_path / "legacy_quest.yml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    cfg = load_config(path)
    assert cfg.headsets.default == "quest3"
    assert set(cfg.headsets.profiles) == {"quest3"}
    assert cfg.quest.apk_version == "1.0.1"


def test_rejects_mirror_rotation_sign(tmp_path):
    src = Path(__file__).parents[1] / "configs" / "nero_dual_agx.yml"
    raw = yaml.safe_load(src.read_text(encoding="utf-8"))
    raw["xr_mapping"]["rotation_sign"] = [-1.0, -1.0, -1.0]
    path = tmp_path / "bad_rotation_sign.yml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="proper rotation"):
        load_config(path)


def test_move_js_requires_explicit_allow(tmp_path):
    src = Path(__file__).parents[1] / "configs" / "nero_dual_agx.yml"
    raw = yaml.safe_load(src.read_text(encoding="utf-8"))
    raw["robot"]["allow_move_js"] = False
    path = tmp_path / "move_js_without_allow.yml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="allow_move_js"):
        load_config(path)
