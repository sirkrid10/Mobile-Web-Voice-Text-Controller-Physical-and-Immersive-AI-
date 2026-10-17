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
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.session_manager import session_manager


@pytest.fixture(autouse=True)
def reset_session_state():
    settings.USE_MOCK_ROS2 = True
    """Reset session manager state before each test."""
    asyncio.run(session_manager.release_session(reason="test_reset"))
    session_manager.robot_state = "IDLE"
    session_manager.current_goal = settings.START_BOOTH_ID
    session_manager.heard_text = ""
    session_manager.llm_explanation = "พร้อมรับคำสั่งจากผู้เข้าชมบูธ"
    session_manager.obstacle_detected = False
    session_manager.auto_return_enabled = True
    session_manager.auto_return_delay_sec = 1  # 1s for fast testing
    session_manager.inactivity_timeout_sec = 60
    if session_manager.auto_return_task and not session_manager.auto_return_task.done():
        session_manager.auto_return_task.cancel()


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
    """Protocol 2: Text/Chip commands and auto-claim if vacant (routes to booth_09)."""
    with TestClient(app) as client:
        # First command from visitor auto-claims session
        res = client.post(
            "/api/v1/command/text",
            headers={"X-Session-Id": "dev-visitor-1"},
            json={"text": "พาไปบูธคอมพิวเตอร์", "input_mode": "text"}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "sent"
        assert data["transcript"] == "พาไปบูธคอมพิวเตอร์"

        # Verify active session belongs to dev-visitor-1 and destination is booth_09
        state = session_manager.get_state_broadcast()
        assert state.active_session_id == "dev-visitor-1"
        assert state.current_goal == "booth_09"


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
        # Claim session and set destination to booth_09
        claim_res = client.post("/api/v1/session/claim", json={"session_id": "dev-return-user"})
        token = claim_res.json()["session_token"]

        # Navigate away from start
        session_manager.current_goal = "booth_09"
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


def test_voice_upload_endpoint():
    """Protocol 6: Voice audio upload & processing fallback."""
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
        assert "transcript" in data
        assert len(data["transcript"]) > 0


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


def test_disconnect_with_session_id_fallback():
    """Verify visitor can disconnect using X-Session-Id even if X-Session-Token was omitted/lost."""
    with TestClient(app) as client:
        # First send command (auto-claims)
        res_cmd = client.post(
            "/api/v1/command/text",
            headers={"X-Session-Id": "dev-autoclaim-user"},
            json={"text": "พาไปบูธคอมพิวเตอร์", "input_mode": "text"}
        )
        assert res_cmd.status_code == 200
        assert res_cmd.json()["session_token"] is not None
        assert session_manager.active_session_id == "dev-autoclaim-user"

        # Disconnect sending only X-Session-Id (no token)
        res_disc = client.post(
            "/api/v1/session/disconnect",
            headers={"X-Session-Id": "dev-autoclaim-user"}
        )
        assert res_disc.status_code == 200
        assert res_disc.json()["status"] == "disconnected"
        assert session_manager.active_session_id is None
