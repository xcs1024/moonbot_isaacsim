from __future__ import annotations

import argparse
import time
from pathlib import Path

from .config import load_config
from .nero_arm import NeroArmInterface


def _wait_for_joint_state(arm: NeroArmInterface, timeout_s: float) -> list[float]:
    deadline = time.monotonic() + timeout_s
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return arm.get_joint_positions()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(0.05)
    if last_exc is not None:
        raise TimeoutError(f"joint state unavailable after enable: {last_exc}") from last_exc
    raise TimeoutError("joint state unavailable after enable")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enable Nero normal CAN push, read joint state, then disable. No move command is sent."
    )
    parser.add_argument("--config", default="configs/nero_dual_agx.yml")
    parser.add_argument("--timeout-s", type=float, default=8.0)
    args = parser.parse_args()

    config = load_config(Path(args.config))
    ok = True
    for name, arm_config in config.arms.items():
        arm = NeroArmInterface(
            name=name,
            channel=arm_config.channel,
            firmware=config.firmware,
            interface=config.interface,
            bitrate=config.bitrate,
            enable_gripper=False,
            speed_percent=10,
        )
        print(f"{name}: connecting on {arm_config.channel}...")
        try:
            arm.connect(auto_enable=False)
            if hasattr(arm.robot, "set_normal_mode"):
                print(f"{name}: set_normal_mode()")
                arm.robot.set_normal_mode()
            print(f"{name}: enable()")
            arm.enable(timeout_s=args.timeout_s)
            joints = _wait_for_joint_state(arm, args.timeout_s)
            formatted = ", ".join(f"{value:.4f}" for value in joints)
            print(f"{name}: read {len(joints)} joints [{formatted}]")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"{name}: FAILED {type(exc).__name__}: {exc}")
        finally:
            try:
                arm.disable()
            except Exception:
                pass
            try:
                arm.disconnect()
            except Exception:
                pass
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
