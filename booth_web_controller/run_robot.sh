#!/usr/bin/env bash
# Start the Backend on the same real Robot profile as turtlebot-llm/run_robot.sh.
set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == --help || "${1:-}" == -h || $# -gt 1 ]]; then
    echo "Usage: bash $0 [current-robot-vm-ip]"
    [[ $# -le 1 ]]
    exit
fi
if [[ $# == 1 ]]; then
    export TURTLEBOT_ROBOT_IP="$1"
fi

# Recompute ROS settings through the shared robot setup even from a local shell.
unset ROS_DOMAIN_ID ROS_AUTOMATIC_DISCOVERY_RANGE ROS_DISCOVERY_SERVER
unset FASTRTPS_DEFAULT_PROFILES_FILE FASTDDS_DEFAULT_PROFILES_FILE
unset ROS_LOCALHOST_ONLY ROS_STATIC_PEERS FASTDDS_BUILTIN_TRANSPORTS
export ROS_PROFILE=robot USE_MOCK_ROS2=false
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export TURTLEBOT_START_ROS_DAEMON=0
exec bash "${SCRIPT_DIR}/run_booth.sh"
