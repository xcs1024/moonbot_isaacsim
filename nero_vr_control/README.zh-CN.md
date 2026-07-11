# xrobot

[英文](README.md) | 中文

面向 AgileX Nero 双臂和 AGX 夹爪的 XR 头显真机遥操作工程。

本项目用于在两台 AgileX Nero 机械臂上部署真实机器人遥操作系统。系统使用
XR-Robotics 头显客户端和 PC Service 获取 XR 输入，使用 AgileX `pyAgxArm`
控制 Nero 真机，并使用官方 Nero URDF 做逆运动学。Meta Quest 3 和 Pico 4 Ultra
都通过同一套遥操作程序运行，用户只需要选择对应头显脚本。

## 当前状态

- Meta Quest 3 遥操作：已验证。
- Pico 4 Ultra 遥操作：已验证。
- 机器人：Nero 双臂 + AGX_GRIPPER 夹爪。
- 默认系统：Ubuntu 22.04。
- 默认 Python：3.10。
- 默认 CAN：左臂 `can0`，右臂 `can1`，bitrate `1000000`。
- Quest 客户端：XR-Robotics 官方 APK，不需要 Unity。
- Pico 客户端：XR-Robotics 官方 APK，不需要 Unity。

## 系统架构

```text
Quest3 / Pico 4 Ultra
        |
        | 手柄位姿、grip、trigger
        v
XRoboToolkit 头显 App
        |
        | 局域网
        v
XRoboToolkit PC Service
        |
        | xrobotoolkit_sdk / Python teleop sample
        v
xrobot_nero 遥操作适配层
        |
        | 官方 Nero URDF + Placo IK
        v
pyAgxArm
        |
        | Linux socketcan
        v
Nero 左臂 + Nero 右臂 + AGX 夹爪
```

关键实现选择：

- Quest 和 Pico 共用同一套机器人控制逻辑，只在 APK profile 和启动脚本上区分。
- 运行时使用 AgileX 官方 Nero URDF，不再使用手写 URDF。
- 程序启动后双臂先移动到 `[0, 45, 0, 45, 0, 0, 0]` 度。
- 按一次 Ctrl-C 后停止遥操作输入，双臂回零，然后程序退出。
- 程序退出时不会主动失能机械臂。
- `hold_enabled` 不允许和真机遥操作同时运行。真机脚本会在遥操作前停止
  `hold_enabled`，仅在正常退出后重新启动。
- 当前现场调优使用低权重关节姿态正则，减少 7 自由度 IK 在中间关节上的异常扭转，
  同时保留较灵敏的腕部姿态跟随。

## 目录结构

```text
xrobot/
  assets/
    apk/                         Quest/Pico 官方 APK 和来源记录
    urdf/                        基于 AgileX 官方 URDF 生成的双 Nero URDF
  configs/
    nero_dual_agx.yml            机器人、安全、CAN、夹爪、头显 profile 配置
  scripts/
    run_teleop_quest.sh          Quest 入口脚本
    run_teleop_pico.sh           Pico 入口脚本
    run_teleop.sh                通用遥操作启动脚本
    run_dataset_capture.sh       VR 遥操作数据采集入口
    setup_can.sh                 激活 can0/can1
    hardware_check.sh            只读关节数据的硬件检查
    status.sh                    环境状态汇总
    download_headset_apk.sh      下载并校验 Quest/Pico APK
    install_headset_apk.sh       通过 adb 安装 Quest/Pico APK
    start_hold_enabled.sh        正常退出后保持机械臂使能
    stop_hold_enabled.sh         停止 hold 进程
  tests/                         配置、运动学、安全逻辑测试
  third_party/                   XR-Robotics 和 AgileX 上游项目
  xrobot_nero/                   Nero 适配层和遥操作运行时代码
```

日常使用主要关注 `scripts/`、`configs/nero_dual_agx.yml` 和 `xrobot_nero/`。
第三方仓库放在 `third_party/`，不要直接修改上游核心逻辑。

## Pico VR LeRobot 数据采集

项目内置 LeRobot v3 直接数据采集链路，用于通过 Pico 4 Ultra VR 遥操作采集真实机器人示教数据。采集入口和普通遥操作入口分离：

