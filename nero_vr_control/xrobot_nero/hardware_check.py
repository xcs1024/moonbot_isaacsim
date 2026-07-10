from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path

from .config import load_config
from .nero_arm import NeroArmInterface


def _print_can_status(channel: str) -> None:
    print(f"{channel}: socketcan status")
    result = subprocess.run(
        ["ip", "-statistics", "-details", "link", "show", channel],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        print(result.stderr.strip() or f"{channel}: ip link query failed")
        return
    include_next = 0
    for line in result.stdout.splitlines():
        if include_next:
            print(f"  {line.strip()}")
            include_next -= 1
            continue
        if "state " in line or "can state" in line:
            print(f"  {line.strip()}")
        elif "RX:" in line or "TX:" in line:
            print(f"  {line.strip()}")
            include_next = 1


def _read_with_timeout(arm: NeroArmInterface, timeout_s: float) -> list[float]:
    deadline = time.monotonic() + timeout_s
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return arm.get_joint_positions()
        except Exception as exc:  # noqa: BLE001 - report the final hardware read error
            last_exc = exc
            time.sleep(0.05)
    if last_exc is not None:
        raise TimeoutError(f"could not read joints within {timeout_s}s: {last_exc}") from last_exc
    raise TimeoutError(f"could not read joints within {timeout_s}s")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read Nero joint states without enabling or commanding motion.")
    parser.add_argument("--config", default="configs/nero_dual_agx.yml")
    parser.add_argument("--timeout-s", type=float, default=5.0)
    args = parser.parse_args()

    config = load_config(Path(args.config))
    ok = True
    for name, arm_config in config.arms.items():
        _print_can_status(arm_config.channel)
        arm = NeroArmInterface(
            name=name,
            channel=arm_config.channel,
            firmware=config.firmware,
            interface=config.interface,
            bitrate=config.bitrate,
            enable_gripper=False,
        )
        print(f"{name}: connecting on {arm_config.channel} without enable...")
        try:
            arm.connect(auto_enable=False)
            joints = _read_with_timeout(arm, args.timeout_s)
            formatted = ", ".join(f"{value:.4f}" for value in joints)
            print(f"{name}: read {len(joints)} joints [{formatted}]")
        except Exception as exc:  # noqa: BLE001 - hardware diagnostics should continue both arms
            ok = False
            print(f"{name}: FAILED {type(exc).__name__}: {exc}")
        finally:
            try:
                arm.disconnect()
            except Exception:
                pass
    if not ok:
        print()
        print("Troubleshooting:")
        print("- Nero web control over Ethernet does not prove that USB-CAN is receiving arm data.")
        print("- In the Nero web UI, enable CAN push before using pyAgxArm over socketcan.")
        print("- Run `candump can0 can1` while CAN push is enabled; normal output should show frames.")
        print("- If candump is still empty, check CAN-H/CAN-L/GND wiring and USB-CAN bus mapping.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
