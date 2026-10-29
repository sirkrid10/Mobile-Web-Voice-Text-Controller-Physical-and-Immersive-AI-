# รวม UI และ Static QR เข้า release ก่อนรวม STT

## เป้าหมาย

ให้ branch `release` มี UI ผู้เข้าชมล่าสุดจาก main และ Static QR/TunnelManager ที่ผ่าน review แล้ว โดยรักษาพฤติกรรม A-D, Home D, session, Staff และ subtitle เดิม
รอบนี้ไม่รวม `feat/stt` และไม่แก้ pipeline เสียง
Codex วางแผนและ review ส่วน luna implement และทดสอบ

## ฐานงานที่ตรวจ

Repository: `Mobile-Web-Voice-Text-Controller-Physical-and-Immersive-AI-`

- `origin/main`: `666b7f1` มี UI ใหม่และการรองรับ mock preview บน macOS ใน agent_runtime
- `origin/feat/static-qr-cloudflare`: `2763cef` มี Worker, TunnelManager, Staff status และคู่มือ
- `origin/feat/stt`: `1ef88c1` เก็บไว้รอบถัดไป ห้าม merge หรือ cherry-pick ในรอบนี้

การจำลอง UI + QR ที่ commit ข้างบน merge ได้โดยไม่มี text conflict ชุดทดสอบที่เลือกผ่าน Python 29 ข้อและ JavaScript 42 ข้อ
ยังต้องรันทดสอบรวมให้ครบหลังสร้าง release ผลข้างต้นไม่แทนการตรวจรอบใหม่
อ่าน `AGENTS.md` ที่เกี่ยวข้อง ตรวจ branch และ git status จริงก่อนเริ่ม จากนั้น fetch remote และบันทึก SHA ล่าสุด
ถ้า SHA เปลี่ยน ให้ตรวจ commits ใหม่ก่อนรวม ไม่ถือว่าแผนนี้รับรองโค้ดที่เพิ่มภายหลัง

## 1. เตรียม branch โดยไม่รบกวนระบบจริง

1. ตรวจ working tree รวมถึงไฟล์แผนนี้ ห้าม reset, clean หรือทิ้งงานที่ยังไม่ commit
2. ตรวจว่ามี local หรือ remote `release` อยู่แล้วหรือไม่ ถ้ามีให้อ่านประวัติและตรวจฐาน ห้ามเขียนทับหรือ force-push
3. ถ้ายังไม่มี release ให้สร้างจาก `origin/main` ล่าสุด แล้ว merge `origin/feat/static-qr-cloudflare` เข้า release
4. ใช้ merge เพื่อเก็บประวัติของทั้งสองชุด ไม่คัดลอกไฟล์ทับทั้งโฟลเดอร์ และไม่รวม STT
5. ระบบจริงกำลังรันจาก workspace หลักบน branch QR หากต้องสลับ branch ให้ทำ integration ใน worktree แยกที่มีชื่อชัดเจนก่อน
   ห้ามเปลี่ยนไฟล์ใต้ process จริงหรือ restart process ผู้ใช้เพื่อทดสอบงานนี้

worktree แยกเป็นพื้นที่ตรวจชั่วคราวเท่านั้น ก่อนส่งมอบต้องระบุว่า runtime ยังอยู่ branch ไหน ห้ามรายงานว่าผู้ใช้รัน release แล้วทั้งที่ยังไม่ได้สลับ
เมื่อถึงขั้นสลับ workspace จริงหลัง review ให้ตรวจว่าหุ่นไม่มีงานค้าง รักษา private `.env` และยืนยัน HEAD ตรงกับ release ที่รับงาน
หาก environment มองไม่เห็น process หรือเข้าถึง network ไม่ได้ ให้รายงานข้อจำกัด ไม่เดา PID และไม่อ้างผลผ่าน

## 2. รักษาพฤติกรรมของทั้งสองชุด

