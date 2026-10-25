"""Automated Test Suite for Verification Protocol.
Uses FastAPI TestClient to test:
1. Session Lock Exclusivity Test (dev-A vs dev-B 409 Conflict)
2. ROS 2 Bridge Publication & Text/Chip Commands (/guide/user_request)
3. Smart Navigation Timer Pause Test (paused during NAVIGATING/REPLANNING)
4. Auto-Return to Start Booth on Disconnect Test (target: start)
5. Staff PIN Authentication & Emergency Stop
6. Voice Audio Command Processing (with fallback)
"""

import io
import time
import asyncio
import pytest
from unittest.mock import Mock
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.session_manager import session_manager
from app.stt_service import STTService, STTUnavailableError


@pytest.fixture(autouse=True)
def reset_session_state():
    settings.USE_MOCK_ROS2 = True
    session_manager.set_broadcast_callback(None)
    """Reset session manager state before each test."""
    asyncio.run(session_manager.release_session(reason="test_reset"))
    session_manager.robot_state = "IDLE"
    session_manager.current_goal = settings.START_BOOTH_ID
    session_manager.heard_text = ""
    session_manager.llm_explanation = "พร้อมรับคำสั่งจากผู้เข้าชมบูธ"
    session_manager.obstacle_detected = False
    session_manager.latest_request_identity = None
    session_manager.latest_intent = None
    session_manager.latest_action = None
    session_manager.auto_return_enabled = True
    session_manager.auto_return_delay_sec = 1  # 1s for fast testing
    session_manager.inactivity_timeout_sec = 60
    if session_manager.auto_return_task and not session_manager.auto_return_task.done():
        session_manager.auto_return_task.cancel()
    # The TestClient lifespan runs on a different event loop than asyncio.run above.
    session_manager._lock = asyncio.Lock()
    yield
    session_manager.set_broadcast_callback(None)


def test_session_lock_exclusivity():
    """Protocol 1: dev-A claims session (200 OK), dev-B claims (409 Conflict)."""
    with TestClient(app) as client:
        # 1. dev-A claims session
        res_a = client.post("/api/v1/session/claim", json={"session_id": "dev-A"})
        assert res_a.status_code == 200
        data_a = res_a.json()
        assert data_a["status"] == "claimed"
        assert data_a["session_id"] == "dev-A"
        token_a = data_a["session_token"]
        assert len(token_a) > 0

        # 2. dev-B attempts to claim while dev-A is active
        res_b = client.post("/api/v1/session/claim", json={"session_id": "dev-B"})
        assert res_b.status_code == 409
        assert "Session locked" in res_b.json()["detail"]

        # 3. dev-A claims again (refresh/reconnect) -> should succeed with same token
        res_a_repeat = client.post("/api/v1/session/claim", json={"session_id": "dev-A"})
        assert res_a_repeat.status_code == 200
        assert res_a_repeat.json()["session_token"] == token_a


