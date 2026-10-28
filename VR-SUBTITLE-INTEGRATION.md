# เพิ่ม subtitle ใน Quest โดยให้งานฝั่ง VR น้อยที่สุด

แผนส่งต่องาน ณ 28 ตุลาคม 2026 อ้างอิง Unity 6000.3.26f1 ใน repo นี้
เอกสารนี้เป็นข้อตกลงงานที่เสนอ ตัวรับ Unity ยังไม่ได้สร้าง และ Backend ยังเป็น WIP ที่ต้องตรวจและทดสอบก่อนส่งมอบ

## สิ่งที่ฝั่ง VR ต้องทำ

1. รับ component subtitle ที่ฝั่ง Backend จะเตรียมให้ แล้วเพิ่มลงในฉาก `Assets/Scenes/ArenaQuest.unity` ใช้ใน `Arena3D.unity` ได้ด้วยสำหรับทดสอบบนคอม
2. ผูกช่องแสดงข้อความกับ `UnityEngine.UI.Text` บน world-space Canvas ที่มองเห็นในแว่น ใช้ `Assets/Resources/Fonts/NotoSansThai-Regular.ttf` ที่มีอยู่ และปิด rich text ถ้าแผงเดิมเหมาะสมให้เพิ่ม Text ในแผงเดิมได้เลย ไม่ต้องสร้างระบบ UI ใหม่
3. ตั้ง Subtitle URL ที่ฝั่ง Backend ส่งให้ใน Inspector แล้ว build และลองบน Quest จริง ตรวจภาษาไทย การตัดบรรทัด และ reconnect

ฝั่ง VR ไม่ต้องเขียน JSON parser หรือ reconnect เอง ไม่ต้องเพิ่ม package ไม่ต้องต่อ ROS และไม่ต้องเปลี่ยน Robot Bridge
ใช้ NativeWebSocket 2.x ที่อยู่ใน repo แล้ว ไม่ต้องเพิ่ม ClientWebSocket หรือ TextMeshPro เพื่อทำงานนี้

## สิ่งที่ฝั่ง Backend จะเตรียมให้

- Endpoint อ่านอย่างเดียว `/ws/vr/subtitle` บน Backend เดิม
- Component C# ที่ใช้ NativeWebSocket พร้อมช่อง URL และ Text ใน Inspector รวมการตรวจข้อมูล การอัปเดต UI บน main thread และการปิด connection เมื่อ component ถูก disable
- Reconnect อัตโนมัติ และจัดการ stream/sequence เมื่อ Backend เริ่มใหม่ โดยไม่ให้ callback ของ connection เก่าทับข้อความใหม่
- ตัวรับมีขอบเขตขนาดข้อความ เก็บเฉพาะ caption ล่าสุด และแสดง plain text
- URL ที่ใช้จริง คู่มือเริ่ม Backend และวิธีตรวจว่า endpoint ส่งข้อความได้
- ผลทดสอบ Backend และรายการที่ยังต้องตรวจใน Unity หรือบนแว่น

## การเชื่อมต่อ

```text
Robot Bridge เดิม : ws://<Robot-Bridge-IP>:8765
Subtitle เพิ่ม   : ws://<Backend-IP>:8000/ws/vr/subtitle
```

พอร์ต Backend เริ่มต้นคือ `8000` และเปลี่ยนได้ด้วย `PORT` ให้ใช้ค่าที่ Backend รันจริง
Subtitle ใช้ IP ของเครื่อง Backend ไม่ใช่ IP ของ Robot VM โดยอัตโนมัติ
Quest ต้องเข้าถึง URL นี้ได้เอง ใช้ Tailscale IP เมื่อแว่นมีเส้นทางถึงเครือข่ายนั้น หรือใช้ LAN IP ที่เข้าถึงกันได้
การต่อ Tailscale บนคอมเพียงเครื่องเดียวไม่ทำให้ Quest เข้าถึง Backend ได้

คง connection เดิมไว้สำหรับสนาม หุ่น LiDAR และสถานะกิจกรรม
`WebSocketContractSource` เดิมตรวจ `v=1` และ hello/Arena protocol จึงใช้รับ subtitle schema ด้านล่างตรง ๆ ไม่ได้
Component ใหม่รับ subtitle แยก โดยไม่แก้ protocol ของช่องเดิม

## รูปแบบข้อความจาก Backend WIP

ตัวอย่างตาม `VRSubtitleHub._encode()` ปัจจุบัน ค่าข้อความและ metadata เป็นตัวอย่าง:

```json
{
  "type": "subtitle",
  "version": 1,
  "stream_id": "example-backend-stream",
  "sequence": 1,
  "text": "กำลังเดินทางไปจุด A ครับ",
  "source_stamp_unix_ms": 1793145600000,
  "request_id": "example-request",
  "observation_id": "example-observation"
}
```

UI แสดงเฉพาะ `text` ส่วน metadata ใช้ใน receiver และการตรวจปัญหา
ตรวจ `type` และ `version` ก่อนใช้ข้อความ และใช้ `sequence` เปรียบเทียบภายใน `stream_id` เดียวกัน
เมื่อ stream เปลี่ยนให้รับ sequence ชุดใหม่ได้
ขนาด packet สูงสุดปัจจุบันคือ 16,384 bytes ของ UTF-8

เมื่อเชื่อมต่อ Backend ส่ง caption ล่าสุดทันที ถ้ายังไม่มี caption จะส่ง `text: ""` และ `sequence: 0`
หลังได้รับ caption ให้แสดงค้างจนมีข้อความใหม่ ROS TTL-clear จะไม่ล้าง caption ใน VR
เมื่อ disconnect ให้คง caption ล่าสุดไว้ แต่แยกสถานะการเชื่อมต่อออกจากข้อความ
ข้อความที่ค้างอยู่ไม่ได้ยืนยันว่าหุ่นยังอยู่ในสถานะนั้น
ไม่มีประวัติย้อนหลัง และ client ที่ช้าอาจข้ามข้อความระหว่างทางเพื่อรับข้อความล่าสุด

## ตรวจรับร่วมกัน

- ส่งข้อความภาษาไทยจาก ROS ผ่าน Backend แล้วเห็นข้อความเดียวกันใน Unity
- Robot Bridge และข้อมูลสนามเดิมยังทำงานระหว่างรับ subtitle
- ตัด connection แล้วต่อใหม่ได้ และได้รับ caption ล่าสุด
- เริ่ม Backend ใหม่แล้ว receiver รับ stream ใหม่ได้
- Disable component แล้ว connection หยุดและไม่มี callback เก่ามาแก้ UI
- ตรวจบน Quest จริงว่าอ่านภาษาไทยได้และข้อความอยู่ในตำแหน่งที่มองเห็น

Backend WIP เคยผ่าน VR tests 7 รายการตาม handoff แต่ยังต้องรันกับงานสุดท้ายอีกครั้ง
ยังไม่มีผลทดสอบ subtitle ผ่าน TCP/Tailscale, Unity หรือ Quest จริง
