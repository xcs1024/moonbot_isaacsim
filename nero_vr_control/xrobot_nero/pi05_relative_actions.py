from __future__ import annotations

from typing import Iterable, List

import numpy as np

from .config import TeleopConfig
from .dataset_capture import vector_names


def gripper_indices(config: TeleopConfig) -> List[int]:
    return [index for index, name in enumerate(vector_names(config)) if name.endswith("_gripper_width")]


def joint_indices(config: TeleopConfig) -> List[int]:
    grippers = set(gripper_indices(config))
    return [index for index in range(len(vector_names(config))) if index not in grippers]


def absolute_action_to_joint_relative(
    config: TeleopConfig,
    observation_state: Iterable[float] | np.ndarray,
    absolute_action: Iterable[float] | np.ndarray,
) -> np.ndarray:
    """Convert absolute commands to joint-space relative actions.

    Joint dimensions become absolute_action - observation_state. Gripper
    dimensions remain absolute width commands. For action chunks, every row is
    relative to the same observation state; this is not sequential delta action.
    """

    state = np.asarray(observation_state, dtype=np.float32)
    action = np.asarray(absolute_action, dtype=np.float32).copy()
    if action.shape[-1] != state.shape[-1]:
        raise ValueError(f"state/action dimensions differ: {state.shape[-1]} vs {action.shape[-1]}")

    joints = joint_indices(config)
    if action.ndim == 1:
        action[joints] = action[joints] - state[joints]
    else:
        action[..., joints] = action[..., joints] - state[joints]
    return action


def joint_relative_action_to_absolute(
    config: TeleopConfig,
    observation_state: Iterable[float] | np.ndarray,
    relative_action: Iterable[float] | np.ndarray,
) -> np.ndarray:
    """Restore absolute commands from joint-space relative policy output."""

    state = np.asarray(observation_state, dtype=np.float32)
    action = np.asarray(relative_action, dtype=np.float32).copy()
    if action.shape[-1] != state.shape[-1]:
        raise ValueError(f"state/action dimensions differ: {state.shape[-1]} vs {action.shape[-1]}")

    joints = joint_indices(config)
    if action.ndim == 1:
        action[joints] = action[joints] + state[joints]
    else:
        action[..., joints] = action[..., joints] + state[joints]
    return action


class NeroPi05RelativeActionProcessor:
    """Small reusable processor for OpenPI/LeRobot training and local inference."""

    def __init__(self, config: TeleopConfig):
        self.config = config

    def preprocess_action(self, observation_state: np.ndarray, absolute_action: np.ndarray) -> np.ndarray:
        return absolute_action_to_joint_relative(self.config, observation_state, absolute_action)

    def postprocess_action(self, observation_state: np.ndarray, relative_action: np.ndarray) -> np.ndarray:
        return joint_relative_action_to_absolute(self.config, observation_state, relative_action)
