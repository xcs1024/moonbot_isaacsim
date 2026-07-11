# xrobot

English | [Chinese](README.zh-CN.md)

XR headset teleoperation for AgileX Nero dual arms with AGX grippers.

This project deploys a real-robot teleoperation system for two AgileX Nero arms.
It uses XR-Robotics headset clients and PC Service for XR input, AgileX
`pyAgxArm` for Nero hardware control, and the official Nero URDF for inverse
kinematics. Meta Quest 3 and Pico 4 Ultra are both supported through the same
teleoperation program; the operator only chooses a headset-specific script.

## Status

- Meta Quest 3 teleoperation: verified.
- Pico 4 Ultra teleoperation: verified.
- Robot: dual Nero arms with AGX_GRIPPER grippers.
- Default OS: Ubuntu 22.04.
- Default Python: 3.10.
- Default CAN: left arm `can0`, right arm `can1`, bitrate `1000000`.
- Quest client: official XR-Robotics APK, no Unity required.
- Pico client: official XR-Robotics APK, no Unity required.

## Architecture

```text
Quest3 / Pico 4 Ultra
        |
        | XR controller pose, grip, trigger
        v
XRoboToolkit headset app
        |
        | LAN
        v
XRoboToolkit PC Service
        |
        | xrobotoolkit_sdk / Python teleop sample
        v
xrobot_nero teleop adapter
        |
        | official Nero URDF + Placo IK
        v
pyAgxArm
        |
        | Linux socketcan
        v
Nero left arm + Nero right arm + AGX grippers
```

Important implementation choices:

- Robot control is common for both headsets. Quest and Pico only differ in APK
  profile and launch script.
- Runtime control uses the official AgileX Nero URDF, not a handwritten URDF.
- Startup moves both arms to `[0, 45, 0, 45, 0, 0, 0]` degrees.
- Ctrl-C stops teleoperation, returns both arms to zero, then exits.
- The program does not intentionally disable the arms on exit.
- `hold_enabled` is not allowed to run concurrently with teleop. The real
  teleop script stops `hold_enabled` before teleop and restarts it only after a
  normal teleop exit.
- Current field tuning uses low-weight joint posture regularization to reduce
  odd intermediate-joint twists in the 7-DoF IK solution while keeping wrist
  orientation responsive.

## Repository Layout

```text
xrobot/
  assets/
    apk/                         Official Quest/Pico APKs and source records
    urdf/                        Generated dual Nero URDF from AgileX official URDF
  configs/
    nero_dual_agx.yml            Robot, safety, CAN, gripper, headset profiles
  scripts/
    run_teleop_quest.sh          Quest entrypoint
    run_teleop_pico.sh           Pico entrypoint
    run_teleop.sh                Shared teleop runner
    run_dataset_capture.sh       VR teleoperation dataset capture entrypoint
    setup_can.sh                 Bring up can0/can1
    hardware_check.sh            Read Nero joints without motion
    status.sh                    Environment status summary
    download_headset_apk.sh      Download and verify Quest/Pico APK
    install_headset_apk.sh       Install Quest/Pico APK through adb
    start_hold_enabled.sh        Keep Nero arms enabled after normal exit
    stop_hold_enabled.sh         Stop hold process
  tests/                         Focused config, kinematics, safety tests
  third_party/                   XR-Robotics and AgileX upstream projects
  xrobot_nero/                   Nero adapter and teleoperation runtime
```

Daily operation mainly uses `scripts/`, `configs/nero_dual_agx.yml`, and
`xrobot_nero/`. Upstream dependencies live under `third_party/`; avoid editing
upstream code directly.

## Pico VR LeRobot Dataset Capture

This project includes a direct LeRobot v3 recorder for real-robot
demonstration collection with Pico 4 Ultra VR teleoperation. Dataset capture is
separate from ordinary teleoperation:

- Ordinary teleoperation: `scripts/run_teleop.sh real pico4ultra`, which does
  not import LeRobot and does not write a dataset.
- Dataset capture: `scripts/run_dataset_capture.sh real pico4ultra`, which
  teleoperates the robot and writes a LeRobot v3 dataset online.

The capture side stores interpretable **absolute state + absolute action**.
For pi0.5 training, a processor later converts the 14 arm joint action
dimensions into joint-space relative actions. The two gripper dimensions stay
absolute width commands. Do not convert actions to relative commands inside the
recorder.

