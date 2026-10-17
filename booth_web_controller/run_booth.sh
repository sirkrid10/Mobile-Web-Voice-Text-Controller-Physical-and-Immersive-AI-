#!/usr/bin/env bash
# Start the booth controller with local or robot ROS discovery settings.

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

# Explicit shell environment wins over values loaded from .env. Profile defaults
# are applied only after both configuration sources have been read.
declare -A SAVED_ENV=()
CONFIG_KEYS=(
    ROS_PROFILE ROS_DOMAIN_ID RMW_IMPLEMENTATION ROS_AUTOMATIC_DISCOVERY_RANGE
    ROS_DISCOVERY_SERVER ROBOT_SUPER_CLIENT_XML ROS_WORKSPACE_SETUP
    HOST PORT USE_MOCK_ROS2
)
for key in "${CONFIG_KEYS[@]}"; do
    if [[ -v "$key" ]]; then
        SAVED_ENV["$key"]="${!key}"
    fi
done

if [ -f "${SCRIPT_DIR}/.env" ]; then
    echo "[Booth Controller] Loading configuration from .env"
    set -a
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/.env"
    set +a
fi

for key in "${!SAVED_ENV[@]}"; do
    export "${key}=${SAVED_ENV[$key]}"
done

ROS_PROFILE="${ROS_PROFILE:-local}"
USE_MOCK_ROS2="${USE_MOCK_ROS2:-false}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

if [[ "${USE_MOCK_ROS2,,}" != "true" ]]; then
    if [ ! -f "/opt/ros/jazzy/setup.bash" ]; then
        echo "[Booth Controller] ROS 2 Jazzy is required unless USE_MOCK_ROS2=true." >&2
        exit 1
    fi
    # shellcheck disable=SC1091
    source "/opt/ros/jazzy/setup.bash"

    ROS_WORKSPACE_SETUP="${ROS_WORKSPACE_SETUP:-${SCRIPT_DIR}/../../turtlebot-llm/install-colcon/setup.bash}"
    if [ -f "${ROS_WORKSPACE_SETUP}" ]; then
        echo "[Booth Controller] Sourcing ai_interfaces workspace: ${ROS_WORKSPACE_SETUP}"
        # shellcheck disable=SC1090
        source "${ROS_WORKSPACE_SETUP}"
    fi
fi

export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
case "${ROS_PROFILE}" in
    local)
        export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-83}"
        export ROS_AUTOMATIC_DISCOVERY_RANGE="${ROS_AUTOMATIC_DISCOVERY_RANGE:-LOCALHOST}"
        unset ROS_DISCOVERY_SERVER FASTRTPS_DEFAULT_PROFILES_FILE FASTDDS_DEFAULT_PROFILES_FILE
        ;;
    robot)
        export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-30}"
        export ROS_AUTOMATIC_DISCOVERY_RANGE="${ROS_AUTOMATIC_DISCOVERY_RANGE:-SUBNET}"
        export ROS_DISCOVERY_SERVER="${ROS_DISCOVERY_SERVER:-192.168.1.17:11811}"
        ROBOT_SUPER_CLIENT_XML="${ROBOT_SUPER_CLIENT_XML:-}"
        if [[ -z "${ROBOT_SUPER_CLIENT_XML}" || ! -r "${ROBOT_SUPER_CLIENT_XML}" ]]; then
            echo "[Booth Controller] robot profile requires readable ROBOT_SUPER_CLIENT_XML." >&2
            exit 1
        fi
        if ! python3 - "${ROBOT_SUPER_CLIENT_XML}" <<'PY'
import sys
import xml.etree.ElementTree as ET

try:
    root = ET.parse(sys.argv[1]).getroot()
except (OSError, ET.ParseError) as exc:
    raise SystemExit(f"Invalid SUPER_CLIENT XML: {exc}")

if "SUPER_CLIENT" not in ET.tostring(root, encoding="unicode"):
    raise SystemExit("SUPER_CLIENT profile is missing from XML")
PY
        then
            exit 1
        fi
        export FASTRTPS_DEFAULT_PROFILES_FILE="${ROBOT_SUPER_CLIENT_XML}"
        export FASTDDS_DEFAULT_PROFILES_FILE="${ROBOT_SUPER_CLIENT_XML}"
        ;;
    *)
        echo "[Booth Controller] ROS_PROFILE must be local or robot (got '${ROS_PROFILE}')." >&2
        exit 1
        ;;
esac

if [[ "${USE_MOCK_ROS2,,}" == "true" ]]; then
    export USE_MOCK_ROS2=true
else
    export USE_MOCK_ROS2=false
fi

if [ -f "${HOME}/booth_web_venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "${HOME}/booth_web_venv/bin/activate"
elif [ -f "${SCRIPT_DIR}/booth_web_venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/booth_web_venv/bin/activate"
elif [ -f "${SCRIPT_DIR}/venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/venv/bin/activate"
fi

if [[ "${USE_MOCK_ROS2}" != "true" ]]; then
    if ! python3 - <<'PY'
try:
    import rclpy
    from ai_interfaces.action import GuideToDestination
    from ai_interfaces.msg import IntentResult
except ImportError as exc:
    raise SystemExit(f"ROS backend imports unavailable: {exc}")

if "valid_until" not in GuideToDestination.Goal.get_fields_and_field_types():
    raise SystemExit("GuideToDestination.Goal is stale: valid_until is missing")
PY
    then
        echo "[Booth Controller] Real ROS mode needs current ai_interfaces; source the rebuilt workspace." >&2
        exit 1
    fi
fi

echo "[Booth Controller] Profile=${ROS_PROFILE}, ROS_DOMAIN_ID=${ROS_DOMAIN_ID}"
echo "[Booth Controller] Binding server to http://${HOST}:${PORT}"
echo "[Booth Controller] Visitor UI: http://localhost:${PORT}/"
echo "[Booth Controller] Staff Panel: http://localhost:${PORT}/staff"

export PYTHONPATH="${PYTHONPATH:+${PYTHONPATH}:}${SCRIPT_DIR}"
exec python3 -m uvicorn app.main:app --host "${HOST}" --port "${PORT}" --reload
