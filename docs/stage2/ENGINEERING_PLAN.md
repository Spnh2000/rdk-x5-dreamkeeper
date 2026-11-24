# Engineering Plan: Vision-Guided Desk Sorter

**Stage 2 (Build), Challenge 3.** Companion documents: [PROPOSAL.md](PROPOSAL.md),
[ARCHITECTURE.md](ARCHITECTURE.md), [../../ROADMAP.md](../../ROADMAP.md).

## 1. Bill of materials

Costs are estimates in EUR. "Owned" = already in hand; "provided" = provided
for this project at no cost to the participant (the arm, gripper and network
equipment by the participant's workplace).

| # | Item | Qty | Supplier / SKU | Voltage / interface | Est. cost | Status |
|---|------|-----|----------------|---------------------|-----------|--------|
| 1 | RDK X5 (4 GB) | 1 | D-Robotics | 5 V / 5 A USB-C; Ethernet, MIPI CSI-2 | – | provided |
| 2 | Arducam IMX708 12 MP camera, wide angle, with ribbon cable | 1 | Arducam | 3.3 V from the board; MIPI CSI-2 2-lane + I2C | 30 | owned |
| 3 | microSD card, 32 GB (RDK OS 3.5.0) | 1 | any | – | 10 | owned |
| 4 | Fairino FR5 collaborative arm + controller + teach pendant | 1 | Fairino FR5 | controller 100–240 V AC; Ethernet to the RDK X5 | – | provided |
| 5 | Jodell EPG40-050 electric parallel gripper (Fairino version) | 1 | Jodell Robotics EPG40-050 | 24 V from the FR5 tool connector; RS-485 Modbus RTU | – | provided |
| 6 | 3D-printed camera bracket (wrist) | 1 | self-printed, PETG | – | 2 | built |
| 7 | 3D-printed RDK X5 mounting plate + straps | 1 | self-printed, PETG | – | 3 | built |
| 8 | USB-C power supply 5 V / 5 A + 2 m USB-C cable along the arm | 1 | any USB-PD supply | 5 V / 5 A | 20 | owned |
| 9 | Flexible Ethernet cable, Cat 6, 3 m | 1 | any | 1 Gbit/s | – | provided |
| 10 | 5-port Ethernet switch (RDK X5 + controller + laptop) | 1 | any unmanaged switch | 5 V or 12 V | – | provided |
| 11 | ChArUco calibration board, printed on a rigid plate | 1 | self-printed | – | 5 | to make |
| 12 | Test objects: bottles, cups, cutlery, scissors, toothbrushes, bananas | ~20 | household | – | – | owned |
| 13 | Three sorting bins, labelled | 3 | any trays | – | 10 | to buy |
| | **To buy or make in total** | | | | **≈ 15** | |

## 2. Schedule

Three milestones run from 27 November to the final demo on 15 December:
M1 perception + arm connection (3 Dec), M2 one object sorted end to end
(10 Dec), M3 benchmarks, demo video and submission (15 Dec). Arm access is a
few sessions per week, so each of the seven arm sessions (A1–A7) has one fixed
goal, and everything else is developed off the arm with a **mock arm** (a
fr5_bridge stand-in that simulates motion) and recorded camera data.

The timeline, tasks per milestone and progress are kept in one place:
[ROADMAP.md](../../ROADMAP.md).

## 3. Top five risks

| # | Risk | Trigger (how we notice) | Mitigation (in advance) | Fallback (if it happens) |
|---|------|-------------------------|-------------------------|--------------------------|
| 1 | **Grasp position error too large** (hand-eye calibration, lens wide angle) | accuracy test A4 shows > 10 mm error | ChArUco board, ~15 varied poses, lens distortion calibrated first; close-up re-detection corrects the position before every grasp | visual centring: move the camera until the object is in the image centre, then descend straight down (needs only relative accuracy) |
| 2 | **Segmentation not usable** (too slow, or the example node does not publish masks) | segmentation > 30 ms per frame, or no masks in the message | own segmenter node using the RDK's Python BPU API, so we control the outputs; test in week 1 | detection boxes + classical OpenCV (`minAreaRect` on the object pixels inside the box) for the angle |
| 3 | **Limited arm time delays integration** | fewer than 2 arm sessions in a week, or a session goal missed | mock arm and recorded data for offline testing; a written checklist per session; start SDK tests in week 1 | reduce scope: 2 bins and fewer classes; demo with fewer objects |
| 4 | **Hardware on the moving arm fails** (ribbon cable snags, power or Ethernet cable strain, camera I2C lock-up) | stream time-outs, I2C errors in `dmesg`, cable under tension in some poses | route and fix the ribbon and cables along the arm, limit wrist rotation in software, power-cycle procedure documented | mount the camera fixed above the table (eye-to-hand); the localizer then uses a fixed camera pose instead of the wrist pose |
| 5 | **Unsafe motion** (collision with a person, the table or the bins) | workspace violation in the supervisor log, a collision stop, network loss | collaborative mode at ≤ 250 mm/s, software workspace box, minimum height above the table, heartbeat with automatic stop, e-stop tested before every session, a person always present | lower the speed to 100 mm/s and narrow the workspace; operate step by step from the web page |

## 4. Planned repository structure

```
rdk-x5-dreamkeeper/
├── README.md
├── ROADMAP.md
├── LICENSE                    GPL-2.0
├── driver/                    IMX708 kernel driver + device tree overlay (Stage 1)
├── src/                       ROS 2 packages (colcon workspace)
│   ├── imx708_camera/         camera node (moved from ros/)
│   ├── sorter_msgs/           custom messages, services, actions
│   ├── sorter_perception/     segmenter, tracker, localizer
│   ├── fr5_bridge/            Fairino SDK wrapper, gripper, mock arm
│   ├── sorter_core/           sorting state machine, safety supervisor
│   └── sorter_web/            control page
├── launch/                    full system: real arm / mock arm / camera only
├── config/                    workspace limits, bins, classes, calibration results (YAML)
├── models/                    model notes + download script (no large binaries in git)
├── scripts/                   install, stop, calibration helpers
├── tests/                     unit tests (geometry, state machine) + replay tests on recorded data
└── docs/
    ├── stage1/                Stage 1 evidence
    ├── stage2/                proposal, architecture, engineering plan
    └── safety.md              safety limits, e-stop and recovery (Stage 3)
```