Default dataset schema:

```text
observation.state: float32[16]
action:            float32[16]
observation.images.head
observation.images.left_wrist
observation.images.right_wrist
```

The 16-dimensional vector order is fixed:

```text
left_joint1..left_joint7, left_arm_gripper_width,
right_joint1..right_joint7, right_arm_gripper_width
```

### Pico Capture Reproduction

Start from the project root:

```bash
cd /home/zxd/xrobot
```

Check CAN, cameras, the Pico profile, and runtime imports:

```bash
bash scripts/setup_can.sh can0 can1 1000000
bash scripts/check_can_ready.sh can0 can1
bash scripts/run_teleop.sh check pico4ultra
```

Start XRoboToolkit PC Service. Background startup is recommended so the capture
terminal remains available:

```bash
bash scripts/start_pc_service_background.sh
pgrep -a RoboticsService
```

Open the XRoboToolkit app on Pico 4 Ultra. The headset and robot PC must be on
the same LAN. Enable:

- `Controller tracking`
- `Send`

If the app asks for the PC IP:

```bash
hostname -I
```

Start capture:

```bash
bash scripts/run_dataset_capture.sh real pico4ultra \
  --dataset-repo-id local/nero_tube_pick_place \
  --dataset-task "pick up the test tube and place it into the tube rack" \
  2>&1 | tee logs/dataset_capture_$(date +%Y%m%d_%H%M%S).log
```

Wait for:

```text
Dataset capture ready. Press X to start/stop an episode; press Y to discard the active episode.
Teleoperation running.
```

### Controller Rules

Dataset capture buttons:

- Left controller `X`: start recording an episode; press `X` again to stop and
  save it.
- Left controller `Y`: discard the active episode.
- Hold right controller `A` for 1 second: slowly move both arms back to the
  program-start state.
- `Ctrl-C`: exit; if an episode is active, it is saved before dataset
  finalization.

Teleoperation controls:

- Right controller `grip` drives the left arm; right controller `trigger`
  drives the left gripper.
- Left controller `grip` drives the right arm; left controller `trigger`
  drives the right gripper.
- Grip is the deadman switch. Releasing grip holds the matching arm target.
- Trigger controls gripper width independently of grip.

### After-Capture Checks

Check LeRobot metadata immediately after collection:

```bash
jq '.total_episodes, .total_frames, .fps' \
  datasets/lerobot/local/nero_tube_pick_place/meta/info.json
```

A successful collection should show:

- `total_episodes >= 1`
- `total_frames > 0`
- `fps` equal to `10`

Check data files:

```bash
find datasets/lerobot/local/nero_tube_pick_place -maxdepth 6 -type f | sort
```

Expected files include:

```text
meta/info.json
meta/tasks.parquet
meta/stats.json
meta/episodes/...
data/chunk-000/file-*.parquet
xrobot_nero_metadata.json
```

If the directory only contains `meta/info.json` and
`xrobot_nero_metadata.json`, only the schema was created and no episode was
saved. On the next recorder startup, a `0 episode / 0 frame` empty residue is
reset automatically, so it should not raise `FileExistsError`.

### Demonstration Quality

Keep only successful, clean, reproducible episodes for formal training. For the
test-tube placement task:

- Keep the rack, cameras, and background fixed for the first fixed-scene demo.
- Aim for 15-35 seconds per episode.
- Use a clear sequence: approach, grasp, orient, handoff, align to hole,
  lower, release, retreat.
- During placement, keep the test tube and target hole visible from the wrist
  camera when possible.
- Discard failures, collisions, long hesitation, and obvious off-task episodes
  with `Y`.
- Do not mix trial recordings into a formal dataset. Remove the corresponding
  `datasets/lerobot/<repo_id>` directory before starting a clean dataset.

### Reusing For New Tasks

The recorder backend is not specific to test-tube placement. For another task,
reuse the same entrypoint and change only the `repo_id` and natural-language
task prompt:

```bash
bash scripts/run_dataset_capture.sh real pico4ultra \
  --dataset-repo-id local/<new_task_name> \
  --dataset-task "<describe the new task in one clear sentence>"
```

Reuse guidelines:

- Use a separate `repo_id` per task, for example `local/nero_tube_pick_place`
  or `local/nero_block_stack`.
