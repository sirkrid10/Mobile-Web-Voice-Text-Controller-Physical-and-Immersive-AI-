# Mobile Web Voice & Text Controller
### Physical and Immersive AI (TurtleBot3 + ROS 2 Nav2 + LLM + VR Robot-Mind View)

[![Target OS](https://img.shields.io/badge/OS-WSL2_Ubuntu_24.04_LTS-orange.svg)](https://ubuntu.com/)
[![ROS 2](https://img.shields.io/badge/ROS2-Jazzy_Jalisco-blue.svg)](https://docs.ros.org/en/jazzy/)
[![Backend](https://img.shields.io/badge/Backend-FastAPI_Python_3.12-green.svg)](https://fastapi.tiangolo.com/)
[![Frontend](https://img.shields.io/badge/Frontend-Vanilla_JS_+_CSS3-purple.svg)]()

Mobile Web Application controller designed for exhibition booth visitors to interact with **TurtleBot3 Autonomous Navigation**, **LLM Task Reasoning (`intent_node` & `subtitle_node`)**, and **VR Robot-Mind View** directly from their own smartphones via QR Code scanning.

---

## เปิดระบบครบทุก terminal

ชุดนี้ใช้หน้าเว็บและ Backend จริง เชื่อม intent/subtitle ผ่าน ROS ส่วนการเดินทางใช้ `mock_robot` บนเครื่องเดียวกัน เปิด Terminal 1–4 ค้างไว้ คนละหน้าต่าง ไม่ต้องเปิด `text_input_node`

ก่อนเริ่ม ต้อง build `ai_interfaces`/`agent_pkg` และติดตั้ง dependencies ของ Backend ตาม `booth_web_controller/requirements.txt` ใน venv ที่ launcher ใช้ เช่น `~/booth_web_venv` แล้ว ตั้ง `GROQ_API_KEY` ใน `.env` ของ TurtleBot workspace และ Backend แยกกัน ห้ามใส่ key ใน README หรือ commit `.env`

คำสั่งแต่ละ terminal source setup ให้ครบ และเติม source package ลง `PYTHONPATH` เพื่อใช้โค้ดล่าสุดแทนสำเนาเก่าใน `install-colcon`

### Terminal 1: mock Robot

```bash
source ~/ros2_ws/turtlebot-llm/setup_demo_auto_ip.sh local
export PYTHONPATH="$PWD/src/agent_pkg:$PWD/src/vlm_pkg${PYTHONPATH:+:$PYTHONPATH}"
ros2 run agent_pkg mock_robot --ros-args -p trip_duration_sec:=20.0
```

### Terminal 2: intent

```bash
source ~/ros2_ws/turtlebot-llm/setup_demo_auto_ip.sh local
export PYTHONPATH="$PWD/src/agent_pkg:$PWD/src/vlm_pkg${PYTHONPATH:+:$PYTHONPATH}"
ros2 run agent_pkg intent_node
```

### Terminal 3: subtitle

```bash
source ~/ros2_ws/turtlebot-llm/setup_demo_auto_ip.sh local
export PYTHONPATH="$PWD/src/agent_pkg:$PWD/src/vlm_pkg${PYTHONPATH:+:$PYTHONPATH}"
ros2 run agent_pkg subtitle_node
```

### Terminal 4: Backend และหน้าเว็บ

```bash
source ~/ros2_ws/turtlebot-llm/setup_demo_auto_ip.sh local
export PYTHONPATH="$PWD/src/agent_pkg:$PWD/src/vlm_pkg${PYTHONPATH:+:$PYTHONPATH}"
cd ~/ros2_ws/Mobile-Web-Voice-Text-Controller-Physical-and-Immersive-AI-/booth_web_controller
ROS_PROFILE=local USE_MOCK_ROS2=false HOST=0.0.0.0 PORT=8000 bash ./run_booth.sh
```

`USE_MOCK_ROS2=false` ให้ Backend ใช้ ROS bridge จริง ส่วน Robot จำลองรันแยกใน Terminal 1 ถ้าตั้ง `true` จะเป็น standalone Backend mock และไม่ใช้ intent/subtitle ใน terminal อื่น

รอ `Uvicorn running` แล้วเปิด <http://localhost:8000> สำหรับผู้ใช้ หรือ <http://localhost:8000/staff> สำหรับเจ้าหน้าที่ ใช้ PIN ที่ตั้งใน `.env` ของ Backend

บน iPhone/iPad ให้เปิดผ่าน HTTPS URL ที่เข้าถึง Backend นี้ได้และส่งต่อ WebSocket `/ws/status` ด้วย ไมค์ต้องใช้ secure context; HTTP บน IP ของเครื่องอื่นอาจใช้ไมค์ไม่ได้ `0.0.0.0` เป็น bind address ไม่ใช่ URL สำหรับเปิดบนมือถือ ใช้ HTTPS URL เดิมที่ตั้งไว้กับระบบ

หน้าแรกกด "ขอสิทธิ์ควบคุม" ก่อน แล้วลองพูดหรือพิมพ์ `ไปจุด A`, `ไปจุด B`, `ไปจุด C` ข้อความขึ้นที่ "หุ่นยนต์ได้ยินว่า:" ส่วนใต้ไมค์แสดงสถานะการรับ/ส่งเสียง ผล intent แยกจากสถานะการเดินของ Robot

แตะไมค์หนึ่งครั้งเพื่อเริ่ม แตะอีกครั้งเพื่อหยุดและส่ง หรือกดค้างแล้วปล่อยเพื่อส่ง หากต้องฟังไฟล์เสียงที่ส่งจริง ใช้ `?debug_audio=1` เช่น <http://localhost:8000/?debug_audio=1>

visitor "กลับจุดเริ่มต้น" หรือ "กลับ start" ตีความเป็น A ส่วน Staff/Auto-return ส่ง system destination `start` พิกัด A/B/C ให้ทีม Robot map จริง

### Terminal 5: VLM พร้อมกล้อง (เลือกเปิด)

ต้องติดตั้ง dependencies และ build `vlm_pkg` ก่อน ไม่จำเป็นสำหรับทดสอบเสียง/ข้อความ/intent ดู `src/vlm_pkg/README.md` ใน TurtleBot workspace สำหรับการตั้งค่า API key และกล้อง

```bash
source ~/ros2_ws/turtlebot-llm/setup_demo_auto_ip.sh local
export PYTHONPATH="$PWD/src/agent_pkg:$PWD/src/vlm_pkg${PYTHONPATH:+:$PYTHONPATH}"
ros2 run vlm_pkg vlm_node --ros-args -p use_webcam:=true -p camera_index:=0
```

หากกล้องอยู่ที่ Robot และส่ง ROS image topic ให้ใช้ `-p use_webcam:=false -p image_topic:=/camera/image_raw` แทนพารามิเตอร์ webcam และเลือก profile `robot` ตามหัวข้อด้านล่าง VLM จะส่ง `/vlm/scene` ให้ subtitle ซึ่ง Backend รับจาก `/vr/subtitle` อีกทอดหนึ่ง

### Terminal 6–8: ดูข้อความ ROS (เลือกเปิด)

เปิดแต่ละคำสั่งใน terminal แยกกัน source profile เดียวกับ node ก่อนทุกครั้ง:

```bash
# Terminal 6: คำสั่งจากเว็บ
source ~/ros2_ws/turtlebot-llm/setup_demo_auto_ip.sh local
ros2 topic echo /guide/user_request ai_interfaces/msg/UserRequest --no-daemon --qos-reliability reliable
```

```bash
# Terminal 7: ผล intent
source ~/ros2_ws/turtlebot-llm/setup_demo_auto_ip.sh local
ros2 topic echo /guide/intent_result ai_interfaces/msg/IntentResult --no-daemon --qos-reliability reliable
```

```bash
# Terminal 8: subtitle
source ~/ros2_ws/turtlebot-llm/setup_demo_auto_ip.sh local
ros2 topic echo /vr/subtitle ai_interfaces/msg/Subtitle --no-daemon --qos-reliability reliable
```

### เปลี่ยนไปใช้ Robot จริง

ไม่เปิด Terminal 1 (`mock_robot`) เปลี่ยน `source ... local` เป็น `source ... robot` ใน terminal ของ intent, subtitle, VLM และ ROS echo และเปลี่ยน Backend เป็น:

```bash
source ~/ros2_ws/turtlebot-llm/setup_demo_auto_ip.sh robot
export PYTHONPATH="$PWD/src/agent_pkg:$PWD/src/vlm_pkg${PYTHONPATH:+:$PYTHONPATH}"
cd ~/ros2_ws/Mobile-Web-Voice-Text-Controller-Physical-and-Immersive-AI-/booth_web_controller
ROS_PROFILE=robot USE_MOCK_ROS2=false HOST=0.0.0.0 PORT=8000 bash ./run_booth.sh
```

ทุก process ต้องใช้ profile เดียวกัน `local` ใช้ domain 83/LOCALHOST ส่วน `robot` ใช้ domain 30/SUBNET และ Discovery Server จาก setup เดิม หาก hostname หาไม่เจอ ตั้ง `TURTLEBOT_ROBOT_IP` เป็น IP ปัจจุบันก่อน source ในทุก terminal ที่เกี่ยวข้อง ไม่ใช้ IP เก่าจากตัวอย่างโดยไม่ตรวจ

ให้ทีม Robot เปิด bridge/navigation และ map จุด A/B/C ก่อนทดสอบการเดินจริง ไม่รัน mock Action server ซ้อนกับ Robot จริง ส่วน Unity/VR เปิดจากโปรเจกต์ของทีม VR แยกต่างหาก

หยุดระบบด้วย `Ctrl+C` ในแต่ละ terminal เมื่อเปลี่ยน profile หรือ environment ให้เริ่ม process ใหม่

## 📌 Executive Summary & Architecture

During exhibition demos (Milestone 4 — Stable Integrated Demo), ambient hall noise and robot-mounted microphone hardware failures can hinder voice interaction. This project replaces the robot-mounted mic with an **Audio Input Gateway** on visitor smartphones:

* **High Signal-to-Noise Ratio (SNR):** Visitors speak directly into their smartphone microphones close to their mouth.
* **Hybrid Voice & Text Pipeline:** MediaRecorder Push-to-Talk audio sent to Whisper STT (Groq API, OpenAI API, or Local Faster-Whisper), supplemented by Quick Scenario Chips (`A`, `B`, `C`, visitor return to A, and unsupported Wait request) and a fallback Text input box.
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
│   ├── config.py                # Pydantic BaseSettings & visitor destinations A/B/C and system start
│   ├── models.py                # Pydantic schemas for REST payloads & WebSocket broadcasts
│   ├── session_manager.py       # Exclusive session lock, smart 60s watchdog, auto-return task
│   ├── stt_service.py           # Whisper STT engine (Groq API / OpenAI API / faster-whisper)
│   ├── ros2_bridge.py           # In-process rclpy Node (/guide/user_request, /robot/navigation_state, /vr/subtitle)
│   └── main.py                  # FastAPI app, lifespan handler, REST endpoints, WebSocket manager
├── static/
│   ├── index.html               # Visitor Mobile Web UI (Single-Page App)
│   ├── staff.html               # Staff Override & Recovery Panel (/staff)
│   ├── styles.css               # Minimal light visitor theme and separate Staff styles
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
| `STT_PROVIDER` | `groq` | `groq` \| `openai` \| `faster_whisper` |
| `STT_LANGUAGE` | `th` | Default transcription language |
| `STT_GROQ_MODEL` | `whisper-large-v3` | Groq transcription model for Thai commands |
| `GROQ_API_KEY` | - | Groq API Key |
| `USE_MOCK_ROS2` | `false` | Force Mock ROS 2 mode (auto-activates if rclpy missing) |

---

## 📡 Aligned ROS 2 Interfaces & Topics

Synchronized with `TurtleBot3_LLM_Subtitle.docx` (`intent_node` and `subtitle_node`):

| Topic / Action | Message Type | Direction | Description |
|---|---|---|---|
| `/guide/user_request` | `ai_interfaces/msg/UserRequest` | Publish (Web ➔ LLM) | `{"request_id": "...", "session_id": "...", "text": "ไปจุด A"}` |
| `/guide/navigate` | `ai_interfaces/action/GuideToDestination` | Publish (Web ➔ Nav2) | `{"request_id": "...", "destination_id": "A\|B\|C\|start"}` |
| `/robot/navigation_state` | `ai_interfaces/msg/NavigationState` | Subscribe (Nav2 ➔ Web & LLM) | `{"stamp": ..., "request_id": "...", "destination_id": "A", "phase": "NAVIGATING\|ARRIVED\|HOME", "ready_for_goal": bool, "distance_remaining_m": float, "error_code": 0, "error_msg": ""}` |
| `/vr/subtitle` | `ai_interfaces/msg/Subtitle` | Subscribe (LLM ➔ VR & Web) | `{"stamp": ..., "request_id": "...", "observation_id": "...", "text": "กำลังนำทางไปจุด A", "ttl": ...}` (ซิงค์คำบรรยายสดขึ้นจอมือถือและแว่น VR) |
| `/robot/emergency_stop` | `std_msgs/msg/Bool` | Publish (Web ➔ Nav2) | Halts robot navigation immediately |
| `/cmd_vel` | `geometry_msgs/msg/Twist` | Publish (Web ➔ Nav2) | Sends 0.0 velocity on Emergency Stop |

---

## 🧪 Verification & Testing Protocol

Run the automated test suite covering all core requirements:

```bash
pytest tests/test_verification_protocol.py -v
```
