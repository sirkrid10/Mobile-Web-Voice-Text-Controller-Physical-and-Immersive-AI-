#!/usr/bin/env bash
set -eo pipefail

SOURCE_SCRIPT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/run_booth.sh}"
TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "${TEST_ROOT}"' EXIT
BACKEND="${TEST_ROOT}/ros2_ws/Mobile-Web-Voice-Text-Controller-Physical-and-Immersive-AI-/booth_web_controller"
FAKE_HOME="${TEST_ROOT}/home"
FAKE_BIN="${TEST_ROOT}/bin"
SHARED_SCRIPT="${TEST_ROOT}/ros2_ws/turtlebot-llm/setup_demo_auto_ip.sh"
PROFILE_XML="${TEST_ROOT}/ros2_ws/turtlebot-llm/config/super_client.xml"
SHARED_LOG="${TEST_ROOT}/shared.log"
SERVER_LOG="${TEST_ROOT}/server.log"

mkdir -p "${BACKEND}" "${FAKE_HOME}/booth_web_venv/bin" "${FAKE_BIN}" "$(dirname "${PROFILE_XML}")"
cp "${SOURCE_SCRIPT}" "${BACKEND}/run_booth.sh"
cat >"${BACKEND}/.env" <<'EOF'
HOST=127.0.0.1
PORT=8123
USE_MOCK_ROS2=false
ROS_PROFILE=local
EOF
cat >"${PROFILE_XML}" <<'EOF'
<profiles><profile><discoveryProtocol>SUPER_CLIENT</discoveryProtocol></profile></profiles>
EOF
cat >"${FAKE_HOME}/booth_web_venv/bin/activate" <<'EOF'
export PATH="${TEST_BIN}:$PATH"
EOF
cat >"${FAKE_BIN}/python3" <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-}" == "-" ]]; then
    cat >/dev/null
    exit 0
fi
{
    printf 'cwd=%s\n' "$PWD"
    printf 'args=%s\n' "$*"
    printf 'profile=%s\n' "${ROS_PROFILE:-}"
    printf 'mock=%s\n' "${USE_MOCK_ROS2:-}"
    printf 'managed=%s\n' "${MANAGE_AGENT_NODES:-}"
    printf 'workspace=%s\n' "${AGENT_WORKSPACE:-}"
    printf 'domain=%s\n' "${ROS_DOMAIN_ID:-}"
    printf 'discovery=%s\n' "${ROS_AUTOMATIC_DISCOVERY_RANGE:-}"
    printf 'server=%s\n' "${ROS_DISCOVERY_SERVER:-}"
    printf 'fastdds=%s\n' "${FASTDDS_DEFAULT_PROFILES_FILE:-}"
} >"${SERVER_LOG}"
EOF
chmod +x "${FAKE_BIN}/python3"
cat >"${SHARED_SCRIPT}" <<'EOF'
#!/usr/bin/env bash
printf 'profile=%s cwd_before=%s\n' "$1" "$PWD" >>"${SHARED_LOG}"
cd /tmp
export PATH="${TEST_BIN}:$PATH"
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
case "$1" in
    local)
        export ROS_DOMAIN_ID=83 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST FASTDDS_BUILTIN_TRANSPORTS=UDPv4
        unset ROS_DISCOVERY_SERVER FASTRTPS_DEFAULT_PROFILES_FILE FASTDDS_DEFAULT_PROFILES_FILE
        ;;
    robot)
        export ROS_DOMAIN_ID=30 ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
        export ROS_DISCOVERY_SERVER="${TURTLEBOT_ROBOT_IP:-10.0.0.2}:11811"
        export FASTRTPS_DEFAULT_PROFILES_FILE="${TURTLEBOT_FASTDDS_PROFILE}"
        export FASTDDS_DEFAULT_PROFILES_FILE="${TURTLEBOT_FASTDDS_PROFILE}"
        ;;
    *) return 2 ;;
esac
EOF

