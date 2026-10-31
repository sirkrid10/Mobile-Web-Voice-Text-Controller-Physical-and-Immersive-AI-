"""Automated Test Suite for Verification Protocol.
Uses FastAPI TestClient to test:
1. Session Lock Exclusivity Test (dev-A vs dev-B 409 Conflict)
2. ROS 2 Bridge Publication & Text/Chip Commands (/guide/user_request)
3. Smart Navigation Timer Pause Test (paused during NAVIGATING/REPLANNING)
4. Auto-Return to Start Booth on Disconnect Test (target: A)
5. Staff PIN Authentication & Emergency Stop
6. Voice Audio Command Processing (with fallback)
"""
from app.session_state import RobotDisplay, SessionError
from app import runtime
from app.routes import commands, sessions
from fastapi import HTTPException

import io
import time
import asyncio
import re
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
    session_manager.display.robot_state = "IDLE"
    session_manager.display.current_goal = settings.START_BOOTH_ID
    session_manager.display.heard_text = ""
    session_manager.display.llm_explanation = "พร้อมรับคำสั่งจากผู้เข้าชมบูธ"
    session_manager.display.obstacle_detected = False
    session_manager.requests.latest_request_identity = None
    session_manager.requests.latest_intent = None
    session_manager.requests.latest_action = None
    session_manager.auto_return_enabled = True
    session_manager.auto_return_delay_sec = 1  # 1s for fast testing
    session_manager.inactivity_timeout_sec = 60
    if session_manager.auto_return.task and not session_manager.auto_return.task.done():
        session_manager.auto_return.task.cancel()
    # The TestClient lifespan runs on a different event loop than asyncio.run above.
    session_manager._lock = asyncio.Lock()
    yield
    session_manager.set_broadcast_callback(None)


@pytest.mark.parametrize("target", ["A", "B", "C", "D", "start"])
def test_robot_return_config_accepts_only_abcd(target):
    from app.config import Settings
    from pydantic import ValidationError

    if target == "start":
        with pytest.raises(ValidationError, match="Robot A/B/C/D contract"):
            Settings(START_BOOTH_ID=target)
    else:
        assert Settings(START_BOOTH_ID=target).START_BOOTH_ID == target


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
        "intent-owner", session_manager.identity.active_session_token
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
    session_manager.requests.latest_request_identity = ("new-request", session_id)
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
    assert session_manager.requests.latest_action.request_id == "action-2"
    assert session_manager.requests.latest_action.outcome == "succeeded"


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
    assert session_manager.requests.latest_request_identity == (payload["request_id"], "chip-visitor")


def test_locations_use_named_abcd_and_start_chip_remains_a_request():
    assert [(item["id"], item["prompt"]) for item in settings.LOCATIONS[:4]] == [
        ("A", "ไปโซนกู้ภัย"), ("B", "ไปโซนการแพทย์"), ("C", "ไปโซนส่งเสบียง"), ("D", "ไปศูนย์บัญชาการ")
    ]
    start = next(item for item in settings.LOCATIONS if item["id"] == "start")
    assert start["prompt"] == "กลับจุดเริ่มต้น"
    assert "จุด D" in start["label"]


@pytest.mark.parametrize(("text", "destination"), [
    ("ไปจุด A", "A"), ("พาไปจุด บี", "B"), ("ไปจุด C", "C"), ("กลับ start", "D")
])
def test_mock_visitor_requests_map_to_a_b_c_and_start_alias(text, destination):
    from app.mock_ros2_bridge import MockROS2Bridge
    target, status, _ = MockROS2Bridge._mock_intent(text)
    assert status == "NAVIGATE"
    assert target == destination


@pytest.mark.parametrize(("text", "status"), [
    ("ไปที่บูธ", "CLARIFY"), ("ไปจุด A แล้วจุด B", "CLARIFY"), ("ส่งคำขอรอ", "UNSUPPORTED")
])
def test_mock_does_not_invent_destination_for_ambiguous_or_unsupported_text(text, status):
    from app.mock_ros2_bridge import MockROS2Bridge
    _, actual_status, _ = MockROS2Bridge._mock_intent(text)
    assert actual_status == status


