# IMX708 camera -> YOLO on the BPU -> browser at http://<board-ip>:8000
#
#   source /opt/tros/humble/setup.bash
#   ros2 launch ~/imx708_ros/imx708_yolo.launch.py                 # camera + YOLOv8
#   ros2 launch ~/imx708_ros/imx708_yolo.launch.py yolo:=false     # camera only
#   ros2 launch ~/imx708_ros/imx708_yolo.launch.py config:=yolov11workconfig.json
#
# Pipeline:
#   imx708_cam (/dev/video8, NV12)  -> /image_raw        sensor_msgs/Image nv12 (width x height)
#                                   -> /image_yolo       640x640 nv12, letterboxed (yolo:=true)
#   hobot_codec (JPU, nv12 -> jpeg) -> /image_jpeg       from /image_yolo (or /image_raw if yolo:=false)
#   dnn_node_example (BPU, YOLO)    -> /hobot_dnn_detection  ai_msgs/PerceptionTargets
#   websocket (port 8000)           shows /image_jpeg + the detection boxes
#
# Why /image_yolo: dnn_node_example resizes NV12 input that is not already the
# model size with the VSE through the HBN stack, which is not loaded in V4L2
# mode ("Resize nv12 img fail!"). A 640x640 input skips that resize, and its
# detections (in 640x640 pixels) line up with the image shown in the browser.
import os

from ament_index_python import get_package_prefix, get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, ExecuteProcess,
                            IncludeLaunchDescription)
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node

HERE = os.path.dirname(os.path.abspath(__file__))


def _include(pkg, launch_file, args, condition=None):
    return IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(get_package_share_directory(pkg), "launch", launch_file)),
        launch_arguments=args.items(), condition=condition)


def _codec(sub_topic, condition):
    return _include("hobot_codec", "hobot_codec_encode.launch.py", {
        "codec_in_mode": "ros", "codec_in_format": "nv12",
        "codec_sub_topic": sub_topic,
        "codec_out_mode": "ros", "codec_out_format": "jpeg",
        "codec_pub_topic": "/image_jpeg"}, condition)


def generate_launch_description():
    dnn_dir = os.path.join(get_package_prefix("dnn_node_example"), "lib", "dnn_node_example")
    yolo = LaunchConfiguration("yolo")
    yolo_img = "/image_yolo"
    det_topic = "/hobot_dnn_detection"

    return LaunchDescription([
        DeclareLaunchArgument("yolo", default_value="true",
                              description="run YOLO detection on the BPU"),
        DeclareLaunchArgument("config", default_value="yolov8workconfig.json",
                              description="dnn_node_example config in its config/ folder"),
        DeclareLaunchArgument("width", default_value="960"),
        DeclareLaunchArgument("height", default_value="544"),

        # camera: V4L2 /dev/video8 -> /image_raw (nv12)
        ExecuteProcess(
            name="imx708_cam",
            cmd=["python3", os.path.join(HERE, "imx708_cam_node.py"), "--ros-args",
                 "-p", ["width:=", LaunchConfiguration("width")],
                 "-p", ["height:=", LaunchConfiguration("height")],
                 "-p", "topic:=/image_raw",
                 "-p", "yolo_topic:=" + yolo_img,
                 "-p", "yolo_size:=640"],
            output="screen"),

        # nv12 -> jpeg on the hardware encoder, for the browser
        _codec(yolo_img, IfCondition(yolo)),
        _codec("/image_raw", UnlessCondition(yolo)),

        # YOLO on the BPU (the official TogetheROS example), fed from /image_yolo
        Node(
            package="dnn_node_example", executable="example", name="dnn_example",
            cwd=dnn_dir, output="screen", condition=IfCondition(yolo),
            parameters=[{
                "feed_type": 1,
                "is_shared_mem_sub": 0,
                "ros_img_topic_name": yolo_img,
                "config_file": PathJoinSubstitution(["config", LaunchConfiguration("config")]),
                "msg_pub_topic_name": det_topic,
                "dump_render_img": 0}],
            arguments=["--ros-args", "--log-level", "warn"]),

        # web view at http://<board-ip>:8000
        _include("websocket", "websocket.launch.py", {
            "websocket_image_topic": "/image_jpeg",
            "websocket_image_type": "mjpeg",
            "websocket_smart_topic": det_topic}, condition=IfCondition(yolo)),
        _include("websocket", "websocket.launch.py", {
            "websocket_image_topic": "/image_jpeg",
            "websocket_image_type": "mjpeg",
            "websocket_only_show_image": "true"}, condition=UnlessCondition(yolo)),
    ])