- 普通遥操作：`scripts/run_teleop.sh real pico4ultra`，不加载 LeRobot，不写数据集。
- 数据采集：`scripts/run_dataset_capture.sh real pico4ultra`，在遥操作同时直接写 LeRobot v3 数据集。

采集端保存的是可解释、可回放的 **absolute state + absolute action**。训练 pi0.5 时再通过 processor 把 14 个机械臂关节动作转换成 joint-space relative action；左右夹爪始终保持 absolute width command。也就是说，采集阶段不要在 recorder 里做相对动作转换。

默认数据 schema：

```text
observation.state: float32[16]
action:            float32[16]
observation.images.head
observation.images.left_wrist
observation.images.right_wrist
```

16 维向量顺序固定为：

```text
left_joint1..left_joint7, left_arm_gripper_width,
right_joint1..right_joint7, right_arm_gripper_width
```

### Pico 采集复现流程

每次采集前先进入项目根目录：

```bash
cd /home/zxd/xrobot
```

确认 CAN、相机、Pico profile 和依赖可用：

```bash
bash scripts/setup_can.sh can0 can1 1000000
bash scripts/check_can_ready.sh can0 can1
bash scripts/run_teleop.sh check pico4ultra
```

启动 XRoboToolkit PC Service。建议后台启动，避免占用采集终端：

```bash
bash scripts/start_pc_service_background.sh
pgrep -a RoboticsService
```

打开 Pico 4 Ultra 里的 XRoboToolkit App，确保头显和电脑在同一局域网。App 中开启：

- `Controller tracking`
- `Send`

如果 App 需要填写电脑 IP：

```bash
hostname -I
```

启动数据采集：

```bash
bash scripts/run_dataset_capture.sh real pico4ultra \
  --dataset-repo-id local/nero_tube_pick_place \
  --dataset-task "pick up the test tube and place it into the tube rack" \
  2>&1 | tee logs/dataset_capture_$(date +%Y%m%d_%H%M%S).log
```

运行后等待终端出现：

```text
Dataset capture ready. Press X to start/stop an episode; press Y to discard the active episode.
Teleoperation running.
```

### 手柄规则

数据采集控制：

- 左手柄 `X`：开始录制 episode；再次按 `X` 停止并保存当前 episode。
- 左手柄 `Y`：丢弃当前正在录制的 episode。
- 右手柄 `A` 长按 1 秒：两个机械臂缓缓回到程序开始时记录的初始状态。
- `Ctrl-C`：退出程序；如果正在录制，会先保存当前 episode 并 finalize 数据集。

遥操作控制：

- 右手柄 `grip` 控制左臂跟随，右手柄 `trigger` 控制左夹爪。
- 左手柄 `grip` 控制右臂跟随，左手柄 `trigger` 控制右夹爪。
- grip 是 deadman switch，松开后对应机械臂保持当前目标。
- trigger 控制夹爪开合，不依赖 grip。

### 采后检查

采完后立刻检查 LeRobot metadata：

```bash
jq '.total_episodes, .total_frames, .fps' \
  datasets/lerobot/local/nero_tube_pick_place/meta/info.json
```

成功采集时：

- `total_episodes >= 1`
- `total_frames > 0`
- `fps` 为 `10`

检查数据文件：

```bash
find datasets/lerobot/local/nero_tube_pick_place -maxdepth 6 -type f | sort
```

应能看到：

```text
meta/info.json
meta/tasks.parquet
meta/stats.json
meta/episodes/...
data/chunk-000/file-*.parquet
xrobot_nero_metadata.json
```

如果只看到 `meta/info.json` 和 `xrobot_nero_metadata.json`，说明只创建了 schema，没有保存 episode。此时下一次启动 recorder 会自动清理 `0 episode / 0 frame` 的空残留目录并重新创建，不会再因为目录已存在报 `FileExistsError`。

### 示教质量建议

正式数据建议只保留成功、干净、可复现的 episode。对“试管放置到试管槽”任务，推荐：

- 固定试管架、相机和背景，先做固定场景 demo。
- 每条 episode 尽量控制在 15-35 秒。
- 动作流程清晰：接近、抓取、调整姿态、交接、对孔、下放、松夹、撤离。
- 右腕相机在放置阶段尽量同时看到试管和孔位。
- 失败、碰撞、长时间犹豫、明显偏离任务的 episode 用 `Y` 丢弃。
- 试验版数据不要混入正式数据集；可以删除对应 `datasets/lerobot/<repo_id>` 后重新开始。