@pytest.mark.parametrize("input_mode", ["voice", "text", "chip"])
def test_real_bridge_published_command_updates_heard_text_on_owner_loop(input_mode):
    from app.ros2_bridge import RealROS2Bridge

    class UserRequest:
        pass

    class Publisher:
        def __init__(self):
            self.messages = []

        def publish(self, message):
            self.messages.append(message)

    class State:
        def __init__(self, owner_loop):
            self.owner_loop = owner_loop
            self.heard_text = "ข้อความก่อนหน้า"
            self.current_goal = "B"
            self.llm_explanation = "คำอธิบายเดิม"
            self.latest_intent = object()
            self.latest_action = object()
            self.broadcasts = 0

        def update_from_llm_mind(self, heard_text, target=None, explanation=None):
            assert asyncio.get_running_loop() is self.owner_loop
            if heard_text:
                self.heard_text = heard_text
            if target:
                self.current_goal = target
            if explanation:
                self.llm_explanation = explanation
            self._trigger_broadcast()

        def _trigger_broadcast(self):
            self.broadcasts += 1

    loop = asyncio.new_event_loop()
    try:
        state = State(loop)
        publisher = Publisher()
        bridge = object.__new__(RealROS2Bridge)
        bridge.session_manager = state
        bridge.loop = loop
        bridge.UserRequest = UserRequest
        bridge.node = type("Node", (), {"pub_user_request": publisher})()
        intent_before = state.latest_intent
        action_before = state.latest_action

        async def publish():
            bridge.publish_user_transcript("req-1", "visitor-1", input_mode, "พาไปจุด A")

        loop.run_until_complete(publish())

        assert len(publisher.messages) == 1
        assert publisher.messages[0].text == "พาไปจุด A"
        assert state.heard_text == "พาไปจุด A"
        assert state.current_goal == "B"
        assert state.llm_explanation == "คำอธิบายเดิม"
        assert state.latest_intent is intent_before
        assert state.latest_action is action_before
        assert state.broadcasts == 1
    finally:
        loop.close()


def test_real_bridge_publish_failure_does_not_update_heard_text():
    from app.ros2_bridge import RealROS2Bridge

    class UserRequest:
        pass

    class Publisher:
        def publish(self, _message):
            raise RuntimeError("publisher failed")

    class State:
        heard_text = "ข้อความก่อนหน้า"
        current_goal = "B"
        llm_explanation = "คำอธิบายเดิม"
        latest_intent = object()
        latest_action = object()
        broadcasts = 0

        def update_from_llm_mind(self, **_kwargs):
            self.broadcasts += 1

    loop = asyncio.new_event_loop()
    try:
        state = State()
        bridge = object.__new__(RealROS2Bridge)
        bridge.session_manager = state
        bridge.loop = loop
        bridge.UserRequest = UserRequest
        bridge.node = type("Node", (), {"pub_user_request": Publisher()})()

        async def publish():
            bridge.publish_user_transcript("req-2", "visitor-1", "voice", "ข้อความใหม่")

        with pytest.raises(RuntimeError, match="publisher failed"):
            loop.run_until_complete(publish())

        assert state.heard_text == "ข้อความก่อนหน้า"
        assert state.broadcasts == 0
    finally:
        loop.close()


def test_mock_busy_result_preserves_simulation_and_emits_subtitle(monkeypatch):
    from app.mock_ros2_bridge import MockROS2Bridge

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
    from app.mock_ros2_bridge import MockROS2Bridge

    class SubtitleState:
        def __init__(self):
            self.display = RobotDisplay(llm_explanation="")

        def update_from_llm_mind(self, heard_text, explanation, target=None):
            self.display.heard_text = heard_text
            self.display.llm_explanation = explanation

        def _trigger_broadcast(self):
            pass

    async def run():
        now = [102.5]
        state = SubtitleState()
        bridge = MockROS2Bridge(state, asyncio.get_running_loop(), clock=lambda: now[0])
        bridge.handle_mock_subtitle("เหลือครึ่งวินาที", ttl_sec=3, stamp_sec=100)
        await asyncio.sleep(0)
        assert state.display.llm_explanation == "เหลือครึ่งวินาที"
        now[0] = 103
        await asyncio.sleep(0.6)
        assert state.display.llm_explanation == ""

        now[0] = 202.5
        bridge.handle_mock_subtitle("หมดอายุระหว่างรอ loop", ttl_sec=0.5, stamp_sec=202)
        now[0] = 203
        await asyncio.sleep(0)
        assert state.display.llm_explanation == ""
        bridge.shutdown()

    asyncio.run(run())


