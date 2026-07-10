from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List


@dataclass
class DryRunNeroArm:
    name: str
    channel: str
    joints: List[float] = field(default_factory=lambda: [0.0] * 7)
    gripper_width_m: float = 0.07

    def connect(self, auto_enable: bool = True) -> None:
        print(f"[dry-run] {self.name}: connect channel={self.channel} auto_enable={auto_enable}")

    def enable(self, timeout_s: float = 5.0) -> None:
        print(f"[dry-run] {self.name}: enable")

    def disable(self) -> None:
        print(f"[dry-run] {self.name}: disable")

    def disconnect(self) -> None:
        print(f"[dry-run] {self.name}: disconnect")

    def is_ok(self) -> bool:
        return True

    def get_joint_positions(self) -> List[float]:
        return list(self.joints)

    def get_joint_velocities(self) -> List[float]:
        return [0.0] * 7

    def send_joint_positions(self, positions: Iterable[float], command_mode: str | None = None) -> None:
        self.joints = [float(v) for v in positions]

    def send_gripper_width(self, width_m: float) -> None:
        self.gripper_width_m = float(width_m)

    def emergency_stop(self) -> None:
        print(f"[dry-run] {self.name}: emergency_stop")
