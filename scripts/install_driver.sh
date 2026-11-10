#!/bin/bash
# Build and install the IMX708 camera driver on an RDK X5
# (RDK OS 3.5.0, Ubuntu 22.04, kernel 6.1.83), on the board itself:
#
#   sudo scripts/install_driver.sh
#
# Installs: the kernel module (+ autoload), the CAM0 device tree overlay,
# the ISP helper library + tuning (borrowed from the IMX477) and
# /boot/config.txt (V4L2 camera mode + overlay; the old file is backed up).
# Afterwards power-cycle the board (README: "Restarting the board").
#
# DESTDIR=/some/dir installs into that directory instead of / (for testing;
# the kernel build tools are still prepared in the real header tree).
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "run as root: sudo $0" >&2; exit 1; }
REPO=$(cd "$(dirname "$0")/.." && pwd)
KDIR=${KDIR:-/usr/src/linux-headers-6}
KVER=$(uname -r)
D=${DESTDIR:-}
SENSOR_DIR=/usr/hobot/lib/sensor
CONFIG=$D/boot/config.txt

step() { printf '\n== %s\n' "$*"; }

step "kernel build tools in $KDIR"
[ -f "$KDIR/Makefile" ] || { echo "no kernel headers in $KDIR (apt install hobot-kernel-headers)" >&2; exit 1; }
if [ -x "$KDIR/scripts/basic/fixdep" ] && [ -x "$KDIR/scripts/mod/modpost" ]; then
    echo "already prepared"
else
    # The header package ships without its host tools. `make scripts` builds
    # fixdep and friends (~1 min). `make modules_prepare` then links
    # scripts/mod/modpost within seconds, but afterwards its prepare0 step
    # (`$(MAKE) $(build)=.`) recurses without end in this header tree
    # ("overriding recipe for target 'built-in.a'" over and over). Everything
    # a module build needs exists by then (scripts/module.lds ships with the
    # package), so stop it there. `timeout` signals the whole make tree.
    make -C "$KDIR" scripts
    log=$(mktemp)
    timeout 900 make -C "$KDIR" modules_prepare > "$log" 2>&1 &
    tpid=$!
    while kill -0 "$tpid" 2>/dev/null; do
        if [ -x "$KDIR/scripts/mod/modpost" ] && grep -q "overriding recipe for target" "$log"; then
            echo "modpost is built; stopping the endless recursion of modules_prepare"
            kill -TERM "$tpid"
            break
        fi
        sleep 1
    done
    wait "$tpid" || true
    grep -E '^ +[A-Z]+ ' "$log" || true
    [ -x "$KDIR/scripts/mod/modpost" ] || { echo "modpost was not built, see $log" >&2; exit 1; }
    rm -f "$log"
fi

step "build imx708.ko"
BUILD=$(mktemp -d)
trap 'rm -rf "$BUILD"' EXIT
cp "$REPO/driver/imx708.c" "$REPO/driver/Makefile" "$BUILD/"
make -C "$BUILD" KDIR="$KDIR"
vermagic=$(modinfo -F vermagic "$BUILD/imx708.ko")
case "$vermagic" in
    "$KVER "*) echo "vermagic: $vermagic" ;;
    *) echo "module built for '$vermagic', running kernel is $KVER" >&2; exit 1 ;;
esac

step "install the module"
install -D -m 644 "$BUILD/imx708.ko" "$D/lib/modules/$KVER/kernel/drivers/media/i2c/imx708.ko"
if [ -z "$D" ]; then depmod -a "$KVER"; fi
mkdir -p "$D/etc/modules-load.d" "$D/etc/modprobe.d"
echo imx708 > "$D/etc/modules-load.d/imx708.conf"
# trace=1 (the driver default) logs every pad-format and stream call
[ -f "$D/etc/modprobe.d/imx708.conf" ] || echo "options imx708 trace=0" > "$D/etc/modprobe.d/imx708.conf"

step "device tree overlay"
mkdir -p "$D/boot/overlays"
dtc -q -@ -I dts -O dtb -o "$D/boot/overlays/dtoverlay_cam0_imx708.dtbo" \
    "$REPO/driver/dtoverlay_cam0_imx708.dts"
cp "$REPO/driver/dtoverlay_cam0_imx708.dts" "$D/boot/overlays/"

step "ISP helper library and tuning (copies of the IMX477 ones)"
mkdir -p "$D$SENSOR_DIR"
cp "$SENSOR_DIR/libimx477_v4l2.so.1.0.0" "$D$SENSOR_DIR/libimx708_v4l2.so"
for f in imx708_tuning.json imx708_1920x1080_tuning.json; do
    sed 's/"sensor_name": "imx477"/"sensor_name": "imx708"/' \
        "$SENSOR_DIR/imx477_1920x1080_tuning.json" > "$D$SENSOR_DIR/$f"
    grep -q '"sensor_name": "imx708"' "$D$SENSOR_DIR/$f" \
        || { echo "could not set sensor_name in $f" >&2; exit 1; }
done

step "$CONFIG"
# V4L2 camera mode (= srpi-config "V4L2 sif-isp-vse") + the IMX708 overlay;
# any other CAM0 overlay line is dropped. Ends with an empty line.
if [ -f "$CONFIG" ]; then
    backup="$CONFIG.bak.$(date +%Y%m%d-%H%M%S)"
    cp -p "$CONFIG" "$backup"
    echo "backup: $backup"
    # $(...) also drops the trailing empty lines
    kept=$(grep -vE '^(v4l2_enable|v4l2_scene=|dtoverlay=dtoverlay_cam0_)' "$CONFIG" || true)
else
    kept=""
fi
{
    [ -n "$kept" ] && printf '%s\n' "$kept"
    printf 'v4l2_enable\nv4l2_scene=22\ndtoverlay=dtoverlay_cam0_imx708\n\n'
} > "$CONFIG.new"
mv "$CONFIG.new" "$CONFIG"
cat "$CONFIG"

step "done"
cat <<'EOF'
Now power-cycle the board (a soft reboot does not reset the sensor):
    sudo systemctl stop cam-service; sync; sudo poweroff
    # wait ~15 s, unplug the power for ~10 s, plug it back in
Then check:
    sudo dmesg | grep -E "imx708 6-001a: (chip|camera)"
    # -> "chip id try 0: ret 0 val 0x708" and "camera module ID 0x...."
    v4l2-ctl -d /dev/video8 --list-formats-ext
EOF