def test_mock_subtitle_clear_stale_messages_and_old_timers_cannot_clear_new_text():
    from app.mock_ros2_bridge import MockROS2Bridge

    class SubtitleState:
        def __init__(self):
            self.display = RobotDisplay(llm_explanation="initial")

        def update_from_llm_mind(self, heard_text, explanation, target=None):
            self.display.llm_explanation = explanation

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
        assert state.display.llm_explanation == "ข้อความใหม่"

        now[0] = 101
        bridge.handle_mock_subtitle("", ttl_sec=0, stamp_sec=101)
        await asyncio.sleep(0)
        assert state.display.llm_explanation == ""
        bridge.handle_mock_subtitle("อนาคต", ttl_sec=3, stamp_sec=102)
        await asyncio.sleep(0)
        assert state.display.llm_explanation == ""
        bridge.shutdown()

    asyncio.run(run())


def test_expired_subtitle_does_not_clear_fresh_subtitle_or_replace_its_timer():
    from app.mock_ros2_bridge import MockROS2Bridge

    class SubtitleState:
        def __init__(self):
            self.display = RobotDisplay(llm_explanation="")

        def update_from_llm_mind(self, heard_text, explanation, target=None):
            self.display.llm_explanation = explanation

        def _trigger_broadcast(self):
            pass

    async def run():
        now = [102.0]
        state = SubtitleState()
        bridge = MockROS2Bridge(state, asyncio.get_running_loop(), clock=lambda: now[0])
        bridge.handle_mock_subtitle("ยังสด", ttl_sec=3, stamp_sec=100)
        await asyncio.sleep(0)
        original_timer = bridge._subtitle_timer

        now[0] = 102.0
        bridge.handle_mock_subtitle("มาช้าและหมดอายุ", ttl_sec=0.5, stamp_sec=101)
        await asyncio.sleep(0)

        assert state.display.llm_explanation == "ยังสด"
        assert bridge._subtitle_timer is original_timer
        assert not original_timer.cancelled()
        bridge.shutdown()

    asyncio.run(run())


def test_staff_return_home_replaces_active_mock_visitor_navigation():
    from app.mock_ros2_bridge import MockROS2Bridge

    async def run():
        bridge = MockROS2Bridge(session_manager, asyncio.get_running_loop())
        session_manager.set_ros_bridge(bridge)
        session_manager.requests.latest_action = None
        session_manager.update_from_ros_state(state="IDLE", goal="A")
        bridge._start_navigation_simulation("B")
        visitor_task = bridge._sim_task
        await asyncio.sleep(0)

        await session_manager.return_to_start_now()
        staff_action_id = session_manager.requests.latest_action.request_id
        staff_task = bridge._sim_task

        assert staff_task is not visitor_task
        assert session_manager.display.current_goal == "D"
        assert session_manager.requests.latest_action.destination_id == "D"
        assert session_manager.requests.latest_action.source == "staff_override"
        assert session_manager.requests.latest_action.outcome == "accepted"

        await asyncio.wrap_future(staff_task)
        assert session_manager.display.current_goal == "D"
        assert session_manager.requests.latest_action.request_id == staff_action_id
        assert session_manager.requests.latest_action.outcome == "succeeded"
        assert session_manager.display.robot_state == "REACHED"
        bridge.shutdown()
        session_manager.set_ros_bridge(None)

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
    from app.ros_node import map_navigation_state
    assert map_navigation_state(phase, ready, error) == expected


def test_web_state_schema_accepts_unknown_and_not_ready():
    for state in ("UNKNOWN", "NOT_READY"):
        session_manager.display.robot_state = state
        assert session_manager.get_state_broadcast().robot_state == state


