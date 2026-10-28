# เชื่อม Subtitle จาก Backend ไป Unity VR

Backend เปิด `/ws/vr/subtitle` พร้อมเว็บเดิม ไม่ต้องเพิ่ม ROS node สำหรับ VR
ชุดวันงานอ้างอิง tag `release-2026-10-28` ของ Backend, LLM และ Unity ผู้ใช้ยืนยันว่าซับ VR แสดงและเปลี่ยนถูกจังหวะแล้ว
คู่มือผูกฉากและ receiver อยู่ใน [repo Unity](https://github.com/charkpongpaksa/Open-House-Project/blob/main/VR-SUBTITLE-INTEGRATION.md)
ตัวรับและไฟล์ `.meta` มีแล้วที่ [SubtitleWebSocketReceiver.cs](https://github.com/charkpongpaksa/Open-House-Project/blob/main/Assets/Scripts/Sources/SubtitleWebSocketReceiver.cs)

## เปิด Backend

เตรียม ROS interfaces และ environment ตาม [README](README.md) แล้วเปิด launcher เดิม:

```bash
cd ~/ros2_ws/Mobile-Web-Voice-Text-Controller-Physical-and-Immersive-AI-
bash booth_web_controller/run_tailscale.sh
```

ใช้พอร์ตที่ launcher แสดงใน log ค่าเริ่มต้นคือ `8000` และเปลี่ยนผ่าน `PORT` ได้
เมื่อ Backend เปิดอยู่แล้ว ไม่ต้องเปิด instance ซ้ำเพื่อรับ VR
Intent และ Subtitle ใช้ชุดเดิมตาม README

## ตั้งค่าฝั่ง VR

1. เพิ่ม `SubtitleWebSocketReceiver` ในฉาก Unity
2. ลาก `UnityEngine.UI.Text` ของแผงซับเข้า **Target** ใช้ฟอนต์ไทยเดิม
3. ใส่ `ws://<Backend-IP>:8000/ws/vr/subtitle` ใน **Subtitle Url**
4. ทดสอบการเชื่อมต่อ ภาษาไทย ข้อความใหม่ และ reconnect บนเครื่องเป้าหมาย

ใช้ IP ของ Backend ไม่ใช่ IP ของ Robot Bridge
ค่า `127.0.0.1` หมายถึงอุปกรณ์ที่รัน receiver จึงใช้ต่อกลับ Backend จาก Quest ไม่ได้
ถ้าใช้ Tailscale IP ต้องมีเส้นทางจาก Quest ถึง IP นั้นเอง การเปิด Tailscale บนคอมอย่างเดียวไม่พอ
เก็บ connection หุ่นเดิมไว้สำหรับสนาม LiDAR และสถานะหุ่น

## Contract

VR อ่านซับที่ ROS2Bridge ยอมรับแล้ว ไม่มีช่องส่งคำสั่งหุ่นผ่าน endpoint นี้
Backend ตรวจ timestamp, TTL และลำดับก่อนส่งข้อความเข้า hub

```json
{
  "type": "subtitle",
  "version": 1,
  "stream_id": "example-stream",
  "sequence": 1,
  "text": "กำลังพาไปจุด Aครับ",
  "source_stamp_unix_ms": 1793177958394,
  "request_id": "example-request",
  "observation_id": ""
}
```

- `sequence` เพิ่มภายใน `stream_id` เดียวกัน Backend restart สร้าง stream ใหม่
- เมื่อเชื่อมต่อหรือ reconnect จะได้ caption ล่าสุดทันที ถ้ายังไม่มี caption จะได้ข้อความว่างและ sequence ศูนย์
- VR เก็บซับล่าสุดจนมีข้อความใหม่ ROS TTL-clear ล้าง state ของเว็บ แต่ไม่ถอน caption ล่าสุดของ VR
- ซับที่ค้างไม่ใช่การยืนยันว่าสถานะหุ่นยังสด ถ้าต้องการถอนข้อความผิด ต้องตกลง clear contract เพิ่มก่อน
- Packet จำกัด 16,384 bytes UTF-8; client ที่ช้ารับข้อความล่าสุดแทนประวัติย้อนหลัง

## อ่าน stream โดยไม่ส่งคำสั่ง

ใช้ Python environment ที่มี package `websockets` แล้วรันจาก repo นี้:

```bash
python tools/watch_vr_subtitles.py ws://127.0.0.1:8000/ws/vr/subtitle
```

เปลี่ยน URL เป็น Backend IP เมื่อรันจากเครื่อง VR ใช้ `--once` เพื่ออ่าน snapshot เดียวแล้วออก
การเห็น snapshot ว่างยืนยัน handshake เท่านั้น ให้รอ caption จากการใช้งานปกติเพื่อตรวจการอัปเดต

## ตรวจ regression

รันบน ROS domain ทดสอบเท่านั้น ตัวอย่างนี้สมมติว่าติดตั้ง test dependencies ใน LLM `.venv` แล้ว:

```bash
cd ~/ros2_ws/Mobile-Web-Voice-Text-Controller-Physical-and-Immersive-AI-
source /opt/ros/jazzy/setup.bash
source ../turtlebot-llm/install-colcon/setup.bash
source ../turtlebot-llm/.venv/bin/activate
unset ROS_DISCOVERY_SERVER ROS_STATIC_PEERS ROS_SUPER_CLIENT
unset FASTRTPS_DEFAULT_PROFILES_FILE FASTDDS_DEFAULT_PROFILES_FILE FASTDDS_BUILTIN_TRANSPORTS
export ROS_DOMAIN_ID=174 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST ROS_LOCALHOST_ONLY=1
export ROS_LOG_DIR=/tmp/vr-subtitle-test-logs
export PYTHONPATH="$PWD/booth_web_controller:$PWD/../turtlebot-llm/src/agent_pkg:${PYTHONPATH:-}"
export GROQ_API_KEY= GROQ_SUBTITLE_API_KEY= GOOGLE_API_KEY= GOOGLE_FALLBACK_ENABLED=false
python -m pytest -q booth_web_controller/tests/test_vr_subtitle.py
node --test booth_web_controller/tests/*.js
bash booth_web_controller/tests/test_run_booth.sh
```

VR tests ตรวจ schema, validation, metadata, clear, reconnect และ ROS → ASGI WebSocket
ได้ทดสอบ local TCP WebSocket และซับจากหุ่นจริงมาถึง endpoint นี้แล้วระหว่าง debug
ผู้ใช้ยืนยันการแสดงซับและจังหวะอัปเดตใน VR แล้ว ส่วน agent ไม่ได้ compile Unity เอง และยังไม่มีรายละเอียดอุปกรณ์/รุ่น Quest ที่ใช้ยืนยัน ให้ตรวจกับชุดอุปกรณ์วันงานอีกครั้ง

ผลตรวจชุดรวมก่อน push `main` วันที่ 28 ตุลาคม 2026: Python **101 passed** (รวม VR 7 tests), JavaScript **27 passed** และ launcher smoke tests ผ่าน
Python มี warnings ของ pytest asyncio config 2 รายการและ FastAPI TestClient deprecation 1 รายการ
