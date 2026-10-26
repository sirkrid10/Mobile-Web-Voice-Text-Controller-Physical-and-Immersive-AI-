"""Cross-process-contract checks with local ROS nodes and fake inference."""

import asyncio
import json
import threading
import time

import pytest

rclpy = pytest.importorskip("rclpy")
pytest.importorskip("ai_interfaces")

from rclpy.executors import MultiThreadedExecutor
from rclpy.parameter import Parameter
from rclpy.node import Node
from ai_interfaces.msg import NavigationState, UserRequest

from agent_pkg.intent_node import IntentNode
from agent_pkg.subtitle_node import SubtitleNode
from agent_pkg.testing.mock_robot import MockRobot
from app import main as backend
from app.config import settings
from app.models import TextCommandRequest
from app.ros2_bridge import RealROS2Bridge
from app.session_manager import session_manager
from app.stt_service import STTUnavailableError


class FakeModel:
    def __init__(self):
        self.destinations = []
        self.hold_next = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def navigate_to(self, destination):
        self.destinations.append(destination)

    def complete(self, _prompt):
        if self.hold_next:
            self.hold_next = False
            self.entered.set()
            if not self.release.wait(timeout=8):
                raise TimeoutError("fake inference gate timed out")
            return json.dumps({"kind": "navigate", "destination": "C"})
        destination = self.destinations.pop(0)
        return json.dumps({"kind": "navigate", "destination": destination})

    def close(self):
        self.release.set()


class RosObserver(Node):
    def __init__(self):
        super().__init__("backend_integration_observer")
        self.requests = []
        self.navigation = []
        self.create_subscription(UserRequest, "/guide/user_request", self.requests.append, 10)
        self.create_subscription(NavigationState, "/robot/navigation_state", self.navigation.append, 10)


async def wait_for(predicate, *, timeout=8, description="condition"):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.025)
    raise AssertionError(f"timed out waiting for {description}")


def test_backend_intent_subtitle_and_mock_robot_integration(monkeypatch):
    asyncio.run(_run_integration(monkeypatch))