def test_voice_request_rechecks_session_ownership_after_transcription(monkeypatch):
    async def transcribe_and_change_owner(_audio):
        await session_manager.release_session(reason="staff_force_release")
        await session_manager.claim("replacement-owner")
        return "ไปจุด A"

    monkeypatch.setattr("app.runtime.stt_service.transcribe_audio", transcribe_and_change_owner)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/command/voice",
            headers={"X-Session-Id": "voice-owner"},
            files={"audio": ("sample.wav", io.BytesIO(b"audio"), "audio/wav")},
        )

    assert response.status_code == 403
    assert session_manager.identity.active_session_id == "replacement-owner"
    assert session_manager.requests.latest_request_identity is None


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
    from unittest.mock import Mock, AsyncMock
    import app.main as main_module

    async def transcribe(_audio):
        if transcript is None:
            raise STTUnavailableError("private provider detail")
        return transcript

    bridge = Mock()
    bridge.inspect_connections = AsyncMock(return_value={})
    bridge.robot_observation.return_value = {}
    monkeypatch.setattr(runtime, 'create_ros2_bridge', lambda *_args: bridge)
    monkeypatch.setattr(runtime.stt_service, "transcribe_audio", transcribe)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/command/voice",
            headers={"X-Session-Id": "empty-audio-user"},
            files={"audio": ("sample.wav", io.BytesIO(b"audio"), "audio/wav")},
        )

    assert response.status_code == status
    assert "private provider detail" not in response.text
    assert session_manager.requests.latest_request_identity is None
    bridge.publish_user_transcript.assert_not_called()


def test_smart_navigation_timer_pause():
    """Protocol 3: Watchdog pauses countdown during NAVIGATING/REPLANNING."""
    asyncio.run(session_manager.claim("dev-timer-test"))
    session_manager.display.robot_state = "IDLE"

    # Tick 1: IDLE countdown
    session_manager.identity.last_activity_ts = time.time() - 10
    state_idle = asyncio.run(session_manager.watchdog_tick())
    assert state_idle.timer_paused_for_navigation is False
    assert state_idle.inactivity_remaining_sec == 50

    # Set state to NAVIGATING -> timer should pause and remain at 60s
    session_manager.display.robot_state = "NAVIGATING"
    state_nav = asyncio.run(session_manager.watchdog_tick())
    assert state_nav.timer_paused_for_navigation is True
    assert state_nav.inactivity_remaining_sec == 60

    # Set state to REPLANNING -> still paused
    session_manager.display.robot_state = "REPLANNING"
    state_replan = asyncio.run(session_manager.watchdog_tick())
    assert state_replan.timer_paused_for_navigation is True
    assert state_replan.inactivity_remaining_sec == 60

    # Reached destination -> countdown resumes
    session_manager.display.robot_state = "REACHED"
    session_manager.identity.last_activity_ts = time.time() - 5
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
        session_manager.display.current_goal = "B"
        session_manager.display.robot_state = "REACHED"
        session_manager.auto_return_delay_sec = 1  # 1s for testing

        # Disconnect
        disc_res = client.post(
            "/api/v1/session/disconnect",
            headers={"X-Session-Token": token}
        )
        assert disc_res.status_code == 200
        assert disc_res.json()["auto_return_scheduled"] is True
        assert session_manager.identity.active_session_id is None

        # Wait for delayed auto-return task to trigger
        time.sleep(1.3)
        assert session_manager.display.current_goal == settings.START_BOOTH_ID == "D"


def test_disconnect_at_d_does_not_schedule_redundant_return():
    with TestClient(app) as client:
        claim = client.post("/api/v1/session/claim", json={"session_id": "at-d"})
        token = claim.json()["session_token"]
        session_manager.display.current_goal = "D"
        session_manager.display.robot_state = "REACHED"
        response = client.post(
            "/api/v1/session/disconnect", headers={"X-Session-Token": token}
        )
        assert response.status_code == 200
        assert response.json()["auto_return_scheduled"] is False


