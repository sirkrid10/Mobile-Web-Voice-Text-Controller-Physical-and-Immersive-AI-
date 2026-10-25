# Backend integration — Luna handoff

Status: planned; no implementation authorized in this handoff.
Repository: /home/lilieay/ros2_ws/Mobile-Web-Voice-Text-Controller-Physical-and-Immersive-AI-
Branch: feat/robot-integration (created from local main at e1fa65b).

## Scope agreed with user

Implement backend integration only when the user starts implementation. Preserve quick-chip start/wait -> UserRequest -> intent routing; changing it is backlog. No frontend or VR edits, no conversation memory, no robot/intent policy changes, no new retry/recovery logic. Existing subtitle and llm_reason behavior remains.

Git: local commits are authorized; PUSH IS NOT AUTHORIZED. No remote branch, PR, merge, or deployment. Do not commit generated files, .env, credentials, or unrelated work. Additional planning documents stay local unless requested. No repository-specific Git guide was found in README/repo/parent instructions during planning; if an actual guide becomes available, read it before implementation and reconcile it with these explicit user constraints.

## Grounding and chosen shape

main.py validates the session and sends UserRequest through ros2_bridge.py. SessionManager owns state and StateBroadcast, broadcast through /ws/status and returned by /api/v1/state. Real bridge receives ROS callbacks on an executor thread and schedules owner updates on the asyncio loop. Subtitle owns llm_reason; NavigationState supplies physical robot state. Action callbacks currently only log outcomes.

Use the existing SessionManager with two additive optional nested fields: latest_intent and latest_action, default null. Keep existing WebSocket frames and fields; do not introduce mixed event envelopes, a new endpoint, another state service, or result history. NAVIGATE means interpretation only, never goal acceptance or arrival. IntentResult reception must never send a duplicate Action.

Authoritative schemas are in ../turtlebot-llm/src/ai_interfaces:
- UserRequest: request_id, session_id, text. Do NOT add valid_until here.
- IntentResult: stamp, request_id, session_id, uint8 status (NAVIGATE=1, CLARIFY=2, UNSUPPORTED=3, FAILED=4), destination_id, message, error_code (string).
- GuideToDestination.Goal: request_id, destination_id, valid_until. Result: error_code (uint16), error_msg. Feedback unchanged.

### Caller examples and proposed signatures

```python
identity = session_manager.begin_user_request(session_id=session_id)
bridge.publish_user_transcript(request_id=identity.request_id,
    session_id=identity.session_id, input_mode=input_mode, text=text)
# Both text and voice responses retain existing fields and add request_id/session_id.

# ROS callback converts primitives before crossing threads:
loop.call_soon_threadsafe(session_manager.record_intent_result, outcome)
# Existing staff/auto-return entry points still use one direct Action send path.
```

```python
class RequestIdentity(BaseModel):
    request_id: str
    session_id: str

class IntentOutcome(BaseModel):
    request_id: str
    session_id: str
    stamp: RosStamp  # sec, nanosec, preserving source precision
    status: Literal['NAVIGATE', 'CLARIFY', 'UNSUPPORTED', 'FAILED']
    destination_id: str
    message: str
    error_code: str

class DirectActionOutcome(BaseModel):
    request_id: str
    source: str  # existing staff/auto-return source, captured at send
    destination_id: str
    outcome: Literal['sending', 'accepted', 'unavailable', 'rejected',
                     'succeeded', 'aborted', 'canceled', 'failed', 'transport_error']
    ros_status: int | None = None
    error_code: int | None = None
    error_msg: str = ''

# StateBroadcast adds latest_intent: IntentOutcome | None and
# latest_action: DirectActionOutcome | None; existing fields stay as-is.
# SessionManager: begin_user_request(*, session_id) -> RequestIdentity;
# record_intent_result(result: IntentOutcome) -> None;
# record_action_outcome(result: DirectActionOutcome) -> None.
# Base/Real/Mock bridge publish_user_transcript signatures must agree.
```

This is a plan, not executable scaffolding. Keep helpers small and private where possible; do not introduce a generic event framework or rewrite the public direct-action API just for tidiness.

## Tasks (execute in order)

### 1. Correlate user requests and add result fields

