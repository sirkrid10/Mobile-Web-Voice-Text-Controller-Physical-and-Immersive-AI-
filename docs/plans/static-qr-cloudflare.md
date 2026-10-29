# แผนส่งงาน agy: QR คงที่สำหรับหน้าเว็บหุ่น

สถานะวันที่ 29 ตุลาคม 2026: implement และ deploy แล้ว ทดสอบเปลี่ยน tunnel บน Mock และสลับ URL กลางไป Backend จริงพร้อมเปิดจากมือถือสำเร็จ ข้อความด้านล่างเก็บขอบเขตงานเดิม คู่มือใช้งานปัจจุบันอยู่ที่ `cloudflare/robot-link/README.md`

## เป้าหมายและบทบาท

ผู้เข้าชมสแกน QR เดิมบนหุ่น แล้วเข้าเว็บ Backend ล่าสุดได้ แม้ Quick Tunnel เปลี่ยน URL
Codex วางแผนและ review ส่วน agy implement ทดสอบ และรายงานหลักฐาน
ส่งช่วงที่ 1 ให้ตรวจผ่านก่อนเริ่มช่วงที่ 2 ไม่ merge หรือ push จนกว่าผู้ใช้สั่ง

Repository คือ `Mobile-Web-Voice-Text-Controller-Physical-and-Immersive-AI-`
ฐานงานที่ตรวจคือ main `02c1695` ให้ตรวจ Git และ AGENTS.md อีกครั้งก่อนเริ่ม
สร้าง feature branch ใน workspace ที่ผู้ใช้ใช้งานจริง ห้ามทับงานที่มีอยู่
งานนี้ไม่ต้องแก้ LLM หรือ Unity

## ข้อตกลงร่วม

- QR เก็บ URL ของ Worker บน `workers.dev` เท่านั้น ไม่เก็บ URL Quick Tunnel
- Worker redirect ไปหน้า `/` ของ Quick Tunnel ด้วย HTTP 302 และ `Cache-Control: no-store`
- Worker เป็น redirect service ไม่ proxy หน้าเว็บหรือ WebSocket
- Backend และ browser ใช้ origin ของ Quick Tunnel ตามเดิม รวมถึง session และ WebSocket
- เมื่อ tunnel เปลี่ยน หน้าเว็บที่เปิด URL เก่าค้างอยู่ไม่ย้ายตาม ผู้ใช้ต้องเปิดลิงก์กลางหรือสแกนใหม่
- KV มี eventual consistency อาจเห็นค่าเก่านาน 60 วินาทีหรือมากกว่า ห้ามสัญญาว่าเปลี่ยนทันที
- ไม่เปลี่ยนการเชื่อม Robot, Tailscale, ROS, VR หรือสิทธิ์ควบคุมและ session ของระบบเดิม
- ไม่ส่ง navigation goal จริงเพื่อทดสอบ และไม่ restart Intent หรือ Subtitle เพื่อทำงานนี้
- ไม่ commit หรือแสดง API token, Staff PIN, secrets หรือ private .env

## ช่วงที่ 1: Worker และการเปลี่ยนปลายทางด้วยมือ

ผลที่ต้องได้: URL คงที่ใช้งานได้โดยไม่ต้องเปลี่ยน launcher เดิม

### งาน implement

1. เพิ่ม Worker ในโฟลเดอร์แยก เช่น `cloudflare/robot-link/` พร้อม Wrangler config ตัวอย่างและคำสั่งทดสอบ
2. ใช้ KV binding `ROBOT_LINKS` และ key `robot_url` เป็นที่เก็บปลายทางหนึ่งรายการ
3. รองรับ GET และ HEAD ที่ `/` เท่านั้น เส้นทางอื่นตอบ 404 และ method อื่นตอบ 405
4. ตรวจค่าจาก KV ด้วย URL parser อนุญาตเฉพาะ HTTPS hostname ซึ่งเป็น subdomain จริงของ `trycloudflare.com`
   ปฏิเสธ userinfo, port ที่กำหนดเอง, query, fragment และ path ที่ไม่ใช่ `/` ปฏิเสธ suffix หลอก เช่น `trycloudflare.com.evil.test`
5. ถ้าไม่มีค่าหรือค่าผิดรูป ตอบ 503 พร้อมข้อความภาษาไทยว่าเว็บยังไม่พร้อม และไม่ redirect
6. ไม่เพิ่ม public endpoint สำหรับเปลี่ยน URL ในรอบนี้ ใช้ Cloudflare Dashboard หรือ CLI ที่ยืนยันตัวตนแล้ว
7. เพิ่มคู่มือสร้างบัญชีและ Worker, สร้าง KV, ผูก binding, deploy, เปลี่ยน URL, ตรวจผล และ fallback
   ใช้ placeholder สำหรับ account และ namespace ID ระบุคำสั่งตาม Wrangler เวอร์ชันที่เลือกจริง