### 换任务快速复用

这套采集后端不绑定“试管放置”任务。未来采集其他任务时，优先复用同一套入口，只换 `repo_id` 和自然语言任务描述：

```bash
bash scripts/run_dataset_capture.sh real pico4ultra \
  --dataset-repo-id local/<new_task_name> \
  --dataset-task "<describe the new task in one clear sentence>"
```

复用建议：

- 每个任务使用独立 `repo_id`，例如 `local/nero_tube_pick_place`、`local/nero_block_stack`。
- `--dataset-task` 要写成模型未来推理时也会使用的 prompt。
- 只要任务仍使用双 Nero、两个夹爪和三相机，就不需要改 schema。
- 如果未来自研数采软件接入，只需要提供同 schema 的 `state/action/images/task`，即可复用 `create_dataset_recorder(config, capture_config)` 写同一种 LeRobot v3 数据集。
- 普通 VR 遥操作入口保持不变；不启用 `--dataset-capture` 时不会加载 LeRobot。

详细 pi0.5 action 语义和服务器训练流程见 [docs/DATASET_CAPTURE_PI05.md](docs/DATASET_CAPTURE_PI05.md)。

### pi0.5 远端训练快速入口

准备 OpenPI 远端训练工作区：

```bash
bash scripts/bootstrap_pi05_remote.sh
```

采集完成后同步数据、训练并拉回 checkpoint：

```bash
bash scripts/sync_pi05_dataset_to_remote.sh local/nero_tube_pick_place
bash scripts/remote_pi05_train.sh local/nero_tube_pick_place tube_pick_place
bash scripts/fetch_pi05_checkpoint.sh tube_pick_place latest
```

本地直接推理冒烟测试：

```bash
export XROBOT_OPENPI_DIR=/path/to/local/openpi
bash scripts/run_pi05_local_smoke.sh checkpoints/nero_pi05/tube_pick_place/<step>
```

默认远端为 SSH alias `A800`，路径限制为 `/local/zqm/zxd`，所有远端环境、缓存、数据和 checkpoint 都应放在这个目录内。旧的 `/home/zqm/zxd` 训练工作区已废弃。
远端 OpenPI 固定到当前验证过的 commit `c23745b5ad24e98f66967ea795a07b2588ed6c79`，环境使用工作区内的 `uv` + Python 3.11，不依赖系统 conda 环境。

### 电脑重启后的完整采集流程

电脑重启后，从零开始采集一批正式数据时按下面顺序执行：

1. 打开机械臂、夹爪、USB-CAN、RealSense 相机和 Pico 4 Ultra，确认实验台区域安全。
2. 在 Nero Web UI 中确认两台机械臂已使能，并开启 CAN push。
3. 进入项目：

   ```bash
   cd /home/zxd/xrobot
   ```

4. 启动 CAN：

   ```bash
   bash scripts/setup_can.sh can0 can1 1000000
   bash scripts/check_can_ready.sh can0 can1
   ```

5. 启动 XRoboToolkit PC Service：

   ```bash
   bash scripts/start_pc_service_background.sh
   pgrep -a RoboticsService
   ```

6. 检查 Pico profile、三相机和 Python 依赖：

   ```bash
   bash scripts/run_teleop.sh check pico4ultra
   ```

7. 打开 Pico 中的 XRoboToolkit App，填写电脑 IP，开启 `Controller tracking` 和 `Send`。
8. 启动数据采集：

   ```bash
   bash scripts/run_dataset_capture.sh real pico4ultra \
     --dataset-repo-id local/nero_tube_pick_place \
     --dataset-task "pick up the test tube and place it into the tube rack" \
     2>&1 | tee logs/dataset_capture_$(date +%Y%m%d_%H%M%S).log
   ```

9. 等待双臂到达启动初始位，不要在启动运动期间按住 grip。
10. 摆好任务物体，按左手柄 `X` 开始 episode。
11. 完成一次任务后，再按左手柄 `X` 保存；失败则按左手柄 `Y` 丢弃。
12. 采集结束后按 `Ctrl-C` 退出。
13. 检查数据：

    ```bash
    jq '.total_episodes, .total_frames, .fps' \
      datasets/lerobot/local/nero_tube_pick_place/meta/info.json

    find datasets/lerobot/local/nero_tube_pick_place -maxdepth 6 -type f | sort
    ```