Files: app/models.py, app/session_manager.py, app/main.py, app/ros2_bridge.py and focused tests.
- Allocate one request_id before publication; register latest identity before sending to avoid immediate-result races. Use it in ROS message and text/voice CommandResponse; preserve existing response fields/status.
- latest_intent accepts only the current request_id AND session_id. A new request clears the previous intent result; release/ownership change clears pending identity. No request history/map of conversations.
- Handle async voice STT carefully: recheck session ownership after transcription before registration/publication; do not let a late transcription publish under a released/replaced owner.
- If publication fails, do not claim successful sent; avoid changing session/inactivity policy.
- Acceptance: request and response IDs match for text/voice/chip; wrong session, old request, duplicate result, and release/reclaim are handled without misattribution. Existing endpoints/session tests still pass. Start/wait chips still publish their original text to intent.

### 2. Subscribe to IntentResult and expose it in the existing snapshot

Files: app/ros2_bridge.py, app/session_manager.py, tests.
- Subscribe /guide/intent_result using generated IntentResult and RELIABLE/VOLATILE/KEEP_LAST depth10.
- Map generated constants at the ROS boundary; unknown values log and discard. Preserve stamp, destination_id, message and error_code including empty strings.
- Convert on ROS thread; update owner/broadcast on asyncio loop. No direct ROS-thread state mutation.
- Base/Real/Mock agree. Mock uses the same result update path for statuses it simulates; do not build another LLM/parser or expand mock behavior. Other statuses can be injected by test fixtures.
- Acceptance: all four statuses reach /api/v1/state and /ws/status accurately; matching IDs required. Clarify text survives subtitle clear/TTL. Subtitle behavior remains intact and IntentResult does not send Action or modify current_goal/robot_state/timers.

### 3. Restore valid_until for backend-owned direct Action goals

Files: app/config.py, app/ros2_bridge.py, .env.example, tests.
- Add DIRECT_ACTION_VALIDITY_SEC default30.0, strictly positive and finite; reject zero/negative/NaN/infinity.
- Compute deadline from node ROS clock + configured duration immediately before send_goal_async after server availability. Use normalized builtin Time (e.g. rclpy Duration.to_msg via Time addition).
- Shared direct send path covers staff Return to Start and automatic return. Preserve existing destination/request ID and eligibility logic. Do not add expiry to UserRequest, and do not reinterpret deadline as navigation execution timeout.
- Acceptance: controlled ROS clock verifies exact deadline even when different from wall clock; received serialized staff/auto-return goals contain expiry; invalid settings reject startup; existing Action result/feedback schema unchanged.

### 4. Report backend-owned Action outcomes

Files: app/ros2_bridge.py, app/session_manager.py, tests.
- Record sending/accepted/unavailable/rejected and terminal success/abort/cancel/error in latest_action, with captured request_id, destination and source. Keep raw ROS status/error_code/error_msg where available.
- Capture context per future/goal. Older callbacks cannot overwrite the newest action or clear a newer active_goal_handle; terminal result cannot regress to accepted. Cancel acknowledgement is not a terminal canceled result.
- Success requires ROS SUCCEEDED and error_code==0. Future exceptions become transport_error with a useful message rather than log-only failures.
- Keep HTTP sent/returning as dispatch acknowledgements; actual asynchronous outcome is in latest_action. Do not claim HTTP proves robot acceptance.
- Acceptance: unavailable/rejected/succeeded/nonzero error/aborted/canceled/future exception are distinguishable; outcome broadcasts occur; late callback race covered. Outcomes do not manufacture ARRIVED/REACHED, change navigation timers, or introduce retries.
- Scope limit: latest_action covers goals sent by BACKEND, not goals sent by intent_node; physical state remains sourced from /robot/navigation_state.

### 5. Align backend launcher with local and robot environments

