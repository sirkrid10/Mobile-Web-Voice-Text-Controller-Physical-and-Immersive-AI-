# Mobile Web Voice & Text Controller
### Physical and Immersive AI (TurtleBot3 + ROS 2 Nav2 + LLM + VR Robot-Mind View)

การเชื่อมหุ่นจริงปัจจุบันใช้ **Tailscale** คำสั่ง intent, subtitle และ Backend อยู่ด้านบนของเอกสารนี้ คำสั่ง LAN เป็นทางเลือกสำหรับเครือข่ายภายใน

[![Target OS](https://img.shields.io/badge/OS-WSL2_Ubuntu_24.04_LTS-orange.svg)](https://ubuntu.com/)
[![ROS 2](https://img.shields.io/badge/ROS2-Jazzy_Jalisco-blue.svg)](https://docs.ros.org/en/jazzy/)
[![Backend](https://img.shields.io/badge/Backend-FastAPI_Python_3.12-green.svg)](https://fastapi.tiangolo.com/)
[![Frontend](https://img.shields.io/badge/Frontend-Vanilla_JS_+_CSS3-purple.svg)]()

Mobile Web Application controller designed for exhibition booth visitors to interact with **TurtleBot3 Autonomous Navigation**, **LLM Task Reasoning (`intent_node` & `subtitle_node`)**, and **VR Robot-Mind View** directly from their own smartphones via QR Code scanning.

---

## Subtitle สำหรับ Unity VR

Backend เปิด `/ws/vr/subtitle` พร้อมเว็บเดิม ดู [วิธีตั้งค่า VR และ contract](VR-SUBTITLE-INTEGRATION.md)

## รัน Backend ผ่าน Tailscale กับ Robot จริง (วิธีใช้งานปัจจุบัน)

ติดตั้ง Tailscale ภายใน Ubuntu WSL ที่รัน ROS ปิด Tailscale ฝั่ง Windows และให้ VM/Pi อนุญาตการติดต่อผ่าน tailnet ติดตั้งชุดล่าสุดของ repo `turtlebot-llm` ไว้เป็นโฟลเดอร์ข้าง repo นี้ และ build `ai_interfaces` กับ `agent_pkg` ตามคู่มือ LLM ก่อน

ก่อนเปิดชุดจริง ตรวจ `tailscale status` และ `tailscale ping 100.127.193.83` ใน WSL ให้ VM ติดต่อได้ ใช้ Tailscale ภายใน WSL และ disconnect ฝั่ง Windows ตามการตั้งค่าชุดนี้ อย่าเปิด node ซ้อนกับชุดเดิม และไม่เปิด mock Robot บน domain ของหุ่นจริง

### Build หลังแก้ subtitle (เครื่องที่ติดตั้งไว้แล้ว)

```bash
cd ~/ros2_ws/turtlebot-llm
source /opt/ros/jazzy/setup.bash
source install-colcon/setup.bash
source .venv/bin/activate
colcon --log-base log-colcon build --build-base build-colcon \
  --install-base install-colcon --packages-select agent_pkg
```

ใช้ `.env` และ `GROQ_API_KEY` เดิม ไม่ต้อง rebuild ฝั่งหุ่น เพราะ interfaces ไม่เปลี่ยน หลัง build เปิด subtitle ใหม่เพื่อโหลดโค้ดล่าสุด เครื่องใหม่ให้ติดตั้งและ build interfaces ตามหัวข้อติดตั้งด้านล่างก่อน

### Terminal 1: Intent

```bash
cd ~/ros2_ws/turtlebot-llm
bash ./run_tailscale.sh intent
```

### Terminal 2: Subtitle

```bash
cd ~/ros2_ws/turtlebot-llm
bash ./run_tailscale.sh subtitle
```

### Terminal 3: Backend

```bash
cd ~/ros2_ws/Mobile-Web-Voice-Text-Controller-Physical-and-Immersive-AI-
bash booth_web_controller/run_tailscale.sh
```

### เลือกโหมด subtitle จากหน้า Staff

หน้า Staff รับคำบรรยายสดผ่าน `/ws/status` เดิมและค้างข้อความล่าสุดจนมีข้อความใหม่แทน เพื่อไม่พลาดซับสั้นระหว่างรอบอ่านสถานะ มี polling สำรองเมื่อการเชื่อมต่อสดหลุด และเชื่อม WebSocket ใหม่อัตโนมัติ หลังอัปเดตหน้า Staff ให้กด Ctrl+Shift+R

เปิด <http://localhost:8000/staff> (หรือพอร์ต/HTTPS URL ที่ใช้งานจริง) ยืนยัน PIN เดิม แล้วใช้ส่วน **รูปแบบการตอบของหุ่น**:

1. รอหน้าเว็บอ่านโหมดปัจจุบันจาก `subtitle_node`
2. เลือก **Standard** หรือ **Friendly** แล้วกด **ใช้โหมดนี้**
3. รอข้อความยืนยัน หากเปลี่ยนจาก Terminal อื่นหรือเปิด node ใหม่ ให้กด **อ่านโหมดปัจจุบัน**

Backend อ่าน/ตั้งเฉพาะ ROS parameter `subtitle_mode` ของ `/subtitle_node` ผ่าน services มาตรฐาน ไม่ส่ง Goal ไม่เปลี่ยน intent หรือ provider และไม่ต้อง rebuild LLM เพื่อเพิ่มเมนูนี้ แต่ต้องใช้ subtitle รุ่นที่รองรับโหมดแล้ว ทั้ง Backend และ subtitle ต้องอยู่ใน ROS profile เดียวกัน (local กับ local หรือ Tailscale กับ Tailscale)

หาก node ไม่พร้อมหรือ timeout จะไม่แจ้งว่าสำเร็จ กรณี timeout การเปลี่ยนอาจถึง node แล้ว จึงควรอ่านโหมดปัจจุบันก่อนลองซ้ำ ไม่สั่งซ้ำอัตโนมัติ โหมดนี้เป็น runtime ไม่เก็บข้าม restart ของ subtitle และหน้า Staff แบบ Backend standalone mock (`USE_MOCK_ROS2=true`) ไม่จำลองผลสำเร็จของการเปลี่ยนโหมด; local demo ที่เปิด subtitle จริงใช้ได้

หลังอัปเดต Backend ให้เปิดใหม่ด้วยสคริปต์เดิมและกด Ctrl+Shift+R ที่หน้า Staff หากตัวรันเดิมเปิด reload อยู่ อาจโหลด Python ที่เปลี่ยนให้แล้ว ไม่ต้องเปลี่ยน `.env` หรือสคริปต์ คำสั่ง Terminal ยังใช้แทนเมนูได้:

```bash
cd ~/ros2_ws/turtlebot-llm
source ./setup_tailscale_ros.sh
ros2 param set /subtitle_node subtitle_mode friendly
ros2 param get /subtitle_node subtitle_mode --no-daemon --spin-time 3
```

กลับโหมดเดิมด้วย `ros2 param set /subtitle_node subtitle_mode standard` ค่านี้ไม่เก็บข้ามการ restart node จึงสลับใหม่หลังเปิด subtitle แต่ละครั้ง ไม่ต้องแก้ `.env` หรือสคริปต์รัน

ใน `friendly` คำคุย/คำถามรอ Groq ก่อน และใช้ fallback เมื่อ API ล้มเหลวหรือคำตอบไม่ผ่านกฎ ส่วนสถานะเดิน/ถึงแล้วและข้อผิดพลาดแสดงทันที การแต่งข้อความไม่เปลี่ยนผล intent หรือส่ง Goal เพิ่ม

เปิด <http://localhost:8000> หรือ <http://localhost:8000/staff> แล้วขอสิทธิ์ควบคุมก่อนส่งคำสั่ง บนมือถือใช้ HTTPS URL เดิมที่ส่งต่อ `/ws/status` ได้

เว็บเก็บข้อความซับล่าสุดไว้จนมีข้อความใหม่มาแทน แม้ ROS ส่ง clear หลัง TTL หมด การค้างข้อความเป็นพฤติกรรมการแสดงผล ไม่ใช่การยืนยันว่าสถานะ Robot ยังสด และไม่เก็บข้อความข้ามการรีเฟรชหน้า หลังอัปเดต `app.js` ให้กด Ctrl+Shift+R

### เตรียม Tailscale ก่อนเปิดระบบ

ใช้ Tailscale ภายใน Ubuntu WSL และ Disconnect ตัวบน Windows ฝั่ง VM และ Pi ที่รับส่ง DDS ต้องออนไลน์ผ่าน Tailscale และอนุญาตการติดต่อกับเครื่อง LLM ด้วย

ตรวจสถานะจาก Ubuntu WSL ก่อนเปิด ROS:

```bash
tailscale status
tailscale ip -4
ip -4 addr show tailscale0
```

ต้องเห็น Tailscale IP ของ WSL บน `tailscale0` และเห็น VM `100.127.193.83` อยู่ในรายการ หาก Tailscale ยังไม่ได้เชื่อมต่อ:

```bash
sudo tailscale up
```

หากคำสั่งแจ้งว่าติดต่อ Tailscale daemon ไม่ได้ ให้เริ่ม service แล้วเชื่อมต่ออีกครั้ง:

```bash
sudo systemctl start tailscaled
sudo tailscale up
```

หากต้องการให้ daemon เริ่มอัตโนมัติเมื่อ Ubuntu WSL เริ่มทำงาน ให้ตั้งครั้งเดียว:

```bash
sudo systemctl enable tailscaled
```

หากมีลิงก์ login ให้เปิดและยืนยันด้วยบัญชีที่ได้รับอนุญาตเข้าถึง VM ไม่ต้อง login ใหม่ทุกครั้ง ตรวจเส้นทางไป VM ก่อนรันระบบได้ด้วย:

```bash
tailscale ping 100.127.193.83
```

การ ping สำเร็จยืนยันเส้นทาง Tailscale เท่านั้น ยังต้องตรวจ ROS ด้วย probe หรือ echo ตามคำสั่งด้านล่าง

### หลังเปลี่ยน Wi-Fi หรือ hotspot

ใช้คำสั่ง `run_tailscale.sh` เดิมได้โดยไม่ต้องเปลี่ยน IP Wi-Fi ใน config ตราบใดที่ Tailscale IP ของ VM ยังเดิมและทุกเครื่องติดต่อกันได้ ตรวจ `tailscale status` และ `tailscale ping 100.127.193.83` ก่อน หาก ROS ไม่กลับมาเชื่อมเอง ให้ยืนยันว่าไม่มี Goal ค้างและหุ่นอยู่ในสถานะที่เหมาะสมก่อนหยุดชุดเดิม แล้วเปิด intent, subtitle และ Backend ใหม่ด้วยคำสั่ง Tailscale ด้านบน อย่าเปิด node ซ้อนหรือ source สคริปต์ LAN ทับ

Launcher โหลด `turtlebot-llm/setup_tailscale_ros.sh` ใช้ ROS จริง, domain 30, Discovery Server `100.127.193.83:11811` และ DDS profile เดียวกับ intent/subtitle ไม่ source สคริปต์ LAN ทับ และไม่เปิด mock Robot บน domain นี้

หาก VM เปลี่ยน Tailscale IP ให้ส่ง IP ใหม่เป็น argument สุดท้ายของทั้งสามคำสั่ง หรือ export `TURTLEBOT_TAILSCALE_SERVER_IP` ให้ตรงกันทุก terminal

เมื่อเปลี่ยน profile ครั้งแรกต้องหยุดชุดเดิมทั้งหมดก่อน สคริปต์ไม่หยุด node ให้และไม่แก้ firewall การเปลี่ยน Wi-Fi มักไม่เปลี่ยน Tailscale IP แต่ยังต้องตรวจว่าทั้ง VM และ WSL ออนไลน์ หากต้องกลับ LAN ให้หยุดชุด Tailscale แล้วเปิด terminal ใหม่ด้วย `run_robot.sh` ตามคู่มือ LAN

ตรวจจาก terminal แยกโดยไม่ส่ง Goal:

```bash
cd ~/ros2_ws/turtlebot-llm
source ./setup_tailscale_ros.sh
python3 tools/tailscale/robot_vm_link_probe.py --samples 10 --timeout 5 --warmup-sec 2
ros2 topic info /guide/user_request --verbose --no-daemon
```

### Terminal สำหรับ echo ข้อมูล ROS ผ่าน Tailscale

เปิดแต่ละคำสั่งใน terminal แยกกัน ทุก terminal ต้องโหลด Tailscale setup ก่อน ไม่ source `setup_demo_auto_ip.sh` ทับ หากใช้ VM IP ที่ต่างจากค่าเริ่มต้น ให้ระบุ IP เดียวกับชุดที่รันอยู่หลัง `setup_tailscale_ros.sh`

#### ดูคำขอจาก Frontend

```bash
cd ~/ros2_ws/turtlebot-llm
source ./setup_tailscale_ros.sh
ros2 topic echo /guide/user_request ai_interfaces/msg/UserRequest --no-daemon
```

#### ดูผลตีความ intent

```bash
cd ~/ros2_ws/turtlebot-llm
source ./setup_tailscale_ros.sh
ros2 topic echo /guide/intent_result ai_interfaces/msg/IntentResult --no-daemon
```

#### ดูสถานะ Robot

```bash
cd ~/ros2_ws/turtlebot-llm
source ./setup_tailscale_ros.sh
ros2 topic echo /robot/navigation_state ai_interfaces/msg/NavigationState \
  --no-daemon --qos-reliability reliable --qos-durability volatile
```

ใช้ volatile เพื่อรับสถานะใหม่และรองรับ publisher ทั้ง volatile และ transient-local หากยืนยันแล้วว่า Robot publisher เป็น transient-local และต้องการรับสถานะที่เก็บไว้ทันที ให้เปลี่ยนเป็น `--qos-durability transient_local`

#### ดู Subtitle

```bash
cd ~/ros2_ws/turtlebot-llm
source ./setup_tailscale_ros.sh
ros2 topic echo /vr/subtitle ai_interfaces/msg/Subtitle --no-daemon
```

คำสั่งเหล่านี้อ่านข้อมูลและไม่ส่ง Goal ใช้ `request_id` จับคู่คำขอ ผล intent และสถานะ Robot ผล `NAVIGATE` ยืนยันการตีความเท่านั้น ต้องดู NavigationState และ Action terminal result ใน log intent ร่วมกันเพื่อยืนยันผลการนำทาง

## สถาปัตยกรรม

During exhibition demos (Milestone 4 — Stable Integrated Demo), ambient hall noise and robot-mounted microphone hardware failures can hinder voice interaction. This project replaces the robot-mounted mic with an **Audio Input Gateway** on visitor smartphones:

* **High Signal-to-Noise Ratio (SNR):** Visitors speak directly into their smartphone microphones close to their mouth.
* **Hybrid Voice & Text Pipeline:** MediaRecorder Push-to-Talk audio sent to Whisper STT (Groq API, OpenAI API, or Local Faster-Whisper), supplemented by Quick Scenario Chips (`A`, `B`, `C`, visitor return to A, and unsupported Wait request) and a fallback Text input box.
* **Exclusive Session Lock & Smart Watchdog:** Grants exclusive control to one smartphone at a time. The inactivity timeout defaults to 120 seconds and pauses while the web state is NAVIGATING or REPLANNING. Existing `.env` settings override this default.
* **Configurable Auto-Return to Start Booth:** Automatically commands TurtleBot3 to return to the QR Code starting booth (`destination_id="A"`) after a session finishes or times out.
* **In-Process rclpy + FastAPI:** Web server and ROS 2 Jazzy Node execute in the same process on WSL 2 Ubuntu 24.04 for ultra-low latency. Standalone simulation requires explicit `USE_MOCK_ROS2=true`; real ROS mode fails startup if ROS imports are missing.

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

Robot Bridge A/B/C ใช้ `READY` → `NAVIGATING` → `ARRIVED` และ `ready_for_goal=true` ก่อนรับงานถัดไป การกลับจุดเริ่มต้นส่ง `A` และเว็บแสดง `REACHED` เมื่อถึง ไม่ต้องรอ `HOME` ตั้ง `START_BOOTH_ID=A` ใน `.env` ของเครื่องที่รัน Backend คำว่า `start` ในปุ่มลัดเป็นข้อความที่ intent ตีความเป็น A ไม่ใช่ Robot destination ID

หน้าเว็บรับผลผ่าน `/ws/status` แสดง transcript, intent, Robot state และ subtitle แยกกัน Backend ล้างข้อมูล subtitle ตาม `stamp + ttl` แต่หน้าเว็บค้างข้อความล่าสุดไว้จนมีข้อความใหม่มาแทน ไม่เก็บข้อความข้ามการรีเฟรชหน้า

## โครงสร้างโปรเจกต์

```text
booth_web_controller/
├── .env.example                 # Template for environment variables
├── requirements.txt             # Python dependencies (FastAPI, Uvicorn, Whisper, Pydantic)
├── run_booth.sh                 # Startup script (sources ROS 2 Jazzy + venv + launches Uvicorn)
├── pytest.ini                   # Pytest configuration
├── app/
│   ├── __init__.py
│   ├── config.py                # Pydantic BaseSettings & visitor destinations A/B/C and return to A
│   ├── models.py                # Pydantic schemas for REST payloads & WebSocket broadcasts
│   ├── session_manager.py       # Exclusive session lock, configurable inactivity watchdog, auto-return task
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

## ติดตั้งและตั้งค่า

### 1. ติดตั้ง dependencies ใน virtual environment
Ubuntu 24.04 enforces `externally-managed-environment`, and `rclpy` resides in the system path (`/opt/ros/jazzy/lib/python3.12/site-packages`). You **MUST** create the virtual environment with `--system-site-packages`:

```bash
# Source ROS 2 Jazzy
source /opt/ros/jazzy/setup.bash

# Create and activate virtual environment with system site-packages
python3 -m venv --system-site-packages ~/booth_web_venv
source ~/booth_web_venv/bin/activate

# Install dependencies
cd ~/ros2_ws/Mobile-Web-Voice-Text-Controller-Physical-and-Immersive-AI-/booth_web_controller
python -m pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp -n .env.example .env
nano .env
```

| Variable | Default | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | Bind IP for Web Server |
| `PORT` | `8000` | Port for Web Server |
| `STAFF_PIN` | `1234` | 4-digit PIN for staff panel access (`/staff`) |
| `INACTIVITY_TIMEOUT_SEC` | `120` | Inactivity countdown seconds before session unlock |
| `AUTO_RETURN_ENABLED` | `true` | Automatically return to Start Booth upon session end |
| `AUTO_RETURN_DELAY_SEC` | `5` | Grace period (seconds) before triggering Auto-Return |
| `START_BOOTH_ID` | `A` | Robot destination for staff and automatic return; use A/B/C contract |
| `STT_PROVIDER` | `groq` | `groq` \| `openai` \| `faster_whisper` |
| `STT_LANGUAGE` | `th` | Default transcription language |
| `STT_GROQ_MODEL` | `whisper-large-v3` | Groq transcription model for Thai commands |
| `GROQ_API_KEY` | - | Groq API Key |
| `USE_MOCK_ROS2` | `false` | Explicit standalone simulation; false uses ROS 2 |

---

## 📡 Aligned ROS 2 Interfaces & Topics

Synchronized with `TurtleBot3_LLM_Subtitle.docx` (`intent_node` and `subtitle_node`):

| Topic / Action | Message Type | Direction | Description |
|---|---|---|---|
| `/guide/user_request` | `ai_interfaces/msg/UserRequest` | Publish (Web ➔ LLM) | `{"request_id": "...", "session_id": "...", "text": "ไปจุด A"}` |
| `/guide/navigate` | `ai_interfaces/action/GuideToDestination` | Publish (Web ➔ Nav2) | `{"request_id": "...", "destination_id": "A\|B\|C", "valid_until": {"sec": ..., "nanosec": ...}}` |
| `/robot/navigation_state` | `ai_interfaces/msg/NavigationState` | Subscribe (Nav2 ➔ Web & LLM) | `{"stamp": ..., "request_id": "...", "destination_id": "A", "phase": "NAVIGATING\|ARRIVED\|HOME", "ready_for_goal": bool, "distance_remaining_m": float, "error_code": 0, "error_msg": ""}` |
| `/vr/subtitle` | `ai_interfaces/msg/Subtitle` | Subscribe (LLM ➔ VR & Web) | `{"stamp": ..., "request_id": "...", "observation_id": "...", "text": "กำลังนำทางไปจุด A", "ttl": ...}` (ซิงค์คำบรรยายสดขึ้นจอมือถือและแว่น VR) |
| `/robot/emergency_stop` | `std_msgs/msg/Bool` | Publish (Web ➔ Nav2) | Halts robot navigation immediately |
| `/cmd_vel` | `geometry_msgs/msg/Twist` | Publish (Web ➔ Nav2) | Sends 0.0 velocity on Emergency Stop |

---

## ทดสอบ

Run the automated test suite covering all core requirements:

```bash
python3 -m pytest tests/test_verification_protocol.py tests/test_stt_dependencies.py -q
node --test tests/test_*.js
bash tests/test_run_booth.sh
```

## ทางเลือก: รัน Robot ผ่าน LAN แยกแต่ละ terminal

Build `ai_interfaces` และ `agent_pkg` ใน repo [turtlebot-llm](https://github.com/Lilieay/turtlebot-llm) ลง `install-colcon` ก่อน ฝั่ง Robot ต้องเปิด Bridge, Nav2 และ Discovery Server ของตัวเอง ตัวอย่างใช้ IP `10.202.238.194` ให้เปลี่ยนเป็น IP ปัจจุบันในทุก terminal และไม่เปิด mock Robot ซ้อนบน domain นี้

### Terminal 1: intent

```bash
export TURTLEBOT_ROBOT_IP=10.202.238.194
source ~/ros2_ws/turtlebot-llm/setup_demo_auto_ip.sh robot
ros2 run agent_pkg intent_node
```

### Terminal 2: subtitle

```bash
export TURTLEBOT_ROBOT_IP=10.202.238.194
source ~/ros2_ws/turtlebot-llm/setup_demo_auto_ip.sh robot
ros2 run agent_pkg subtitle_node
```

### Terminal 3: Backend และหน้าเว็บ

```bash
bash ~/ros2_ws/Mobile-Web-Voice-Text-Controller-Physical-and-Immersive-AI-/booth_web_controller/run_robot.sh 10.202.238.194
```

Wrapper เลือก `ROS_PROFILE=robot`, `USE_MOCK_ROS2=false` และล้าง ROS environment ที่ค้างจาก local ก่อนเรียก `run_booth.sh` เพื่อโหลด shared setup ใช้ domain 30/SUBNET กับ Discovery Server `IP:11811`

หากต้องการรัน launcher โดยตรง ใช้ชุดคำสั่งนี้แทน Terminal 3:

```bash
export TURTLEBOT_ROBOT_IP=10.202.238.194
source ~/ros2_ws/turtlebot-llm/setup_demo_auto_ip.sh robot
cd ~/ros2_ws/Mobile-Web-Voice-Text-Controller-Physical-and-Immersive-AI-/booth_web_controller
ROS_PROFILE=robot USE_MOCK_ROS2=false HOST=0.0.0.0 PORT=8000 bash ./run_booth.sh
```

เปิด <http://localhost:8000> หรือ <http://localhost:8000/staff> บนมือถือใช้ HTTPS และส่งต่อ WebSocket `/ws/status` ด้วย กดขอสิทธิ์ควบคุมก่อนส่งคำสั่ง

### Terminal 4: ตรวจคำขอจากเว็บ

```bash
export TURTLEBOT_ROBOT_IP=10.202.238.194
source ~/ros2_ws/turtlebot-llm/setup_demo_auto_ip.sh robot
ros2 topic echo /guide/user_request ai_interfaces/msg/UserRequest --no-daemon
```

### Terminal 5: ตรวจสถานะ Robot

```bash
export TURTLEBOT_ROBOT_IP=10.202.238.194
source ~/ros2_ws/turtlebot-llm/setup_demo_auto_ip.sh robot
ros2 topic echo /robot/navigation_state ai_interfaces/msg/NavigationState \
	--no-daemon --qos-reliability reliable --qos-durability transient_local
```

### Terminal 6: ตรวจผล intent

```bash
export TURTLEBOT_ROBOT_IP=10.202.238.194
source ~/ros2_ws/turtlebot-llm/setup_demo_auto_ip.sh robot
ros2 topic echo /guide/intent_result ai_interfaces/msg/IntentResult --no-daemon
```

### Terminal 7: ตรวจ subtitle

```bash
export TURTLEBOT_ROBOT_IP=10.202.238.194
source ~/ros2_ws/turtlebot-llm/setup_demo_auto_ip.sh robot
ros2 topic echo /vr/subtitle ai_interfaces/msg/Subtitle --no-daemon
```

กด Ctrl+C ในแต่ละ terminal เพื่อหยุด หากใช้ LLM launcher รุ่นใหม่ สามารถแทน Terminal 1 และ 2 ด้วย `bash ~/ros2_ws/turtlebot-llm/run_robot.sh 10.202.238.194`

## ปัญหาที่พบและคำสั่งแก้ไข

### เว็บส่งคำขอแล้ว intent ไม่รับ

ตรวจ domain ใน terminal ที่เปิดแต่ละ process และตรวจ subscriber:

```bash
printenv ROS_DOMAIN_ID RMW_IMPLEMENTATION ROS_AUTOMATIC_DISCOVERY_RANGE ROS_DISCOVERY_SERVER
ros2 topic info /guide/user_request --verbose --no-daemon
```

เคยพบ Backend อยู่ domain 83/LOCALHOST แต่ intent อยู่ 30/SUBNET ทำให้เห็น publisher แต่ subscription เป็น 0 หยุด process เดิมแล้วเปิดด้วยชุด Robot จริงด้านบน การ source ใน shell อื่นไม่เปลี่ยน process ที่รันแล้ว

### Backend ยังส่งกลับด้วย destination start

ตั้ง `START_BOOTH_ID=A` ใน `.env` แล้ว restart Backend ค่า start ไม่ผ่าน config validation เพื่อไม่ให้ส่ง goal ที่ Robot ปฏิเสธ ปุ่ม "กลับ start" บนเว็บยังใช้ได้เพราะส่งเป็นข้อความให้ intent แปลเป็น A

### Timeout ไม่เปลี่ยนเป็น 120 วินาที

ค่า 120 เป็น default ใน config และ `.env.example` ไฟล์ `.env` เดิมหรือค่าที่ Staff ปรับยัง override ได้ ตรวจเฉพาะค่านี้โดยไม่แสดง API keys:

```bash
cd ~/ros2_ws/Mobile-Web-Voice-Text-Controller-Physical-and-Immersive-AI-/booth_web_controller
rg '^INACTIVITY_TIMEOUT_SEC=' .env
nano .env
```

ตั้ง `INACTIVITY_TIMEOUT_SEC=120` ถ้าต้องการค่าใหม่ แล้ว restart Backend หรือปรับค่าจาก Staff Panel

### Import rclpy หรือ ai_interfaces ไม่ได้

Build ai_interfaces ลง install-colcon ใน repo LLM แล้วใช้ launcher ที่ source shared setup ตรวจ imports หลัง source robot profile:

```bash
python3 -c 'import rclpy, ai_interfaces; print(rclpy.__file__); print(ai_interfaces.__file__)'
```

หากขาด FastAPI, openai หรือ dependencies ของ STT ให้ติดตั้ง `requirements.txt` ใน venv ที่ launcher ใช้ เช่น `~/booth_web_venv` ไม่ติดตั้งลง system Python

### ได้ผล NAVIGATE แต่หุ่นไม่เดิน หรือคำสั่งถัดไปค้าง

NAVIGATE ยืนยันการตีความเท่านั้น จับคู่ request ID ใน UserRequest, IntentResult, NavigationState และ log Action ตรวจว่า goal เดิมมี terminal result แล้ว มี heartbeat ใหม่พร้อม `ready_for_goal=true` และ valid_until ของ goal ใหม่ยังไม่หมดอายุ อย่าเพิ่ม freshness หรือข้าม readiness เพื่อกลบอาการ ปัญหาการรับหลาย goal ต่อเนื่องยังต้องวินิจฉัยจาก log ของแต่ละคำขอ

## รันเดโม local แยกแต่ละ terminal

ชุดนี้ใช้หน้าเว็บและ Backend จริง เชื่อม intent/subtitle ผ่าน ROS ส่วนการเดินทางใช้ `mock_robot` บนเครื่องเดียวกัน เปิด Terminal 1–4 ค้างไว้ คนละหน้าต่าง ไม่ต้องเปิด `text_input_node`

ก่อนเริ่ม ต้อง build `ai_interfaces`/`agent_pkg` และติดตั้ง dependencies ของ Backend ตาม `booth_web_controller/requirements.txt` ใน venv ที่ launcher ใช้ เช่น `~/booth_web_venv` แล้ว ตั้ง `GROQ_API_KEY` ใน `.env` ของ TurtleBot workspace และ Backend แยกกัน ห้ามใส่ key ใน README หรือ commit `.env`

Build แพ็กเกจ LLM ลง install-colcon ก่อนเปิด node ทุก terminal ต้องใช้ profile local ชุดเดียวกัน

### Terminal 1: mock Robot

```bash
source ~/ros2_ws/turtlebot-llm/setup_demo_auto_ip.sh local
ros2 run agent_pkg mock_robot --ros-args -p trip_duration_sec:=20.0
```

### Terminal 2: intent

```bash
source ~/ros2_ws/turtlebot-llm/setup_demo_auto_ip.sh local
ros2 run agent_pkg intent_node
```

### Terminal 3: subtitle

```bash
source ~/ros2_ws/turtlebot-llm/setup_demo_auto_ip.sh local
ros2 run agent_pkg subtitle_node
```

### Terminal 4: Backend และหน้าเว็บ

```bash
source ~/ros2_ws/turtlebot-llm/setup_demo_auto_ip.sh local
cd ~/ros2_ws/Mobile-Web-Voice-Text-Controller-Physical-and-Immersive-AI-/booth_web_controller
ROS_PROFILE=local USE_MOCK_ROS2=false HOST=0.0.0.0 PORT=8000 bash ./run_booth.sh
```

`USE_MOCK_ROS2=false` ให้ Backend ใช้ ROS bridge จริง ส่วน Robot จำลองรันแยกใน Terminal 1 ถ้าตั้ง `true` จะเป็น standalone Backend mock และไม่ใช้ intent/subtitle ใน terminal อื่น

รอ `Uvicorn running` แล้วเปิด <http://localhost:8000> สำหรับผู้ใช้ หรือ <http://localhost:8000/staff> สำหรับเจ้าหน้าที่ ใช้ PIN ที่ตั้งใน `.env` ของ Backend

บน iPhone/iPad ให้เปิดผ่าน HTTPS URL ที่เข้าถึง Backend นี้ได้และส่งต่อ WebSocket `/ws/status` ด้วย ไมค์ต้องใช้ secure context; HTTP บน IP ของเครื่องอื่นอาจใช้ไมค์ไม่ได้ `0.0.0.0` เป็น bind address ไม่ใช่ URL สำหรับเปิดบนมือถือ ใช้ HTTPS URL เดิมที่ตั้งไว้กับระบบ

หน้าแรกกด "ขอสิทธิ์ควบคุม" ก่อน แล้วลองพูดหรือพิมพ์ `ไปจุด A`, `ไปจุด B`, `ไปจุด C` ข้อความขึ้นที่ "หุ่นยนต์ได้ยินว่า:" ส่วนใต้ไมค์แสดงสถานะการรับ/ส่งเสียง ผล intent แยกจากสถานะการเดินของ Robot

แตะไมค์หนึ่งครั้งเพื่อเริ่ม แตะอีกครั้งเพื่อหยุดและส่ง หรือกดค้างแล้วปล่อยเพื่อส่ง หากต้องฟังไฟล์เสียงที่ส่งจริง ใช้ `?debug_audio=1` เช่น <http://localhost:8000/?debug_audio=1>

visitor "กลับจุดเริ่มต้น" หรือ "กลับ start" ตีความเป็น A ส่วน Staff/Auto-return ส่ง destination `A` พิกัด A/B/C ให้ทีม Robot map จริง

### Terminal 5: VLM พร้อมกล้อง (เลือกเปิด)

ต้องติดตั้ง dependencies และ build `vlm_pkg` ก่อน ไม่จำเป็นสำหรับทดสอบเสียง/ข้อความ/intent ดู `src/vlm_pkg/README.md` ใน TurtleBot workspace สำหรับการตั้งค่า API key และกล้อง

```bash
source ~/ros2_ws/turtlebot-llm/setup_demo_auto_ip.sh local
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