def test_staff_pin_security_and_emergency_stop():
    """Protocol 5: Staff PIN authentication & Emergency Stop behavior."""
    with TestClient(app) as client:
        config_before = {
            "auto_return_enabled": session_manager.auto_return_enabled,
            "inactivity_timeout_sec": session_manager.inactivity_timeout_sec,
            "auto_return_delay_sec": session_manager.auto_return_delay_sec,
        }
        assert client.get("/api/v1/staff/config").status_code == 401
        config_res = client.get(
            "/api/v1/staff/config",
            headers={"X-Staff-Pin": settings.STAFF_PIN}
        )
        assert config_res.status_code == 200
        assert config_res.json() == config_before
        assert "staff_pin" not in config_res.json()
        assert "session_token" not in config_res.json()
        assert {
            "auto_return_enabled": session_manager.auto_return_enabled,
            "inactivity_timeout_sec": session_manager.inactivity_timeout_sec,
            "auto_return_delay_sec": session_manager.auto_return_delay_sec,
        } == config_before

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
        assert session_manager.display.robot_state == "STOPPED"


def test_voice_upload_endpoint(monkeypatch):
    """Voice upload publishes an explicitly injected transcript."""
    async def transcribe(_audio):
        return "ไปจุด C"

    monkeypatch.setattr("app.runtime.stt_service.transcribe_audio", transcribe)
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
        assert "<title>Robot Rescue Mission | CSTU Open House</title>" in res_index.text
        assert 'class="visitor-page" data-theme="dark"' in res_index.text
        assert 'id="btn-theme-toggle"' in res_index.text
        assert 'id="view-available"' in res_index.text
        assert "เริ่มสั่งงานหุ่นยนต์" in res_index.text
        assert "แตะขอสิทธิ์ควบคุมก่อน เมื่อได้รับสิทธิ์แล้วจึงสั่งงานด้วยเสียงหรือข้อความได้" in res_index.text
        assert "กำลังเชื่อมต่อและรอสถานะล่าสุด" in res_index.text
        assert "หุ่นยนต์ได้ยินว่า:" in res_index.text

        res_staff = client.get("/staff")
        assert res_staff.status_code == 200
        assert "Staff Override Panel" in res_staff.text
        assert "กรุณาระบุรหัส PIN ของเจ้าหน้าที่" in res_staff.text

        for page in (res_index, res_staff):
            for asset_url in re.findall(r'(?:href|src)="(/static/[^"?#]+)', page.text):
                assert client.get(asset_url).status_code == 200, asset_url


@pytest.mark.parametrize("mode", ["text", "voice"])
def test_command_returns_token_for_disconnect_without_weakening_session_auth(monkeypatch, mode):
    """Auto-claimed commands return the token needed by heartbeat and disconnect."""
    from unittest.mock import AsyncMock
    from app import main as backend
    from app.models import CommandResponse, TextCommandRequest

    async def run():
        session_manager.auto_return_enabled = False
        monkeypatch.setattr(runtime, 'ros_bridge_instance', Mock())
        monkeypatch.setattr(runtime.stt_service, "transcribe_audio", AsyncMock(return_value="ไปจุด B"))
        if mode == "text":
            result = await commands.command_text(
                TextCommandRequest(text="ไปจุด B"),
                x_session_id="autoclaim-user", x_session_token=None,
            )
        else:
            result = await commands.command_voice(
                object(), x_session_id="autoclaim-user", x_session_token=None,
            )
        response = CommandResponse(**result)
        assert response.session_token == session_manager.identity.active_session_token
        assert response.request_id and response.session_id == "autoclaim-user"
        with pytest.raises(SessionError) as denied:
            await session_manager.validate_or_auto_claim("autoclaim-user", None)
        assert denied.value.status_code == 403
        with pytest.raises(HTTPException) as denied:
            await sessions.disconnect_session(x_session_token=None)
        assert denied.value.status_code == 403
        await sessions.heartbeat_session(x_session_token=response.session_token)
        result = await sessions.disconnect_session(x_session_token=response.session_token)
        assert result["status"] == "disconnected"
        assert session_manager.identity.active_session_id is None

    asyncio.run(run())