14. 只把正式成功 episode 保留在正式数据集中；试验版数据确认无用后可删除对应 `datasets/lerobot/<repo_id>` 目录。

## 硬件要求

- 两台 AgileX Nero 机械臂。
- 两个 AGX_GRIPPER 夹爪。
- 两个 Linux `gs_usb` 支持的 USB-CAN 适配器。
- 建议给 USB-CAN 适配器使用带外部供电的 USB hub。
- 机器人控制电脑运行 Ubuntu 22.04。
- Meta Quest 3 和/或 Pico 4 Ultra。
- 头显和机器人控制电脑必须在同一局域网内，以便连接 XRoboToolkit PC Service。
- Nero Web UI 需要能通过网线访问，用于开启 CAN push 和手动恢复。

真机运行依赖两条通信链路：头显到 PC 的局域网链路，以及 PC 到 Nero 的
USB-CAN 链路。Web 网页控制正常不代表 USB-CAN 链路一定正常。

## 安全要求

真机遥操作前必须确认：

- 双臂周围工作空间已清空。
- 急停按钮可触达。
- 双臂已上电，Web UI 手动控制正常。
- Nero Web UI 中已开启 CAN push。
- `hardware_check` 可以读到两台机械臂的关节数据。
- 程序移动到启动初始位期间，不要按住 grip。
- 新头显、新电脑或新接线首次验证时，只做小幅低风险运动。

默认安全行为：

- grip 是机械臂跟随的 deadman switch。
- trigger 独立控制对应夹爪，不依赖 grip。
- 松开 grip 后，机械臂保持当前目标。
- XR 超时后停止更新命令。
- 每个控制周期都会限制关节命令增量。
- 每个控制周期都会限制夹爪宽度命令增量。
- 启动和退出回零使用 `move_j`。
- 主动遥操作阶段在安全限幅后使用 `move_js`。
- IK 中加入低权重关节姿态正则，避免 7 自由度冗余解导致中间关节异常扭转。

## 当前电脑首次部署

所有命令都从项目根目录执行：

```bash
cd /home/zxd/xrobot
```

安装系统依赖：

```bash
bash scripts/install_system_deps.sh
```

创建虚拟环境并安装基础 Python 依赖：

```bash
bash scripts/bootstrap_python.sh
```

拉取上游依赖并安装最小运行环境：

```bash
bash scripts/setup_third_party.sh
bash scripts/install_runtime_minimal.sh
```

如需要，以 editable 模式安装本项目：

```bash
. .venv/bin/activate
pip install -e .
```

安装 XRoboToolkit PC Service：

```bash
bash scripts/download_pc_service_deb.sh
bash scripts/install_pc_service_deb.sh
```

启动 PC Service：

```bash
bash scripts/run_pc_service.sh
```

如需后台启动：

```bash
bash scripts/start_pc_service_background.sh
```

## 头显 APK 设置

项目默认使用 XR-Robotics 官方 APK：

- Quest3：`XRoboToolkit-Quest-1.0.1.apk`
- Pico 4 Ultra：`XRoboToolkit-PICO-1.1.1.apk`

下载并校验 APK：

```bash
bash scripts/download_headset_apk.sh quest3
bash scripts/download_headset_apk.sh pico4ultra
```

安装 Quest APK：

```bash
bash scripts/install_headset_apk.sh quest3
```

安装 Pico APK：

```bash
bash scripts/install_headset_apk.sh pico4ultra
```

ADB 注意事项：

- 安装 APK 前，需要先在头显中开启开发者模式。
- USB 连接头显后，需要在头显内确认 USB 调试授权。
- 如果同时连接了多个 Android 设备，设置 `ADB_SERIAL=<serial>`。
- USB 只用于 APK 安装和 ADB 维护；实际遥操作通过局域网连接 PC Service。

## Quest 不佩戴时保持唤醒设置

本节只针对 Meta Quest 3。用于启动遥操作后，把头显摘下，只使用两个手柄继续遥操作。

推荐先设置头显自身的自动休眠时间：

