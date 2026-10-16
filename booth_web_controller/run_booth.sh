#!/usr/bin/env bash
# ==============================================================================
# Startup Script: Mobile Web Voice & Text Controller
# Target: WSL 2 Ubuntu 24.04 LTS + ROS 2 Jazzy
# ==============================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "[Booth Controller] Starting Mobile Web Voice & Text Controller..."

# 1. Source ROS 2 Jazzy if present
if [ -f "/opt/ros/jazzy/setup.bash" ]; then
    echo "[Booth Controller] Sourcing ROS 2 Jazzy environment (/opt/ros/jazzy/setup.bash)..."
    # shellcheck disable=SC1091
    source "/opt/ros/jazzy/setup.bash"
else
    echo "[Booth Controller] ROS 2 Jazzy not found in /opt/ros/jazzy. Running in standalone Mock ROS 2 mode."
fi

# 2. Source Python Virtual Environment
if [ -f "${HOME}/booth_web_venv/bin/activate" ]; then
    echo "[Booth Controller] Activating virtual environment: ${HOME}/booth_web_venv"
    # shellcheck disable=SC1091
    source "${HOME}/booth_web_venv/bin/activate"
elif [ -f "${SCRIPT_DIR}/booth_web_venv/bin/activate" ]; then
    echo "[Booth Controller] Activating local virtual environment: ${SCRIPT_DIR}/booth_web_venv"
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/booth_web_venv/bin/activate"
elif [ -f "${SCRIPT_DIR}/venv/bin/activate" ]; then
    echo "[Booth Controller] Activating local virtual environment: ${SCRIPT_DIR}/venv"
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/venv/bin/activate"
else
    echo "[Booth Controller] No virtual environment found. Using system Python: $(which python3)"
fi

# 3. Load Environment Variables from .env if present
if [ -f "${SCRIPT_DIR}/.env" ]; then
    echo "[Booth Controller] Loading configuration from .env"
    set -a
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/.env"
    set +a
elif [ -f "${SCRIPT_DIR}/.env.example" ]; then
    echo "[Booth Controller] .env not found. Copying defaults from .env.example -> .env"
    cp "${SCRIPT_DIR}/.env.example" "${SCRIPT_DIR}/.env"
    set -a
    # shellcheck disable=SC1091
    source "${SCRIPT_DIR}/.env"
    set +a
fi

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

echo "[Booth Controller] Binding server to http://${HOST}:${PORT}"
echo "[Booth Controller] Visitor UI: http://localhost:${PORT}/"
echo "[Booth Controller] Staff Panel: http://localhost:${PORT}/staff"

export PYTHONPATH="${PYTHONPATH}:${SCRIPT_DIR}"

exec python3 -m uvicorn app.main:app --host "${HOST}" --port "${PORT}" --reload
