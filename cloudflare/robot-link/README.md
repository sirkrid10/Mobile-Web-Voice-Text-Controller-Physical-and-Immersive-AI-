# Cloudflare Worker: Static QR Redirect Service

บริการ Redirect URL คงที่สำหรับสแกน QR Code เข้าสู่ระบบควบคุมหุ่นยนต์ TurtleBot3 Mobile Web Controller เมื่อใช้งานร่วมกับ Cloudflare Quick Tunnel (`trycloudflare.com`)

---

## 1. ภาพรวมสถาปัตยกรรม (Architecture)

```
[ผู้เข้าชมบูธ]
      │  (1) สแกน QR Code ถาวร
      ▼
[Cloudflare Worker] (https://<worker-name>.<subdomain>.workers.dev/)
      │
      ├─► ตรวจสอบสิทธิ์ Method (GET/HEAD) และ Path (เฉพาะ '/')
      ├─► อ่านค่า key `robot_url` จาก KV `ROBOT_LINKS`
      ├─► ตรวจสอบความปลอดภัย URL (ต้องเป็น HTTPS และเป็น subdomain ของ trycloudflare.com เท่านั้น)
      │
      ▼  (2) HTTP 302 Found (Cache-Control: no-store, no-cache, must-revalidate)
[มือถือของผู้เข้าชม]
      │
      ▼  (3) วิ่งตรงไปยัง Quick Tunnel URL
[Cloudflare Quick Tunnel] (https://<active-tunnel>.trycloudflare.com/)
      │
      ▼
[Backend Web Controller] (WSL 2 / FastAPI port 8000)
```

