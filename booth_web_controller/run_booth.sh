#!/usr/bin/env bash
# Start the booth controller with the shared TurtleBot ROS setup.

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

declare -A SHELL_OVERRIDES=()
declare -A CONFIG_VALUES=()
CONFIG_KEYS=(
    ROS_PROFILE ROS_DOMAIN_ID RMW_IMPLEMENTATION ROS_AUTOMATIC_DISCOVERY_RANGE
    ROS_DISCOVERY_SERVER FASTRTPS_DEFAULT_PROFILES_FILE FASTDDS_DEFAULT_PROFILES_FILE
    ROS_WORKSPACE_SETUP ROBOT_SUPER_CLIENT_XML TURTLEBOT_SETUP_SCRIPT
    TURTLEBOT_FASTDDS_PROFILE TURTLEBOT_ROBOT_HOST TURTLEBOT_ROBOT_IP
    HOST PORT USE_MOCK_ROS2
)
for key in "${CONFIG_KEYS[@]}"; do
    if [[ -v "$key" ]]; then
        SHELL_OVERRIDES["$key"]="${!key}"
    fi
done

if [ -f "${SCRIPT_DIR}/.env" ]; then
    echo "[Booth Controller] Loading configuration from .env"
    set -a
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/.env"
    set +a
fi
for key in "${!SHELL_OVERRIDES[@]}"; do
    export "${key}=${SHELL_OVERRIDES[$key]}"
done
for key in "${CONFIG_KEYS[@]}"; do
    if [[ -v "$key" ]]; then
        CONFIG_VALUES["$key"]="${!key}"
    fi
done

ROS_PROFILE="${ROS_PROFILE:-local}"
USE_MOCK_ROS2="${USE_MOCK_ROS2:-false}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

fail() {
    echo "[Booth Controller] ERROR: $*" >&2
    exit 1
}

if [[ -n "${ROBOT_SUPER_CLIENT_XML:-}" && -n "${TURTLEBOT_FASTDDS_PROFILE:-}" \
    && "${ROBOT_SUPER_CLIENT_XML}" != "${TURTLEBOT_FASTDDS_PROFILE}" ]]; then
    fail "ROBOT_SUPER_CLIENT_XML conflicts with TURTLEBOT_FASTDDS_PROFILE. Set only one value or make them identical."
fi
if [[ -z "${TURTLEBOT_FASTDDS_PROFILE:-}" && -n "${ROBOT_SUPER_CLIENT_XML:-}" ]]; then
    TURTLEBOT_FASTDDS_PROFILE="${ROBOT_SUPER_CLIENT_XML}"
    export TURTLEBOT_FASTDDS_PROFILE
fi
if [[ -n "${FASTRTPS_DEFAULT_PROFILES_FILE:-}" && -n "${FASTDDS_DEFAULT_PROFILES_FILE:-}" \
    && "${FASTRTPS_DEFAULT_PROFILES_FILE}" != "${FASTDDS_DEFAULT_PROFILES_FILE}" ]]; then
    fail "FASTRTPS_DEFAULT_PROFILES_FILE conflicts with FASTDDS_DEFAULT_PROFILES_FILE."
fi