- Write `--dataset-task` as the same prompt that will be used at inference
  time.
- If the task still uses the dual Nero arms, two grippers, and three cameras,
  keep the same schema.
- A future in-house collection UI only needs to provide the same
  `state/action/images/task` schema and can reuse
  `create_dataset_recorder(config, capture_config)` to write the same LeRobot
  v3 dataset format.
- Ordinary VR teleoperation remains unchanged. LeRobot is loaded only when
  `--dataset-capture` is enabled.

See [docs/DATASET_CAPTURE_PI05.md](docs/DATASET_CAPTURE_PI05.md) for pi0.5
action semantics and server-side training notes.

### Full Capture Flow After PC Reboot

After rebooting the robot PC, use this sequence to start a clean formal capture
session:

1. Power on the arms, grippers, USB-CAN adapters, RealSense cameras, and Pico 4
   Ultra. Confirm the workspace is safe.
2. In the Nero Web UI, confirm both arms are enabled and CAN push is active.
3. Enter the project:

   ```bash
   cd /home/zxd/xrobot
   ```

4. Bring up CAN:

   ```bash
   bash scripts/setup_can.sh can0 can1 1000000
   bash scripts/check_can_ready.sh can0 can1
   ```

5. Start XRoboToolkit PC Service:

   ```bash
   bash scripts/start_pc_service_background.sh
   pgrep -a RoboticsService
   ```

6. Check the Pico profile, three cameras, and Python imports:

   ```bash
   bash scripts/run_teleop.sh check pico4ultra
   ```

7. Open the XRoboToolkit app on Pico, enter the PC IP, and enable
   `Controller tracking` and `Send`.
8. Start dataset capture:

   ```bash
   bash scripts/run_dataset_capture.sh real pico4ultra \
     --dataset-repo-id local/nero_tube_pick_place \
     --dataset-task "pick up the test tube and place it into the tube rack" \
     2>&1 | tee logs/dataset_capture_$(date +%Y%m%d_%H%M%S).log
   ```

9. Wait for both arms to reach the startup pose. Do not hold grip during
   startup motion.
10. Arrange the task objects, then press left controller `X` to start an
    episode.
11. Finish one task trial, then press left controller `X` to save it. Press
    left controller `Y` to discard failed trials.
12. Press `Ctrl-C` when the capture session is done.
13. Check the dataset:

    ```bash
    jq '.total_episodes, .total_frames, .fps' \
      datasets/lerobot/local/nero_tube_pick_place/meta/info.json

    find datasets/lerobot/local/nero_tube_pick_place -maxdepth 6 -type f | sort
    ```

14. Keep only formal successful episodes in the formal dataset. Remove the
    corresponding `datasets/lerobot/<repo_id>` directory if a trial dataset
    should not be used for training.

## Hardware Requirements

- Two AgileX Nero arms.
- Two AGX_GRIPPER grippers.
- Two USB-CAN adapters supported by Linux `gs_usb`.
- A powered USB hub is recommended for the USB-CAN adapters.
- Robot PC running Ubuntu 22.04.
- Meta Quest 3 and/or Pico 4 Ultra.
- The headset and robot PC must be on the same LAN for XRoboToolkit PC Service.
- The Nero Web UI must be reachable over Ethernet for CAN push setup and
  manual recovery.

## Safety Requirements

Before running real teleoperation:

- Clear the workspace around both arms.
- Confirm the emergency stop is reachable.
- Confirm both arms are powered and Web UI control works.
- Confirm CAN push is enabled in the Nero Web UI.
- Confirm `hardware_check` can read both arms.
- Do not hold grip while the program is moving to the startup pose.
- Use low-risk small motions when validating a new headset or PC.

The default safety behavior:

- Grip is the deadman switch for arm following.
- Trigger controls the matching gripper independently of grip.
- Releasing grip holds the current arm target.
- XR timeout stops command updates.
- Joint command deltas are limited each cycle.
- Gripper width command deltas are limited each cycle.
- Startup and shutdown return use `move_j`.
- Active teleoperation uses `move_js` after safety limiting.
- IK includes low-weight joint posture regularization to avoid odd
  intermediate-joint twisting from 7-DoF redundancy.

## First-Time Setup On This PC

Run all commands from the project root:

```bash
cd /home/zxd/xrobot
```

Install system packages:

```bash
bash scripts/install_system_deps.sh
```