### คุณสมบัติสำคัญ
- **QR Code ไม่เปลี่ยน**: สามารถพิมพ์ QR Code ติดบนตัวหุ่นยนต์หรือป้ายบูธได้ล่วงหน้า โดยชี้ไปที่ URL ของ Worker
- **ความปลอดภัยสูง (No Open Redirect)**: อนุญาตเฉพาะ HTTPS และ subdomain ของ `trycloudflare.com` ที่ถูกต้องเท่านั้น ปฏิเสธ userinfo, port แปลกปลอม, query, fragment, และโดเมนปลอมแปลง (suffix attacks เช่น `trycloudflare.com.evil.test`)
- **ไม่ยุ่งเกี่ยวกับ WebSocket หรือข้อมูลนำทาง**: Worker ทำหน้าที่เพียง HTTP 302 redirect ครั้งแรก เบราว์เซอร์จะเชื่อมต่อ session, WebSocket `/ws/status` และส่งเสียง STT กับ Quick Tunnel โดยตรง
- **Eventual Consistency**: Cloudflare Workers KV กระจายข้อมูลทั่วโลกแบบ eventually consistent (อาจใช้ 60 วินาทีหรือมากกว่า ตาม [เอกสาร Workers KV](https://developers.cloudflare.com/kv/concepts/how-kv-works/))

---

## 2. การเตรียมระบบและการ Deploy (Initial Setup)

### สิ่งที่ต้องเตรียม
- บัญชี Cloudflare (สมัครฟรีได้ที่ [cloudflare.com](https://dash.cloudflare.com/sign-up))
- Node.js (เวอร์ชัน 22.0.0 ขึ้นไป ตามข้อกำหนด `engines.node >= 22.0.0` ของ Wrangler 4)
- npm (เวอร์ชัน 10 ขึ้นไป)
- **ไฟล์ Config หลักไฟล์เดียว**: โปรเจกต์นี้ใช้ `wrangler.toml` เป็นไฟล์คอนฟิกหลักเพียงไฟล์เดียว และระบุ `--config wrangler.toml` ชัดเจนในทุกคำสั่ง

### ขั้นตอนติดตั้ง dependencies และสร้าง KV
1. เข้ามาที่โฟลเดอร์ Worker:
   ```bash
   cd ~/ros2_ws/Mobile-Web-Voice-Text-Controller-Physical-and-Immersive-AI-/cloudflare/robot-link
   ```

2. ติดตั้ง dependencies ตามเวอร์ชันที่ล็อกไว้แน่นอนด้วย `npm ci`:
   ```bash
   npm ci
   ```
   *(หมายเหตุ: คำสั่งนี้อ่าน `package-lock.json` เพื่อติดตั้ง Wrangler เวอร์ชัน `4.155.0` ตรงตามที่กำหนดไว้ ไม่เสี่ยงได้เวอร์ชันต่างกัน)*

3. ตรวจสอบเวอร์ชันของ Wrangler:
   ```bash
   npx wrangler --version
   ```
   ผลลัพธ์ควรแสดง `4.155.0` หรือเวอร์ชันตรงตามที่กำหนด

4. ตรวจสอบหรือเข้าสู่ระบบ Cloudflare ด้วย Wrangler CLI:
   ```bash
   npx wrangler login
   ```
   *(คำสั่งจะเปิดเบราว์เซอร์ให้กดยืนยันการอนุญาต)*

5. สร้าง KV Namespace สำหรับเก็บ URL (ใช้ `--config wrangler.toml`):
   ```bash
   # สร้าง Production KV
   npx wrangler kv namespace create ROBOT_LINKS --config wrangler.toml

   # สร้าง Preview KV (สำหรับทดสอบในเครื่อง)
   npx wrangler kv namespace create ROBOT_LINKS --preview --config wrangler.toml
   ```
   ผลลัพธ์จะแสดง ID เช่น:
   ```text
   [[kv_namespaces]]
   binding = "ROBOT_LINKS"
   id = "0123456789abcdef0123456789abcdef"
   ```

6. นำ `id` และ `preview_id` ที่ได้ ไปใส่ในไฟล์ `wrangler.toml`:
   ```toml
   [[kv_namespaces]]
   binding = "ROBOT_LINKS"
   id = "ใส่_KV_NAMESPACE_ID_จริงที่ได้"
   preview_id = "ใส่_PREVIEW_KV_NAMESPACE_ID_จริงที่ได้"
   ```

7. ทดสอบความถูกต้องของโค้ดและการ bundle ด้วย `--dry-run` (ไม่ deploy ขึ้นบัญชีจริง):
   ```bash
   npx wrangler deploy --dry-run --config wrangler.toml
   ```
   หรือใช้ npm script:
   ```bash
   npm run deploy:dry-run
   ```

8. เมื่อได้รับการอนุมัติให้ Deploy ขึ้น Cloudflare จริง:
   ```bash
   npx wrangler deploy --config wrangler.toml
   ```
   เมื่อเสร็จสิ้น Wrangler จะแจ้ง Production URL เช่น:
   `https://robot-link.<your-account-subdomain>.workers.dev`

> [!IMPORTANT]
> **ยังไม่พร้อมพิมพ์ QR จนกว่าจะทดสอบ production กับมือถือแล้ว**: ห้ามพิมพ์หรือเผยแพร่ QR Code ก่อนทำการทดสอบบนระบบ production จริงว่าโทรศัพท์มือถือสามารถสแกน, claim session และเชื่อมต่อ WebSocket ได้สำเร็จสมบูรณ์

---

## 3. การเปลี่ยน URL ปลายทางด้วยมือ (Manual Target Update)

เมื่อเปิด Backend พร้อม Quick Tunnel ใหม่ และได้ URL เช่น `https://quick-sample-tunnel.trycloudflare.com` ให้ปรับปรุงค่าใน KV ด้วยวิธีใดวิธีหนึ่งต่อไปนี้:

### วิธีที่ 1: ผ่าน Wrangler CLI (แนะนำใน Terminal)

> [!WARNING]
> **ข้อกำหนดสำคัญของ Wrangler v4**: ตาม [คู่มือ Migration Wrangler v3 -> v4](https://developers.cloudflare.com/workers/wrangler/migration/update-v3-to-v4/) คำสั่งเข้าถึงข้อมูลทั้งหมดของ Wrangler v4 จะทำงานใน **local mode เป็นค่าเริ่มต้น** ดังนั้นการเขียนค่าลง Production KV **จำเป็นต้องระบุแฟล็ก `--remote` เสมอ** มิฉะนั้นจะเขียนลงเฉพาะ Miniflare local emulator ของเครื่อง

```bash
npx wrangler kv key put --binding=ROBOT_LINKS "robot_url" "https://quick-sample-tunnel.trycloudflare.com" --remote --config wrangler.toml
```
หรือหากต้องการระบุ namespace id โดยตรง:
```bash
npx wrangler kv key put --namespace-id="<YOUR_KV_NAMESPACE_ID>" "robot_url" "https://quick-sample-tunnel.trycloudflare.com" --remote
```

### วิธีที่ 2: ผ่าน Cloudflare Dashboard (ผ่านหน้าเว็บ)
1. เข้าไปที่ [dash.cloudflare.com](https://dash.cloudflare.com/)
2. ไปที่เมนู **Storage & Databases** > **KV**
3. คลิกเลือก Namespace **ROBOT_LINKS**
4. กด **Add Entry** หรือแก้ไข Key เดิม:
   - **Key**: `robot_url`
   - **Value**: `https://quick-sample-tunnel.trycloudflare.com`
5. กด **Save**

> [!WARNING]
> การอัปเดตค่าใน KV ใช้เวลาแพร่กระจายไปยัง Cloudflare Edge ทั่วโลก (Eventual Consistency) **อาจใช้ 60 วินาทีหรือมากกว่า** ตาม [เอกสาร Workers KV](https://developers.cloudflare.com/kv/concepts/how-kv-works/) ในช่วงเวลานี้ผู้ใช้อาจได้รับ URL เดิมหรือค่าใหม่ขึ้นอยู่กับ Edge data center ที่เชื่อมต่อ และ**ยังไม่พร้อมพิมพ์ QR จนกว่าจะทดสอบ production กับมือถือแล้ว**

---

## 4. การทดสอบ (Testing & Verification)

### รัน Unit Tests ในเครื่อง (ไม่ต้องต่อเน็ต ไม่ต้องมีบัญชี Cloudflare)
ใช้ Node.js built-in test runner:
```bash
cd ~/ros2_ws/Mobile-Web-Voice-Text-Controller-Physical-and-Immersive-AI-/cloudflare/robot-link
node --test test/index.test.js
```

### ทดสอบ Dry-Run ก่อน Deploy
```bash
npx wrangler deploy --dry-run --config wrangler.toml
```
ยืนยันว่าการ bundle source code และการ validate config ผ่าน โดยไม่ส่งข้อมูลขึ้น Cloudflare account

### ทดสอบ Production URL ด้วย `curl`

1. **ตรวจสอบการ Redirect ปกติ (HTTP 302)**:
   ```bash
   curl -i https://<worker-name>.<subdomain>.workers.dev/
   ```
   - ต้องได้ `HTTP/... 302 Found`
   - มี Header `Location: https://<active-tunnel>.trycloudflare.com/`
   - มี Header `Cache-Control: no-store, no-cache, must-revalidate`

2. **ตรวจสอบคำขอ HEAD (ต้องไม่มี Response Body)**:
   ```bash
   curl -i -X HEAD https://<worker-name>.<subdomain>.workers.dev/
   ```
   - ต้องได้ `HTTP/... 302 Found` และ Content-Length: 0 หรือไม่มี body

3. **ตรวจสอบกรณีระบบยังไม่พร้อม / ค่าว่าง / ค่าผิดรูป (HTTP 503)**:
   (เช่น ก่อนใส่ค่าใน KV หรือใส่ค่าผิด)
   ```bash
   curl -i https://<worker-name>.<subdomain>.workers.dev/
   ```
   - ต้องได้ `HTTP/... 503 Service Unavailable`
   - ไม่มี Header `Location`
   - แสดงข้อความภาษาไทย: "ระบบยังไม่พร้อมให้บริการ"

4. **ตรวจสอบ Path อื่น (HTTP 404)**:
   ```bash
   curl -i https://<worker-name>.<subdomain>.workers.dev/staff
   ```
   - ต้องได้ `HTTP/... 404 Not Found`

5. **ตรวจสอบ Method อื่น (HTTP 405)**:
   ```bash
   curl -i -X POST https://<worker-name>.<subdomain>.workers.dev/
   ```
   - ต้องได้ `HTTP/... 405 Method Not Allowed`
   - มี Header `Allow: GET, HEAD`

---

## 5. แผนรับมือเมื่อระบบขัดข้อง (Fallback Procedures)

1. **กรณี Worker ล่ม หรือเข้าผ่าน QR ไม่ได้**:
   - ผู้ดูแลระบบสามารถคัดลอก Quick Tunnel URL โดยตรงจาก Terminal ของ WSL ที่เปิด Backend ส่งให้ผู้เข้าชม หรือสร้าง QR Code ชั่วคราวจาก URL ดังกล่าว
   - หรือให้ผู้เข้าชมเชื่อมต่อผ่าน Wi-Fi บูธและเข้าผ่าน Local IP เช่น `http://192.168.1.xxx:8000`

2. **กรณีหน้าเว็บค้างที่ URL เก่าหลังรีสตาร์ท Tunnel**:
   - Quick Tunnel ตัวเก่าจะหยุดทำงานทันทีเมื่อ process ปิดตัวลง
   - ผู้เข้าชมที่เปิดหน้าเว็บเดิมค้างไว้จะไม่ได้รับการย้ายอัตโนมัติ ให้ทำการสแกน QR Code ใหม่อีกครั้ง หรือรีเฟรชผ่าน URL ของ Worker

---

## 6. ข้อกำหนดด้านความปลอดภัย (Security Rules)

- **ห้าม Commit Secrets**: ไฟล์ config และ README จะใช้ placeholder เสมอ ห้าม commit Cloudflare API tokens, Account IDs หรือ Global keys
- **ไม่มี Public Update Endpoint**: เปลี่ยน KV ผ่าน CLI, Dashboard หรือ Backend ที่ใช้ API token เท่านั้น ผู้สแกน QR ไม่มีสิทธิ์เปลี่ยนปลายทาง

## เปิด Backend พร้อม tunnel อัตโนมัติ

ตั้งค่าครั้งแรกใน `booth_web_controller/.env` โดยเก็บค่าเดิมของระบบไว้:

```dotenv
ENABLE_TUNNEL=true
WORKER_STATIC_URL=https://robot-link.phongsapak-ket.workers.dev/
CLOUDFLARE_API_TOKEN=ใส่_token_ส่วนตัว
CLOUDFLARE_ACCOUNT_ID=ใส่_account_id
CLOUDFLARE_KV_NAMESPACE_ID=ใส่_namespace_id
CLOUDFLARE_KV_KEY=robot_url
```

Account ID อยู่ใน Workers & Pages ส่วน Namespace ID คือรหัสของ KV namespace ไม่ใช่ชื่อ `ROBOT_LINKS`
ใช้ API token ที่มี Workers KV Storage Edit/Write เฉพาะบัญชีที่ใช้งาน ห้ามส่ง token ในแชตหรือ commit private `.env`
ติดตั้ง `cloudflared` ให้เรียกผ่าน PATH ได้ก่อนเปิด Backend

เปิดระบบกับ Robot ผ่าน Tailscale ด้วยคำสั่งเดิม:

```bash
cd ~/ros2_ws/Mobile-Web-Voice-Text-Controller-Physical-and-Immersive-AI-
bash booth_web_controller/run_tailscale.sh
```

Backend เปิด Intent และ Subtitle ตามการตั้งค่า manager เดิม และเปิด cloudflared เพิ่มเมื่อ `ENABLE_TUNNEL=true`
ไม่ต้องเปิด tunnel ซ้ำด้วยมือ Launcher ปิด reload เมื่อเปิด tunnel อัตโนมัติ
หลังแก้ `.env` ให้เปิด Backend ใหม่ตอนที่หุ่นไม่มีงานนำทางค้างอยู่
การปิด Backend จะหยุด tunnel ที่ Backend เป็นเจ้าของ ส่วน URL กลางของ Worker ยังอยู่

เปิด `/staff` และตรวจสถานะ:

- Process running บอกว่า process cloudflared ยังทำงาน
- Target reachable บอกว่าตรวจ public health แล้วตรงกับ Backend instance นี้
- KV update accepted บอกว่า Cloudflare API รับค่าปลายทางแล้ว ไม่ยืนยันว่าทุกพื้นที่เห็นค่าใหม่ทันที

รอ DNS ของ hostname ใหม่และการเผยแพร่ค่า KV ก่อนทดสอบจากมือถือ หน้าเว็บเก่าที่เปิดค้างไว้ไม่ย้าย tunnel อัตโนมัติ ให้เปิด URL กลางหรือสแกน QR ใหม่
การเข้าหน้าเว็บสำเร็จไม่ยืนยันว่า Robot พร้อมนำทาง ต้องตรวจสถานะสดของ Robot แยกกัน

### รับมือเมื่ออัปเดตปลายทางไม่สำเร็จ

1. ถ้า Process ไม่ทำงาน ให้ตรวจว่าติดตั้ง cloudflared แล้ว บริการ Quick Tunnel อาจ timeout ตอนสร้าง tunnel ได้ เปิด Backend ใหม่เมื่อหุ่นไม่มีงานค้าง ตัว manager ไม่เปิด cloudflared ใหม่อัตโนมัติหลัง process ออก
2. ถ้า Process ทำงานแต่ Target reachable ยังไม่ผ่าน ให้รอการตรวจรอบถัดไป ตรวจอินเทอร์เน็ตและ DNS ก่อนแก้ network config ไม่ต้องเขียน KV ข้าม readiness check
3. ถ้า KV update ถูกปฏิเสธ ให้ตรวจ Account ID, Namespace ID และสิทธิ์ token ระบบลองเขียนสูงสุด 3 attempts สำหรับ URL เดิม ส่วน 401/403 หยุดทันที หลังแก้ config ให้เปิด Backend ใหม่เมื่อหุ่นไม่มีงานค้าง
4. ถ้าต้องปิดการเปิด tunnel อัตโนมัติ ให้ตั้ง `ENABLE_TUNNEL=false` แล้วเปิด Backend ใหม่ ใช้ `cloudflared tunnel --url http://127.0.0.1:8000` ใน terminal แยก และอัปเดต KV ผ่านคำสั่งในหัวข้อ Manual Target Update
5. ถ้าลิงก์กลางยังชี้ URL เก่า ให้ตรวจ KV acceptance และรอการเผยแพร่ค่า ซึ่งอาจใช้ 60 วินาทีหรือมากกว่า ไม่ต้องเปลี่ยน QR

ใช้ Backend ที่อัปเดต KV นี้เพียงเครื่องเดียวในเวลาเดียวกัน Lock ป้องกันได้เฉพาะ manager ซ้ำบนเครื่องเดียว
หากหยุด tunnel ที่เปิดเอง ให้กด Ctrl+C ใน terminal ของ tunnel นั้น อย่าใช้ `pkill cloudflared` เพราะอาจปิดของระบบอื่น

### สถานะทดสอบวันที่ 29 ตุลาคม 2026

Deploy Worker production แล้ว และทดสอบจากมือถือผ่าน URL กลางสำเร็จ
ทดสอบ Mock บนพอร์ต 18002 โดยเปลี่ยน tunnel แล้ว Backend อัปเดต KV เองและ Worker redirect ไป URL ใหม่สำเร็จ
จากนั้นปิด Mock เปิด Backend จริงพอร์ต 8000 และยืนยันการอัปเดต KV อัตโนมัติพร้อมการเปิด URL กลางจากมือถือแล้ว
การทดสอบนี้ไม่ได้ส่ง navigation goal ให้หุ่น และไม่ได้ยืนยันการทำงานของ VR

Config deploy ของเครื่องนี้อยู่ที่ `~/.config/turtlebot-qr/wrangler.toml` ซึ่งอยู่นอก repo ส่วน config ใน repo เป็นตัวอย่าง
หากแก้โค้ด Worker และต้อง deploy ใหม่ ใช้บัญชี Cloudflare ที่ล็อกอินและ config ฝั่งเครื่อง:

```bash
cd ~/ros2_ws/Mobile-Web-Voice-Text-Controller-Physical-and-Immersive-AI-/cloudflare/robot-link
npm ci
npx --no-install wrangler deploy --config "$HOME/.config/turtlebot-qr/wrangler.toml"
```

การเปลี่ยนชื่อ Worker หรือ subdomain ของบัญชีจะเปลี่ยน URL กลาง จึงต้องรักษาชื่อทั้งสองไว้หลังพิมพ์ QR
