from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import numpy as np

from .config import TeleopConfig
from .pi05_relative_actions import joint_relative_action_to_absolute


@dataclass
class Pi05Observation:
    state: np.ndarray
    images: Dict[str, np.ndarray]
    prompt: str


class LocalPi05PolicyRunner:
    """Lazy local pi0.5 policy wrapper.

    The policy is expected to output joint-space relative actions with absolute
    gripper commands. This runner restores absolute commands before they enter
    the Nero control/safety layer.
    """

    def __init__(self, config: TeleopConfig, *, policy_config: str, checkpoint_dir: str | Path):
        self.config = config
        self.policy_config = policy_config
        self.checkpoint_dir = Path(checkpoint_dir).expanduser()
        self.policy = self._load_policy()

    def infer_absolute_action(self, observation: Pi05Observation) -> np.ndarray:
        model_input = self._to_policy_input(observation)
        output = self.policy.infer(model_input)
        relative_action = np.asarray(output["actions"], dtype=np.float32)
        if relative_action.ndim > 1:
            relative_action = relative_action[0]
        return joint_relative_action_to_absolute(self.config, observation.state, relative_action)

    def _load_policy(self) -> Any:
        try:
            from openpi.policies import policy_config as _policy_config
            from openpi.training import config as _training_config
        except ImportError as exc:
            raise RuntimeError(
                "OpenPI is required for local pi0.5 inference. Install OpenPI on this "
                "machine or run inference on the server and stream actions back."
            ) from exc

        config = _training_config.get_config(self.policy_config)
        return _policy_config.create_trained_policy(config, self.checkpoint_dir)

    @staticmethod
    def _to_policy_input(observation: Pi05Observation) -> Dict[str, Any]:
        return {
            "observation.state": observation.state,
            "observation.images.head": observation.images.get("head"),
            "observation.images.left_wrist": observation.images.get("left_wrist"),
            "observation.images.right_wrist": observation.images.get("right_wrist"),
            "prompt": observation.prompt,
        }
