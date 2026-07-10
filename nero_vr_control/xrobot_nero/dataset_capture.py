from __future__ import annotations

import inspect
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Protocol

import numpy as np

from .config import DatasetCaptureConfig, TeleopConfig


CAMERA_FEATURES = {
    "head": "observation.images.head",
    "left_wrist": "observation.images.left_wrist",
    "right_wrist": "observation.images.right_wrist",
}


def _arm_order(config: TeleopConfig) -> List[str]:
    preferred = [name for name in ("left_arm", "right_arm") if name in config.arms]
    return preferred + [name for name in config.arms if name not in preferred]


def vector_names(config: TeleopConfig) -> List[str]:
    names: List[str] = []
    for arm_name in _arm_order(config):
        names.extend(config.arms[arm_name].joint_names)
        names.append(f"{arm_name}_gripper_width")
    return names


def state_vector(
    config: TeleopConfig,
    qpos: Dict[str, Iterable[float]],
    gripper_widths: Dict[str, float | None],
) -> List[float]:
    values: List[float] = []
    for arm_name in _arm_order(config):
        joints = list(qpos.get(arm_name, [0.0] * len(config.arms[arm_name].joint_names)))
        values.extend(float(value) for value in joints)
        width = gripper_widths.get(arm_name)
        if width is None:
            width = config.gripper.open_width_m
        values.append(float(width))
    return values


@dataclass
class DatasetSample:
    timestamp_s: float
    wall_time_ns: int
    state: List[float]
    action: List[float]
    robot_state: Dict[str, Any]
    gripper_widths: Dict[str, float | None]
    active: Dict[str, bool]
    xr_stale: bool
    images: Dict[str, Dict[str, Any]]


class EpisodeRecorder(Protocol):
    @property
    def is_recording(self) -> bool:
        ...

    def start_episode(self, task: str | None = None) -> None:
        ...

    def record(self, sample: DatasetSample) -> None:
        ...

    def finish_episode(self) -> Path | None:
        ...

    def discard_episode(self) -> None:
        ...

    def finalize(self) -> None:
        ...


def image_feature_name(stream: str) -> str:
    return CAMERA_FEATURES.get(stream, f"observation.images.{stream}")


def lerobot_features(config: TeleopConfig, capture: DatasetCaptureConfig) -> Dict[str, Dict[str, Any]]:
    vector_dim = len(vector_names(config))
    features: Dict[str, Dict[str, Any]] = {
        "observation.state": {
            "dtype": "float32",
            "shape": (vector_dim,),
            "names": vector_names(config),
        },
        "action": {
            "dtype": "float32",
            "shape": (vector_dim,),
            "names": vector_names(config),
        },
    }
    for stream in capture.image_streams:
        features[image_feature_name(stream)] = {
            "dtype": "image",
            "shape": (config.camera.height, config.camera.width, 3),
            "names": ["height", "width", "channel"],
        }
    return features


def create_dataset_recorder(config: TeleopConfig, capture: DatasetCaptureConfig) -> EpisodeRecorder:
    if capture.format != "lerobot_v3":
        raise ValueError("dataset_capture.format must be 'lerobot_v3'")
    return LeRobotV3EpisodeRecorder(config, capture)


