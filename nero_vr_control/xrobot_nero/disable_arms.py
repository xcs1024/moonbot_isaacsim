from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .nero_arm import NeroArmInterface


def main() -> int:
    parser = argparse.ArgumentParser(description="Explicitly disable both Nero arms.")
    parser.add_argument("--config", default="configs/nero_dual_agx.yml")
    parser.add_argument("--timeout-s", type=float, default=5.0)
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
            print(f"{name}: connecting on {arm_config.channel}...")
            arm.connect(auto_enable=False)
            print(f"{name}: disable()")
            arm.disable(timeout_s=args.timeout_s)
            print(f"{name}: enable_status={arm.get_enable_status()}")
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
