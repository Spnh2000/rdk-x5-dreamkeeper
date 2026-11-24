# Proposal: Vision-Guided Desk Sorter

**Robotics Dream Keeper Challenge 2026 Winter, Stage 2 (Build).**
Participant: ZakiePanahipour. Repository: https://github.com/Spnh2000/rdk-x5-dreamkeeper
Companion documents: [ARCHITECTURE.md](ARCHITECTURE.md),
[ENGINEERING_PLAN.md](ENGINEERING_PLAN.md), [../../ROADMAP.md](../../ROADMAP.md).

An industrial collaborative arm (Fairino FR5) with an RDK X5 and a camera on
its wrist. It finds everyday objects on a table, picks each one up and drops
it into the bin for its kind, with all AI running on the RDK X5's BPU.

## 1. Problem

Sorting mixed small items is everyday work: clearing a workbench, sorting
returns, tidying a lab or a desk. Industrial arms are good at repeating a
taught path, but a taught path only works when every object is always in the
same place. To handle objects placed anywhere, the arm has to **see** them.
Vision systems for industrial arms are usually expensive, closed products
running on a PC. This project shows that a **low-cost embedded AI board**,
attached to the arm, can provide the eyes and the decisions.

## 2. Operating scenario and constraints

**Setting:** a table (about 60 x 80 cm) next to a Fairino FR5 in a workplace
lab. Up to 8 objects lie on the table at random positions and angles, not
stacked. Three labelled bins stand at fixed positions in the arm's reach.

**Objects and bins:** classes that YOLO (COCO) recognises and that the
gripper can hold by a part narrower than its 40 mm stroke:

| Bin | Classes | Grasped at |
|-----|---------|------------|
| A: drinkware | `bottle`, `cup` | bottle neck or cap; cup rim (one finger inside, one outside) |
| B: cutlery | `fork`, `knife`, `spoon` | handle |
| C: other | `scissors`, `toothbrush`, `banana` | handle / middle |
| no bin | anything else stays on the table and is reported | |

**Constraints:**

| Constraint | Consequence for the design |
|------------|----------------------------|
| Arm access only a few sessions per week | develop and test perception off the arm (recorded images, offline replay); arm sessions are short and scripted |
| One camera, no depth sensor | objects are assumed to lie on the known table plane; height comes from the arm pose, not from the image |
| Camera ribbon cable is short | the RDK X5 rides on the arm next to the camera (built: 3D-printed camera bracket at the wrist, board fixed to the arm); only power and Ethernet run along the arm |
| Shared workplace, real industrial arm | collaborative mode, reduced speed, software workspace limits, emergency stop always reachable |
| Jodell EPG40-050 gripper: 0–40 mm stroke, 2–50 N per finger, about 0.8 kg recommended load | objects must offer a grasp point narrower than about 38 mm and weigh under 0.8 kg; the grasp point is chosen per class |
| Lighting not controlled | auto exposure plus a confidence threshold |

## 3. Intended user and interaction

**Users:** lab staff or makers who want a tidy work area without teaching
the robot every object position, and visitors watching a demonstration.

**Interaction:**
1. The user places objects on the table and starts a sorting run from a
   **web page** (start, pause, stop, choose which classes to sort).
2. The web page shows the live camera view with detections, the object being
   handled, and a log ("cup → bin A, 11.8 s").
3. The user can stop at any time from the page; the arm's **hardware
   emergency stop** always overrides the software.
4. Objects it cannot classify or grasp are left on the table and listed, so
   the user knows what to handle by hand.

## 4. Core capabilities

### Perception (RDK X5, BPU)
- **Live camera:** IMX708 12 MP sensor on the wrist, 1920x1080 at 56 fps
  through the driver ported in Stage 1, published into ROS 2.
- **Object detection:** YOLOv8n on the BPU (measured in Stage 1: 7 ms per
  frame, 56 frames/s, 21 % BPU load), giving class, box and confidence.