1. 戴上 Quest 头显。
2. 打开 `设置`。
3. 进入 `系统` -> `电源`。
4. 将头显自动休眠时间设置为可选的最长时间。
5. 长时间测试时，保持头显电量充足，必要时接入电源。

开发者模式下的保持唤醒方式：

1. 确认 Quest 已通过 ADB 连接：

   ```bash
   adb devices -l
   ```

2. 延长 Android 屏幕超时时间：

   ```bash
   adb shell settings put system screen_off_timeout 14400000
   ```

   `14400000` 表示 4 小时，单位是毫秒。

3. 关闭当前开机周期内的 Quest 接近传感器休眠行为：

   ```bash
   adb shell taskset 0000000F am broadcast -a com.oculus.vrpowermanager.prox_close
   ```

   如果当前头显系统没有 `taskset`，尝试：

   ```bash
   adb shell am broadcast -a com.oculus.vrpowermanager.prox_close
   ```

4. 打开 Quest 头显 App，开启 Controller tracking 和 Send，然后把头显放在稳定位置，
   避免阳光直射镜片。
5. 正常启动 Quest 遥操作：

   ```bash
   bash scripts/run_teleop_quest.sh real
   ```

恢复 Quest 默认休眠行为：

```bash
adb shell am broadcast -a com.oculus.vrpowermanager.automation_disable
adb shell settings delete system screen_off_timeout
```

注意事项：

- 关闭接近传感器休眠的命令可能在头显重启后失效，需要在遥操作前重新执行。
- 不要遮挡镜片，不要让头显镜片受到阳光直射。
- 禁用休眠会增加耗电和发热，长时间遥操作时需要观察头显状态。
- Pico 遥操作不需要执行本节设置。

## CAN 设置

默认映射：

- 左 Nero 机械臂：`can0`
- 右 Nero 机械臂：`can1`
- Bitrate：`1000000`

激活 CAN：

```bash
bash scripts/setup_can.sh can0 can1 1000000
```

检查 CAN 网卡：

```bash
bash scripts/check_can_ready.sh can0 can1
```

检查 USB-CAN 物理端口映射：

```bash
for iface in can0 can1; do
  echo "== $iface =="
  ethtool -i "$iface" | grep bus-info
done
```

如果重启或重插 USB hub 后接口名变化，需要重新检查当前映射，并按需要修改
`configs/nero_dual_agx.yml`。

## Nero Web UI CAN Push

Nero Web UI 通过网线控制机械臂，`pyAgxArm` 通过 Linux `socketcan`
控制机械臂。这两条链路不是同一条链路。使用 USB-CAN 控制前，必须在
Nero Web UI 中开启 CAN push。

开启 CAN push 后，`candump` 应能看到持续 CAN 帧：

```bash
timeout 10s candump can0 can1
```

如果 `candump` 没有输出：

- 确认 Nero Web UI 中已开启 CAN push。
- 确认 CAN-H/CAN-L/GND 接线正确。
- 确认两个 USB-CAN 适配器都有供电。
- 如果适配器接在 hub 上，使用带外部供电的 hub。
- 确认适配器连接到了 Nero 的 CAN 口，而不只是接到了电脑 USB。

## 硬件检查

真机遥操作前，必须先验证机器人侧通信：

```bash
bash scripts/hardware_check.sh --timeout-s 5
```

期望输出：

```text
left_arm: read 7 joints [...]
right_arm: read 7 joints [...]
```

`hardware_check` 只读取关节数据，不会主动移动机械臂。如果检查失败，不要启动
真机遥操作，先修复 CAN push、接线、供电或 CAN 映射。

## 运行遥操作

查看项目状态：

```bash
bash scripts/status.sh
```

检查 Quest profile：

```bash
bash scripts/run_teleop_quest.sh check
```

检查 Pico profile：

```bash
bash scripts/run_teleop_pico.sh check
```

干跑并显示 Placo 可视化：

```bash
bash scripts/run_teleop_quest.sh dry-run
bash scripts/run_teleop_pico.sh dry-run
```

运行 Quest 真机遥操作：

```bash
bash scripts/run_teleop_quest.sh real
```

运行 Pico 真机遥操作：

```bash
bash scripts/run_teleop_pico.sh real
```

