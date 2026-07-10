import json

import numpy as np
import pytest

from xrobot_nero.config import load_config
from xrobot_nero.dataset_capture import (
    DatasetSample,
    LeRobotV3EpisodeRecorder,
    lerobot_features,
    state_vector,
    vector_names,
)
from xrobot_nero.pi05_relative_actions import (
    absolute_action_to_joint_relative,
    gripper_indices,
    joint_indices,
    joint_relative_action_to_absolute,
)


class FakeLeRobotDataset:
    create_calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.frames = []
        self.saved_tasks = []
        self.finalized = False
        self.cleared = False

    @classmethod
    def create(cls, **kwargs):
        cls.create_calls.append(kwargs)
        return cls(**kwargs)

    def add_frame(self, frame):
        self.frames.append(frame)

    def save_episode(self, task=None):
        self.saved_tasks.append(task)

    def clear_episode_buffer(self):
        self.frames.clear()
        self.cleared = True

    def finalize(self):
        self.finalized = True


class ExistingPathFakeLeRobotDataset(FakeLeRobotDataset):
    create_calls = []

    @classmethod
    def create(cls, **kwargs):
        cls.create_calls.append(kwargs)
        if kwargs["root"].exists():
            raise FileExistsError(kwargs["root"])
        return cls(**kwargs)


def test_state_vector_matches_dual_arm_order():
    cfg = load_config("configs/nero_dual_agx.yml")
    values = state_vector(
        cfg,
        {
            "left_arm": [1, 2, 3, 4, 5, 6, 7],
            "right_arm": [8, 9, 10, 11, 12, 13, 14],
        },
        {"left_arm": 0.01, "right_arm": 0.02},
    )

    assert len(values) == 16
    assert values == [1, 2, 3, 4, 5, 6, 7, 0.01, 8, 9, 10, 11, 12, 13, 14, 0.02]
    assert vector_names(cfg)[7] == "left_arm_gripper_width"
    assert vector_names(cfg)[15] == "right_arm_gripper_width"


def test_lerobot_features_use_absolute_state_and_action_schema():
    cfg = load_config("configs/nero_dual_agx.yml")
    capture = cfg.dataset_capture.__class__(
        **{
            **cfg.dataset_capture.__dict__,
            "image_streams": ["head"],
        }
    )

    features = lerobot_features(cfg, capture)

    assert features["observation.state"]["shape"] == (16,)
    assert features["observation.state"]["names"] == vector_names(cfg)
    assert features["action"]["shape"] == (16,)
    assert features["action"]["names"] == vector_names(cfg)
    assert "observation.images.head" in features


def test_lerobot_recorder_writes_absolute_action(tmp_path):
    cfg = load_config("configs/nero_dual_agx.yml")
    capture = cfg.dataset_capture.__class__(
        **{
            **cfg.dataset_capture.__dict__,
            "root_dir": tmp_path,
            "repo_id": "local/test_dataset",
            "image_streams": ["head"],
            "min_episode_frames": 1,
        }
    )
    recorder = LeRobotV3EpisodeRecorder(cfg, capture, dataset_cls=FakeLeRobotDataset)
    recorder.start_episode(task="test task")
    recorder.record(
        DatasetSample(
            timestamp_s=0.1,
            wall_time_ns=123,
            state=[0.0] * 16,
            action=[1.0] * 16,
            robot_state={"qpos": {"left_arm": [0.0] * 7, "right_arm": [0.0] * 7}},
            gripper_widths={"left_arm": 0.1, "right_arm": 0.1},
            active={"left_arm": True, "right_arm": False},
            xr_stale=False,
            images={"head": {"color": np.zeros((480, 640, 3), dtype=np.uint8), "timestamp_us": 456}},
        )
    )
    dataset_path = recorder.finish_episode()
    recorder.finalize()

    assert dataset_path == tmp_path / "local/test_dataset"
    assert len(recorder.dataset.frames) == 1
    frame = recorder.dataset.frames[0]
    np.testing.assert_array_equal(frame["observation.state"], np.zeros(16, dtype=np.float32))
    np.testing.assert_array_equal(frame["action"], np.ones(16, dtype=np.float32))
    assert recorder.dataset.saved_tasks == ["test task"]
    assert recorder.dataset.finalized


