#!/usr/bin/env python3
"""ROS 2 camera node for the IMX708 on the RDK X5 (V4L2 path).

Reads NV12 frames straight from the X5 camera pipeline
(sensor -> CSI -> SIF -> ISP -> VSE -> /dev/video8) with plain V4L2
memory-mapped streaming and publishes them as sensor_msgs/Image
(encoding "nv12") - the format hobot_codec and dnn_node_example take.

Optionally it also publishes a letterboxed square copy of every frame
(yolo_topic, yolo_size x yolo_size NV12, aspect ratio kept, black bars).
dnn_node_example resizes NV12 input with the hardware VSE through the HBN
stack, which is not available in V4L2 mode ("Resize nv12 img fail!"); it
skips that resize when the image already has the model input size.

Parameters: device (/dev/video8), width (960), height (544),
topic (/image_raw), yolo_topic ("" = off), yolo_size (640),
frame_id (camera), log_fps (true).
Each topic is only filled and published while it has subscribers.
"""
import array
import ctypes
import fcntl
import mmap
import os
import select
import signal
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image

# ---- V4L2 ABI (linux/videodev2.h, 64-bit) ---------------------------------
V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
V4L2_MEMORY_MMAP = 1
V4L2_FIELD_NONE = 1
V4L2_PIX_FMT_NV12 = int.from_bytes(b"NV12", "little")


class v4l2_pix_format(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint32) for n in (
        "width", "height", "pixelformat", "field", "bytesperline",
        "sizeimage", "colorspace", "priv", "flags", "ycbcr_enc",
        "quantization", "xfer_func")]


class _fmt_union(ctypes.Union):
    _fields_ = [("pix", v4l2_pix_format), ("raw_data", ctypes.c_uint8 * 200),
                ("_align", ctypes.c_uint64)]


class v4l2_format(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("fmt", _fmt_union)]


class v4l2_requestbuffers(ctypes.Structure):
    _fields_ = [("count", ctypes.c_uint32), ("type", ctypes.c_uint32),
                ("memory", ctypes.c_uint32), ("capabilities", ctypes.c_uint32),
                ("flags", ctypes.c_uint8), ("reserved", ctypes.c_uint8 * 3)]


class timeval(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_long)]


class v4l2_timecode(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("flags", ctypes.c_uint32),
                ("frames", ctypes.c_uint8), ("seconds", ctypes.c_uint8),
                ("minutes", ctypes.c_uint8), ("hours", ctypes.c_uint8),
                ("userbits", ctypes.c_uint8 * 4)]


class _m_union(ctypes.Union):
    _fields_ = [("offset", ctypes.c_uint32), ("userptr", ctypes.c_ulong),
                ("planes", ctypes.c_void_p), ("fd", ctypes.c_int32)]


class v4l2_buffer(ctypes.Structure):
    _fields_ = [("index", ctypes.c_uint32), ("type", ctypes.c_uint32),
                ("bytesused", ctypes.c_uint32), ("flags", ctypes.c_uint32),
                ("field", ctypes.c_uint32), ("timestamp", timeval),
                ("timecode", v4l2_timecode), ("sequence", ctypes.c_uint32),
                ("memory", ctypes.c_uint32), ("m", _m_union),
                ("length", ctypes.c_uint32), ("reserved2", ctypes.c_uint32),
                ("request_fd", ctypes.c_int32)]


def _iowr(nr, size):
    return (3 << 30) | (size << 16) | (ord("V") << 8) | nr


def _iow(nr, size):
    return (1 << 30) | (size << 16) | (ord("V") << 8) | nr


VIDIOC_S_FMT = _iowr(5, ctypes.sizeof(v4l2_format))
VIDIOC_REQBUFS = _iowr(8, ctypes.sizeof(v4l2_requestbuffers))
VIDIOC_QUERYBUF = _iowr(9, ctypes.sizeof(v4l2_buffer))
VIDIOC_QBUF = _iowr(15, ctypes.sizeof(v4l2_buffer))
VIDIOC_DQBUF = _iowr(17, ctypes.sizeof(v4l2_buffer))
VIDIOC_STREAMON = _iow(18, ctypes.sizeof(ctypes.c_int))
VIDIOC_STREAMOFF = _iow(19, ctypes.sizeof(ctypes.c_int))


