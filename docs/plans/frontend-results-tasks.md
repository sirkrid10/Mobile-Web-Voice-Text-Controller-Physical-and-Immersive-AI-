# Frontend result display — Luna handoff

Status: plan only; start implementation when user requests it.
Repository: /home/lilieay/ros2_ws/Mobile-Web-Voice-Text-Controller-Physical-and-Immersive-AI-
Branch: feat/robot-integration. Current backend commit: a15e9e8.

## User constraints and Git workflow

Show the data the backend already sends in the existing web pages. No VR changes, conversational memory, quick-chip routing changes, retry/recovery or robot/intent policy changes. Keep start/wait flowing to intent; routing changes remain backlog. Preserve existing subtitle behavior.

Commit each completed coherent feat/fix separately after its relevant checks; do not wait to combine all work into one commit. Examples below are suggested boundaries, not a requirement to split a working feature into broken intermediate commits. User authorizes local commits only: NO PUSH, PR, merge or remote updates. Stage explicit files; exclude docs/plans and unrelated work. Check status/branch/diff before each commit and never amend existing commits without need. No specific Git guide was found previously; read one if discovered and preserve these explicit user constraints.

## Grounding (pstack sharpen)

Raw sources inspected: static/app.js, index.html, staff.html, styles.css, app/models.py and SessionManager state contract. app.js parses each /ws/status frame as a full state snapshot and currently renders robot_state/current_goal/heard_text/llm_reason. It ignores latest_intent/latest_action. staff.html polls /api/v1/state every2s and displays raw JSON, so new fields already appear there as diagnostics; it has no dedicated outcome display.

Existing backend contract:
- latest_intent nullable: request_id, session_id, stamp{sec,nanosec}, status NAVIGATE/CLARIFY/UNSUPPORTED/FAILED, destination_id, message, error_code(string).
- latest_action nullable: request_id, source, destination_id, outcome sending/accepted/unavailable/rejected/succeeded/aborted/canceled/failed/transport_error, ros_status nullable, error_code(int nullable), error_msg.
- Text/voice command responses add request_id/session_id; status sent is a dispatch acknowledgement.
- New visitor submission clears latest_intent; session release clears it. latest_action describes BACKEND-owned direct goals (staff/auto-return), not intent_node goals. NavigationState remains the source of physical robot state.

Chosen shape: add an intent section to the existing visitor card and a direct-action section in the staff dashboard. Use existing WebSocket/polling and small rendering functions; no new transport, framework, design system or generic event/state service. Keep llm_reason as subtitle content; label it accurately instead of calling it LLM reasoning. Do not duplicate result text into subtitle.

## Task 1 — Show intent status and clarify text on the visitor page

Files: static/index.html, static/app.js, static/styles.css as necessary.
- Add a clearly labelled result area, e.g. “ผลแปลงคำสั่ง (Intent)”, separate from subtitle and physical robot state. Use current card/style conventions; fit mobile widths.
- Render current latest_intent through one helper, e.g. renderIntentResult(state). It must tolerate absent/null fields from older snapshots without exceptions.
- Display mappings:
  NAVIGATE -> “แปลงคำสั่งเป็นการนำทาง” + destination label. This is not proof of acceptance/movement.
  CLARIFY -> “ขอข้อมูลเพิ่มเติม” + exact message (the question).
  UNSUPPORTED -> “คำสั่งนี้ยังไม่รองรับ” + message when supplied.
  FAILED -> “แปลงคำสั่งไม่สำเร็จ” + message when supplied; fallback “ลองส่งคำสั่งใหม่อีกครั้ง”. Show supplied error_code as a separate detail if useful, without fabricating a reason.
- Resolve destination labels using existing state.locations; fallback to destination_id for unknown IDs. Do not change location definitions/chip routing.
- No result -> “ยังไม่มีผลแปลงคำสั่ง” (neutral). During a known current submission, “กำลังส่งคำสั่ง” then “ส่งแล้ว รอผลแปลงคำสั่ง” may be used; do not create an unbounded spinner, automatic resend, artificial FAILED, or claim an error just because no intent result arrives.
- Render source strings with textContent, not interpolated innerHTML; long messages must wrap. Use aria-live=polite for the outcome content without announcing the entire state on every heartbeat.
- Rename the old “ความคิดและการตัดสินใจ (LLM Reasoning)” label to reflect that llm_reason is existing subtitle text. Empty subtitle should be blank/neutral rather than “กำลังรันการประมวลผลคำสั่ง”, which implies processing without evidence.
- Acceptance: all4 statuses and null/absent/unknown status have a usable display; message and destination shown accurately; malicious markup rendered as text; subtitle clear/TTL cannot erase intent; NAVIGATE does not alter physical status or imply robot accepted a goal.
- Commit: feat(frontend): display intent results and clarify messages