- เก็บ UI ใหม่: mission.css, logo, dark/light theme และ mobile layout
- เก็บหน้า Staff และ PIN gate, system status, terminal fallback และ Intent dispatch inspection
- เก็บจุด A กู้ภัย, B การแพทย์, C ส่งเสบียง, D ศูนย์บัญชาการ และ Home/Auto-return D
- เก็บ Worker redirect, health instance check, bounded KV retry และ process ownership ของ TunnelManager
- ใช้ launcher เดิม เมื่อ ENABLE_TUNNEL=false ต้องไม่เปิด cloudflared เมื่อ true ต้องปิด reload
- เก็บการรองรับ mock preview ของ agent_runtime บนแพลตฟอร์มที่ไม่มี /proc ห้ามย้อนทิ้งโดยเลือกไฟล์จาก QR ทั้งไฟล์
- ไม่เพิ่ม STT preprocessing, audio constraint, debug audio saving หรือ disconnect behavior จาก feat/stt ในรอบนี้
- ไม่เปลี่ยนสัญญา ROS, Robot, VR และไม่ส่ง navigation goal จริง

## 3. แก้เฉพาะสิ่งจำเป็นสำหรับ integration

1. ตรวจ script/CSS references ในหน้า visitor และ Staff ให้โหลดไฟล์ที่มีอยู่จริง ไม่มี module หรือ DOM ID ที่ถูกทิ้ง
2. กำหนด cache version ให้เหมาะกับ asset ที่เปลี่ยนจริง ไม่เปลี่ยนไฟล์เสียงเพียงเพื่อให้ diff ดูครบ
3. ตรวจ test_html_pages_served ใน tests/test_verification_protocol.py ซึ่งยังผูกกับคำว่า TurtleBot3 Controller
   UI ใหม่เปลี่ยนชื่อแล้ว ให้แก้ test ให้ตรวจชื่อหรือโครงสร้างปัจจุบันและหน้า visitor/Staff ที่เปิดได้ ไม่เปลี่ยน UI กลับเพื่อผ่าน test
4. README หลักต้องอธิบาย UI ปัจจุบันและการเปิด Static QR ด้วย launcher เดิม ระบุว่า feat/stt ยังไม่อยู่ใน release นี้
5. รักษา config ตัวอย่างเป็น placeholder ไม่คัดลอก token, account config, private .env หรือไฟล์ ~/.config/turtlebot-qr เข้ามาใน Git

## 4. ตรวจพฤติกรรมใน candidate เดียวกัน

ใช้ mock Backend บนพอร์ตว่าง เช่น 18003 โดยตั้ง USE_MOCK_ROS2=true, MANAGE_AGENT_NODES=false, ENABLE_TUNNEL=false และ AUTO_RETURN_ENABLED=false
ห้ามใช้พอร์ต 8000 หรือ runtime .env ของผู้ใช้ ให้ใช้ config ทดสอบแยก
ไม่เปิด tunnel ทดสอบที่เขียน production KV เพราะ URL บน QR กำลังชี้ Backend จริงอยู่

### Visitor UI และ session

- เปิดหน้าใน Chromium จริงที่ 320, 390, 768, 1440px ทดสอบ dark/light และจำธีมเมื่อ reload
- ขอสิทธิ์ เห็น A-D/Home D และส่ง text/chip บน mock ได้ ข้อความและผล intent ไม่ค้างจากคำสั่งเก่า
- เปิด browser context สองตัว ยืนยันว่าผู้ชมคนที่สองถูกจัดเป็นคิว และรับสิทธิ์ได้หลังคนแรกจบ session
- เลิก session และลอง claim ใหม่ได้ตาม behavior ปัจจุบัน ไม่แอบเพิ่ม fix จาก STT branch
- ตรวจ horizontal overflow, ปุ่มกดได้จริง และ JS console errors รวมหน้า active ที่มีข้อความยาว
- ทดสอบไมค์ด้วย fake device เฉพาะ flow เดิม เมื่อ STT ไม่พร้อมต้องแสดง error และให้ลองใหม่ได้ ไม่เรียก provider จริงเพื่อพิสูจน์ integration นี้

