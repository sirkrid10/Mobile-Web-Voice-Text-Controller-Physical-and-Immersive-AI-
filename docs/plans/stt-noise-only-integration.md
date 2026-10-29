# รวมเฉพาะการกรองเสียงเข้ากับ release

## เป้าหมายและฐานงาน

เพิ่มการกรองเสียงก่อนส่ง STT โดยรักษาพฤติกรรมของ release ที่รวม UI และ QR แล้ว
Codex วางแผนและ review ส่วน luna implement และทดสอบ

ฐาน release ที่ตรวจผ่านคือ `5b1af88` ซึ่งรวม main UI `666b7f1` และ QR `2763cef`
แหล่งโค้ดอ้างอิงคือ `origin/feat/stt` ที่ตรวจไว้ถึง `1ef88c1`
อ่าน AGENTS.md และ fetch ก่อนเริ่ม หาก SHA เปลี่ยนให้ตรวจ commits ใหม่ก่อนเลือกส่วนที่จะนำมาใช้

ห้าม merge `feat/stt` ทั้ง branch และห้าม cherry-pick commit ที่มีพฤติกรรมอื่นติดมาด้วย
สร้าง feature branch เช่น `feat/release-stt-noise` จาก `origin/release` แล้วเลือกปรับเฉพาะส่วนที่อยู่ในขอบเขตด้านล่าง
ทำใน worktree แยกเพื่อไม่เปลี่ยนไฟล์ใต้ Backend จริงที่กำลังรัน

## สิ่งที่นำมาใช้

- แนวทาง ffmpeg preprocessing ใน `app/stt_service.py`: high-pass, low-pass และแปลงเป็น mono PCM WAV 16 kHz
- ตัวเลือก normalize แยกจาก filter เพราะการปรับความดังไม่ได้ยืนยันว่าลด noise
- การเลือกส่งไฟล์ที่ preprocess สำเร็จเข้า provider เดิม และ fallback ไปไฟล์ต้นฉบับเมื่อใช้ preprocessing ไม่ได้
- Config, tests และคู่มือที่จำเป็นต่อส่วนนี้

เริ่มด้วย config ตามแนวทาง branch เพื่อน: high-pass 100 Hz, low-pass 7500 Hz และ normalize ที่ปิดแยกได้
อย่าอ้างว่าค่านี้ให้คุณภาพดีที่สุดก่อนเทียบเสียงจริง Filter นี้ไม่ได้แยกเสียงพูดคนอื่นออกจากเสียงผู้ใช้
หากใช้ dynaudnorm ให้ตรวจความหมาย parameters จาก ffmpeg ที่ใช้จริง ไม่คัดลอก comment ที่อธิบาย g=15 ว่าเป็น max gain

## สิ่งที่ต้องรักษาและห้ามนำเข้ามา

| ส่วน | ข้อตกลง |
| --- | --- |
| Frontend microphone | เก็บ getUserMedia และ gesture/recording lifecycle ของ release เดิม ไม่คัดลอกการเปิดหรือปิด noiseSuppression, echoCancellation หรือ autoGainControl จาก feat/stt |
| Prompt และภาษา | เก็บ STATION_SPEECH_HINT, validator, STT_LANGUAGE และ prompt ที่ส่ง provider แบบ release เดิม ไม่ใช้ prompt A/B/C ของเพื่อน และไม่เพิ่มการตัด 800 bytes ในงานนี้ |
| Destinations | เก็บ A-D, ชื่อโซน และ Home/Staff Return/Auto-return D |
| Session และ command | เก็บ token, claim, disconnect, inactivity, request_id, session_id และการตรวจ ownership ก่อน publish ไม่คัดลอก idempotent-disconnect/403 handling จาก feat/stt |
| Intent/Action/Subtitle | เก็บ ROS topics, interfaces, correlation, decision/dispatch และ subtitle contract เดิม |
| QR/Tunnel | เก็บ Worker, KV, instance readiness, ownership และ launcher เดิม ไม่ deploy หรือแก้ production KV |
| Debug audio | ไม่เอา STT_SAVE_DEBUG_AUDIO, latest_raw/latest_whisper หรือ UI/query debug เพิ่มเข้ามา จึงไม่ต้องแก้ Worker เพื่อ forward debug_audio ในรอบนี้ |
| UI และ Staff | เก็บ UI ที่ review แล้ว ไม่เพิ่ม redesign หรือ process controls ใหม่ |

การส่งเสียงที่ผ่าน filter อาจทำให้ transcript เปลี่ยนได้ นี่คือผลที่ต้องเทียบคุณภาพ ส่วน API schema และพฤติกรรมรอบข้างต้องเหมือนเดิม