头显 App 中必须开启 Controller tracking 和 Send。

如果头显 App 要求填写 PC 地址，使用机器人控制电脑在同一局域网内的 IP：

```bash
hostname -I
```

## 操作流程

1. 给两台 Nero 机械臂上电。
2. 打开 Nero Web UI，确认两台机械臂都能手动控制。
3. 在 Nero Web UI 中开启 CAN push。
4. 如果使用 USB-CAN hub，确认 hub 已外部供电。
5. 激活 CAN：

   ```bash
   bash scripts/setup_can.sh can0 can1 1000000
   ```

6. 验证 CAN 和关节读取：

   ```bash
   timeout 10s candump can0 can1
   bash scripts/hardware_check.sh --timeout-s 5
   ```

7. 启动 XRoboToolkit PC Service：

   ```bash
   bash scripts/run_pc_service.sh
   ```

8. 打开头显 App。
9. 开启 Controller tracking 和 Send。
10. 启动对应遥操作脚本：

   ```bash
   bash scripts/run_teleop_quest.sh real
   # 或
   bash scripts/run_teleop_pico.sh real
   ```

11. 等待双臂到达启动初始位。
12. 按住 grip 后，对应机械臂开始跟随手柄。
13. 使用 trigger 控制对应夹爪。
14. 按一次 Ctrl-C，双臂回零后程序正常退出。

## 当前控制映射

当前映射是根据已验证的 Nero 真机安装和头显输入调试得到的：

- `left_arm` 使用 `right_controller`、`right_grip`、`right_trigger`。
- `right_arm` 使用 `left_controller`、`left_grip`、`left_trigger`。
- 平移符号：`[-1, -1, 1]`。
- 旋转符号：`[-1, -1, 1]`。
- 控制模式：pose，即位置和腕部姿态都参与控制。
- 腕部响应现场调优：`orientation_weight: 0.45`、`rotation_scale: 0.95`。
- 关节姿态正则：`posture_regularization_weight: 0.001`，用于减少 7 自由度 IK
  在肩肘等中间关节上的异常扭转，同时保持腕部跟随。

这些设置由 Quest 和 Pico 共用。除非实测证明某个设备输入约定不同，否则不要按头显
复制或分叉机器人调参。

## 启动、退出和保持使能

启动：

- 双臂移动到 `[0, 45, 0, 45, 0, 0, 0]` 度。
- 启动阶段使用 `move_j`，当前调优为 `speed_percent: 40`、
  `max_delta_rad_per_cycle: 0.022`；A 键回初始位置复用同一组 `startup` 速度参数。
- 启动完成前不要使用 grip 输入。

正常遥操作：

- 主动遥操作阶段使用 `move_js`。
- 命令发送前仍会执行关节增量限幅。
- 真机模式默认关闭日志，以降低 CAN/SDK 负载。

Ctrl-C：

- 按一次 Ctrl-C。
- 遥操作输入停止。
- 双臂回到零位 `[0, 0, 0, 0, 0, 0, 0]`。
- 回零当前调优为 `speed_percent: 40`、`max_delta_rad_per_cycle: 0.022`。
- 程序退出，但不会主动失能机械臂。
- 正常退出后，`hold_enabled` 会启动，用于保持机械臂使能。

如果初始化失败：

- 不会自动启动 `hold_enabled`。
- 必须先修复失败原因。

手动控制 hold：

```bash
bash scripts/start_hold_enabled.sh
bash scripts/stop_hold_enabled.sh
```

仅在安全时手动失能：

```bash
bash scripts/disable_arms.sh
```

## 重要配置

主配置文件：

```text
configs/nero_dual_agx.yml
```

关键字段：

- `robot.control_rate_hz`：遥操作循环频率。
- `robot.teleop_speed_percent`：遥操作时 Nero 速度百分比。
- `robot.teleop_command_mode`：主动遥操作命令模式，当前为 `move_js`。
- `robot.allow_move_js`：对使用 `move_js` 的显式风险确认。
- `gripper.open_width_m`：夹爪完全打开目标，当前为 `0.10`。
- `gripper.max_delta_m_per_cycle`：每个控制周期的夹爪速度限制。
- `startup.*`：启动初始位和 A 键回初始位置速度，当前为 40% 且每周期最大 0.022 rad。
- `shutdown.*`：Ctrl-C 后回零姿态和速度，当前为 40% 且每周期最大 0.022 rad。
- `xr_mapping.*`：头显到机器人方向映射和 pose 权重。
- `xr_mapping.orientation_weight` / `xr_mapping.rotation_scale`：腕部姿态跟随权重
  和响应比例，当前现场调优为 0.45 / 0.95。
