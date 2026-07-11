# Isaac Sim Real-World Digital Twin

基于 NVIDIA Isaac Sim、Intel RealSense、XRoboToolkit 和 AgileX Nero 机械臂构建的实时数字孪生与 VR 遥操作项目。

项目将真实环境、目标检测结果和机械臂关节状态同步到 Isaac Sim，支持：

- RealSense D435 实时彩色背景和深度遮罩背景。
- RealSense 彩色点云或外部 PCD 点云可视化。
- Pico 4 Ultra / Meta Quest 3 VR 遥操作。
- AgileX Nero 单臂或双臂真机控制。
- 通过 ROS 2 `sensor_msgs/JointState` 将真机关节同步到 Isaac Sim。
- Grounded-SAM-2 检测结果同步到 USD 场景物体。
- Insta360 全景背景接入。
- GLB 衣物模型转换为 Isaac Sim PhysX 柔性布料。

> 当前集成启动脚本主要针对 Pico 4 Ultra、Nero 右臂、`can0` 和 NVIDIA aarch64 环境。  
> 真机操作具有碰撞和设备损坏风险，首次运行必须先完成 CAN、急停和机械臂状态检查。

## 系统架构

```text
RealSense D435 ───────────────┐
                             │ RGB / Depth / Point Cloud
Grounded-SAM-2 ──────────────┤
                             │ detected object pose
Insta360 ────────────────────┤
                             v
                       NVIDIA Isaac Sim
                             ^
                             │ ROS 2 JointState
                             │ topic: isaac_joint_commands
                             │
Pico 4 Ultra / Quest 3       │
        │                    │
        v                    │
XRoboToolkit Headset App     │
        │ LAN                │
        v                    │
XRoboToolkit PC Service      │
        │                    │
        v                    │
xrobot_nero + Placo IK ──────┘
        │
        v
pyAgxArm → SocketCAN → AgileX Nero
```

## 主要功能

### 数字孪生场景

默认主场景为：

```text
assets/sim_world.usd
```

该场景包含 Nero 机械臂、夹爪、桌面和实验物体，并通过 Isaac Sim OmniGraph 接收关节状态。

真机同步默认使用：

```text
Topic: isaac_joint_commands
Type:  sensor_msgs/msg/JointState
Names: joint1..joint7, gripper_joint1, gripper_joint2
Rate:  30 Hz
```

### RealSense 环境融合

项目提供三种主要显示方式：

| 模式 | 脚本 | 用途 |
| --- | --- | --- |
| 深度遮罩纹理 | `scripts/realsense_depth_masked_texture_isaacsim.py` | 保留远景，弱化或隐藏近景 |
| 彩色点云 | `scripts/realsense_colored_pointcloud_isaacsim.py` | 在 Isaac Sim 中显示真实深度几何 |
| 普通 RGB 平面 | `scripts/realsense_isaacsim_live.py` | 将相机画面显示在 USD 平面上 |
| 外部 PCD | `scripts/realtime_pcd_background.py` | 周期性加载外部程序生成的 PCD |

深度遮罩模式同时集成了：

- Isaac Sim ROS 2 Bridge。
- Isaac Sim Timeline 自动播放。
- Insta360 全景脚本。
- Grounded-SAM-2 目标位置同步。

### VR 真机遥操作

`nero_vr_control/` 包含完整的 Nero 遥操作实现，支持：

- Pico 4 Ultra。
- Meta Quest 3。
- 单右臂或双臂 Nero。
- AGX gripper。
- Placo 逆运动学。
- XR 超时保护和关节增量限制。
- LeRobot 数据采集。
- 真机关节到 Isaac Sim 的同步。

当前单右臂映射：

- 右手柄 `grip`：机械臂跟随开关。
- 右手柄 `trigger`：夹爪开合。
- 长按 `A` 1 秒：回到程序启动位置。
- 长按 `B` 0.5 秒：退出遥操作并保持机械臂使能。
- `Ctrl+C`：退出程序。

## 目录结构