Create the virtual environment and install base Python dependencies:

```bash
bash scripts/bootstrap_python.sh
```

Fetch upstream dependencies and install the minimal runtime:

```bash
bash scripts/setup_third_party.sh
bash scripts/install_runtime_minimal.sh
```

Install this project in editable mode if needed:

```bash
. .venv/bin/activate
pip install -e .
```

Install XRoboToolkit PC Service:

```bash
bash scripts/download_pc_service_deb.sh
bash scripts/install_pc_service_deb.sh
```

Start PC Service:

```bash
bash scripts/run_pc_service.sh
```

For background startup:

```bash
bash scripts/start_pc_service_background.sh
```

## Headset APK Setup

The project uses official XR-Robotics APKs:

- Quest3: `XRoboToolkit-Quest-1.0.1.apk`
- Pico 4 Ultra: `XRoboToolkit-PICO-1.1.1.apk`

Download and verify APKs:

```bash
bash scripts/download_headset_apk.sh quest3
bash scripts/download_headset_apk.sh pico4ultra
```

Install the Quest APK:

```bash
bash scripts/install_headset_apk.sh quest3
```

Install the Pico APK:

```bash
bash scripts/install_headset_apk.sh pico4ultra
```

Legacy Quest wrappers are still available:

```bash
bash scripts/download_quest_apk.sh
bash scripts/install_quest_apk.sh
```

ADB notes:

- Enable developer mode on the headset before installing APKs.
- Connect the headset over USB and confirm USB debugging inside the headset.
- If multiple Android devices are connected, set `ADB_SERIAL=<serial>`.
- USB is only required for installing APKs or ADB maintenance. Runtime
  teleoperation uses LAN through XRoboToolkit PC Service.

## Quest Keep-Awake Setup

This section is only for Meta Quest 3. Use it when you want to start teleop,
take off the headset, place it safely on the table, and keep using the two
controllers.

Recommended headset setting:

1. Wear the Quest headset.
2. Open `Settings`.
3. Go to `System` -> `Power`.
4. Set headset auto sleep to the longest available value.
5. Keep the headset charged or connected to power during long tests.

Developer-mode keep-awake option:

1. Confirm the Quest is connected through ADB:

   ```bash
   adb devices -l
   ```

2. Extend the Android screen timeout:

   ```bash
   adb shell settings put system screen_off_timeout 14400000
   ```

   `14400000` is 4 hours in milliseconds.

3. Disable the Quest proximity sleep behavior for the current boot:

   ```bash
   adb shell taskset 0000000F am broadcast -a com.oculus.vrpowermanager.prox_close
   ```

   If `taskset` is unavailable on a headset OS version, try:

   ```bash
   adb shell am broadcast -a com.oculus.vrpowermanager.prox_close
   ```

4. Start the Quest headset app, enable Controller tracking and Send, then place
   the headset somewhere stable and away from direct sunlight.
5. Run teleoperation normally:

   ```bash
   bash scripts/run_teleop_quest.sh real
   ```

Restore normal Quest sleep behavior:

```bash
adb shell am broadcast -a com.oculus.vrpowermanager.automation_disable
adb shell settings delete system screen_off_timeout
```

Notes:

- The proximity-sensor command may reset after reboot. Run it again before a
  teleop session if needed.
- Do not cover the lenses or leave the headset in direct sunlight.
- Disabling sleep increases battery drain and heat. Monitor the headset during
  long teleop sessions.
- This setup is not required for Pico.

## CAN Setup

Default mapping:

- Left Nero arm: `can0`
- Right Nero arm: `can1`
- Bitrate: `1000000`

Bring up CAN:

```bash
bash scripts/setup_can.sh can0 can1 1000000
```

Verify the CAN interfaces:

```bash
bash scripts/check_can_ready.sh can0 can1
```

Check USB-CAN physical port mapping:

```bash
for iface in can0 can1; do
  echo "== $iface =="
  ethtool -i "$iface" | grep bus-info
done
```

If interface names change after reboot or after replugging the USB hub, inspect
the current mapping and adjust `configs/nero_dual_agx.yml` if needed.

## Nero Web UI CAN Push

Nero Web UI control over Ethernet is not the same as PC control over USB-CAN.
For `pyAgxArm` with Linux `socketcan`, the Nero Web UI must enable CAN push.