class LeRobotV3EpisodeRecorder:
    """Direct LeRobot v3 writer for Nero demonstrations.

    The recorded actions are absolute joint/gripper commands. Joint-relative
    actions for pi0.5 are produced later by the training/inference processor.
    """

    def __init__(
        self,
        config: TeleopConfig,
        capture: DatasetCaptureConfig,
        *,
        dataset_cls: Any | None = None,
    ):
        self.config = config
        self.capture = capture
        self.root = capture.root_dir.expanduser()
        self.repo_id = capture.repo_id
        self.dataset_path = self.root / self.repo_id
        self._dataset_cls = dataset_cls or _import_lerobot_dataset()
        self.dataset = self._create_dataset()
        self._is_recording = False
        self._task = capture.task
        self._frame_index = 0
        self._episode_index = self._dataset_total_episodes()
        self._dropped_frames = 0
        self._finalized = False
        self._write_xrobot_metadata()

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    def start_episode(self, task: str | None = None) -> None:
        if self._is_recording:
            return
        self._task = task if task is not None else self.capture.task
        self._frame_index = 0
        self._dropped_frames = 0
        self._is_recording = True

    def record(self, sample: DatasetSample) -> None:
        if not self._is_recording:
            return
        frame = self._sample_to_frame(sample)
        if frame is None:
            return
        self.dataset.add_frame(frame)
        self._frame_index += 1

    def finish_episode(self) -> Path | None:
        if not self._is_recording:
            return None
        if self._frame_index < self.capture.min_episode_frames:
            print(
                "Discarding short dataset episode: "
                f"{self._frame_index} frames < {self.capture.min_episode_frames} minimum."
            )
            self._clear_episode_buffer()
            self._is_recording = False
            return None

        self._save_episode(self._task)
        self._is_recording = False
        self._episode_index += 1
        return self.dataset_path

    def discard_episode(self) -> None:
        if not self._is_recording:
            return
        self._clear_episode_buffer()
        self._is_recording = False

    def finalize(self) -> None:
        if self._finalized:
            return
        if self._is_recording:
            self.finish_episode()
        finalize = getattr(self.dataset, "finalize", None)
        if callable(finalize):
            finalize()
        self._finalized = True

    def _create_dataset(self) -> Any:
        self.root.mkdir(parents=True, exist_ok=True)
        kwargs = {
            "repo_id": self.repo_id,
            "root": self.dataset_path,
            "robot_type": self.capture.robot_type,
            "fps": self.capture.fps,
            "features": lerobot_features(self.config, self.capture),
        }
        for optional_key, value in {
            "image_writer_threads": self.capture.image_writer_threads,
            "image_writer_processes": self.capture.image_writer_processes,
        }.items():
            if value is not None:
                kwargs[optional_key] = value
        try:
            return self._create_new_dataset(kwargs)
        except FileExistsError:
            if self._can_reset_empty_dataset_dir():
                print(f"Resetting empty LeRobot dataset directory: {self.dataset_path}")
                shutil.rmtree(self.dataset_path)
                return self._create_new_dataset(kwargs)
            return self._load_existing_dataset_for_recording()

    def _create_new_dataset(self, kwargs: Dict[str, Any]) -> Any:
        try:
            return self._dataset_cls.create(**kwargs)
        except TypeError:
            accepted = set(inspect.signature(self._dataset_cls.create).parameters)
            filtered = {key: value for key, value in kwargs.items() if key in accepted}
            return self._dataset_cls.create(**filtered)

    def _load_existing_dataset_for_recording(self) -> Any:
        try:
            dataset = self._dataset_cls(
                self.repo_id,
                root=self.dataset_path,
                download_videos=False,
            )
        except TypeError:
            dataset = self._dataset_cls(self.repo_id, root=self.dataset_path)
        except Exception as exc:
            raise RuntimeError(
                "LeRobot dataset directory already exists but could not be loaded for recording. "
                f"If it is an unwanted failed capture, move or remove it: {self.dataset_path}"
            ) from exc

        start_writer = getattr(dataset, "start_image_writer", None)
        if callable(start_writer):
            start_writer(
                num_processes=self.capture.image_writer_processes or 0,
                num_threads=self.capture.image_writer_threads or 0,
            )
        create_buffer = getattr(dataset, "create_episode_buffer", None)
        if callable(create_buffer):
            dataset.episode_buffer = create_buffer()
        print(
            "Loaded existing LeRobot dataset for appending: "
            f"{self.dataset_path} ({self._dataset_total_episodes(dataset)} episodes)"
        )
        return dataset

    def _can_reset_empty_dataset_dir(self) -> bool:
        if not self.dataset_path.exists() or not self.dataset_path.is_dir():
            return False
        try:
            self.dataset_path.resolve().relative_to(self.root.resolve())
        except ValueError:
            return False

        info_path = self.dataset_path / "meta" / "info.json"
        if not info_path.exists():
            return not any(self.dataset_path.iterdir())
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if int(info.get("total_episodes", 0)) != 0 or int(info.get("total_frames", 0)) != 0:
            return False

        recorded_patterns = [
            "data/**/*.parquet",
            "videos/**/*.mp4",
            "images/**/*.png",
            "images/**/*.jpg",
            "images/**/*.jpeg",
        ]
        return not any(
            any(self.dataset_path.glob(pattern))
            for pattern in recorded_patterns
        )

    def _dataset_total_episodes(self, dataset: Any | None = None) -> int:
        dataset = dataset if dataset is not None else self.dataset
        meta = getattr(dataset, "meta", None)
        if meta is not None and hasattr(meta, "total_episodes"):
            return int(meta.total_episodes)
        if hasattr(dataset, "num_episodes"):
            return int(dataset.num_episodes)
        return 0

    def _sample_to_frame(self, sample: DatasetSample) -> Dict[str, Any] | None:
        frame: Dict[str, Any] = {
            "observation.state": np.asarray(sample.state, dtype=np.float32),
            "action": np.asarray(sample.action, dtype=np.float32),
            "task": self._task or self.capture.task,
        }
        for stream in self.capture.image_streams:
            frame_data = sample.images.get(stream) or {}
            color = frame_data.get("color")
            if color is None:
                self._report_dropped_frame(f"missing image stream {stream}")
                return None
            frame[image_feature_name(stream)] = _as_rgb_array(color)
        return frame

    def _save_episode(self, task: str) -> None:
        try:
            self.dataset.save_episode(task=task)
        except TypeError:
            self.dataset.save_episode()

    def _clear_episode_buffer(self) -> None:
        clear = getattr(self.dataset, "clear_episode_buffer", None)
        if callable(clear):
            clear()
            return
        if hasattr(self.dataset, "episode_buffer"):
            buffer = getattr(self.dataset, "episode_buffer")
            if hasattr(buffer, "clear"):
                buffer.clear()

    def _write_xrobot_metadata(self) -> None:
        metadata = {
            "format": "lerobot_v3",
            "robot_name": self.config.name,
            "robot_type": self.capture.robot_type,
            "fps": self.capture.fps,
            "state_names": vector_names(self.config),
            "action_names": vector_names(self.config),
            "action_semantics": "absolute_joint_and_gripper_command",
            "training_action_semantics": "joint_space_relative_action_with_absolute_gripper",
            "image_streams": self.capture.image_streams,
            "camera_serials": self.config.camera.serials,
            "created_wall_time_ns": time.time_ns(),
        }
        try:
            self.dataset_path.mkdir(parents=True, exist_ok=True)
            (self.dataset_path / "xrobot_nero_metadata.json").write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"Failed to write xrobot dataset metadata: {exc}")

    def _report_dropped_frame(self, reason: str) -> None:
        self._dropped_frames += 1
        if self._dropped_frames <= 3 or self._dropped_frames % 50 == 0:
            print(f"Dropping dataset frame #{self._dropped_frames}: {reason}")