- `xr_mapping.posture_regularization_weight`：低权重关节姿态正则，当前为 0.001，
  用于抑制中间关节奇怪扭转。
- `safety.max_joint_delta_rad_per_cycle`：主动遥操作每周期关节增量限幅，当前为
  0.014。调腕部响应时不要优先放宽它。
- `headsets.profiles.quest3`：Quest APK 元数据。
- `headsets.profiles.pico4ultra`：Pico APK 元数据。

## 测试

运行单元测试：

```bash
. .venv/bin/activate
pytest -q tests
```

运行 smoke test：

```bash
bash scripts/smoke_test.sh
```

运行 profile 检查：

```bash
bash scripts/run_teleop_quest.sh check
bash scripts/run_teleop_pico.sh check
```

运行硬件检查：

```bash
bash scripts/hardware_check.sh --timeout-s 5
```

修改代码、迁移电脑或调整配置后，建议至少运行单元测试、smoke test 和对应头显
的 `check`。真机运行前必须再跑 `hardware_check`。

## 故障排查

故障排查按通信链路分层：先看 USB-CAN 和关节读取，再看 PC Service，最后看头显
App、IP、ADB 和 APK。

### `hardware_check` 提示 `SDK returned no data`

这个错误通常不是 Python 依赖问题，而是 PC 没有从 Nero 的 CAN 口收到反馈。

常见原因：

- Nero Web UI 中没有开启 CAN push。
- USB-CAN hub 没有外部供电。
- CAN-H/CAN-L/GND 接线错误或松动。
- `can0/can1` 映射错误。
- USB-CAN 适配器连接到了电脑，但没有接到 Nero CAN 口。

检查：

```bash
timeout 10s candump can0 can1
```

如果 `candump` 为空，先修复 CAN，再运行遥操作。

### `read: Network is down`

CAN 网卡没有处于 up 状态。运行：

```bash
bash scripts/setup_can.sh can0 can1 1000000
```

### `left_arm/right_arm did not enable within 20.0s`

当前封装会在使能时最多等待 20 秒，周期性设置 normal mode、批量使能，并对未使能
关节逐个补发使能。如果仍失败，先运行：

```bash
bash scripts/check_can_ready.sh can0 can1
bash scripts/hardware_check.sh --timeout-s 5
bash scripts/enable_can_push_check.sh --timeout-s 15
```

确认 Web UI 中已开启 CAN push、USB-CAN hub 有外部供电、没有急停或错误状态。
必要时先在 Web UI 手动恢复后再试。关节数据读通前，不要反复启动真机遥操作。

### 头显 App 无法连接 PC Service

检查：

- PC Service 是否运行：

  ```bash
  pgrep -a RoboticsService || bash scripts/run_pc_service.sh
  ```

- 头显和 PC 是否在同一局域网。
- 头显 App 中填写的 PC IP 是否正确：

  ```bash
  hostname -I
  ```

- App 中是否开启 Controller tracking 和 Send。

### APK 安装失败

检查 ADB：

```bash
adb devices -l
```

如果显示 unauthorized，戴上头显确认 USB 调试授权。

如果同时连接多个设备：

```bash
ADB_SERIAL=<serial> bash scripts/install_headset_apk.sh quest3
ADB_SERIAL=<serial> bash scripts/install_headset_apk.sh pico4ultra
```

### 夹爪打开不够大

软件侧当前目标开度为 `0.10m`。如果物理夹爪仍只能开到约 `0.07m`，可能需要在
夹爪本体参数或标定中配置更大行程，不一定是遥操作程序问题。AgileX 示例中出现过
`0.07m` 和 `0.10m` 两种最大行程配置。

## 迁移到另一台电脑

支持两种迁移方式。

### 方式 A：复制整个项目文件夹

推荐方式。复制 `/home/zxd/xrobot` 到新电脑，例如：