if [[ "${USE_MOCK_ROS2,,}" != "true" ]]; then
    [[ "${ROS_PROFILE}" == local || "${ROS_PROFILE}" == robot ]] \
        || fail "ROS_PROFILE must be local or robot (got '${ROS_PROFILE}')."

    TURTLEBOT_SETUP_SCRIPT="${TURTLEBOT_SETUP_SCRIPT:-${SCRIPT_DIR}/../../turtlebot-llm/setup_demo_auto_ip.sh}"
    [[ -r "${TURTLEBOT_SETUP_SCRIPT}" ]] || fail "Shared TurtleBot setup is not readable: ${TURTLEBOT_SETUP_SCRIPT}"
    TURTLEBOT_SETUP_SCRIPT="$(realpath "${TURTLEBOT_SETUP_SCRIPT}")"
    SHARED_WORKSPACE="$(cd "$(dirname "${TURTLEBOT_SETUP_SCRIPT}")" && pwd)"
    SHARED_SETUP="${SHARED_WORKSPACE}/install-colcon/setup.bash"
    if [[ -n "${ROS_WORKSPACE_SETUP:-}" ]]; then
        requested_workspace="$(realpath -m "${ROS_WORKSPACE_SETUP}")"
        expected_workspace="$(realpath -m "${SHARED_SETUP}")"
        [[ "${requested_workspace}" == "${expected_workspace}" ]] \
            || fail "ROS_WORKSPACE_SETUP points to another workspace (${ROS_WORKSPACE_SETUP}); the shared setup owns ${SHARED_SETUP}."
    fi
    if [[ "${ROS_PROFILE}" == robot && -z "${TURTLEBOT_FASTDDS_PROFILE:-}" ]]; then
        TURTLEBOT_FASTDDS_PROFILE="${SHARED_WORKSPACE}/config/super_client_configuration_file.xml"
        export TURTLEBOT_FASTDDS_PROFILE
    fi

    source_status=0
    # shellcheck disable=SC1090
    source "${TURTLEBOT_SETUP_SCRIPT}" "${ROS_PROFILE}" || source_status=$?
    cd "${SCRIPT_DIR}"
    [[ "${source_status}" == 0 ]] || fail "Shared TurtleBot setup failed for profile '${ROS_PROFILE}'."

    expected_domain=83
    expected_discovery=LOCALHOST
    if [[ "${ROS_PROFILE}" == robot ]]; then
        expected_domain=30
        expected_discovery=SUBNET
    fi
    [[ "${ROS_DOMAIN_ID:-}" == "${expected_domain}" ]] \
        || fail "Shared profile '${ROS_PROFILE}' selected ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-unset}; expected ${expected_domain}."
    [[ "${ROS_AUTOMATIC_DISCOVERY_RANGE:-}" == "${expected_discovery}" ]] \
        || fail "Shared profile '${ROS_PROFILE}' selected ROS_AUTOMATIC_DISCOVERY_RANGE=${ROS_AUTOMATIC_DISCOVERY_RANGE:-unset}; expected ${expected_discovery}."
    [[ "${RMW_IMPLEMENTATION:-}" == "rmw_fastrtps_cpp" ]] \
        || fail "Shared profile '${ROS_PROFILE}' selected RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-unset}; expected rmw_fastrtps_cpp."

    if [[ "${ROS_PROFILE}" == local ]]; then
        [[ -z "${ROS_DISCOVERY_SERVER:-}" ]] || fail "Local profile unexpectedly enables ROS_DISCOVERY_SERVER=${ROS_DISCOVERY_SERVER}."
        [[ -z "${FASTDDS_DEFAULT_PROFILES_FILE:-}${FASTRTPS_DEFAULT_PROFILES_FILE:-}" ]] \
            || fail "Local profile unexpectedly selects a Fast DDS XML profile."
        [[ -z "${TURTLEBOT_FASTDDS_PROFILE:-}${ROBOT_SUPER_CLIENT_XML:-}" ]] \
            || fail "Fast DDS XML overrides are only valid with ROS_PROFILE=robot."
    else
        [[ "${ROS_DISCOVERY_SERVER:-}" == *:11811 ]] \
            || fail "Robot profile did not select a Discovery Server on port 11811."
        [[ -n "${TURTLEBOT_FASTDDS_PROFILE:-}" && -r "${TURTLEBOT_FASTDDS_PROFILE}" ]] \
            || fail "Robot profile requires readable TURTLEBOT_FASTDDS_PROFILE."
        [[ "${FASTRTPS_DEFAULT_PROFILES_FILE:-}" == "${TURTLEBOT_FASTDDS_PROFILE}" \
            && "${FASTDDS_DEFAULT_PROFILES_FILE:-}" == "${TURTLEBOT_FASTDDS_PROFILE}" ]] \
            || fail "Robot profile's effective Fast DDS XML does not match TURTLEBOT_FASTDDS_PROFILE."
    fi

    for key in ROS_DOMAIN_ID RMW_IMPLEMENTATION ROS_AUTOMATIC_DISCOVERY_RANGE ROS_DISCOVERY_SERVER \
        FASTRTPS_DEFAULT_PROFILES_FILE FASTDDS_DEFAULT_PROFILES_FILE; do
        if [[ -v "CONFIG_VALUES[$key]" && "${CONFIG_VALUES[$key]}" != "${!key-}" ]]; then
            fail "Explicit ${key}=${CONFIG_VALUES[$key]} conflicts with shared profile value ${!key-unset}."
        fi
    done

    if [[ "${USE_MOCK_ROS2,,}" != "true" ]]; then
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
            fail "Real ROS mode needs current ai_interfaces; shared setup is missing or stale."
        fi
    fi
    export USE_MOCK_ROS2=false
else
    export USE_MOCK_ROS2=true
    echo "[Booth Controller] USE_MOCK_ROS2=true; skipping ROS setup."
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

export HOST PORT
export PYTHONPATH="${PYTHONPATH:+${PYTHONPATH}:}${SCRIPT_DIR}"
echo "[Booth Controller] Profile=${ROS_PROFILE}, USE_MOCK_ROS2=${USE_MOCK_ROS2}"
echo "[Booth Controller] Binding server to http://${HOST}:${PORT}"
echo "[Booth Controller] Visitor UI: http://localhost:${PORT}/"
echo "[Booth Controller] Staff Panel: http://localhost:${PORT}/staff"
exec python3 -m uvicorn app.main:app --host "${HOST}" --port "${PORT}" --reload