class V4L2Nv12Camera:
    """Minimal V4L2 mmap capture of NV12 frames."""

    def __init__(self, device, width, height, nbuf=4):
        self.fd = os.open(device, os.O_RDWR | os.O_NONBLOCK)
        fmt = v4l2_format()
        fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
        fmt.fmt.pix.width = width
        fmt.fmt.pix.height = height
        fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_NV12
        fmt.fmt.pix.field = V4L2_FIELD_NONE
        fcntl.ioctl(self.fd, VIDIOC_S_FMT, fmt)
        self.width, self.height = fmt.fmt.pix.width, fmt.fmt.pix.height
        self.stride = fmt.fmt.pix.bytesperline or self.width
        req = v4l2_requestbuffers()
        req.count, req.type, req.memory = nbuf, V4L2_BUF_TYPE_VIDEO_CAPTURE, V4L2_MEMORY_MMAP
        fcntl.ioctl(self.fd, VIDIOC_REQBUFS, req)
        self.maps = []
        for i in range(req.count):
            buf = self._buf(i)
            fcntl.ioctl(self.fd, VIDIOC_QUERYBUF, buf)
            self.maps.append(mmap.mmap(self.fd, buf.length, mmap.MAP_SHARED,
                                       mmap.PROT_READ | mmap.PROT_WRITE,
                                       offset=buf.m.offset))
            fcntl.ioctl(self.fd, VIDIOC_QBUF, buf)
        fcntl.ioctl(self.fd, VIDIOC_STREAMON, ctypes.c_int(V4L2_BUF_TYPE_VIDEO_CAPTURE))

    def _buf(self, index=0):
        buf = v4l2_buffer()
        buf.type, buf.memory, buf.index = V4L2_BUF_TYPE_VIDEO_CAPTURE, V4L2_MEMORY_MMAP, index
        return buf

    def read(self, timeout=2.0):
        """Return one NV12 frame as bytes (tightly packed, width x height*3/2)."""
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            raise TimeoutError("no frame from camera within %.1f s" % timeout)
        buf = self._buf()
        fcntl.ioctl(self.fd, VIDIOC_DQBUF, buf)
        try:
            m = self.maps[buf.index]
            w, h, s = self.width, self.height, self.stride
            if s == w:
                data = m[:w * h * 3 // 2]
            else:  # drop the row padding
                rows = h * 3 // 2
                data = b"".join(m[r * s:r * s + w] for r in range(rows))
        finally:
            fcntl.ioctl(self.fd, VIDIOC_QBUF, buf)
        return data

    def close(self):
        try:
            fcntl.ioctl(self.fd, VIDIOC_STREAMOFF, ctypes.c_int(V4L2_BUF_TYPE_VIDEO_CAPTURE))
        except OSError:
            pass
        for m in self.maps:
            m.close()
        os.close(self.fd)


class Nv12Letterbox:
    """Scale an NV12 frame into a size x size NV12 image, aspect ratio kept,
    centred on black (Y=0, U=V=128). All sizes and offsets are even so the
    half-resolution UV plane lines up with the Y plane."""

    def __init__(self, width, height, size):
        scale = min(size / width, size / height)
        self.w, self.h = width, height
        self.nw = max(2, int(width * scale) // 2 * 2)
        self.nh = max(2, int(height * scale) // 2 * 2)
        self.left = (size - self.nw) // 4 * 2
        self.top = (size - self.nh) // 4 * 2
        self.size = size
        self.out = np.empty(size * size * 3 // 2, np.uint8)
        self.out[:size * size] = 0      # Y: black
        self.out[size * size:] = 128    # UV: neutral
        self.y_out = self.out[:size * size].reshape(size, size)
        self.uv_out = self.out[size * size:].reshape(size // 2, size // 2, 2)

    def __call__(self, nv12):
        """nv12: tightly packed width x height*3/2 frame (bytes-like).
        Returns the letterboxed frame (a reused numpy buffer)."""
        w, h, nw, nh = self.w, self.h, self.nw, self.nh
        src = np.frombuffer(nv12, np.uint8)
        y = src[:w * h].reshape(h, w)
        uv = src[w * h:w * h * 3 // 2].reshape(h // 2, w // 2, 2)
        t, l = self.top, self.left
        self.y_out[t:t + nh, l:l + nw] = cv2.resize(
            y, (nw, nh), interpolation=cv2.INTER_LINEAR)
        self.uv_out[t // 2:(t + nh) // 2, l // 2:(l + nw) // 2] = cv2.resize(
            uv, (nw // 2, nh // 2), interpolation=cv2.INTER_LINEAR)
        return self.out


def _nv12_msg(stamp, frame_id, width, height, data):
    msg = Image()
    msg.header.stamp = stamp
    msg.header.frame_id = frame_id
    msg.height, msg.width = height, width
    msg.encoding = "nv12"
    msg.is_bigendian = 0
    msg.step = width
    # array('B') takes rclpy's fast path; plain bytes get checked
    # element by element (~0.6 s per frame at 960x544)
    buf = array.array("B")
    buf.frombytes(data)
    msg.data = buf
    return msg


class Imx708CamNode(Node):
    def __init__(self):
        super().__init__("imx708_cam")
        self.declare_parameter("device", "/dev/video8")
        self.declare_parameter("width", 960)
        self.declare_parameter("height", 544)
        self.declare_parameter("topic", "/image_raw")
        self.declare_parameter("yolo_topic", "")
        self.declare_parameter("yolo_size", 640)
        self.declare_parameter("frame_id", "camera")
        self.declare_parameter("log_fps", True)
        p = lambda n: self.get_parameter(n).value  # noqa: E731
        self.frame_id, self.log_fps = p("frame_id"), p("log_fps")
        self.device = p("device")
        self.cam = V4L2Nv12Camera(self.device, p("width"), p("height"))
        self.pub = self.create_publisher(Image, p("topic"), 5)
        self.get_logger().info(
            "IMX708 %s -> %s: %dx%d NV12 (stride %d)" % (
                p("device"), p("topic"), self.cam.width, self.cam.height, self.cam.stride))
        self.yolo_pub = self.letterbox = None
        if p("yolo_topic"):
            size = p("yolo_size")
            self.letterbox = Nv12Letterbox(self.cam.width, self.cam.height, size)
            self.yolo_pub = self.create_publisher(Image, p("yolo_topic"), 5)
            lb = self.letterbox
            self.get_logger().info(
                "letterbox -> %s: %dx%d NV12 (picture %dx%d at x=%d y=%d)" % (
                    p("yolo_topic"), size, size, lb.nw, lb.nh, lb.left, lb.top))
        self.count, self.t_last = 0, time.monotonic()

    def spin_capture(self):
        timeout = 10.0  # the X5 pipeline needs a moment for the first frame
        while rclpy.ok():
            try:
                data = self.cam.read(timeout)
            except TimeoutError as e:
                self.get_logger().error(
                    "%s - check 'sudo dmesg | grep -E \"imx708|341d0000\"': "
                    "'controller timed out' / 'Failed to write reg' means the sensor "
                    "holds its I2C bus; only a power cut (unplug ~10 s) clears it. "
                    "No I2C errors: another program opened %s (e.g. v4l2-ctl), "
                    "which stops the stream; restart this node" % (e, self.device))
                raise SystemExit(1)
            timeout = 2.0
            stamp = self.get_clock().now().to_msg()
            if not rclpy.ok():
                break
            # both topics carry the same stamp, so detections made on the
            # letterboxed image can be matched to the full frame
            if self.pub.get_subscription_count():
                self.pub.publish(_nv12_msg(stamp, self.frame_id, self.cam.width,
                                           self.cam.height, data))
            if self.yolo_pub and self.yolo_pub.get_subscription_count():
                s = self.letterbox.size
                self.yolo_pub.publish(_nv12_msg(stamp, self.frame_id, s, s,
                                                self.letterbox(data)))
            self.count += 1
            now = time.monotonic()
            if self.log_fps and now - self.t_last >= 5.0:
                self.get_logger().info("camera %.1f fps" % (self.count / (now - self.t_last)))
                self.count, self.t_last = 0, now

    def destroy_node(self):
        self.cam.close()
        super().destroy_node()


def _interrupt(signum, frame):
    raise KeyboardInterrupt


def main():
    rclpy.init()
    # Own handlers for SIGINT and SIGTERM, so the node always stops the stream
    # and exits. rclpy's handler only chains to the previous Python handler,
    # and a process started in the background of a non-interactive shell
    # (nohup ... &) inherits SIGINT as ignored - then nothing would stop it.
    signal.signal(signal.SIGINT, _interrupt)
    signal.signal(signal.SIGTERM, _interrupt)
    node = Imx708CamNode()
    try:
        node.spin_capture()
    except KeyboardInterrupt:
        pass
    except Exception:
        if rclpy.ok():  # a real error, not a shutdown (Ctrl-C / SIGTERM)
            raise
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
