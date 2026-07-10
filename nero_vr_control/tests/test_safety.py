import pytest

from xrobot_nero.safety import (
    StepLimiter,
    apply_translation_sign,
    apply_vector_deadband,
    is_deadman_active,
    trigger_to_width,
)


def test_trigger_to_width_maps_open_to_close():
    assert trigger_to_width(0.0, 0.07, 0.0) == 0.07
    assert trigger_to_width(1.0, 0.07, 0.0) == 0.0
    assert trigger_to_width(0.5, 0.08, 0.0) == 0.04


def test_deadman_threshold_accepts_bool_and_float():
    assert is_deadman_active(True, 0.5)
    assert not is_deadman_active(False, 0.5)
    assert is_deadman_active(0.6, 0.5)
    assert not is_deadman_active(0.4, 0.5)


def test_step_limiter_limits_each_cycle():
    limiter = StepLimiter(0.1)
    limiter.reset([0.0, 1.0])
    assert limiter.limit([1.0, 0.0]) == [0.1, 0.9]
    assert limiter.limit([1.0, 0.0]) == [0.2, 0.8]


def test_apply_translation_sign_flips_front_back_and_left_right():
    assert apply_translation_sign([1.0, -2.0, 3.0], [-1.0, -1.0, 1.0]) == [-1.0, 2.0, 3.0]
    with pytest.raises(ValueError):
        apply_translation_sign([1.0, 2.0], [-1.0, -1.0, 1.0])


def test_apply_vector_deadband_zeros_small_motion():
    assert apply_vector_deadband([0.001, 0.001, 0.0], 0.004) == [0.0, 0.0, 0.0]
    assert apply_vector_deadband([0.004, 0.0, 0.0], 0.004) == [0.004, 0.0, 0.0]