def test_lerobot_recorder_drops_missing_camera_frame(tmp_path):
    cfg = load_config("configs/nero_dual_agx.yml")
    capture = cfg.dataset_capture.__class__(
        **{
            **cfg.dataset_capture.__dict__,
            "root_dir": tmp_path,
            "repo_id": "local/test_dataset",
            "image_streams": ["head"],
            "min_episode_frames": 1,
        }
    )
    recorder = LeRobotV3EpisodeRecorder(cfg, capture, dataset_cls=FakeLeRobotDataset)
    recorder.start_episode(task="test task")
    recorder.record(
        DatasetSample(
            timestamp_s=0.1,
            wall_time_ns=123,
            state=[0.0] * 16,
            action=[1.0] * 16,
            robot_state={},
            gripper_widths={},
            active={},
            xr_stale=False,
            images={},
        )
    )

    assert recorder.dataset.frames == []
    assert recorder.finish_episode() is None
    assert recorder.dataset.cleared


def test_lerobot_recorder_resets_empty_failed_dataset_dir(tmp_path):
    cfg = load_config("configs/nero_dual_agx.yml")
    dataset_path = tmp_path / "local/test_dataset"
    (dataset_path / "meta").mkdir(parents=True)
    (dataset_path / "images/observation.images.head").mkdir(parents=True)
    (dataset_path / "meta/info.json").write_text(
        json.dumps({"total_episodes": 0, "total_frames": 0}),
        encoding="utf-8",
    )

    capture = cfg.dataset_capture.__class__(
        **{
            **cfg.dataset_capture.__dict__,
            "root_dir": tmp_path,
            "repo_id": "local/test_dataset",
            "image_streams": ["head"],
            "min_episode_frames": 1,
        }
    )
    recorder = LeRobotV3EpisodeRecorder(cfg, capture, dataset_cls=ExistingPathFakeLeRobotDataset)

    assert isinstance(recorder.dataset, ExistingPathFakeLeRobotDataset)
    assert len(ExistingPathFakeLeRobotDataset.create_calls) == 2
    assert (dataset_path / "xrobot_nero_metadata.json").exists()
    assert not (dataset_path / "images/observation.images.head").exists()


def test_pi05_relative_action_processor_keeps_grippers_absolute():
    cfg = load_config("configs/nero_dual_agx.yml")
    state = np.array([1, 2, 3, 4, 5, 6, 7, 0.01, 8, 9, 10, 11, 12, 13, 14, 0.02], dtype=np.float32)
    absolute = np.array([2, 3, 4, 5, 6, 7, 8, 0.08, 9, 10, 11, 12, 13, 14, 15, 0.09], dtype=np.float32)

    relative = absolute_action_to_joint_relative(cfg, state, absolute)

    assert joint_indices(cfg) == [0, 1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14]
    assert gripper_indices(cfg) == [7, 15]
    np.testing.assert_allclose(relative[joint_indices(cfg)], np.ones(14, dtype=np.float32))
    np.testing.assert_allclose(relative[gripper_indices(cfg)], [0.08, 0.09])
    np.testing.assert_allclose(joint_relative_action_to_absolute(cfg, state, relative), absolute)


def test_pi05_relative_action_chunk_is_not_sequential_delta():
    cfg = load_config("configs/nero_dual_agx.yml")
    state = np.zeros(16, dtype=np.float32)
    state[0] = 10.0
    state[7] = 0.01
    state[15] = 0.02
    absolute_chunk = np.zeros((2, 16), dtype=np.float32)
    absolute_chunk[:, 0] = [11.0, 12.0]
    absolute_chunk[:, 7] = [0.03, 0.04]
    absolute_chunk[:, 15] = [0.05, 0.06]

    relative_chunk = absolute_action_to_joint_relative(cfg, state, absolute_chunk)

    assert relative_chunk[0, 0] == pytest.approx(1.0)
    assert relative_chunk[1, 0] == pytest.approx(2.0)
    np.testing.assert_allclose(relative_chunk[:, 7], [0.03, 0.04])
    np.testing.assert_allclose(relative_chunk[:, 15], [0.05, 0.06])
    np.testing.assert_allclose(joint_relative_action_to_absolute(cfg, state, relative_chunk), absolute_chunk)
