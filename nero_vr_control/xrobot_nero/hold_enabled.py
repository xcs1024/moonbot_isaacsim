from __future__ import annotations

import argparse
import signal
import time
from pathlib import Path

from .config import load_config
from .nero_arm import NeroArmInterface


_STOP = False


def _request_stop(_signum, _frame) -> None:
    global _STOP
    _STOP = True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Keep both Nero arms connected and enabled without sending motion commands."
    )
    parser.add_argument("--config", default="configs/nero_dual_agx.yml")
    parser.add_argument("--period-s", type=float, default=1.0)
    parser.add_argument("--disable-on-exit", action="store_true")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    config = load_config(Path(args.config))
    arms: list[NeroArmInterface] = []
    try:
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
            print(f"{name}: connecting on {arm_config.channel} and enabling hold...")
            arm.connect(auto_enable=True)
            print(f"{name}: enable_status={arm.get_enable_status()}")
            arms.append(arm)

        print("Nero hold process running. Stop with scripts/stop_hold_enabled.sh.")
        next_report = 0.0
        while not _STOP:
            report = time.monotonic() >= next_report
            for arm in arms:
                status = arm.get_enable_status()
                if report:
                    print(f"{arm.name}: enable_status={status}", flush=True)
                if not all(status):
                    arm.enable()
            if report:
                next_report = time.monotonic() + 5.0
            time.sleep(args.period_s)
    finally:
        for arm in arms:
            try:
                if args.disable_on_exit:
                    arm.disable()
                arm.disconnect()
            except Exception as exc:  # noqa: BLE001
                print(f"{arm.name}: hold shutdown failed: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