def _import_lerobot_dataset() -> Any:
    try:
        from lerobot.datasets.lerobot_dataset import LeRobotDataset

        return LeRobotDataset
    except ImportError:
        try:
            from lerobot.common.datasets.lerobot_dataset import LeRobotDataset

            return LeRobotDataset
        except ImportError as exc:
            raise RuntimeError(
                "LeRobot is required for dataset capture. Install it in the local "
                "capture environment, for example: pip install 'lerobot[pi] @ "
                "git+https://github.com/huggingface/lerobot.git'"
            ) from exc


def _as_rgb_array(image: Any) -> np.ndarray:
    if isinstance(image, (bytes, bytearray, memoryview)):
        return _decode_rgb_bytes(bytes(image))
    array = np.asarray(image)
    if array.ndim != 3 or array.shape[2] != 3:
        raise ValueError(f"expected RGB image with shape HxWx3, got {array.shape}")
    if array.dtype != np.uint8:
        array = np.clip(array, 0, 255).astype(np.uint8)
    return array


def _decode_rgb_bytes(data: bytes) -> np.ndarray:
    try:
        import cv2

        encoded = np.frombuffer(data, dtype=np.uint8)
        bgr = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("cv2.imdecode returned None")
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    except ImportError:
        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError("opencv-python or Pillow is required to decode compressed camera frames") from exc

        import io

        with Image.open(io.BytesIO(data)) as image:
            return np.asarray(image.convert("RGB"))