async def _run_integration(monkeypatch):
    owned_ros_context = not rclpy.ok()
    if owned_ros_context:
        rclpy.init()

    model = FakeModel()
    intent = IntentNode(model=model)
    subtitle = SubtitleNode(parameter_overrides=[
        Parameter("subtitle_max_ttl_sec", value=0.6),
    ])
    robot = MockRobot(parameter_overrides=[
        Parameter("trip_duration_sec", value=0.45),
    ])
    observer = RosObserver()
    external_executor = MultiThreadedExecutor(num_threads=4)
    for node in (intent, subtitle, robot, observer):
        external_executor.add_node(node)
    executor_thread = threading.Thread(target=external_executor.spin, daemon=True)

    previous_mock_setting = settings.USE_MOCK_ROS2
    settings.USE_MOCK_ROS2 = False
    session_manager._lock = asyncio.Lock()
    session_manager.active_session_id = None
    session_manager.active_session_token = None
    session_manager.latest_request_identity = None
    session_manager.latest_intent = None
    session_manager.latest_action = None
    session_manager.robot_state = "UNKNOWN"
    session_manager.current_goal = settings.START_BOOTH_ID
    session_manager.heard_text = ""
    session_manager.llm_explanation = ""
    session_manager.auto_return_enabled = True
    session_manager.auto_return_delay_sec = 1
    session_manager.auto_return_task = None
    session_manager.set_broadcast_callback(None)

    loop = asyncio.get_running_loop()
    bridge = RealROS2Bridge(session_manager, loop)
    backend.ros_bridge_instance = bridge
    session_manager.set_ros_bridge(bridge)
    executor_thread.start()

    async def submit_text(text, destination, input_mode="chip"):
        model.navigate_to(destination)
        response = await backend.command_text(
            TextCommandRequest(text=text, input_mode=input_mode),
            x_session_id="integration-visitor",
            x_session_token=session_manager.active_session_token,
        )
        request_id = response["request_id"]
        await wait_for(
            lambda: any(
                request.request_id == request_id
                and request.session_id == "integration-visitor"
                and request.text == text
                for request in observer.requests
            ),
            description=f"UserRequest {request_id}",
        )
        await wait_for(
            lambda: session_manager.latest_intent is not None
            and session_manager.latest_intent.request_id == request_id,
            description=f"IntentResult {request_id}",
        )
        return response

    try:
        await wait_for(lambda: session_manager.robot_state == "IDLE", description="Robot READY readiness")

        for text, destination, input_mode in (
            ("ไปจุด A", "A", "text"),
            ("พาไปจุด บี", "B", "chip"),
            ("ไปจุด C", "C", "chip"),
            ("กลับ start", "A", "chip"),
            ("ไปจุด B อีกครั้ง", "B", "text"),
        ):
            response = await submit_text(text, destination, input_mode)
            outcome = session_manager.latest_intent
            assert outcome.status == "NAVIGATE"
            assert outcome.destination_id == destination
            assert outcome.session_id == response["session_id"]
            assert outcome.request_id == response["request_id"]
            await wait_for(
                lambda: session_manager.current_goal == destination
                and session_manager.robot_state == "REACHED",
                description=f"Robot arrival at {destination}",
            )
            await wait_for(
                lambda: intent.controller._active is None,
                description=f"terminal Action result for {destination}",
            )
            await wait_for(
                intent.controller._robot_ready,
                description=f"new Robot readiness heartbeat after {destination}",
            )

        # Auto-return uses the same A/B/C Action contract, targeting A.
        assert await session_manager.release_session(reason="user_disconnect")
        await wait_for(
            lambda: session_manager.latest_action is not None
            and session_manager.latest_action.source == "auto_return"
            and session_manager.latest_action.destination_id == "A",
            description="auto-return direct A Action",
        )
        await wait_for(
            lambda: session_manager.current_goal == "A" and session_manager.robot_state == "REACHED",
            description="auto-return ARRIVED at A",
        )

        claim = await session_manager.claim("integration-visitor")
        token = claim["session_token"]

        # Provider failure and empty audio leave the last registered request untouched.
        prior_identity = session_manager.latest_request_identity
        request_count = len(observer.requests)

        async def provider_error(_audio):
            raise STTUnavailableError("private provider detail")

        monkeypatch.setattr(backend.stt_service, "transcribe_audio", provider_error)
        with pytest.raises(backend.HTTPException) as failed:
            await backend.command_voice(
                _FakeUpload(), x_session_id="integration-visitor", x_session_token=token,
            )
        assert failed.value.status_code == 503
        assert "private provider detail" not in failed.value.detail

        async def empty_audio(_audio):
            return "  \n"

        monkeypatch.setattr(backend.stt_service, "transcribe_audio", empty_audio)
        with pytest.raises(backend.HTTPException) as empty:
            await backend.command_voice(
                _FakeUpload(), x_session_id="integration-visitor", x_session_token=token,
            )
        assert empty.value.status_code == 422
        assert session_manager.latest_request_identity == prior_identity
        await asyncio.sleep(0.15)
        assert len(observer.requests) == request_count

        # Hold inference, make the Robot busy with a staff Action, then release it.
        model.hold_next = True
        response = await backend.command_text(
            TextCommandRequest(text="hold-model then go C", input_mode="text"),
            x_session_id="integration-visitor",
            x_session_token=token,
        )
        visitor_request_id = response["request_id"]
        await wait_for(lambda: model.entered.is_set(), description="fake model entering held inference")
        await session_manager.return_to_start_now()
        staff_action_id = session_manager.latest_action.request_id
        assert session_manager.latest_action.source == "staff_override"
        assert session_manager.latest_action.destination_id == "A"
        await wait_for(
            lambda: session_manager.robot_state == "NAVIGATING",
            description="staff Return Home Robot motion",
        )
        model.release.set()

        await wait_for(
            lambda: session_manager.latest_intent is not None
            and session_manager.latest_intent.request_id == visitor_request_id,
            description="busy result for held request",
        )
        busy = session_manager.latest_intent
        assert busy.status == "FAILED"
        assert busy.error_code == "robot_busy"
        assert busy.request_id == visitor_request_id
        assert busy.request_id != staff_action_id
        assert busy.session_id == "integration-visitor"
        assert session_manager.latest_action.request_id == staff_action_id
        assert session_manager.latest_action.destination_id == "A"
        assert visitor_request_id not in {
            state.request_id for state in observer.navigation
        }
        await wait_for(
            lambda: "หุ่นยังไม่ว่าง" in session_manager.llm_explanation,
            description="busy Subtitle through SubtitleNode to thought",
        )
        await wait_for(
            lambda: "หุ่นยังไม่ว่าง" not in session_manager.llm_explanation,
            timeout=2,
            description="busy subtitle expires without replaying consumed navigation",
        )
        await wait_for(
            lambda: session_manager.current_goal == "A" and session_manager.robot_state == "REACHED",
            description="staff return ARRIVED at A",
        )

        # A successful voice transcript follows the same UserRequest and Action flow.
        async def fake_voice(_audio):
            return "ช่วยพาไปจุด C"

        monkeypatch.setattr(backend.stt_service, "transcribe_audio", fake_voice)
        model.navigate_to("C")
        voice_response = await backend.command_voice(
            _FakeUpload(), x_session_id="integration-visitor", x_session_token=token,
        )
        await wait_for(
            lambda: any(request.request_id == voice_response["request_id"] for request in observer.requests),
            description="voice UserRequest publication",
        )
        await wait_for(
            lambda: session_manager.latest_intent is not None
            and session_manager.latest_intent.request_id == voice_response["request_id"],
            description="voice IntentResult",
        )
        voice_result = session_manager.latest_intent
        assert voice_result.status == "NAVIGATE"
        assert voice_result.destination_id == "C"
        assert voice_result.session_id == voice_response["session_id"]
        assert session_manager.latest_action.request_id == staff_action_id
        assert session_manager.latest_action.source == "staff_override"
        await wait_for(
            lambda: session_manager.current_goal == "C" and session_manager.robot_state == "REACHED",
            description="voice navigation arrival at C",
        )
    finally:
        model.release.set()
        settings.USE_MOCK_ROS2 = previous_mock_setting
        session_manager.auto_return_enabled = False
        if session_manager.auto_return_task and not session_manager.auto_return_task.done():
            session_manager.auto_return_task.cancel()
        if session_manager.active_session_id is not None:
            await session_manager.release_session(reason="staff_force_release")
        external_executor.shutdown(timeout_sec=1)
        executor_thread.join(timeout=1)
        intent.close()
        robot.close()
        observer.destroy_node()
        subtitle.destroy_node()
        robot.destroy_node()
        intent.destroy_node()
        bridge.shutdown()
        backend.ros_bridge_instance = None
        session_manager.set_ros_bridge(None)
        session_manager._lock = asyncio.Lock()
        session_manager.active_session_id = None
        session_manager.active_session_token = None
        session_manager.latest_request_identity = None
        session_manager.latest_intent = None
        session_manager.latest_action = None
        session_manager.robot_state = "IDLE"
        session_manager.current_goal = settings.START_BOOTH_ID
        session_manager.heard_text = ""
        session_manager.llm_explanation = ""


class _FakeUpload:
    content_type = "audio/wav"
    filename = "mock.wav"

    async def read(self):
        return b"fake audio; no provider is called"