```bash
rsync -a /home/zxd/xrobot/ user@new-pc:/home/zxd/xrobot/
```

在新电脑上：

```bash
cd /home/zxd/xrobot
```

重建 Python 环境。不要依赖复制过来的 `.venv`：

```bash
rm -rf .venv
bash scripts/install_system_deps.sh
bash scripts/bootstrap_python.sh
bash scripts/install_runtime_minimal.sh
. .venv/bin/activate
pip install -e .
```

安装 PC Service：

```bash
bash scripts/download_pc_service_deb.sh
bash scripts/install_pc_service_deb.sh
```

如果 APK 文件已随项目复制，会直接复用；否则重新下载：

```bash
bash scripts/download_headset_apk.sh quest3
bash scripts/download_headset_apk.sh pico4ultra
```

如果新电脑或头显环境需要重新安装 APK：

```bash
bash scripts/install_headset_apk.sh quest3
bash scripts/install_headset_apk.sh pico4ultra
```

启动 PC Service：

```bash
bash scripts/run_pc_service.sh
```

配置 CAN：

```bash
bash scripts/setup_can.sh can0 can1 1000000
```

如果新电脑上 USB-CAN 映射不同，检查：

```bash
for iface in can0 can1; do
  echo "== $iface =="
  ethtool -i "$iface" | grep bus-info
done
```

如果左右臂通道变化，修改 `configs/nero_dual_agx.yml`。

在 Nero Web UI 中开启 CAN push，并验证：

```bash
timeout 10s candump can0 can1
bash scripts/hardware_check.sh --timeout-s 5
```

运行需要的头显链路：

```bash
bash scripts/run_teleop_quest.sh real
bash scripts/run_teleop_pico.sh real
```

### 方式 B：全新文件夹或重新克隆

在新电脑上创建 `/home/zxd/xrobot` 并放入项目文件，然后运行：

```bash
cd /home/zxd/xrobot
bash scripts/install_system_deps.sh
bash scripts/bootstrap_python.sh
bash scripts/setup_third_party.sh
bash scripts/install_runtime_minimal.sh
. .venv/bin/activate
pip install -e .
```

安装 PC Service 和 APK：

```bash
bash scripts/download_pc_service_deb.sh
bash scripts/install_pc_service_deb.sh
bash scripts/download_headset_apk.sh quest3
bash scripts/download_headset_apk.sh pico4ultra
```

通过 ADB 安装 APK：

```bash
bash scripts/install_headset_apk.sh quest3
bash scripts/install_headset_apk.sh pico4ultra
```

启动 PC Service：

```bash
bash scripts/run_pc_service.sh
```

激活 CAN 并验证：

```bash
bash scripts/setup_can.sh can0 can1 1000000
timeout 10s candump can0 can1
bash scripts/hardware_check.sh --timeout-s 5
```

运行：

```bash
bash scripts/run_teleop_quest.sh real
# 或
bash scripts/run_teleop_pico.sh real
```

## 迁移注意事项

- 生成的 URDF 使用 `package://agx_arm_description/...` mesh 路径，运行脚本会自动设置
  `ROS_PACKAGE_PATH`。移动项目文件夹后不需要手动修改 mesh 路径。
- 复制过来的 `.venv` 不视为可移植环境，需要在新电脑重建。
- 新电脑上的 USB-CAN 接口名可能变化，遥操作前必须运行 `hardware_check`。
- 迁移后，头显 App 中可能需要填写新电脑 IP。
- PC Service 必须在新电脑上安装，仅复制仓库不够。
- 如果新电脑访问 GitHub 或 PyPI 不稳定，可以从旧电脑复制 `third_party/`、
  `assets/apk/` 和 `assets/deb/`，再使用本地安装脚本。

## 参考资料

- XR-Robotics: https://github.com/XR-Robotics
- XRoboToolkit Quest client: https://github.com/XR-Robotics/XRoboToolkit-Unity-Client-Quest
- XRoboToolkit Pico client: https://github.com/XR-Robotics/XRoboToolkit-Unity-Client
- AgileX Robotics: https://github.com/agilexrobotics
- pyAgxArm: https://github.com/agilexrobotics/pyAgxArm
- Official Nero URDF: https://github.com/agilexrobotics/agx_arm_urdf/tree/main/nero