## Task 2 — Match visitor submission feedback to the correct request

Files: static/app.js (and small markup if needed).
- Both text/chip and voice use response request_id/session_id and state latest_intent identities. Keep only the current submission identity in memory; no conversation history or persisted request ledger.
- Show result only for mySessionId while this visitor owns the session. Clear locally cached identity/result on release, ownership change, and new submission. Do not show another visitor's clarify question in the active controller.
- Handle event ordering: WebSocket result can arrive before HTTP response. Retain currentState, then reconcile it after response rather than waiting for another frame; delayed HTTP responses must not replace a newer submission identity. A small monotonically increasing local submission generation is enough; no request map required.
- On reload/reconnect, recover the current matching-session result from snapshot when no conflicting newer local submission exists. Do not clear a valid result merely on socket reconnect.
- Handle non-OK command responses (including503), offline/send failure and disconnect with an honest submission error. Do not keep “ส่งแล้ว” on failed publication or reinterpret HTTP200 as robot acceptance. Preserve microphone/STT/session controls.
- A pending local submission may suppress stale previous intent until its response identifies the new request; newer received results must remain recoverable from currentState.
- Acceptance: voice/text/chip use the same correlation rule; result-before-response, rapid two requests with delayed first response, stale snapshot, session switch/reclaim and reconnect work without cross-request attribution. No changes to chip request body or destination behavior.
- Commit: fix(frontend): correlate command feedback with request results

## Task 3 — Show direct Action outcomes on the staff page

Files: static/staff.html and static/styles.css if needed.
- Add a compact Action result section using existing /api/v1/state polling. Keep raw JSON diagnostics available.
- Read latest_action: show source, destination, status and error_msg. Render error_code==0 correctly (do not hide it through truthiness); nullable fields get neutral treatment.
- Labels: sending “กำลังส่งคำสั่ง”; accepted “Robot รับงานแล้ว”; unavailable “ไม่พบ Action server”; rejected “Robot ปฏิเสธงาน”; succeeded “Action เสร็จสำเร็จ”; aborted “Action ถูกยุติ”; canceled “Action ถูกยกเลิก”; failed “Action ไม่สำเร็จ”; transport_error “ส่งหรือรับผล Action ไม่สำเร็จ”. Use neutral fallback for unknown future values.
- This panel describes backend staff/auto-return commands. Never imply it tracks intent_node Action goals or use it to set physical robot arrival.
- Fix staffApi to treat all non-OK HTTP responses as failures, preserving existing401 handling. Change return-to-start acknowledgement to “ส่งคำขอกลับจุดเริ่มต้นแล้ว” and direct user to outcome panel; do not report robot accepted based on POST response. Polling must show eventual reject/error even if POST acknowledged dispatch.
- Null clears stale content to neutral “ยังไม่มีผล Action”; use textContent. Do not add buttons, retries or additional controls.
- Acceptance: all outcomes/null/unknown, source/destination, raw error fields, HTTP500/503 and successful POST followed by rejected Action render honestly. Existing staff controls/polling still work.
- Commit: feat(frontend): display backend action outcomes for staff

## Task 4 — Verify the actual pages and finish local handoff

Build verification as part of the above tasks. Do not add a large test framework for this change. Use an available browser driver (inspect availability first); serve real static pages with controlled API/WebSocket fixtures if FastAPI remains unavailable. Fixtures may inject four IntentResult statuses and all direct Action outcomes without ROS/hardware. Test the real DOM/rendering functions, not a copied implementation.

Required cases: status mappings and exact messages; safe text rendering; null/missing/unknown fields; WebSocket-before-HTTP race; rapid submissions; wrong session; reconnect; HTTP error; subtitle clearing; narrow/mobile layout; no browser console errors. Check staff polling and controls. Inspect any fixture code for accidental production inclusion.

Run JS syntax and git diff --check as appropriate. Record which browser scenarios actually ran and which checks are manual/pending; syntax alone is not proof the page displays results correctly. Do not claim mock UI proves real robot connectivity. If tools are unavailable, complete code and explicitly list pending browser checks rather than silently claiming validation.

At each finished feat/fix, review and commit that unit on feat/robot-integration. Do not create an extra empty “verification commit”; commit a test artifact only when it adds useful repeatable coverage and is intended for the repo. Final handoff: local commit hashes, screens/behaviors observed, limitations, git status. NO PUSH.

## Backlog remains

start/wait routing; VR output; conversational context; robot/intent readiness/return-home policies; recovery/retries. Clarify is displayed only—no automatic context assembly or conversational loop.