### Staff และ Robot contract

- ก่อนใส่ PIN อ่าน system API ไม่ได้ หลังใส่ PIN เห็น process, ROS/VR observation และ tunnel status
- โหมด mock ต้องไม่สร้าง Intent/Subtitle จริง
- ยืนยัน target Home/Auto-return D ด้วย fake bridge เท่านั้น และคำขอเสียงที่เสีย session ระหว่างรอไม่หลุดไป publish
- Subtitle และ Intent decision/dispatch ยังแสดงตาม contract เดิม ไม่ถือว่าปุ่มแสดง sent แปลว่า Robot นำทางสำเร็จ

### QR และ lifecycle

- รัน tests ของ Worker, TunnelManager, Staff system API, system health และ process manager
- ตรวจ ENABLE_TUNNEL=false กับ true ผ่าน fake cloudflared และ fake HTTP รวม lock/ownership/retry/shutdown
- เปิด main health endpoint แล้ว instance_id คงที่ใน backend instance เดียวกันและไม่มี secrets
- ทดสอบ launcher ด้วย tests/test_run_booth.sh
- Production Worker ถูก deploy และทดสอบแล้ว รอบนี้ไม่ deploy ซ้ำ ไม่สลับ production KV และไม่หยุด tunnel จริง

## 5. คำสั่งตรวจและหลักฐาน

เลือก Python environment ที่มี dependencies จาก requirements.txt พร้อม pytest/httpx อย่าใช้ environment ที่ขาด dependencies แล้วสรุปว่า code ล้ม
หากต้องสร้าง environment ให้แยกจาก runtime จริง

คำสั่งจากโฟลเดอร์ booth_web_controller:

```bash
python -m pytest -q tests
node --test tests/*.js
bash tests/test_run_booth.sh
```

ตั้งค่า mock ตามส่วนก่อนหน้าก่อนรัน Python tests
ROS contract tests ต้องมี rclpy/interfaces และใช้ ROS domain ทดสอบที่แยกจาก 30 หาก environment ไม่มี ให้แยกผลเป็น not run และรันชุดที่เหลือ ไม่ปลอม modules เพื่อให้รายงานเหมือนผ่านจริง
จาก cloudflare/robot-link รัน npm test และตรวจ bundle ด้วย dry-run ห้าม deploy
รายงานทุก failure/skip พร้อมสาเหตุ และแยก tests ที่ผ่านออกจากสิ่งที่ยังไม่ได้รัน

## 6. เกณฑ์ส่งตรวจ

- release candidate มี main UI และ QR ครบ ไม่มี commit จาก feat/stt ปะปน
- ไม่พบพฤติกรรม session, A-D/Home D, Staff, subtitle หรือ tunnel ที่ถอยหลัง
- Tests ที่เกี่ยวข้องผ่าน และมีหลักฐาน browser ของ visitor UI ใหม่
- ไม่มี secret, dependency directory, debug recording หรือ runtime config ใน diff
- ส่ง branch, SHA ฐาน, รายการ commit ที่รวม, วิธี resolve ถ้ามี, diff summary, ผล tests และตำแหน่ง worktree/runtime
- เก็บงานไว้ให้ Codex review ก่อน ยังไม่ commit งานแก้ใหม่, push release, merge main, deploy หรือสลับ runtime โดยไม่มีคำสั่งเพิ่ม

## รอบถัดไป

เมื่อ UI + QR ผ่านแล้ว จึงวางงานรวม feat/stt แยก โดยจัดการ prompt budget ที่รักษา D, dependency/สถานะ ffmpeg, timeout/cleanup, debug file format และข้อตกลง debug_audio ผ่าน URL กลาง
อย่าดึงงานเสียงมารวมเพื่อแก้ปัญหาที่ไม่ได้อยู่ในรอบนี้
