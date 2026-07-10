from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .nero_arm import NeroArmInterface


def main() -> int:
    parser = argparse.ArgumentParser(description="Read Nero joint enable status without changing it.")
    parser.add_argument("--config", default="configs/nero_dual_agx.yml")
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
        )
        try:
            arm.connect(auto_enable=False)
            statuses = arm.get_enable_status()
            print(f"{name}: enable_status={statuses}")
            if any(statuses):
                ok = False
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"{name}: FAILED {type(exc).__name__}: {exc}")
        finally:
            try:
                arm.disconnect()
            except Exception:
                pass
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