def test_text_command_and_auto_claim():
    """Protocol 2: Text/Chip commands and auto-claim if vacant (routes to A)."""
    with TestClient(app) as client:
        # First command from visitor auto-claims session
        res = client.post(
            "/api/v1/command/text",
            headers={"X-Session-Id": "dev-visitor-1"},
            json={"text": "ไปจุด A", "input_mode": "text"}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "sent"
        assert data["transcript"] == "ไปจุด A"
        assert data["session_id"] == "dev-visitor-1"
        assert data["request_id"].startswith("req-")

        # Verify active session belongs to dev-visitor-1 and destination is A
        state = session_manager.get_state_broadcast()
        assert state.active_session_id == "dev-visitor-1"
        assert state.current_goal == "A"
        assert state.latest_intent.status == "NAVIGATE"
        assert state.latest_intent.request_id == data["request_id"]
        assert state.latest_intent.session_id == data["session_id"]


def test_intent_result_requires_current_request_and_session():
    from app.models import IntentOutcome, RosStamp

    asyncio.run(session_manager.claim("intent-owner"))
    request_id, session_id = asyncio.run(session_manager.begin_user_request(
        "intent-owner", session_manager.active_session_token
    ))
    result = IntentOutcome(
        request_id=request_id,
        session_id=session_id,
        stamp=RosStamp(sec=1, nanosec=2),
        status="CLARIFY",
        message="Which booth?",
    )

    assert not session_manager.record_intent_result(result.model_copy(update={"request_id": "old"}))
    assert not session_manager.record_intent_result(result.model_copy(update={"session_id": "other"}))
    assert session_manager.record_intent_result(result)
    assert not session_manager.record_intent_result(result)

    state = session_manager.get_state_broadcast()
    assert state.latest_intent.message == "Which booth?"
    session_manager.latest_request_identity = ("new-request", session_id)
    assert not session_manager.record_intent_result(result)


def test_action_snapshot_keeps_newest_goal_and_terminal_state():
    from app.models import DirectActionOutcome

    first = DirectActionOutcome(
        request_id="action-1", source="staff_override", destination_id="start", outcome="sending"
    )
    second = DirectActionOutcome(
        request_id="action-2", source="auto_return", destination_id="start", outcome="sending"
    )
    assert session_manager.record_action_outcome(first)
    assert session_manager.record_action_outcome(first.model_copy(update={"outcome": "accepted"}))
    assert session_manager.record_action_outcome(second)
    assert not session_manager.record_action_outcome(first.model_copy(update={"outcome": "succeeded"}))
    assert session_manager.record_action_outcome(second.model_copy(update={"outcome": "succeeded"}))
    assert not session_manager.record_action_outcome(second.model_copy(update={"outcome": "accepted"}))
    assert session_manager.latest_action.request_id == "action-2"
    assert session_manager.latest_action.outcome == "succeeded"


def test_quick_chip_command_keeps_original_flow_and_correlates_result():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/command/text",
            headers={"X-Session-Id": "chip-visitor"},
            json={"text": "หยุดรอตรงนี้ก่อน", "input_mode": "chip"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["transcript"] == "หยุดรอตรงนี้ก่อน"
    assert payload["session_id"] == "chip-visitor"
    state = session_manager.get_state_broadcast()
    assert state.heard_text == "หยุดรอตรงนี้ก่อน"
    assert session_manager.latest_request_identity == (payload["request_id"], "chip-visitor")


def test_locations_use_visitor_a_b_c_and_start_chip_remains_a_request():
    assert [(item["id"], item["prompt"]) for item in settings.LOCATIONS[:3]] == [
        ("A", "ไปจุด A"), ("B", "ไปจุด B"), ("C", "ไปจุด C")
    ]
    start = next(item for item in settings.LOCATIONS if item["id"] == "start")
    assert start["prompt"] == "กลับจุดเริ่มต้น"
    assert "จุด A" in start["label"]


@pytest.mark.parametrize(("text", "destination"), [
    ("ไปจุด A", "A"), ("พาไปจุด บี", "B"), ("ไปจุด C", "C"), ("กลับ start", "A")
])
def test_mock_visitor_requests_map_to_a_b_c_and_start_alias(text, destination):
    from app.ros2_bridge import MockROS2Bridge
    target, status, _ = MockROS2Bridge._mock_intent(text)
    assert status == "NAVIGATE"
    assert target == destination


@pytest.mark.parametrize(("text", "status"), [
    ("ไปที่บูธ", "CLARIFY"), ("ไปจุด A แล้วจุด B", "CLARIFY"), ("ส่งคำขอรอ", "UNSUPPORTED")
])
def test_mock_does_not_invent_destination_for_ambiguous_or_unsupported_text(text, status):
    from app.ros2_bridge import MockROS2Bridge
    _, actual_status, _ = MockROS2Bridge._mock_intent(text)
    assert actual_status == status


def test_mock_busy_result_preserves_simulation_and_emits_subtitle(monkeypatch):
    from app.ros2_bridge import MockROS2Bridge

    loop = asyncio.new_event_loop()
    bridge = MockROS2Bridge(session_manager, loop)
    task = Mock()
    task.done.return_value = False
    bridge._sim_task = task
    result = Mock()
    subtitle = Mock()
    monkeypatch.setattr(session_manager, "record_intent_result", result)
    monkeypatch.setattr(bridge, "handle_mock_subtitle", subtitle)

    bridge.publish_user_transcript("req-next", "visitor", "text", "ไปจุด B")

    recorded = result.call_args.args[0]
    assert recorded.request_id == "req-next"
    assert recorded.session_id == "visitor"
    assert recorded.status == "FAILED"
    assert recorded.error_code == "robot_busy"
    subtitle.assert_called_once()
    assert bridge._sim_task is task
    loop.close()


def test_mock_subtitle_uses_remaining_source_ttl_and_discards_owner_loop_expiry():
    from app.ros2_bridge import MockROS2Bridge

    class SubtitleState:
        heard_text = ""
        llm_explanation = ""

        def update_from_llm_mind(self, heard_text, explanation, target=None):
            self.heard_text = heard_text
            self.llm_explanation = explanation

        def _trigger_broadcast(self):
            pass

    async def run():
        now = [102.5]
        state = SubtitleState()
        bridge = MockROS2Bridge(state, asyncio.get_running_loop(), clock=lambda: now[0])
        bridge.handle_mock_subtitle("เหลือครึ่งวินาที", ttl_sec=3, stamp_sec=100)
        await asyncio.sleep(0)
        assert state.llm_explanation == "เหลือครึ่งวินาที"
        now[0] = 103
        await asyncio.sleep(0.6)
        assert state.llm_explanation == ""

        now[0] = 202.5
        bridge.handle_mock_subtitle("หมดอายุระหว่างรอ loop", ttl_sec=0.5, stamp_sec=202)
        now[0] = 203
        await asyncio.sleep(0)
        assert state.llm_explanation == ""
        bridge.shutdown()

    asyncio.run(run())


def test_mock_subtitle_clear_stale_messages_and_old_timers_cannot_clear_new_text():
    from app.ros2_bridge import MockROS2Bridge

    class SubtitleState:
        heard_text = ""
        llm_explanation = "initial"

        def update_from_llm_mind(self, heard_text, explanation, target=None):
            self.llm_explanation = explanation

        def _trigger_broadcast(self):
            pass

    async def run():
        now = [100.0]
        state = SubtitleState()
        bridge = MockROS2Bridge(state, asyncio.get_running_loop(), clock=lambda: now[0])
        bridge.handle_mock_subtitle("ข้อความเก่า", ttl_sec=0.1, stamp_sec=100)
        await asyncio.sleep(0)
        bridge.handle_mock_subtitle("ข้อความใหม่", ttl_sec=5, stamp_sec=100)
        await asyncio.sleep(0)
        bridge.handle_mock_subtitle("ย้อนเวลา", ttl_sec=5, stamp_sec=99)
        await asyncio.sleep(0.15)
        assert state.llm_explanation == "ข้อความใหม่"

        now[0] = 101
        bridge.handle_mock_subtitle("", ttl_sec=0, stamp_sec=101)
        await asyncio.sleep(0)
        assert state.llm_explanation == ""
        bridge.handle_mock_subtitle("อนาคต", ttl_sec=3, stamp_sec=102)
        await asyncio.sleep(0)
        assert state.llm_explanation == ""
        bridge.shutdown()

    asyncio.run(run())


@pytest.mark.parametrize(("phase", "ready", "error", "expected"), [
    ("NAVIGATING", False, 0, "NAVIGATING"),
    ("RETURNING_HOME", False, 0, "NAVIGATING"),
    ("ARRIVED", False, 0, "REACHED"),
    ("READY", True, 0, "IDLE"),
    ("HOME", True, 0, "IDLE"),
    ("READY", False, 0, "NOT_READY"),
    ("HOME", False, 0, "NOT_READY"),
    ("NOT_READY", True, 0, "NOT_READY"),
    ("CANCELED", False, 0, "STOPPED"),
    ("FAILED", True, 0, "FAILED"),
    ("NAVIGATING", True, 7, "FAILED"),
    ("new_phase", False, 0, "UNKNOWN"),
])
def test_navigation_phase_maps_only_to_confirmed_web_state(phase, ready, error, expected):
    from app.ros2_bridge import map_navigation_state
    assert map_navigation_state(phase, ready, error) == expected


def test_web_state_schema_accepts_unknown_and_not_ready():
    for state in ("UNKNOWN", "NOT_READY"):
        session_manager.robot_state = state
        assert session_manager.get_state_broadcast().robot_state == state


def test_voice_request_rechecks_session_ownership_after_transcription(monkeypatch):
    async def transcribe_and_change_owner(_audio):
        await session_manager.release_session(reason="staff_force_release")
        await session_manager.claim("replacement-owner")
        return "ไปจุด A"

    monkeypatch.setattr("app.main.stt_service.transcribe_audio", transcribe_and_change_owner)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/command/voice",
            headers={"X-Session-Id": "voice-owner"},
            files={"audio": ("sample.wav", io.BytesIO(b"audio"), "audio/wav")},
        )

    assert response.status_code == 403
    assert session_manager.active_session_id == "replacement-owner"
    assert session_manager.latest_request_identity is None


@pytest.mark.parametrize("provider", ["groq", "openai", "faster_whisper"])
@pytest.mark.parametrize("transcript", ["ไปจุด B", "", "   "])
def test_stt_providers_return_successful_and_empty_transcripts_without_fallback(monkeypatch, provider, transcript):
    service = STTService()
    service.provider = provider

    async def fake_provider(_path):
        return transcript

    method = {
        "groq": "_transcribe_groq",
        "openai": "_transcribe_openai",
        "faster_whisper": "_transcribe_faster_whisper",
    }[provider]
    monkeypatch.setattr(service, method, fake_provider)

    class FakeUpload:
        content_type = "audio/wav"
        filename = "sample.wav"

        async def read(self):
            return b"audio"

    async def run():
        return await service.transcribe_audio(FakeUpload())

    assert asyncio.run(run()) == transcript


@pytest.mark.parametrize("provider", ["groq", "openai", "faster_whisper", "invalid"])
def test_stt_provider_failures_raise_controlled_error(monkeypatch, provider):
    service = STTService()
    service.provider = provider

    async def fail_provider(_path):
        raise RuntimeError("provider secret detail")

    for method in ("_transcribe_groq", "_transcribe_openai", "_transcribe_faster_whisper"):
        monkeypatch.setattr(service, method, fail_provider)

    class FakeUpload:
        content_type = "audio/wav"
        filename = "sample.wav"

        async def read(self):
            return b"audio"

    async def run():
        return await service.transcribe_audio(FakeUpload())

    with pytest.raises(STTUnavailableError):
        asyncio.run(run())


@pytest.mark.parametrize(("transcript", "status"), [("", 422), ("  \n", 422), (None, 503)])
def test_voice_failures_do_not_register_or_publish_requests(monkeypatch, transcript, status):
    from unittest.mock import Mock
    import app.main as main_module

    async def transcribe(_audio):
        if transcript is None:
            raise STTUnavailableError("private provider detail")
        return transcript

    bridge = Mock()
    monkeypatch.setattr(main_module, "create_ros2_bridge", lambda *_args: bridge)
    monkeypatch.setattr(main_module.stt_service, "transcribe_audio", transcribe)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/command/voice",
            headers={"X-Session-Id": "empty-audio-user"},
            files={"audio": ("sample.wav", io.BytesIO(b"audio"), "audio/wav")},
        )

    assert response.status_code == status
    assert "private provider detail" not in response.text
    assert session_manager.latest_request_identity is None
    bridge.publish_user_transcript.assert_not_called()