Files: booth_web_controller/run_booth.sh, .env.example, focused shell checks; concise operational docs only if needed.
- Existing launcher hardcodes domain83/LOCALHOST and ~/turtlebot_ws/install; replace with explicit local/robot profile defaults and configurable workspace setup path. Default interface setup on this machine is ../turtlebot-llm/install-colcon/setup.bash (resolve against script/repo location, not caller cwd).
- Load configuration before choosing network defaults; define/document precedence for explicit environment versus .env/profile. Preserve normal local development.
- Robot defaults must match the supplied Robot guide: domain30, rmw_fastrtps_cpp, SUBNET, Discovery Server192.168.1.17:11811 and actual supplied SUPER_CLIENT XML. Check readable XML and SUPER_CLIENT; expose server/XML overrides. Set both FASTRTPS_DEFAULT_PROFILES_FILE and FASTDDS_DEFAULT_PROFILES_FILE consistently. Do not invent XML or switch to generic peers instead of the agreed Discovery Server.
- Local defaults domain83/LOCALHOST, and clear robot-only discovery/XML settings when switching back; do not leak stale network config between profiles. Follow established setup_demo.sh behavior but do not source it wholesale because it activates the intent venv.
- Source ROS Jazzy and selected generated interface workspace, then use backend's own venv/interpreter. Preflight real mode imports rclpy, IntentResult, and Goal.valid_until; fail clearly on stale/missing interfaces. Never silently fall back to mock; explicit mock mode remains usable without ROS.
- Acceptance: bash -n; local/robot/override/missing XML/stale interface shell probes; launcher does not overwrite robot profile with83/LOCALHOST and selected backend Python has required imports. Missing peer XML is a pending live test, not permission to create a guessed production file.

### 6. Verification and local Git handoff

- Run existing tests/test_verification_protocol.py plus focused owner/model/bridge tests. Run tests/test_real_ros2_contract.py in properly sourced ROS environment with latest interfaces; use isolated domain/fixtures, bounded polling and cleanup rather than arbitrary new sleeps.
- Real in-process smoke: publish UserRequest, inject IntentResult -> WebSocket snapshot, subtitle unchanged, mock Action server captures valid_until and returns rejection/success/error. Add tests incrementally with each task rather than postponing all verification.
- Reuse an available backend environment; inspect prerequisites before installing anything. If socket restrictions prevent ROS integration tests, record the limitation separately; do not call unit tests proof of cross-machine connectivity.
- Before each coherent local commit: git status, verify branch feat/robot-integration, inspect diff, run relevant checks and git diff --check, stage explicit files, inspect staged diff. Example commit groups: feat(backend): expose correlated intent results; fix(ros2): set goal expiry and report action outcomes; fix(runtime): support robot discovery profile.
- Do not include this plan or other additional docs unless user requests it; stage deliberately. No git push, PR, merge, deployment, or remote updates. End with commit hashes, tests actually run and pending manual checks.

## Backlog — explicitly excluded

- Route start/wait quick chips differently or make them perform new actions. Keep their current input flow.
- Frontend display/layout and VR changes; conversation context/history.
- Robot readiness/return-home policy, intent dispatch policy, retry/recovery logic.

## Manual checks on integration day

Actual supplied SUPER_CLIENT XML; bidirectional WSL/robot reachability (Discovery Server discovery does not relay topic payloads); clocks aligned; robot navigation_state heartbeat/ready; one real goal round-trip. Local tests do not certify these. Consecutive-booth/return-home restrictions stay as previously agreed.

## pstack synthesis and reconciliation

Phases: Ground complete; Sketch complete (two model candidates); Agree: user requested plan-only handoff; Implement/Scrap deferred until implementation is requested.
Arena rubric: respect scope, backward-compatible WS, minimal ownership/correlation, correct ROS guide/expiry, independently verifiable tasks with local-only Git.
Candidate A uses existing SessionManager and nested snapshots; candidate B uses distinct typed event frames. Choose A: preserves the existing consumer frame shape and reconnect snapshots with fewer moving parts. Reject B's mixed-frame protocol because current frontend is unchanged and cannot be assumed to ignore unknown frames. Graft B's explicit warning about preserving backend venv and preflighting generated imports. Correct A's candidate default expiry10 to30 and generic discovery suggestion to the actual Robot guide.
Implementation reconciliation: no code changed. Record material accepted deviations here and update signatures/acceptance before passing the next unit to another worker. Do not broaden scope to repair excluded chip behavior.
Independent cross-judge agreed on A and the compatibility reason. One judge suggestion is rejected: 192.168.1.17:11811 belongs in ROS_DISCOVERY_SERVER, NOT ROS_STATIC_PEERS (static peers are not a Discovery Server address/port setting). Use the agreed Fast DDS SUPER_CLIENT setup. Scope and default30 corrections incorporated; verification/commit steps above are future Luna implementation tasks, not work performed during planning.
