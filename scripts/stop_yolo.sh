#!/bin/bash
# Stop the IMX708 YOLO demo started with imx708_yolo.launch.py.
#
#   scripts/stop_yolo.sh           # stop ros2 launch and its nodes
#   scripts/stop_yolo.sh --nginx   # also stop the nginx web server (port 8000)
#
# Ctrl-C on a foreground `ros2 launch` is enough. This script is for a launch
# that runs in the background or in another session: it sends SIGINT to
# `ros2 launch` (which forwards it to the nodes), then SIGINT / SIGTERM /
# SIGKILL to whatever is left. Do not stop a launch with SIGTERM alone:
# ros2 launch then exits at once and leaves its nodes running as orphans.
#
# Note: it matches the TogetheROS processes by name, so it also stops
# hobot_codec / dnn_node_example / websocket instances from other launches.
# nginx is left running by default; the websocket launch reuses it.

# Anchored to the start of the command line, so a shell whose command text
# merely mentions these names (e.g. `ssh board 'ros2 launch ...'`) is not hit.
launch='^[^ ]*python3? [^ ]*/ros2 launch .*imx708_yolo\.launch\.py'
nodes='^[^ ]*python3? [^ ]*imx708_cam_node\.py|^[^ ]*/(dnn_node_example/example|hobot_codec/hobot_codec_republish|websocket/websocket)( |$)'

wait_gone() {  # wait_gone <pattern> <seconds>
    local i
    for ((i = 0; i < $2 * 2; i++)); do
        pgrep -f "$1" >/dev/null || return 0
        sleep 0.5
    done
    return 1
}

if pgrep -f "$launch" >/dev/null; then
    echo "stopping ros2 launch ..."
    pkill -INT -f "$launch"
    wait_gone "$launch|$nodes" 10
fi
for sig in INT TERM KILL; do
    pgrep -f "$nodes" >/dev/null || break
    echo "sending SIG$sig to leftover nodes:"
    pgrep -af "$nodes" | cut -c1-100
    pkill -$sig -f "$nodes"
    wait_gone "$nodes" 5
done
# a launch with no nodes left can be ended with SIGTERM (it ignores SIGINT
# when it was started with `nohup ... &` from a script)
if pgrep -f "$launch" >/dev/null; then
    pkill -TERM -f "$launch"
    wait_gone "$launch" 5 || pkill -KILL -f "$launch"
fi

if [ "$1" = "--nginx" ]; then
    pkill -QUIT -f '^nginx: master process \./sbin/nginx -p \.' && echo "nginx stopped"
fi

if pgrep -af "$launch|$nodes"; then
    echo "some processes are still running (see above)"
    exit 1
fi
echo "demo stopped"