```text
isaacsim_realworld/
├── assets/
│   ├── sim_world.usd              # 默认 Isaac Sim 主场景
│   ├── sim_world_clothes.usd      # 布料场景
│   ├── cloth/                     # 衣物 GLB、贴图和柔性 USD
│   ├── chair/                     # 椅子模型
│   ├── milk/                      # 牛奶模型
│   ├── redBull/                   # Red Bull 检测目标模型
│   └── bread_nero_.../            # 面包、桌面和 Nero 组合场景
├── config/
│   └── redbull_detection_offset.json
├── scripts/
│   ├── realsense_depth_masked_texture_isaacsim.py
│   ├── realsense_colored_pointcloud_isaacsim.py
│   ├── realsense_isaacsim_live.py
│   ├── realtime_pcd_background.py
│   └── detection_pose_sync_isaacsim.py
├── tools/
│   ├── glb_cloth_pipeline.py
│   └── glb_cloth_pipeline.md
└── nero_vr_control/
    ├── configs/                    # 机械臂、CAN、XR 和安全参数
    ├── scripts/                    # 安装、检查和启动脚本
    ├── tests/                      # 单元测试
    ├── third_party/                # XRoboToolkit、pyAgxArm、官方 URDF
    └── xrobot_nero/                # 遥操作、IK、安全和数据采集实现
```

## 环境要求

### 推荐部署平台

当前集成环境：

- NVIDIA DGX Spark 或支持 Isaac Sim 的 NVIDIA RTX Linux 主机。
- Isaac Sim 6.0.1。
- Python 3.12。
- Linux aarch64 或 x86_64。
- Isaac Sim 内置 ROS 2 Jazzy，代码也兼容 Humble。
- Intel RealSense D435。
- Pico 4 Ultra 或 Meta Quest 3。
- AgileX Nero 机械臂。
- Linux SocketCAN USB-CAN 适配器。

Isaac Sim 6.0 在 aarch64 上官方支持 NVIDIA DGX Spark 和 DGX OS 7。其他平台要求和显卡驱动版本请以 [NVIDIA Isaac Sim Requirements](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/installation/requirements.html) 为准。

### 路径约定

现有脚本的默认部署路径为：

```text
项目目录:       /home/nvidia/isaacsim_realworld
Conda 环境:     /home/nvidia/miniconda3/envs/env_isaacsim
XR SDK:         /home/nvidia/xrobotoolkit_sdk
PC Service:     /opt/apps/roboticsservice
Grounded-SAM-2: /home/nvidia/Grounded-SAM-2
Insta360:       /home/nvidia/insta360_live_panorama
DAP PCD:        /home/nvidia/DAP/data/point/latest.pcd
```

如果实际路径不同，应优先通过命令行参数或环境变量覆盖：

```bash
export PYTHON="$CONDA_PREFIX/bin/python"
export XRSDK_ROOT=/path/to/xrobotoolkit_sdk
export SERVICE_DIR=/path/to/roboticsservice
```

Isaac Sim 脚本支持通过 `--world`、`--detection-position-json`、
`--detection-offset-file` 和 `--insta360-panorama-script` 指定自定义路径。

## 安装环境

### 1. 创建 Isaac Sim Python 环境

Isaac Sim 6.0.1 要求 Python 3.12。推荐使用独立 Conda 环境：

```bash
conda create -n env_isaacsim python=3.12 -y
conda activate env_isaacsim

python -m pip install --upgrade pip setuptools wheel
python -m pip install "isaacsim[all,extscache]==6.0.1.0" \
  --extra-index-url https://pypi.nvidia.com
```