After enabling CAN push in the Web UI, `candump` should show continuous frames:

```bash
timeout 10s candump can0 can1
```

If `candump` is empty:

- Confirm CAN push is enabled in the Nero Web UI.
- Confirm CAN-H/CAN-L/GND wiring.
- Confirm both USB-CAN adapters are powered.
- Use a powered USB hub if the adapters are on a hub.
- Confirm the adapters are connected to the Nero CAN ports, not only to USB.

## Hardware Check

Before real teleoperation, always verify robot-side communication:

```bash
bash scripts/hardware_check.sh --timeout-s 5
```

Expected result:

```text
left_arm: read 7 joints [...]
right_arm: read 7 joints [...]
```

If this fails, do not start teleoperation. Fix CAN push, wiring, power, or CAN
mapping first.

## Running Teleoperation

Check project status:

```bash
bash scripts/status.sh
```

Check Quest profile:

```bash
bash scripts/run_teleop_quest.sh check
```

Check Pico profile:

```bash
bash scripts/run_teleop_pico.sh check
```

Dry-run with Placo visualization:

```bash
bash scripts/run_teleop_quest.sh dry-run
bash scripts/run_teleop_pico.sh dry-run
```

Run Quest real teleoperation:

```bash
bash scripts/run_teleop_quest.sh real
```

Run Pico real teleoperation:

```bash
bash scripts/run_teleop_pico.sh real
```

The headset app must have Controller tracking and Send enabled.

If the headset app asks for the PC address, use the IP address of the robot PC
on the same LAN as the headset:

```bash
hostname -I
```

## Operator Workflow

1. Power on both Nero arms.
2. Open Nero Web UI and confirm both arms can be controlled manually.
3. Enable CAN push in the Nero Web UI.
4. Power the USB-CAN hub if using one.
5. Bring up CAN:

   ```bash
   bash scripts/setup_can.sh can0 can1 1000000
   ```

6. Verify CAN and joint reads:

   ```bash
   timeout 10s candump can0 can1
   bash scripts/hardware_check.sh --timeout-s 5
   ```

7. Start XRoboToolkit PC Service:

   ```bash
   bash scripts/run_pc_service.sh
   ```

8. Open the headset app.
9. Enable Controller tracking and Send.
10. Start the matching teleop script:

   ```bash
   bash scripts/run_teleop_quest.sh real
   # or
   bash scripts/run_teleop_pico.sh real
   ```

11. Wait for both arms to reach the startup pose.
12. Hold grip to start following with the corresponding arm.
13. Use trigger to control the corresponding gripper.
14. Press Ctrl-C once to return both arms to zero and exit normally.

## Current Control Mapping

The current mapping reflects the tested physical setup:

- `left_arm` uses `right_controller`, `right_grip`, `right_trigger`.
- `right_arm` uses `left_controller`, `left_grip`, `left_trigger`.
- Translation sign: `[-1, -1, 1]`.
- Rotation sign: `[-1, -1, 1]`.
- Control mode: pose, meaning position and wrist orientation are both used.
- Tuned wrist response: `orientation_weight: 0.45`, `rotation_scale: 0.95`.
- Joint posture regularization: `posture_regularization_weight: 0.001`, used to
  reduce odd shoulder/elbow twists in the 7-DoF IK solution while preserving
  wrist following.

These settings are shared by Quest and Pico. Do not duplicate robot tuning per
headset unless a device-specific input convention is proven different.

## Startup, Shutdown, And Hold Behavior

Startup:

- Both arms move to `[0, 45, 0, 45, 0, 0, 0]` degrees.
- Startup uses `move_j`, currently tuned to `speed_percent: 20` and
  `max_delta_rad_per_cycle: 0.012`.
- Grip input should not be used until startup completes.

Normal teleoperation:

- Active teleop uses `move_js`.
- Joint delta limiting remains active before commands are sent.
- Logs are disabled by default in real mode to reduce CAN/SDK load.

Ctrl-C:

- Press Ctrl-C once.
- Teleop input stops.
- Both arms return to zero `[0, 0, 0, 0, 0, 0, 0]`.
- Return-to-zero is currently tuned to `speed_percent: 40` and
  `max_delta_rad_per_cycle: 0.022`.
- The program exits without intentionally disabling the arms.
- After a normal exit, `hold_enabled` starts to keep the arms enabled.

If initialization fails:

