import math
import os
from pathlib import Path

import numpy as np
import pytest

placo = pytest.importorskip("placo")
mdh_kinematics = pytest.importorskip("pyAgxArm.utiles.mdh_kinematics")


def _mdh_transform(joints):
    transform = np.eye(4)
    for joint, (d, a, alpha, theta_offset) in zip(joints, mdh_kinematics.get_mdh("nero")):
        theta = joint + theta_offset
        ca, sa = math.cos(alpha), math.sin(alpha)
        ct, st = math.cos(theta), math.sin(theta)
        link = np.array(
            [
                [ct, -st, 0.0, a],
                [ca * st, ca * ct, -sa, -sa * d],
                [sa * st, sa * ct, ca, ca * d],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )
        transform = transform @ link
    return transform


def _set_arm_joints(robot, prefix, joints):
    for index, value in enumerate(joints, start=1):
        robot.state.q[robot.get_joint_offset(f"{prefix}_joint{index}")] = value


def test_official_dual_urdf_matches_pyagxarm_nero_mdh():
    root = Path(__file__).parents[1]
    os.environ["ROS_PACKAGE_PATH"] = f"{root / 'third_party'}:{os.environ.get('ROS_PACKAGE_PATH', '')}"
    robot = placo.RobotWrapper(str(root / "assets" / "urdf" / "dual_nero_official.urdf"))
    solver = placo.KinematicsSolver(robot)
    solver.mask_fbase(True)
    robot.state.q[:7] = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0])

    samples = [
        [0.0] * 7,
        [0.0, math.pi / 4, 0.0, math.pi / 4, 0.0, 0.0, 0.0],
        [0.1, 0.2, -0.3, 0.4, 0.2, -0.1, 0.3],
    ]

    for joints in samples:
        _set_arm_joints(robot, "left", joints)
        robot.update_kinematics()
        urdf_transform = (
            np.linalg.inv(robot.get_T_world_frame("left_base_link"))
            @ robot.get_T_world_frame("left_link7")
        )

        assert np.allclose(urdf_transform, _mdh_transform(joints), atol=1e-6)