完整安装说明参见 [NVIDIA Isaac Sim Python Environment Installation](https://docs.isaacsim.omniverse.nvidia.com/6.0.1/installation/install_python.html)。

验证安装：

```bash
python -c "from isaacsim import SimulationApp; print('Isaac Sim import OK')"
isaacsim isaacsim.exp.compatibility_check
```

### 2. 安装 RealSense 和图像依赖

```bash
conda activate env_isaacsim

python -m pip install numpy opencv-python
python -m pip install pyrealsense2
```

如果 aarch64 平台没有匹配的 `pyrealsense2` wheel，需要安装或编译 Intel
librealsense Python binding。

验证相机：

```bash
python - <<'PY'
import pyrealsense2 as rs

ctx = rs.context()
devices = list(ctx.query_devices())
print(f"RealSense devices: {len(devices)}")
for device in devices:
    print(device.get_info(rs.camera_info.name))
PY
```

使用 V4L2 模式前检查视频节点：

```bash
v4l2-ctl --list-devices
```

默认 RGB 脚本使用 `/dev/video4`，如果设备节点不同：

```bash
python scripts/realsense_isaacsim_live.py \
  --video-device /dev/videoX \
  --world "$PWD/assets/sim_world.usd"
```

### 3. 安装 Nero 遥操作依赖

集成运行需要遥操作代码和 Isaac Sim ROS 2 库处于同一个
`env_isaacsim` 环境中。

```bash
conda activate env_isaacsim
cd /home/nvidia/isaacsim_realworld/nero_vr_control

python -m pip install -r requirements.txt
python -m pip install -e third_party/pyAgxArm
python -m pip install \
  meshcat \
  placo \
  opencv-python-headless \
  tyro \
  pybind11

python -m pip install \
  -e third_party/XRoboToolkit-Teleop-Sample-Python \
  --no-deps \
  --no-build-isolation

python -m pip install \
  -e third_party/XRoboToolkit-PC-Service-Pybind \
  --no-build-isolation

python -m pip install -e . --no-build-isolation
```

验证 Python 依赖：

```bash
python - <<'PY'
import cv2
import placo
import pyAgxArm
import xrobot_nero
import xrobotoolkit_sdk
import xrobotoolkit_teleop

print("Nero teleoperation imports OK")
PY
```

> `nero_vr_control/scripts/bootstrap_python.sh` 面向 Ubuntu 22.04/Python 3.10
> 独立部署，会创建 `.venv`。一体化 Isaac Sim 同步应使用上面的 Python 3.12
> Conda 环境。
>
> DGX OS 7 上不要直接执行 `install_system_deps.sh`。该脚本会添加 Ubuntu
> Jammy 软件源，主要用于项目原始的 Ubuntu 22.04 控制电脑。

### 4. 安装 XRoboToolkit PC Service

根据主机架构选择安装包：

```text
aarch64:
XRoboToolkit-PC-Service-headless_1.0.0.0_arm64.deb

x86_64 / Ubuntu 22.04:
nero_vr_control/assets/deb/XRoboToolkit_PC_Service_1.0.0_ubuntu_22.04_amd64.deb
```

aarch64 示例：

```bash
sudo apt install ./XRoboToolkit-PC-Service-headless_1.0.0.0_arm64.deb
```

安装后确认：

```bash
test -f /opt/apps/roboticsservice/runService.sh
bash /opt/apps/roboticsservice/runService.sh
```

Pico 或 Quest 必须与运行 PC Service 的主机处于同一局域网。

### 5. 安装头显 App

项目已包含 Pico 和 Quest APK：

```text
nero_vr_control/assets/apk/pico4ultra/XRoboToolkit-PICO-1.1.1.apk
nero_vr_control/assets/apk/quest3/XRoboToolkit-Quest-1.0.1.apk
```

开启头显开发者模式和 USB 调试后执行：

```bash
cd nero_vr_control

bash scripts/install_headset_apk.sh pico4ultra
# 或
bash scripts/install_headset_apk.sh quest3
```

在头显 App 中填写控制电脑 IP，并开启：

- `Controller tracking`
- `Send`

查看电脑 IP：

```bash
hostname -I
```

## CAN 配置

当前单右臂配置：

```text
接口:    can0
Bitrate: 1000000
配置:    nero_vr_control/configs/nero_single_right_controller.yml
```

激活 CAN：

```bash
sudo ip link set can0 down 2>/dev/null || true
sudo ip link set can0 up type can bitrate 1000000
```

检查状态：

```bash
ip -details link show can0
candump can0
```

真机运行前还必须在 Nero Web UI 中：

1. 确认机械臂已使能。
2. 确认没有急停或错误状态。
3. 开启 CAN push。
4. 确认 `candump can0` 能持续收到数据。

只读硬件检查：

```bash
cd nero_vr_control
bash scripts/hardware_check.sh --timeout-s 5
```

如果无法读取 7 个关节，不要启动真机遥操作。

## 快速启动

### 仅启动 Isaac Sim 和 RealSense

该模式不依赖 Insta360 和 Grounded-SAM-2：

```bash
cd /home/nvidia/isaacsim_realworld
conda activate env_isaacsim

python scripts/realsense_depth_masked_texture_isaacsim.py \
  --world "$PWD/assets/sim_world.usd" \
  --min-distance 3.0 \
  --near-mode dim \
  --near-dim 0.12 \
  --update-interval 0.10 \
  --no-enable-insta360-panorama \
  --no-enable-detection-object-sync
```

无界面运行：

```bash
python scripts/realsense_depth_masked_texture_isaacsim.py \
  --world "$PWD/assets/sim_world.usd" \
  --headless \
  --no-enable-insta360-panorama \
  --no-enable-detection-object-sync
```

### 启动完整数字孪生

完整模式要求以下外部文件存在：

```text
/home/nvidia/insta360_live_panorama/isaacsim_live_panorama.py
/home/nvidia/Grounded-SAM-2/outputs/realtime_grounded_sam2/latest_positions.json
```

终端 1：

```bash
cd /home/nvidia/isaacsim_realworld
conda activate env_isaacsim

python scripts/realsense_depth_masked_texture_isaacsim.py \
  --world "$PWD/assets/sim_world.usd" \
  --min-distance 3.0 \
  --near-mode dim \
  --near-dim 0.12 \
  --update-interval 0.10
```

终端 2：

```bash
cd /home/nvidia/isaacsim_realworld/nero_vr_control
conda activate env_isaacsim

PYTHON="$CONDA_PREFIX/bin/python" \
XRSDK_ROOT=/home/nvidia/xrobotoolkit_sdk \
./scripts/start_single_right_teleop_isaac_sync.sh
```

第二个脚本会：

1. 启动 XRoboToolkit PC Service。
2. 激活 `can0@1000000`。
3. 启动 Pico 右手柄到 Nero 右臂的遥操作。
4. 向 `isaac_joint_commands` 发布真机关节和夹爪状态。
5. 将日志写入 `logs/teleop_single_right_isaac_sync.log`。

### 仅运行 VR 真机遥操作

不需要 Isaac Sim 同步时：

```bash
cd /home/nvidia/isaacsim_realworld/nero_vr_control
conda activate env_isaacsim

PYTHON="$CONDA_PREFIX/bin/python" \
XRSDK_ROOT=/home/nvidia/xrobotoolkit_sdk \
./scripts/start_single_right_teleop.sh
```

## 其他运行模式

### RealSense 彩色点云

```bash
python scripts/realsense_colored_pointcloud_isaacsim.py \
  --world "$PWD/assets/sim_world.usd" \
  --min-distance 0.3 \
  --max-distance 5.0 \
  --max-points 60000
```

### RealSense 普通 RGB 背景

```bash
python scripts/realsense_isaacsim_live.py \
  --world "$PWD/assets/sim_world.usd" \
  --video-device /dev/video4
```

### 外部 PCD 背景

```bash
python scripts/realtime_pcd_background.py \
  --world "$PWD/assets/sim_world.usd" \
  --pcd /home/nvidia/DAP/data/point/latest.pcd \
  --refresh 5 \
  --render-mode instancer
```

### 仅同步检测目标

Grounded-SAM-2 在独立进程中持续更新 JSON，本脚本负责更新 Isaac Sim Prim：

```bash
python scripts/detection_pose_sync_isaacsim.py \
  --world "$PWD/assets/sim_world.usd" \
  --detection-position-json \
    /home/nvidia/Grounded-SAM-2/outputs/realtime_grounded_sam2/latest_positions.json \
  --detection-object-prim /World/redBull
```

目标坐标转换规则：

```text
Isaac position = detected_position * scale + offset
```

热更新配置：

```text
config/redbull_detection_offset.json
```

### 生成柔性布料 USD

安装可选依赖：

```bash
conda activate env_isaacsim
python -m pip install trimesh fast-simplification pillow numpy
```

执行：

```bash
python tools/glb_cloth_pipeline.py \
  --input "$PWD/assets/cloth/base_basic_pbr.glb" \
  --output "$PWD/assets/cloth/clothes_cloth.usd" \
  --sim-mode grid \
  --grid-x 33 \
  --grid-y 45 \
  --solver-iterations 3
```

详细参数参见 `tools/glb_cloth_pipeline.md`。

## 配置文件

### 目标检测偏移

`config/redbull_detection_offset.json`：

```json
{
  "offset": [0.0, 0.0, 0.0],
  "scale": [1.0, 1.0, 1.0],
  "formula": "target = detected_position * scale + offset"
}
```

文件会在程序运行期间热加载，可用于标定检测坐标系和 Isaac Sim 世界坐标系。

### 单右臂遥操作

主要配置：

```text
nero_vr_control/configs/nero_single_right_controller.yml
```

关键字段：

- `arms.right_arm.channel`：SocketCAN 接口，当前为 `can0`。
- `robot.control_rate_hz`：遥操作控制频率。
- `robot.teleop_speed_percent`：真机速度百分比。
- `safety.xr_timeout_s`：XR 数据超时阈值。
- `safety.max_joint_delta_rad_per_cycle`：每周期最大关节变化。
- `xr_mapping.*`：XR 到机械臂的位置和姿态映射。
- `startup.*`：启动动作配置。
- `shutdown.*`：退出动作配置。
- `gripper.*`：夹爪开度和速度限制。

调整配置前应先使用小范围动作验证，禁止直接提高速度或取消关节限幅。

## 测试

运行 Nero 模块单元测试：

```bash
cd nero_vr_control
conda activate env_isaacsim
pytest -q tests
```

运行 smoke test：

```bash
bash scripts/smoke_test.sh
```

运行头显和依赖检查：

```bash
bash scripts/run_teleop.sh check pico4ultra
```

测试 Isaac Sim 脚本参数：

```bash
python scripts/realsense_depth_masked_texture_isaacsim.py --help
python scripts/realsense_colored_pointcloud_isaacsim.py --help
python scripts/detection_pose_sync_isaacsim.py --help
```

## 安全要求

真机遥操作前必须确认：

- 机械臂周围没有人员和障碍物。
- 急停按钮随时可触达。
- 机械臂、夹爪和 USB-CAN 供电正常。
- Nero Web UI 控制正常。
- CAN push 已开启。
- `candump` 能收到连续数据。
- `hardware_check` 能读取全部关节。
- 启动阶段不要按住 `grip`。
- 首次运行只进行低速、小范围动作。

安全行为：

- `grip` 是机械臂跟随的 deadman switch。
- 松开 `grip` 后保持当前目标。
- XR 数据超时后停止更新运动命令。
- 每周期关节和夹爪变化均有限幅。
- 当前单右臂配置默认不在退出时失能机械臂。

## 常见问题

### `Isaac Sim ROS2 libraries were not found`

确认遥操作和 Isaac Sim 使用同一个 Python 环境：

```bash
conda activate env_isaacsim
echo "$CONDA_PREFIX"
python -c "import sys; print(sys.executable)"
```

检查 ROS 2 库：

```bash
find "$CONDA_PREFIX/lib" \
  -path '*isaacsim.ros2.core*/rclpy' \
  -type d
```

### `Cannot open RealSense video device`

```bash
v4l2-ctl --list-devices
ls -l /dev/video*
```

然后通过 `--video-device` 指定正确节点。

### `SDK returned no data`

通常是 CAN 链路问题，不是 Python 问题。检查：

```bash
ip -details link show can0
candump can0
```

同时确认：

- Nero Web UI 已开启 CAN push。
- CAN-H、CAN-L 和 GND 接线正确。
- USB-CAN 适配器正常供电。
- 配置文件中的 CAN 接口映射正确。

### 头显无法连接 PC Service

```bash
pgrep -af RoboticsService
hostname -I
```

确认头显和控制电脑位于同一局域网，并在 App 中开启
`Controller tracking` 和 `Send`。

### Isaac Sim 中机械臂不运动

检查：

1. Isaac Sim Timeline 是否处于播放状态。
2. ROS 2 Bridge 是否已启用。
3. Topic 名是否为 `isaac_joint_commands`。
4. 关节名是否与 USD OmniGraph 配置一致。
5. 遥操作日志中是否出现 `Isaac Sim joint sync enabled`。
6. `RMW_IMPLEMENTATION` 是否一致，默认使用 `rmw_fastrtps_cpp`。

## 子模块文档

Nero 双臂部署、头显 APK、数据采集、pi0.5 训练和完整故障排查参见：

```text
nero_vr_control/README.zh-CN.md
```

## 当前限制

- 多个脚本包含 `/home/nvidia/...` 默认路径，迁移机器时需要覆盖参数。
- Insta360、Grounded-SAM-2 和 DAP 不包含在本仓库中。
- `assets/sim_world.usd` 较大，加载和首轮着色器编译需要时间。
- 当前单臂 Isaac 同步链路主要针对 Pico 4 Ultra 和右臂验证。
- Isaac Sim 环境与原始 Ubuntu 22.04 双臂遥操作环境的 Python 版本不同。
- 真机功能只能在 Linux 上运行，Windows 适合代码阅读，不能直接使用 SocketCAN。