- `hold_enabled` is not started automatically.
- Fix the failed condition first.

Manual hold controls:

```bash
bash scripts/start_hold_enabled.sh
bash scripts/stop_hold_enabled.sh
```

Manual disable, only when safe:

```bash
bash scripts/disable_arms.sh
```

## Important Configuration

Main config file:

```text
configs/nero_dual_agx.yml
```

Key fields:

- `robot.control_rate_hz`: teleop loop rate.
- `robot.teleop_speed_percent`: Nero speed percent during teleop.
- `robot.teleop_command_mode`: active command mode, currently `move_js`.
- `robot.allow_move_js`: explicit risk acknowledgement for `move_js`.
- `gripper.open_width_m`: fully open gripper target, currently `0.10`.
- `gripper.max_delta_m_per_cycle`: gripper speed limit per control cycle.
- `startup.*`: startup pose and speed, currently 20% with a 0.012 rad maximum
  per cycle.
- `shutdown.*`: Ctrl-C return-to-zero pose and speed, currently 40% with a
  0.022 rad maximum per cycle.
- `xr_mapping.*`: headset-to-robot direction and pose weighting.
- `xr_mapping.orientation_weight` / `xr_mapping.rotation_scale`: wrist
  orientation following weight and response scale, currently field-tuned to
  0.45 / 0.95.
- `xr_mapping.posture_regularization_weight`: low-weight joint posture
  regularization, currently 0.001, used to suppress odd intermediate-joint
  twisting.
- `safety.max_joint_delta_rad_per_cycle`: active teleop joint delta limit per
  cycle, currently 0.014. Do not start by loosening this when tuning wrist
  response.
- `headsets.profiles.quest3`: Quest APK metadata.
- `headsets.profiles.pico4ultra`: Pico APK metadata.

## Testing

Run unit tests:

```bash
. .venv/bin/activate
pytest -q tests
```

Run smoke test:

```bash
bash scripts/smoke_test.sh
```

Run profile checks:

```bash
bash scripts/run_teleop_quest.sh check
bash scripts/run_teleop_pico.sh check
```

Run hardware check:

```bash
bash scripts/hardware_check.sh --timeout-s 5
```

## Troubleshooting

### `hardware_check` says `SDK returned no data`

Most likely causes:

- CAN push is not enabled in Nero Web UI.
- USB-CAN hub is not powered.
- CAN-H/CAN-L/GND wiring is wrong or loose.
- `can0/can1` mapping is wrong.
- The USB-CAN adapters are connected to the PC but not to the Nero CAN ports.

Check:

```bash
timeout 10s candump can0 can1
```

If `candump` is empty, fix CAN before running teleop.

### `read: Network is down`

The CAN interfaces are down. Run:

```bash
bash scripts/setup_can.sh can0 can1 1000000
```

### `left_arm/right_arm did not enable within 20.0s`

The wrapper now waits up to 20 seconds while periodically setting normal mode,
bulk-enabling the arm, and sending per-joint enable commands for joints that are
still disabled. If it still fails, run:

```bash
bash scripts/check_can_ready.sh can0 can1
bash scripts/hardware_check.sh --timeout-s 5
bash scripts/enable_can_push_check.sh --timeout-s 15
```

Confirm CAN push is enabled in the Web UI, the USB-CAN hub has external power,
and there is no emergency-stop or error state. If needed, recover manually in
the Web UI before trying again. Do not retry real teleop until joint reads work.

### Headset app cannot connect to PC Service

Check:

- PC Service is running:

  ```bash
  pgrep -a RoboticsService || bash scripts/run_pc_service.sh
  ```

- Headset and PC are on the same LAN.
- The headset app uses the correct PC IP:

  ```bash
  hostname -I
  ```

- Controller tracking and Send are enabled inside the app.

### APK install fails

Check ADB:

```bash
adb devices -l
```

If unauthorized, put on the headset and confirm USB debugging.

If multiple devices are connected:

```bash
ADB_SERIAL=<serial> bash scripts/install_headset_apk.sh quest3
ADB_SERIAL=<serial> bash scripts/install_headset_apk.sh pico4ultra
```

### Gripper does not open enough

The teleop target is currently `0.10m`. If the physical gripper still opens only
about `0.07m`, the gripper may need teaching pendant parameter configuration or
calibration for the larger stroke. AgileX examples mention both `0.07m` and
`0.10m` maximum stroke configurations.