run_launcher() {
    env HOME="${FAKE_HOME}" TEST_BIN="${FAKE_BIN}" SHARED_LOG="${SHARED_LOG}" SERVER_LOG="${SERVER_LOG}" \
        "$@" bash "${BACKEND}/run_booth.sh"
}
expect_failure() {
    rm -f "${SERVER_LOG}"
    if run_launcher "$@" >/dev/null 2>&1; then
        echo "expected launcher failure" >&2
        exit 1
    fi
    [[ ! -f "${SERVER_LOG}" ]] || { echo "server started after failed setup" >&2; exit 1; }
}

# Shared setup applies local defaults, then launcher returns to Backend before uvicorn.
rm -f "${SHARED_LOG}" "${SERVER_LOG}"
run_launcher HOST=127.0.0.2 PORT=8124
grep -q 'profile=local' "${SHARED_LOG}"
grep -q "cwd=${BACKEND}" "${SERVER_LOG}"
grep -q 'domain=83' "${SERVER_LOG}"
grep -q 'discovery=LOCALHOST' "${SERVER_LOG}"
grep -q 'mock=false' "${SERVER_LOG}"
grep -q -- '--host 127.0.0.2 --port 8124' "${SERVER_LOG}"
grep -q 'managed=true' "${SERVER_LOG}"
if grep -q -- '--reload' "${SERVER_LOG}"; then exit 1; fi
run_launcher MANAGE_AGENT_NODES=false
grep -q 'managed=false' "${SERVER_LOG}"
grep -q -- '--reload' "${SERVER_LOG}"

# Robot mode maps the legacy XML name and passes the dynamic profile values through.
rm -f "${SERVER_LOG}"
env HOME="${FAKE_HOME}" TEST_BIN="${FAKE_BIN}" SHARED_LOG="${SHARED_LOG}" SERVER_LOG="${SERVER_LOG}" \
    ROS_PROFILE=robot ROBOT_SUPER_CLIENT_XML="${PROFILE_XML}" TURTLEBOT_ROBOT_IP=10.2.3.4 \
    bash "${BACKEND}/run_booth.sh"
grep -q 'domain=30' "${SERVER_LOG}"
grep -q 'discovery=SUBNET' "${SERVER_LOG}"
grep -q 'server=10.2.3.4:11811' "${SERVER_LOG}"
grep -q "fastdds=${PROFILE_XML}" "${SERVER_LOG}"

# Mock mode does not need the ROS setup script or ROS variables.
rm -f "${SERVER_LOG}"
env HOME="${FAKE_HOME}" TEST_BIN="${FAKE_BIN}" SHARED_LOG="${SHARED_LOG}" SERVER_LOG="${SERVER_LOG}" \
    USE_MOCK_ROS2=true TURTLEBOT_SETUP_SCRIPT="${TEST_ROOT}/missing-setup.sh" bash "${BACKEND}/run_booth.sh"
grep -q 'mock=true' "${SERVER_LOG}"
grep -q 'managed=false' "${SERVER_LOG}"

expect_failure TURTLEBOT_SETUP_SCRIPT="${TEST_ROOT}/missing-setup.sh"
expect_failure ROS_PROFILE=invalid
expect_failure ROS_DOMAIN_ID=179
expect_failure ROS_WORKSPACE_SETUP="${TEST_ROOT}/another/setup.bash"
expect_failure AGENT_WORKSPACE="${TEST_ROOT}/another"
expect_failure ROBOT_SUPER_CLIENT_XML="${PROFILE_XML}"
expect_failure ROS_PROFILE=robot ROBOT_SUPER_CLIENT_XML="${PROFILE_XML}" TURTLEBOT_FASTDDS_PROFILE="${TEST_ROOT}/other.xml"

if grep -q '192\.168\.1\.17' "${BACKEND}/run_booth.sh" "${BACKEND}/.env"; then
    echo "legacy Discovery Server address remains in launcher configuration" >&2
    exit 1
fi

echo "run_booth smoke tests passed"