## 1. เตรียมและระบุ diff ที่จะทำ

1. ตรวจ branch/worktree/dirty files ก่อน ห้าม reset หรือ clean งานเดิม
2. บันทึก SHA ของ release และ feat/stt ที่อ่านจริง
3. คาดว่าจะเพิ่มหรือแก้เฉพาะ `app/stt_service.py`, config, `.env.example`, tests และเอกสาร
4. อาจแยก subprocess/filter logic เป็น module เล็ก เช่น `app/audio_preprocessing.py` ถ้าช่วยแยก ownership/cleanup ชัดเจน ไม่สร้าง manager หรือ framework เพิ่ม
5. ถ้าจำเป็นต้องแก้ `static/app.js`, session_manager, main command routes หรือ ROS bridge ให้หยุดส่วนที่ขยายขอบเขตและส่งเหตุผลให้ Codex review ก่อน

## 2. ออกแบบ preprocessing ที่ย้อนปิดได้

ใช้ `STT_PREPROCESS_AUDIO=false` เป็นค่าเริ่มต้นใน config และตัวอย่าง `.env` ของ release รอบแรก
เปิดใช้เฉพาะ config ทดสอบจนผ่านการเทียบเสียงจริง การปิด flag ต้องกลับไปส่งไฟล์ต้นฉบับโดยไม่ spawn ffmpeg
ไม่แก้ private `.env` ของ runtime ผู้ใช้ในงานนี้

Config ที่ต้องมี:

- เปิด/ปิด preprocessing
- ความถี่ high-pass และ low-pass โดย 0 หมายถึงปิด filter ตัวนั้น
- เปิด/ปิด normalization แยกได้
- timeout ประมวลผลที่มีขอบเขตชัดเจน

Validate config ที่ขอบระบบ: ไม่รับ NaN/Infinity, timeout ต้องมากกว่า 0, ความถี่ต้องอยู่ในช่วงที่ ffmpeg/output sample rate รองรับ และ high-pass ต้องต่ำกว่า low-pass เมื่อเปิดทั้งคู่
ระบุค่า timeout เริ่มต้นที่เลือกและเหตุผลในรายงาน โดยคำนึงถึงเวลารอของผู้ใช้ ไม่เพิ่ม timeout ของระบบส่วนอื่นเพื่อกลบปัญหา

## 3. จัดการ subprocess และไฟล์ให้ครบ

1. ใช้ Linux ffmpeg ใน WSL และบันทึกวิธีติดตั้ง/ตรวจเวอร์ชันในคู่มือ อย่านำ ffmpeg.exe มาใช้กับ /tmp path โดยสมมติว่าอ่านไฟล์ได้
2. ใช้ argument list กับ create_subprocess_exec ไม่ใช้ shell command string
3. รอ communicate แบบมี timeout ระหว่างรอต้องไม่ block event loop ของ Backend
4. เมื่อ timeout, request ถูก cancel หรือเกิด exception ให้ terminate/kill และ await process ที่ตัวเองสร้าง พร้อมเก็บกวาด output ชั่วคราว
5. Cancellation ต้องส่งต่อเป็น cancellation ห้าม fallback แล้วส่งคำสั่งต่อหลังผู้ใช้ยกเลิก
6. ถ้า ffmpeg ไม่มี, exit nonzero, timeout หรือ output ใช้ไม่ได้ ให้ fallback ไปไฟล์ต้นฉบับและรายงานสาเหตุโดยไม่ปล่อย provider secrets
7. แต่ละ request ใช้ไฟล์ของตัวเอง ห้ามใช้ชื่อ latest ร่วมกัน
8. ตรวจว่า output ไม่ว่างและเป็น WAV ที่อ่านได้ ก่อนส่ง provider
9. transcribe สำเร็จหรือล้มเหลวต้องลบไฟล์ raw/processed ที่สร้างไว้ครบ รวมไฟล์ partial ตอน preprocessing ล้ม

ใช้ log แบบกระชับเพื่อแยก disabled, processed และ fallback พร้อมสาเหตุ ห้ามอ้างว่าเปิด flag แล้วแปลว่ากรองเสียงสำเร็จ
ไม่จำเป็นต้องเพิ่มหน้า Staff ใหม่เพื่อทำส่วนนี้

## 4. ทดสอบพฤติกรรมที่สังเกตได้

### Unit และ subprocess

