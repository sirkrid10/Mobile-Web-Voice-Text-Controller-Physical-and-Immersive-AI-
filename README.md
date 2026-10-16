# Mobile Web Voice & Text Controller
### Physical and Immersive AI (TurtleBot3 + ROS 2 Nav2 + LLM + VR Robot-Mind View)

[![Target OS](https://img.shields.io/badge/OS-WSL2_Ubuntu_24.04_LTS-orange.svg)](https://ubuntu.com/)
[![ROS 2](https://img.shields.io/badge/ROS2-Jazzy_Jalisco-blue.svg)](https://docs.ros.org/en/jazzy/)
[![Backend](https://img.shields.io/badge/Backend-FastAPI_Python_3.12-green.svg)](https://fastapi.tiangolo.com/)
[![Frontend](https://img.shields.io/badge/Frontend-Vanilla_JS_+_CSS3-purple.svg)]()

Mobile Web Application controller designed for exhibition booth visitors to interact with **TurtleBot3 Autonomous Navigation** and **VR Robot-Mind View** directly from their own smartphones via QR Code scanning.

---

## 📌 Executive Summary & Architecture

During exhibition demos (Milestone 4 — Stable Integrated Demo), ambient hall noise and robot-mounted microphone hardware failures can hinder voice interaction. This project replaces the robot-mounted mic with an **Audio Input Gateway** on visitor smartphones:

* **High Signal-to-Noise Ratio (SNR):** Visitors speak directly into their smartphone microphones close to their mouth.
* **Hybrid Voice & Text Pipeline:** MediaRecorder Push-to-Talk audio sent to Whisper STT (Groq API, OpenAI API, or Local Faster-Whisper), supplemented by Quick Scenario Chips and a fallback Text input box.
* **Exclusive Session Lock & Smart Watchdog:** Grants exclusive control to one smartphone at a time. The 60-second inactivity watchdog **intelligently pauses** countdown while the robot is navigating (`NAVIGATING` / `REPLANNING`), preventing premature session drops.
* **Configurable Auto-Return to Start Booth:** Automatically commands TurtleBot3 to return to the QR Code starting booth after a session finishes or times out.
* **In-Process rclpy + FastAPI:** Web server and ROS 2 Jazzy Node execute in the same process on WSL 2 Ubuntu 24.04 for ultra-low latency. Includes automatic **Mock ROS 2 Fallback** for standalone web development.

```mermaid
graph TD
    A[Visitor Smartphone<br/>Mobile Web UI] -->|HTTPS POST Voice/Text| B[FastAPI Web Backend<br/>WSL 2 Python 3.12]
    B -->|Whisper STT| C[Transcript Processing]
    C -->|In-Process rclpy| D[/visitor/user_transcript<br/>std_msgs/String]
    D --> E[LLM Task Reasoning Node]
    E -->|/llm/high_level_action| F[TurtleBot3 Nav2]
    E -->|Mind State| G[Unity VR Robot-Mind View]
    F -->|/robot/system_state| B
    B -->|WebSocket /ws/status| A
```

---

## 🗂️ Project Directory Structure

```text
booth_web_controller/
├── .env.example                 # Template for environment variables
├── requirements.txt             # Python dependencies (FastAPI, Uvicorn, Whisper, Pydantic)
├── run_booth.sh                 # Startup script (sources ROS 2 Jazzy + venv + launches Uvicorn)
├── pytest.ini                  # Pytest configuration
├── app/
│   ├── __init__.py
│   ├── config.py                # Pydantic BaseSettings & predefined booth locations
│   ├── models.py                # Pydantic schemas for REST payloads & WebSocket broadcasts
│   ├── session_manager.py       # Exclusive session lock, smart 60s watchdog, auto-return task
│   ├── stt_service.py           # Whisper STT engine (Groq API / OpenAI API / faster-whisper)
│   ├── ros2_bridge.py           # In-process rclpy Node + automatic Mock ROS fallback
│   └── main.py                  # FastAPI app, lifespan handler, REST endpoints, WebSocket manager
├── static/
│   ├── index.html               # Visitor Mobile Web UI (Single-Page App)
│   ├── staff.html               # Staff Override & Recovery Panel (/staff)
│   ├── styles.css               # Modern glassmorphism dark theme stylesheet
│   └── app.js                   # Visitor & Staff frontend logic, WebSocket client, MediaRecorder
└── tests/
    └── test_verification_protocol.py # Automated test suite for verification protocol
```

---

## 🚀 Installation & Setup on WSL 2 Ubuntu 24.04 + ROS 2 Jazzy

### 1. Ubuntu 24.04 PEP 668 Virtual Environment Rule (CRITICAL)
Ubuntu 24.04 enforces `externally-managed-environment`, and `rclpy` resides in the system path (`/opt/ros/jazzy/lib/python3.12/site-packages`). You **MUST** create the virtual environment with `--system-site-packages`:

```bash
# Source ROS 2 Jazzy
source /opt/ros/jazzy/setup.bash

# Create and activate virtual environment with system site-packages
python3 -m venv --system-site-packages ~/booth_web_venv
source ~/booth_web_venv/bin/activate

# Install dependencies
cd booth_web_controller
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
nano .env
```

| Variable | Default | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | Bind IP for Web Server |
| `PORT` | `8000` | Port for Web Server |
| `STAFF_PIN` | `1234` | 4-digit PIN for staff panel access (`/staff`) |
| `INACTIVITY_TIMEOUT_SEC` | `60` | Inactivity countdown seconds before session unlock |
| `AUTO_RETURN_ENABLED` | `true` | Automatically return to Start Booth upon session end |
| `AUTO_RETURN_DELAY_SEC` | `5` | Grace period (seconds) before triggering Auto-Return |
| `STT_PROVIDER` | `groq` | `groq` (recommended, ultra-fast) \| `openai` \| `faster_whisper` |
| `GROQ_API_KEY` | - | Groq API Key |
| `USE_MOCK_ROS2` | `false` | Force Mock ROS 2 mode (auto-activates if rclpy missing) |

### 3. Run the Application
Launch via the startup script:

```bash
chmod +x run_booth.sh
./run_booth.sh
```

Or directly via Uvicorn:
```bash
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 🌐 Exhibition Booth Deployment & HTTPS Setup

Browsers (both iOS Safari and Android Chrome) **block microphone access (`getUserMedia`) on unencrypted HTTP** when accessed via local IP addresses. To allow visitors to use their microphone without connecting to the booth Wi-Fi:

1. **Launch Cloudflare Tunnel (Recommended):**
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
2. **Or ngrok:**
   ```bash
   ngrok http 8000
   ```
3. Copy the resulting `https://*.trycloudflare.com` URL and generate the QR Code for the booth entrance table.
4. Visitors scan the QR Code using their phone's native camera app and gain instant microphone access over 4G/5G.

---

## 📡 ROS 2 Interfaces & Topics

| Topic | Message Type | Direction | Description |
|---|---|---|---|
| `/visitor/user_transcript` | `std_msgs/msg/String` | Publish | JSON payload with visitor transcript |
| `/llm/high_level_action` | `std_msgs/msg/String` | Publish | Action for Nav2: `{"action": "GO_TO\|STOP\|WAIT", "target": "START_BOOTH"}` |
| `/robot/emergency_stop` | `std_msgs/msg/Bool` | Publish | Halts robot navigation immediately |
| `/cmd_vel` | `geometry_msgs/msg/Twist` | Publish | Sends 0.0 velocity on Emergency Stop |
| `/robot/system_state` | `std_msgs/msg/String` | Subscribe | State updates from Nav2 |
| `/llm/mind_status` | `std_msgs/msg/String` | Subscribe | Reasoning output from LLM for VR & Web UI |

---

## 🧪 Verification & Testing Protocol

Run the automated test suite covering all core requirements:

```bash
pytest tests/test_verification_protocol.py -v
```

Tests verify:
1. **Exclusive Session Lock (409 Conflict):** dev-A locks session; dev-B receives 409 Conflict.
2. **Smart Timer Pause:** Inactivity timer pauses countdown during `NAVIGATING` and `REPLANNING`.
3. **Auto-Return on Disconnect:** Disconnecting triggers delayed `GO_TO(START_BOOTH)`.
4. **Staff PIN Security:** `/api/v1/staff/*` endpoints reject unauthorized requests without the correct PIN.
5. **Fallback Voice & Text Input:** Transcripts properly published to ROS 2 topic payload.
