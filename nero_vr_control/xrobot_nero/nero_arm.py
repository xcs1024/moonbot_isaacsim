from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterable, List


def _message_payload(value: Any) -> Any:
    return getattr(value, "msg", value)


def _as_float_list(value: Any) -> List[float]:
    payload = _message_payload(value)
    if payload is None:
        raise RuntimeError("SDK returned no data")
    if isinstance(payload, dict):
        return [float(payload[f"joint{i}"]) for i in range(1, 8)]
    if isinstance(payload, (list, tuple)):
        return [float(v) for v in payload]
    if hasattr(payload, "__iter__") and not isinstance(payload, (str, bytes)):
        return [float(v) for v in payload]
    fields = [f"joint{i}" for i in range(1, 8)]
    if all(hasattr(payload, field) for field in fields):
        return [float(getattr(payload, field)) for field in fields]
    raise TypeError(f"cannot convert SDK payload to joint list: {type(payload)!r}")


@dataclass
class NeroArmInterface:
    name: str
    channel: str
    firmware: str = "default"
    interface: str = "socketcan"
    bitrate: int = 1000000
    command_mode: str = "move_j"
    allow_move_js: bool = False
    enable_gripper: bool = True
    speed_percent: int = 30

    def __post_init__(self) -> None:
        self.robot: Any | None = None
        self.gripper: Any | None = None
        self._last_command_mode: str | None = None

    def connect(self, auto_enable: bool = True) -> None:
        from pyAgxArm import AgxArmFactory, ArmModel, NeroFW, create_agx_arm_config

        firmware = self._resolve_firmware(NeroFW)
        cfg = create_agx_arm_config(
            robot=ArmModel.NERO,
            firmeware_version=firmware,
            interface=self.interface,
            channel=self.channel,
            bitrate=self.bitrate,
        )
        self.robot = AgxArmFactory.create_arm(cfg)
        self.robot.connect()
        if self.enable_gripper:
            self.gripper = self.robot.init_effector(self.robot.OPTIONS.EFFECTOR.AGX_GRIPPER)
        if auto_enable:
            self.enable()
        if hasattr(self.robot, "set_speed_percent"):
            self.robot.set_speed_percent(self.speed_percent)

    def set_speed_percent(self, speed_percent: int) -> None:
        self.speed_percent = int(speed_percent)
        if self.robot is not None and hasattr(self.robot, "set_speed_percent"):
            self.robot.set_speed_percent(self.speed_percent)

    def _resolve_firmware(self, nero_fw: Any) -> Any:
        normalized = self.firmware.lower()
        if normalized in {"default", "nero_fw.default"}:
            return nero_fw.DEFAULT
        if normalized in {"v111", "1.11", "nero_fw.v111"}:
            return nero_fw.V111
        if normalized in {"v112", "1.12", "nero_fw.v112"}:
            return nero_fw.V112
        raise ValueError(f"unsupported Nero firmware: {self.firmware}")

    def enable(self, timeout_s: float = 20.0) -> None:
        self._require_robot()
        start = time.monotonic()
        last_normal_mode = 0.0
        last_bulk_enable = 0.0
        last_joint_enable = 0.0
        last_status: List[bool] = []
        while True:
            now = time.monotonic()
            if hasattr(self.robot, "set_normal_mode") and now - last_normal_mode >= 1.0:
                self.robot.set_normal_mode()
                last_normal_mode = now

            if now - last_bulk_enable >= 0.2:
                self.robot.enable()
                last_bulk_enable = now

            status = self.get_enable_status()
            if status:
                last_status = status
                if all(status):
                    return

            if status and now - last_joint_enable >= 0.5:
                for joint_index, enabled in enumerate(status, start=1):
                    if not enabled:
                        self.robot.enable(joint_index)
                last_joint_enable = now

            if time.monotonic() - start > timeout_s:
                suffix = f"; last status={last_status}" if last_status else ""
                raise TimeoutError(f"{self.name} did not enable within {timeout_s}s{suffix}")
            time.sleep(0.05)

    def disable(self, timeout_s: float = 5.0) -> None:
        if self.robot is not None and hasattr(self.robot, "disable"):
            if hasattr(self.robot, "set_normal_mode"):
                self.robot.set_normal_mode()
            start = time.monotonic()
            while not self.robot.disable():
                if time.monotonic() - start > timeout_s:
                    raise TimeoutError(f"{self.name} did not disable within {timeout_s}s")
                time.sleep(0.01)

    def disconnect(self) -> None:
        if self.robot is not None and hasattr(self.robot, "disconnect"):
            self.robot.disconnect()

    def is_ok(self) -> bool:
        self._require_robot()
        if hasattr(self.robot, "is_ok"):
            return bool(self.robot.is_ok())
        return not bool(getattr(self.robot, "has_comm_error", lambda: False)())

    def get_enable_status(self) -> List[bool]:
        self._require_robot()
        if hasattr(self.robot, "get_joints_enable_status_list"):
            return [bool(v) for v in self.robot.get_joints_enable_status_list()]
        return []

    def get_joint_positions(self) -> List[float]:
        self._require_robot()
        joints = _as_float_list(self.robot.get_joint_angles())
        if len(joints) != 7:
            raise RuntimeError(f"{self.name} returned {len(joints)} joints, expected 7")
        return joints

    def get_joint_velocities(self) -> List[float]:
        return [0.0] * 7

    def send_joint_positions(self, positions: Iterable[float], command_mode: str | None = None) -> None:
        self._require_robot()
        joints = [float(v) for v in positions]
        if len(joints) != 7:
            raise ValueError(f"Nero command for {self.name} must contain 7 joints")
        mode = command_mode or self.command_mode
        if mode == "move_js":
            if not self.allow_move_js:
                raise RuntimeError("move_js is disabled; set allow_move_js=true only after safety validation")
            self.robot.move_js(joints)
        elif mode == "move_j":
            if self._last_command_mode == "move_js" and hasattr(self.robot, "set_normal_mode"):
                self.robot.set_normal_mode()
            self.robot.move_j(joints)
        else:
            raise ValueError(f"unsupported Nero command mode: {mode}")
        self._last_command_mode = mode

    def send_gripper_width(self, width_m: float) -> None:
        if not self.enable_gripper:
            return
        if self.gripper is None:
            raise RuntimeError(f"{self.name} gripper was not initialized")
        self.gripper.move_gripper_m(float(width_m))

    def emergency_stop(self) -> None:
        if self.robot is not None and hasattr(self.robot, "electronic_emergency_stop"):
            self.robot.electronic_emergency_stop()

    def _require_robot(self) -> None:
        if self.robot is None:
            raise RuntimeError(f"{self.name} is not connected")