8. เพิ่มลิงก์คู่มือใน README หลัก ระบุชัดว่าคำสั่งรันเดิมยังใช้ได้

### เกณฑ์รับงาน

- URL ที่ถูกต้องให้ status 302, Location ถูกต้อง และ no-store ทั้ง GET และ HEAD โดย HEAD ไม่มี body
- ค่าว่าง ค่าผิด และ hostname หลอกไม่ทำให้ redirect ออกไปที่อื่น
- 503 และข้อผิดพลาดไม่ถูก cache และไม่เปิดเผยข้อมูลภายใน
- เปลี่ยนจากปลายทางทดสอบ A เป็น B แล้วเปิด URL กลางเดิมไป B ได้หลัง KV เผยแพร่ค่าใหม่
- เปิดเว็บจากมือถือผ่าน URL กลางแล้ว claim session และเชื่อม WebSocket ได้ โดยไม่สั่งหุ่นเดิน
- ไม่มี Cloudflare credentials ในไฟล์ tracked, log หรือหน้าเว็บ

### หลักฐานส่งตรวจ

ส่ง unit tests ของ Worker และ validation พร้อมคำสั่งรันจริง
ส่งผล HTTP สำหรับ redirect, unavailable, invalid target และวิธีเปลี่ยนค่า
ถ้ายังไม่มีบัญชีหรือ resource จริง ให้รายงานว่า local tests ผ่านแต่ยังไม่ทดสอบ deploy ห้ามกล่าวว่าพร้อมพิมพ์ QR
ก่อนพิมพ์ QR ต้องยืนยัน URL production ที่ผู้ใช้เป็นเจ้าของและทดสอบสแกนจากมือถือแล้ว

## ช่วงที่ 2: เปิด tunnel และอัปเดตปลายทางอัตโนมัติ

เริ่มหลังช่วงที่ 1 ผ่าน review ผลที่ต้องได้คือเปิดระบบครั้งเดียวแล้วอ่านสถานะจาก Staff ได้

### งาน implement

1. เพิ่ม opt-in launcher หรือ option ที่เรียก Backend launcher เดิมและเปิด Quick Tunnel ไป `127.0.0.1:8000`
   ค่าเริ่มต้นของ `run_tailscale.sh` และ `run_booth.sh` ต้องยังทำงานแบบเดิม
2. แยกตัวดูแล tunnel และตัวอัปเดต KV ออกจาก ROS process manager ห้ามให้ tunnel ล่มแล้วปิด Backend หรือ agent nodes
3. อ่าน URL จาก output ของ cloudflared ด้วย parser ที่ทดสอบได้ ตรวจ URL แบบเดียวกับช่วงที่ 1
4. รอ Backend พร้อม และตรวจปลายทางใหม่ผ่าน public tunnel ด้วย read-only request ที่มี timeout ก่อนเขียน KV
   เลือก endpoint ที่ระบุตัวแอปได้โดยไม่ส่งคำสั่ง ไม่อ้างว่าแค่ HTTP 200 ใด ๆ คือ Backend พร้อม
5. ใช้ Cloudflare API token สิทธิ์เท่าที่ต้องใช้กับบัญชีและ KV ที่ระบุ เก็บฝั่งเครื่องเท่านั้น
   ไม่เพิ่ม public update endpoint และไม่ส่ง token ไป frontend
6. เขียนเมื่อ URL เปลี่ยนเท่านั้น กำหนด timeout และ retry แบบจำกัดพร้อม backoff
   ถ้า API ล้มเหลวให้รักษาค่าเดิมและแสดง error โดยไม่ทำให้ระบบหุ่นล่ม
7. ป้องกัน launcher ซ้ำไม่ให้เปิด tunnel สองตัวหรือแย่งเขียนปลายทางเดียวกัน
   จัดการเฉพาะ process ที่ launcher เป็นเจ้าของ ใช้แนวทาง ownership ของระบบเดิมเมื่อเหมาะสม