def test_smart_navigation_timer_pause():
    """Protocol 3: Watchdog pauses countdown during NAVIGATING/REPLANNING."""
    asyncio.run(session_manager.claim("dev-timer-test"))
    session_manager.robot_state = "IDLE"

    # Tick 1: IDLE countdown
    session_manager.last_activity_ts = time.time() - 10
    state_idle = asyncio.run(session_manager.watchdog_tick())
    assert state_idle.timer_paused_for_navigation is False
    assert state_idle.inactivity_remaining_sec == 50

    # Set state to NAVIGATING -> timer should pause and remain at 60s
    session_manager.robot_state = "NAVIGATING"
    state_nav = asyncio.run(session_manager.watchdog_tick())
    assert state_nav.timer_paused_for_navigation is True
    assert state_nav.inactivity_remaining_sec == 60

    # Set state to REPLANNING -> still paused
    session_manager.robot_state = "REPLANNING"
    state_replan = asyncio.run(session_manager.watchdog_tick())
    assert state_replan.timer_paused_for_navigation is True
    assert state_replan.inactivity_remaining_sec == 60

    # Reached destination -> countdown resumes
    session_manager.robot_state = "REACHED"
    session_manager.last_activity_ts = time.time() - 5
    state_reached = asyncio.run(session_manager.watchdog_tick())
    assert state_reached.timer_paused_for_navigation is False
    assert state_reached.inactivity_remaining_sec == 55