- **Object outline and angle:** a YOLOv8 **segmentation** model on the BPU
  (included in the RDK OS image), giving each object's mask. The mask's
  minimum-area rectangle gives the grasp angle and width.
- **Position on the table:** pixel → table coordinates from the wrist pose
  (read from the arm), the camera calibration (lens + camera-to-gripper,
  calibrated once) and the known table height.

### Decision (RDK X5, CPU)
- A **sorting state machine:** survey → choose next object → approach →
  close-up check → grasp → lift and verify → place → return.
- **Close-up check:** above the object the camera detects again from short
  distance and corrects the position before grasping. This is the main
  advantage of the wrist camera.
- **Grasp check:** after closing, the gripper reports its finger position;
  fully closed means nothing was caught. After lifting, the camera checks
  that the object left the table. A failed grasp is retried once, then
  skipped.
- **Safety supervisor:** every target is checked against the allowed
  workspace before it is sent; heartbeat between RDK X5 and arm; any error
  → stop and return to a safe pose.

### Actuation (Fairino FR5 + electric gripper)
- The RDK X5 sends **target poses** to the FR5 controller (software
  v3.9.8) over Ethernet with Fairino's official Python SDK; the controller
  plans and executes the motion.
- **Jodell EPG40-050 electric parallel gripper** (Modbus RTU over RS-485,
  24 V) on the FR5's end-tool connector. The RDK X5 commands position, speed
  and force through the controller and reads back the finger position.
- Collaborative mode with reduced speed and the controller's collision
  detection active.

## 5. Innovation compared with a stock demo

| Stock demo | This project |
|------------|--------------|
| Vendor camera, bundled driver | IMX708 sensor with no X5 support, made to work by porting the kernel driver (Stage 1) |
| Detection shown on a screen | detection **closes the loop** to an industrial arm that acts on it |
| Fixed camera, boxes only | camera **moves with the arm**: survey from far, correct from close up |
| Axis-aligned boxes | **segmentation masks** give the grasp angle and width |
| Model resize fails in V4L2 mode | letterboxed 640x640 input pipeline that runs every frame on the BPU (Stage 1) |
| PC in the loop | all perception and decisions on a 10 TOPS embedded board riding on the arm |

## 6. Measurable success targets

Measured at the final demo (Stage 3) over a run of **20 objects** placed at
random.

| # | Metric | Target | How it is measured |
|---|--------|--------|--------------------|
| 1 | Detection rate on the BPU, live camera | ≥ 30 fps (Stage 1: 56 fps) | `ros2 topic hz` on detections |
| 2 | Segmentation latency on the BPU | ≤ 30 ms per frame **[to measure]** | node timing log |
| 3 | Image-to-arm-command latency | ≤ 100 ms | time stamps from image to SDK call |
| 4 | Grasp position error on the table | ≤ 10 mm | marked test points, ruler |
| 5 | Classification accuracy of sorted objects | ≥ 90 % | correct class / detected objects |
| 6 | Sorting success (in the correct bin) | ≥ 80 % | objects in correct bin / 20 |
| 7 | Cycle time per object | ≤ 20 s | run log |
| 8 | Safety | 0 workspace violations, e-stop tested before every session, collaborative speed ≤ 250 mm/s | supervisor log, checklist |

## 7. Scope

**In scope (Stage 3):** the sorting loop above, calibration tools, the web
page, safety supervisor, documentation and a public demo video.

## 8. Hardware facts (verified on site)

| Item | Value |
|------|-------|
| Arm | Fairino FR5, 6 axes, 5 kg payload, controller software v3.9.8 |
| Gripper | Jodell EPG40-050: 0–40 mm stroke, 2–50 N per finger, Modbus RTU (RS-485), 24 V |
| Safety | collaborative speed limit 250 mm/s, collision detection active, emergency stop within reach of the operator |
| Network | RDK X5 connected to the controller's Ethernet network |
| Mounting | IMX708 camera on a 3D-printed bracket at the wrist; RDK X5 fixed to the arm |