## Migrating To Another PC

There are two supported migration styles.

### Option A: Copy The Whole Project Folder

Copy `/home/zxd/xrobot` to the new PC, for example:

```bash
rsync -a /home/zxd/xrobot/ user@new-pc:/home/zxd/xrobot/
```

On the new PC:

```bash
cd /home/zxd/xrobot
```

Recreate the Python environment. Do not rely on the copied `.venv`:

```bash
rm -rf .venv
bash scripts/install_system_deps.sh
bash scripts/bootstrap_python.sh
bash scripts/install_runtime_minimal.sh
. .venv/bin/activate
pip install -e .
```

Install PC Service:

```bash
bash scripts/download_pc_service_deb.sh
bash scripts/install_pc_service_deb.sh
```

If APK files were copied, they will be reused. Otherwise download them:

```bash
bash scripts/download_headset_apk.sh quest3
bash scripts/download_headset_apk.sh pico4ultra
```

Install headset APKs if the new PC/headset setup needs it:

```bash
bash scripts/install_headset_apk.sh quest3
bash scripts/install_headset_apk.sh pico4ultra
```

Start PC Service:

```bash
bash scripts/run_pc_service.sh
```

Configure CAN:

```bash
bash scripts/setup_can.sh can0 can1 1000000
```

If the new PC maps USB-CAN adapters differently, inspect:

```bash
for iface in can0 can1; do
  echo "== $iface =="
  ethtool -i "$iface" | grep bus-info
done
```

Then update `configs/nero_dual_agx.yml` if left/right channels changed.

Enable CAN push from Nero Web UI and verify:

```bash
timeout 10s candump can0 can1
bash scripts/hardware_check.sh --timeout-s 5
```

Run the desired headset:

```bash
bash scripts/run_teleop_quest.sh real
bash scripts/run_teleop_pico.sh real
```

### Option B: Fresh Clone Or Fresh Folder

Create `/home/zxd/xrobot` on the new PC and place the project files there.
Then run:

```bash
cd /home/zxd/xrobot
bash scripts/install_system_deps.sh
bash scripts/bootstrap_python.sh
bash scripts/setup_third_party.sh
bash scripts/install_runtime_minimal.sh
. .venv/bin/activate
pip install -e .
```

Install PC Service and APKs:

```bash
bash scripts/download_pc_service_deb.sh
bash scripts/install_pc_service_deb.sh
bash scripts/download_headset_apk.sh quest3
bash scripts/download_headset_apk.sh pico4ultra
```

Install APKs through ADB:

```bash
bash scripts/install_headset_apk.sh quest3
bash scripts/install_headset_apk.sh pico4ultra
```

Start PC Service:

```bash
bash scripts/run_pc_service.sh
```

Bring up CAN and verify:

```bash
bash scripts/setup_can.sh can0 can1 1000000
timeout 10s candump can0 can1
bash scripts/hardware_check.sh --timeout-s 5
```

Run:

```bash
bash scripts/run_teleop_quest.sh real
# or
bash scripts/run_teleop_pico.sh real
```

## Migration Notes

- The generated URDF uses `package://agx_arm_description/...` mesh paths and
  the runtime scripts set `ROS_PACKAGE_PATH` automatically. Moving the project
  folder does not require editing mesh paths.
- A copied `.venv` is not considered portable. Recreate it on the new PC.
- USB-CAN interface names can change on a new PC. Always run `hardware_check`
  before teleoperation.
- The headset app may need the new PC IP after migration.
- PC Service must be installed on the new PC; copying the repository alone is
  not enough.
- If the new PC cannot access GitHub or PyPI reliably, copy `third_party/`,
  `assets/apk/`, and `assets/deb/` from the old PC and use the local install
  scripts.

## References

- XR-Robotics: https://github.com/XR-Robotics
- XRoboToolkit Quest client: https://github.com/XR-Robotics/XRoboToolkit-Unity-Client-Quest
- XRoboToolkit Pico client: https://github.com/XR-Robotics/XRoboToolkit-Unity-Client
- AgileX Robotics: https://github.com/agilexrobotics
- pyAgxArm: https://github.com/agilexrobotics/pyAgxArm
- Official Nero URDF: https://github.com/agilexrobotics/agx_arm_urdf/tree/main/nero
