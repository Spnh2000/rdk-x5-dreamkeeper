# IMX708 V4L2 driver for the RDK X5

The RDK X5 OS (3.5.0, kernel 6.1.83) has no support for the Sony IMX708, the
sensor of the Raspberry Pi Camera Module 3 and of Arducam's IMX708 modules.
This is the Raspberry Pi kernel driver (`rpi-6.1.y`,
`drivers/media/i2c/imx708.c`) ported to the X5 camera pipeline in its V4L2
mode (sensor -> MIPI CSI-2 -> SIF -> ISP -> VSE -> `/dev/video8`).

License: GPL-2.0, like the original driver (see the SPDX header).

## Files

| File | Installed as |
|------|--------------|
| `imx708.c`, `Makefile` | `/lib/modules/6.1.83/kernel/drivers/media/i2c/imx708.ko` |
| `dtoverlay_cam0_imx708.dts` | `/boot/overlays/dtoverlay_cam0_imx708.dtbo` |

`../scripts/install_driver.sh` builds and installs everything, including the
ISP files and `/boot/config.txt` (see below).

## What the port changes

Search for "RDK X5 port" in `imx708.c`.

| Change | Why |
|--------|-----|
| One source pad (no metadata pad) | as in D-Robotics' own imx477/imx219 drivers |
| Embedded-data lines off (`0xBCF1 = 0`, param `embedded_data`) | they trip the X5 SIF frame-size check |
| One mode: 2x2 binned, centre-cropped to **1920x1080** | the X5 pipeline input is at most 1920x1080; after the first stream it programs its receiver for 1920x1080 whatever the sensor reports, so a 2304x1296 mode works exactly once per boot |
| `g_frame_interval` | the X5 pipeline reads the frame rate through it |
| No `_wide`/`_noir` suffix on the subdev name | the X5 CSI takes the sensor name up to the first space (`imx708 6-001a`) and loads `/usr/hobot/lib/sensor/lib<name>_v4l2.so` |

The mode's default timing is 30 fps (VBLANK 1414 lines); the X5 pipeline
sets VBLANK to its minimum (256), which gives
585.6 MHz / (7824 x 1336) = **56 fps**. The crop keeps the centre 1920 of 2304
columns and 1080 of 1296 rows of the binned image (83 % of each).

Module parameters (`/etc/modprobe.d/imx708.conf`):

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `trace` | 1 | log pad-format and stream calls (bring-up); the install sets 0 |
| `x5_mode` | 0 | 1 = full binned 2304x1296 (works once per boot, test only) |
| `embedded_data` | 0 | 1 = sensor sends embedded-data lines (RPi default) |
| `qbc_adjust` | 2 | from the RPi driver (full-resolution mode only, unused here) |

## Device tree overlay

CAM0 port: I2C controller `341d0000.i2c` (Linux bus 6), address `0x1a`,
reset on `lsio_gpio1_6`, 24 MHz fixed clock, 2 data lanes, 450 MHz link.
Modelled on D-Robotics' `dtoverlay_cam0_imx477.dts`.
The autofocus VCM (dw9807 at `0x0c`) is not declared, so the lens stays at
its rest focus (sharp from about 20 cm to the far side of a room).

## ISP side

The X5 ISP needs a per-sensor helper library and tuning file. The install
borrows the IMX477 ones:

- `/usr/hobot/lib/sensor/libimx708_v4l2.so` = copy of `libimx477_v4l2.so.1.0.0`
- `imx708_tuning.json`, `imx708_1920x1080_tuning.json` = copies of
  `imx477_1920x1080_tuning.json` with `sensor_name` set to `imx708`.
  It must be the 1920x1080 tuning: its crop rectangles, lens-shading sectors
  and AF window must match the resolution, or the image is banded garbage.

Colours and white balance look plausible but are **not calibrated** for this sensor.

## Boot configuration

`/boot/config.txt` (read by U-Boot and `/etc/init.d/S70loadko`; it does not
exist on a fresh image):

```
v4l2_enable
v4l2_scene=22
dtoverlay=dtoverlay_cam0_imx708

```

`v4l2_enable` + `v4l2_scene=22` is what `srpi-config` writes for the
"V4L2 sif-isp-vse" camera mode: S70loadko then loads the V4L2 camera
drivers instead of the HBN stack. Keep the trailing empty line.

## Pitfalls met during bring-up

- **The sensor can hold its I2C bus** (`i2c_designware 341d0000.i2c:
  controller timed out`, `chip id ... ret -5`, `Failed to write reg 0x0100`).
  A soft reboot does not clear it, neither does re-binding the driver; only a
  power cut does. See the main README.
- Do **not** unbind/rebind the I2C controller `341d0000.i2c`: it hung the
  kernel and the watchdog rebooted the board.
- Do not read SIF registers through `/dev/mem` (bus error).
- A rebuilt module only loads after a restart: the pipeline holds the old
  one (`rmmod`: in use).
- `sif frame size incorrect` kernel lines at stream start/stop are harmless.