8. เพิ่มข้อมูลใน Staff ผ่าน API ที่ตรวจ Staff PIN เดิม แสดง URL กลาง, URL tunnel ปัจจุบัน, process status,
   เวลาตรวจปลายทางสำเร็จ, เวลาเขียน KV สำเร็จ และ error ล่าสุดที่ตัด secrets แล้ว
   แยกสถานะ tunnel connected, target reachable และ KV update accepted อย่างชัดเจน
   ไม่อ้างว่า KV update accepted แปลว่าทุกพื้นที่เห็นค่าใหม่แล้ว
9. หน้า Staff ใช้รูปแบบเดิม รองรับ desktop, iPad และมือถือ ให้คัดลอก URL กลางได้
   ปุ่ม start, stop หรือ restart tunnel ยังไม่อยู่ในขอบเขตนี้ ใช้ terminal ก่อน
10. เพิ่มคำสั่ง fallback ในแท็บคู่มือและ README สำหรับเปิด tunnel เอง, เปลี่ยน KV เอง และหยุด process ที่เป็นเจ้าของ
    ห้ามใช้ `pkill cloudflared` แบบครอบคลุมทุก process

### พฤติกรรมเมื่อขัดข้อง

- Cloudflared ไม่ติดตั้ง: รายงานสาเหตุและวิธีติดตั้ง Backend ต้องยังรันได้
- Backend ยังไม่พร้อมหรือ public URL ตรวจไม่ผ่าน: ยังไม่เขียน KV
- Cloudflare API ปฏิเสธหรือ timeout: แสดงสถานะอัปเดตไม่สำเร็จพร้อม retry ที่จำกัด
- Tunnel ปิด: แสดงสถานะ disconnected ค่า KV เดิมอาจยังชี้ URL ที่ใช้ไม่ได้ ต้องอธิบายตามจริง
- ไม่ลบ KV อัตโนมัติเมื่อ shutdown เพราะ launcher เก่าอาจลบค่าที่ launcher ใหม่เพิ่งเขียน
- ปิด launcher: เก็บกวาดเฉพาะ process ที่ตัวเองสร้างตาม ownership ที่ระบุในคู่มือ
- Runtime อื่นที่ใช้ Worker และ KV เดียวกันต้องหยุดการอัปเดตอัตโนมัติก่อนสลับเครื่อง รอบนี้รองรับผู้เขียนหนึ่งเครื่องเท่านั้น

### เกณฑ์รับงานและการทดสอบ

- ทดสอบ parser, URL validation, ready probe และ Cloudflare API ด้วย fake process และ fake HTTP
- ทดสอบว่าค่าเดิมไม่ถูกเขียนทับเมื่อ target ตรวจไม่ผ่านหรือ API ล้มเหลว
- ทดสอบ retry มีขอบเขต เปิดซ้ำถูกป้องกัน และ shutdown ไม่ kill process ภายนอก
- ทดสอบ Staff ไม่เปิดข้อมูลโดยไม่มี PIN และไม่เผย credentials
- ทดสอบ UI แสดง disconnected, checking, update failed และ update accepted ได้ถูกต้อง
- ทดสอบ launcher เดิมและ tests ที่เกี่ยวข้องกับ Staff และ process manager ผ่าน
- ทดสอบจริงโดยเปิด tunnel A แล้วปิดและเปิด B สแกน QR เดิมเข้าถึง B หลัง KV เผยแพร่ค่า
- การทดสอบจริงใช้ mock Backend ได้ ห้ามใช้การเคลื่อนหุ่นเป็นเงื่อนไขพิสูจน์งานนี้

## การตั้งค่าภายนอกและการส่งมอบ

agy เตรียมโค้ด ตัวอย่าง config และคู่มือให้ตรวจได้ก่อน deploy
หากไม่มี account หรือสิทธิ์ Cloudflare ให้ถามผู้ใช้เฉพาะขั้นตอนที่ต้องทำบนบัญชี อย่าขอ token ในแชต
การ deploy ครั้งแรกต้องใช้บัญชีของผู้ใช้และได้รับคำสั่งให้ deploy ก่อน

แต่ละช่วงส่ง branch, commit ถ้ามี, รายการไฟล์สำคัญ, คำสั่งและผลทดสอบจริง, ข้อจำกัด และสถานะ workspace local
Codex ตรวจ diff เทียบเกณฑ์รับงานก่อนแนะนำให้รวมเข้า main

## เอกสารอ้างอิง

- [Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
- [Workers KV consistency](https://developers.cloudflare.com/kv/concepts/how-kv-works/)

ตรวจเอกสาร Cloudflare ปัจจุบันอีกครั้งตอนเลือก Wrangler, API และ deployment config
ไม่บันทึกโควตาหรือราคาจากความจำ ให้ลิงก์เอกสารปัจจุบันหากต้องระบุ