def test_auto_return_on_disconnect():
    """Protocol 4: Disconnect triggers delayed auto-return to start booth."""
    with TestClient(app) as client:
        # Claim session and set destination to A
        claim_res = client.post("/api/v1/session/claim", json={"session_id": "dev-return-user"})
        token = claim_res.json()["session_token"]

        # Navigate away from start
        session_manager.current_goal = "A"
        session_manager.robot_state = "REACHED"
        session_manager.auto_return_delay_sec = 1  # 1s for testing

        # Disconnect
        disc_res = client.post(
            "/api/v1/session/disconnect",
            headers={"X-Session-Token": token}
        )
        assert disc_res.status_code == 200
        assert disc_res.json()["auto_return_scheduled"] is True
        assert session_manager.active_session_id is None

        # Wait for delayed auto-return task to trigger
        time.sleep(1.3)
        assert session_manager.current_goal == settings.START_BOOTH_ID  # "start"


def test_staff_pin_security_and_emergency_stop():
    """Protocol 5: Staff PIN authentication & Emergency Stop behavior."""
    with TestClient(app) as client:
        # Attempt E-Stop without PIN -> 401
        res_unauth = client.post("/api/v1/staff/emergency-stop")
        assert res_unauth.status_code == 401

        # Attempt E-Stop with invalid PIN -> 401
        res_bad_pin = client.post(
            "/api/v1/staff/emergency-stop",
            headers={"X-Staff-Pin": "9999"}
        )
        assert res_bad_pin.status_code == 401

        # E-Stop with valid PIN -> 200
        res_ok = client.post(
            "/api/v1/staff/emergency-stop",
            headers={"X-Staff-Pin": settings.STAFF_PIN}
        )
        assert res_ok.status_code == 200
        assert res_ok.json()["status"] == "stopped"
        assert session_manager.robot_state == "STOPPED"


def test_voice_upload_endpoint(monkeypatch):
    """Voice upload publishes an explicitly injected transcript."""
    async def transcribe(_audio):
        return "ไปจุด C"

    monkeypatch.setattr("app.main.stt_service.transcribe_audio", transcribe)
    with TestClient(app) as client:
        dummy_audio = io.BytesIO(b"RIFF....WAVEfmt ....data....")
        res = client.post(
            "/api/v1/command/voice",
            headers={"X-Session-Id": "dev-audio-user"},
            files={"audio": ("sample.wav", dummy_audio, "audio/wav")}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "sent"
        assert data["transcript"] == "ไปจุด C"


def test_html_pages_served():
    """Verify static/index.html and static/staff.html are served."""
    with TestClient(app) as client:
        res_index = client.get("/")
        assert res_index.status_code == 200
        assert "TurtleBot3 Controller" in res_index.text
        assert "หุ่นยนต์ว่าง พร้อมรับคำสั่ง!" in res_index.text

        res_staff = client.get("/staff")
        assert res_staff.status_code == 200
        assert "Staff Override Panel" in res_staff.text
        assert "กรุณาระบุรหัส PIN ของเจ้าหน้าที่" in res_staff.text
