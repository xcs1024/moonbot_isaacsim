from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def trigger_to_width(trigger_value: float, open_width_m: float, close_width_m: float) -> float:
    trigger = clamp(float(trigger_value), 0.0, 1.0)
    return open_width_m + (close_width_m - open_width_m) * trigger


def is_deadman_active(value: float | bool, threshold: float) -> bool:
    if isinstance(value, bool):
        return value
    return float(value) >= threshold


def apply_translation_sign(delta: Iterable[float], sign: Iterable[float]) -> List[float]:
    delta_list = [float(value) for value in delta]
    sign_list = [float(value) for value in sign]
    if len(delta_list) != 3 or len(sign_list) != 3:
        raise ValueError("delta and sign must both contain exactly 3 values")
    return [value * sign_value for value, sign_value in zip(delta_list, sign_list)]


def apply_vector_deadband(values: Iterable[float], threshold: float) -> List[float]:
    value_list = [float(value) for value in values]
    if sum(value * value for value in value_list) ** 0.5 < float(threshold):
        return [0.0 for _ in value_list]
    return value_list


@dataclass
class StepLimiter:
    max_delta: float
    _last: List[float] | None = field(default=None, init=False)

    def reset(self, values: Iterable[float] | None = None) -> None:
        self._last = list(values) if values is not None else None

    def limit(self, target: Iterable[float]) -> List[float]:
        target_list = [float(v) for v in target]
        if self._last is None:
            self._last = target_list
            return target_list
        if len(target_list) != len(self._last):
            raise ValueError(f"target length changed from {len(self._last)} to {len(target_list)}")

        limited: List[float] = []
        for previous, desired in zip(self._last, target_list):
            delta = clamp(desired - previous, -self.max_delta, self.max_delta)
            limited.append(previous + delta)
        self._last = limited
        return limited
