# Mobile Web Voice & Text Controller
### Physical and Immersive AI (TurtleBot3 + ROS 2 Nav2 + LLM + VR Robot-Mind View)

[![Target OS](https://img.shields.io/badge/OS-WSL2_Ubuntu_24.04_LTS-orange.svg)](https://ubuntu.com/)
[![ROS 2](https://img.shields.io/badge/ROS2-Jazzy_Jalisco-blue.svg)](https://docs.ros.org/en/jazzy/)
[![Backend](https://img.shields.io/badge/Backend-FastAPI_Python_3.12-green.svg)](https://fastapi.tiangolo.com/)
[![Frontend](https://img.shields.io/badge/Frontend-Vanilla_JS_+_CSS3-purple.svg)]()

Mobile Web Application controller designed for exhibition booth visitors to interact with **TurtleBot3 Autonomous Navigation**, **LLM Task Reasoning (`intent_node` & `subtitle_node`)**, and **VR Robot-Mind View** directly from their own smartphones via QR Code scanning.

---

## 📌 Executive Summary & Architecture

During exhibition demos (Milestone 4 — Stable Integrated Demo), ambient hall noise and robot-mounted microphone hardware failures can hinder voice interaction. This project replaces the robot-mounted mic with an **Audio Input Gateway** on visitor smartphones:

* **High Signal-to-Noise Ratio (SNR):** Visitors speak directly into their smartphone microphones close to their mouth.
* **Hybrid Voice & Text Pipeline:** MediaRecorder Push-to-Talk audio sent to Whisper STT (Groq API, OpenAI API, or Local Faster-Whisper), supplemented by Quick Scenario Chips (`booth_09`, `booth_10`, `start`, `wait`) and a fallback Text input box.
* **Exclusive Session Lock & Smart Watchdog:** Grants exclusive control to one smartphone at a time. The 60-second inactivity watchdog **intelligently pauses** countdown while the robot is navigating (`NAVIGATING` / `RETURNING_HOME`), preventing premature session drops.
* **Configurable Auto-Return to Start Booth:** Automatically commands TurtleBot3 to return to the QR Code starting booth (`destination_id="start"`) after a session finishes or times out.
* **In-Process rclpy + FastAPI:** Web server and ROS 2 Jazzy Node execute in the same process on WSL 2 Ubuntu 24.04 for ultra-low latency. Includes automatic **Mock ROS 2 Fallback** for standalone web development.

```mermaid
graph TD
    A[Visitor Smartphone<br/>Mobile Web UI] -->|HTTPS POST Voice/Text| B[FastAPI Web Backend<br/>WSL 2 Python 3.12]
    B -->|Whisper STT| C[Transcript Processing]
    C -->|ROS 2 Topic| D[/guide/user_request<br/>UserRequest]
    D --> E[LLM intent_node]
    E -->|/guide/navigate<br/>GuideToDestination| F[TurtleBot3 Nav2]
    F -->|/robot/navigation_state| G[LLM subtitle_node]
    G -->|/vr/subtitle| H[Unity VR Headset & Mobile Web]
    F -->|/robot/navigation_state| B
    B -->|WebSocket /ws/status| A
```

---

## 🗂️ Project Directory Structure

```text
booth_web_controller/
├── .env.example                 # Template for environment variables
├── requirements.txt             # Python dependencies (FastAPI, Uvicorn, Whisper, Pydantic)
├── run_booth.sh                 # Startup script (sources ROS 2 Jazzy + venv + launches Uvicorn)
├── pytest.ini                   # Pytest configuration
├── app/
│   ├── __init__.py
│   ├── config.py                # Pydantic BaseSettings & booth destinations (booth_09, booth_10, start)
│   ├── models.py                # Pydantic schemas for REST payloads & WebSocket broadcasts
│   ├── session_manager.py       # Exclusive session lock, smart 60s watchdog, auto-return task
│   ├── stt_service.py           # Whisper STT engine (Groq API / OpenAI API / faster-whisper)
│   ├── ros2_bridge.py           # In-process rclpy Node (/guide/user_request, /robot/navigation_state, /vr/subtitle)
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
| `START_BOOTH_ID` | `start` | Canonical location identifier for the starting booth |
| `STT_PROVIDER` | `groq` | `groq` (recommended, ultra-fast) \| `openai` \| `faster_whisper` |
| `GROQ_API_KEY` | - | Groq API Key |
| `USE_MOCK_ROS2` | `false` | Force Mock ROS 2 mode (auto-activates if rclpy missing) |

---

## 📡 Aligned ROS 2 Interfaces & Topics

Synchronized with `TurtleBot3_LLM_Subtitle.docx` (`intent_node` and `subtitle_node`):

| Topic / Action | Message Type | Direction | Description |
|---|---|---|---|
| `/guide/user_request` | `std_msgs/msg/String` / `ai_interfaces/msg/UserRequest` | Publish (Web ➔ LLM) | `{"request_id": "...", "session_id": "...", "text": "พาไปบูธคอมพิวเตอร์"}` |
| `/guide/navigate` | `std_msgs/msg/String` / `ai_interfaces/action/GuideToDestination` | Publish (Web ➔ Nav2) | `{"request_id": "...", "destination_id": "start\|booth_09\|booth_10"}` |
| `/robot/navigation_state` | `std_msgs/msg/String` / `ai_interfaces/msg/NavigationState` | Subscribe (Nav2 ➔ Web & LLM) | `{"stamp": ..., "request_id": "...", "destination_id": "booth_09", "phase": "NAVIGATING\|ARRIVED\|HOME", "ready_for_goal": bool, "distance_remaining_m": float, "error_code": 0, "error_msg": ""}` |
| `/vr/subtitle` | `std_msgs/msg/String` / `ai_interfaces/msg/Subtitle` | Subscribe (LLM ➔ VR & Web) | `{"stamp": ..., "request_id": "...", "observation_id": "...", "text": "เห็นคนด้านหน้า กำลังนำทางไปบูธคอมพิวเตอร์", "ttl": ...}` (ซิงค์คำบรรยายสดขึ้นจอมือถือและแว่น VR) |
| `/robot/emergency_stop` | `std_msgs/msg/Bool` | Publish (Web ➔ Nav2) | Halts robot navigation immediately |
| `/cmd_vel` | `geometry_msgs/msg/Twist` | Publish (Web ➔ Nav2) | Sends 0.0 velocity on Emergency Stop |
| `/visitor/user_transcript` | `std_msgs/msg/String` | Publish | Fallback alias topic for user speech |
| `/llm/mind_status` | `std_msgs/msg/String` | Subscribe | Fallback alias topic for reasoning explanation |

---

## 🧪 Verification & Testing Protocol

Run the automated test suite covering all core requirements:

```bash
pytest tests/test_verification_protocol.py -v
```