- ปิด flag แล้ว provider ได้ bytes เดิมและไม่มี subprocess
- ffmpeg ไม่อยู่แล้ว fallback ได้ โดยไม่ทำให้ command API เปลี่ยน schema
- สำเร็จแล้ว provider ได้ไฟล์ WAV 16 kHz mono ที่ผ่าน filter จริง
- nonzero/empty/invalid output และ timeout fallback พร้อมลบ partial output
- cancel ระหว่าง communicate ต้องหยุด child และไม่ส่งต่อ provider
- mock binary discovery ใน unit tests ไม่ทำให้ผลขึ้นอยู่กับว่าเครื่องมี ffmpeg หรือไม่
- ทดสอบ Linux ffmpeg จริงแยกจาก unit tests ถ้าข้ามต้องรายงานชัดว่าไม่ได้พิสูจน์ pipeline จริง

### Compatibility กับ release

- ส่ง fixture เดิมไป Groq/OpenAI/local adapter จำลอง ตรวจ model, language และ prompt ว่าไม่เปลี่ยนจากฐาน release มีเพียงไฟล์เสียงที่เลือกส่งเปลี่ยน
- ตรวจ A-D/Home D ทั้ง prompt/catalog และ fake bridge
- ถ้า session เปลี่ยนระหว่าง preprocessing/STT คำสั่งเก่าต้องไม่ publish
- หลัง preprocessing/provider ล้มเหลว UI ต้องลองใหม่ได้ตาม flow เดิม
- Request สองตัวไม่อ่าน/ลบไฟล์ของกันและกัน
- Text/chip, Staff, subtitle และ TunnelManager tests เดิมต้องผ่าน
- Python, JavaScript, launcher และ Worker tests ต้องผ่านใน candidate เดียวกัน
- ถ้ารัน ROS contract tests ให้ใช้ localhost domain แยก เช่น 178 และถอด discovery/profile ของจริง ห้ามส่ง tests เข้า domain 30

## 5. พิสูจน์คุณภาพก่อนเปิดเป็นค่าใช้งานจริง

เก็บชุดเสียงทดสอบที่ได้รับอนุญาต แยกจาก Git และ secrets ใช้เสียงต้นฉบับเดียวกันเปรียบเทียบ flag off/on
ให้มีคำสั่ง A/B/C/D, ชื่อโซน, กลับศูนย์บัญชาการ และบทสนทนาทั่วไปในสภาพเงียบกับมี noise
ตรวจ transcript ว่าถูกต้อง รวมถึงกรณีคำพูดค่อยหรือคำสั้น และวัดเวลาประมวลผลเพิ่ม
ถ้าจะเรียก STT provider จริงให้รายงานจำนวนตัวอย่างและผลจริง ไม่อ้างจาก fake provider ว่าคุณภาพดีขึ้น
เสียงสังเคราะห์ใช้ตรวจ filter ทำงานได้ แต่ไม่แทนการพิสูจน์ STT กับเสียงพูดจริง
หากยังไม่ได้เทียบเสียงจริง ให้ส่ง implementation ที่ปิด flag ไว้เป็นค่าเริ่มต้น และระบุว่ายังไม่พร้อมเปิดใช้วันงาน

## 6. คู่มือและ rollback

README ต้องมี dependency Linux ffmpeg, วิธีตรวจ binary, config ที่เพิ่ม, log เมื่อ fallback และคำสั่งรัน Backend เดิม
หากผลเสียงแย่ลง ให้ตั้ง `STT_PREPROCESS_AUDIO=false` แล้วเปิด Backend ใหม่ตอนหุ่นไม่มีงานค้าง ห้าม restart ระหว่างนำทาง
การย้อน flag ต้องไม่เปลี่ยน QR, session, ROS หรือ prompt
เก็บ release UI+QR `5b1af88` เป็นฐานที่ไม่ต้องใช้ preprocessing เพื่อกลับไปใช้งานได้

## ส่งให้ Codex review

ส่ง base SHA, branch/worktree, diff summary, ผล unit/integration/real-ffmpeg tests, สิ่งที่ยังไม่ได้พิสูจน์ และหลักฐานว่าไม่มี commit หรือพฤติกรรมอื่นจาก feat/stt ปะปน
ระบุ runtime จริงยังอยู่ branch/commit ใด ห้ามสลับ runtime หรือแก้ private .env ให้ผู้ใช้เอง
หาก environment ไม่มี network/process permission ให้รายงานตามจริง ไม่สร้าง lockfile หรือ test results ขึ้นเอง
ยังไม่ merge กลับ release/main, commit, push หรือเปิด preprocessing ในระบบจริงจนกว่าจะมีคำสั่งเพิ่ม
